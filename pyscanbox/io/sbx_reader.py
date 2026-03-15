""".sbx file reader for raw PMT data.

This module provides two reader classes for .sbx binary files:

    SbxReaderObsolete
        Obsolete reader for files produced by the old **pyscanbox** native
        format.  The binary data is a headerless uint16 C-order dump with
        shape (frames, channels, lines_per_frame, pixels_per_line) and the
        companion .mat file stores flat key/value metadata.  Use
        :class:`ScanboxOriginalReader` for new recordings.

    ScanboxOriginalReader
        Reads files produced by the **original MATLAB Scanbox** software
        and by pyscanbox's :class:`~pyscanbox.io.sbx_writer.ScanboxOriginalWriter`.
        The binary data is written in MATLAB column-major order, with the
        on-disk layout equivalent to (lines_per_frame, pixels_per_line,
        nchan) per frame.  Values are stored bitwise-complemented
        (raw = 65535 - signal); this class undoes the complement
        automatically.  The companion .mat file contains a nested ``info``
        struct with fields such as ``sz``, ``recordsPerBuffer``, and
        ``channels``.

Example (pyscanbox / original Scanbox files)::

    >>> import pyscanbox.io.sbx_reader
    >>> with pyscanbox.io.sbx_reader.ScanboxOriginalReader('mydata') as reader:
    ...     frame = reader.get_frame(0)

Example (obsolete pyscanbox native format)::

    >>> import pyscanbox.io.sbx_reader
    >>> with pyscanbox.io.sbx_reader.SbxReaderObsolete('mydata') as reader:
    ...     frame = reader.get_frame(0)
"""

import os
import numpy as np
import scipy.io
from typing import Dict, Any, Optional


