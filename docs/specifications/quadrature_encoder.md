# Quadrature Encoder Specification

**Status:** 🔴 Planning Phase (Optional Feature)  
**Implementation Target:** Phase 2  
**Last Updated:** March 18, 2026

---

## Overview

The quadrature encoder system monitors the rotation angle of a motorized platform via an Arduino-based reader. This enables experiments requiring precise rotation synchronization, such as imaging during continuous rotation or recording head direction in behavioral paradigms.

---

## Hardware Details

### Components

**Quadrature Encoder:**
- Mounted on rotating platform axis
- Outputs two square-wave signals (A and B) 90° out of phase
- Pulses per revolution: Typically 360-1440 (device-specific)

**Arduino Reader:**
- Decodes quadrature signals to count pulses
- Determines rotation direction from phase relationship
- Sends position updates to PC via serial

**Platform:**
- Motorized rotating platform (e.g., for head-direction experiments)
- Radius: ~10 cm (typical)
- Used for continuous rotation during imaging

### Serial Communication

**Port:** Configurable (`sbconfig.quad_com`, e.g. `COM8`)  
**Baud Rate:**
- Arduino DUE firmware: **115,200 baud**
- Arduino Mega firmware: **1,000,000 baud**  
  *(The spec previously listed 57600 — that is incorrect.)*

**Protocol:** Strictly **binary command/response** — no text framing.

| Command byte | Action | Response |
|---|---|---|
| `0x00` | Request current count | 4 bytes, signed `int32`, little-endian |
| `0x01` | Zero the counter | *(none)* |
| `0x02` | Lamp OFF (DUE only) | *(none)* |
| `0x03` | Lamp ON (DUE only) | *(none)* |

**Non-blocking poll pattern** (matches original `scanbox.m` acquisition loop):
1. Send command byte `0x00` (`quad_poll`) **before** waiting on the Alazar buffer.
2. Wait for the Alazar buffer to complete.
3. Read the 4-byte int32 response (`quad_get`) **after** the buffer completes.

This decouples the serial latency from the imaging latency: by the time the buffer is
ready, the response has almost certainly arrived in the UART receive buffer.

---

## PSoC Controller Independence

**The quadrature encoder system is completely independent of the PSoC5 Scanbox
controller.** It communicates directly with its own dedicated Arduino (DUE or Mega)
over a separate serial port. The PSoC is not involved in encoder communication,
timing, or data capture in any way. This means the encoder can in principle be
used before the main Scanbox hardware is opened.

---

## Functional Requirements

### 1. Hardware Interface Module

**Module:** `pyscanbox/plugins/quadrature.py`

**Class:** `QuadratureEncoder`

```python
class QuadratureEncoder:
    """Interface for Arduino-based quadrature encoder reader.
    
    Communicates directly with the Arduino over a dedicated serial port,
    completely independent of the PSoC5 Scanbox controller.
    """
    
    def __init__(self, config: dict):
        """Initialize encoder with configuration.
        
        Args:
            config: Configuration dictionary with encoder settings
        """
        self.port = config.get('port', 'COM8')
        self.baud_rate = config.get('baud_rate', 115200)  # 1000000 for Mega
        self.calibration = config.get('calibration', 0.043633)  # cm/count
        self.serial = None
        self.count = 0
        
    def open(self) -> None:
        """Open serial connection to Arduino."""
        
    def close(self) -> None:
        """Close serial connection."""
        
    def poll(self) -> None:
        """Send the count-request byte (0x00) without waiting for the response.
        
        Call this BEFORE waiting on the next Alazar buffer to decouple
        serial latency from imaging latency.
        """
        
    def read_count(self) -> int:
        """Read the 4-byte int32 response from a preceding poll().
        
        Call this AFTER the Alazar buffer completes.
        
        Returns:
            Accumulated count (positive: clockwise, negative: counter-clockwise,
            depending on encoder wiring).
        """
        
    def reset_count(self) -> None:
        """Zero the encoder counter (sends command byte 0x01)."""
        
    def set_calibration(self, cm_per_count: float) -> None:
        """Set calibration factor.
        
        Args:
            cm_per_count: Arc length per encoder count, in centimetres.
                Computed as (2 * pi * radius_cm) / pulses_per_revolution.
        """
```

### 2. Arduino Protocol

**Protocol is strictly binary — there is no text-based option.**

**Command/response summary:**

```
PC → Arduino:  1 byte command
  0x00  →  Arduino replies: int32 (4 bytes, little-endian), current count
  0x01  →  Arduino zeroes counter, no reply
  0x02  →  (DUE only) Turn lamp OFF
  0x03  →  (DUE only) Turn lamp ON

Arduino firmware variants:
  quad_encoder/quad_encoder.ino  — Arduino DUE, 115200 baud, supports lamp
  quad_encoder_mega/quad_encoder_mega.ino — Arduino Mega, 1,000,000 baud
```

Both variants use the `Encoder` library on pins 8/9 (DUE) or 2/3 (Mega).
The DUE version also listens on `SerialUSB` (the native USB port) in addition
to the hardware `Serial` (the programming port), both at 115200 baud.

### 3. Calibration

**Calibration Factor:** arc-length in centimetres per encoder count (cm/count).
*(The spec previously described this as radians/count — that is incorrect.)*

**Calibration Factor Calculation:**
```python
# calibration = arc length per count = circumference / pulses_per_revolution
#             = (2 * pi * radius_cm) / pulses_per_revolution

# Scanbox default (scanbox_config.m): r=10 cm, 1440 ppr
calibration = 20 * np.pi / 1440   # = 0.04363... cm/count

# Jaralab config (scanbox_config.jaralab.m): r=7 cm, 2048 ppr
calibration = 14 * np.pi / 2048   # = 0.02150... cm/count
```

