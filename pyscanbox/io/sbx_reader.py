# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

""".sbx file reader for raw PMT data.

This module provides :class:`SbxReader`, which reads .sbx binary files
produced by the **original MATLAB Scanbox** software and by pyscanbox's
:class:`~pyscanbox.io.sbx_writer.SbxWriter`.  The binary data is written in
MATLAB column-major order, with the on-disk layout equivalent to
(lines_per_frame, pixels_per_line, nchan) per frame.  Values are stored
bitwise-complemented (raw = 65535 - signal); this class undoes the complement
automatically.  The companion .mat file contains a nested ``info`` struct with
fields such as ``sz``, ``recordsPerBuffer``, and ``channels``.

Example::

    >>> import pyscanbox.io.sbx_reader
    >>> with pyscanbox.io.sbx_reader.SbxReader('mydata') as reader:
    ...     frame = reader.get_frame(0)
"""

import os
import numpy as np
import scipy.io
from typing import Dict, Any, Optional


# Mapping from .mat ``channels`` field value to number of active PMT channels.
_CHANNELS_TO_NCHAN = {1: 2, 2: 1, 3: 1}


def load_mat_info(mat_path: str) -> Dict[str, Any]:
    """Load and flatten the ``info`` struct from a Scanbox .mat metadata file.

    Can be called without opening the associated .sbx binary, making it
    suitable for scripts that only need session metadata.

    Args:
        mat_path: Path to the .mat file (e.g., ``'mydata.mat'``).

    Returns:
        Flat dictionary of ``info`` struct fields plus a computed ``nchan``
        key derived from the ``channels`` bitmask.

    Raises:
        FileNotFoundError: If ``mat_path`` does not exist.
        KeyError: If the .mat file does not contain an ``info`` struct.
        ValueError: If ``channels`` encodes an unknown PMT configuration.
    """
    if not os.path.exists(mat_path):
        raise FileNotFoundError(f".mat file not found: {mat_path}")

    raw = scipy.io.loadmat(mat_path, squeeze_me=True, struct_as_record=False)
    if 'info' not in raw:
        raise KeyError(
            f"No 'info' struct found in {mat_path}. "
            "This file may have been written by the old pyscanbox native "
            "format — use SbxReader instead."
        )

    info_obj = raw['info']
    flat: Dict[str, Any] = {}
    for field in info_obj._fieldnames:
        flat[field] = getattr(info_obj, field)

    channels = int(flat['channels'])
    if channels not in _CHANNELS_TO_NCHAN:
        raise ValueError(
            f"Unexpected 'channels' value {channels} in {mat_path}. "
            f"Expected one of {list(_CHANNELS_TO_NCHAN)}: "
            "1=both PMTs, 2=PMT0, 3=PMT1."
        )
    flat['nchan'] = _CHANNELS_TO_NCHAN[channels]

    return flat


