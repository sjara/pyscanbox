# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""File I/O modules for .sbx format.

This package handles reading and writing data in the Scanbox-compatible format:
    - .sbx: Raw binary data (MATLAB column-major uint16, bitwise-complemented)
    - .mat: MATLAB info struct metadata (nested 'info' struct, compatible with
            sbxread.m and downstream tools such as Suite2p)

Export utilities:
    - tiff_exporter: Convert .sbx recordings to multi-page TIFF files.
    - meta_exporter: Convert .mat metadata to JSON or YAML.
"""

from pyscanbox.io import sbx_writer
from pyscanbox.io import sbx_reader
from pyscanbox.io import tiff_exporter
from pyscanbox.io import meta_exporter
from pyscanbox.io import metadata

__all__ = ["sbx_writer", "sbx_reader", "tiff_exporter", "meta_exporter"]
