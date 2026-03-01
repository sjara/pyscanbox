"""Tests for pyscanbox.io.mat_writer.

Verifies that MatWriter, write_mat_file, and create_suite2p_metadata
produce correct .mat files that can be round-tripped through scipy.io.loadmat.
"""

import os
import tempfile
import unittest

import scipy.io

from pyscanbox.io.mat_writer import MatWriter, write_mat_file, create_suite2p_metadata


# -- Helpers --------------------------------------------------------------------

def _minimal_config():
    """Return a minimal config dict accepted by create_suite2p_metadata."""
    return {
        'alazar': {'channels': 2},
        'acquisition': {
            'lines_per_frame': 512,
            'pixels_per_line': 796,
        },
    }


# -- MatWriter ------------------------------------------------------------------

class TestMatWriter(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = os.path.join(self.tmpdir.name, 'testdata')

    def tearDown(self):
        self.tmpdir.cleanup()

    # -- Initialisation ---------------------------------------------------------

    def test_mat_path_adds_extension(self):
        w = MatWriter(self.base)
        self.assertEqual(w.mat_path, self.base + '.mat')

    def test_filepath_stored(self):
        w = MatWriter(self.base)
        self.assertEqual(w.filepath, self.base)

    # -- write() ----------------------------------------------------------------

    def test_write_creates_file(self):
        MatWriter(self.base).write({'frames': 100})
        self.assertTrue(os.path.exists(self.base + '.mat'))

    def test_write_integer_scalar_roundtrip(self):
        MatWriter(self.base).write({'frames': 42})
        loaded = scipy.io.loadmat(self.base + '.mat')
        self.assertEqual(int(loaded['frames'].flat[0]), 42)

    def test_write_string_roundtrip(self):
        MatWriter(self.base).write({'label': 'test'})
        loaded = scipy.io.loadmat(self.base + '.mat')
        self.assertIn('label', loaded)

    def test_write_multiple_keys(self):
        metadata = {'frames': 10, 'lines': 512, 'pixels': 796}
        MatWriter(self.base).write(metadata)
        loaded = scipy.io.loadmat(self.base + '.mat')
        self.assertEqual(int(loaded['frames'].flat[0]), 10)
        self.assertEqual(int(loaded['lines'].flat[0]), 512)
        self.assertEqual(int(loaded['pixels'].flat[0]), 796)

    def test_write_creates_parent_directory(self):
        nested = os.path.join(self.tmpdir.name, 'sub', 'dir', 'data')
        MatWriter(nested).write({'x': 1})
        self.assertTrue(os.path.exists(nested + '.mat'))

    def test_write_overwrites_existing_file(self):
        MatWriter(self.base).write({'value': 1})
        MatWriter(self.base).write({'value': 2})
        loaded = scipy.io.loadmat(self.base + '.mat')
        self.assertEqual(int(loaded['value'].flat[0]), 2)

    # -- append() ---------------------------------------------------------------

    def test_append_to_nonexistent_creates_file(self):
        MatWriter(self.base).append({'a': 1})
        self.assertTrue(os.path.exists(self.base + '.mat'))

    def test_append_adds_new_key(self):
        w = MatWriter(self.base)
        w.write({'a': 1})
        w.append({'b': 2})
        loaded = scipy.io.loadmat(self.base + '.mat')
        self.assertIn('a', loaded)
        self.assertIn('b', loaded)

    def test_append_updates_existing_key(self):
        w = MatWriter(self.base)
        w.write({'count': 1})
        w.append({'count': 99})
        loaded = scipy.io.loadmat(self.base + '.mat')
        self.assertEqual(int(loaded['count'].flat[0]), 99)

    def test_append_preserves_unmodified_keys(self):
        w = MatWriter(self.base)
        w.write({'keep': 7, 'also': 8})
        w.append({'also': 9})
        loaded = scipy.io.loadmat(self.base + '.mat')
        self.assertEqual(int(loaded['keep'].flat[0]), 7)
        self.assertEqual(int(loaded['also'].flat[0]), 9)


# -- write_mat_file convenience function ----------------------------------------

class TestWriteMatFile(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = os.path.join(self.tmpdir.name, 'out')

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_creates_mat_file(self):
        write_mat_file(self.base, {'x': 5})
        self.assertTrue(os.path.exists(self.base + '.mat'))

    def test_value_roundtrip(self):
        write_mat_file(self.base, {'n': 123})
        loaded = scipy.io.loadmat(self.base + '.mat')
        self.assertEqual(int(loaded['n'].flat[0]), 123)


# -- create_suite2p_metadata ----------------------------------------------------

class TestCreateSuite2pMetadata(unittest.TestCase):

    def test_returns_dict(self):
        result = create_suite2p_metadata(_minimal_config(), frames_acquired=100)
        self.assertIsInstance(result, dict)

    def test_nframes_set_correctly(self):
        result = create_suite2p_metadata(_minimal_config(), frames_acquired=500)
        self.assertEqual(result['nframes'], 500)

    def test_nchannels_from_config(self):
        cfg = _minimal_config()
        cfg['alazar']['channels'] = 2
        result = create_suite2p_metadata(cfg, frames_acquired=1)
        self.assertEqual(result['nchannels'], 2)

    def test_sz_contains_lines_and_pixels(self):
        result = create_suite2p_metadata(_minimal_config(), frames_acquired=1)
        self.assertEqual(result['sz'][0], 512)
        self.assertEqual(result['sz'][1], 796)

    def test_required_suite2p_keys_present(self):
        result = create_suite2p_metadata(_minimal_config(), frames_acquired=1)
        for key in ('nframes', 'nchannels', 'nplanes', 'nrois', 'sz'):
            with self.subTest(key=key):
                self.assertIn(key, result)

    def test_suite2p_metadata_writes_to_mat(self):
        """Full round-trip: create → write → load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = os.path.join(tmpdir, 'meta')
            meta = create_suite2p_metadata(_minimal_config(), frames_acquired=200)
            write_mat_file(base, meta)
            self.assertTrue(os.path.exists(base + '.mat'))


if __name__ == '__main__':
    unittest.main()
