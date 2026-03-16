""".sbx file writer for raw PMT data.

This module provides two writer classes:

    SbxWriterObsolete
        Obsolete writer for the **pyscanbox** native format.  Binary data is a
        headerless uint16 C-order dump with shape
        (frames, channels, lines_per_frame, pixels_per_line).  The companion
        .mat file stores flat key/value metadata.  Use
        :class:`ScanboxOriginalWriter` for new recordings.

    ScanboxOriginalWriter
        Writes files in the format produced by the **original MATLAB Scanbox**
        software.  Binary data is in MATLAB column-major order
        ``(nchan, pixels_per_line, lines_per_frame)`` per frame (equivalent to
        C-order ``(lines_per_frame, pixels_per_line, nchan)``).  Values are
        stored as their bitwise complement ``65535 − signal``.  The companion
        .mat file contains a nested ``info`` struct compatible with
        ``sbxread.m`` and downstream tools such as Suite2p.

Example (pyscanbox native format, obsolete)::

    >>> import pyscanbox.io.sbx_writer
    >>> with pyscanbox.io.sbx_writer.SbxWriterObsolete('mydata') as writer:
    ...     writer.write_frame(frame_data)

Example (original Scanbox format)::

    >>> import pyscanbox.io.sbx_writer
    >>> with pyscanbox.io.sbx_writer.ScanboxOriginalWriter(
    ...         'mydata', lines_per_frame=512, pixels_per_line=796,
    ...         nchan=2) as writer:
    ...     writer.write_frame(frame_data)  # shape (nchan, lines, pixels)
"""

import os
import numpy as np
import scipy.io
from typing import Any, Dict, Optional