class SbxReaderObsolete:
    """Obsolete reader for .sbx files in the pyscanbox native format.

    .. deprecated::
        Use :class:`ScanboxOriginalReader` instead, which reads files
        produced by both the original MATLAB Scanbox software and
        pyscanbox's :class:`~pyscanbox.io.sbx_writer.ScanboxOriginalWriter`.

    Provides memory-mapped access to the raw uint16 PMT data and
    convenience methods for extracting frames and channels.

    The binary layout on disk is C-order (row-major) uint16 with
    dimensions (frames, channels, lines_per_frame, pixels_per_line),
    matching what SbxWriterObsolete produces.

    Attributes:
        filepath: Base path (without extension).
        sbx_path: Full path to the .sbx binary file.
        mat_path: Full path to the .mat metadata file.
        metadata: Dictionary of acquisition metadata loaded from .mat.
        data: Memory-mapped numpy array, shape
            (frames, channels, lines_per_frame, pixels_per_line).
    """

    def __init__(self, filepath: str):
        """Initialize .sbx reader.

        Loads the .mat metadata and memory-maps the .sbx binary file.

        Args:
            filepath: Base path without extension (e.g., 'mydata').
                Will load 'mydata.sbx' and 'mydata.mat'.

        Raises:
            FileNotFoundError: If .sbx or .mat file does not exist.
            ValueError: If file size is inconsistent with metadata.
        """
        self.filepath = filepath
        self.sbx_path = f"{filepath}.sbx"
        self.mat_path = f"{filepath}.mat"
        self._mmap: Optional[np.memmap] = None

        if not os.path.exists(self.sbx_path):
            raise FileNotFoundError(f".sbx file not found: {self.sbx_path}")
        if not os.path.exists(self.mat_path):
            raise FileNotFoundError(f".mat file not found: {self.mat_path}")

        self.metadata = self._load_metadata()
        self.data = self._open_sbx()

    # ------------------------------------------------------------------
    # Properties derived from metadata
    # ------------------------------------------------------------------

    @property
    def shape(self):
        """Array shape: (frames, channels, lines_per_frame, pixels_per_line)."""
        return self.data.shape

    @property
    def num_frames(self) -> int:
        """Number of frames in the recording."""
        return int(self.metadata['frames'])

    @property
    def num_channels(self) -> int:
        """Number of PMT channels saved (1 or 2).

        Uses the opened memory-map shape when available (file size is the
        ground truth), otherwise reads ``nchan`` (new format) or ``channels``
        (old format where the value was the raw count, not the MATLAB bitmask).
        """
        if self._mmap is not None:
            return self._mmap.shape[1]
        if 'nchan' in self.metadata:
            return int(self.metadata['nchan'])
        return int(self.metadata['channels'])

    @property
    def lines_per_frame(self) -> int:
        """Number of lines per frame.

        Reads ``sz[0]`` if present (new format), otherwise ``lines_per_frame``.
        """
        if 'sz' in self.metadata:
            sz = self.metadata['sz']
            return int(sz[0] if hasattr(sz, '__len__') else sz)
        return int(self.metadata['lines_per_frame'])

    @property
    def pixels_per_line(self) -> int:
        """Number of pixels per line.

        Reads ``sz[1]`` if present (new format), otherwise ``pixels_per_line``.
        """
        if 'sz' in self.metadata:
            sz = self.metadata['sz']
            return int(sz[1] if hasattr(sz, '__len__') else sz)
        return int(self.metadata['pixels_per_line'])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_metadata(self) -> Dict[str, Any]:
        """Load and flatten the .mat metadata file.

        Returns:
            Dictionary with metadata fields as plain Python scalars or
            strings (scipy internal keys are stripped).

        Raises:
            FileNotFoundError: If .mat file does not exist.
        """
        raw = scipy.io.loadmat(self.mat_path)
        # Detect original Scanbox .mat files (nested 'info' struct, no flat keys).
        if 'info' in raw and not any(
                k for k in raw if not k.startswith('__') and k != 'info'):
            raise ValueError(
                f"{self.mat_path} appears to be an original Scanbox file "
                "(nested 'info' struct rather than flat pyscanbox keys). "
                "Use ScanboxOriginalReader instead of SbxReaderObsolete."
            )
        meta = {}
        for key, val in raw.items():
            if key.startswith('__'):
                continue
            # Unwrap 1-element arrays produced by scipy.io.loadmat
            if isinstance(val, np.ndarray):
                if val.size == 1:
                    meta[key] = val.flat[0]
                elif val.ndim == 2 and val.shape[0] == 1:
                    # Row vector — return as 1-D array
                    meta[key] = val[0]
                else:
                    meta[key] = val
            else:
                meta[key] = val
        return meta

    def _open_sbx(self) -> np.memmap:
        """Memory-map the .sbx binary file.

        Determines the array shape from metadata and validates the file
        size before opening the map.

        Returns:
            numpy.memmap with shape
            (frames, channels, lines_per_frame, pixels_per_line).

        Raises:
            ValueError: If the file size does not match expected shape.
        """
        frames = int(self.metadata['frames'])
        lines = self.lines_per_frame   # resolves sz[0] / lines_per_frame
        pixels = self.pixels_per_line  # resolves sz[1] / pixels_per_line

        actual_bytes = os.path.getsize(self.sbx_path)
        bytes_per_frame_per_ch = lines * pixels * np.dtype(np.uint16).itemsize

        # Channels are derived from file size (ground truth).  Metadata may
        # lag behind if a previous .mat was reused after the .sbx was replaced.
        if actual_bytes == frames * 2 * bytes_per_frame_per_ch:
            channels = 2
        elif actual_bytes == frames * 1 * bytes_per_frame_per_ch:
            channels = 1
        else:
            raise ValueError(
                f"File size mismatch for {self.sbx_path}: "
                f"{actual_bytes} bytes is not consistent with "
                f"{frames} frames × 1 or 2 channels × {lines} lines × "
                f"{pixels} px × 2 bytes."
            )

        # Warn if the file-derived channel count disagrees with metadata.
        # Only `nchan` is unambiguous (the MATLAB `channels` bitmask and the
        # old pyscanbox raw count both use overlapping values).
        if 'nchan' in self.metadata:
            meta_nchan = int(self.metadata['nchan'])
            if meta_nchan != channels:
                import warnings
                warnings.warn(
                    f"{self.sbx_path}: metadata reports {meta_nchan} channel(s) "
                    f"but file size implies {channels}. "
                    "Using file-size-derived value.",
                    stacklevel=3,
                )

        shape = (frames, channels, lines, pixels)
        self._mmap = np.memmap(self.sbx_path, dtype=np.uint16, mode='r',
                               shape=shape)
        return self._mmap

    # ------------------------------------------------------------------
    # Public access methods
    # ------------------------------------------------------------------

    def get_frame(self, index: int) -> np.ndarray:
        """Return a single frame as a numpy array.

        Args:
            index: Frame index (0-based).

        Returns:
            Frame array of shape (channels, lines_per_frame, pixels_per_line),
            dtype uint16.

        Raises:
            IndexError: If index is out of range.
        """
        if index < 0 or index >= self.num_frames:
            raise IndexError(
                f"Frame index {index} out of range [0, {self.num_frames - 1}]"
            )
        return np.array(self.data[index])

    def get_channel(self, channel: int) -> np.ndarray:
        """Return all frames for a single channel.

        Args:
            channel: Channel index (0-based).

        Returns:
            Array of shape (frames, lines_per_frame, pixels_per_line),
            dtype uint16.

        Raises:
            IndexError: If channel index is out of range.
        """
        if channel < 0 or channel >= self.num_channels:
            raise IndexError(
                f"Channel index {channel} out of range "
                f"[0, {self.num_channels - 1}]"
            )
        return np.array(self.data[:, channel, :, :])

    def load(self) -> np.ndarray:
        """Load the entire dataset into memory.

        Returns:
            Array of shape (frames, channels, lines_per_frame, pixels_per_line),
            dtype uint16.

        Note:
            For large files this may consume significant RAM.  Prefer
            get_frame() or get_channel() for selective access.
        """
        return np.array(self.data)

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
            f"SbxReaderObsolete('{self.filepath}', "
            f"shape={self.shape}, dtype=uint16)"
        )


