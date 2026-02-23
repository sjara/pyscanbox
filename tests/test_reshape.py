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


if __name__ == '__main__':
    unittest.main()
