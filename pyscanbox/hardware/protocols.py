"""Serial communication protocols for Scanbox hardware.

This module implements low-level protocol handling for:
    - TMCL (Trinamic Motion Control Language) for motor control
    - Other hardware-specific protocols

The TMCL protocol uses 9-byte packets with checksums for reliable
communication with Trinamic motor controllers.

Reference:
    Original implementation: trinamic/tri_send.m, scanknob/scanknob.py
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
