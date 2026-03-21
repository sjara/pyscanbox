# Bidirectional Scanning Specification

**Status:** 🔴 Planning Phase  
**Implementation Target:** Phase 1 (logic), Phase 3 (calibration), Phase 4 (optimization)  
**Last Updated:** February 23, 2026

---

## Overview

Bidirectional scanning enables acquisition during both forward and backward sweeps of the resonant scanner, effectively doubling the frame rate. However, due to scanner inertia and timing differences between scan directions, pixel positions require correction via calibrated shifts.

---

## Motivation

### Frame Rate Improvement
- **Unidirectional:** Lines scanned only during forward sweep (e.g., 15 Hz for 512 lines)
- **Bidirectional:** Lines scanned during both forward and backward sweeps (e.g., 30 Hz)
- **Benefit:** 2× frame rate for same resonant frequency

### Trade-offs
- **Pros:** Higher temporal resolution, faster data collection
- **Cons:** Requires calibration, slightly more complex processing, potential image artifacts if miscalibrated

---

## Technical Details

### Scan Pattern

**Unidirectional:**
```
→ Line 0 (forward)
  ← (flyback, no acquisition)
→ Line 1 (forward)
  ← (flyback, no acquisition)
→ Line 2 (forward)
  ...
```

**Bidirectional:**
```
→ Line 0 (forward)
← Line 1 (backward)
→ Line 2 (forward)
← Line 3 (backward)
...
```

### Pixel Shift Phenomenon

Due to mechanical inertia of the resonant scanner and timing delays:
- Forward scan lines are acquired with timing offset T_forward
- Backward scan lines are acquired with timing offset T_backward
- Result: Backward lines appear horizontally shifted by N pixels

**Shift varies with:**
- Magnification setting (different for each zoom level)
- Scanner resonant frequency
- Objective being used
- Physical scanner characteristics

### Shift Calibration Values

From MATLAB `sbconfig.bishift`:
```python
bishift = [
    -10,  # Magnification 1 (lowest zoom)
    -9,
    -7,
    -3,
    -3,
    0,    # Magnification 6 (mid-range)
    3,
    7,
    14,
    21,
    30,
    40,
    58    # Magnification 13 (highest zoom)
]
```

**Interpretation:**
- Negative values: Backward lines shifted left
- Positive values: Backward lines shifted right
- Zero: No shift (rare, depends on electronics)
- Magnitude increases at higher magnifications

---

## Functional Requirements

### 1. Extended Reshape Function

**Module:** `pyscanbox/acquisition/reshape.py`

**Function Signature:**
```python
def reshape_pmt_data(
    raw_data: np.ndarray,
    width: int,
    height: int,
    bidirectional: bool = False,
    pixel_shift: int = 0
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Reshape and extract PMT data with optional bidirectional correction.
    
    Args:
        raw_data: Raw interleaved 16-bit data from Alazar
        width: Image width (pixels per line)
        height: Image height (number of lines)
        bidirectional: If True, apply bidirectional correction
        pixel_shift: Horizontal shift for backward lines (can be negative)
        
    Returns:
        (pmt0, pmt1, sync): Tuple of reshaped arrays
        - pmt0: First PMT channel (height, width) uint16
        - pmt1: Second PMT channel (height, width) uint16
        - sync: Sync bit array (height, width) uint8
    """
```

**Implementation Logic:**
```python
# After initial reshape to (height, width)
if bidirectional:
    # Separate even (forward) and odd (backward) lines
    forward_lines = pmt0[0::2, :]   # Lines 0, 2, 4, ...
    backward_lines = pmt0[1::2, :]  # Lines 1, 3, 5, ...
    
    # Apply shift to backward lines
    if pixel_shift != 0:
        backward_lines = np.roll(backward_lines, pixel_shift, axis=1)
        
        # Handle edge cases (wrap-around pixels)
        if pixel_shift > 0:
            backward_lines[:, :pixel_shift] = 0  # Or extrapolate
        else:
            backward_lines[:, pixel_shift:] = 0
    
    # Interleave corrected lines back
    pmt0[0::2, :] = forward_lines
    pmt0[1::2, :] = backward_lines
    
    # Repeat for pmt1 and sync
```

### 2. Calibration Procedure

**Purpose:** Determine optimal `pixel_shift` value for each magnification and objective.

**Requirements:**
- High-contrast calibration sample (fine grid, sharp edges)
- Original MATLAB files available as reference for comparison
- Visual inspection capability for alignment quality

**Workflow:**

1. **Setup:**
   - Mount calibration target (e.g., fine mesh grid, pollen)
   - Configure for specific magnification level
   - Acquire in unidirectional mode (reference)

2. **Bidirectional Acquisition:**
   - Switch to bidirectional mode
   - Acquire same field of view
   - Try range of shift values (e.g., -20 to +20)

3. **Alignment Metric:**
   - For each shift value, compute image quality metric:
     - Cross-correlation between even and odd lines
     - Edge alignment score
     - Structural similarity (SSIM)
   - Optimal shift = maximum alignment score

4. **Validation:**
   - Visual inspection of corrected image
   - Compare against unidirectional reference
   - Verify consistent structures across line boundaries

5. **Documentation:**
   - Record shift value for (objective, magnification) pair
   - Note acquisition parameters (frame rate, etc.)
   - Save calibration images for reference

