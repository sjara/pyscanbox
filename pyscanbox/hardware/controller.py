"""Main Scanbox controller interface for Pockels, shutter, and mirror control.

This module provides serial communication with the main Scanbox controller
(PSoC 5LP) at 1,000,000 baud using 3-byte command packets.

Protocol:
    All commands are 3-byte packets: [Command_ID, Param1, Param2]
    
    Commands:
        Pockels Cell (ID 8):  [8, base_power, active_power]
        Epi/2P Mirror (ID 5): [5, 0, 0] (2P) or [5, 0, 1] (Epi)
        Shutter (ID 16):      [16, 0, 1] (Open) or [16, 0, 0] (Close)

Reference:
    Original MATLAB implementation: sb/sb_open.m, sb/sb_pockels.m,
    sb/sb_shutter.m, sb/sb_mirror.m

Example:
    >>> import pyscanbox.hardware.controller
    >>> controller = pyscanbox.hardware.controller.ScanboxController(config)
    >>> controller.open()
    >>> controller.set_pockels(base=50, active=100)
    >>> controller.set_shutter(open=True)
"""

import time
from typing import Optional


def _get_serial_module(use_emulation: bool):
    """Get appropriate serial module based on emulation setting.
    
    Args:
        use_emulation: If True, use mock serial
        
    Returns:
        Serial module (either serial or mock_serial)
    """
    if use_emulation:
        from pyscanbox.emulator import mock_serial
        return mock_serial
    else:
        import serial
        return serial


