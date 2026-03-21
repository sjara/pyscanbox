# AlazarTech ATS9440 Protocol

> **Note**: This document contains low-level developer specifications (API constants, bitmasks, and strict initialization sequences). For high-level theory of operation, PCle/cable setup, and data formatting, see the user-facing [AlazarTech ATS9440 Digitizer Reference](../alazar_digitizer.md).

Low-level protocol specification for the AlazarTech ATS9440 digitizer used for PMT data acquisition.

## Overview

The AlazarTech ATS9440 is a high-speed digitizer providing:
- 125 MS/s sampling rate per channel
- 14-bit ADC resolution
- 2-channel simultaneous acquisition
- ~500 MB/s data throughput
- External clock synchronization with laser sync-out (~80 MHz)

## API Constants

### Clock Source Constants

```python
INTERNAL_CLOCK        = 0x1
EXTERNAL_CLOCK        = 0x2  # Also FAST_EXTERNAL_CLOCK
MEDIUM_EXTERNAL_CLOCK = 0x3
SLOW_EXTERNAL_CLOCK   = 0x4
```

**Scanbox uses:** `FAST_EXTERNAL_CLOCK (0x2)`

### Sample Rate Constants

Used **only with internal clock**. When using external clock, use `SAMPLE_RATE_USER_DEF`.

```python
SAMPLE_RATE_125MSPS   = 0x25  # Most common for Scanbox
SAMPLE_RATE_USER_DEF  = 0x40  # Used with external clock
```

**Scanbox uses:** `SAMPLE_RATE_USER_DEF (0x40)` with external clock

For complete list of sample rates, see the `atsbindings.enumerations` module.

### Input Range Constants

```python
INPUT_RANGE_PM_200_MV = 0x6  # Scanbox default for variable gain amps
INPUT_RANGE_PM_1_V    = 0xA  # Scanbox default for fixed gain amps
```

### Coupling and Impedance

```python
AC_COUPLING = 0x1
DC_COUPLING = 0x2  # Scanbox uses DC coupling

IMPEDANCE_1M_OHM = 0x1
IMPEDANCE_50_OHM = 0x2  # Scanbox uses 50 ohm
```

### Trigger Constants

```python
# Trigger engines
TRIG_ENGINE_J = 0x0
TRIG_ENGINE_K = 0x1

# Trigger operations
TRIG_ENGINE_OP_J        = 0x0  # Scanbox uses this
TRIG_ENGINE_OP_J_OR_K   = 0x2
TRIG_ENGINE_OP_J_AND_K  = 0x3

# Trigger sources
TRIG_CHAN_A   = 0x0
TRIG_CHAN_B   = 0x1
TRIG_EXTERNAL = 0x2  # Scanbox uses external trigger
TRIG_DISABLE  = 0x3

# Trigger slopes
TRIGGER_SLOPE_POSITIVE = 0x1
TRIGGER_SLOPE_NEGATIVE = 0x2

# External trigger ranges
ETR_TTL = 0x2  # Scanbox uses TTL
```

### Channel Constants

```python
CHANNEL_A = 0x1
CHANNEL_B = 0x2
CHANNEL_C = 0x4
CHANNEL_D = 0x8
```

**Important:** Use bitmask, not indices. For 2 channels: `CHANNEL_A | CHANNEL_B = 0x3`

### Clock Edge

```python
CLOCK_EDGE_RISING  = 0x0  # Scanbox uses rising edge
CLOCK_EDGE_FALLING = 0x1
```

## Configuration Sequence

Complete configuration matching original MATLAB implementation. **Must be called in this order:**

### 1. Clock Configuration

```python
board.setCaptureClock(
    FAST_EXTERNAL_CLOCK,    # 0x2
    SAMPLE_RATE_USER_DEF,   # 0x40 (ignored with external clock)
    CLOCK_EDGE_RISING,      # 0x0
    0                       # decimation
)
```

### 2. External Clock Level

**Required for ATS9440:**
```python
board.setExternalClockLevel(65.0)  # 65% level
```

### 3. Input Channels

Configure both channels A and B:

```python
# Channel A
board.inputControl(
    CHANNEL_A,              # 0x1
    DC_COUPLING,            # 0x2
    INPUT_RANGE_PM_200_MV,  # 0x6 (or 0xA for fixed gain amps)
    IMPEDANCE_50_OHM        # 0x2
)

# Channel B
board.inputControl(
    CHANNEL_B,              # 0x2
    DC_COUPLING,            # 0x2
    INPUT_RANGE_PM_200_MV,  # 0x6
    IMPEDANCE_50_OHM        # 0x2
)
```

### 4. Trigger Operation

```python
board.setTriggerOperation(
    TRIG_ENGINE_OP_J,       # 0x0
    TRIG_ENGINE_J,          # 0x0
    TRIG_EXTERNAL,          # 0x2
    TRIGGER_SLOPE_POSITIVE, # 0x1
    128,                    # Mid-range level
    TRIG_ENGINE_K,          # 0x1
    TRIG_DISABLE,           # 0x3
    TRIGGER_SLOPE_POSITIVE, # 0x1 (ignored)
    128                     # Level (ignored)
)
```

### 5. External Trigger

```python
board.setExternalTrigger(
    DC_COUPLING,  # 0x2
    ETR_TTL       # 0x2
)
```

### 6. Trigger Delay

```python
board.setTriggerDelay(0)  # No delay
```

### 7. Trigger Timeout

```python
board.setTriggerTimeOut(0)  # Wait forever
```

### 8. LSB Configuration

Configure LSB outputs for frame/line synchronization:

