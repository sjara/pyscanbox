"""Serial communication protocols for Scanbox hardware.

This module is the canonical reference for all wire formats used between
the three devices in the Knobby system:

    Knobby (Arduino, COM5)  ←→  PC  ←→  Trinamic motor controller (COM4)

Formats implemented:
    TMCL (Trinamic Motion Control Language):
        build_tmcl_packet()       — build 9-byte command packet
        parse_tmcl_command()      — parse 9-byte command packet → dict
        parse_tmcl_response()     — parse 9-byte response packet → dict
        calculate_checksum()      — compute TMCL checksum byte

    Knobby serial protocol (knobby2.ino):
        parse_knobby_position_packet()  — parse 5-byte Knobby→PC position packet
        parse_knobby_command_packet()   — parse 9-byte PC→Knobby command packet

All functions return plain dicts of parsed fields so they can be used
independently of any hardware or GUI layer.

Reference:
    Original implementation: trinamic/tri_send.m, scanknob/scanknob.py
    Arduino firmware:        Scanbox/scanknob/knobby2/knobby2.ino
"""

from typing import Dict


# TMCL command mapping
TMCL_COMMANDS: Dict[str, int] = {
    'ROR': 1,    # Rotate right
    'ROL': 2,    # Rotate left
    'MST': 3,    # Motor stop
    'MVP': 4,    # Move to position
    'SAP': 5,    # Set axis parameter
    'GAP': 6,    # Get axis parameter
    'STAP': 7,   # Store axis parameter
    'RSAP': 8,   # Restore axis parameter
    'SGP': 9,    # Set global parameter
    'GGP': 10,   # Get global parameter
    'STGP': 11,  # Store global parameter
    'RSGP': 12,  # Restore global parameter
    'RFS': 13,   # Reference search
    'SIO': 14,   # Set output
    'GIO': 15,   # Get input
    'SCO': 30,   # Set coordinate
    'GCO': 31,   # Get coordinate
    'CCO': 32,   # Capture coordinate
    'STP': 128,  # Stop
    'RUN': 129,  # Run application
    'GAS': 135,  # Get application status
    'KBY': 200,  # Knobby custom command
}


def build_tmcl_packet(cmd: str, cmd_type: int, motor: int, value: int) -> bytes:
    """Build a TMCL protocol packet with checksum.

    The TMCL packet format is 9 bytes:
        [0]: Module address (always 1)
        [1]: Command number
        [2]: Type parameter
        [3]: Motor/Bank number
        [4-7]: Value (32-bit, big-endian)
        [8]: Checksum

    Args:
        cmd: Command string (must be in TMCL_COMMANDS)
        cmd_type: Command type parameter
        motor: Motor number (0-3)
        value: 32-bit signed integer value

    Returns:
        9-byte TMCL packet with checksum.

    Reference:
        See scanknob/scanknob.py TriCmd function for checksum calculation.

    Raises:
        ValueError: If command is invalid or parameters out of range.

    Example:
        >>> packet = build_tmcl_packet('MVP', 0, 0, 1000)
        >>> # Move motor 0 to absolute position 1000
    """
    if cmd not in TMCL_COMMANDS:
        raise ValueError(f"Invalid TMCL command: {cmd}")
    
    if not (0 <= motor <= 255):
        raise ValueError(f"Motor must be 0-255, got {motor}")
    
    if not (0 <= cmd_type <= 255):
        raise ValueError(f"Command type must be 0-255, got {cmd_type}")
    
    # Build packet
    packet = bytearray(9)
    packet[0] = 1  # Module address
    packet[1] = TMCL_COMMANDS[cmd]  # Command number
    packet[2] = cmd_type  # Type
    packet[3] = motor  # Motor number
    
    # Value as 32-bit big-endian signed integer
    # Handle negative values with two's complement
    if value < 0:
        value = (1 << 32) + value  # Convert to unsigned representation
    
    packet[4] = (value >> 24) & 0xFF
    packet[5] = (value >> 16) & 0xFF
    packet[6] = (value >> 8) & 0xFF
    packet[7] = value & 0xFF
    
    # Calculate checksum (sum of bytes 0-7, modulo 256)
    checksum = sum(packet[0:8]) % 256
    packet[8] = checksum
    
    return bytes(packet)


def parse_tmcl_response(response: bytes) -> Dict[str, int]:
    """Parse TMCL response packet.

    The response packet format is 9 bytes:
        [0]: Reply address
        [1]: Module address
        [2]: Status (100 = success, 101 = error)
        [3]: Command number
        [4-7]: Value (32-bit, big-endian)
        [8]: Checksum

    Args:
        response: 9-byte response packet

    Returns:
        Dictionary with parsed fields:
            - status: Status code
            - value: Returned value
            - command: Command number
            - valid: True if checksum is valid

    Raises:
        ValueError: If response is not 9 bytes.

    Example:
        >>> response = port.read(9)
        >>> parsed = parse_tmcl_response(response)
        >>> if parsed['status'] == 100 and parsed['valid']:
        >>>     position = parsed['value']
    """
    if len(response) != 9:
        raise ValueError(f"Response must be 9 bytes, got {len(response)}")
    
    # Extract fields
    reply_address = response[0]
    module_address = response[1]
    status = response[2]
    command = response[3]
    
    # Extract 32-bit value (big-endian)
    value = int.from_bytes(response[4:8], byteorder='big', signed=False)
    
    # Convert to signed if necessary (two's complement)
    if value >= (1 << 31):
        value -= (1 << 32)
    
    # Verify checksum
    expected_checksum = sum(response[0:8]) % 256
    actual_checksum = response[8]
    valid = (expected_checksum == actual_checksum)
    
    return {
        'reply_address': reply_address,
        'module_address': module_address,
        'status': status,
        'command': command,
        'value': value,
        'checksum': actual_checksum,
        'valid': valid,
    }


