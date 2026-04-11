# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

""".sbx file writer for raw PMT data.

This module provides :class:`SbxWriter`, which writes files in the format
produced by the **original MATLAB Scanbox** software.  Binary data is in
MATLAB column-major order ``(nchan, pixels_per_line, lines_per_frame)`` per
frame (equivalent to C-order ``(lines_per_frame, pixels_per_line, nchan)``).
Values are stored as their bitwise complement ``65535 − signal``.  The
companion .mat file contains a nested ``info`` struct compatible with
``sbxread.m`` and downstream tools such as Suite2p.

Example::

    >>> import pyscanbox.io.sbx_writer
    >>> with pyscanbox.io.sbx_writer.SbxWriter(
    ...         'mydata', lines_per_frame=512, pixels_per_line=796,
    ...         nchan=2) as writer:
    ...     writer.write_frame(frame_data)  # shape (nchan, lines, pixels)
"""

import os
import numpy as np
import scipy.io
from typing import Any, Dict, Optional

from pyscanbox.io import metadata


# ---------------------------------------------------------------------------
# Internal helper: map AcquisitionMetadata → .mat info struct dict
# ---------------------------------------------------------------------------

def _metadata_to_mat_dict(meta: metadata.AcquisitionMetadata) -> Dict[str, Any]:
    """Convert an :class:`~pyscanbox.io.metadata.AcquisitionMetadata` to a .mat-compatible dict.

    This is the single authoritative mapping from logical acquisition
    fields (snake_case) to the MATLAB ``info`` struct field names used by
    ``sbxread.m``, Suite2p, and other downstream tools.

    Args:
        meta: Populated :class:`~pyscanbox.io.metadata.AcquisitionMetadata` instance.

    Returns:
        Dictionary ready to be passed to ``scipy.io.savemat`` as the
        ``info`` struct.
    """
    bytes_per_buffer = (
        meta.post_trigger_samples * meta.records_per_buffer * meta.nchan * 2
    )
    d: Dict[str, Any] = {
        # --- Fields required by sbxread.m ---
        # sz: [lines_per_frame, pixels_per_line] — mirrors size(chA') in MATLAB
        'sz': np.array([[meta.lines_per_frame, meta.pixels_per_line]],
                       dtype=np.int64),
        'recordsPerBuffer': np.int64(meta.records_per_buffer),
        # channels bitmask: 1=both PMT0+1, 2=PMT0 only, 3=PMT1 only
        'channels': np.int64(meta.channels_mask),
        'scanbox_version': np.int64(2),
        'scanmode': np.int64(meta.scanmode),
        # max_idx: index of the last frame (sbxread.m v2 also derives this
        # from file size, but we store it explicitly for direct access).
        'max_idx': np.int64(meta.frames - 1),
        # nchan is derived in sbxread.m from channels; we store it explicitly
        # so SbxReader can use it without re-deriving.
        'nchan': np.int64(meta.nchan),
        # --- Additional original Scanbox fields ---
        'resfreq': np.int64(meta.resonant_freq),
        'postTriggerSamples': np.int64(meta.post_trigger_samples),
        'bytesPerBuffer': np.int64(bytes_per_buffer),
        'ballmotion': meta.ballmotion,
        'abort_bit': np.int64(meta.abort_bit),
        # config sub-struct mirrors scanbox_getconfig() in scanbox.m.
        # Suite2p accesses config.magnification and config.lines unconditionally.
        # magnification is 1-based to match the MATLAB listbox Value convention.
        # magnification_list contains float zoom values (1.0, 1.2, ..., 8.0).
        'config': {
            'wavelength':   np.int64(meta.laser_wavelength),
            'frames':       np.int64(meta.frames),
            'lines':        np.int64(meta.lines_per_frame),
            'magnification': np.int64(meta.magnification + 1),
            'magnification_list': np.array(meta.magnification_list, dtype=np.float64),
            'pmt0_gain':    np.float64(meta.pmt0_gain),
            'pmt1_gain':    np.float64(meta.pmt1_gain),
            'knobby': {
                'pos': {
                    'x': np.float64(meta.knobby_x),
                    'y': np.float64(meta.knobby_y),
                    'z': np.float64(meta.knobby_z),
                    'a': np.float64(meta.knobby_a),
                },
            },
        },
        'fold_lines':       np.int64(meta.fold_lines),
        'otwave':           meta.otwave,
        'otwave_um':        meta.otwave_um,
        'otparam':          meta.otparam,
        'otwavestyle':      np.int64(meta.otwavestyle),
        'volscan':          np.int64(meta.volscan),
        'power_depth_link': np.int64(meta.power_depth_link),
        'opto2pow':         meta.opto2pow,
        'area_line':        np.int64(meta.area_line),
        'objective':        meta.objective,
        'messages':         np.array(meta.messages, dtype=object),
        'usernotes':        meta.usernotes,
        # TTL event timestamps (mirrors sb_timestamps.m field names)
        'frame':            meta.ttl_frame,
        'line':             meta.ttl_line,
        'event_id':         meta.ttl_event_id,
        # --- pyscanbox-specific fields (not in original MATLAB info) ---
        'frames':           np.int64(meta.frames),
        'lines_per_frame':  np.int64(meta.lines_per_frame),
        'pixels_per_line':  np.int64(meta.pixels_per_line),
        'sample_rate':      np.int64(meta.sample_rate),
        'magnification':    np.int64(meta.magnification),
        'pockels_base':     np.int64(meta.pockels_base),
        'pockels_active':   np.int64(meta.pockels_active),
        'timestamp':        meta.timestamp,
        'pyscanbox_version': meta.pyscanbox_version,
        'objective_type':   meta.objective_type,
        'laser_type':       meta.laser_type,
    }
    # Merge plugin data last so plugins can add extra fields.
    d.update(meta.plugin_data)
    return d


