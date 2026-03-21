# Scanbox Controller Protocol

Low-level protocol specification for the Scanbox PSoC 5LP controller.

## Overview

The main Scanbox controller (PSoC 5LP-based) communicates via serial at **1,000,000 baud (1 Mbaud)**.

**Original Hardware:** Custom PSoC 5LP 32-bit ARM processor card (Cypress)  
**Reference:** https://scanbox.org/2014/03/13/welcome-to-scanbox/

**Capabilities:**
- Generates scan signals for resonant scanner
- Generates trigger signals for cameras
- Timestamps external TTL events (two TTL signals with frame and line numbers)
- Controls Pockels cell, laser shutter, and mirror actuators
- Additional digital I/O, I2C, SPI expansion capability
- Current generator for electrically tuned lens

## Packet Structure

All commands are **3-byte packets**:

```
[Command_ID, Parameter_1, Parameter_2]
```

## Command Reference

### Frame Count Configuration (ID: 1)

Sets the number of frames to acquire.

**Command Format:**
```python
[1, frame_high, frame_low]
```

**Parameters:**
- Byte 0: Command ID (1)
- Byte 1: High byte of frame count (bits 8-15)
- Byte 2: Low byte of frame count (bits 0-7)

**Example:**
```python
# Set frame count to 1000 (0x03E8)
frames = 1000
controller.send([1, (frames >> 8) & 0xFF, frames & 0xFF])
# Sends: [1, 3, 232]
```

**Original MATLAB Reference:** `sb/sb_setframe.m`

---

### Lines Per Frame Configuration (ID: 2)

Sets the number of scan lines per frame.

**Command Format:**
```python
[2, line_high, line_low]
```

**Parameters:**
- Byte 0: Command ID (2)
- Byte 1: High byte of line count (bits 8-15)
- Byte 2: Low byte of line count (bits 0-7)

**Example:**
```python
# Set 512 lines per frame (0x0200)
lines = 512
controller.send([2, (lines >> 8) & 0xFF, lines & 0xFF])
# Sends: [2, 2, 0]
```

**Original MATLAB Reference:** `sb/sb_setline.m`

---

### Magnification Configuration (ID: 3)

Sets the magnification/zoom level.

**Command Format:**
```python
[3, 0, magnification]
```

**Parameters:**
- Byte 0: Command ID (3)
- Byte 1: Always 0
- Byte 2: Magnification index (0–12; MATLAB sends `popup.Value - 1` where popup has
  13 items numbered 1–13)

**Notes:**
- 13 discrete zoom levels in total (0 = largest FOV / minimum zoom,
  12 = smallest FOV / maximum zoom).
- Values outside 0–12 are rejected by `set_magnification()` in
  `pyscanbox/hardware/controller.py`.

**Example:**
```python
# Set to zoom level 4 (5th item in the MATLAB popup)
controller.send([3, 0, 4])
```

**Original MATLAB Reference:** `sb/sb_setmag.m`

---

### Scan Control (ID: 4)

Starts or stops the scanning system.

**Command Format:**
```python
[4, 0, state]
```

**Parameters:**
- Byte 0: Command ID (4)
- Byte 1: Always 0
- Byte 2: State (0 = stop/abort, 1 = start)

**Examples:**
```python
# Start scanning
controller.send([4, 0, 1])

# Stop/abort scanning
controller.send([4, 0, 0])
```

**Original MATLAB Reference:** `sb/sb_scan.m`, `sb/sb_abort.m`

---

### Mirror Toggle (ID: 5)

Switches between two-photon (2P) and epifluorescence (epi) optical paths using a Firgelli linear actuator.

**Command Format:**
```python
[5, 0, mode]
```

**Parameters:**
- Byte 0: Command ID (5)
- Byte 1: Always 0
- Byte 2: Mode (0 = 2P path, 1 = epi path)

**Examples:**
```python
# Switch to 2P path
controller.send([5, 0, 0])

# Switch to epi/fluorescence path
controller.send([5, 0, 1])
```

**Original MATLAB Reference:** `sb/sb_mirror.m`

---

### PMT0 Gain Control (ID: 6)

Sets the gain for photomultiplier tube 0.

**Command Format:**
```python
[6, 0, gain]
```

**Parameters:**
- Byte 0: Command ID (6)
- Byte 1: Always 0
- Byte 2: Gain value (0-255, where 255 = maximum gain)

**Example:**
```python
# Set PMT0 to 50% gain
controller.send([6, 0, 128])
```

**Original MATLAB Reference:** `sb/sb_gain0.m`

---

### PMT1 Gain Control (ID: 7)

Sets the gain for photomultiplier tube 1.

**Command Format:**
```python
[7, 0, gain]
```

**Parameters:**
- Byte 0: Command ID (7)
- Byte 1: Always 0
- Byte 2: Gain value (0-255, where 255 = maximum gain)

**Example:**
```python
# Set PMT1 to 50% gain
controller.send([7, 0, 128])
```

**Original MATLAB Reference:** `sb/sb_gain1.m`

---

### Pockels Cell Control (ID: 8)

Controls laser power during imaging.

**Command Format:**
```python
[8, base_power, active_power]
```

**Parameters:**
- `base_power` (0-255): Baseline power level (typically lower, for idle/flyback)
- `active_power` (0-255): Active imaging power level (during line scan)

**Example:**
```python
# Set 10% base power, 85% active power
controller.send([8, 26, 217])  # 26/255 ≈ 10%, 217/255 ≈ 85%
```

**Original MATLAB Reference:** `sb/sb_pockels.m`

---

### Pockels Deadband Control (ID: 9)

Configures the left and right deadband regions where the Pockels cell is turned off (at line margins).

**Command Format:**
```python
[9, left_deadband, right_deadband]
```

**Parameters:**
- Byte 0: Command ID (9)
- Byte 1: Left deadband size (pixels)
- Byte 2: Right deadband size (pixels)

**Example:**
```python
# Set deadband: 120 pixels on left, 150 on right
controller.send([9, 120, 150])
```

**Note:** The deadband defines regions at the beginning and end of each scan line where the laser is blanked to avoid edge artifacts.

**Original MATLAB Reference:** `sb/sb_deadband.m`

---

### Shutter Control (ID: 16)

Opens or closes the laser shutter.

**Command Format:**
```python
[16, 0, state]
```

