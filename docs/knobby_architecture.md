# Knobby Position Controller Architecture

## Overview

The Knobby is an Arduino-based hardware controller that provides manual positioning control for the Scanbox microscope. It consists of rotary encoders, a touchscreen display, and acts as an intermediary between the user and the Trinamic motor controller.

## Hardware Components

### 1. Arduino Microcontroller
- Runs the knobby firmware (`Scanbox/scanknob/knobby2/knobby2.ino`)
- Connects to PC via Serial at **57600 baud** (COM5)
- Manages all I/O between encoders, display, and PC

### 2. Rotary Encoders (4x)
- **X-axis encoder**: Pins 36, 34 (horizontal stage movement)
- **Y-axis encoder**: Pins 32, 30 (vertical stage movement)
- **Z-axis encoder**: Pins 40, 38 (focus/depth)
- **A-axis encoder**: Pins 44, 42 (objective angle/rotation)

### 3. Nextion Touchscreen Display
- Connected via Serial1 at **9600 baud**
- Displays positions in microns
- Provides touch interface for settings

## System Architecture

```
┌──────────────┐         ┌──────────────┐         ┌──────────────────────┐
│   Knobby     │ Serial  │   PC/Host    │ Serial  │ Trinamic Motor Ctrl  │
│  (Arduino)   │◄───────►│ (MATLAB/Py)  │◄───────►│      (COM4)          │
│   COM5       │ 57600   │              │ 57600   │                      │
│   baud       │         │              │  baud   │  TMCL Protocol       │
└──────────────┘         └──────────────┘         └──────────────────────┘
       │                                                      │
       │                                                      │
       ▼                                                      ▼
┌──────────────┐                                    ┌──────────────┐
│   Nextion    │                                    │ Stepper      │
│   Display    │                                    │ Motors       │
│   9600 baud  │                                    │ (X, Y, Z)    │
└──────────────┘                                    └──────────────┘
```

## Position Tracking and Conversion

### Motor Position Units

The motor controller (Trinamic) stores positions in **steps** (motor steps).

### Conversion Factors (motor_gain)

From knobby2.ino, the conversion factors from steps to microns are:

```cpp
// motor_gain[4] = {Z, Y, X, A}
float motor_gain[4] = {
    2000.0 / 400.0 / 32.0 / 2.0,      // Z-axis: 0.078125 steps/μm
    (0.02 * 25400.0) / 400.0 / 64.0,  // Y-axis: 19.8425 steps/μm
    (0.02 * 25400.0) / 400.0 / 64.0,  // X-axis: 19.8425 steps/μm
    0.0225 / 64.0                      // A-axis: 0.000351563 steps/deg
};
```

**Python equivalents:**
```python
motor_gain = [
    2000.0 / 400.0 / 32.0 / 2.0,      # Motor 0 (Z): 0.078125 steps/μm
    (0.02 * 25400.0) / 400.0 / 64.0,  # Motor 1 (Y): 19.8425 steps/μm
    (0.02 * 25400.0) / 400.0 / 64.0,  # Motor 2 (X): 19.8425 steps/μm
    0.0225 / 64.0,                     # Motor 3 (A): 0.000351563 steps/deg
]

# Convert steps to microns (or degrees for A-axis):
if motor_id == 3:
    position_deg = position_steps * motor_gain[motor_id]
else:
    position_um = position_steps * motor_gain[motor_id]
```

### Motor-Axis Mapping

**Important**: The motor numbering is:
- Motor 0 = **Z-axis** (focus/depth)
- Motor 1 = **Y-axis** (vertical stage position)
- Motor 2 = **X-axis** (horizontal stage position)
- Motor 3 = **A-axis** (objective angle/rotation)

This is defined in knobby2.ino:
```cpp
#define X 2     // motor axes
#define Y 1
#define Z 0
#define A 3
```

## Communication Protocol

### 1. Knobby → PC (COM5)

When a knob is turned, Knobby sends a **5-byte packet**:
```
[motor_id, byte0, byte1, byte2, byte3]
```

Where:
- `motor_id`: 0 (Z), 1 (Y), 2 (X), or 3 (A)
- `byte0-byte3`: 32-bit signed integer position in steps (little-endian)

Example code from knobby2.ino:
```cpp
cmd[0] = i;                          // motor_id
Serial.write(cmd[0]);
for (int j = 0; j <= 3; j++) {
    Serial.write((dpos[i] >> (8 * j)) & 0x0ff);  // Send position bytes
}
```

### 2. PC → Knobby (COM5)

The PC can send **9-byte command packets** to control Knobby:
```
[0x01, 0xC8, reserved, cmd_id, val_high, val_low, 0, 0, 0]
```

Where `cmd_id` includes:
- 0-2: Move motors by X microns
- 10-12: Set velocity (coarse, fine, superfine)
- 20-21: Set mode (normal, rotate)
- 30-31: Zero positions
- 40-42, 50-52: Store/recall memory positions
- 60-61: Lock/unlock knobs

### 3. PC → Motor Controller (COM4)

The PC translates Knobby commands to **TMCL protocol** (9-byte packets):
```
[address, command, type, motor, value[4], checksum]
```

TMCL commands used:
- **MVP** (Move to Position): Command 4, Type 0 (absolute)
- **GAP** (Get Axis Parameter): Command 6
- **SAP** (Set Axis Parameter): Command 5
- **ROR/ROL** (Rotate Right/Left): Commands 1/2
- **MST** (Motor Stop): Command 3

## Data Flow for Position Reading

