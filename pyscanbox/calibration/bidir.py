"""Bidirectional scan calibration for two-photon resonant microscopy.

Measures and stores per-magnification pixel shift values that align forward
(even) and backward (odd) scan lines in bidirectional acquisition mode.

Due to a small timing offset in the resonant mirror controller, backward-sweep
lines are displaced horizontally relative to forward-sweep lines.  This offset
(bishift) is constant for a given microscope but varies with magnification
because higher zoom levels use a larger fraction of each resonant half-period,
amplifying any fixed timing delay into a larger apparent pixel shift.

**Calibration procedure:**

1. Switch to bidirectional mode and ensure bishift is 0 for the target
   magnification (call :meth:`AppController.set_bishift(0)`).
2. Image a sample with fine horizontal structure (fluorescent beads, pollen
   grains, or any sample with visible lateral features).
3. Use the rolling average (tau = 5 frames, matching the GUI display widget)
   to reduce noise — feed frames via :meth:`BidirCalibration.add_frame` until
   :attr:`BidirCalibration.is_converged` is True.
4. Call :meth:`BidirCalibration.calibrate_magnification` to compute the shift
   from the accumulated average, store it, and return the value.
5. Pass the returned value to :meth:`AppController.set_bishift` and call
   :meth:`BidirCalibration.save` to write ``bidir_cal.json``.

**Measurement algorithm:**

The mean column profile of even rows (forward sweeps) and odd rows (backward
sweeps) are extracted from the accumulated average frame.  Their cross-
correlation is computed via FFT; the lag at the peak is the measured bishift::

    even_profile = avg_frame[0::2, :].mean(axis=0)
    odd_profile  = avg_frame[1::2, :].mean(axis=0)
    xcorr = IFFT( FFT(even_profile) ⋅ conj(FFT(odd_profile)) )
    bishift = argmax(xcorr)   [signed, ±max_shift search range]

Zero-padding to 2× the signal length avoids circular-correlation artefacts.

**Sign convention:**

A positive ``bishift`` value shifts backward-scan samples toward higher
indices in ``reshape_pmt_data_bi`` (``s = lut_bi[px] + bishift``).  In the
backward sweep the resonant mirror moves right-to-left, so higher sample
indices correspond to positions further to the LEFT in the output image.
Therefore a positive bishift moves backward lines LEFT in the displayed frame.

If the cross-correlation peak is at lag ``+d``, the backward lines are shifted
``d`` pixels to the RIGHT.  Setting ``bishift = d`` compensates this.

⚠  Always verify the sign on real hardware and fine-tune with the GUI spinbox.
   In emulation mode the synthetic frames contain no real timing offset, so
   the measured shift will be near zero and calibration is not meaningful.

**Calibration file format (JSON):**

.. code-block:: json

    {
        "bishift": [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 0],
        "date": "2026-03-16",
        "note": "optional free-text note"
    }

The ``bishift`` list has 13 elements — one per magnification index (0 = lowest
zoom, 12 = highest zoom).  Missing or extra elements are handled gracefully.
"""

import datetime
import json
import logging
import math
import os

import numpy as np


logger = logging.getLogger(__name__)

NUM_MAGNIFICATIONS = 13

#: Default rolling-average time constant in frames, matching the first GUI
#: preset in :class:`~pyscanbox.gui.widgets.ImageDisplayControlGroup`.
DEFAULT_TAU = 5

#: Number of tau-multiples to accumulate before declaring convergence.
#: At tau=5 this means 25 frames (~1.6 s at 15 fps).
FRAMES_TO_CONVERGE = 5

CALIBRATION_FILENAME = 'bidir_cal.json'

#: Default maximum shift to search in :func:`measure_bishift` (pixels).
DEFAULT_MAX_SHIFT = 64


def calibration_path(config_path: str, filename: str | None = None) -> str:
    """Return the bidir calibration file path alongside *config_path*.

    Args:
        config_path: Absolute or relative path to the active YAML config file.
        filename: Optional filename override.  Defaults to
            ``CALIBRATION_FILENAME`` (``'bidir_cal.json'``).

    Returns:
        Path to ``bidir_cal.json`` (or *filename*) in the same directory as
        the config.
    """
    return os.path.join(
        os.path.dirname(os.path.abspath(config_path)),
        filename or CALIBRATION_FILENAME,
    )


