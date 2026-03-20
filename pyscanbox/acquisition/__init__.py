"""Data acquisition and processing modules.

This package contains modules for:
    - Main acquisition loop and scanner control
    - High-speed data reshaping (optimized with Numba)
    - Plugin interface and plugin manager
"""

from pyscanbox.acquisition import scan
from pyscanbox.acquisition import reshape
from pyscanbox.acquisition import plugin

__all__ = ["scan", "reshape", "plugin"]
