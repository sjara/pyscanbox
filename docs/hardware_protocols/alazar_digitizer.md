# AlazarTech ATS9440 Protocol

This document specifies the low-level API constants, bitmasks, initialization sequences, and Python implementation details for the AlazarTech ATS9440 digitizer. It is designed for developers implementing hardware drivers and understanding strict configuration requirements.

For high-level system architecture, hardware installation, theory of operation, and troubleshooting guidance, see [AlazarTech ATS9440 Digitizer Reference](../advanced/alazar_digitizer_reference.md).

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
board.set_capture_clock(
    ATS_ENUM.ClockSources.FAST_EXTERNAL_CLOCK,
    ATS_ENUM.SampleRates.SAMPLE_RATE_USER_DEF,  # (ignored with external clock)
    ATS_ENUM.ClockEdges.CLOCK_EDGE_RISING,
    0  # decimation
)
```

### 2. External Clock Level

**Required for ATS9440:**
```python
board.set_external_clock_level(65.0)  # 65% level
```

### 3. Input Channels

Configure both channels A and B (input range depends on amplifier type):

```python
# Input range depends on amplifier type from config
pmt_amp_type = config.get('pmt', {}).get('amplifier_type', 'variable')
if pmt_amp_type == 'fixed':
    input_range = ATS_ENUM.InputRanges.INPUT_RANGE_PM_1_V
else:
    input_range = ATS_ENUM.InputRanges.INPUT_RANGE_PM_200_MV  # default

# Channel A
board.input_control_ex(
    ATS_ENUM.Channels.CHANNEL_A,
    ATS_ENUM.Couplings.DC_COUPLING,
    input_range,  # 0x6 (±200 mV) or 0xA (±1 V)
    ATS_ENUM.Impedances.IMPEDANCE_50_OHM
)

# Channel B
board.input_control_ex(
    ATS_ENUM.Channels.CHANNEL_B,
    ATS_ENUM.Couplings.DC_COUPLING,
    input_range,  # same as Channel A
    ATS_ENUM.Impedances.IMPEDANCE_50_OHM
)
```

### 4. Trigger Operation

**Configuration from pyscanbox config:**
- `config['alazar']['trigger_level']` (default 160, range 0-255)
- `config['alazar']['trigger_slope']` (default 0; offset to TRIGGER_SLOPE_POSITIVE)

```python
trig_level = config.get('alazar', {}).get('trigger_level', 160)
trig_slope = config.get('alazar', {}).get('trigger_slope', 0)

board.set_trigger_operation(
    ATS_ENUM.TriggerOperations.TRIG_ENGINE_OP_J,
    ATS_ENUM.TriggerEngines.TRIG_ENGINE_J,
    ATS_ENUM.TriggerSources.TRIG_EXTERNAL,
    ATS_ENUM.TriggerSlopes(1 + trig_slope),  # 1=positive, 2=negative
    trig_level,        # 0-255
    ATS_ENUM.TriggerEngines.TRIG_ENGINE_K,
    ATS_ENUM.TriggerSources.TRIG_DISABLE,
    ATS_ENUM.TriggerSlopes.TRIGGER_SLOPE_POSITIVE,
    128                 # Level (ignored for engine K)
)
```

### 5. External Trigger

```python
board.set_external_trigger(
    ATS_ENUM.Couplings.DC_COUPLING,
    ATS_ENUM.ExternalTriggerRanges.ETR_TTL
)
```

### 6. Trigger Delay

```python
board.set_trigger_delay(0)  # Pre-trigger samples (0 for NPT mode)
```

### 7. Trigger Timeout

```python
board.set_trigger_time_out(0)  # Wait forever (0 = infinite timeout)
```

### 8. LSB Configuration

Configure LSB outputs for frame/line synchronization (via register manipulation):

```python
board.configure_lsb_outputs(
    lsb0_source=2,  # LSB[0] = AUX_IN[0]
    lsb1_source=3   # LSB[1] = AUX_IN[1]
)
```

**Register details (internal implementation):**
- REG 29: LSB source selection (bits [13:12] = lsb0, bits [15:14] = lsb1)
- REG 15: AUX_IN[1] direction (bit 27 = 1 when lsb0=3 or lsb1=3, else 0)

**Important Notes:**
- All configuration calls must complete successfully before starting acquisition
- Channel identifiers use enum: `ATS_ENUM.Channels.CHANNEL_A` (0x1), `CHANNEL_B` (0x2)
- Use bitwise OR to combine channels: `CHANNEL_A | CHANNEL_B = 0x3`
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
board.set_record_size(transferOffset, samplesPerRecord)
board.before_async_read(channelSelect, transferOffset, samplesPerRecord,
                        recordsPerBuffer, recordsPerAcquisition, flags)
```

