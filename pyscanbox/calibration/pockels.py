"""Pockels cell linearisation LUT calibration.

Provides functions to fit the sinusoidal voltage-to-power response of the
Pockels cell, invert it to a 256-entry linearisation lookup table (LUT), and
persist the result as a JSON file alongside the active configuration.

Physics
-------
The Pockels cell modulates laser power via the electro-optic effect.  With a
crossed-polariser arrangement the transmitted power follows::

    P = A * sin(V * k) ** 2

where V is the PSoC5 DAC output voltage (Volts), A is the maximum achievable
power, and k (rad/V) is determined by the cell, the laser wavelength, and the
optical alignment.

The PSoC5 DAC has a fixed full-scale of ``DEFAULT_MAX_VOLTAGE`` (2.040 V).
DAC value 255 maps to this voltage.

Calibration procedure
---------------------
1. Step the Pockels DAC level through ~20 values covering 0 to the first
   maximum of the sin² curve (typically 0–200 for a 920 nm beam).
2. Measure the output laser power with a calibrated power meter at each step.
3. Call :func:`fit_pockels_curve` to obtain the model parameters A and k.
4. Call :func:`generate_lut` to invert the fit and produce the 256-entry LUT.
5. Upload the LUT to the PSoC5 via
   :meth:`~pyscanbox.hardware.controller.ScanboxController.set_pockels_lut`.
6. Call :func:`save_calibration` to persist the result as ``pockels_cal.json``
   alongside the active YAML config.

The LUT maps each power-level index (0–255, linear in power) to the DAC value
(0–255) required to produce that power, compensating the sin² non-linearity so
the GUI slider produces perceptually uniform changes in laser intensity.

Calibration file format (JSON)::

    {
        "lut":        [0, 5, 10, ...],   // 256-entry list, int 0-255
        "amplitude":  1480.5,            // A in mW (or whatever meter units)
        "frequency":  1.023,             // k in rad/V
        "max_voltage": 2.040,            // PSoC DAC full scale (V)
        "date":       "2026-03-17",
        "note":       "920 nm, 60x objective"
    }

Reference
---------
core/pockels_920nm.m — original MATLAB calibration script (Scanbox).
core/scanbox.m lines 262–275 — LUT upload at startup.
sb/sb_pockels_lut.m — serial packet format for one LUT entry.
"""

import datetime
import json
import logging
import os
from typing import Optional, Tuple

import numpy as np
import scipy.optimize


logger = logging.getLogger(__name__)

#: Number of entries in the Pockels cell linearisation LUT (matches PSoC5).
LUT_SIZE = 256

#: Default calibration filename, placed alongside the active YAML config.
DEFAULT_CALIBRATION_FILE = 'pockels_cal.json'

#: PSoC5 DAC full-scale output voltage in Volts.
#: DAC value 255 maps to this voltage.  This is the hardware constant used
#: in the original MATLAB script (``lut = round(256*Vint/2.040)``).  Change
#: only if the PSoC5 DAC reference or hardware changes.
DEFAULT_MAX_VOLTAGE = 2.040


def calibration_path(config_path: str) -> str:
    """Return the Pockels calibration file path alongside *config_path*.

    Args:
        config_path: Absolute or relative path to the active YAML config file.

    Returns:
        Path to ``pockels_cal.json`` in the same directory as the config.
    """
    return os.path.join(
        os.path.dirname(os.path.abspath(config_path)),
        DEFAULT_CALIBRATION_FILE,
    )


def _pockels_model(voltage: np.ndarray, amplitude: float, frequency: float) -> np.ndarray:
    """Pockels cell sin² power model: P = A · sin(V · k)².

    Args:
        voltage: Array of DAC output voltages (Volts).
        amplitude: Maximum achievable power A (any consistent unit).
        frequency: Frequency parameter k (rad/V).

    Returns:
        Predicted power array (same units as ``amplitude``).
    """
    return amplitude * np.sin(voltage * frequency) ** 2


