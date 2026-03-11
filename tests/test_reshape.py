"""Tests for data reshaping functions.

Tests the high-speed Numba-optimized reshaping functions.
"""

import unittest
import numpy as np
from pyscanbox.acquisition import reshape


class TestReshape(unittest.TestCase):
    """Test cases for data reshaping functions."""

    def test_reshape_pmt_data_basic(self):
        """Test basic reshaping with known data."""
        lines = 2
        pixels = 4
        channels = 2
        
        # Create test buffer (interleaved)
        buffer = np.arange(lines * pixels * channels, dtype=np.uint16)
        
        # Shift left by 2 to simulate 14-bit data in upper bits
        buffer = buffer << 2
        
        # Reshape
        reshaped = reshape.reshape_pmt_data(buffer, lines, pixels)
        
        # Verify output shape
        self.assertEqual(reshaped.shape, (channels, lines, pixels))
        self.assertEqual(reshaped.dtype, np.uint16)

    def test_reshape_pmt_data_14bit_extraction(self):
        """Test that 14-bit data is correctly extracted."""
        # Create buffer with known pattern
        buffer = np.array([0xFFFC, 0xFFFC], dtype=np.uint16)  # All 14 bits set
        
        reshaped = reshape.reshape_pmt_data(buffer, 1, 1)
        
        # After shifting right by 2, should be 0x3FFF (14 bits)
        self.assertEqual(reshaped[0, 0, 0], 0x3FFF)
        self.assertEqual(reshaped[1, 0, 0], 0x3FFF)

    def test_extract_sync_bits(self):
        """Test sync bit extraction."""
        buffer = np.array([0b0000, 0b0001, 0b0010, 0b0011], dtype=np.uint16)
        
        sync = reshape.extract_sync_bits(buffer)
        
        self.assertEqual(sync[0], 0b00)
        self.assertEqual(sync[1], 0b01)
        self.assertEqual(sync[2], 0b10)
        self.assertEqual(sync[3], 0b11)

    def test_bit_shift_14_to_16(self):
        """Test bit shifting from 14-bit to 16-bit range."""
        data = np.array([0x3FFF, 0x2000, 0x0000], dtype=np.uint16)
        
        shifted = reshape.bit_shift_14_to_16(data)
        
        # 0x3FFF << 2 = 0xFFFC
        self.assertEqual(shifted[0], 0xFFFC)
        # 0x2000 << 2 = 0x8000
        self.assertEqual(shifted[1], 0x8000)
        # 0x0000 << 2 = 0x0000
        self.assertEqual(shifted[2], 0x0000)

    def test_validate_buffer_size(self):
        """Test buffer size validation."""
        lines = 512
        pixels = 796
        channels = 2
        
        # Correct size
        buffer = np.zeros(lines * pixels * channels, dtype=np.uint16)
        self.assertTrue(reshape.validate_buffer_size(buffer, lines, pixels, channels))
        
        # Wrong size
        buffer_wrong = np.zeros(100, dtype=np.uint16)
        self.assertFalse(reshape.validate_buffer_size(buffer_wrong, lines, pixels, channels))

    def test_reshape_for_display(self):
        """Test display preparation function."""
        # Create 2-channel data
        data = np.zeros((2, 10, 10), dtype=np.uint16)
        data[0, :, :] = 8000  # Channel 0
        data[1, :, :] = 8000  # Channel 1
        
        display = reshape.reshape_for_display(data)
        
        # Should be 2D
        self.assertEqual(display.ndim, 2)
        self.assertEqual(display.shape, (10, 10))
        # Should be uint8
        self.assertEqual(display.dtype, np.uint8)