**CRITICAL:** `ADMA_NPT` (0x200) and `ADMA_CONTINUOUS_MODE` (0x100) are **mutually exclusive**. Combining them causes `ApiInvalidData`. Scanbox uses NPT mode with external trigger and interleaved samples.

**Acquisition modes (depending on scanning geometry):**

**Unidirectional mode:**
- 1 trigger per frame
- Each DMA record = one resonant scan line
- `samplesPerRecord = samples_per_line` (e.g. 5000)
- `recordsPerBuffer = lines_per_frame` (e.g. 512)

**Bidirectional mode:**
- 1 trigger per full resonant cycle (forward + backward sweeps)
- Each DMA record spans both sweeps
- `samplesPerRecord = samples_per_line_bidir` (e.g. 9000)
- `recordsPerBuffer = lines_per_frame // 2` (e.g. 256)
- Each record yields 2 output lines (one forward, one backward)

**Example (unidirectional):**
```python
# Determine geometry based on config
unidirectional = config.get('acquisition', {}).get('unidirectional', True)
if unidirectional:
    samples_per_record = config['acquisition']['samples_per_line']  # 5000
    records_per_buffer = config['acquisition']['lines_per_frame']   # 512
else:
    samples_per_record = config['acquisition']['samples_per_line_bidir']  # 9000
    records_per_buffer = config['acquisition']['lines_per_frame'] // 2    # 256

# Set record parameters (pre-trigger = 0, post-trigger = samplesPerRecord)
board.set_record_size(0, samples_per_record)

# Configure before async read
channels_mask = (ATS_ENUM.Channels.CHANNEL_A.value | 
                 ATS_ENUM.Channels.CHANNEL_B.value)  # 0x3

board.before_async_read(
    channels_mask,          # CHANNEL_A | CHANNEL_B
    0,                      # transferOffset (no pre-trigger in NPT)
    samples_per_record,     # Samples per record (per channel, per line)
    records_per_buffer,     # Records per buffer (lines per frame or frame/2)
    0x7FFFFFFF,             # recordsPerAcquisition (infinite for focus/live)
    # Flags: ADMA_EXTERNAL_STARTCAPTURE | ADMA_NPT | ADMA_INTERLEAVE_SAMPLES
    ATS_ENUM.ADMAFlags.ADMA_EXTERNAL_STARTCAPTURE |
    ATS_ENUM.ADMAModes.ADMA_NPT |
    ATS_ENUM.ADMAFlags.ADMA_INTERLEAVE_SAMPLES
)
```

**Parameter details:**

| Parameter | Type | Description | Scanbox Value |
|-----------|------|-------------|---------------|
| `channelSelect` | U32 | Channel bitmask (Channels.CHANNEL_A \| Channels.CHANNEL_B) | 0x3 |
| `transferOffset` | c_long | Pre-trigger samples (0 for NPT mode) | 0 |
| `samplesPerRecord` | U32 | Samples per record (must be aligned to 64) | 5000 (uni) or 9000 (bi) |
| `recordsPerBuffer` | U32 | Records per DMA buffer (1..N) | 512 (uni) or 256 (bi) |
| `recordsPerAcquisition` | U32 | Total records (0x7FFFFFFF = infinite) | 0x7FFFFFFF |
| `flags` | U32 | ADMA_EXTERNAL_STARTCAPTURE \| ADMA_NPT \| ADMA_INTERLEAVE_SAMPLES | 0x301 |

**Acquisition flags:**
```python
ADMA_EXTERNAL_STARTCAPTURE = 0x001  # External trigger starts acquisition
ADMA_NPT                   = 0x200  # No pre-trigger mode
ADMA_INTERLEAVE_SAMPLES    = 0x100  # Interleave samples from both channels
ADMA_CONTINUOUS_MODE       = 0x100  # (MUTUALLY EXCLUSIVE with NPT—do not use)
```

### DMA Buffer Management

**Buffer posting and retrieval:**
```python
# Calculate buffer size based on acquisition geometry
bytes_per_buffer = samples_per_record * records_per_buffer * channels * 2

# Post buffers before starting acquisition
for buffer_ptr in buffer_pointers:
    board.post_async_buffer(buffer_ptr, bytes_per_buffer)

# Start acquisition
board.start_capture()

# Wait for and retrieve filled buffers in circular fashion
buffer_index = 0
while acquiring:
    buffer_ptr = buffer_pointers[buffer_index]
    board.wait_async_buffer_complete(buffer_ptr, timeout_ms=5000)
    
    # Process data from buffer
    data = buffers[buffer_index].copy()
    
    # Re-post buffer for continuous acquisition
    board.post_async_buffer(buffer_ptr, bytes_per_buffer)
    
    buffer_index = (buffer_index + 1) % len(buffer_pointers)
```

