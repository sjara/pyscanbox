# Optotune/ETL Control Specification

**Status:** � In Progress (current control implemented; calibration pending)  
**Implementation Target:** Phase 2  
**Last Updated:** March 3, 2026

---

## Key Implementation Finding

> **The ETL is controlled through the existing Scanbox PSoC5 controller,
> not via a separate serial port.**
>
> Analysis of `Scanbox/sb/sb_current.m` confirms that the ETL current
> command (ID 48) is sent over the same 1 Mbaud serial link as all other
> controller commands.  There is no separate USB-serial connection to an
> Optotune lens driver in this hardware configuration.
>
> `set_etl_current()` is therefore a method of `ScanboxController` in
> `pyscanbox/hardware/controller.py`, not a separate `OptotuneController`
> class.  The separate-serial-device design described in the original
> planning notes below does not apply to this rig.

---

## Overview

The Optotune Electrically Tunable Lens (ETL) provides rapid axial focus control without mechanical objective movement. This enables fast z-stack acquisition and dynamic focus adjustment during imaging sessions.

---

## Hardware Details

### Optotune Lens Controller
- **Communication:** Serial (typically USB-serial adapter)
- **Protocol:** Text-based command protocol
- **Current Range:** 0-1760 (arbitrary units, typically milliamps)
- **Response Time:** ~10ms for focus adjustment
- **Typical Port:** COM7 or similar

### Integration with Microscope
- Lens positioned in optical path near objective
- Current setting maps to focal depth via calibration
- No moving parts - purely electromagnetic lens deformation

---

## Functional Requirements

### 1. Hardware Interface Module

**Module:** `pyscanbox/hardware/optotune.py`

**Class:** `OptotuneController`

**Methods:**
```python
class OptotuneController:
    def __init__(self, config: dict):
        """Initialize controller with serial port and settings."""
        
    def open(self) -> None:
        """Open serial connection to Optotune driver."""
        
    def close(self) -> None:
        """Close serial connection."""
        
    def set_current(self, current: int) -> None:
        """Set lens current (0-1760).
        
        Args:
            current: Lens current in arbitrary units (typically mA)
        """
        
    def get_current(self) -> int:
        """Read current lens setting.
        
        Returns:
            Current value (0-1760)
        """
        
    def set_depth(self, depth_um: float) -> None:
        """Set focal depth using calibration.
        
        Args:
            depth_um: Desired depth in microns relative to calibration zero
            
        Raises:
            ValueError: If depth is outside calibrated range
        """
        
    def get_depth(self) -> float:
        """Get current focal depth in microns.
        
        Returns:
            Depth in microns using current calibration
        """
        
    def load_calibration(self, filepath: str) -> None:
        """Load calibration data from file.
        
        Args:
            filepath: Path to calibration file (otcal.mat format)
        """
        
    def save_calibration(self, filepath: str) -> None:
        """Save calibration data to file."""
```

### 2. Calibration System

**Purpose:** Map lens current to actual focal depth in microns

**Calibration File Format:**
- MATLAB .mat file (`otcal.mat`)
- Contains polynomial coefficients for current → depth mapping
- Generated via calibration procedure using motor controller

**Calibration Coefficients (`otcoeff`):**
- Polynomial fit: `depth_um = polyval(otcoeff, current)`
- Typically 2nd or 3rd order polynomial
- Example: `[0.0001, -0.2, 100]` for quadratic fit

**Lookup Table (`optolut`):**
- Pre-computed `uint16` array mapping current to depth
- Length: 1761 entries (0-1760 inclusive)
- Enables fast lookup without repeated polynomial evaluation

### 3. Calibration Procedure

**Workflow:**
1. **Setup:** Mount calibration sample (e.g., pollen grains, beads on coverslip)
2. **Reference:** Focus manually and set motor Z-position as zero reference
3. **Current Sweep:** For each current value in sequence:
   - Set Optotune current
   - Wait for lens to stabilize (~50ms)
   - Move motor Z until sample is in focus
   - Record (current, motor_z_position) pair
4. **Polynomial Fit:** Fit polynomial to (current, depth) data points
5. **Validation:** Test calibration by setting random depths and verifying focus

**MATLAB Reference:** `sbx/sbxoptotunecalibration.m`

**Configuration for Calibration:**
```python
config['optotune']['calibration'] = {
    'current_sequence': list(range(0, 1760, 170)),  # 0, 170, 340, ..., 1700
    'z_range_um': -320,           # Total z-range to cover
    'z_step_um': -10,             # Step size for motor movement
    'frames_per_step': 10,        # Frames to acquire at each position
    'polynomial_order': 2         # 2 = quadratic, 3 = cubic
}
```

### 4. Z-Stack Acquisition

**Integration with Scanner:**
- Before each frame (or set of frames), set ETL current
- Acquire frames at each depth
- Store depth information in metadata

**Z-Stack Configuration:**
```python
config['acquisition']['z_stack'] = {
    'enabled': True,
    'start_depth_um': -50,
    'end_depth_um': 50,
    'step_size_um': 5,
    'frames_per_depth': 10,
    'use_optotune': True  # vs motor-based z-stack
}
```