```python
board.configureLSB(
    2,  # LSB[0] = AUX_IN[0]
    3   # LSB[1] = AUX_IN[1]
)
```

**Important Notes:**
- All configuration calls must complete successfully before starting acquisition
- Channel identifiers are CHANNEL_A=0x1, CHANNEL_B=0x2 (not 0, 1)
- Missing any of these configuration steps will cause acquisition to fail

## Data Acquisition (NPT Mode)

After configuration, continuous data acquisition uses NPT (No Pre-Trigger) mode for streaming.

### Buffer Allocation Requirements

**Critical alignment requirements:**
- `samplesPerRecord` must be aligned to 64-sample boundaries
- Minimum buffer size: 256 samples
- Buffer size calculation: `bytes_per_buffer = samplesPerRecord * channels * 2`
  - Example: 2048 samples/record × 2 channels × 2 bytes = 8192 bytes per buffer

**Alignment helper:**
```python
def _align_sample_count(samples: int, alignment: int = 64) -> int:
    """Align to 64-sample boundary and enforce minimum."""
    min_samples = 256
    if samples < min_samples:
        samples = min_samples
    return ((samples + alignment - 1) // alignment) * alignment
```

### AlazarBeforeAsyncRead

Prepares the board for asynchronous DMA acquisition.

**Function signature:**
```python
AlazarBeforeAsyncRead(boardHandle, channelSelect, transferOffset, 
                     samplesPerRecord, recordsPerBuffer, 
                     recordsPerAcquisition, flags)
```

**Parameter details:**

| Parameter | Type | Description | Scanbox Value |
|-----------|------|-------------|---------------|
| `channelSelect` | U32 | Channel bitmask (CHANNEL_A \| CHANNEL_B) | 0x3 |
| `transferOffset` | c_long | Pretrigger samples (0 for NPT mode) | 0 |
| `samplesPerRecord` | U32 | Samples per record (must be aligned to 64) | 2048 |
| `recordsPerBuffer` | U32 | Records per DMA buffer (1 for NPT) | 1 |
| `recordsPerAcquisition` | U32 | Total records (0x7FFFFFFF = infinite) | 0x7FFFFFFF |
| `flags` | U32 | ADMA_NPT \| ADMA_CONTINUOUS_MODE | 0x300 |

**Acquisition flags:**
```python
ADMA_NPT             = 0x200  # No pre-trigger mode
ADMA_CONTINUOUS_MODE = 0x100  # Continuous streaming
```

**Example:**
```python
board.beforeAsyncRead(
    0x3,              # CHANNEL_A | CHANNEL_B
    0,                # No pretrigger samples
    2048,             # 2048 samples/record (aligned to 64)
    1,                # 1 record per buffer (NPT mode)
    0x7FFFFFFF,       # Infinite acquisition
    0x300             # ADMA_NPT | ADMA_CONTINUOUS_MODE
)
```

### DMA Buffer Management

**Buffer posting and retrieval:**
```python
# Post buffers before starting acquisition
for buffer_ptr in buffer_pointers:
    board.postAsyncBuffer(buffer_ptr, bytes_per_buffer)

# Start acquisition
board.startCapture()

# Wait for and retrieve filled buffers
board.waitAsyncBufferComplete(buffer_ptr, timeout_ms)

# Re-post buffer for continuous acquisition
board.postAsyncBuffer(buffer_ptr, bytes_per_buffer)
```

**Buffer circular management:**
- Allocate multiple buffers (typically 16) for ring buffer
- Post all buffers before starting capture
- Wait for buffer to complete, process data, then re-post
- Rotate through buffers in circular fashion

**Performance considerations:**
- More buffers = more latency tolerance but higher memory usage
- Typical configuration: 16 buffers × 8KB = 128KB total
- At 125 MS/s with 2 channels, each 2048-sample buffer fills in ~8 μs
- Processing must be faster than buffer fill rate to avoid overflow

## Common Errors and Solutions

### ApiInvalidData Error

**Cause:** Buffer size not aligned or parameters inconsistent

**Solution:** 
- Ensure `samplesPerRecord` is aligned to 64 samples
- Ensure `samplesPerRecord >= 256`
- Verify: `samplesPerRecord % 64 == 0` and `samplesPerRecord >= 256`

### Buffer Overflow

**Cause:** Not reading buffers fast enough

**Solution:**
- Increase buffer count
- Reduce samples per buffer
- Monitor: Check `AlazarBusy()` status during acquisition

### Invalid Channel Selection

**Cause:** Using channel index (0, 1) instead of bitmask (0x1, 0x2)

**Solution:** Use `CHANNEL_A = 0x1`, `CHANNEL_B = 0x2`, combined with bitwise OR

### Configuration Fails

**Cause:** Missing required configuration calls or wrong order

**Solution:**
- Follow the 8-step configuration sequence exactly
- Ensure `setExternalClockLevel()` is called (required for ATS9440)
- Verify all calls return success before proceeding to next step

## Example Usage

See `pyscanbox/hardware/alazar.py` for complete implementation and `examples/check_alazar.py` for usage examples.

## Original MATLAB References

**File Locations:**
- `Scanbox/core/scanbox.m` (lines 743-893) - Board initialization and configuration
- `Scanbox/core/configureLsb9440.m` - LSB register manipulation
- `Scanbox/alazartech/AlazarDefs.m` - All API constant definitions
- `Scanbox/alazartech/*.m` - Individual API function wrappers

## Additional Resources

- `../alazar_digitizer.md` - User-facing documentation
- `atsbindings.enumerations` - Complete API constant definitions
