# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""TIFF export for .sbx recordings.

This module provides functions to write Scanbox imaging data to
multi-page TIFF files, suitable for use with ImageJ/Fiji, Suite2p,
and other downstream analysis tools.

Frames are written one page at a time so that large recordings do not
need to be fully loaded into RAM.

Example::

    >>> import pyscanbox.io.sbx_reader
    >>> import pyscanbox.io.tiff_exporter
    >>> with pyscanbox.io.sbx_reader.SbxReader('mydata') as reader:
    ...     pyscanbox.io.tiff_exporter.save_channel_as_tiff(reader, 'mydata_ch0.tif')

"""

import os
import numpy as np
import tifffile


def save_channel_as_tiff(reader, output_path, channel=0, invert=True,
                         bigtiff=None, progress=False):
    """Write all frames of a single PMT channel to a multi-page TIFF.

    Frames are written incrementally (one page per frame) so that large
    recordings are handled without loading the entire dataset into RAM.

    The output uses uint16 values throughout to preserve dynamic range.
    The file is written in BigTIFF format automatically when the estimated
    size exceeds 4 GB, or when ``bigtiff=True`` is passed.

    Args:
        reader: An open :class:`~pyscanbox.io.sbx_reader.SbxReader` instance.
        output_path: Destination ``.tif`` file path.
        channel: PMT channel index to export (0-based, default ``0``).
        invert: If ``True`` (default), pass ``invert=True`` to the reader so
            that pixel values use the **signal convention** (high = bright),
            which matches downstream tools such as Suite2p.
            Pass ``False`` only if you need the raw wire-format values.
        bigtiff: Force BigTIFF mode.  If ``None`` (default), BigTIFF is
            selected automatically when the estimated output size exceeds
            4 GB (``2**32`` bytes).
        progress: If ``True``, print a simple frame counter to stdout.

    Raises:
        IndexError: If ``channel`` is out of range for this recording.

    Example::

        >>> with pyscanbox.io.sbx_reader.SbxReader('mydata') as r:
        ...     pyscanbox.io.tiff_exporter.save_channel_as_tiff(
        ...         r, 'mydata_ch0.tif', channel=0)
    """
    if channel < 0 or channel >= reader.num_channels:
        raise IndexError(
            f"Channel {channel} out of range [0, {reader.num_channels - 1}]"
        )

    nframes = reader.num_frames
    lines = reader.lines_per_frame
    pixels = reader.pixels_per_line

    # Decide BigTIFF automatically: uint16 = 2 bytes per pixel.
    estimated_bytes = nframes * lines * pixels * 2
    use_bigtiff = bigtiff if bigtiff is not None else (estimated_bytes > 2**32)

    metadata = {
        'axes': 'TYX',
        'Channel': {'Name': [f'PMT{channel}']},
    }

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with tifffile.TiffWriter(output_path, bigtiff=use_bigtiff) as tif:
        for frame_idx in range(nframes):
            if progress:
                print(f'\r  Writing frame {frame_idx + 1}/{nframes}',
                      end='', flush=True)
            # get_frame returns shape (nchan, lines, pixels)
            frame = reader.get_frame(frame_idx, invert=invert)
            page = frame[channel]   # shape: (lines, pixels), dtype uint16
            tif.write(page, contiguous=True)

    if progress:
        print()  # newline after progress line


def save_all_channels_as_tiff(reader, output_base, invert=True,
                               bigtiff=None, progress=False):
    """Write each PMT channel to its own multi-page TIFF file.

    The output filenames are derived from ``output_base`` by appending
    ``_ch0.tif``, ``_ch1.tif``, etc.

    Args:
        reader: An open SbxReader instance.
        output_base: Base path for output files (extension is ignored or
            omitted; suffixes are appended automatically).
        invert: Passed to :func:`save_channel_as_tiff`.
        bigtiff: Passed to :func:`save_channel_as_tiff`.
        progress: Passed to :func:`save_channel_as_tiff`.

    Returns:
        List of output file paths that were written.

    Example::

        >>> with pyscanbox.io.sbx_reader.SbxReader('mydata') as r:
        ...     paths = pyscanbox.io.tiff_exporter.save_all_channels_as_tiff(
        ...         r, 'mydata')
        >>> print(paths)  # ['mydata_ch0.tif', 'mydata_ch1.tif']
    """
    # Strip any extension the user may have included in the base path.
    base, _ = os.path.splitext(output_base)
    paths = []
    for ch in range(reader.num_channels):
        out_path = f'{base}_ch{ch}.tif'
        if progress:
            print(f'Channel {ch} → {out_path}')
        save_channel_as_tiff(reader, out_path, channel=ch,
                             invert=invert, bigtiff=bigtiff, progress=progress)
        paths.append(out_path)
    return paths
