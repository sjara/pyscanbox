"""Knobby display and control interface.

This module provides serial communication with the Knobby Arduino-based controller
at 57600 baud. The Knobby has rotary encoders for manual position control and 
a Nextion touchscreen display.

The Knobby acts as an intermediary between the user and the motor controller:
- Reads rotary encoder inputs
- Calculates position changes
- Displays positions in microns/degrees on screen
- Sends position commands to PC (which forwards to motor controller)

Module-level constants (from knobby2.ino):
    MOTOR_GAIN: Steps-to-unit conversion factors for each motor axis.
    MOTOR_MSTEP: Steps-per-encoder-count table for each velocity mode.
    AXIS_NAMES: Human-readable axis labels ['Z', 'Y', 'X', 'A'].
    AXIS_UNITS: Physical unit strings ['μm', 'μm', 'μm', 'deg'].

Protocol:
    PC -> Knobby: 9-byte command packets
    Knobby -> PC: 5-byte position packets [motor_id, byte0-3 of position]

Reference:
    Arduino firmware: Scanbox/scanknob/knobby2/knobby2.ino
    Documentation: docs/knobby_architecture.md

Example:
    >>> import pyscanbox.hardware.knobby
    >>> knobby = pyscanbox.hardware.knobby.Knobby(config)
    >>> knobby.open()
    >>> knobby.move_motor(0, 100.0)  # Move Z-axis by 100 microns
    >>> knobby.close()
    >>> pos_um = pyscanbox.hardware.knobby.steps_to_units(motor_id=2, steps=19843)
"""

from typing import Optional


# Motor-to-unit conversion factors (from knobby2.ino, line 29).
# Index order: [Z, Y, X, A]  (matches motor_gain[4] in firmware).
#
# Units are μm/step (motors 0-2) and deg/step (motor 3). This is confirmed by
# two usages in knobby2.ino:
#   1. update_axis():  display_value = dpos[i] * motor_gain[i]
#      dpos is in steps, display_value is shown in μm or deg on screen,
#      so motor_gain must be μm/step or deg/step.
#   2. Move command handler:  encoder_counts = fval / motor_gain[i] / mstep[vel][i]
#      fval is the PC command value in μm, confirming the same unit direction.
MOTOR_GAIN = [
    2000.0 / 400.0 / 32.0 / 2.0,      # Motor 0 (Z): 0.078125  μm/step  (12.8   steps/μm)
    (0.02 * 25400.0) / 400.0 / 64.0,  # Motor 1 (Y): 0.019843  μm/step  (50.4   steps/μm)
    (0.02 * 25400.0) / 400.0 / 64.0,  # Motor 2 (X): 0.019843  μm/step  (50.4   steps/μm)
    0.0225 / 64.0,                    # Motor 3 (A): 3.516e-4  deg/step (2844.4 steps/deg)
]

# Steps per encoder count for each velocity mode (from knobby2.ino mstep[3][4]).
# First index: 0=coarse, 1=fine, 2=superfine.
# Second index: motor (Z=0, Y=1, X=2, A=3).
MOTOR_MSTEP = [
    [10, 3.9370 * 10, 3.9370 * 10, 10],  # Coarse
    [5,  3.9370 * 5,  3.9370 * 5,  5],   # Fine
    [1,  3.9370,      3.9370,      1],   # Superfine
]

AXIS_NAMES = ['Z', 'Y', 'X', 'A']
AXIS_UNITS = ['um', 'um', 'um', 'deg']


def steps_to_units(motor_id: int, steps: int) -> float:
    """Convert motor steps to physical units.

    Uses the conversion factors from knobby2.ino (motor_gain array) to
    translate raw Trinamic step counts into microns (X/Y/Z) or degrees (A).

    Args:
        motor_id: Motor index — 0=Z, 1=Y, 2=X, 3=A.
        steps: Position in motor steps (signed integer).

    Returns:
        Position in microns for motors 0-2, or degrees for motor 3.

    Raises:
        IndexError: If motor_id is outside 0-3.

    Example:
        >>> pyscanbox.hardware.knobby.steps_to_units(2, 19843)
        999.98...
    """
    return steps * MOTOR_GAIN[motor_id]


def units_to_steps(motor_id: int, value: float) -> int:
    """Convert physical units to motor steps.

    Inverse of steps_to_units(). Useful for computing the step count that
    corresponds to a desired position in microns or degrees.

    Args:
        motor_id: Motor index — 0=Z, 1=Y, 2=X, 3=A.
        value: Position in microns (motors 0-2) or degrees (motor 3).

    Returns:
        Nearest integer step count.

    Raises:
        IndexError: If motor_id is outside 0-3.

    Example:
        >>> pyscanbox.hardware.knobby.units_to_steps(2, 1000.0)
        50394
    """
    return round(value / MOTOR_GAIN[motor_id])