class TestComputePixelLut(unittest.TestCase):
    """Tests for compute_pixel_lut()."""

    # Reference parameters matching the real Scanbox hardware.
    LASER_FREQ = 80_180_000   # Hz
    RES_FREQ   = 7_930        # Hz
    N_PIXELS   = 796

    def _get_lut(self):
        return reshape.compute_pixel_lut(self.N_PIXELS, self.LASER_FREQ, self.RES_FREQ)

    def test_output_shape(self):
        """LUT must have exactly one entry per pixel."""
        lut = self._get_lut()
        self.assertEqual(lut.shape, (self.N_PIXELS,))

    def test_output_dtype(self):
        """LUT entries must be int32 for Numba compatibility."""
        lut = self._get_lut()
        self.assertEqual(lut.dtype, np.int32)

    def test_values_in_valid_range(self):
        """All base sample indices plus 3 must fit within a 5000-sample line."""
        lut = self._get_lut()
        self.assertTrue(np.all(lut >= 0), "Negative base index found")
        self.assertTrue(np.all(lut + 3 < 5000), "Index+3 exceeds samples_per_line")

    def test_strictly_increasing(self):
        """Arccosine warp means raw indices must be monotonically non-decreasing."""
        lut = self._get_lut()
        self.assertTrue(np.all(np.diff(lut) >= 0), "LUT is not monotonically non-decreasing")

    def test_endpoints_excluded(self):
        """First and last LUT entries must be well inside the sample range
        (the arccosine endpoints at ±1 are excluded from the LUT)."""
        lut = self._get_lut()
        # First pixel should not map to sample 0 (excluded endpoint).
        self.assertGreater(int(lut[0]), 0)
        # Last pixel should not map to sample 4999 + offset ≥ 5000.
        self.assertLess(int(lut[-1]) + 3, 5000)

    def test_deterministic(self):
        """Two calls with the same parameters must return identical arrays."""
        lut1 = reshape.compute_pixel_lut(self.N_PIXELS, self.LASER_FREQ, self.RES_FREQ)
        lut2 = reshape.compute_pixel_lut(self.N_PIXELS, self.LASER_FREQ, self.RES_FREQ)
        np.testing.assert_array_equal(lut1, lut2)

    def test_small_example(self):
        """Basic smoke-test on a tiny LUT (10 pixels, 200 samples/line)."""
        lut = reshape.compute_pixel_lut(10, laser_freq=10_000, res_freq=50)
        self.assertEqual(lut.shape, (10,))
        self.assertTrue(np.all(lut >= 0))
        nsamp = round(10_000 / 50)   # = 200 samples per full period
        # postTriggerSamples ≈ nsamp/2 ≈ 100
        self.assertTrue(np.all(lut + 3 < nsamp // 2 + 10))


class TestReshapePmtDataRaw(unittest.TestCase):
    """Tests for reshape_pmt_data_raw()."""

    LASER_FREQ   = 80_180_000
    RES_FREQ     = 7_930
    N_PIXELS     = 796
    N_LINES      = 4         # small frame for fast tests
    SAMPLES_PER_LINE = 5000

    def _make_lut(self):
        return reshape.compute_pixel_lut(self.N_PIXELS, self.LASER_FREQ, self.RES_FREQ)

    def _make_zero_buffer(self):
        """All-zero buffer (DC = 0)."""
        return np.zeros(self.N_LINES * self.SAMPLES_PER_LINE * 2, dtype=np.uint16)

    def test_output_shape(self):
        """Output must be (2, lines, pixels)."""
        lut = self._make_lut()
        buf = self._make_zero_buffer()
        out = reshape.reshape_pmt_data_raw(buf, self.N_LINES, self.N_PIXELS, lut)
        self.assertEqual(out.shape, (2, self.N_LINES, self.N_PIXELS))

    def test_output_dtype(self):
        """Output dtype must be uint16."""
        lut = self._make_lut()
        buf = self._make_zero_buffer()
        out = reshape.reshape_pmt_data_raw(buf, self.N_LINES, self.N_PIXELS, lut)
        self.assertEqual(out.dtype, np.uint16)

    def test_zero_buffer_gives_zero_output(self):
        """All-zero input must give all-zero output."""
        lut = self._make_lut()
        buf = self._make_zero_buffer()
        out = reshape.reshape_pmt_data_raw(buf, self.N_LINES, self.N_PIXELS, lut)
        self.assertTrue(np.all(out == 0))

    def test_uniform_buffer_value(self):
        """Uniform non-zero buffer: each pixel should equal the original value
        (after the 4-sample average, which is exact for constant data)."""
        lut = self._make_lut()
        value_14bit = np.uint16(4096)   # 14-bit value
        # Wire format: value left-shifted by 2
        wire_val = np.uint16(value_14bit << np.uint16(2))
        buf = np.full(self.N_LINES * self.SAMPLES_PER_LINE * 2, wire_val, dtype=np.uint16)
        out = reshape.reshape_pmt_data_raw(buf, self.N_LINES, self.N_PIXELS, lut)
        # Each sample is wire_val; the 4-sample sum >> 2 = wire_val.
        # But reshape_pmt_data_raw does NOT strip the 2 LSBs — it averages
        # the raw wire values directly.  So expected = (4 * wire_val) >> 2 = wire_val.
        np.testing.assert_array_equal(out, wire_val)

    def test_known_pixel_average(self):
        """Set 4 raw samples for a specific pixel and verify the averaged output."""
        lut = self._make_lut()
        buf  = self._make_zero_buffer()
        px   = 100
        line = 2
        s    = int(lut[px])             # base raw sample index
        # samples_per_line * 2 bytes per sample * 2 channels interleaved
        line_start = line * self.SAMPLES_PER_LINE * 2

        # Set chA (even offsets) for the 4 neighbours to known values
        raw_vals_a = np.array([100, 200, 300, 400], dtype=np.uint32)
        for k, v in enumerate(raw_vals_a):
            buf[line_start + 2 * (s + k)] = np.uint16(v)

        out = reshape.reshape_pmt_data_raw(buf, self.N_LINES, self.N_PIXELS, lut)
        expected_a = np.uint16((raw_vals_a.sum()) >> 2)
        self.assertEqual(int(out[0, line, px]), int(expected_a))
        # chB should still be zero
        self.assertEqual(int(out[1, line, px]), 0)

    def test_channels_independent(self):
        """Channel A and B samples are decoded independently."""
        lut = self._make_lut()
        buf = self._make_zero_buffer()
        px = 50
        s  = int(lut[px])

        # Line 0, chA samples = 1000; line 0, chB samples = 500
        for k in range(4):
            buf[2 * (s + k)]     = np.uint16(1000)   # chA (even)
            buf[2 * (s + k) + 1] = np.uint16(500)    # chB (odd)

        out = reshape.reshape_pmt_data_raw(buf, self.N_LINES, self.N_PIXELS, lut)
        self.assertEqual(int(out[0, 0, px]), 1000)   # average of [1000,1000,1000,1000]
        self.assertEqual(int(out[1, 0, px]), 500)


class TestApplyBidirectionalCorrection(unittest.TestCase):
    """Tests for apply_bidirectional_correction()."""

    def _make_frame(self, lines: int = 4, pixels: int = 8,
                    channels: int = 2) -> np.ndarray:
        """Return a frame filled with sequential values for easy inspection."""
        frame = np.arange(channels * lines * pixels, dtype=np.uint16).reshape(
            channels, lines, pixels
        )
        return frame

    def test_output_shape_and_dtype(self):
        """Corrected frame must have the same shape and dtype as the input."""
        frame = self._make_frame()
        out = reshape.apply_bidirectional_correction(frame.copy(), pixel_shift=0)
        self.assertEqual(out.shape, frame.shape)
        self.assertEqual(out.dtype, np.uint16)

    def test_even_lines_unchanged_by_flip(self):
        """Forward (even) lines must not be modified."""
        frame = self._make_frame(lines=4, pixels=6)
        orig = frame.copy()
        reshape.apply_bidirectional_correction(frame, pixel_shift=0)
        np.testing.assert_array_equal(frame[:, 0, :], orig[:, 0, :])
        np.testing.assert_array_equal(frame[:, 2, :], orig[:, 2, :])

    def test_odd_lines_flipped(self):
        """Backward (odd) lines must be horizontally flipped."""
        pixels = 6
        frame = np.zeros((1, 4, pixels), dtype=np.uint16)
        # Set odd line 1 to a recognisable pattern [10, 20, 30, 40, 50, 60].
        frame[0, 1, :] = np.arange(10, pixels * 10 + 1, 10, dtype=np.uint16)
        orig_line1 = frame[0, 1, :].copy()

        reshape.apply_bidirectional_correction(frame, pixel_shift=0)

        expected = orig_line1[::-1]
        np.testing.assert_array_equal(frame[0, 1, :], expected)

    def test_zero_shift_only_flips(self):
        """With pixel_shift=0 only the flip is applied; no roll artefacts."""
        frame = self._make_frame(lines=6, pixels=8)
        orig = frame.copy()
        reshape.apply_bidirectional_correction(frame, pixel_shift=0)

        # Even lines must be untouched.
        for ln in (0, 2, 4):
            np.testing.assert_array_equal(frame[:, ln, :], orig[:, ln, :])

        # Odd lines must be flipped and only flipped.
        for ln in (1, 3, 5):
            np.testing.assert_array_equal(
                frame[:, ln, :], orig[:, ln, ::-1]
            )

    def test_positive_shift_rolls_right(self):
        """pixel_shift > 0 shifts backward lines to the right; leading edge zeroed."""
        pixels = 8
        shift = 2
        frame = np.zeros((1, 4, pixels), dtype=np.uint16)
        # Line 1 after flip would be [60, 50, 40, 30, 20, 10, 0, 0] (if original
        # was [0, 0, 10, 20, 30, 40, 50, 60]).  But we want to verify the roll
        # independently of the flip, so we set up the frame *after* what the flip
        # would produce and check only the shift step.
        # Use a simpler known pattern: all ones in line 1.
        frame[0, 1, :] = 1
        reshape.apply_bidirectional_correction(frame, pixel_shift=shift)
        # First `shift` pixels of the backward line must be 0 (zeroed wrap-around).
        self.assertTrue(np.all(frame[0, 1, :shift] == 0))
        # Remaining pixels must still be non-zero (not zeroed by the shift).
        self.assertTrue(np.all(frame[0, 1, shift:] == 1))

    def test_negative_shift_rolls_left(self):
        """pixel_shift < 0 shifts backward lines to the left; trailing edge zeroed."""
        pixels = 8
        shift = -3
        frame = np.zeros((1, 4, pixels), dtype=np.uint16)
        frame[0, 1, :] = 1
        reshape.apply_bidirectional_correction(frame, pixel_shift=shift)
        # Last |shift| pixels must be zeroed.
        self.assertTrue(np.all(frame[0, 1, shift:] == 0))
        # Leading pixels must still be non-zero.
        self.assertTrue(np.all(frame[0, 1, :pixels + shift] == 1))

    def test_returns_same_array(self):
        """Function must return the same object (in-place modification)."""
        frame = self._make_frame()
        out = reshape.apply_bidirectional_correction(frame, pixel_shift=0)
        self.assertIs(out, frame)

    def test_multichannel_both_corrected(self):
        """Both PMT channels must receive identical flip-and-shift treatment."""
        pixels = 6
        frame = np.zeros((2, 4, pixels), dtype=np.uint16)
        frame[0, 1, :] = np.arange(1, pixels + 1, dtype=np.uint16)
        frame[1, 1, :] = np.arange(10, (pixels + 1) * 10, 10, dtype=np.uint16)
        orig_ch0 = frame[0, 1, :].copy()
        orig_ch1 = frame[1, 1, :].copy()

        reshape.apply_bidirectional_correction(frame, pixel_shift=0)

        np.testing.assert_array_equal(frame[0, 1, :], orig_ch0[::-1])
        np.testing.assert_array_equal(frame[1, 1, :], orig_ch1[::-1])


if __name__ == '__main__':
    unittest.main()