### To Read Current Position:

```
1. Python connects to motor controller (COM4)
2. Python sends TMCL GAP command: [1, 6, 1, motor, 0,0,0,0, checksum]
   - Command 6 = GAP (Get Axis Parameter)
   - Type 1 = Actual position
3. Motor controller responds with 9 bytes: [2, 100, 6, 0, value[4], checksum]
4. Python extracts value[4] = position in steps
5. Python converts: position_um = position_steps * motor_gain[motor]
```

### Knobby Display Update Flow:

```
1. User turns knob → encoder value changes
2. Knobby calculates new position in steps: dpos[i] += (encoder_change * mstep)
3. Knobby converts to microns: position_um = dpos[i] * motor_gain[i]
4. Knobby updates display: "Z = +1234.56 um"
5. Knobby sends position to PC via COM5  (5-byte packet: motor_id + dpos as int32 LE)
6. PC computes delta = dpos_new − dpos_prev and forwards it to the motor controller
   as a TMCL MVP Type 1 (relative) command — NOT an absolute move.  See note below.
7. Motor moves by the delta amount
```

> **Why relative, not absolute?**  The Knobby firmware tracks an accumulated
> offset (`dpos`) that starts at 0 after each reset or zero-button press.  This
> value is *not* the motor controller's hardware step counter.  Forwarding
> `dpos` directly as an MVP Type 0 (absolute) command would drive all motors to
> hardware position 0 on startup (when `dpos` is still 0) and would produce
> wrong positions whenever the motor counter was not also zeroed.  Using the
> delta between consecutive `dpos` packets keeps the two coordinate systems
> independent and makes startup zero-packets harmless.

## Step Multipliers (mstep)

Knobby has three velocity modes that change how many steps occur per encoder count:

```cpp
// mstep[velocity_mode][motor] = steps per encoder count
float mstep[3][4] = {
    {10, 3.9370 * 10, 3.9370 * 10, 10},  // Coarse
    {5,  3.9370 * 5,  3.9370 * 5,  5},   // Fine
    {1,  3.9370,      3.9370,      1}    // Superfine
};
```

## Python Integration

### Reading Positions from Motor Controller

```python
import pyscanbox.hardware.motor
import pyscanbox.config

# Load configuration
config = pyscanbox.config.ScanboxConfig('config.yaml')
config['emulation']['enabled'] = False  # Use real hardware

# Connect to motor controller
motor = pyscanbox.hardware.motor.TrinamicMotor(config)
motor.open()

# Motor-to-micron conversion factors (from knobby2.ino)
motor_gain = [
    2000.0 / 400.0 / 32.0 / 2.0,      # Motor 0 (Z)
    (0.02 * 25400.0) / 400.0 / 64.0,  # Motor 1 (Y)
    (0.02 * 25400.0) / 400.0 / 64.0,  # Motor 2 (X)
    0.0225 / 64.0,                     # Motor 3 (A)
]

# Read positions
axis_names = ['Z', 'Y', 'X', 'A']
units = ['μm', 'μm', 'μm', 'deg']

for motor_id in range(4):
    pos_steps = motor.get_position(motor_id)
    if pos_steps is not None:
        pos_converted = pos_steps * motor_gain[motor_id]
        print(f"{axis_names[motor_id]}: {pos_steps} steps = {pos_converted:.2f} {units[motor_id]}")

motor.close()
```

### Future: Direct Knobby Communication (Optional)

If you want to read the displayed position directly from Knobby instead of the motor controller:

```python
import serial

# Connect to Knobby
knobby = serial.Serial('COM5', 57600, timeout=1)

# Send command to request current position (if protocol supports it)
# Note: Current knobby firmware doesn't have a "query position" command
# You would need to track positions sent from Knobby or modify firmware

knobby.close()
```

## Important Notes

1. **Knobby is NOT required to read positions** - you can read directly from the motor controller (COM4)

2. **Position may differ between Knobby display and actual motor position** if:
   - Motors are still moving to target
   - Motor stalled or hit limit
   - Communication error occurred

3. **Always read from motor controller for ground truth** - this is the actual hardware position

4. **Coordinate system**: 
   - Knobby uses Motor 0=Z, 1=Y, 2=X, 3=A
   - Z = focus/depth, Y = vertical stage, X = horizontal stage, A = objective angle
   - This matches the physical axes on the microscope stage

5. **Startup zero-packets (firmware quirk):** On the very first iteration of the
   Arduino `loop()`, the firmware detects that `page` (initialised to 1) differs
   from `oldpage` (initialised to -1) and immediately transmits a 5-byte
   position packet for each of the four axes with `dpos = 0`.  This happens
   before any knob has been turned.  Any PC-side code that forwards these
   packets as *absolute* MVP moves will drive all motors to hardware step
   position 0, which can be dangerous.  Always translate Knobby packets into
   *relative* (delta) moves to the motor controller, so that a zero-delta
   startup packet produces no physical movement.

6. **`dpos` is not the motor hardware counter:** The Knobby `dpos` array
   accumulates encoder deltas from the last zero/reset and is independent of
   the Trinamic board's absolute step counter.  Never use `dpos` directly as an
   MVP Type 0 (absolute) target.

## References

- **Knobby firmware**: `Scanbox/scanknob/knobby2/knobby2.ino`
- **TMCL protocol**: `pyscanbox/hardware/protocols.py`
- **Motor controller**: `pyscanbox/hardware/motor.py`
- **Original MATLAB**: `trinamic/tri_send.m`, `scanknob/scanknob.py`
