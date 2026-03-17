"""Unit tests for pyscanbox.calibration.pockels.

Tests cover:
- fit_pockels_curve: recovers known A and k from synthetic sin² data.
- generate_lut: correct shape, monotonicity, boundary values.
- save_calibration / load_calibration: round-trip JSON consistency.
- calibration_path: path construction alongside a config file.
"""

import json
import os
import tempfile

import numpy as np
import pytest

from pyscanbox.calibration import pockels as pockels_cal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _synthetic_data(amplitude=1200.0, frequency=1.1, max_voltage=2.040, n=20,
                    noise_std=0.0):
    """Generate synthetic (dac_levels, powers) following P = A·sin(V·k)²."""
    # Choose DAC levels spanning 0 to ~first maximum of sin².
    # First maximum at V = π/(2k) -> DAC = 255 * π/(2k*max_voltage).
    v_at_max = np.pi / (2.0 * frequency)
    dac_at_max = int(min(240, round(v_at_max / max_voltage * 255)))
    dac_levels = np.linspace(0, dac_at_max, n)
    voltages = dac_levels / 255.0 * max_voltage
    powers = amplitude * np.sin(voltages * frequency) ** 2
    if noise_std > 0.0:
        rng = np.random.default_rng(42)
        powers = powers + rng.normal(0, noise_std, size=powers.shape)
        powers = np.clip(powers, 0.0, None)
    return dac_levels, powers


# ---------------------------------------------------------------------------
# fit_pockels_curve
# ---------------------------------------------------------------------------

class TestFitPockcelsCurve:

    def test_recovers_amplitude_and_frequency(self):
        """Fit to noise-free synthetic data must recover A and k closely."""
        A_true = 1500.0
        k_true = 1.05
        dac, pwr = _synthetic_data(amplitude=A_true, frequency=k_true)
        A_fit, k_fit, r_sq = pockels_cal.fit_pockels_curve(dac, pwr)
        assert abs(A_fit - A_true) / A_true < 0.01, (
            f'Amplitude mismatch: got {A_fit:.1f}, expected {A_true:.1f}'
        )
        assert abs(k_fit - k_true) / k_true < 0.01, (
            f'Frequency mismatch: got {k_fit:.4f}, expected {k_true:.4f}'
        )
        assert r_sq > 0.999, f'R² too low: {r_sq}'

    def test_r_squared_near_one_noise_free(self):
        dac, pwr = _synthetic_data()
        _, _, r_sq = pockels_cal.fit_pockels_curve(dac, pwr)
        assert r_sq > 0.999

    def test_r_squared_acceptable_with_noise(self):
        dac, pwr = _synthetic_data(noise_std=5.0)
        _, _, r_sq = pockels_cal.fit_pockels_curve(dac, pwr)
        assert r_sq > 0.98

    def test_raises_on_too_few_points(self):
        with pytest.raises(ValueError, match='4'):
            pockels_cal.fit_pockels_curve(
                np.array([0.0, 50.0, 100.0]),
                np.array([0.0, 500.0, 1000.0]),
            )

    def test_custom_max_voltage(self):
        """Fit with a non-default max_voltage should still converge."""
        max_v = 1.5
        dac, pwr = _synthetic_data(frequency=1.4, max_voltage=max_v)
        A_fit, k_fit, r_sq = pockels_cal.fit_pockels_curve(dac, pwr, max_voltage=max_v)
        assert r_sq > 0.999


# ---------------------------------------------------------------------------
# generate_lut
# ---------------------------------------------------------------------------