def load_sbx_obsolete(filepath: str) -> tuple:
    """Obsolete convenience function to load a pyscanbox-native .sbx file.

    .. deprecated::
        Use :class:`ScanboxOriginalReader` for files written by pyscanbox
        v0.5+ or by the original MATLAB Scanbox software.

    Args:
        filepath: Base path without extension (e.g., 'mydata').

    Returns:
        Tuple of (data, metadata) where:
            data: numpy array, shape
                (frames, channels, lines_per_frame, pixels_per_line),
                dtype uint16.
            metadata: dict with acquisition parameters from the .mat file.

    Example:
        >>> import pyscanbox.io.sbx_reader
        >>> data, meta = pyscanbox.io.sbx_reader.load_sbx_obsolete('mydata')
        >>> print(data.shape, meta['frames'])
    """
    with SbxReaderObsolete(filepath) as reader:
        data = reader.load()
        metadata = reader.metadata
    return data, metadata


# ---------------------------------------------------------------------------
# Reader for files produced by the original MATLAB Scanbox software
# ---------------------------------------------------------------------------


class ScanboxOriginalReader:
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

    # Mapping from .mat ``channels`` field value to number of active PMT channels.
    _CHANNELS_TO_NCHAN = {1: 2, 2: 1, 3: 1}

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
        """Load and flatten the ``info`` struct from the .mat file.

        Scanbox saves a MATLAB struct named ``info`` into the .mat file.
        ``scipy.io.loadmat`` returns it as a structured numpy array;
        this method unwraps all scalar fields to plain Python scalars.

        Returns:
            Flat dictionary of ``info`` struct fields plus a computed
            ``nchan`` key.

        Raises:
            KeyError: If ``info`` key is absent from the .mat file.
            ValueError: If ``channels`` encodes an unknown PMT configuration.
        """
        raw = scipy.io.loadmat(self.mat_path, squeeze_me=True,
                               struct_as_record=False)
        if 'info' not in raw:
            raise KeyError(
                f"No 'info' struct found in {self.mat_path}. "
                "This file may have been written by the old pyscanbox native "
                "format — use SbxReaderObsolete instead."
            )

        info_obj = raw['info']  # scipy MatlabObject or structured array
        # Convert to a plain dict by iterating over _fieldnames
        flat: Dict[str, Any] = {}
        for field in info_obj._fieldnames:
            val = getattr(info_obj, field)
            flat[field] = val

        # Derive nchan from the channels bitmask
        channels = int(flat['channels'])
        if channels not in self._CHANNELS_TO_NCHAN:
            raise ValueError(
                f"Unexpected 'channels' value {channels} in {self.mat_path}. "
                f"Expected one of {list(self._CHANNELS_TO_NCHAN)}: "
                "1=both PMTs, 2=PMT0, 3=PMT1."
            )
        flat['nchan'] = self._CHANNELS_TO_NCHAN[channels]

        return flat

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
            f"ScanboxOriginalReader('{self.filepath}', "
            f"nframes={self.num_frames}, nchan={self.num_channels}, "
            f"lines={self.lines_per_frame}, pixels={self.pixels_per_line})"
        )