To convert counts to arc angle: `angle_rad = count * calibration / radius_cm`

**Calibration Verification:**
- Rotate platform by a known arc length (e.g., one full revolution).
- Measure total count change.
- Verify: `arc_length_cm = count_delta * calibration`

---

## Configuration Schema

```yaml
quadrature:
  enabled: false
  port: 'COM8'
  baud_rate: 115200           # 115200 for DUE, 1000000 for Mega
  timeout: 1.0
  
  # Calibration: arc length per encoder count (cm/count)
  # = (2 * pi * radius_cm) / pulses_per_revolution
  calibration: 0.04363323     # default: r=10 cm, 1440 ppr (scanbox_config.m)
  # calibration: 0.02150      # jaralab: r=7 cm, 2048 ppr
  
  # Platform specifications (for reference / documentation)
  platform_radius_cm: 10.0
  pulses_per_revolution: 1440
```

---

## Integration with Acquisition

### Sampling Strategy

**One sample per Alazar buffer (= one per frame).** This exactly mirrors the
original Scanbox implementation (`scanbox.m` lines ~2621 and ~2939).

The non-blocking poll pattern is used:
```
frame N-1 completes
↓
quad_poll()          ← send command byte 0x00 (fire-and-forget)
↓
wait for Alazar buffer N to fill...
↓
quad_data[N] = quad_get()  ← read the 4-byte int32 response
```

This gives a temporal resolution of one imaging frame (~33 ms at 30 fps).
Sub-frame resolution requires a TTL input connected to the encoder index pulse
(see the Plugin System section).

### Data Format

The original Scanbox saves **raw encoder counts only**, as a MATLAB int32 array
with one element per frame, in a separate file:

```
<animal>_<unit>_<experiment>_quadrature.mat
  → quad_data: int32 array [1 × n_frames]
```

There are no per-sample timestamps embedded in this file. The frame index *is*
the timestamp: `time_s[i] = i / frame_rate`.

For pyscanbox, the equivalent would be a NumPy int32 array saved alongside the
`.sbx` file. Calibrated arc-length is computed in post-processing:

```python
arc_cm = quad_data * calibration     # element-wise: int32 → float64
angle_rad = arc_cm / radius_cm
```

### Metadata Fields

```python
info = {
    'quadrature_enabled': True,
    'quadrature_calibration': 0.04363,  # cm/count
    'platform_radius_cm': 10.0,
    'pulses_per_revolution': 1440,
    # quad_data array lives in the companion _quadrature.npy file
}
```

---

## GUI Integration

### Position Display Panel

**Display Elements:**
- **Numeric Display:** Current angle in degrees (or radians)
- **Dial Widget:** Visual representation of rotation angle
- **Reset Button:** Zero the encoder count
- **Calibration Input:** Set calibration factor

**Real-time Updates:**
- Update display at ~10 Hz during acquisition
- Show rotation direction indicator (CW/CCW)

### Configuration Settings

- Enable/disable checkbox
- Serial port selection dropdown
- Calibration factor input field
- Test connection button

---

## Emulation Mode

**Mock Encoder for Linux Development:**

```python
class MockQuadratureEncoder:
    """Emulated quadrature encoder for testing."""
    
    def __init__(self, config: dict):
        self.count = 0
        self.calibration = config.get('calibration', 0.04363)  # cm/count
        self._counts_per_frame = 4  # simulated rotation speed
        
    def poll(self) -> None:
        pass  # nothing to do in mock
        
    def read_count(self) -> int:
        """Simulate continuous rotation: advance count by a fixed step."""
        self.count += self._counts_per_frame
        return self.count
        
    def reset_count(self):
        self.count = 0
```

---

## References

- **MATLAB Config:** `Scanbox/core/scanbox_config.m` (lines 12-13)  
  `sbconfig.quad_com = 'COM6'`, `sbconfig.quad_cal = 20*pi/1440`
- **MATLAB jaralab Config:** `Scanbox/core/scanbox_config.jaralab.m`  
  `sbconfig.quad_com = 'COM8'`, `sbconfig.quad_cal = 14*pi/2048`
- **Arduino Firmware (DUE):** `Scanbox/quad/quad_encoder/quad_encoder.ino`
- **Arduino Firmware (Mega):** `Scanbox/quad/quad_encoder_mega/quad_encoder_mega.ino`
- **MATLAB functions:** `Scanbox/quad/quad_open.m`, `quad_read.m`, `quad_poll.m`, `quad_get.m`, `quad_zero.m`, `quad_close.m`
- **Acquisition integration:** `Scanbox/core/scanbox.m` lines ~2398–2403 (setup), ~2619–2622 (poll), ~2936–2939 (read), ~3144–3150 (save)

---

## Implementation Priority

**Status:** Optional Feature — implement as a plugin under the Plugin System (see
`devel/specifications/plugin_system.md`).

**Dependencies:**
- Arduino with encoder reader firmware
- Quadrature encoder mounted on platform
- USB-serial connection to PC

---

## Milestones

- **Phase 2:** Milestone 2.6 - Implementation (optional)
- **Phase 3:** Milestone 3.7 - Hardware validation (if hardware available)
- **Phase 4:** Integration with acquisition metadata system

---

## Decision Criteria

**Implement if:**
- ✅ Lab uses rotating platform experiments
- ✅ Hardware is installed and functional
- ✅ Core features (Phases 1-2) complete

**Skip if:**
- ❌ No rotating platform in current rig
- ❌ Time/resources limited
- ❌ Can use alternative synchronization method (TTL triggers)
