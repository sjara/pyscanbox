# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""pyscanbox: Python implementation of Scanbox two-photon microscope software.

This package provides hardware control and data acquisition for two-photon
microscopy using the Scanbox system.

Main modules:
    hardware: Hardware interface modules for Alazar, motors, and controller
    acquisition: Data acquisition and processing logic
    io: File I/O for .sbx and .mat formats
    utils: Utility functions and helpers
    gui: PyQt-based graphical user interface (Phase 3)
"""

__version__ = "1.6.5"
__author__ = "Santiago Jaramillo"

# Import main configuration module
from pyscanbox import config

__all__ = ["config", "__version__", "__author__"]