class SbxWriterObsolete:
    """Obsolete writer for .sbx binary files in the pyscanbox native format.

    .. deprecated::
        Use :class:`ScanboxOriginalWriter` instead, which produces files
        compatible with the original Scanbox MATLAB software and downstream
        tools (Suite2p, sbxread.m, etc.).

    Writes raw uint16 PMT data directly to disk in headerless binary format.

    Attributes:
        filepath: Path to .sbx file (without extension)
        file_handle: Open file handle
        frames_written: Counter for frames written
    """

    def __init__(self, filepath: str):
        """Initialize .sbx writer.

        Args:
            filepath: Output path without extension (e.g., 'mydata').
                Will create 'mydata.sbx'.
        """
        self.filepath = filepath
        self.sbx_path = f"{filepath}.sbx"
        self.file_handle: Optional[object] = None
        self.frames_written = 0
        
        self._open_file()

    def _open_file(self) -> None:
        """Open .sbx file for writing.

        Creates output directory if needed and opens file in binary
        write mode.
        """
        # Create directory if needed
        output_dir = os.path.dirname(self.sbx_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        
        # Open file in binary write mode
        self.file_handle = open(self.sbx_path, 'wb')

    def write_frame(self, frame_data: np.ndarray) -> None:
        """Write one frame of data to .sbx file.

        Args:
            frame_data: Frame data as numpy array (uint16).
                Shape: (channels, lines, pixels) or (lines, pixels)

        Note:
            Data is written directly as raw bytes in C-order (row-major).
            This matches MATLAB's fwrite behavior.

        Raises:
            RuntimeError: If file is not open.
            ValueError: If data type is not uint16.
        """
        if self.file_handle is None:
            raise RuntimeError("File not open")
        
        if frame_data.dtype != np.uint16:
            raise ValueError(f"Data must be uint16, got {frame_data.dtype}")
        
        # Write raw bytes directly
        # Use tofile() for efficient binary write
        frame_data.tofile(self.file_handle)
        
        self.frames_written += 1

    def write_buffer(self, buffer: np.ndarray) -> None:
        """Write raw buffer data (alternative to write_frame).

        Args:
            buffer: Raw uint16 buffer to write
        """
        self.write_frame(buffer)

    def flush(self) -> None:
        """Flush write buffer to disk.

        Forces immediate write of buffered data to disk.
        """
        if self.file_handle is not None:
            self.file_handle.flush()
            os.fsync(self.file_handle.fileno())

    def close(self) -> None:
        """Close .sbx file.

        Flushes buffers and closes file handle.
        """
        if self.file_handle is not None:
            self.flush()
            self.file_handle.close()
            self.file_handle = None
        
        print(f"Wrote {self.frames_written} frames to {self.sbx_path}")

    def get_frames_written(self) -> int:
        """Get number of frames written.

        Returns:
            Number of frames written to file.
        """
        return self.frames_written

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


# ---------------------------------------------------------------------------
# Writer for files produced by the original MATLAB Scanbox software
# ---------------------------------------------------------------------------


class ScanboxOriginalWriter:
    """Writer that produces .sbx/.mat files compatible with original Scanbox.

    The binary layout on disk matches what the original MATLAB Scanbox writes:
    values are stored as their bitwise complement (``stored = 65535 − signal``)
    and laid out in MATLAB column-major order equivalent to the C-order numpy
    shape ``(lines_per_frame, pixels_per_line, nchan)`` per frame.

    The companion .mat file contains a nested ``info`` struct understood by
    ``sbxread.m`` and tools built on top of it (e.g. Suite2p, ScanImageTiffReader
    variants, custom MATLAB pipelines).

    The ``channels`` field in the ``info`` struct follows the Scanbox bitmask
    convention:

    * ``1`` → both PMT0 and PMT1 active (``nchan = 2``)
    * ``2`` → PMT0 only             (``nchan = 1``)
    * ``3`` → PMT1 only             (``nchan = 1``)

    Attributes:
        filepath: Base path without extension.
        sbx_path: Full path to the .sbx binary file.
        mat_path: Full path to the .mat metadata file.
        lines_per_frame: Number of scan lines per frame.
        pixels_per_line: Number of pixels per scan line.
        nchan: Number of active PMT channels (1 or 2).
        scanmode: ``1`` for unidirectional, ``0`` for bidirectional.
        frames_written: Number of frames written so far.
    """

    # Scanbox channels bitmask: maps (nchan, pmt_index) → channels field value.
    # pmt_index is only relevant when nchan == 1.
    _NCHAN_PMT_TO_CHANNELS = {
        (2, 0): 1,   # both channels
        (1, 0): 2,   # PMT0 only
        (1, 1): 3,   # PMT1 only
    }

    def __init__(self, filepath: str, lines_per_frame: int,
                 pixels_per_line: int, nchan: int, scanmode: int = 1,
                 pmt_channel: int = 0,
                 extra_info: Optional[Dict[str, Any]] = None):
        """Initialize the Scanbox-compatible .sbx writer.

        Args:
            filepath: Output base path without extension (e.g. ``'mydata'``).
                Creates ``mydata.sbx`` and ``mydata.mat``.
            lines_per_frame: Number of scan lines per frame.
            pixels_per_line: Number of pixels per scan line.
            nchan: Number of PMT channels to save (1 or 2).
            scanmode: ``1`` for unidirectional (default), ``0`` for
                bidirectional.
            pmt_channel: Which PMT is active when ``nchan == 1``.  ``0``
                selects PMT0 (``channels = 2``), ``1`` selects PMT1
                (``channels = 3``).  Ignored when ``nchan == 2``.
            extra_info: Optional dict of additional fields to merge into the
                ``info`` struct in the .mat file.  Use this to store
                pyscanbox-specific metadata alongside the standard Scanbox
                fields without breaking backward compatibility.

        Raises:
            ValueError: If ``nchan`` is not 1 or 2, or if ``pmt_channel``
                is not 0 or 1 when ``nchan == 1``.
            ValueError: If ``scanmode`` is not 0 or 1.
        """
        if nchan not in (1, 2):
            raise ValueError(f"nchan must be 1 or 2, got {nchan}")
        if nchan == 1 and pmt_channel not in (0, 1):
            raise ValueError(
                f"pmt_channel must be 0 or 1 when nchan == 1, got {pmt_channel}"
            )
        if scanmode not in (0, 1):
            raise ValueError(f"scanmode must be 0 or 1, got {scanmode}")

        self.filepath = filepath
        self.sbx_path = f"{filepath}.sbx"
        self.mat_path = f"{filepath}.mat"
        self.lines_per_frame = lines_per_frame
        self.pixels_per_line = pixels_per_line
        self.nchan = nchan
        self.scanmode = scanmode
        self._pmt_channel = pmt_channel
        self.extra_info: Dict[str, Any] = extra_info or {}
        self.frames_written = 0
        self._file_handle: Optional[object] = None

        output_dir = os.path.dirname(self.sbx_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        self._file_handle = open(self.sbx_path, 'wb')

    def write_frame(self, frame_data: np.ndarray) -> None:
        """Write one frame in Scanbox binary format.

        Accepts data in **wire-format convention** (high values = dark
        background, low values = bright fluorescence signal), matching the
        polarity coming directly from the PMT/Alazar pipeline.  The values
        are written to disk as-is, laid out in C-order shape
        ``(lines_per_frame, pixels_per_line, nchan)`` so that MATLAB reads
        them correctly via its column-major reshape to
        ``[nchan, pixels_per_line, lines_per_frame]``.

        When reading back with :class:`ScanboxOriginalReader`:

        * ``get_frame(invert=True)``  (default) applies ``65535 − stored``
          and returns **signal convention** (high = bright), matching
          ``sbxread.m`` and downstream tools such as Suite2p.
        * ``get_frame(invert=False)`` returns wire-format (high = dark),
          identical to what was passed here — useful for the GUI display
          pipeline, which applies its own inversion internally.

        Args:
            frame_data: Frame data with shape
                ``(nchan, lines_per_frame, pixels_per_line)`` and dtype
                ``uint16``.  Values must be in wire-format convention
                (high = dark).

        Raises:
            RuntimeError: If the file is not open.
            ValueError: If ``frame_data`` dtype is not ``uint16`` or shape
                does not match the dimensions supplied at construction.
        """
        if self._file_handle is None:
            raise RuntimeError("File is not open")
        if frame_data.dtype != np.uint16:
            raise ValueError(
                f"frame_data must be uint16, got {frame_data.dtype}"
            )
        expected_shape = (self.nchan, self.lines_per_frame, self.pixels_per_line)
        if frame_data.shape != expected_shape:
            raise ValueError(
                f"frame_data shape {frame_data.shape} does not match "
                f"expected {expected_shape}"
            )

        # Transpose from (nchan, lines, pixels) to (lines, pixels, nchan).
        # In C-order this produces the same byte sequence that MATLAB reads
        # as Fortran-order [nchan, pixels, lines].
        disk_frame = frame_data.transpose(1, 2, 0)
        disk_frame.tofile(self._file_handle)
        self.frames_written += 1

    def flush(self) -> None:
        """Flush the write buffer to disk."""
        if self._file_handle is not None:
            self._file_handle.flush()
            os.fsync(self._file_handle.fileno())

    def write_mat(self) -> None:
        """Write the companion .mat metadata file.

        Creates a .mat file containing a MATLAB ``info`` struct with the
        standard Scanbox fields required by ``sbxread.m``.  Any
        ``extra_info`` fields supplied at construction are merged in.

        The ``info`` struct includes:

        * ``sz``               – ``[lines_per_frame, pixels_per_line]``
        * ``recordsPerBuffer`` – lines per frame
        * ``channels``         – PMT bitmask (1/2/3)
        * ``scanbox_version``  – 2 (modern Scanbox format)
        * ``scanmode``         – 1 = unidirectional, 0 = bidirectional
        * ``max_idx``          – index of the last frame (``frames − 1``)
        """
        key = (self.nchan, self._pmt_channel) if self.nchan == 1 else (2, 0)
        channels_bitmask = self._NCHAN_PMT_TO_CHANNELS[key]

        info: Dict[str, Any] = {
            'sz': np.array([[self.lines_per_frame, self.pixels_per_line]],
                           dtype=np.int64),
            'recordsPerBuffer': np.int64(self.lines_per_frame),
            'channels': np.int64(channels_bitmask),
            'scanbox_version': np.int64(2),
            'scanmode': np.int64(self.scanmode),
            'max_idx': np.int64(self.frames_written - 1),
        }
        # Merge extra_info last so callers can override defaults if needed.
        info.update(self.extra_info)

        output_dir = os.path.dirname(self.mat_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        scipy.io.savemat(self.mat_path, {'info': info}, oned_as='row')

    def close(self) -> None:
        """Flush, close the .sbx file, and write the .mat metadata."""
        if self._file_handle is not None:
            self.flush()
            self._file_handle.close()
            self._file_handle = None
        self.write_mat()

    def get_frames_written(self) -> int:
        """Return the number of frames written so far."""
        return self.frames_written

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def __repr__(self) -> str:
        return (
            f"ScanboxOriginalWriter('{self.filepath}', "
            f"nchan={self.nchan}, lines={self.lines_per_frame}, "
            f"pixels={self.pixels_per_line}, frames_written={self.frames_written})"
        )


def write_sbx_file_obsolete(filepath: str, data: np.ndarray) -> None:
    """Obsolete convenience function to write dataset in pyscanbox native format.

    .. deprecated::
        Use :func:`write_sbx_scanbox` instead, which produces files compatible
        with the original Scanbox MATLAB software.

    Args:
        filepath: Output path without extension
        data: Full dataset as numpy array (uint16).
            Shape: (frames, channels, lines, pixels) or (frames, lines, pixels)

    Example:
        >>> import numpy as np
        >>> data = np.zeros((1000, 2, 512, 796), dtype=np.uint16)
        >>> write_sbx_file_obsolete('mydata', data)
    """
    with SbxWriterObsolete(filepath) as writer:
        if data.ndim == 4:
            # (frames, channels, lines, pixels)
            for frame in data:
                writer.write_frame(frame)
        elif data.ndim == 3:
            # (frames, lines, pixels)
            for frame in data:
                writer.write_frame(frame)
        else:
            raise ValueError(f"Data must be 3D or 4D, got shape {data.shape}")


def write_sbx_scanbox(filepath: str, data: np.ndarray, scanmode: int = 1,
                      pmt_channel: int = 0,
                      extra_info: Optional[Dict[str, Any]] = None) -> None:
    """Write an entire dataset in original Scanbox-compatible format.

    Convenience wrapper around :class:`ScanboxOriginalWriter`.  The output
    .sbx/.mat pair can be read by ``sbxread.m``, Suite2p, and any other tool
    that supports the original Scanbox file format.

    Args:
        filepath: Output base path without extension (e.g. ``'mydata'``).
            Creates ``mydata.sbx`` and ``mydata.mat``.
        data: Full dataset, shape
            ``(frames, nchan, lines_per_frame, pixels_per_line)``,
            dtype ``uint16``.  Values must be in **wire-format convention**
            (high = dark background, low = bright fluorescence), matching
            the PMT/Alazar acquisition pipeline.  Written to disk as-is.
        scanmode: ``1`` for unidirectional (default), ``0`` for bidirectional.
        pmt_channel: Active PMT index (0 or 1) when ``nchan == 1``.
            Ignored when ``nchan == 2``.
        extra_info: Optional dict of additional fields to store in the
            ``info`` struct (e.g. pyscanbox version, frame rate).

    Example:
        >>> import numpy as np
        >>> import pyscanbox.io.sbx_writer
        >>> data = np.zeros((100, 2, 512, 796), dtype=np.uint16)
        >>> pyscanbox.io.sbx_writer.write_sbx_scanbox('mydata', data)
    """
    if data.ndim != 4:
        raise ValueError(
            f"data must be 4-D (frames, nchan, lines, pixels), got shape {data.shape}"
        )
    nframes, nchan, lines, pixels = data.shape
    with ScanboxOriginalWriter(filepath, lines_per_frame=lines,
                               pixels_per_line=pixels, nchan=nchan,
                               scanmode=scanmode, pmt_channel=pmt_channel,
                               extra_info=extra_info) as writer:
        for frame in data:
            writer.write_frame(frame)