class ScanboxController:
    """Interface to main Scanbox controller box.

    This class handles serial communication with the PSoC 5LP-based
    controller for Pockels cell, shutter, and epi/2P mirror control.

    Attributes:
        port: Serial port object
        com_port: COM port name (e.g., 'COM3')
        baud_rate: Baud rate (1,000,000 for Scanbox)
        timeout: Serial communication timeout in seconds
    """

    # Command IDs
    CMD_SCAN = 4
    CMD_MIRROR = 5
    CMD_POCKELS = 8
    CMD_SHUTTER = 16

    def __init__(self, config: dict):
        """Initialize Scanbox controller.

        Args:
            config: Configuration dictionary with controller settings.
                Must contain 'controller' key with COM port and parameters.
        """
        self.config = config
        self.com_port = config['controller']['com_port']
        self.baud_rate = config['controller']['baud_rate']
        self.timeout = config['controller']['timeout']
        
        # Check if emulation is enabled
        self.use_emulation = config.get('emulation', {}).get('enabled', False)
        self.emulation_verbose = config.get('emulation', {}).get('verbose', False)
        
        self.port: Optional[object] = None
        self.is_open = False
        
        # State tracking
        self.current_pockels = {'base': 0, 'active': 0}
        self.shutter_open = False
        self.mirror_mode = '2p'  # '2p' or 'epi'
        self.scan_running = False

    def open(self) -> None:
        """Open serial connection to controller.

        Opens the serial port with appropriate settings for Scanbox
        controller communication.

        Reference:
            See sb/sb_open.m for serial port settings.

        Raises:
            serial.SerialException: If port cannot be opened.
        """
        # Get appropriate serial module
        serial_module = _get_serial_module(self.use_emulation)
        
        self.port = serial_module.Serial(
            port=self.com_port,
            baudrate=self.baud_rate,
            timeout=self.timeout,
            bytesize=serial_module.EIGHTBITS if not self.use_emulation else 8,
            parity=serial_module.PARITY_NONE if not self.use_emulation else 'N',
            stopbits=serial_module.STOPBITS_ONE if not self.use_emulation else 1,
        )
        
        # Configure emulation verbosity if using mock
        if self.use_emulation and hasattr(self.port, 'verbose'):
            self.port.verbose = self.emulation_verbose
        
        self.is_open = True
        
        # Wait for controller to reset after serial connection (real hardware only)
        if not self.use_emulation:
            time.sleep(2.0)
        
        # Flush any startup data
        self.port.reset_input_buffer()
        self.port.reset_output_buffer()

    def close(self) -> None:
        """Close serial connection to controller."""
        if self.port is not None and self.port.is_open:
            self.port.close()
        
        self.is_open = False

    def _send_command(self, cmd_id: int, param1: int, param2: int) -> None:
        """Send 3-byte command packet to controller.

        Args:
            cmd_id: Command ID byte
            param1: First parameter byte
            param2: Second parameter byte

        Raises:
            RuntimeError: If port is not open.
            ValueError: If parameters are out of range.
        """
        if not self.is_open or self.port is None:
            raise RuntimeError("Controller port not open. Call open() first.")
        
        # Validate byte values
        if not (0 <= cmd_id <= 255):
            raise ValueError(f"Command ID must be 0-255, got {cmd_id}")
        if not (0 <= param1 <= 255):
            raise ValueError(f"Parameter 1 must be 0-255, got {param1}")
        if not (0 <= param2 <= 255):
            raise ValueError(f"Parameter 2 must be 0-255, got {param2}")
        
        # Send 3-byte packet
        packet = bytes([cmd_id, param1, param2])
        self.port.write(packet)

    def set_pockels(self, base: int, active: int) -> None:
        """Set Pockels cell power levels.

        Args:
            base: Base power level (0-255). Power during flyback/idle.
            active: Active power level (0-255). Power during line scan.

        Reference:
            See sb/sb_pockels.m
        """
        self._send_command(self.CMD_POCKELS, base, active)
        self.current_pockels = {'base': base, 'active': active}

    def set_shutter(self, open: bool) -> None:
        """Set laser shutter state.

        Args:
            open: True to open shutter, False to close.

        Reference:
            See sb/sb_shutter.m
        """
        param2 = 1 if open else 0
        self._send_command(self.CMD_SHUTTER, 0, param2)
        self.shutter_open = open

    def set_mirror(self, mode: str) -> None:
        """Set epi/2P mirror position using Firgelli actuator.

        Args:
            mode: Mirror mode, either '2p' or 'epi'.

        Reference:
            See sb/sb_mirror.m

        Raises:
            ValueError: If mode is not '2p' or 'epi'.
        """
        if mode not in ['2p', 'epi']:
            raise ValueError(f"Mode must be '2p' or 'epi', got '{mode}'")
        
        param2 = 0 if mode == '2p' else 1
        self._send_command(self.CMD_MIRROR, 0, param2)
        self.mirror_mode = mode

    def get_current_pockels(self) -> dict:
        """Get current Pockels cell settings.

        Returns:
            Dictionary with 'base' and 'active' power levels.
        """
        return self.current_pockels.copy()

    def get_shutter_state(self) -> bool:
        """Get current shutter state.

        Returns:
            True if shutter is open, False if closed.
        """
        return self.shutter_open

    def get_mirror_mode(self) -> str:
        """Get current mirror mode.

        Returns:
            Current mirror mode ('2p' or 'epi').
        """
        return self.mirror_mode

    def start_scan(self) -> None:
        """Start scanning.

        Sends command to start the resonant scanner and galvo mirrors.
        Does NOT start PMTs or data acquisition - this only starts
        the physical scanning mechanism.

        Reference:
            See sb/sb_scan.m (sends [4, 0, 1])
        """
        self._send_command(self.CMD_SCAN, 0, 1)
        self.scan_running = True

    def stop_scan(self) -> None:
        """Stop scanning.

        Sends abort command to stop the scanning system.

        Reference:
            See sb/sb_abort.m
        """
        self._send_command(self.CMD_SCAN, 0, 0)
        self.scan_running = False

    def get_scan_state(self) -> bool:
        """Get current scan state.

        Returns:
            True if scanning is running, False if stopped.
        """
        return self.scan_running
