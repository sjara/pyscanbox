# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Tests for data reshaping functions.

Tests the high-speed Numba-optimized reshaping functions.
"""

import unittest
import numpy as np
from pyscanbox.acquisition import reshape


class TestReshape(unittest.TestCase):
    """Test cases for data reshaping functions."""

    def test_reshape_pmt_data_emulation_basic(self):
        """Test basic reshaping with known data (emulation mode)."""
        lines = 2
        pixels = 4
        channels = 2

        # Create test buffer (interleaved)
        buffer = np.arange(lines * pixels * channels, dtype=np.uint16)

        # Shift left by 2 to simulate 14-bit data in upper bits
        buffer = buffer << 2

        # Reshape
        reshaped = reshape.reshape_pmt_data_emulation(buffer, lines, pixels)
        
        # Verify output shape
        self.assertEqual(reshaped.shape, (channels, lines, pixels))
        self.assertEqual(reshaped.dtype, np.uint16)

    def test_reshape_pmt_data_emulation_wire_format_preserved(self):
        """Test that wire-format values pass through unchanged (emulation mode)."""
        # Wire-format input: 14-bit max (16383) left-shifted by 2 = 0xFFFC
        buffer = np.array([0xFFFC, 0xFFFC], dtype=np.uint16)

        reshaped = reshape.reshape_pmt_data_emulation(buffer, 1, 1)

        # Wire format is preserved: 0xFFFC passes through unchanged
        self.assertEqual(reshaped[0, 0, 0], 0xFFFC)
        self.assertEqual(reshaped[1, 0, 0], 0xFFFC)

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


class TestReshapePmtData(unittest.TestCase):
    """Tests for reshape_pmt_data() (real hardware / raw ADC path)."""

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
        out = reshape.reshape_pmt_data(buf, self.N_LINES, self.N_PIXELS, lut)
        self.assertEqual(out.shape, (2, self.N_LINES, self.N_PIXELS))

    def test_output_dtype(self):
        """Output dtype must be uint16."""
        lut = self._make_lut()
        buf = self._make_zero_buffer()
        out = reshape.reshape_pmt_data(buf, self.N_LINES, self.N_PIXELS, lut)
        self.assertEqual(out.dtype, np.uint16)

    def test_zero_buffer_gives_zero_output(self):
        """All-zero input must give all-zero output."""
        lut = self._make_lut()
        buf = self._make_zero_buffer()
        out = reshape.reshape_pmt_data(buf, self.N_LINES, self.N_PIXELS, lut)
        self.assertTrue(np.all(out == 0))

    def test_uniform_buffer_value(self):
        """Uniform non-zero buffer: each pixel should equal the original value
        (after the 4-sample average, which is exact for constant data)."""
        lut = self._make_lut()
        value_14bit = np.uint16(4096)   # 14-bit value
        # Wire format: value left-shifted by 2
        wire_val = np.uint16(value_14bit << np.uint16(2))
        buf = np.full(self.N_LINES * self.SAMPLES_PER_LINE * 2, wire_val, dtype=np.uint16)
        out = reshape.reshape_pmt_data(buf, self.N_LINES, self.N_PIXELS, lut)
        # Each sample is wire_val; the 4-sample sum >> 2 = wire_val.
        # But reshape_pmt_data does NOT strip the 2 LSBs — it averages
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

        out = reshape.reshape_pmt_data(buf, self.N_LINES, self.N_PIXELS, lut)
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

        out = reshape.reshape_pmt_data(buf, self.N_LINES, self.N_PIXELS, lut)
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

    def test_flip_lines_false_skips_flip(self):
        """flip_lines=False must apply only the bishift, not the line flip."""
        pixels = 6
        frame = np.zeros((1, 4, pixels), dtype=np.uint16)
        frame[0, 1, :] = np.arange(1, pixels + 1, dtype=np.uint16)
        orig_odd = frame[0, 1, :].copy()

        reshape.apply_bidirectional_correction(frame, pixel_shift=0, flip_lines=False)

        # Odd line must be unchanged (no flip requested).
        np.testing.assert_array_equal(frame[0, 1, :], orig_odd)

    def test_flip_lines_false_still_applies_shift(self):
        """flip_lines=False with a non-zero shift must still roll backward lines."""
        pixels = 8
        shift = 2
        frame = np.zeros((1, 4, pixels), dtype=np.uint16)
        frame[0, 1, :] = 1   # uniform backward line

        reshape.apply_bidirectional_correction(frame, pixel_shift=shift,
                                               flip_lines=False)

        # Leading edge must be zeroed by the roll.
        self.assertTrue(np.all(frame[0, 1, :shift] == 0))
        self.assertTrue(np.all(frame[0, 1, shift:] == 1))


class TestComputePixelLutBi(unittest.TestCase):
    """Tests for compute_pixel_lut_bi() (bidirectional hardware path)."""

    LASER_FREQ    = 80_180_000
    RES_FREQ      = 7_930
    N_PIXELS      = 796
    BIDIR_SAMPLES = 9000

    def _get_lut_bi(self):
        return reshape.compute_pixel_lut_bi(
            self.N_PIXELS, self.LASER_FREQ, self.RES_FREQ, self.BIDIR_SAMPLES
        )

    def test_output_dtype(self):
        """LUT must be int32 for Numba compatibility."""
        lut = self._get_lut_bi()
        self.assertEqual(lut.dtype, np.int32)

    def test_output_length(self):
        """LUT must have more than n_pixels entries (forward + backward)."""
        lut = self._get_lut_bi()
        self.assertGreater(len(lut), self.N_PIXELS)

    def test_forward_section_matches_unidirectional_lut(self):
        """First n_pixels entries must equal the unidirectional LUT."""
        lut_bi = self._get_lut_bi()
        lut_uni = reshape.compute_pixel_lut(
            self.N_PIXELS, self.LASER_FREQ, self.RES_FREQ
        )
        np.testing.assert_array_equal(lut_bi[:self.N_PIXELS], lut_uni)

    def test_forward_indices_in_first_half(self):
        """Forward scan indices must fall within the first half of bidir_samples."""
        lut = self._get_lut_bi()
        nsamp_half = round(self.LASER_FREQ / self.RES_FREQ) // 2
        fwd = lut[:self.N_PIXELS]
        self.assertTrue(np.all(fwd >= 0))
        self.assertTrue(np.all(fwd + 3 < nsamp_half + 200),
                        "Forward indices must be in the first half-period")

    def test_backward_indices_in_second_half(self):
        """Backward scan indices must be offset into the second half of the record."""
        lut = self._get_lut_bi()
        nsamp = round(self.LASER_FREQ / self.RES_FREQ)
        bwd = lut[self.N_PIXELS:]
        # All backward indices must be in the range [nsamp/2 - small, bidir_samples - 4]
        nsamp_half = nsamp // 2
        self.assertTrue(np.all(bwd >= nsamp_half - 200))
        self.assertTrue(np.all(bwd + 3 < self.BIDIR_SAMPLES))

    def test_deterministic(self):
        """Two calls with the same parameters return identical arrays."""
        lut1 = self._get_lut_bi()
        lut2 = self._get_lut_bi()
        np.testing.assert_array_equal(lut1, lut2)

    def test_fewer_backward_pixels_than_forward(self):
        """The 9000-sample window does not cover the full backward sweep;
        so there are fewer backward pixels than forward pixels."""
        lut = self._get_lut_bi()
        n_bwd = len(lut) - self.N_PIXELS
        self.assertLess(n_bwd, self.N_PIXELS)
        self.assertGreater(n_bwd, 0)


class TestReshapePmtDataBi(unittest.TestCase):
    """Tests for reshape_pmt_data_bi() (bidirectional hardware path)."""

    LASER_FREQ    = 80_180_000
    RES_FREQ      = 7_930
    N_PIXELS      = 796
    N_RECORDS     = 4          # small frame: 4 records → 8 output lines
    BIDIR_SAMPLES = 9000

    def _make_lut_bi(self):
        return reshape.compute_pixel_lut_bi(
            self.N_PIXELS, self.LASER_FREQ, self.RES_FREQ, self.BIDIR_SAMPLES
        )

    def _make_zero_buffer(self):
        size = self.N_RECORDS * self.BIDIR_SAMPLES * 2
        return np.zeros(size, dtype=np.uint16)

    def test_output_shape(self):
        """Output must be (2, 2*records, pixels)."""
        lut = self._make_lut_bi()
        buf = self._make_zero_buffer()
        out = reshape.reshape_pmt_data_bi(buf, self.N_RECORDS, self.N_PIXELS, lut, 0)
        self.assertEqual(out.shape, (2, self.N_RECORDS * 2, self.N_PIXELS))

    def test_output_dtype(self):
        """Output dtype must be uint16."""
        lut = self._make_lut_bi()
        buf = self._make_zero_buffer()
        out = reshape.reshape_pmt_data_bi(buf, self.N_RECORDS, self.N_PIXELS, lut, 0)
        self.assertEqual(out.dtype, np.uint16)

    def test_zero_buffer_gives_zero_output(self):
        """All-zero input must give all-zero output."""
        lut = self._make_lut_bi()
        buf = self._make_zero_buffer()
        out = reshape.reshape_pmt_data_bi(buf, self.N_RECORDS, self.N_PIXELS, lut, 0)
        self.assertTrue(np.all(out == 0))

    def test_uniform_buffer_value(self):
        """Uniform non-zero buffer: forward pixels must equal the wire value."""
        lut = self._make_lut_bi()
        wire_val = np.uint16(4096 << 2)   # 14-bit 4096 in wire format
        buf = np.full(self.N_RECORDS * self.BIDIR_SAMPLES * 2, wire_val,
                      dtype=np.uint16)
        out = reshape.reshape_pmt_data_bi(buf, self.N_RECORDS, self.N_PIXELS, lut, 0)
        # Even (forward) lines: all pixels should equal wire_val.
        np.testing.assert_array_equal(out[:, 0::2, :], wire_val)

    def test_even_lines_use_forward_lut(self):
        """Forward pixels (even output lines) are derived from first record half."""
        lut = self._make_lut_bi()
        buf = self._make_zero_buffer()
        # Set one forward pixel in record 0 to a known value.
        px = 50
        rec = 0
        s = int(lut[px])
        rec_start = rec * self.BIDIR_SAMPLES * 2
        known_val = np.uint16(800)
        for k in range(4):
            buf[rec_start + 2 * (s + k)] = known_val  # chA
        out = reshape.reshape_pmt_data_bi(buf, self.N_RECORDS, self.N_PIXELS, lut, 0)
        expected = np.uint16((int(known_val) * 4) >> 2)
        self.assertEqual(int(out[0, 0, px]), int(expected))   # even line 0, chA

    def test_odd_lines_filled_in_correct_columns(self):
        """Backward pixel values must appear in right-side columns of odd lines."""
        lut = self._make_lut_bi()
        n_bwd = len(lut) - self.N_PIXELS
        buf = self._make_zero_buffer()
        # Set all backward-scan samples in record 0 to a non-zero value.
        rec = 0
        ref_val = np.uint16(400)
        rec_start = rec * self.BIDIR_SAMPLES * 2
        for j in range(n_bwd):
            s = int(lut[self.N_PIXELS + j])
            for k in range(4):
                buf[rec_start + 2 * (s + k)] = ref_val
        out = reshape.reshape_pmt_data_bi(buf, self.N_RECORDS, self.N_PIXELS, lut, 0)
        odd_line = out[0, 1, :]   # first odd output line
        # Right-side n_bwd columns should be non-zero.
        self.assertTrue(np.any(odd_line[self.N_PIXELS - n_bwd:] > 0))
        # Left-side skip columns should be zero.
        skip = self.N_PIXELS - n_bwd
        self.assertTrue(np.all(odd_line[:skip] == 0))

    def test_backward_pixels_reversed_vs_lut_order(self):
        """Backward pixel j=0 (closest to right edge) goes to column n_pixels-1."""
        lut = self._make_lut_bi()
        buf = self._make_zero_buffer()
        rec = 0
        rec_start = rec * self.BIDIR_SAMPLES * 2
        # Set only backward pixel j=0 to a non-zero value; all others zero.
        s = int(lut[self.N_PIXELS])
        bwd_val = np.uint16(1000)
        for k in range(4):
            buf[rec_start + 2 * (s + k)] = bwd_val
        out = reshape.reshape_pmt_data_bi(buf, self.N_RECORDS, self.N_PIXELS, lut, 0)
        odd_line = out[0, 1, :]
        # j=0 should land at the rightmost column.
        expected = np.uint16((int(bwd_val) * 4) >> 2)
        self.assertEqual(int(odd_line[-1]), int(expected))
        # All other columns in the backward line must be zero.
        self.assertTrue(np.all(odd_line[:-1] == 0))


if __name__ == '__main__':
    unittest.main()