**Parameters:**
- Byte 0: Command ID (16)
- Byte 1: Always 0
- Byte 2: State (0 = closed, 1 = open)

**Examples:**
```python
# Open shutter
controller.send([16, 0, 1])

# Close shutter
controller.send([16, 0, 0])
```

**Original MATLAB Reference:** `sb/sb_shutter.m`

**Notes on rig-specific behavior:**

In the original Scanbox system this command drives a **Uniblitz** shutter
connected to the LASER SHUTTER output on the controller front panel.

On some rigs a different shutter model (e.g., ThorLabs) is connected to
the same LASER SHUTTER output but is triggered by the **Scan Control
command (ID 4)** rather than this command. In that configuration,
`CMD_SHUTTER` (ID 16) is still sent for compatibility with original
Scanbox systems, but produces no hardware effect on its own — the shutter
opens and closes automatically with `start_scan()` / `stop_scan()`.

This difference is determined by how the shutter driver is wired to the
controller outputs and is not configurable in software.

---

### ETL Current Control (ID: 48)

Sets the current for the Optotune Electrically Tunable Lens (ETL), which
controls axial focus position without mechanical objective movement.

The current value is encoded as a 16-bit word: the upper nibble is always
`0b0111` (hardware convention for the PSoC5 DAC channel), and the lower 12
bits carry the current value. The two bytes of the encoded word are sent as
`param1` (upper byte) and `param2` (lower byte).

**Command Format:**
```python
[48, b1, b2]
```

where:
```python
encoded = 0x7000 | (current & 0x0FFF)
b1 = (encoded >> 8) & 0xFF  # upper byte
b2 =  encoded       & 0xFF  # lower byte
```

**Parameters:**
- `current` (0–1760): ETL current in arbitrary units (~61.5 µA per count).
  Values above 1760 are not used by MATLAB; the 12-bit hardware maximum is 4095.

**Example:**
```python
# Set ETL to mid-range (current = 880)
current = 880
encoded = 0x7000 | (current & 0x0FFF)  # 0x7370
b1 = (encoded >> 8) & 0xFF             # 0x73 = 115
b2 = encoded & 0xFF                    # 0x70 = 112
controller.send([48, 115, 112])
```

**Original MATLAB Reference:** `sb/sb_current.m`

---

### Unidirectional Scan Mode (ID: 33)

Switches the resonant scanner to unidirectional mode. Data is acquired on the forward sweep only; the return sweep is discarded.

**Command Format:**
```python
[33, 0, 0]
```

**Parameters:**
- Byte 0: Command ID (33)
- Byte 1: Always 0
- Byte 2: Always 0

**Example:**
```python
controller.send([33, 0, 0])
```

**Original MATLAB Reference:** `sb/sb_unidirectional.m`

---

### Bidirectional / Continuous Resonant Mode (ID: 34)

Controls bidirectional scanning and continuous resonant mode. Bidirectional mode acquires data on both the forward and return sweeps, doubling the effective frame rate at the cost of requiring pixel-shift correction between odd and even lines.

The `param1` byte selects the sub-mode:
- `param1 = 0`: Bidirectional scan (acquire on both sweeps; resonant scanner not kept running continuously)
- `param1 = 1`: Continuous resonant mode (scanner runs continuously even when not acquiring frames)

**Command Format:**
```python
[34, sub_mode, 0]
```

**Parameters:**
- Byte 0: Command ID (34)
- Byte 1: Sub-mode (0 = bidirectional, 1 = continuous resonant)
- Byte 2: Always 0

**Examples:**
```python
# Enable bidirectional scanning
controller.send([34, 0, 0])

# Enable continuous resonant mode (scanner keeps running between acquisitions)
controller.send([34, 1, 0])

# Disable continuous resonant mode (falls back to bidirectional)
controller.send([34, 0, 0])
```

**Original MATLAB Reference:** `sb/sb_bidirectional.m`, `sb/sb_continuous_resonant.m`

---

### Line Scan Mode (ID: 53 / 0x35)

> **pyscanbox scope:** Out of scope — remove this line when implemented.

Enables or disables line scan mode, in which the scanner repeatedly sweeps a single line instead of raster-scanning a 2D frame. Used for high-speed 1D recordings along a fixed line.

**Command Format:**
```python
[53, state, 0]
```

**Parameters:**
- Byte 0: Command ID (53 / 0x35)
- Byte 1: State (1 = enable line scan, 0 = disable)
- Byte 2: Always 0

**Examples:**
```python
# Enable line scan mode
controller.send([53, 1, 0])

# Disable line scan mode
controller.send([53, 0, 0])
```

**Original MATLAB Reference:** `sb/sb_linescan.m`

---

### TTL Interrupt Mask (ID: 64 / 0x40)

