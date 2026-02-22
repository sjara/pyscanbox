"""Tests for .sbx file writer."""

import unittest
import tempfile
import os
import numpy as np
from pyscanbox.io import sbx_writer


class TestSbxWriter(unittest.TestCase):
    """Test cases for SbxWriter."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_path = os.path.join(self.temp_dir, 'test')

    def tearDown(self):
        """Clean up test files."""
        # Remove test files
        if os.path.exists(f"{self.test_path}.sbx"):
            os.remove(f"{self.test_path}.sbx")
        os.rmdir(self.temp_dir)

    def test_create_writer(self):
        """Test creating writer."""
        writer = sbx_writer.SbxWriter(self.test_path)
        self.assertIsNotNone(writer)
        self.assertEqual(writer.frames_written, 0)
        writer.close()
        
        # Verify file was created
        self.assertTrue(os.path.exists(f"{self.test_path}.sbx"))

    def test_write_frame(self):
        """Test writing frame data."""
        writer = sbx_writer.SbxWriter(self.test_path)
        
        # Create test frame
        frame = np.ones((2, 10, 10), dtype=np.uint16) * 1000
        
        writer.write_frame(frame)
        self.assertEqual(writer.frames_written, 1)
        
        writer.close()
        
        # Verify file size
        file_size = os.path.getsize(f"{self.test_path}.sbx")
        expected_size = 2 * 10 * 10 * 2  # channels * lines * pixels * bytes
        self.assertEqual(file_size, expected_size)

    def test_write_multiple_frames(self):
        """Test writing multiple frames."""
        writer = sbx_writer.SbxWriter(self.test_path)
        
        num_frames = 5
        for i in range(num_frames):
            frame = np.ones((2, 10, 10), dtype=np.uint16) * i
            writer.write_frame(frame)
        
        self.assertEqual(writer.frames_written, num_frames)
        writer.close()
        
        # Verify file size
        file_size = os.path.getsize(f"{self.test_path}.sbx")
        expected_size = num_frames * 2 * 10 * 10 * 2
        self.assertEqual(file_size, expected_size)

    def test_context_manager(self):
        """Test using writer as context manager."""
        with sbx_writer.SbxWriter(self.test_path) as writer:
            frame = np.ones((2, 10, 10), dtype=np.uint16)
            writer.write_frame(frame)
        
        # File should be closed and written
        self.assertTrue(os.path.exists(f"{self.test_path}.sbx"))

    def test_wrong_dtype(self):
        """Test that wrong data type raises error."""
        writer = sbx_writer.SbxWriter(self.test_path)
        
        # Try to write float32 data
        frame = np.ones((2, 10, 10), dtype=np.float32)
        
        with self.assertRaises(ValueError):
            writer.write_frame(frame)
        
        writer.close()


if __name__ == '__main__':
    unittest.main()
