"""Hardware emulation for Linux/offline development.

This module provides mock implementations of hardware interfaces to enable
development and testing without physical hardware. The emulators provide
functional interfaces that track state and generate synthetic data.

Usage:
    Enable emulation mode in configuration:
    ```yaml
    emulation:
      enabled: true
      verbose: false  # Log emulation events
    ```

    The hardware modules will automatically use emulators when enabled.
"""

from pyscanbox.emulator import mock_serial
from pyscanbox.emulator import mock_alazar

__all__ = ["mock_serial", "mock_alazar"]