**Advantages over Motor Z-Stack:**
- Much faster (~10ms vs ~100ms per step)
- No mechanical vibration
- Can interleave depths during acquisition

---

## Configuration Schema

```yaml
optotune:
  enabled: false
  port: 'COM7'
  baud_rate: 115200
  timeout: 1.0
  
  # Hardware limits
  min_current: 0
  max_current: 1760
  default_current: 860
  
  # Calibration
  calibration_file: 'otcal.mat'
  
  # Calibration generation settings
  calibration:
    current_sequence: [0, 170, 340, 510, 680, 850, 1020, 1190, 1360, 1530, 1700]
    z_range_um: -320
    z_step_um: -10
    frames_per_step: 10
    polynomial_order: 2
```

---

## GUI Integration

### Optotune Control Panel (Already in GUI Specification)

**Widgets:**
- **Current Slider:** Set lens current (0-1760)
- **Current SpinBox:** Numeric input for precise control
- **Depth Display:** Show current depth in microns (read-only, requires calibration)
- **Calibrate Button:** Launch calibration wizard
- **Enable Checkbox:** Enable/disable ETL control

**Behavior:**
- Slider and spinbox bidirectionally linked
- Real-time update of depth display when calibration loaded
- Disabled state when no calibration available
- Visual indicator of calibration status

### Calibration Wizard

**Steps:**
1. **Preparation:** Instructions for mounting calibration sample
2. **Reference Setting:** Set motor Z-position as zero
3. **Acquisition:** Automated current sweep with motor focus tracking
4. **Fitting:** Display calibration curve and residuals
5. **Validation:** Test calibration at random depths
6. **Save:** Save calibration file

---

## Implementation Notes

### Serial Protocol (Actual Implementation)

ETL current is sent via the **Scanbox PSoC5 controller** (CMD_ETL = 48),
the same 1 Mbaud serial link used by all other controller commands.

**Encoding** (from `sb/sb_current.m`)::

    encoded = 0x7000 | (current & 0x0FFF)   # 0b0111 prefix in upper nibble
    b1 = (encoded >> 8) & 0xFF
    b2 =  encoded       & 0xFF
    send [48, b1, b2]

Current range: 0–1760 (software limit); hardware limit is 0–4095 (12-bit).
Resolution ~61.5 µA per count.

**Python:**
```python
controller.set_etl_current(880)   # mid-range
```

The device-specific text-command protocols described below (4-channel
driver, single-channel driver) are **not used** on this rig.

---

### Serial Protocol (Device-Specific — Not Used on This Rig)

The exact protocol depends on the Optotune model. Common patterns:

**4-Channel Lens Driver (4Ch):**
```python
# Set current (channel A)
command = f"CrA{current}\r\n"
serial_port.write(command.encode())

# Read current
command = "CrA?\r\n"
response = serial_port.readline()
```

**Single-Channel Driver:**
```python
# Set current
command = f"Cr{current}\r\n"

# Enable/disable
command = "M1\r\n"  # Enable
command = "M0\r\n"  # Disable
```

Refer to Optotune documentation for specific model.

### Emulation Mode

**Mock Optotune for Linux Development:**
```python
class MockOptotuneController:
    """Emulated Optotune controller for testing."""
    
    def __init__(self):
        self.current = 860  # Default
        self.calibration = None
        
    def set_current(self, current: int):
        self.current = max(0, min(1760, current))
        
    def get_current(self) -> int:
        return self.current
```

### Performance Considerations

- **Settling Time:** Allow ~10-50ms after setting current for lens to stabilize
- **Hysteresis:** ETL may show slight hysteresis; calibration should account for this
- **Temperature Drift:** Long sessions may require recalibration
- **Frame Synchronization:** For z-stacks, ensure Alazar triggering synchronized with ETL changes

---

## Testing Strategy

### Unit Tests
- Serial protocol command formatting
- Calibration coefficient loading/saving
- Current-to-depth conversion accuracy
- Bounds checking (0-1760 range)

### Integration Tests (Emulation)
- GUI control → controller communication
- Z-stack acquisition with mock ETL
- Calibration data persistence

### HIL Tests (Phase 3)
- Actual current setting and verification
- Calibration procedure with motor controller
- Focus accuracy and repeatability
- Long-term stability test

---

## Dependencies

- **pyserial:** Serial communication
- **scipy:** For polynomial fitting during calibration
- **numpy:** Array operations
- **Motor Controller:** Required for calibration procedure

---

## References

- **MATLAB Config:** `Scanbox/core/scanbox_config.m` (lines 40-46)
- **MATLAB Calibration:** `Scanbox/sbx/sbxoptotunecalibration.m`
- **Optotune Documentation:** Device-specific protocol manual
- **GUI Specification:** `pyscanbox/devel/GUI_SPECIFICATION.md` (Optotune panel)

---

## Milestones

- **Phase 2:** Milestone 2.5 - Implementation
- **Phase 3:** Milestone 3.6 - Hardware validation
- **Phase 4:** Integration with z-stack acquisition workflows