class SbxReader:
    """Reader for .sbx files produced by the original MATLAB Scanbox.

    Scanbox stores raw uint16 data in MATLAB column-major (Fortran) order.
    The on-disk layout per frame is equivalent to the C-order shape
    ``(lines_per_frame, pixels_per_line, nchan)``.  Values are stored as
    their bitwise complement (``stored = 65535 - signal``); this class
    undoes that automatically in ``get_frame()`` and ``get_channel()``.

    The companion .mat file contains a nested MATLAB struct named ``info``
    with fields including:

    * ``sz``  – ``[lines_per_frame, pixels_per_line]``
    * ``recordsPerBuffer``  – lines per frame (same as ``sz[0]``)
    * ``channels``  – PMT channel bitmask:
        * ``1`` → both PMT0 & PMT1 (nchan = 2)
        * ``2`` → PMT0 only  (nchan = 1)
        * ``3`` → PMT1 only  (nchan = 1)
    * ``scanbox_version``  – file format version (>= 2 for modern files)
    * ``scanmode``  – ``0`` = bidirectional, ``1`` = unidirectional

    The number of frames is derived from the file size rather than any
    metadata field because Scanbox truncates the field on premature stop.

    Reference implementation: ``Scanbox/sbx/sbxread.m``

    Attributes:
        filepath: Base path (without extension).
        sbx_path: Full path to the .sbx binary file.
        mat_path: Full path to the .mat metadata file.
        info: Flattened dictionary of the ``info`` struct fields.
        data: Memory-mapped numpy array, shape
            ``(nframes, lines_per_frame, pixels_per_line, nchan)``.
            This is the raw (bitwise-complemented) layout as stored on
            disk.  Use ``get_frame()`` / ``get_channel()`` to obtain
            processed data in the standard
            ``(nchan, lines_per_frame, pixels_per_line)`` orientation.
    """

    def __init__(self, filepath: str):
        """Initialize the original Scanbox .sbx reader.

        Args:
            filepath: Base path without extension (e.g., 'mydata').
                Will load 'mydata.sbx' and 'mydata.mat'.

        Raises:
            FileNotFoundError: If .sbx or .mat file does not exist.
            KeyError: If the .mat file does not contain the ``info`` struct.
            ValueError: If ``channels`` field has an unexpected value.
        """
        self.filepath = filepath
        self.sbx_path = f"{filepath}.sbx"
        self.mat_path = f"{filepath}.mat"
        self._mmap: Optional[np.memmap] = None

        if not os.path.exists(self.sbx_path):
            raise FileNotFoundError(f".sbx file not found: {self.sbx_path}")
        if not os.path.exists(self.mat_path):
            raise FileNotFoundError(f".mat file not found: {self.mat_path}")

        self.info = self._load_info()
        self.data = self._open_sbx()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def shape(self):
        """Memory-map shape: (nframes, lines_per_frame, pixels_per_line, nchan)."""
        return self.data.shape

    @property
    def num_frames(self) -> int:
        """Number of frames derived from file size."""
        return self.data.shape[0]

    @property
    def num_channels(self) -> int:
        """Number of active PMT channels (1 or 2)."""
        return int(self.info['nchan'])

    @property
    def lines_per_frame(self) -> int:
        """Number of scan lines per frame."""
        return int(self.info['sz'][0])

    @property
    def pixels_per_line(self) -> int:
        """Number of pixels per scan line."""
        return int(self.info['sz'][1])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_info(self) -> Dict[str, Any]:
        """Load and flatten the ``info`` struct from the .mat file."""
        return load_mat_info(self.mat_path)

    def _open_sbx(self) -> np.memmap:
        """Memory-map the .sbx binary file.

        Scanbox writes data in MATLAB column-major order.  For each frame
        the fastest-varying index is the channel, then pixel, then line.
        Expressed as a C-order numpy shape this is
        ``(lines_per_frame, pixels_per_line, nchan)`` per frame.

        The number of frames is computed solely from the file size so that
        recordings stopped early are handled correctly.

        Returns:
            numpy.memmap with C-order shape
            ``(nframes, lines_per_frame, pixels_per_line, nchan)``.

        Raises:
            ValueError: If the file size is not an exact multiple of one
                frame's worth of bytes.
        """
        nchan = int(self.info['nchan'])
        sz = self.info['sz']          # [lines, pixels]
        lines = int(sz[0])
        pixels = int(sz[1])

        bytes_per_frame = nchan * lines * pixels * np.dtype(np.uint16).itemsize
        file_bytes = os.path.getsize(self.sbx_path)

        if file_bytes % bytes_per_frame != 0:
            raise ValueError(
                f"File size {file_bytes} bytes is not divisible by the "
                f"expected frame size {bytes_per_frame} bytes "
                f"({nchan} ch × {lines} lines × {pixels} px × 2 bytes)."
            )

        nframes = file_bytes // bytes_per_frame
        # C-order shape that matches MATLAB Fortran-order (nchan, pixels, lines)
        shape = (nframes, lines, pixels, nchan)
        self._mmap = np.memmap(self.sbx_path, dtype=np.uint16, mode='r',
                               shape=shape)
        return self._mmap

    # ------------------------------------------------------------------
    # Public access methods
    # ------------------------------------------------------------------

    def get_frame(self, index: int, invert: bool = True) -> np.ndarray:
        """Return a single frame as a numpy array.

        Args:
            index: Frame index (0-based).
            invert: If ``True`` (default), apply ``65535 − stored`` and
                return **signal convention** (high = bright fluorescence,
                low = dark background), matching ``sbxread.m`` and
                downstream tools such as Suite2p.  If ``False``, return
                the raw on-disk values in **wire-format convention**
                (high = dark) — use this when feeding the GUI display
                pipeline, which applies its own inversion internally.

        Returns:
            Array of shape ``(nchan, lines_per_frame, pixels_per_line)``,
            dtype uint16.

        Raises:
            IndexError: If index is out of range.
        """
        if index < 0 or index >= self.num_frames:
            raise IndexError(
                f"Frame index {index} out of range [0, {self.num_frames - 1}]"
            )
        # Disk layout per frame (C-order): (lines, pixels, nchan)
        # Transpose to (nchan, lines, pixels) to match MATLAB permute([1 3 2])
        frame = np.array(self.data[index]).transpose(2, 0, 1)
        if invert:
            return np.uint16(65535) - frame
        return frame

    def get_channel(self, channel: int, invert: bool = True) -> np.ndarray:
        """Return all frames for a single PMT channel.

        Args:
            channel: Channel index (0-based).
            invert: If ``True`` (default), apply ``65535 − stored`` to
                return signal convention (high = bright).  If ``False``,
                return wire-format values (high = dark) as stored on disk.

        Returns:
            Array of shape ``(nframes, lines_per_frame, pixels_per_line)``,
            dtype uint16.

        Raises:
            IndexError: If channel index is out of range.
        """
        if channel < 0 or channel >= self.num_channels:
            raise IndexError(
                f"Channel index {channel} out of range "
                f"[0, {self.num_channels - 1}]"
            )
        # data shape: (nframes, lines, pixels, nchan) → select channel last axis
        ch_data = np.array(self.data[:, :, :, channel])
        if invert:
            return np.uint16(65535) - ch_data
        return ch_data

    def load(self, invert: bool = True) -> np.ndarray:
        """Load the entire dataset into memory.

        Args:
            invert: If ``True`` (default), apply ``65535 − stored`` to
                return signal convention (high = bright), matching
                ``sbxread.m``.  If ``False``, return wire-format values
                (high = dark) as stored on disk.

        Returns:
            Array of shape
            ``(nframes, nchan, lines_per_frame, pixels_per_line)``,
            dtype uint16.

        Note:
            For large files this may consume significant RAM.  Prefer
            ``get_frame()`` or ``get_channel()`` for selective access.
        """
        # data shape on disk: (nframes, lines, pixels, nchan)
        # Desired output:     (nframes, nchan, lines, pixels)
        result = np.array(self.data).transpose(0, 3, 1, 2)
        if invert:
            return np.uint16(65535) - result
        return result

    def close(self) -> None:
        """Release the memory-mapped file handle."""
        if self._mmap is not None:
            del self._mmap
            self._mmap = None
            self.data = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def __repr__(self) -> str:
        return (
            f"SbxReader('{self.filepath}', "
            f"nframes={self.num_frames}, nchan={self.num_channels}, "
            f"lines={self.lines_per_frame}, pixels={self.pixels_per_line})"
        )
