# Trinamic TMCL Protocol

Low-level protocol specification for Trinamic motor controllers.

## Overview

Trinamic motor controllers use the **TMCL (Trinamic Motion Control Language)** protocol at **57,600 baud**.

## Packet Structure

All TMCL commands are **9-byte packets**:

```
[Module, Command, Type, Motor, Value_MSB, Value_2, Value_1, Value_LSB, Checksum]
```

**Byte Positions:**
- Byte 0: Module address (typically 1)
- Byte 1: Command number
- Byte 2: Type byte (command-specific)
- Byte 3: Motor/Bank number (0-3)
- Bytes 4-7: Value (32-bit integer, big-endian)
- Byte 8: Checksum

## Checksum Calculation

The checksum is the sum of bytes 0-7, modulo 256:

```python
def calculate_checksum(cmd_bytes):
    """Calculate TMCL checksum."""
    return sum(cmd_bytes[:8]) % 256
```

**Example:**
```python
# Move motor 0 to absolute position 1000
cmd = [1, 4, 0, 0, 0, 0, 3, 232, 0]  # Last byte will be checksum
checksum = sum(cmd[:8]) % 256  # = 240
cmd[8] = checksum
# Final: [1, 4, 0, 0, 0, 0, 3, 232, 240]
```

## Common Commands

### MVP - Move to Position (Command: 4)

**Absolute Movement:**
```python
[Module, 4, 0, Motor, Value_bytes..., Checksum]
```

**Relative Movement:**
```python
[Module, 4, 1, Motor, Value_bytes..., Checksum]
```

**Example - Move motor 0 to position 1000:**
```python
position = 1000
cmd = [
    1,                              # Module
    4,                              # MVP command
    0,                              # Type: 0=absolute, 1=relative
    0,                              # Motor 0
    (position >> 24) & 0xFF,        # Value MSB
    (position >> 16) & 0xFF,
    (position >> 8) & 0xFF,
    position & 0xFF,                # Value LSB
    0                               # Checksum (calculated)
]
cmd[8] = sum(cmd[:8]) % 256
```

---

### GAP - Get Axis Parameter (Command: 6)

Read motor parameters like position, velocity, current, etc.

**Format:**
```python
[Module, 6, ParamType, Motor, 0, 0, 0, 0, Checksum]
```

**Common Parameter Types:**
- `1`: Actual position
- `2`: Target position
- `3`: Maximum positioning speed
- `8`: Target reached flag

**Example - Get current position of motor 0:**
```python
cmd = [1, 6, 1, 0, 0, 0, 0, 0, 0]
cmd[8] = sum(cmd[:8]) % 256
# Send cmd, then read 9-byte response
```

---

### SAP - Set Axis Parameter (Command: 5)

Set motor parameters.

**Format:**
```python
[Module, 5, ParamType, Motor, Value_bytes..., Checksum]
```

**Example - Set maximum speed to 2000:**
```python
speed = 2000
cmd = [
    1,                          # Module
    5,                          # SAP command
    4,                          # Parameter type: max speed
    0,                          # Motor 0
    (speed >> 24) & 0xFF,
    (speed >> 16) & 0xFF,
    (speed >> 8) & 0xFF,
    speed & 0xFF,
    0
]
cmd[8] = sum(cmd[:8]) % 256
```

---

### MST - Motor Stop (Command: 3)

Emergency stop for a motor.

**Format:**
```python
[Module, 3, 0, Motor, 0, 0, 0, 0, Checksum]
```

---

### ROR/ROL - Rotate Right/Left (Commands: 1/2)

Continuous rotation at specified velocity.

**Format:**
```python
[Module, ROR/ROL, 0, Motor, Velocity_bytes..., Checksum]
```

## Response Format

The controller sends a 9-byte response:

```
[Reply_Address, Module, Status, Command, Value_MSB, Value_2, Value_1, Value_LSB, Checksum]
```

**Status Codes:**
- `100`: Successfully executed
- `101`: Command loaded into memory
- Others indicate errors

## Serial Configuration

```python
import serial

port = serial.Serial(
    port='COM4',              # Update with actual port
    baudrate=57600,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=0.5
)
```

## Implementation Notes

1. **Always verify checksum** on received packets
2. **Wait for response** before sending next command
3. **Polling required** for continuous position updates
4. **Background thread** recommended to avoid blocking main application

## Example Usage

See `pyscanbox/hardware/motor.py` for complete implementation and `examples/check_motor.py` for comprehensive connection checking and usage examples.

## Original MATLAB References

**File Locations:**
- `Scanbox/trinamic/*.m`
  - `tri_open.m` - Initialize motor controller
  - `tri_send.m` - Send TMCL command

**Legacy Python intermediary:** `Scanbox/scanknob/scanknob.py`

Because MATLAB cannot own a serial port directly, `tri_open.m` launched `scanknob.py` as a Python subprocess. MATLAB communicated with it via two **memory-mapped files**:
- `scanknob.pos` — flag byte + 4 × int32 motor positions (written by Python, read by MATLAB)
- `scanknob.cmd` — flag byte + 9-byte TMCL command (written by MATLAB, executed by Python)

`tri_send.m` wrote a command into `scanknob.cmd`, set the flag to 1, then busy-waited (`while(tri.Data(1)~=0)`) until Python cleared the flag after sending the command over serial and receiving the response.

**In pyscanbox this entire IPC layer is eliminated.** Python owns the serial port directly via `pyserial`, so no subprocess, no mmap files, and no busy-wait handshake are needed.
