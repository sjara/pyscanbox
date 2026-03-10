"""Data acquisition and processing modules.

This package contains modules for:
    - Main acquisition loop and scanner control
    - High-speed data reshaping (optimized with Numba)
"""

from pyscanbox.acquisition import scan
from pyscanbox.acquisition import reshape

__all__ = ["scan", "reshape"]