def calculate_checksum(data: bytes) -> int:
    """Calculate TMCL checksum for data.

    Args:
        data: Byte sequence to checksum (typically first 8 bytes of packet)

    Returns:
        Checksum byte (sum modulo 256).
    """
    return sum(data) % 256


# Reverse map used by parsers: TMCL command number → command name string.
_TMCL_CMD_NAMES: Dict[int, str] = {v: k for k, v in TMCL_COMMANDS.items()}

# Knobby command IDs → human-readable names (from knobby2.ino switch-case).
KNOBBY_CMD_NAMES: Dict[int, str] = {
    0: 'Move Z', 1: 'Move Y', 2: 'Move X',
    10: 'Vel coarse', 11: 'Vel fine', 12: 'Vel superfine',
    20: 'Mode normal', 21: 'Mode rotate',
    30: 'Zero XYZ', 31: 'Zero XYZA',
    40: 'Store A', 41: 'Store B', 42: 'Store C',
    50: 'Recall A', 51: 'Recall B', 52: 'Recall C',
    60: 'Lock', 61: 'Unlock',
}


def parse_tmcl_command(packet: bytes) -> Dict:
    """Parse a 9-byte TMCL command packet sent from PC to motor controller.

    Symmetric counterpart to parse_tmcl_response(): decodes the packet
    built by build_tmcl_packet() so callers can inspect or log commands
    without re-implementing the field layout.

    Packet layout (from scanknob/scanknob.py TriCmd):
        [0]: Module address (always 1)
        [1]: Command number
        [2]: Type parameter
        [3]: Motor/Bank number
        [4-7]: Value (32-bit, big-endian, signed)
        [8]: Checksum

    Args:
        packet: 9-byte TMCL command packet.

    Returns:
        Dictionary with keys:
            - module_address: int
            - command: int  (command number)
            - command_name: str  (e.g. 'MVP', 'GAP', or 'cmd#N' if unknown)
            - cmd_type: int
            - motor: int
            - value: int  (signed 32-bit)
            - checksum: int
            - valid: bool  (True if checksum matches)

    Raises:
        ValueError: If packet is not 9 bytes.
    """
    if len(packet) != 9:
        raise ValueError(f'TMCL command must be 9 bytes, got {len(packet)}')

    cmd_num = packet[1]
    value = int.from_bytes(packet[4:8], byteorder='big', signed=False)
    if value >= (1 << 31):
        value -= (1 << 32)

    expected = sum(packet[:8]) % 256
    return {
        'module_address': packet[0],
        'command': cmd_num,
        'command_name': _TMCL_CMD_NAMES.get(cmd_num, f'cmd#{cmd_num}'),
        'cmd_type': packet[2],
        'motor': packet[3],
        'value': value,
        'checksum': packet[8],
        'valid': packet[8] == expected,
    }


def parse_knobby_position_packet(data: bytes) -> Dict:
    """Parse the 5-byte position packet sent by Knobby firmware to the PC.

    The Knobby sends this packet whenever a knob is turned (from
    knobby2.ino normal and rotate mode loops):

        cmd[0] = motor_id;
        Serial.write(cmd[0]);
        for (int j = 0; j <= 3; j++)
            Serial.write((dpos[i] >> (8 * j)) & 0x0ff);

    Packet layout:
        [0]:   motor_id  (0=Z, 1=Y, 2=X, 3=A)
        [1-4]: dpos — 32-bit signed step count, little-endian

    This is the byte sequence consumed by Knobby.read_command().

    Args:
        data: 5-byte packet received from Knobby.

    Returns:
        Dictionary with keys:
            - motor_id: int  (0-3)
            - steps: int     (signed 32-bit position in motor steps)

    Raises:
        ValueError: If data is not 5 bytes.
    """
    if len(data) != 5:
        raise ValueError(f'Knobby position packet must be 5 bytes, got {len(data)}')

    return {
        'motor_id': data[0],
        'steps': int.from_bytes(data[1:5], byteorder='little', signed=True),
    }


def parse_knobby_command_packet(data: bytes) -> Dict:
    """Parse the 9-byte command packet sent by PC to Knobby.

    Packet layout (from knobby2.ino external command handler):
        [0]: 0x01  (fixed header)
        [1]: 0xC8  (fixed header, decimal 200)
        [2]: reserved
        [3]: cmd_id  (see KNOBBY_CMD_NAMES)
        [4]: value high byte
        [5]: value low byte
        [6-8]: reserved

    This is the byte sequence produced by Knobby.send_command().

    Args:
        data: 9-byte packet sent to Knobby.

    Returns:
        Dictionary with keys:
            - cmd_id: int
            - cmd_name: str  (from KNOBBY_CMD_NAMES, or 'cmd#N' if unknown)
            - value: int     (signed 16-bit, reconstructed from bytes 4-5)
            - valid_header: bool  (True if bytes 0-1 match 0x01 0xC8)

    Raises:
        ValueError: If data is not 9 bytes.
    """
    if len(data) != 9:
        raise ValueError(f'Knobby command packet must be 9 bytes, got {len(data)}')

    cmd_id = data[3]
    value = int.from_bytes(bytes([data[4], data[5]]), byteorder='big', signed=True)
    return {
        'cmd_id': cmd_id,
        'cmd_name': KNOBBY_CMD_NAMES.get(cmd_id, f'cmd#{cmd_id}'),
        'value': value,
        'valid_header': (data[0] == 0x01 and data[1] == 0xC8),
    }