**Buffer circular management:**
- Allocate multiple buffers (typically 16) for ring buffer
- Post all buffers before starting capture
- Wait for buffer to complete, process data, then re-post
- Rotate through buffers in circular fashion

**Important:** After any timeout or error from `wait_async_buffer_complete()`, call `abort_async_read()` to reclaim all pending DMA buffers and reset the board to a clean state.

**Performance considerations:**
- More buffers = more latency tolerance but higher memory usage
- Typical configuration: 16 buffers × 8KB = 128KB total
- At 125 MS/s with 2 channels, each 2048-sample record fills in ~8 μs
- Processing must be faster than buffer fill rate to avoid overflow

## Common Errors and Solutions

### ApiInvalidData Error

**Cause 1:** Using `ADMA_CONTINUOUS_MODE | ADMA_NPT` together (mutually exclusive).

**Solution:** Use only `ADMA_NPT` with `ADMA_EXTERNAL_STARTCAPTURE` and `ADMA_INTERLEAVE_SAMPLES`.

**Cause 2:** Buffer size not aligned or parameters inconsistent.

**Solution:** 
- Ensure `samplesPerRecord` is aligned to 64 samples
- Ensure `samplesPerRecord >= 256`
- Verify: `samplesPerRecord % 64 == 0` and `samplesPerRecord >= 256`
- Verify channel mask is correct: `CHANNEL_A | CHANNEL_B = 0x3`

### Buffer Overflow

**Cause:** Not reading buffers fast enough during continuous acquisition.

**Solution:**
- Increase buffer count
- Reduce samples per buffer (adjust acquisition parameters)
- Optimize processing code to read data faster
- Monitor: Check if application is keeping up with data rate

### Timeout on wait_async_buffer_complete()

**Cause:** Acquisition not actually running, or DMA stalled.

**Solution:**
- Verify `set_record_size()` was called before `before_async_read()`
- Verify all configuration steps completed successfully
- Call `abort_async_read()` after timeout
- Clear all buffer references to reset board state
- Check external trigger signal is present and valid

### Configuration Fails / Board Not Responding

**Cause:** Missing required configuration calls or wrong order.

**Solution:**
- Follow the 8-step configuration sequence exactly (Section: Configuration Sequence)
- Ensure `set_external_clock_level()` is called (required for ATS9440, not optional)
- Verify external clock and trigger signals are connected and active
- Check board connection (PCIe)
- Verify driver is installed (atsbindings requires Alazar SDK)

### Variable Amplitude / Gain Issues

**Cause 1:** Wrong input range selected for amplifier type.

**Solution:** 
- Use `INPUT_RANGE_PM_200_MV` (0x6) for variable-gain amplifiers
- Use `INPUT_RANGE_PM_1_V` (0xA) for fixed-gain amplifiers
- Check `config['pmt']['amplifier_type']` setting

**Cause 2:** Trigger level too high or too low.

**Solution:**
- Adjust `config['alazar']['trigger_level']` (default 160, range 0-255)
- Monitor external trigger signal with oscilloscope
- Try trigger_level values in range [100, 200]

## Example Usage

See [pyscanbox/hardware/alazar.py](../../pyscanbox/hardware/alazar.py) for the complete implementation including:
- `AlazarDigitizer.__init__()` — Initialization and configuration
- `AlazarDigitizer.configure()` — All 8 configuration steps
- `AlazarDigitizer.allocate_buffers()` — DMA buffer allocation
- `AlazarDigitizer.start_acquisition()` — Start data acquisition
- `AlazarDigitizer.read_buffer()` — Circular buffer management
- `AlazarDigitizer.configure_lsb_outputs()` — LSB register manipulation

For validation examples, see `examples/check_alazar.py` (if available).

## Python API Reference

This documentation uses the `atsbindings` Python bindings which wrap the Alazar SDK. Key classes and enums:

- `atsbindings.Board` — Main hardware interface
- `atsbindings.enumerations` — All API constants (ClockSources, SampleRates, Channels, etc.)
- `atsbindings.Buffer` — Pinned memory for DMA transfers

Access enums as: `ATS_ENUM.ClockSources.FAST_EXTERNAL_CLOCK`, `ATS_ENUM.Channels.CHANNEL_A`, etc.

## Original MATLAB References

**File Locations:**
- `Scanbox/core/scanbox.m` (lines 743-893) - Board initialization and configuration
- `Scanbox/core/configureLsb9440.m` - LSB register manipulation
- `Scanbox/alazartech/AlazarDefs.m` - All API constant definitions
- `Scanbox/alazartech/*.m` - Individual API function wrappers

## Additional Resources

- `../alazar_digitizer.md` - User-facing documentation
- `atsbindings.enumerations` - Complete API constant definitions