class TestGenerateLut:

    def test_length(self):
        lut = pockels_cal.generate_lut(1200.0, 1.1)
        assert len(lut) == pockels_cal.LUT_SIZE

    def test_first_entry_zero(self):
        lut = pockels_cal.generate_lut(1200.0, 1.1)
        assert lut[0] == 0, f'LUT[0] should be 0, got {lut[0]}'

    def test_entries_in_range(self):
        lut = pockels_cal.generate_lut(1200.0, 1.1)
        assert all(0 <= v <= 255 for v in lut), 'LUT contains out-of-range values'

    def test_monotonically_non_decreasing(self):
        lut = pockels_cal.generate_lut(1200.0, 1.1)
        diffs = np.diff(lut)
        assert np.all(diffs >= 0), 'LUT is not monotonically non-decreasing'

    def test_amplitude_does_not_affect_lut(self):
        """Two different amplitudes with the same k must produce the same LUT."""
        lut_a = pockels_cal.generate_lut(500.0, 1.1)
        lut_b = pockels_cal.generate_lut(2000.0, 1.1)
        assert lut_a == lut_b, 'LUT should not depend on amplitude'

    def test_higher_frequency_gives_lower_max_dac(self):
        """Higher k means the first sin² maximum is at lower voltage → lower max LUT value."""
        lut_lo = pockels_cal.generate_lut(1200.0, frequency=0.8)
        lut_hi = pockels_cal.generate_lut(1200.0, frequency=1.5)
        assert lut_hi[-1] < lut_lo[-1], (
            'Higher frequency should give smaller max DAC in LUT'
        )

    def test_round_trip_linearizes_power(self):
        """LUT[i] → DAC value that produces power proportional to i/255.

        At very low indices (idx ≤ 4) integer rounding of the 8-bit DAC
        creates a larger relative error; tolerance is relaxed there.
        """
        A, k = 1200.0, 1.1
        max_v = pockels_cal.DEFAULT_MAX_VOLTAGE
        lut = pockels_cal.generate_lut(A, k, max_v)
        # Check a few representative indices.
        for idx in [1, 32, 64, 128, 192, 254]:
            dac_val = lut[idx]
            voltage = dac_val / 255.0 * max_v
            power = A * np.sin(voltage * k) ** 2
            expected_power = A * idx / 255.0
            # Tolerance: very low indices suffer more from integer DAC rounding.
            tol = 0.06 if idx <= 4 else 0.03
            rel_err = abs(power - expected_power) / (expected_power + 1e-9)
            assert rel_err < tol, (
                f'LUT linearization error at idx {idx}: '
                f'got {power:.2f} mW, expected {expected_power:.2f} mW '
                f'(rel_err={rel_err:.4f})'
            )


# ---------------------------------------------------------------------------
# save_calibration / load_calibration
# ---------------------------------------------------------------------------

class TestSaveLoadCalibration:

    def test_round_trip(self):
        lut = pockels_cal.generate_lut(1200.0, 1.1)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'pockels_cal.json')
            pockels_cal.save_calibration(path, lut, 1200.0, 1.1, note='test')
            loaded = pockels_cal.load_calibration(path)
        assert loaded is not None
        assert loaded['lut'] == lut
        assert abs(loaded['amplitude'] - 1200.0) < 1e-9
        assert abs(loaded['frequency'] - 1.1) < 1e-9
        assert loaded['note'] == 'test'

    def test_lut_entries_are_integers(self):
        lut = pockels_cal.generate_lut(1200.0, 1.1)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'cal.json')
            pockels_cal.save_calibration(path, lut, 1200.0, 1.1)
            loaded = pockels_cal.load_calibration(path)
        assert all(isinstance(v, int) for v in loaded['lut'])

    def test_load_missing_file_returns_none(self):
        result = pockels_cal.load_calibration('/nonexistent/path/pockels_cal.json')
        assert result is None

    def test_load_corrupt_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'bad.json')
            with open(path, 'w') as fh:
                fh.write('not valid json {{{')
            result = pockels_cal.load_calibration(path)
        assert result is None

    def test_load_wrong_lut_length_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'bad.json')
            with open(path, 'w') as fh:
                json.dump({'lut': [0] * 128}, fh)
            result = pockels_cal.load_calibration(path)
        assert result is None

    def test_custom_max_voltage_preserved(self):
        lut = pockels_cal.generate_lut(800.0, 1.4, max_voltage=1.5)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'cal.json')
            pockels_cal.save_calibration(path, lut, 800.0, 1.4, max_voltage=1.5)
            loaded = pockels_cal.load_calibration(path)
        assert abs(loaded['max_voltage'] - 1.5) < 1e-9


# ---------------------------------------------------------------------------
# calibration_path
# ---------------------------------------------------------------------------

class TestCalibrationPath:

    def test_returns_json_alongside_config(self):
        path = pockels_cal.calibration_path('/some/dir/config.yaml')
        assert os.path.dirname(path) == '/some/dir'
        assert os.path.basename(path) == 'pockels_cal.json'

    def test_works_with_relative_config_path(self):
        path = pockels_cal.calibration_path('config.yaml')
        assert path.endswith('pockels_cal.json')