def measure_bishift(frame: np.ndarray, max_shift: int = DEFAULT_MAX_SHIFT) -> int:
    """Measure horizontal pixel shift between forward and backward scan lines.

    Extracts the mean column profiles of even rows (forward sweeps) and odd
    rows (backward sweeps) then finds the lag at the peak of their cross-
    correlation.  Zero-padding to 2× avoids circular-correlation artefacts.

    The input should be an exponentially averaged frame captured in
    bidirectional mode with ``bishift = 0``, so any residual shift reflects
    the raw scanner timing offset.

    Args:
        frame: 2-D array of shape ``(lines, pixels)``, float or uint.
            Even rows are forward scan lines; odd rows are backward scan lines
            already placed left-to-right by ``reshape_pmt_data_bi``.
        max_shift: Maximum absolute pixel shift to search (pixels).
            Default 64 is sufficient for typical 796-pixel lines.

    Returns:
        Measured shift as a signed integer.  Positive means backward (odd)
        lines are shifted to the right relative to forward (even) lines.
        Pass this value directly to :meth:`AppController.set_bishift`.
    """
    img = np.asarray(frame, dtype=np.float64)
    even = img[0::2, :].mean(axis=0)
    odd  = img[1::2, :].mean(axis=0)
    even -= even.mean()
    odd  -= odd.mean()

    n = even.size
    # Zero-pad to 2n so lags in [-n, +n] are unambiguous.
    # conj(FFT(even)) * FFT(odd) → IFFT gives (even ⋆ odd)[k] = Σ even[m]·odd[m+k],
    # which peaks at k = +d when odd = roll(even, d) — the correct sign convention.
    F_even = np.fft.rfft(even, n=2 * n)
    F_odd  = np.fft.rfft(odd,  n=2 * n)
    xcorr  = np.fft.irfft(np.conj(F_even) * F_odd, n=2 * n)

    # Build search indices: positive lags [0 .. max_shift] at the front of
    # xcorr; negative lags [-max_shift .. -1] at the tail (2n - k → lag -k).
    pos_idx = np.arange(max_shift + 1, dtype=int)
    neg_idx = np.arange(2 * n - max_shift, 2 * n, dtype=int)
    search_idx = np.concatenate([pos_idx, neg_idx])

    peak = int(search_idx[np.argmax(xcorr[search_idx])])
    # Convert circular index to signed lag.
    if peak > n:
        peak = peak - 2 * n
    return peak


