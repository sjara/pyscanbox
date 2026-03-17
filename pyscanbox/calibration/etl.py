"""ETL (Electrically Tunable Lens) calibration utilities.

Provides functions to load, save, and apply a quadratic polynomial
calibration that converts ETL current values to focal depth in microns.

The calibration is derived by imaging a reference sample (e.g., pollen
grains) through a sweep of ETL current values, computing depth via
cross-correlation phase analysis (see sbxoptotunecalibration.m in the
original Scanbox codebase), then fitting a degree-2 polynomial::

    otcoeff = polyfit(oval, -depth, 2)

where ``oval`` is the sequence of ETL current values and ``depth`` is
the measured axial displacement in microns.  The coefficients are stored
as a 3-element list ``[a, b, c]`` (highest degree first, matching NumPy
and MATLAB polyfit/polyval convention) in a JSON file.

Calibration file format (JSON)::

    {
        "coeffs": [a, b, c],
        "date": "YYYY-MM-DD",
        "note": "optional free-text note"
    }

**Phase-based depth measurement:**

During calibration, pollen grains (or another sample with fine z-structure)
are imaged at N different ETL current values (the calibration sweep).
For each ETL value i, the cross-correlation ``xc[k]`` between frame i
(shifted by k lines) and the reference frame (i=0) is computed.  Because
the sample has periodic z-structure, this cross-correlation oscillates
sinusoidally as k increases — completing roughly one full cycle over the
scan depth.

The mean phase of that oscillation is extracted using the first Fourier
component (equivalent to fitting a phasor to the cross-correlation)::

    theta = linspace(0, 2*pi, n_frames)
    phase_i = angle(sum(exp(1j * theta) * xc))

Unwrapping the phases across the full ETL sweep gives a monotonically
increasing depth signal.  Fitting a quadratic polynomial to
``(oval, -depth)`` produces the three calibration coefficients stored
in ``etl_cal.json``.

The key insight is that you do not need to know the exact z-period of
the sample: the phase encodes depth *within* one period, and ``unwrap``
removes the modulo ambiguity to give a monotonic total depth estimate.

Reference:
    sbxoptotunecalibration.m (original MATLAB calibration procedure)
    scanbox.m lines 87-95 (calibration loading and LUT computation)
"""

import datetime
import json
import logging
import os
from typing import Optional

import numpy as np


logger = logging.getLogger(__name__)

# Default calibration filename, resolved relative to the working directory.
# Matches the MATLAB convention (otcal.mat stored in the Scanbox core/ dir).
DEFAULT_CALIBRATION_FILE = 'etl_cal.json'


def load_calibration(path: str) -> Optional[np.ndarray]:
    """Load ETL calibration coefficients from a JSON file.

    Args:
        path: Path to the JSON calibration file.  Relative paths are
            resolved from the current working directory.

    Returns:
        NumPy array of 3 polynomial coefficients ``[a, b, c]``
        (degree 2, highest first), or ``None`` if the file does not
        exist or cannot be parsed.
    """
    if not os.path.exists(path):
        logger.debug("ETL calibration file not found: %s", path)
        return None
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        coeffs = np.asarray(data['coeffs'], dtype=float)
        if coeffs.shape != (3,):
            raise ValueError(
                f'Expected 3 coefficients, got shape {coeffs.shape}'
            )
        logger.info("ETL calibration loaded from %s", path)
        return coeffs
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "Could not load ETL calibration from %s: %s", path, exc
        )
        return None


def save_calibration(
    path: str,
    coeffs: np.ndarray,
    note: str = '',
) -> None:
    """Save ETL calibration coefficients to a JSON file.

    Args:
        path: Destination file path.  Parent directories are created if
            they do not exist.
        coeffs: Array of 3 polynomial coefficients ``[a, b, c]``
            (degree 2, highest first) from
            ``numpy.polyfit(etl_values, -depth_um, 2)``.
        note: Optional free-text note stored alongside the coefficients
            (e.g., objective used, sample type, date of procedure).

    Raises:
        ValueError: If ``coeffs`` does not have exactly 3 elements.
    """
    coeffs = np.asarray(coeffs, dtype=float)
    if coeffs.shape != (3,):
        raise ValueError(f'Expected 3 coefficients, got shape {coeffs.shape}')
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    data = {
        'coeffs': coeffs.tolist(),
        'date': datetime.date.today().isoformat(),
        'note': note,
    }
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2)
    logger.info("ETL calibration saved to %s", path)


def etl_to_depth(
    current: int,
    coeffs: Optional[np.ndarray],
) -> Optional[int]:
    """Convert an ETL current value to focal depth in microns.

    Evaluates the quadratic polynomial from the calibration procedure::

        depth_um = int(numpy.polyval(coeffs, current))

    This mirrors the MATLAB slider display callback in scanbox.m::

        floor(polyval(sbconfig.optocal, hObject.Value))

    Args:
        current: ETL current level (0–1760 hardware units).
        coeffs: Calibration coefficients ``[a, b, c]`` as returned by
            :func:`load_calibration`, or ``None`` if uncalibrated.

    Returns:
        Depth in microns as an ``int``, or ``None`` if ``coeffs`` is
        ``None`` (uncalibrated).
    """
    if coeffs is None:
        return None
    return int(np.polyval(coeffs, current))
