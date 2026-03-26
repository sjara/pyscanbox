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

from . import sbx_writer
from . import sbx_reader
from . import tiff_exporter
from . import meta_exporter

__all__ = ["sbx_writer", "sbx_reader", "tiff_exporter", "meta_exporter"]
