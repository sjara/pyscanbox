"""Trinamic motor control interface for Knobby.

This module provides serial communication with the Trinamic motor controller
board at 57600 baud using the TMCL (Trinamic Motion Control Language) protocol.

The legacy MATLAB memory-mapping IPC is eliminated in favor of direct
serial communication using pyserial. A background thread handles continuous
hardware polling without blocking the main thread.

Protocol:
    TMCL uses 9-byte command packets with checksum.
    Packet format: [address, command, type, motor, value(4 bytes), checksum]

Reference:
    Original MATLAB/Python implementation: trinamic/tri_send.m, 
    scanknob/scanknob.py

Example:
    >>> import pyscanbox.hardware.motor
    >>> motor = pyscanbox.hardware.motor.TrinamicMotor(config)
    >>> motor.open()
    >>> motor.move_absolute(motor=0, position=1000)
    >>> position = motor.get_position(motor=0)
"""

import threading
import time
from typing import Optional, Callable, Dict
from pyscanbox.hardware import protocols


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


class TrinamicMotor:
    """Interface to Trinamic motor controller.

    This class handles serial communication with the Trinamic board
    using TMCL protocol for precise motor control in the Knobby system.

    Attributes:
        port: Serial port object
        com_port: COM port name
        baud_rate: Baud rate (57600 for Trinamic)
        timeout: Serial communication timeout
        polling_active: Flag for background polling thread
        polling_interval: Polling interval in seconds
    """

    def __init__(self, config: dict, on_command=None):
        """Initialize Trinamic motor controller.

        Args:
            config: Configuration dictionary with motor settings.
                Must contain 'motor' key with COM port and parameters.
            on_command: Optional callback fired after each TMCL packet is
                written.  Signature::

                    on_command(com_port: str, cmd: str, cmd_type: int,
                               motor: int, value: int)
        """
        self.config = config
        self.com_port = config['motor']['com_port']
        self.baud_rate = config['motor']['baud_rate']
        self.timeout = config['motor']['timeout']
        self.on_command = on_command
        
        # Check if emulation is enabled
        self.use_emulation = config.get('emulation', {}).get('enabled', False)
        self.emulation_verbose = config.get('emulation', {}).get('verbose', False)
        
        self.port: Optional[object] = None
        self.is_open = False
        
        # Background polling
        self.polling_active = False
        self.polling_interval = 0.05  # 50ms polling
        self.polling_thread: Optional[threading.Thread] = None
        self.polling_callback: Optional[Callable] = None
        
        # Motor state cache
        self.motor_positions: Dict[int, int] = {}
        self.motor_velocities: Dict[int, int] = {}

    def open(self) -> None:
        """Open serial connection to Trinamic board.

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
        
        # Flush buffers
        self.port.reset_input_buffer()
        self.port.reset_output_buffer()
        self.port.reset_input_buffer()
        self.port.reset_output_buffer()

    def close(self) -> None:
        """Close serial connection and stop polling thread."""
        if self.polling_active:
            self.stop_polling()
        
        if self.port is not None and self.port.is_open:
            self.port.close()
        
        self.is_open = False

    def send_command(self, cmd: str, cmd_type: int, motor: int, 
                     value: int) -> Optional[bytes]:
        """Send TMCL command and get response.

        Args:
            cmd: Command string (e.g., 'GAP', 'SAP', 'MVP', 'ROR', 'ROL')
            cmd_type: Command type parameter
            motor: Motor number (0-3)
            value: 32-bit value parameter

        Returns:
            9-byte response packet, or None if no response expected.

        Reference:
            See trinamic/tri_send.m for command structure.

        Raises:
            RuntimeError: If port is not open.
        """
        if not self.is_open or self.port is None:
            raise RuntimeError("Motor port not open. Call open() first.")
        
        # Build TMCL packet using protocol module
        packet = protocols.build_tmcl_packet(cmd, cmd_type, motor, value)
        
        # Send packet
        self.port.write(packet)
        if self.on_command is not None:
            self.on_command(self.com_port, cmd, cmd_type, motor, value)
        
        # Wait for response (9 bytes)
        response = self.port.read(9)
        
        if len(response) != 9:
            return None
        
        return response

    @staticmethod
    def format_command(cmd: str, cmd_type: int, motor: int, value: int) -> str:
        """Decode a TMCL command into a human-readable call string.

        Args:
            cmd: TMCL command string ('MVP', 'GAP', 'SAP', 'ROR', 'ROL', 'MST').
            cmd_type: Command type parameter.
            motor: Motor number (0-3).
            value: 32-bit value parameter.

        Returns:
            Human-readable string, e.g. ``'move_absolute(motor=0, pos=1000)'``.
        """
        if cmd == 'MVP':
            if cmd_type == 0:
                return f'move_absolute(motor={motor}, pos={value})'
            else:
                return f'move_relative(motor={motor}, dist={value})'
        elif cmd == 'GAP':
            return f'get_axis_parameter(motor={motor}, param={cmd_type})'
        elif cmd == 'SAP':
            return f'set_axis_parameter(motor={motor}, param={cmd_type}, value={value})'
        elif cmd == 'ROR':
            return f'rotate_right(motor={motor}, vel={value})'
        elif cmd == 'ROL':
            return f'rotate_left(motor={motor}, vel={value})'
        elif cmd == 'MST':
            return f'stop(motor={motor})'
        else:
            return f'{cmd}(type={cmd_type}, motor={motor}, value={value})'

    def get_axis_parameter(self, motor: int, param_type: int) -> Optional[int]:
        """Get axis parameter (GAP command).

        Args:
            motor: Motor number (0-3)
            param_type: Parameter type ID

        Returns:
            Parameter value, or None if command fails.
        """
        response = self.send_command('GAP', param_type, motor, 0)
        
        if response is None:
            return None
        
        # Extract 32-bit value from response bytes 4-7
        value = int.from_bytes(response[4:8], byteorder='big', signed=True)
        return value

    def set_axis_parameter(self, motor: int, param_type: int, 
                          value: int) -> bool:
        """Set axis parameter (SAP command).

        Args:
            motor: Motor number (0-3)
            param_type: Parameter type ID
            value: Parameter value to set

        Returns:
            True if command succeeded, False otherwise.
        """
        response = self.send_command('SAP', param_type, motor, value)
        return response is not None

    def set_freewheel(self, motor_id: int, enabled: bool) -> bool:
        """Set freewheeling mode for a single motor (TMCL SAP 204).

        When enabled, the motor coils de-energize as soon as the motor
        reaches its target position (less heat, less vibration from
        holding-torque PWM).  When disabled, the motor stays energized
        and actively holds position against gravity or cable drag.

        Use ``enabled=False`` for gravity-loaded axes (e.g. Z focus) and
        ``enabled=True`` for horizontal axes where drift is not a concern
        (e.g. X and Y translation).

        Args:
            motor_id: Motor number (0=Z, 1=Y, 2=X, 3=A).
            enabled: True = freewheel (power off at position),
                     False = hold position (power stays on).

        Returns:
            True if the command was acknowledged, False otherwise.

        Reference:
            TMCL SAP parameter 204 (Freewheeling).
            Original MATLAB: ``tri_send('SAP', 204, i, sbconfig.freewheel)``.
            Config keys: ``motor.freewheel_z/y/x/a`` in YAML config.
        """
        return self.set_axis_parameter(motor_id, 204, int(enabled))

    def get_position(self, motor: int) -> Optional[int]:
        """Get current motor position.

        Args:
            motor: Motor number (0-3)

        Returns:
            Current position in steps, or None if command fails.
        """
        # Parameter type 1 is actual position
        return self.get_axis_parameter(motor, 1)

    def move_absolute(self, motor: int, position: int) -> bool:
        """Move motor to absolute position (MVP command).

        Args:
            motor: Motor number (0-3)
            position: Target position in steps

        Returns:
            True if command succeeded, False otherwise.
        """
        # Type 0 is absolute positioning
        response = self.send_command('MVP', 0, motor, position)
        return response is not None

    def move_relative(self, motor: int, distance: int) -> bool:
        """Move motor relative to current position (MVP command).

        Args:
            motor: Motor number (0-3)
            distance: Distance to move in steps (signed)

        Returns:
            True if command succeeded, False otherwise.
        """
        # Type 1 is relative positioning
        response = self.send_command('MVP', 1, motor, distance)
        return response is not None

    def rotate_right(self, motor: int, velocity: int) -> bool:
        """Rotate motor right at specified velocity (ROR command).

        Args:
            motor: Motor number (0-3)
            velocity: Rotation velocity

        Returns:
            True if command succeeded, False otherwise.
        """
        response = self.send_command('ROR', 0, motor, velocity)
        return response is not None

    def rotate_left(self, motor: int, velocity: int) -> bool:
        """Rotate motor left at specified velocity (ROL command).

        Args:
            motor: Motor number (0-3)
            velocity: Rotation velocity

        Returns:
            True if command succeeded, False otherwise.
        """
        response = self.send_command('ROL', 0, motor, velocity)
        return response is not None

    def stop_motor(self, motor: int) -> bool:
        """Stop motor (MST command).

        Args:
            motor: Motor number (0-3)

        Returns:
            True if command succeeded, False otherwise.
        """
        response = self.send_command('MST', 0, motor, 0)
        return response is not None

    def start_polling(self, callback: Optional[Callable] = None) -> None:
        """Start background polling thread.

        The polling thread continuously reads motor positions and
        calls the optional callback function with updated positions.

        Args:
            callback: Optional function to call with motor positions.
                Called with dict of {motor_id: position}.
        """
        if self.polling_active:
            return
        
        self.polling_callback = callback
        self.polling_active = True
        self.polling_thread = threading.Thread(
            target=self._polling_loop,
            daemon=True
        )
        self.polling_thread.start()

    def stop_polling(self) -> None:
        """Stop background polling thread."""
        if not self.polling_active:
            return
        
        self.polling_active = False
        
        if self.polling_thread is not None:
            self.polling_thread.join(timeout=1.0)
            self.polling_thread = None

    def _polling_loop(self) -> None:
        """Background polling loop (runs in separate thread).

        Continuously polls motor positions and updates cache.
        """
        while self.polling_active:
            # Poll all motors (typically 4 motors)
            for motor_id in range(4):
                if not self.polling_active:
                    break
                
                position = self.get_position(motor_id)
                if position is not None:
                    self.motor_positions[motor_id] = position
            
            # Call callback if registered
            if self.polling_callback is not None:
                self.polling_callback(self.motor_positions.copy())
            
            # Sleep for polling interval
            time.sleep(self.polling_interval)

    def get_cached_positions(self) -> Dict[int, int]:
        """Get cached motor positions from polling thread.

        Returns:
            Dictionary mapping motor ID to position.
        """
        return self.motor_positions.copy()

    def __enter__(self):
        """Context manager entry."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
