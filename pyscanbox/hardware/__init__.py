"""Hardware interface modules for Scanbox system.

This package contains modules for interfacing with:
    - AlazarTech digitizer (PMT data acquisition)
    - Main Scanbox controller (Pockels, shutter, mirror)
    - Trinamic motors (knobby motor control)
"""

from pyscanbox.hardware import alazar
from pyscanbox.hardware import controller
from pyscanbox.hardware import motor
from pyscanbox.hardware import protocols

__all__ = ["alazar", "controller", "motor", "protocols"]
