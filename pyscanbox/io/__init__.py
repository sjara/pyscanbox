"""File I/O modules for .sbx format.

This package handles reading and writing data in the Scanbox-compatible format:
    - .sbx: Raw binary data (MATLAB column-major uint16, bitwise-complemented)
    - .mat: MATLAB info struct metadata (nested 'info' struct, compatible with
            sbxread.m and downstream tools such as Suite2p)
"""

from pyscanbox.io import sbx_writer
from pyscanbox.io import sbx_reader

__all__ = ["sbx_writer", "sbx_reader"]
