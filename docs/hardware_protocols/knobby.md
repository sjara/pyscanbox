# Knobby Position Controller Architecture

## Overview

The Knobby is an Arduino-based hardware controller that provides manual positioning control for the Neurolabware microscope. It consists of rotary encoders, a touchscreen display, and acts as an intermediary between the user and the Trinamic motor controller.

## Hardware Components

### 1. Arduino Microcontroller
- Runs the knobby firmware (`Scanbox/scanknob/knobby2/knobby2.ino` or newer like `knobby3_1.ino`). Note: The hardware available to the developer uses `knobby2_2.ino`.
- Connects to PC via Serial at **57600 baud** (COM5)
- Manages all I/O between encoders, display, and PC
- **Note**: Version 3 firmwares (like `knobby3_1.ino` for Model 3) support setups with only 3 physical knobs, utilizing a "Virtual A-axis" mode where the Z knob controls the A-axis when toggled via the touchscreen. Version 2 (e.g. `knobby2_2.ino`) uses 4 physical encoders.

### 2. Rotary Encoders (4x or 3x)
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
│  (Arduino)   │◄───────►│ (pyscanbox)  │◄───────►│      (COM4)          │
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

### Motor-Axis Mapping

The motor numbering is:
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
[0x01, 0xC8, reserved, cmd_id, val_high, val_low, val_high2, val_low2, reserved]
```

**Note:** The first two bytes (0x01 and 0xC8) are documented packet header values but are **not validated** by the Arduino firmware — they are ignored. The Arduino firmware reads all 9 bytes unconditionally, regardless of their values. These bytes appear to be convention/documentation only.

Where `cmd_id` (byte 3) includes:
- 0-2: Move motors Z, Y, X by X microns (converted to steps internally based on current velocity mode and gain)
- 3-5: Move motors Z, Y, X by explicit hardware steps **(v2_3 and v3+ only)**
- 10-12: Set velocity (coarse, fine, superfine)
- 20-21: Set mode (normal, rotate)
- 30-31: Zero positions (XYZ or XYZA)
- 40-42: Store memory positions (A, B, C)
- 50-52: Recall memory positions
- 60-61: Lock/unlock knobs
- 70: Reset hardware scheduler delta table
- 71-75: Append values to hardware scheduler table (Z delta, Y delta, X delta, memory flags, frame jumps)
- 76-78: Set delta modes for X, Y, Z axes **(v2_3 and v3+ only)**
- 80-81: Arm/Disarm hardware scheduler (interrupt-driven stepping, e.g., for automated Z-stacks)
- 100-103: Force a position report packet back to the PC for a specific axis (Z, Y, X, A)

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

For more details, see [Trinamic Motor Protocol](trinamic_motor.md).

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
6. PC computes `delta = dpos_new − dpos_prev`.
7. PC accumulates the delta into an absolute `desired_steps` tracker (seeded from the motor controller's hardware position at startup).
8. PC issues a TMCL MVP Type 0 (absolute) move command to the new `desired_steps` target.
9. Motor moves to the absolute target position.
```

> **Why absolute, not relative?** While an older implementation attempted sending relative commands (`MVP Type 1`), the current `pyscanbox` implementation specifically uses absolute moves (`MVP Type 0`) to a locally tracked coordinate. Using absolute moves is much smoother: if the knobs are turned faster than the motor can settle, each new command simply updates the target to the correct final destination, rather than compounding trajectory errors from executing multiple relative steps while the motor is already in motion. The PC-side `desired_steps` tracker is seeded at startup with the motor board's absolute hardware counter, ensuring that Knobby's `dpos` coordinate system and the hardware coordinates stay correctly aligned.

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

5. **Startup zero-packets (firmware quirk):** On the very first iteration of the
   Arduino `loop()`, the firmware detects that `page` (initialised to 1) differs
   from `oldpage` (initialised to -1) and immediately transmits a 5-byte
   position packet for each of the four axes with `dpos = 0`.  This happens
   before any knob has been turned.  Because `pyscanbox` computes the delta first
   (`delta = 0 - 0 = 0`), this results in a safe no-op that leaves the PC's
   absolute movement target unchanged. This cleanly resolves the danger of
   driving motors to hardware position 0 on startup.

6. **`dpos` is not the motor hardware counter:** The Knobby `dpos` array
   accumulates encoder deltas from the last zero/reset and is independent of
   the Trinamic board's absolute step counter.  Never use `dpos` directly as an
   MVP Type 0 (absolute) target. Instead, compute the delta and apply it as an
   offset to the current hardware step counter.

7. **Normal / Rotated mode button — no packet sent to the PC:** Knobby has a
   physical button that toggles between *Normal* mode (each encoder controls its
   own axis independently) and *Rotated* mode (turning the Z or X encoder
   applies a 2-D rotation by the current A-axis angle, so movements stay
   parallel/perpendicular to the objective axis rather than the stage horizon).
   When the button is pressed the firmware toggles an internal `mode` variable
   and updates the Nextion touchscreen (`Serial1`), but it does **not** write
   any packet to the PC (`Serial`).  The PC therefore has no way to detect the
   current mode from the serial stream.

   The 5-byte position packets emitted while in Rotated mode already contain the
   post-rotation `dpos` values, so the motors always move correctly regardless
   of which mode Knobby is in.  From the PC's perspective the stream is
   byte-identical in both modes.

   **GUI design decision:** pyscanbox always computes and displays the
   *Rotated* coordinates panel (stage-axis frame, accounting for objective
   tilt), even when Knobby may be in Normal mode.  Because we cannot observe the
   mode over serial, graying out the panel conditionally is not possible without
   a dedicated firmware change.  The Rotated coordinates remain valid at all
   times; they are simply not being actively used when the user is in Normal
   mode.

## References

- **Knobby firmware**: `Scanbox/scanknob/knobby2/knobby2.ino`, `Scanbox/scanknob/knobby3_1/knobby3_1.ino`
- **TMCL protocol**: `pyscanbox/hardware/protocols.py`
- **Motor controller**: `pyscanbox/hardware/motor.py`
- **Original MATLAB**: `trinamic/tri_send.m`, `scanknob/scanknob.py`
