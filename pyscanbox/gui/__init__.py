# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""pyscanbox GUI module.

This module provides the PyQt6-based graphical user interface for the
pyscanbox two-photon microscope control system.

Main components:
- MainWindow: The primary application window
- panels: Control and display panels
- widgets: Individual widget components
"""

from pyscanbox.gui.main_window import MainWindow
from pyscanbox.gui.app_controller import AppController

__all__ = ['MainWindow', 'AppController']