Selects which external TTL input lines on the Scanbox controller card are
monitored for edge events.  When an enabled input transitions, the PSoC5
firmware **immediately sends a 5-byte event packet back** on the same serial
port (see [TTL Event Packet](#ttl-event-packet) below).

The two physical inputs are labelled **TTL0** and **TTL1** and are exposed
as SMA connectors on the controller card front panel.  By default TTL0 fires
on the rising edge only; TTL1 fires on both rising and falling edges.

**Command Format:**
```python
[64, 0, imask]
```

**Parameters:**
- Byte 0: Command ID (64 / 0x40)
- Byte 1: Always 0
- Byte 2: `imask` — interrupt mask

  | `imask` | Enabled inputs |
  |---------|----------------|
  | 0       | None (disabled) |
  | 1       | TTL0 only |
  | 2       | TTL1 only |
  | 3       | TTL0 and TTL1 |

> **Warning:** Never enable a TTL input without a signal connected.
> Floating inputs will generate a storm of spurious events.

**Examples:**
```python
# Disable both TTL inputs (safe default)
controller.send([64, 0, 0])

# Enable TTL1 only (e.g. stimulus signal on both edges)
controller.send([64, 0, 2])

# Enable both TTL0 and TTL1
controller.send([64, 0, 3])
```

**pyscanbox implementation:**
`ScanboxController.set_ttl_mask(imask)`.  Called from
`Scanner.configure_scan_params()` using the `external_events.interrupt_mask`
config key (default 0 = disabled).

**Original MATLAB Reference:** `sb/sb_imask.m`

---

### TTL Event Packet (PSoC5 → PC, unsolicited 5-byte response)

When the TTL interrupt mask is non-zero and a TTL event fires, the PSoC5
sends an unsolicited **5-byte packet** back on the **same serial port** used
for outgoing commands:

```
Byte 0:  frame_low   — low byte of current frame number
Byte 1:  frame_high  — high byte of current frame number
Byte 2:  line_low    — low byte of current line number within frame
Byte 3:  line_high   — high byte of current line number within frame
Byte 4:  event_id    — which input(s) fired (see table below)
```

Reconstruction:
```python
frame_number = packet[0] + packet[1] * 256   # uint16
line_number  = packet[2] + packet[3] * 256   # uint16
event_id     = packet[4]                     # uint8
```

`event_id` values:

| `event_id` | Meaning |
|------------|---------|
| 1          | TTL0 fired |
| 2          | TTL1 fired |
| 3          | TTL0 and TTL1 fired within same frame/line |
| 255        | Acquisition-complete sentinel (not a user TTL event) |

The time resolution of event timestamps equals one resonant mirror half-period
(~125 µs in unidirectional mode at 7930 Hz / 512 lines).

**Receiving packets in pyscanbox:**

`ScanboxController.start_ttl_reader()` starts a background daemon thread
that polls `port.in_waiting` every 5 ms, reads complete 5-byte packets,
discards the `event_id = 255` sentinel, and appends the remainder to an
internal list.  After acquisition, `get_ttl_events()` returns a list of
`(frame, line, event_id)` tuples which `Scanner._create_metadata()` saves
in the `.mat` file as the MATLAB-compatible fields `frame`, `line`, and
`event_id`.

**Original MATLAB Reference:**
- `core/serialcb.m` — MATLAB serial callback (reads 5 bytes into global `T`)
- `core/scanbox.m` (`sb_callback` function) — accumulates packets in `T`
- `core/scanbox.m` (end of acquisition) — saves `T` via `sb_timestamps()` → `info`

---

### Echo / Communication Test (ID: 119 / 0x77)

Sends a fixed magic payload and reads back 3 bytes from the controller to verify that the serial link is working. This is one of the two commands where the controller **sends a response**.

**Command Format:**
```python
[0x77, 0xAA, 0x55]
```

**Parameters:**
- Byte 0: Command ID (0x77 = 119)
- Byte 1: Magic value 0xAA (fixed)
- Byte 2: Magic value 0x55 (fixed)

**Response:** Controller echoes back 3 bytes. A successful read confirms communication.

**Example:**
```python
import serial
port.write(bytes([0x77, 0xAA, 0x55]))
response = port.read(3)  # 3-byte echo response
if len(response) == 3:
    print('Communication OK')
```

**Original MATLAB Reference:** `sb/sb_echo.m`

---

### Firmware Version Query (ID: 120 / 0x78)

Queries the firmware version running on the PSoC5 controller. This is one of the two commands where the controller **sends a response**.

**Command Format:**
```python
[0x78, 0xAA, 0x55]
```

**Parameters:**
- Byte 0: Command ID (0x78 = 120)
- Byte 1: Magic value 0xAA (fixed)
- Byte 2: Magic value 0x55 (fixed)

**Response:** Controller replies with 3 bytes. Bytes 2 and 3 (index 1 and 2) encode the major and minor version numbers respectively, giving a version string of `"major.minor"`.

**Example:**
```python
port.write(bytes([0x78, 0xAA, 0x55]))
response = port.read(3)
version = f'{response[1]}.{response[2]}'
print(f'Firmware version: {version}')
```

**Original MATLAB Reference:** `sb/sb_version.m`

---

### Camera Control (ID: 121 / 0x79)

> **pyscanbox scope:** Out of scope — remove this line when implemented.

Controls the camera interface on the controller.

**Command Format:**
```python
[0x79, val, 0]
```

**Parameters:**
- Byte 0: Command ID (0x79 = 121)
- Byte 1: Camera control value
- Byte 2: Always 0

**Example:**
```python
controller.send([0x79, val, 0])
```

**Original MATLAB Reference:** `sb/sb_ccam.m`

---

### H-sync Polarity (ID: 128 / 0x80)

> **pyscanbox scope:** Out of scope — remove this line when implemented.

Sets the polarity of the horizontal sync signal.

**Command Format:**
```python
[0x80, val, 0]
```

**Parameters:**
- Byte 0: Command ID (0x80 = 128)
- Byte 1: Polarity value (uint8)
- Byte 2: Always 0

**Example:**
```python
controller.send([0x80, val, 0])
```

**Original MATLAB Reference:** `sb/sb_hsync_sign.m`

---

### Magnification Calibration X-axis Indexed (IDs: 176–188 / 0xB0–0xBC)

Sets the X-axis (resonant scanner) gain amplitude for one of the 13 zoom levels.
A higher gain value produces a wider scan amplitude and a larger horizontal field
of view (lower effective magnification) at that zoom index.

In the original Scanbox system the values sent here come from
`sbconfig.gain_resonant`, derived as:

```
gain_resonant = gain_resonant_mult × gain_galvo
```

where `gain_resonant_mult = 1.42` is a rig-specific aspect-ratio corrector
compensating for the resonant mirror having a different voltage-to-angle curve
than the galvo. `gain_galvo = logspace(log10(1), log10(8), 13)` spans 1.0 to
8.0 across 13 zoom levels.

Float encoding: the value `x` is split into `xh = floor(x)` (integer part)
and `xl = floor((x − xh) × 10)` (tenths digit). Only the first decimal digit
is representable; values are truncated, not rounded.

**Command Format:**
```python
[0xB0 + i, xh, xl]   # i = 0 to 12
```

**Parameters:**
- Byte 0: Command ID (0xB0 + i, where i is the 0-based zoom-level index)
- Byte 1: `xh = floor(x)` — integer part of gain value
- Byte 2: `xl = floor((x - xh) × 10)` — tenths digit of gain value

**Example:**
```python
# Set X-axis gain for zoom index 5 (≈2.4x) to resonant gain ≈ 3.3
i = 5
x = 1.42 * 2.378  # gain_resonant[5] ≈ 3.377
xh = int(x)              # 3
xl = int((x - xh) * 10) # 3
controller.send([0xB0 + i, xh, xl])
```

**pyscanbox implementation:**
`ScanboxController.set_mag_x_gain(index, value)`. Called for all 13 zoom levels
by `update_scanner_gains(gain_galvo, gain_resonant, dv_galvo)` when
`scanner.gain_override` is `true` in config.
Config keys: `scanner.gain_galvo` (13-element array) and
`scanner.gain_resonant_mult` (default 1.42); `gain_resonant` is derived at
runtime as `gain_resonant_mult × gain_galvo`.

**Original MATLAB Reference:** `sb/sb_set_mag_x_i.m`
Config: `sbconfig.gain_resonant = sbconfig.gain_resonant_mult * sbconfig.gain_galvo;`

---

### Magnification Calibration Y-axis Indexed (IDs: 192–204 / 0xC0–0xCC)

Sets the Y-axis (galvo scanner) gain amplitude for one of the 13 zoom levels.
A higher gain value produces a taller scan amplitude and a larger vertical field
of view (lower effective magnification) at that zoom index.

In the original Scanbox system the values come directly from `sbconfig.gain_galvo`:

```
gain_galvo = logspace(log10(1), log10(8), 13)
```

This yields 13 values logarithmically spaced from 1.0 to 8.0. Index 0
(1.0x, widest FOV) → gain 1.0; index 12 (8.0x, narrowest FOV) → gain 8.0.
These values also determine the zoom-level labels shown in the MATLAB GUI
popup (formatted as `"%.1f"`).

Float encoding is identical to the X-axis indexed variant: `xh = floor(x)`,
`xl = floor((x − xh) × 10)` (tenths digit only).

**Command Format:**
```python
[0xC0 + i, xh, xl]   # i = 0 to 12
```

**Parameters:**
- Byte 0: Command ID (0xC0 + i, where i is the 0-based zoom-level index)
- Byte 1: `xh = floor(x)` — integer part of gain value
- Byte 2: `xl = floor((x - xh) × 10)` — tenths digit of gain value

**Example:**
```python
# Set Y-axis gain for zoom index 3 (≈1.7x) to galvo gain ≈ 1.6
i = 3
x = 1.682  # gain_galvo[3] = logspace(log10(1), log10(8), 13)[3] ≈ 1.682
xh = int(x)              # 1
xl = int((x - xh) * 10) # 6
controller.send([0xC0 + i, xh, xl])
```

**pyscanbox implementation:**
`ScanboxController.set_mag_y_gain(index, value)`. Called for all 13 zoom levels
by `update_scanner_gains(gain_galvo, gain_resonant, dv_galvo)` when
`scanner.gain_override` is `true` in config.
Config key: `scanner.gain_galvo` (13-element array, default
`logspace(log10(1), log10(8), 13)` ≈ `[1.0, 1.2, 1.4, 1.7, 2.0, 2.4, 2.8, 3.4, 4.0, 4.8, 5.7, 6.7, 8.0]`).

**Original MATLAB Reference:** `sb/sb_set_mag_y_i.m`
Config: `sbconfig.gain_galvo = logspace(log10(1),log10(8),13);`

---

### Gain Override Initialization Sequence

During system startup, when `sbconfig.gain_override > 0` (`core/scanbox.m`
lines 253–262), the following sequence is sent once to program custom
per-zoom-level scan amplitudes into the PSoC5 firmware:

```
1. [0x66, dv_galvo, 0]            — Galvo differential voltage (once)
2. [0xB0+0, xh, xl] … [0xB0+12, xh, xl]  — Resonant (X) gain for each of 13 zoom levels
3. [0xC0+0, yh, yl] … [0xC0+12, yh, yl]  — Galvo (Y) gain for each of 13 zoom levels
```

The MATLAB source:

```matlab
if(sbconfig.gain_override>0)
    sb_galvo_dv(sbconfig.dv_galvo);
    for k=1:length(sbconfig.gain_resonant)
        sb_set_mag_x_i(k-1, sbconfig.gain_resonant(k));
        sb_set_mag_y_i(k-1, sbconfig.gain_galvo(k));
    end
end
```

The four config keys involved:

| Config key (`sbconfig.*`) | pyscanbox key | Default | Description |
|---------------------------|---------------|---------|-------------|
| `gain_override` | `scanner.gain_override` | `true` | If true, send custom gains on startup |
| `dv_galvo` | `scanner.dv_galvo` | `64` | Galvo voltage step per line (max = 64) |
| `gain_galvo` | `scanner.gain_galvo` | `logspace(1,8,13)` | Galvo (Y) gain for each of the 13 zoom levels |
| `gain_resonant_mult` | `scanner.gain_resonant_mult` | `1.42` | Resonant/galvo aspect-ratio corrector |

`gain_resonant` is derived (not stored independently):
`gain_resonant[i] = gain_resonant_mult × gain_galvo[i]`.

If `gain_override` is false (or absent), the PSoC5 uses whatever gain values
are already in its firmware — suitable only when the firmware has been
pre-programmed with the correct gains for this rig.

**pyscanbox implementation:**
`ScanboxController.update_scanner_gains(gain_galvo, gain_resonant, dv_galvo)`.
Called once from `Scanner.configure_scan_params()` (or equivalent startup
routine) when `scanner.gain_override` is `true` in the YAML config.

---

### Controller Reset (ID: 255)

Performs a soft reset of the PSoC5 controller, returning it to its power-on state.

**Command Format:**
```python
[255, 0, 0]
```

**Parameters:**
- Byte 0: Command ID (255)
- Byte 1: Always 0
- Byte 2: Always 0

**Example:**
```python
controller.send([255, 0, 0])
```

**Original MATLAB Reference:** `sb/sb_reset.m`

---

### Pockels Deadband Period (ID: 10)

Sets the PWM period for the Pockels cell deadband signal. Must be called **before** `sb_deadband` (ID 9) when changing the deadband configuration.

The hardware requires the raw period value `p` to satisfy `1245 < p < 1500`. MATLAB passes the desired period value and the firmware applies the transformation `1500 - p` internally; pyscanbox should send the pre-transformed byte directly (i.e. send `1500 - p` as the parameter).

**Command Format:**
```python
[10, 0, period]
```

**Parameters:**
- Byte 0: Command ID (10)
- Byte 1: Always 0
- Byte 2: Pre-transformed period value (`1500 - p`, where `1245 < p < 1500`; result fits in one byte)

**Example:**
```python
# Set deadband period p=1400; send 1500-1400 = 100
controller.send([10, 0, 100])
```

**Original MATLAB Reference:** `sb/sb_deadband_period.m`

---

### Warmup Delay (ID: 11)

> **pyscanbox scope:** Out of scope — remove this line when implemented.

Sets the resonant scanner warmup delay period in units of 10 milliseconds.

**Command Format:**
```python
[11, 0, period]
```

**Parameters:**
- Byte 0: Command ID (11)
- Byte 1: Always 0
- Byte 2: Warmup delay in units of 10 ms

**Example:**
```python
# Set 500 ms warmup delay (50 × 10 ms)
controller.send([11, 0, 50])
```

**Original MATLAB Reference:** `sb/sb_warmup_delay.m`

---

### Camera Pulse Width (ID: 12)

> **pyscanbox scope:** Out of scope — remove this line when implemented.

Sets the width of the CAM0/CAM1 trigger pulse in scan lines. One scan line = 1/8000 s ≈ 125 µs.

**Command Format:**
```python
[12, 0, width]
```

**Parameters:**
- Byte 0: Command ID (12)
- Byte 1: Always 0
- Byte 2: Pulse width in scan lines

**Example:**
```python
# Set camera pulse width to 2 scan lines
controller.send([12, 0, 2])
```

**Original MATLAB Reference:** `sb/sb_cam_pulse_width.m`

---

### Pockels Range (ID: 13)

Sets the range of the Pockels cell DAC output and the programmable gain amplifier (PGA).

**Command Format:**
```python
[13, dac_range, pga_range]
```

**Parameters:**
- Byte 0: Command ID (13)
- Byte 1: DAC range value
- Byte 2: PGA range value

**Example:**
```python
controller.send([13, dac_val, pga_val])
```

**Original MATLAB Reference:** `sb/sb_pockels_range.m`

---

### Pockels Mode (ID: 17)

Sets the operating mode of the Pockels cell controller.

**Command Format:**
```python
[17, 0, mode]
```

**Parameters:**
- Byte 0: Command ID (17)
- Byte 1: Always 0
- Byte 2: Mode value

**Example:**
```python
controller.send([17, 0, mode])
```

**Original MATLAB Reference:** `sb/sb_pockels_mode.m`

---

### Pockels LUT Write (ID: 67 / 0x43)

Writes a single entry into the Pockels cell lookup table (LUT). The LUT maps a position index to a laser power value, enabling non-uniform power correction across the scan line.

**Command Format:**
```python
[0x43, index, value]
```

**Parameters:**
- Byte 0: Command ID (0x43 = 67)
- Byte 1: LUT index (uint8)
- Byte 2: LUT value (uint8)

**Example:**
```python
# Set LUT entry 10 to value 200
controller.send([0x43, 10, 200])
```

**Original MATLAB Reference:** `sb/sb_pockels_lut.m`

---

### Pockels LUT Reset to Identity (ID: 68 / 0x44)

Resets the entire Pockels cell LUT to the identity mapping (each index maps to the same output value), disabling any non-uniform power correction.

**Command Format:**
```python
[0x44, 0, 0]
```

**Parameters:**
- Byte 0: Command ID (0x44 = 68)
- Byte 1: Always 0
- Byte 2: Always 0

**Example:**
```python
controller.send([0x44, 0, 0])
```

**Original MATLAB Reference:** `sb/sb_pockels_lut_identity.m`

---

### Magnification Calibration X-axis Fixed (IDs: 96–98 / 0x60–0x62)

> **pyscanbox scope:** Out of scope — the indexed variants (IDs 0xB0–0xBC) cover all 13 zoom levels and are used instead.

Sets the X-axis magnification calibration coefficient for each of three fixed zoom levels (0, 1, 2). The float value `x` is encoded as two bytes: `xh = floor(x)` (integer part) and `xl = floor((x − xh) × 10)` (tenths digit).

These are legacy commands that only address the first three zoom levels. They appear in `sb/sb_update_gains.m` but `core/scanbox.m` uses the indexed variants (IDs 0xB0–0xBC) to set all 13 levels in the `gain_override` block.

| ID (dec) | ID (hex) | MATLAB file | Zoom level |
|----------|----------|-------------|------------|
| 96 | 0x60 | `sb_set_mag_x_0.m` | 0 |
| 97 | 0x61 | `sb_set_mag_x_1.m` | 1 |
| 98 | 0x62 | `sb_set_mag_x_2.m` | 2 |

**Command Format:**
```python
[0x60 + n, xh, xl]   # n = 0, 1, or 2
```

**Parameters:**
- Byte 0: Command ID (96 + n)
- Byte 1: `xh = floor(x)` — integer part of calibration value
- Byte 2: `xl = floor((x - xh) × 10)` — tenths digit

**Example:**
```python
# Set X-axis zoom level 0 calibration to 1.5
x = 1.5
xh = int(x)              # 1
xl = int((x - xh) * 10) # 5
controller.send([0x60, xh, xl])
```

**Original MATLAB Reference:** `sb/sb_set_mag_x_0.m`, `sb/sb_set_mag_x_1.m`, `sb/sb_set_mag_x_2.m`

---

### Magnification Calibration Y-axis Fixed (IDs: 99–101 / 0x63–0x65)

> **pyscanbox scope:** Out of scope — the indexed variants (IDs 0xC0–0xCC) cover all 13 zoom levels and are used instead.

Sets the Y-axis magnification calibration coefficient for each of three fixed zoom levels (0, 1, 2). Same encoding as X-axis fixed (IDs 96–98).

These are legacy commands that only address the first three zoom levels. They appear in `sb/sb_update_gains.m` but `core/scanbox.m` uses the indexed variants (IDs 0xC0–0xCC) to set all 13 levels in the `gain_override` block.

| ID (dec) | ID (hex) | MATLAB file | Zoom level |
|----------|----------|-------------|------------|
| 99 | 0x63 | `sb_set_mag_y_0.m` | 0 |
| 100 | 0x64 | `sb_set_mag_y_1.m` | 1 |
| 101 | 0x65 | `sb_set_mag_y_2.m` | 2 |

**Command Format:**
```python
[0x63 + n, xh, xl]   # n = 0, 1, or 2
```

**Parameters:**
- Byte 0: Command ID (99 + n)
- Byte 1: `xh = floor(x)` — integer part of calibration value
- Byte 2: `xl = floor((x - xh) × 10)` — tenths digit

**Example:**
```python
# Set Y-axis zoom level 1 calibration to 2.3
x = 2.3
xh = int(x)              # 2
xl = int((x - xh) * 10) # 3
controller.send([0x64, xh, xl])
```

**Original MATLAB Reference:** `sb/sb_set_mag_y_0.m`, `sb/sb_set_mag_y_1.m`, `sb/sb_set_mag_y_2.m`

---

### Galvo Differential Voltage (ID: 102 / 0x66)

Sets the galvo mirror voltage step per scan line. This controls how far the
Y-axis (galvo) mirror advances between consecutive scan lines.

The hardware maximum is **64**, which is the standard value used in all normal
configurations (`sbconfig.dv_galvo = 64` in `scanbox_config.m`, comment:
"don't touch!"). Per-zoom-level angular scaling is handled separately by
the Y-axis indexed gain commands (IDs 0xC0–0xCC), not by this value.

This command is sent once at startup, immediately before uploading the
per-zoom-level gain tables, as part of the `gain_override` block in
`core/scanbox.m`. See [Gain Override Initialization Sequence](#gain-override-initialization-sequence).

**Command Format:**
```python
[0x66, dv, 0]
```

**Parameters:**
- Byte 0: Command ID (0x66 = 102)
- Byte 1: Differential voltage value (0–64; 64 = hardware maximum)
- Byte 2: Always 0

**Example:**
```python
# Set galvo differential voltage to maximum (standard configuration)
controller.send([0x66, 64, 0])
```

**pyscanbox implementation:**
`ScanboxController.set_galvo_dv(dv)`. Called by `update_scanner_gains()` when
`scanner.gain_override` is `true` in config.
Config key: `scanner.dv_galvo` (default 64).

**Original MATLAB Reference:** `sb/sb_galvo_dv.m`
Config: `sbconfig.dv_galvo = 64; % dv per line (64 is the maximum) -- don't touch!`

---

### ETL Current–Power Link (ID: 19)

Links a specific ETL current level `c` to a Pockels cell power level `p`, so that when the ETL steps to that current during a z-stack sweep, the laser power is automatically adjusted to compensate for depth-dependent signal attenuation.

**Command Format:**
```python
[19, current, power]
```

**Parameters:**
- Byte 0: Command ID (19)
- Byte 1: ETL current index (uint8)
- Byte 2: Laser power value (uint8)

**Example:**
```python
# Link ETL current 5 to laser power 180
controller.send([19, 5, 180])
```

**Original MATLAB Reference:** `sb/sb_current_power.m`

---

### ETL Current–Power Link Enable (ID: 20)

Activates or deactivates the current–power compensation link set by ID 19.

**Command Format:**
```python
[20, state, 0]
```

**Parameters:**
- Byte 0: Command ID (20)
- Byte 1: State (1 = active, 0 = inactive)
- Byte 2: Always 0

**Example:**
```python
# Enable current-to-power compensation
controller.send([20, 1, 0])
```

**Original MATLAB Reference:** `sb/sb_current_power_active.m`

---

### ETL Waveform Entry Write (ID: 21)

Writes a single current value into the ETL waveform table at the current waveform index. The 12-bit current value (0–4095) is split across two bytes: `b2` is the high byte (bits 8–11) and `b1` is the low byte (bits 0–7).

**Command Format:**
```python
[21, b2, b1]
```

**Parameters:**
- Byte 0: Command ID (21)
- Byte 1: High byte of current value (bits 8–11)
- Byte 2: Low byte of current value (bits 0–7)

**Example:**
```python
# Write current value 2048 (0x0800) to the current waveform index
current = 2048
controller.send([21, (current >> 8) & 0xFF, current & 0xFF])
# Sends: [21, 8, 0]
```

**Original MATLAB Reference:** `sb/sb_optowave.m`

---

### ETL Waveform Period (ID: 22)

Sets the period of the ETL waveform in frames (i.e. how many frames per full waveform cycle).

**Command Format:**
```python
[22, period, 0]
```

**Parameters:**
- Byte 0: Command ID (22)
- Byte 1: Period in frames (0–255)
- Byte 2: Always 0

**Example:**
```python
# Set ETL waveform period to 10 frames
controller.send([22, 10, 0])
```

**Original MATLAB Reference:** `sb/sb_optoperiod.m`

---

### ETL Waveform Active (ID: 23)

Activates or deactivates the ETL waveform playback (i.e. enables/disables stepping through the waveform table each frame).

**Command Format:**
```python
[23, state, 0]
```

**Parameters:**
- Byte 0: Command ID (23)
- Byte 1: State (1 = active, 0 = inactive)
- Byte 2: Always 0

**Example:**
```python
# Enable ETL waveform playback
controller.send([23, 1, 0])
```

**Original MATLAB Reference:** `sb/sb_optotune_active.m`

---

### ETL Waveform Index Reset (ID: 24)

Resets the internal waveform write/playback index to zero. Call this before writing a new waveform sequence with ID 21 to ensure entries are written from the start of the table.

**Command Format:**
```python
[24, 0, 0]
```

**Parameters:**
- Byte 0: Command ID (24)
- Byte 1: Always 0
- Byte 2: Always 0

**Example:**
```python
controller.send([24, 0, 0])
```

**Original MATLAB Reference:** `sb/sb_optowave_init.m`

---

### Optotune Control Entry Write (ID: 25)

Writes the next entry into the optotune control (optoctrl) waveform array. This command is always preceded by ID 35 (which resets the index and zeros the array), then called in a loop — once per waveform entry. Each entry is a 16-bit value split across two bytes.

**Command Format:**
```python
[25, b2, b1]
```

**Parameters:**
- Byte 0: Command ID (25)
- Byte 1: High byte of the 16-bit control value
- Byte 2: Low byte of the 16-bit control value

**Example:**
```python
# Write a full optoctrl waveform
controller.send([35, 0, 0])          # reset index first (ID 35)
for val in waveform_values:          # list of uint16 values
    b2 = (val >> 8) & 0xFF
    b1 = val & 0xFF
    controller.send([25, b2, b1])
```

**Original MATLAB Reference:** `sb/sb_optocontrol.m` (loop body)

---

### Galvo Position (ID: 32 / 0x20)

> **pyscanbox scope:** Out of scope — remove this line when implemented.

Sets the galvo scanner position directly using a 2-byte value.

**Command Format:**
```python
[0x20, val_b1, val_b2]
```

**Parameters:**
- Byte 0: Command ID (0x20 = 32)
- Byte 1: First byte of position value (uint8)
- Byte 2: Second byte of position value (uint8)

**Example:**
```python
val = [100, 50]
controller.send([0x20, val[0], val[1]])
```

**Original MATLAB Reference:** `sb/sb_galvo.m`

---

### Optotune Control Array Reset (ID: 35)

Resets the optoctrl waveform index to zero and zeros the entire optoctrl array. Always send this before uploading a new optoctrl waveform via ID 25.

**Command Format:**
```python
[35, 0, 0]
```

**Parameters:**
- Byte 0: Command ID (35)
- Byte 1: Always 0
- Byte 2: Always 0

**Example:**
```python
controller.send([35, 0, 0])
```

**Original MATLAB Reference:** `sb/sb_optocontrol.m` (preamble)

---

### Optotune Control Active (ID: 36)

Activates or deactivates the optoctrl waveform. When active, the controller steps through the optoctrl array to modulate the ETL on each frame.

**Command Format:**
```python
[36, state, 0]
```

**Parameters:**
- Byte 0: Command ID (36)
- Byte 1: State (1 = active, 0 = inactive)
- Byte 2: Always 0

**Example:**
```python
# Enable optoctrl waveform
controller.send([36, 1, 0])
```

**Original MATLAB Reference:** `sb/sb_optocontrol_active.m`

---

### Axis Gain Calibration (ID: 51)

> **pyscanbox scope:** Out of scope — remove this line when implemented.

Sets the gain multiplier for the X or Y scan axis at a specified range setting.

The axis and range are encoded into a single byte `code`:
- X axis: `code = 0xF0 + x` (where `x` is 0 = ×1, 1 = ×2, 2 = ×4)
- Y axis: `code = x`

The multiplier is encoded as `m = round((mult - 1) × 128 + 128)`.

**Command Format:**
```python
[51, code, gain]
```

**Parameters:**
- Byte 0: Command ID (51)
- Byte 1: Axis/range code (see encoding above)
- Byte 2: Encoded gain multiplier `m` (uint8)

**Example:**
```python
# Set X axis, ×2 range, multiplier 1.5
x = 1             # ×2 range
code = 0xF0 + x   # 0xF1 = 241 (X axis)
gain = round((1.5 - 1) * 128 + 128)  # 192
controller.send([51, code, gain])
```

**Original MATLAB Reference:** `sb/sb_axis_gain.m`

---

### TTL Trigger Enable (ID: 224 / 0xE0)

Enables recording of external TTL events. Once enabled, the controller timestamps incoming TTL pulses with the current frame and line number and makes them available for readout.

**Command Format:**
```python
[0xE0, 0, 0]
```

**Parameters:**
- Byte 0: Command ID (0xE0 = 224)
- Byte 1: Always 0
- Byte 2: Always 0

**Example:**
```python
controller.send([0xE0, 0, 0])
```

**Original MATLAB Reference:** `sb/sb_ttl_trig_enable.m`

---

### TTL Trigger Disable (ID: 225 / 0xE1)

Disables recording of external TTL events.

**Command Format:**
```python
[0xE1, 0, 0]
```

**Parameters:**
- Byte 0: Command ID (0xE1 = 225)
- Byte 1: Always 0
- Byte 2: Always 0

**Example:**
```python
controller.send([0xE1, 0, 0])
```

**Original MATLAB Reference:** `sb/sb_ttl_trig_disable.m`

---

### TTL Trigger Input Select (ID: 226 / 0xE2)

Selects which TTL input channel is monitored for event timestamping.

**Command Format:**
```python
[0xE2, channel, 0]
```

**Parameters:**
- Byte 0: Command ID (0xE2 = 226)
- Byte 1: Channel selector value
- Byte 2: Always 0

**Example:**
```python
# Select TTL input channel 1
controller.send([0xE2, 1, 0])
```

**Original MATLAB Reference:** `sb/sb_trig_sel.m`

---

### Intrinsic Imaging Mode (ID: 240 / 0xF0)

> **pyscanbox scope:** Out of scope — remove this line when implemented.

Enables or disables intrinsic imaging mode on the controller. Also resets the timestamp buffer when called.

**Command Format:**
```python
[0xF0, state, 0]
```

**Parameters:**
- Byte 0: Command ID (0xF0 = 240)
- Byte 1: State (1 = enable, 0 = disable)
- Byte 2: Always 0

**Examples:**
```python
# Enable intrinsic imaging mode
controller.send([0xF0, 1, 0])

# Disable intrinsic imaging mode
controller.send([0xF0, 0, 0])
```

**Original MATLAB Reference:** `sb/sb_intrinsic.m`

---

### LCD Title Refresh (ID: 254)

> **pyscanbox scope:** Out of scope — remove this line when implemented.

Refreshes/redraws the first line of the Scanbox controller LCD display.

**Command Format:**
```python
[254, 0, 0]
```

**Parameters:**
- Byte 0: Command ID (254)
- Byte 1: Always 0
- Byte 2: Always 0

**Example:**
```python
controller.send([254, 0, 0])
```

**Original MATLAB Reference:** `sb/sb_title.m`

---

## Command Summary Table

| ID | Command | Format | Purpose | Scope |
|----|---------|--------|---------|-------|
| 1 | Set Frame Count | `[1, high, low]` | Configure number of frames (16-bit) | In scope |
| 2 | Set Lines | `[2, high, low]` | Configure lines per frame (16-bit) | In scope |
| 3 | Set Magnification | `[3, 0, mag]` | Set zoom/magnification level | In scope |
| 4 | Scan Control | `[4, 0, state]` | Start (1) or stop/abort (0) scanning | In scope |
| 5 | Mirror Toggle | `[5, 0, mode]` | Switch 2P (0) or epi (1) path | In scope |
| 6 | PMT0 Gain | `[6, 0, gain]` | Set PMT channel 0 gain (0-255) | In scope |
| 7 | PMT1 Gain | `[7, 0, gain]` | Set PMT channel 1 gain (0-255) | In scope |
| 8 | Pockels Cell | `[8, base, active]` | Laser power control | In scope |
| 9 | Pockels Deadband | `[9, left, right]` | Line margin blanking | In scope |
| 10 | Pockels Deadband Period | `[10, 0, period]` | Set PWM period for deadband; call before ID 9 | In scope |
| 11 | Warmup Delay | `[11, 0, period]` | Set warmup delay (units of 10 ms) | Out of scope |
| 12 | Camera Pulse Width | `[12, 0, width]` | Set CAM0/1 trigger pulse width in scan lines | Out of scope |
| 13 | Pockels Range | `[13, dac, pga]` | Set Pockels DAC and PGA range | In scope |
| 16 | Shutter | `[16, 0, state]` | Open (1) or close (0) laser shutter | In scope |
| 17 | Pockels Mode | `[17, 0, mode]` | Set Pockels cell operating mode | In scope |
| 19 | ETL Current–Power Link | `[19, current, power]` | Link ETL current to laser power level | In scope |
| 20 | ETL Current–Power Link Enable | `[20, state, 0]` | Activate (1) / deactivate (0) current–power link | In scope |
| 21 | ETL Waveform Entry Write | `[21, b2, b1]` | Write current value (0–4095) to waveform table | In scope |
| 22 | ETL Waveform Period | `[22, period, 0]` | Set waveform period in frames (0–255) | In scope |
| 23 | ETL Waveform Active | `[23, state, 0]` | Activate (1) / deactivate (0) ETL waveform playback | In scope |
| 24 | ETL Waveform Index Reset | `[24, 0, 0]` | Reset waveform index to zero before writing | In scope |
| 25 | Optotune Control Entry Write | `[25, b2, b1]` | Write next optoctrl waveform entry (follow ID 35) | In scope |
| 32 / 0x20 | Galvo Position | `[0x20, b1, b2]` | Set galvo scanner position directly | Out of scope |
| 33 | Unidirectional Mode | `[33, 0, 0]` | Switch to unidirectional scan | In scope |
| 34 | Bidirectional / Continuous Resonant | `[34, sub_mode, 0]` | Bidirectional (0) or continuous resonant (1) mode | In scope |
| 35 | Optotune Control Array Reset | `[35, 0, 0]` | Reset optoctrl index and zero the entire array | In scope |
| 36 | Optotune Control Active | `[36, state, 0]` | Activate (1) / deactivate (0) optoctrl waveform | In scope |
| 48 | ETL Current | `[48, b1, b2]` | Set Optotune ETL current (0–1760, 16-bit encoded) | In scope |
| 51 | Axis Gain Calibration | `[51, code, gain]` | Set scan axis gain multiplier | Out of scope |
| 53 / 0x35 | Line Scan Mode | `[53, state, 0]` | Enable (1) or disable (0) line scan mode | Out of scope |
| 64 / 0x40 | TTL Interrupt Mask | `[64, 0, imask]` | Select which TTL inputs fire timestamped events (0=off, 1=TTL0, 2=TTL1, 3=both); PSoC5 returns unsolicited 5-byte event packets | In scope |
| 67 / 0x43 | Pockels LUT Write | `[0x43, index, value]` | Write one entry into the Pockels LUT | In scope |
| 68 / 0x44 | Pockels LUT Reset | `[0x44, 0, 0]` | Reset Pockels LUT to identity mapping | In scope |
| 96–98 / 0x60–0x62 | Mag Cal X (fixed) | `[0x60+n, xh, xl]` | Set X-axis mag calibration coefficient n (n=0–2) | Out of scope |
| 99–101 / 0x63–0x65 | Mag Cal Y (fixed) | `[0x63+n, xh, xl]` | Set Y-axis mag calibration coefficient n (n=0–2) | Out of scope |
| 102 / 0x66 | Galvo Differential | `[0x66, val, 0]` | Set galvo differential voltage | Out of scope |
| 119 / 0x77 | Echo / Comm Test | `[0x77, 0xAA, 0x55]` | Verify serial link; controller responds with 3 bytes | In scope |
| 120 / 0x78 | Firmware Version | `[0x78, 0xAA, 0x55]` | Query firmware version; controller responds with 3 bytes | In scope |
| 121 / 0x79 | Camera Control | `[0x79, val, 0]` | Camera interface control | Out of scope |
| 128 / 0x80 | H-sync Polarity | `[0x80, val, 0]` | Set horizontal sync signal polarity | Out of scope |
| 176–188 / 0xB0–0xBC | Mag Cal X (indexed) | `[0xB0+i, xh, xl]` | Set X-axis mag calibration at index i (i=0–12) | Out of scope |
| 192–204 / 0xC0–0xCC | Mag Cal Y (indexed) | `[0xC0+i, xh, xl]` | Set Y-axis mag calibration at index i (i=0–12) | Out of scope |
| 224 / 0xE0 | TTL Trigger Enable | `[0xE0, 0, 0]` | Enable external TTL event timestamping | In scope |
| 225 / 0xE1 | TTL Trigger Disable | `[0xE1, 0, 0]` | Disable external TTL event timestamping | In scope |
| 226 / 0xE2 | TTL Trigger Input Select | `[0xE2, channel, 0]` | Select which TTL input to monitor | In scope |
| 240 / 0xF0 | Intrinsic Imaging Mode | `[0xF0, state, 0]` | Enable (1) / disable (0) intrinsic imaging mode | Out of scope |
| 254 | LCD Title Refresh | `[254, 0, 0]` | Refresh the first line of the controller LCD | Out of scope |
| 255 | Controller Reset | `[255, 0, 0]` | Soft reset the controller | In scope |

## Serial Configuration

**Port Settings:**
```python
import serial

port = serial.Serial(
    port='COM3',           # Update with actual port
    baudrate=1000000,      # 1 Mbaud
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=1.0
)
```

## Implementation Notes

1. **Responses:** Most commands receive no acknowledgment. The two exceptions are Echo (ID 0x77) and Firmware Version (ID 0x78), which each return 3 bytes.
2. **State Tracking:** Application must track current state
3. **Timing:** Commands execute immediately, no handshaking
4. **Buffer Flushing:** Recommended to flush buffers before sending critical commands

## Example Usage

See `pyscanbox/hardware/controller.py` for complete implementation.

## Original MATLAB References

**File Locations:** `Scanbox/sb/*.m`
- `sb_open.m` - Initialize controller
- `sb_pockels.m` - Pockels cell control
- `sb_shutter.m` - Shutter control
- `sb_mirror.m` - Mirror toggle
- `sb_scan.m`, `sb_abort.m` - Scan control
