# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Tests for .sbx file writers."""

import unittest
import tempfile
import os
import numpy as np
import scipy.io
from pyscanbox.io import sbx_writer
from pyscanbox.io import sbx_reader


class TestSbxWriter(unittest.TestCase):
    """Test cases for SbxWriter (Scanbox-compatible format)."""

    # Shared dimensions used across most tests.
    LINES = 8
    PIXELS = 12
    NCHAN = 2

    def setUp(self):
        """Create a temporary directory for test output files."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_path = os.path.join(self.temp_dir, 'test')

    def tearDown(self):
        """Remove all test output files and the temporary directory."""
        for ext in ('.sbx', '.mat'):
            path = f"{self.test_path}{ext}"
            if os.path.exists(path):
                os.remove(path)
        os.rmdir(self.temp_dir)

    # ------------------------------------------------------------------
    # Construction and basic file creation
    # ------------------------------------------------------------------

    def test_create_writer_two_channels(self):
        """Writer creates the .sbx file and reports zero frames written."""
        writer = sbx_writer.SbxWriter(
            self.test_path, self.LINES, self.PIXELS, nchan=2)
        self.assertEqual(writer.frames_written, 0)
        writer.close()
        self.assertTrue(os.path.exists(f"{self.test_path}.sbx"))
        self.assertTrue(os.path.exists(f"{self.test_path}.mat"))

    def test_invalid_nchan(self):
        """nchan values other than 1 or 2 raise ValueError."""
        with self.assertRaises(ValueError):
            sbx_writer.SbxWriter(
                self.test_path, self.LINES, self.PIXELS, nchan=3)

    def test_invalid_pmt_channel(self):
        """pmt_channel outside 0/1 raises ValueError when nchan == 1."""
        with self.assertRaises(ValueError):
            sbx_writer.SbxWriter(
                self.test_path, self.LINES, self.PIXELS, nchan=1,
                pmt_channel=2)

    def test_invalid_scanmode(self):
        """scanmode outside 0/1 raises ValueError."""
        with self.assertRaises(ValueError):
            sbx_writer.SbxWriter(
                self.test_path, self.LINES, self.PIXELS, nchan=2, scanmode=2)

    # ------------------------------------------------------------------
    # Binary file layout and size
    # ------------------------------------------------------------------

    def test_file_size_two_channels(self):
        """File size equals nframes * nchan * lines * pixels * 2 bytes."""
        nframes = 5
        with sbx_writer.SbxWriter(
                self.test_path, self.LINES, self.PIXELS, nchan=2) as writer:
            for _ in range(nframes):
                frame = np.zeros((2, self.LINES, self.PIXELS), dtype=np.uint16)
                writer.write_frame(frame)

        expected = nframes * 2 * self.LINES * self.PIXELS * 2
        self.assertEqual(os.path.getsize(f"{self.test_path}.sbx"), expected)

    def test_file_size_one_channel(self):
        """File size is halved when nchan == 1."""
        nframes = 4
        with sbx_writer.SbxWriter(
                self.test_path, self.LINES, self.PIXELS, nchan=1) as writer:
            for _ in range(nframes):
                frame = np.zeros((1, self.LINES, self.PIXELS), dtype=np.uint16)
                writer.write_frame(frame)

        expected = nframes * 1 * self.LINES * self.PIXELS * 2
        self.assertEqual(os.path.getsize(f"{self.test_path}.sbx"), expected)

    def test_wrong_dtype_raises(self):
        """write_frame raises ValueError for non-uint16 input."""
        writer = sbx_writer.SbxWriter(
            self.test_path, self.LINES, self.PIXELS, nchan=2)
        bad_frame = np.zeros((2, self.LINES, self.PIXELS), dtype=np.float32)
        with self.assertRaises(ValueError):
            writer.write_frame(bad_frame)
        writer.close()

    def test_wrong_shape_raises(self):
        """write_frame raises ValueError when shape does not match dimensions."""
        writer = sbx_writer.SbxWriter(
            self.test_path, self.LINES, self.PIXELS, nchan=2)
        bad_frame = np.zeros((2, self.LINES + 1, self.PIXELS), dtype=np.uint16)
        with self.assertRaises(ValueError):
            writer.write_frame(bad_frame)
        writer.close()

    def test_wrong_nchan_in_frame_raises(self):
        """write_frame raises ValueError when channel count mismatches."""
        writer = sbx_writer.SbxWriter(
            self.test_path, self.LINES, self.PIXELS, nchan=2)
        bad_frame = np.zeros((1, self.LINES, self.PIXELS), dtype=np.uint16)
        with self.assertRaises(ValueError):
            writer.write_frame(bad_frame)
        writer.close()

    # ------------------------------------------------------------------
    # .mat metadata file
    # ------------------------------------------------------------------

    def test_mat_info_struct_fields(self):
        """The .mat contains an 'info' struct with all required fields."""
        nframes = 3
        with sbx_writer.SbxWriter(
                self.test_path, self.LINES, self.PIXELS, nchan=2,
                scanmode=1) as writer:
            for _ in range(nframes):
                frame = np.zeros((2, self.LINES, self.PIXELS), dtype=np.uint16)
                writer.write_frame(frame)

        raw = scipy.io.loadmat(
            f"{self.test_path}.mat", squeeze_me=True, struct_as_record=False)
        self.assertIn('info', raw)
        info = raw['info']
        self.assertEqual(int(info.scanbox_version), 2)
        self.assertEqual(int(info.channels), 1)  # both PMTs → bitmask 1
        self.assertEqual(int(info.scanmode), 1)
        self.assertEqual(int(info.recordsPerBuffer), self.LINES)
        sz = info.sz
        self.assertEqual(int(sz[0]), self.LINES)
        self.assertEqual(int(sz[1]), self.PIXELS)
        self.assertEqual(int(info.max_idx), nframes - 1)

    def test_channels_bitmask_pmt0_only(self):
        """channels field is 2 when nchan==1 and pmt_channel==0."""
        with sbx_writer.SbxWriter(
                self.test_path, self.LINES, self.PIXELS, nchan=1,
                pmt_channel=0) as writer:
            writer.write_frame(
                np.zeros((1, self.LINES, self.PIXELS), dtype=np.uint16))

        raw = scipy.io.loadmat(
            f"{self.test_path}.mat", squeeze_me=True, struct_as_record=False)
        self.assertEqual(int(raw['info'].channels), 2)

    def test_channels_bitmask_pmt1_only(self):
        """channels field is 3 when nchan==1 and pmt_channel==1."""
        with sbx_writer.SbxWriter(
                self.test_path, self.LINES, self.PIXELS, nchan=1,
                pmt_channel=1) as writer:
            writer.write_frame(
                np.zeros((1, self.LINES, self.PIXELS), dtype=np.uint16))

        raw = scipy.io.loadmat(
            f"{self.test_path}.mat", squeeze_me=True, struct_as_record=False)
        self.assertEqual(int(raw['info'].channels), 3)

    def test_extra_info_stored_in_mat(self):
        """extra_info fields appear in the info struct."""
        extra = {'pyscanbox_version': '0.4.8', 'frame_rate': 15.0}
        with sbx_writer.SbxWriter(
                self.test_path, self.LINES, self.PIXELS, nchan=2,
                extra_info=extra) as writer:
            writer.write_frame(
                np.zeros((2, self.LINES, self.PIXELS), dtype=np.uint16))

        raw = scipy.io.loadmat(
            f"{self.test_path}.mat", squeeze_me=True, struct_as_record=False)
        info = raw['info']
        self.assertIn('pyscanbox_version', info._fieldnames)
        self.assertIn('frame_rate', info._fieldnames)

    # ------------------------------------------------------------------
    # Round-trip: write then read with SbxReader
    # ------------------------------------------------------------------

    def test_round_trip_values_two_channels(self):
        """Wire-format data written by SbxWriter round-trips via SbxReader."""
        nframes = 3
        rng = np.random.default_rng(42)
        original = rng.integers(
            0, 65536, (nframes, 2, self.LINES, self.PIXELS),
            dtype=np.uint16)

        with sbx_writer.SbxWriter(
                self.test_path, self.LINES, self.PIXELS, nchan=2) as writer:
            for frame in original:
                writer.write_frame(frame)

        with sbx_reader.SbxReader(self.test_path) as reader:
            # invert=False returns wire-format (high=dark), matching what was written
            loaded = reader.load(invert=False)

        np.testing.assert_array_equal(loaded, original)

    def test_round_trip_invert_two_channels(self):
        """invert=True (default) returns 65535-complement of the stored wire-format data."""
        nframes = 2
        rng = np.random.default_rng(13)
        original = rng.integers(
            0, 65536, (nframes, 2, self.LINES, self.PIXELS),
            dtype=np.uint16)

        with sbx_writer.SbxWriter(
                self.test_path, self.LINES, self.PIXELS, nchan=2) as writer:
            for frame in original:
                writer.write_frame(frame)

        with sbx_reader.SbxReader(self.test_path) as reader:
            loaded = reader.load()  # invert=True by default

        np.testing.assert_array_equal(loaded, np.uint16(65535) - original)

    def test_round_trip_values_one_channel(self):
        """Single-channel wire-format round-trip preserves signal values."""
        nframes = 2
        rng = np.random.default_rng(7)
        original = rng.integers(
            0, 65536, (nframes, 1, self.LINES, self.PIXELS),
            dtype=np.uint16)

        with sbx_writer.SbxWriter(
                self.test_path, self.LINES, self.PIXELS,
                nchan=1, pmt_channel=0) as writer:
            for frame in original:
                writer.write_frame(frame)

        with sbx_reader.SbxReader(self.test_path) as reader:
            loaded = reader.load(invert=False)

        np.testing.assert_array_equal(loaded, original)

    def test_round_trip_frame_count(self):
        """SbxReader reports the correct number of frames."""
        nframes = 7
        with sbx_writer.SbxWriter(
                self.test_path, self.LINES, self.PIXELS, nchan=2) as writer:
            for _ in range(nframes):
                frame = np.zeros((2, self.LINES, self.PIXELS), dtype=np.uint16)
                writer.write_frame(frame)

        with sbx_reader.SbxReader(self.test_path) as reader:
            self.assertEqual(reader.num_frames, nframes)

    # ------------------------------------------------------------------
    # Convenience function
    # ------------------------------------------------------------------

    def test_write_sbx_scanbox_convenience(self):
        """write_sbx_scanbox produces a file readable by SbxReader."""
        nframes, nchan, lines, pixels = 4, 2, self.LINES, self.PIXELS
        rng = np.random.default_rng(99)
        data = rng.integers(0, 65536, (nframes, nchan, lines, pixels),
                            dtype=np.uint16)

        sbx_writer.write_sbx_scanbox(self.test_path, data)

        with sbx_reader.SbxReader(self.test_path) as reader:
            loaded = reader.load(invert=False)

        np.testing.assert_array_equal(loaded, data)

    def test_write_sbx_scanbox_wrong_ndim(self):
        """write_sbx_scanbox raises ValueError for non-4D input."""
        bad = np.zeros((10, self.LINES, self.PIXELS), dtype=np.uint16)
        with self.assertRaises(ValueError):
            sbx_writer.write_sbx_scanbox(self.test_path, bad)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def test_context_manager(self):
        """Writer used as a context manager closes and writes .mat on exit."""
        with sbx_writer.SbxWriter(
                self.test_path, self.LINES, self.PIXELS, nchan=2) as writer:
            frame = np.zeros((2, self.LINES, self.PIXELS), dtype=np.uint16)
            writer.write_frame(frame)

        self.assertTrue(os.path.exists(f"{self.test_path}.sbx"))
        self.assertTrue(os.path.exists(f"{self.test_path}.mat"))


if __name__ == '__main__':
    unittest.main()