class BidirCalibration:
    """Bidirectional scan calibration: accumulates frames and measures bishift.

    Uses an exponential rolling average::

        avg = delta * avg + (1 - delta) * frame,   delta = exp(-1/tau)

    This formula matches :class:`~pyscanbox.gui.widgets.ImageDisplayWidget`
    so the calibration frame has the same noise reduction as the live display.

    After :attr:`frames_needed` frames have been fed via :meth:`add_frame`,
    call :meth:`calibrate_magnification` to compute and store the shift.
    Then call :meth:`save` to write the JSON file alongside the config.

    Args:
        config_path: Path to the active config YAML.  ``bidir_cal.json`` is
            written to the same directory.
        tau: Rolling-average time constant in frames.  Default 5 matches the
            first GUI rolling-average preset.
    """

    def __init__(self, config_path: str, tau: int = DEFAULT_TAU, filename: str | None = None) -> None:
        self._config_path = config_path
        self._calib_path  = calibration_path(config_path, filename)
        self._tau         = tau
        self._delta       = math.exp(-1.0 / max(tau, 1))
        self._avg: np.ndarray | None = None
        self._frame_count = 0
        self._shifts: list[int] = [0] * NUM_MAGNIFICATIONS
        self._load_from_disk()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def calib_path(self) -> str:
        """Absolute path to the JSON calibration file."""
        return self._calib_path

    @property
    def shifts(self) -> list[int]:
        """Copy of the 13-element per-magnification shift list."""
        return list(self._shifts)

    @property
    def frame_count(self) -> int:
        """Number of frames added since the last :meth:`reset`."""
        return self._frame_count

    @property
    def frames_needed(self) -> int:
        """Total frames required before the rolling average is converged."""
        return FRAMES_TO_CONVERGE * self._tau

    @property
    def is_converged(self) -> bool:
        """True once :attr:`frame_count` ≥ :attr:`frames_needed`."""
        return self._frame_count >= self.frames_needed

    # ------------------------------------------------------------------
    # Accumulation
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset the rolling average accumulator.

        Call before starting a new calibration run so the previous
        averaged frame does not bias the measurement.
        """
        self._avg = None
        self._frame_count = 0

    def add_frame(self, frame: np.ndarray) -> None:
        """Feed one frame into the rolling average accumulator.

        Args:
            frame: 2-D array of shape ``(lines, pixels)`` — pass a single
                channel extracted from the full ``(2, lines, pixels)``
                acquisition frame, e.g. ``frame[0]``.
        """
        f = np.asarray(frame, dtype=np.float32)
        if self._avg is None or self._avg.shape != f.shape:
            self._avg = f.copy()
        else:
            self._avg = self._delta * self._avg + (1.0 - self._delta) * f
        self._frame_count += 1

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def compute_shift(self) -> int:
        """Compute bishift from the current accumulated average.

        Returns:
            Measured shift in pixels.

        Raises:
            RuntimeError: If no frames have been accumulated.
        """
        if self._avg is None:
            raise RuntimeError(
                'No frames accumulated — call add_frame() before compute_shift().'
            )
        return measure_bishift(self._avg)

    def get_shift(self, mag_index: int) -> int:
        """Return the stored shift for *mag_index* (0 if not calibrated).

        Args:
            mag_index: Magnification index (0–12).
        """
        if 0 <= mag_index < NUM_MAGNIFICATIONS:
            return self._shifts[mag_index]
        return 0

    def set_shift(self, mag_index: int, shift: int) -> None:
        """Manually store *shift* for *mag_index* without measuring.

        Useful if a known-good value is available (e.g. copied from
        another config).

        Args:
            mag_index: Magnification index (0–12).
            shift: Pixel shift value.
        """
        if 0 <= mag_index < NUM_MAGNIFICATIONS:
            self._shifts[mag_index] = int(shift)

    def calibrate_magnification(self, mag_index: int) -> int:
        """Compute the bishift from accumulated frames and store it.

        Calls :meth:`compute_shift`, stores the result for *mag_index*,
        and returns it.  Call :meth:`save` afterwards to persist to disk.

        Args:
            mag_index: Magnification index (0–12) being calibrated.

        Returns:
            Measured shift in pixels.
        """
        shift = self.compute_shift()
        self.set_shift(mag_index, shift)
        logger.info(
            'Bidir calibration: mag_index=%d → bishift=%d', mag_index, shift
        )
        return shift

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, note: str = '') -> None:
        """Write the current calibration to ``bidir_cal.json``.

        The file is placed in the same directory as the config file used
        at construction time.

        Args:
            note: Optional free-text annotation stored in the JSON.
        """
        data: dict = {
            'bishift': list(self._shifts),
            'date': datetime.date.today().isoformat(),
        }
        if note:
            data['note'] = note
        os.makedirs(os.path.dirname(self._calib_path), exist_ok=True)
        with open(self._calib_path, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2)
        logger.info('Bidir calibration saved to %s', self._calib_path)

    def load(self) -> None:
        """Reload calibration from disk, overwriting any unsaved changes."""
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Internal: populate ``_shifts`` from ``bidir_cal.json`` if present."""
        if not os.path.exists(self._calib_path):
            logger.debug('No bidir calibration file at %s', self._calib_path)
            return
        try:
            with open(self._calib_path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            shifts = data.get('bishift', [])
            n = min(len(shifts), NUM_MAGNIFICATIONS)
            self._shifts[:n] = [int(s) for s in shifts[:n]]
            logger.info('Bidir calibration loaded from %s', self._calib_path)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                'Could not load bidir calibration from %s: %s',
                self._calib_path, exc,
            )