# ---------------------------------------------------------------------------
# Writer for files produced by the original MATLAB Scanbox software
# ---------------------------------------------------------------------------

class SbxWriter:
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

        When reading back with :class:`SbxReader`:

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

    def write_mat(self,
                  metadata: Optional[metadata.AcquisitionMetadata] = None) -> None:
        """Write the companion .mat metadata file.

        When *metadata* is supplied the full set of Scanbox-compatible
        fields (as returned by :func:`_metadata_to_mat_dict`) is written,
        producing a ``.mat`` file readable by ``sbxread.m``, Suite2p,
        and other downstream tools.

        When *metadata* is ``None`` a minimal ``.mat`` file is written
        using only the geometry/mode fields known at construction time,
        plus any ``extra_info`` dict supplied there.  This path exists
        for standalone use of :class:`SbxWriter` without a full
        :class:`~pyscanbox.io.metadata.AcquisitionMetadata`.

        Args:
            metadata: Optional :class:`~pyscanbox.io.metadata.AcquisitionMetadata`
                containing all acquisition fields.  When provided it takes
                precedence over ``extra_info``.
        """
        if metadata is not None:
            info = _metadata_to_mat_dict(metadata)
        else:
            key = (self.nchan, self._pmt_channel) if self.nchan == 1 else (2, 0)
            channels_bitmask = self._NCHAN_PMT_TO_CHANNELS[key]
            info = {
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

    def close(self,
              metadata: Optional[metadata.AcquisitionMetadata] = None) -> None:
        """Flush, close the .sbx file, and write the .mat metadata.

        Args:
            metadata: Optional :class:`~pyscanbox.io.metadata.AcquisitionMetadata`
                forwarded to :meth:`write_mat`.  When ``None`` the minimal
                fallback ``.mat`` is written instead.
        """
        if self._file_handle is not None:
            self.flush()
            self._file_handle.close()
            self._file_handle = None
        self.write_mat(metadata)

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
            f"SbxWriter('{self.filepath}', "
            f"nchan={self.nchan}, lines={self.lines_per_frame}, "
            f"pixels={self.pixels_per_line}, frames_written={self.frames_written})"
        )


def write_sbx_scanbox(filepath: str, data: np.ndarray, scanmode: int = 1,
                      pmt_channel: int = 0,
                      extra_info: Optional[Dict[str, Any]] = None) -> None:
    """Write an entire dataset in original Scanbox-compatible format.

    Convenience wrapper around :class:`SbxWriter`.  The output
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
    with SbxWriter(filepath, lines_per_frame=lines,
                               pixels_per_line=pixels, nchan=nchan,
                               scanmode=scanmode, pmt_channel=pmt_channel,
                               extra_info=extra_info) as writer:
        for frame in data:
            writer.write_frame(frame)