def build_position_packet(motor_id: int, steps: int) -> bytes:
    """Build the 5-byte position packet sent by Knobby firmware to the PC.

    Mirrors the transmit loop in knobby2.ino (normal and rotate modes):
        cmd[0] = i;
        Serial.write(cmd[0]);
        for (int j = 0; j <= 3; j++) {
            Serial.write((dpos[i] >> (8 * j)) & 0x0ff);
        }

    This is the exact byte sequence that Knobby.read_command() parses on
    the PC side, making the two functions symmetric counterparts.

    Args:
        motor_id: Motor index — 0=Z, 1=Y, 2=X, 3=A.
        steps: Accumulated position in steps (firmware dpos[motor_id]).

    Returns:
        5-byte packet: [motor_id, b0, b1, b2, b3] where b0-b3 are the
        32-bit signed step count in little-endian order.

    Example:
        >>> pyscanbox.hardware.knobby.build_position_packet(0, 1000)
        b'\\x00\\xe8\\x03\\x00\\x00'
    """
    packet = bytearray(5)
    packet[0] = motor_id
    packet[1:5] = steps.to_bytes(4, byteorder='little', signed=True)
    return bytes(packet)


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


class Knobby:
    """Interface to Knobby display and control unit.

    This class handles serial communication with the Arduino-based Knobby
    controller which provides manual position control via rotary encoders
    and displays position information on a touchscreen.

    Attributes:
        port: Serial port object
        com_port: COM port name or IP address
        baud_rate: Baud rate (57600 for Knobby)
        timeout: Serial communication timeout
        version: Knobby version (1 or 2)
    """

    def __init__(self, config: dict, on_command=None):
        """Initialize Knobby controller.

        Args:
            config: Configuration dictionary with knobby settings.
                Must contain 'knobby' key with COM port and parameters.
            on_command: Optional callback fired after each 9-byte packet is
                written.  Signature::

                    on_command(com_port: str, command_id: int, value: int)
        """
        self.config = config
        self.on_command = on_command
        
        # Get knobby configuration
        knobby_config = config.get('knobby', {})
        self.com_port = knobby_config.get('com_port', 'COM5')
        self.baud_rate = 57600  # Fixed baud rate for Knobby
        self.timeout = knobby_config.get('timeout', 1.0)
        self.version = knobby_config.get('version', 2)
        self.reset_on_startup = knobby_config.get('reset_on_startup', True)
        
        # Check if emulation is enabled
        self.use_emulation = config.get('emulation', {}).get('enabled', False)
        self.emulation_verbose = config.get('emulation', {}).get('verbose', False)
        
        self.port: Optional[object] = None
        self.is_open = False
        
        # Check if this is an IP address (for knobby tablet)
        self.is_network = '.' in self.com_port and not self.com_port.startswith('COM')

    def open(self) -> None:
        """Open serial connection to Knobby.

        Raises:
            serial.SerialException: If port cannot be opened.
            NotImplementedError: If network-based Knobby is specified.
        """
        if self.is_network:
            raise NotImplementedError(
                f"Network-based Knobby connection not yet implemented: {self.com_port}"
            )
        
        # Get appropriate serial module
        serial_module = _get_serial_module(self.use_emulation)
        
        self.port = serial_module.Serial(
            self.com_port,
            self.baud_rate,
            timeout=self.timeout
        )
        self.is_open = True
        
        if self.emulation_verbose:
            print(f"Knobby: Connected to {self.com_port} at {self.baud_rate} baud")

    def close(self) -> None:
        """Close serial connection to Knobby."""
        if self.port is not None and self.is_open:
            self.port.close()
            self.is_open = False
            
            if self.emulation_verbose:
                print(f"Knobby: Closed connection to {self.com_port}")

    def send_command(self, command_id: int, value: int = 0) -> bool:
        """Send command to Knobby.
        
        Sends a 9-byte command packet to the Knobby.
        Packet format: [0x01, 0xC8, reserved, cmd_id, val_high, val_low, 0, 0, 0]
        
        Args:
            command_id: Command ID (see knobby2.ino for list)
            value: Optional 16-bit value parameter
            
        Returns:
            True if command sent successfully, False otherwise.
            
        Raises:
            RuntimeError: If port is not open.
        """
        if not self.is_open or self.port is None:
            raise RuntimeError("Knobby port not open. Call open() first.")
        
        # Build command packet
        packet = bytearray(9)
        packet[0] = 0x01  # Fixed header
        packet[1] = 0xC8  # Fixed header (200)
        packet[2] = 0x00  # Reserved
        packet[3] = command_id
        packet[4] = (value >> 8) & 0xFF  # High byte
        packet[5] = value & 0xFF         # Low byte
        packet[6] = 0x00  # Reserved
        packet[7] = 0x00  # Reserved
        packet[8] = 0x00  # Reserved
        
        try:
            self.port.write(packet)
            if self.on_command is not None:
                self.on_command(self.com_port, command_id, value)
            return True
        except Exception as e:
            if self.emulation_verbose:
                print(f"Knobby: Error sending command {command_id}: {e}")
            return False

    CMD_NAMES = {
        10: 'set_velocity_coarse',
        11: 'set_velocity_fine',
        12: 'set_velocity_superfine',
        20: 'set_mode_normal',
        21: 'set_mode_rotate',
        30: 'zero_xyz',
        31: 'zero_xyza',
        40: 'store_position_A',
        41: 'store_position_B',
        42: 'store_position_C',
        50: 'recall_position_A',
        51: 'recall_position_B',
        52: 'recall_position_C',
        60: 'lock',
        61: 'unlock',
    }

    @staticmethod
    def format_command(command_id: int, value: int) -> str:
        """Decode a Knobby command into a human-readable call string.

        Args:
            command_id: Command ID sent to the Knobby.
            value: 16-bit value parameter.

        Returns:
            Human-readable string, e.g. ``'move_motor(motor=0, dist=100 um)'``.
        """
        if 0 <= command_id <= 2:
            axis = ['Z', 'Y', 'X'][command_id]
            return f'move_motor(motor={command_id} [{axis}], dist={value} um)'
        name = Knobby.CMD_NAMES.get(command_id)
        if name:
            return f'{name}()'
        return f'cmd({command_id}, value={value})'

    def move_motor(self, motor_id: int, distance_um: float) -> bool:
        """Command Knobby to move a motor by a relative distance.
        
        Args:
            motor_id: Motor ID (0=Z, 1=Y, 2=X)
            distance_um: Distance to move in microns (signed)
            
        Returns:
            True if command sent successfully, False otherwise.
        """
        if motor_id not in [0, 1, 2]:
            raise ValueError(f"Invalid motor_id: {motor_id}. Must be 0, 1, or 2.")
        
        # Convert to 16-bit signed integer
        value = int(distance_um)
        if value < -32768 or value > 32767:
            raise ValueError(f"Distance out of range: {distance_um} (must fit in 16-bit signed)")
        
        return self.send_command(motor_id, value)

    def set_velocity_coarse(self) -> bool:
        """Set Knobby velocity mode to coarse."""
        return self.send_command(10)

    def set_velocity_fine(self) -> bool:
        """Set Knobby velocity mode to fine."""
        return self.send_command(11)

    def set_velocity_superfine(self) -> bool:
        """Set Knobby velocity mode to superfine."""
        return self.send_command(12)

    def set_mode_normal(self) -> bool:
        """Set Knobby to normal mode."""
        return self.send_command(20)

    def set_mode_rotate(self) -> bool:
        """Set Knobby to rotate mode."""
        return self.send_command(21)

    def zero_xyz(self) -> bool:
        """Zero X, Y, Z positions."""
        return self.send_command(30)

    def zero_xyza(self) -> bool:
        """Zero X, Y, Z, and A positions."""
        return self.send_command(31)

    def store_position(self, memory_slot: int) -> bool:
        """Store current position to memory slot.
        
        Args:
            memory_slot: Memory slot (0=A, 1=B, 2=C)
            
        Returns:
            True if command sent successfully, False otherwise.
        """
        if memory_slot not in [0, 1, 2]:
            raise ValueError(f"Invalid memory_slot: {memory_slot}. Must be 0, 1, or 2.")
        
        return self.send_command(40 + memory_slot)

    def recall_position(self, memory_slot: int) -> bool:
        """Recall position from memory slot.
        
        Args:
            memory_slot: Memory slot (0=A, 1=B, 2=C)
            
        Returns:
            True if command sent successfully, False otherwise.
        """
        if memory_slot not in [0, 1, 2]:
            raise ValueError(f"Invalid memory_slot: {memory_slot}. Must be 0, 1, or 2.")
        
        return self.send_command(50 + memory_slot)

    def lock(self) -> bool:
        """Lock the Knobby (disable knobs and touch screen)."""
        return self.send_command(60)

    def unlock(self) -> bool:
        """Unlock the Knobby (enable knobs and touch screen)."""
        return self.send_command(61)

    def read_command(self) -> Optional[tuple]:
        """Read position command from Knobby.
        
        The Knobby sends 5-byte packets when knobs are turned:
        [motor_id, byte0, byte1, byte2, byte3] where bytes 0-3 are position in steps.
        
        Returns:
            Tuple of (motor_id, position_steps) if data available, None otherwise.
        """
        if not self.is_open or self.port is None:
            raise RuntimeError("Knobby port not open. Call open() first.")
        
        if self.port.in_waiting >= 5:
            data = self.port.read(5)
            if len(data) == 5:
                motor_id = data[0]
                # Reconstruct 32-bit signed position (little-endian)
                position = int.from_bytes(data[1:5], byteorder='little', signed=True)
                return (motor_id, position)
        
        return None

    def __enter__(self):
        """Context manager entry."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
