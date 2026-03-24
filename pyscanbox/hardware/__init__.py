# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Hardware interface modules for Scanbox system.

This package contains modules for interfacing with:
    - AlazarTech digitizer (PMT data acquisition)
    - Main Scanbox controller (PSoC 5LP - Pockels, shutter, mirror)
    - Trinamic motors (knobby motor control)
    - Knobby display (Arduino-based position controller)
"""

from pyscanbox.hardware import alazar
from pyscanbox.hardware import controller
from pyscanbox.hardware import motor
from pyscanbox.hardware import knobby
from pyscanbox.hardware import protocols

__all__ = ["alazar", "controller", "motor", "knobby", "protocols"]