**Automated Calibration Function:**
```python
def calibrate_bidirectional_shift(
    alazar: AlazarDigitizer,
    width: int,
    height: int,
    shift_range: Tuple[int, int] = (-30, 30)
) -> int:
    """Automatically determine optimal pixel shift.
    
    Args:
        alazar: Configured Alazar digitizer
        width, height: Image dimensions
        shift_range: (min_shift, max_shift) to test
        
    Returns:
        Optimal pixel shift value
    """
    # Acquire calibration frame
    raw_data = alazar.read_buffer()
    
    best_score = -np.inf
    best_shift = 0
    
    for shift in range(shift_range[0], shift_range[1] + 1):
        pmt0, _, _ = reshape_pmt_data(raw_data, width, height, 
                                      bidirectional=True, 
                                      pixel_shift=shift)
        
        # Compute alignment score
        score = compute_line_alignment_score(pmt0)
        
        if score > best_score:
            best_score = score
            best_shift = shift
    
    return best_shift
```

### 3. Configuration Schema

```yaml
acquisition:
  # Scan mode
  unidirectional: true  # false = bidirectional mode
  
  # Bidirectional calibration per magnification
  bishift: [
    -10, -9, -7, -3, -3, 0, 3, 7, 14, 21, 30, 40, 58
  ]
  
  # Current magnification index (0-12)
  magnification: 6
```

---

## Implementation Phases

### Phase 1: Core Logic (Milestone 1.7)
- Extend `reshape_pmt_data()` with bidirectional support
- Implement pixel shift correction
- Unit tests with synthetic data
- **Deliverable:** Working reshape function with configurable shift

### Phase 3: Calibration (Milestone 3.8)
- Perform calibration on actual hardware
- Measure shift values for all magnifications
- Validate image quality in bidirectional mode
- **Deliverable:** Calibrated shift values for production use

### Phase 4: Optimization (Milestone 4.4)
- Optimize reshape performance for bidirectional data
- Verify frame rate doubling
- Handle edge cases and error conditions
- **Deliverable:** Production-ready bidirectional mode

---

## Performance Considerations

### Reshape Performance
- Bidirectional mode adds minimal overhead (~5% estimated)
- Pixel shifting is simple array indexing operation
- Numba JIT compilation maintains high throughput

### Memory Usage
- No additional memory required (in-place operations)
- Same buffer size as unidirectional mode

### Frame Rate
- **Target:** Maintain 500 MB/s throughput
- **Benefit:** 2× temporal resolution for same data rate

---

## Testing Strategy

### Unit Tests
```python
def test_bidirectional_reshape_no_shift():
    """Test bidirectional mode with zero shift."""
    
def test_bidirectional_reshape_positive_shift():
    """Test backward line shift to the right."""
    
def test_bidirectional_reshape_negative_shift():
    """Test backward line shift to the left."""
    
def test_bidirectional_edge_handling():
    """Test proper handling of edge pixels during shift."""
```

### Integration Tests (Emulation)
- Full acquisition loop in bidirectional mode
- Metadata recording of mode and shift value
- File I/O with bidirectional data

### HIL Tests (Phase 3)
- Calibrate all magnifications for available objectives
- Compare unidirectional vs bidirectional image quality
- Measure actual frame rate improvement
- Long-duration stability test

---

## GUI Integration

### Scanner Control Panel

**Scan Mode Selection:**
- Radio buttons or dropdown: "Unidirectional" / "Bidirectional"
- Display current shift value for selected magnification
- Warning if no calibration available for current settings

**Calibration Interface:**
- "Calibrate Bidirectional" button
- Progress indicator during calibration
- Save/load calibration files
- Display before/after comparison

**Status Display:**
- Show current scan mode
- Display frame rate (should double in bidirectional)
- Indicate if calibration is loaded

---

## Data Format

### Metadata (.mat file)

Additional fields for bidirectional acquisitions:
```python
info = {
    'unidirectional': False,           # Scan mode
    'bishift': -7,                     # Shift used for this acquisition
    'magnification': 2,                # Magnification index
    'calibrated': True,                # Whether shift was from calibration
    # ... other existing fields
}
```

### File Compatibility

- `.sbx` file format unchanged (pixel-corrected data written)
- Suite2p and other analysis tools see corrected images
- Metadata allows post-processing tools to verify correction

---

## Known Issues and Limitations

### Calibration Stability
- May drift over time due to temperature changes
- Recommend periodic recalibration (monthly or per objective change)

### Objective Dependence
- Different objectives may have different shifts even at same magnification
- Store calibration per objective serial number

### Edge Artifacts
- Shifted pixels at line edges may show artifacts
- Consider cropping edge pixels in post-processing

### Temporal Alignment
- Forward and backward lines acquired at slightly different times (~60 μs apart)
- May cause artifacts for very fast dynamics

---

## References

- **MATLAB Config:** `Scanbox/core/scanbox_config.m` (`sbconfig.bishift`)
- **MATLAB Pixel LUT:** `Scanbox/core/pixel_lut_bi.m`, `pixel_lut_bi_2.m`
- **Alazar MEX:** `Scanbox/core/alazarReshapeCData2bi.c` (bidirectional variant)
- **Development Guide:** `pyscanbox/devel/DEVELOPMENT_GUIDE.md`

---

## Milestones

- **Phase 1:** Milestone 1.7 - Core reshape logic implementation
- **Phase 3:** Milestone 3.8 - Hardware calibration and validation
- **Phase 4:** Milestone 4.4 - Performance optimization and production readiness
