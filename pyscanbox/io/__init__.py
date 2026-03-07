"""File I/O modules for .sbx and .mat formats.

This package handles reading and writing data in Scanbox formats:
    - .sbx: Raw binary data (headerless uint16)
    - .mat: MATLAB metadata for backwards compatibility
"""

from pyscanbox.io import sbx_writer
from pyscanbox.io import mat_writer
from pyscanbox.io import sbx_reader

__all__ = ["sbx_writer", "mat_writer", "sbx_reader"]
