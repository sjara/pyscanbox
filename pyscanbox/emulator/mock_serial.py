"""Mock serial interface for controller and motor emulation.

This module provides a mock serial.Serial replacement that:
- Tracks hardware state for Scanbox controller (Pockels, shutter, mirror, scan)
- Returns valid TMCL responses for Trinamic motor commands
- Prevents crashes during Linux/offline development

Example:
    >>> import pyscanbox.emulator.mock_serial as mock_serial
    >>> port = mock_serial.Serial('COM3', 1000000)
    >>> port.write(bytes([8, 50, 100]))  # Pockels command
    >>> print(port.state['pockels'])  # (50, 100)
"""

import time
import logging
from typing import Optional, Dict, Any, Callable
from pyscanbox.hardware import protocols


logger = logging.getLogger(__name__)


class Serial:
    """Mock serial port for hardware emulation.

    This class emulates pyserial's Serial interface, tracking hardware
    state and responding to commands appropriately.

    Attributes:
        port: Port name (e.g., 'COM3')
        baudrate: Baud rate
        timeout: Read timeout in seconds
        is_open: Connection state
        state: Dictionary tracking hardware state
        verbose: Whether to log emulation events
    """

    # Scanbox controller command IDs
    CMD_SCAN = 4
    CMD_MIRROR = 5
    CMD_POCKELS = 8
    CMD_SHUTTER = 16
    CMD_UNIDIRECTIONAL = 33
    CMD_BIDIRECTIONAL = 34

    def __init__(self, port: str = 'COM1', baudrate: int = 9600,
                 bytesize: int = 8, parity: str = 'N', stopbits: int = 1,
                 timeout: Optional[float] = None, **kwargs):
        """Initialize mock serial port.

        Args:
            port: Port name
            baudrate: Baud rate
            bytesize: Data bits
            parity: Parity setting
            stopbits: Stop bits
            timeout: Read timeout in seconds
            **kwargs: Additional serial parameters (ignored)
        """
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.timeout = timeout
        self.is_open = True
        self.verbose = False

        # Hardware state tracking
        self.state: Dict[str, Any] = {
            'pockels': (0, 0),  # (base, active)
            'shutter': False,
            'mirror': '2p',
            'scan_mode': 'unidirectional',
            'motor_positions': [0, 0, 0, 0],  # 4 motors
            'motor_velocities': [0, 0, 0, 0],
        }

        # Buffer for responses
        self._response_buffer = bytearray()

        # Last bytes written to this port (useful for test assertions)
        self._last_written: bytes = b''

        logger.info(f"Mock serial port opened: {port} @ {baudrate} baud")

    def write(self, data: bytes) -> int:
        """Write data to mock serial port.

        Parses commands and updates internal state.

        Args:
            data: Bytes to write

        Returns:
            Number of bytes written.
        """
        if not self.is_open:
            raise RuntimeError("Port is not open")

        self._last_written = bytes(data)

        # Determine command type by length and baudrate
        if len(data) == 3:
            # Scanbox controller command (1 Mbaud)
            self._handle_scanbox_command(data)
        elif len(data) == 9:
            # TMCL command (57600 baud)
            self._handle_tmcl_command(data)

        return len(data)

    def read(self, size: int = 1) -> bytes:
        """Read data from mock serial port.

        Returns buffered response data.

        Args:
            size: Number of bytes to read

        Returns:
            Bytes read from buffer.
        """
        if not self.is_open:
            raise RuntimeError("Port is not open")

        # Return data from response buffer
        if len(self._response_buffer) == 0:
            # No data available
            return bytes()

        # Read up to size bytes
        data = bytes(self._response_buffer[:size])
        self._response_buffer = self._response_buffer[size:]

        return data

    def close(self) -> None:
        """Close mock serial port."""
        self.is_open = False
        logger.info(f"Mock serial port closed: {self.port}")

    def reset_input_buffer(self) -> None:
        """Reset input buffer."""
        self._response_buffer.clear()

    def reset_output_buffer(self) -> None:
        """Reset output buffer (no-op for mock)."""
        pass

    @property
    def in_waiting(self) -> int:
        """Return number of bytes available to read.
        
        This property mimics pyserial's in_waiting attribute.
        
        Returns:
            Number of bytes in the input buffer.
        """
        return len(self._response_buffer)

    def _handle_scanbox_command(self, data: bytes) -> None:
        """Handle 3-byte Scanbox controller command.

        Args:
            data: 3-byte command array
        """
        cmd_id = data[0]
        param1 = data[1]
        param2 = data[2]

        if cmd_id == self.CMD_POCKELS:
            self.state['pockels'] = (param1, param2)
            if self.verbose:
                logger.debug(f"Pockels set: base={param1}, active={param2}")

        elif cmd_id == self.CMD_SHUTTER:
            self.state['shutter'] = bool(param2)
            if self.verbose:
                logger.debug(f"Shutter: {'open' if param2 else 'closed'}")

        elif cmd_id == self.CMD_MIRROR:
            self.state['mirror'] = 'epi' if param2 else '2p'
            if self.verbose:
                logger.debug(f"Mirror: {self.state['mirror']}")

        elif cmd_id == self.CMD_SCAN:
            self.state['scan_running'] = bool(param2)
            if self.verbose:
                logger.debug(f"Scan: {'started' if param2 else 'stopped'}")

        elif cmd_id == self.CMD_UNIDIRECTIONAL:
            self.state['scan_mode'] = 'unidirectional'
            if self.verbose:
                logger.debug("Scan mode: unidirectional")

        elif cmd_id == self.CMD_BIDIRECTIONAL:
            self.state['scan_mode'] = 'bidirectional'
            if self.verbose:
                logger.debug("Scan mode: bidirectional")

        else:
            if self.verbose:
                logger.debug(f"Unknown command: {cmd_id}")

    def _handle_tmcl_command(self, data: bytes) -> None:
        """Handle 9-byte TMCL motor command.

        Parses command and generates appropriate response.

        Args:
            data: 9-byte TMCL packet
        """
        # Parse TMCL packet
        module_addr = data[0]
        cmd = data[1]
        cmd_type = data[2]
        motor = data[3]
        value = int.from_bytes(data[4:8], byteorder='big', signed=False)

        # Convert to signed if needed
        if value >= (1 << 31):
            value -= (1 << 32)

        # Handle different TMCL commands
        if cmd == 4:  # MVP (move to position)
            if cmd_type == 0:  # Absolute
                if 0 <= motor < 4:
                    self.state['motor_positions'][motor] = value
                    if self.verbose:
                        logger.debug(f"Motor {motor} moved to position {value}")
            elif cmd_type == 1:  # Relative
                if 0 <= motor < 4:
                    self.state['motor_positions'][motor] += value
                    if self.verbose:
                        logger.debug(f"Motor {motor} moved by {value}")

        elif cmd == 6:  # GAP (get axis parameter)
            # Return current position for parameter type 1
            if cmd_type == 1 and 0 <= motor < 4:
                value = self.state['motor_positions'][motor]

        elif cmd == 5:  # SAP (set axis parameter)
            pass  # Just acknowledge

        elif cmd == 1:  # ROR (rotate right)
            if 0 <= motor < 4:
                self.state['motor_velocities'][motor] = value
                if self.verbose:
                    logger.debug(f"Motor {motor} rotating right at {value}")

        elif cmd == 2:  # ROL (rotate left)
            if 0 <= motor < 4:
                self.state['motor_velocities'][motor] = -value
                if self.verbose:
                    logger.debug(f"Motor {motor} rotating left at {value}")

        elif cmd == 3:  # MST (motor stop)
            if 0 <= motor < 4:
                self.state['motor_velocities'][motor] = 0
                if self.verbose:
                    logger.debug(f"Motor {motor} stopped")

        # Generate TMCL response
        response = self._build_tmcl_response(cmd, value)
        self._response_buffer.extend(response)

    def _build_tmcl_response(self, command: int, value: int) -> bytes:
        """Build TMCL response packet.

        Args:
            command: Command number
            value: Return value

        Returns:
            9-byte TMCL response packet.
        """
        response = bytearray(9)
        response[0] = 2  # Reply address
        response[1] = 1  # Module address
        response[2] = 100  # Status (100 = success)
        response[3] = command

        # Value as 32-bit big-endian
        if value < 0:
            value = (1 << 32) + value
        response[4] = (value >> 24) & 0xFF
        response[5] = (value >> 16) & 0xFF
        response[6] = (value >> 8) & 0xFF
        response[7] = value & 0xFF

        # Checksum
        response[8] = sum(response[0:8]) % 256

        return bytes(response)

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


def get_mock_serial(**kwargs) -> Serial:
    """Factory function to create mock serial port.

    This allows easy substitution in code:
        if emulation:
            serial_class = mock_serial.get_mock_serial
        else:
            import serial
            serial_class = serial.Serial

    Args:
        **kwargs: Serial port parameters

    Returns:
        Mock Serial instance.
    """
    return Serial(**kwargs)