def fit_pockels_curve(
    dac_levels: np.ndarray,
    powers: np.ndarray,
    max_voltage: float = DEFAULT_MAX_VOLTAGE,
) -> Tuple[float, float, float]:
    """Fit the Pockels cell sin² curve to (DAC level, power) measurements.

    Converts DAC levels to voltages using::

        V = dac_level / 255 * max_voltage

    then fits ``P = A · sin(V · k)²`` via non-linear least squares
    (scipy.optimize.curve_fit).  Bounds are enforced so that A > 0 and k > 0,
    which ensures physically meaningful parameters.

    Args:
        dac_levels: 1-D array of DAC values (0–255) at which power was
            measured.  Must have at least 4 elements.
        powers: 1-D array of measured laser power values in any consistent
            unit (e.g. mW).  Must be the same length as ``dac_levels``.
        max_voltage: PSoC5 DAC full-scale voltage (Volts).
            DAC value 255 corresponds to this voltage.
            Default is 2.040 V (hardware constant from pockels_920nm.m).

    Returns:
        Tuple ``(amplitude, frequency, r_squared)`` where:

        * ``amplitude`` — maximum achievable power A (same units as *powers*).
        * ``frequency`` — frequency parameter k (rad/V).
        * ``r_squared`` — coefficient of determination R² of the fit.

    Raises:
        ValueError: If fewer than 4 data points are given.
        RuntimeError: If scipy.optimize.curve_fit fails to converge.
    """
    dac_levels = np.asarray(dac_levels, dtype=float)
    powers = np.asarray(powers, dtype=float)
    if len(dac_levels) < 4:
        raise ValueError(
            f'Need at least 4 measurements to fit, got {len(dac_levels)}.'
        )

    voltages = dac_levels / 255.0 * max_voltage

    # Initial guess: A = max observed power, k derived from the DAC level at
    # which the maximum occurs (first sin² peak at V = π / (2k)).
    a0 = float(np.max(powers))
    idx_max = int(np.argmax(powers))
    v_at_max = voltages[idx_max]
    # Protect against v_at_max = 0 (maximum at first measurement point).
    if v_at_max <= 0.0:
        v_at_max = max_voltage / 2.0
    k0 = np.pi / (2.0 * v_at_max)

    popt, _ = scipy.optimize.curve_fit(
        _pockels_model,
        voltages,
        powers,
        p0=[a0, k0],
        bounds=([0.0, 0.0], [np.inf, np.inf]),
        maxfev=20000,
    )
    amplitude, frequency = float(popt[0]), float(popt[1])

    residuals = powers - _pockels_model(voltages, amplitude, frequency)
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((powers - float(np.mean(powers))) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else float('nan')

    return amplitude, frequency, r_squared


def generate_lut(
    amplitude: float,  # noqa: ARG001 — kept for API symmetry; not used in formula
    frequency: float,
    max_voltage: float = DEFAULT_MAX_VOLTAGE,
) -> list:
    """Generate the 256-entry linearisation LUT from fitted sin² parameters.

    The LUT maps each power-level index *i* (0–255, representing a linear
    fraction of maximum power) to the DAC value required to produce that
    power, inverting the Pockels cell sin² response::

        V[i]   = arcsin(sqrt(i / 255)) / frequency
        lut[i] = clip(round(256 · V[i] / max_voltage), 0, 255)

    This matches the MATLAB formula from ``core/pockels_920nm.m``::

        pint = linspace(0, pp(1), 256)           % pp(1) = A
        Vint = asin(sqrt(pint / pp(1))) / pp(2)  % pp(2) = k
        lut  = round(256 * Vint / 2.040)

    Note that ``amplitude`` (A) cancels in the formula (``pint/A = i/255``) and
    therefore does not affect the LUT shape — only ``frequency`` and
    ``max_voltage`` matter.

    Args:
        amplitude: Maximum achievable power A from :func:`fit_pockels_curve`.
            Accepted for API symmetry but not used in the computation.
        frequency: Frequency parameter k (rad/V) from :func:`fit_pockels_curve`.
        max_voltage: PSoC5 DAC full-scale voltage (Volts).  Default 2.040 V.

    Returns:
        256-element list of integers in the range 0–255.
    """
    indices = np.arange(LUT_SIZE, dtype=float)  # 0, 1, …, 255
    # arcsin(sqrt(0)) = 0, so index 0 gives V=0 and lut[0]=0 naturally.
    voltages = np.arcsin(np.sqrt(indices / float(LUT_SIZE - 1))) / frequency
    lut_float = 256.0 * voltages / max_voltage
    lut = np.clip(np.round(lut_float), 0, 255).astype(int)
    return lut.tolist()


def save_calibration(
    path: str,
    lut: list,
    amplitude: float,
    frequency: float,
    max_voltage: float = DEFAULT_MAX_VOLTAGE,
    date: Optional[str] = None,
    note: str = '',
) -> None:
    """Save a Pockels cell calibration to a JSON file.

    Args:
        path: Destination file path.  Parent directory must exist.
        lut: 256-entry linearisation LUT (integers 0–255).
        amplitude: Fitted maximum power A.
        frequency: Fitted frequency k (rad/V).
        max_voltage: PSoC5 DAC full-scale voltage used during calibration.
        date: ISO-8601 date string; defaults to today.
        note: Optional free-text comment (e.g. laser wavelength).

    Raises:
        OSError: If the file cannot be written.
    """
    if date is None:
        date = datetime.date.today().isoformat()
    data = {
        'lut': [int(v) for v in lut],
        'amplitude': float(amplitude),
        'frequency': float(frequency),
        'max_voltage': float(max_voltage),
        'date': date,
        'note': note,
    }
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2)
    logger.info('Pockels calibration saved to %s', path)


def load_calibration(path: str) -> Optional[dict]:
    """Load a Pockels cell calibration from a JSON file.

    Args:
        path: Path to the JSON calibration file.  Relative paths are
            resolved from the current working directory.

    Returns:
        Dictionary with keys ``lut``, ``amplitude``, ``frequency``,
        ``max_voltage``, ``date``, ``note``, or ``None`` if the file does
        not exist or contains invalid data.
    """
    if not os.path.exists(path):
        logger.debug('Pockels calibration file not found: %s', path)
        return None
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        lut = data.get('lut', [])
        if len(lut) != LUT_SIZE:
            raise ValueError(
                f'Expected {LUT_SIZE}-entry lut, got {len(lut)}.'
            )
        # Ensure integer values.
        data['lut'] = [int(v) for v in lut]
        logger.info('Pockels calibration loaded from %s', path)
        return data
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            'Could not load Pockels calibration from %s: %s', path, exc
        )
        return None
