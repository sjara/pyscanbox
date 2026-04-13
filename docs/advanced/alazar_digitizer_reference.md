# AlazarTech ATS9440 Digitizer Reference

This document describes the high-level system architecture, hardware setup, theory of operation, and troubleshooting for the AlazarTech ATS9440 digitizer. It is designed for users installing, configuring, and operating the digitizer system.

For low-level technical details, strict configuration sequences, API constants, and Python implementation examples, see [AlazarTech ATS9440 Protocol](../hardware_protocols/alazar_digitizer.md).

## Overview

The AlazarTech ATS9440 is a high-speed PCIe digitizer that acquires PMT (photomultiplier tube) signals during two-photon imaging. It samples at 125 MS/s with 14-bit resolution across 2 channels, providing ~500 MB/s continuous data throughput.

**Key Specifications:**
- **Model:** ATS9440
- **Sample Rate:** 125 MS/s (externally clocked)
- **Resolution:** 14-bit
- **Channels:** 2 (Channel A and Channel B for dual PMTs)
- **Interface:** PCIe x8
- **Throughput:** ~500 MB/s continuous DMA transfer

## Critical Configuration: External Clock Synchronization

### Why External Clock?

**The ATS9440 in Scanbox uses an EXTERNAL CLOCK, not the internal clock.** The original MATLAB implementation (`core/scanbox.m`, line 757) configures the clock source as `FAST_EXTERNAL_CLOCK`.

The digitizer is clocked by the **laser sync-out** (~80 MHz from the Chameleon), cleaned with a BBP-70+ band-pass filter from Mini-circuits. This ensures that each sample is synchronized to a single laser pulse, avoiding the beat-pattern artifacts that arise when using an asynchronous clock. ([source](https://scanbox.org/2014/03/18/synchronize-to-the-laser/))

The **line trigger** is a separate signal sent by the Scanbox controller card (PSoC5) to the TRIG IN input, triggering acquisition of each line. ([source](https://scanbox.org/2014/03/13/the-heart-of-scanbox/))

**Clock Source:** `FAST_EXTERNAL_CLOCK (0x2)`  
**Sample Rate Parameter:** `SAMPLE_RATE_USER_DEF (0x40)` - ignored when using external clock  
**Actual Sample Rate:** Determined by the laser pulse frequency (~80 MHz, varies with wavelength)

### Configuration

The clock is configured in `pyscanbox.hardware.alazar.AlazarDigitizer.configure()` via Python enums (see [AlazarTech ATS9440 Protocol](../hardware_protocols/alazar_digitizer.md) for implementation details).

**Common Mistake:** Using `INTERNAL_CLOCK (0x1)` with a sample rate constant. This will fail because the system expects external synchronization from the scanner hardware.

**Config reference:** Set in `pyscanbox.config.yaml` under `alazar` section (externally sourced clock requires no config parameters).

### External Clock Level

The external clock comparator level is set to 65% to ensure reliable edge detection:

```matlab
% Original MATLAB implementation
AlazarSetExternalClockLevel(boardHandle, 65.0)
```

## LSB Outputs: Frame/Line Synchronization

### What Are LSB Outputs?

**LSB (Least Significant Bit) outputs are NOT physical output connectors.** They are control bits embedded in the digitized data stream. This is an important safety consideration.

The LSB bits (LSB[0] and LSB[1]) are configured by writing to Register 29 via
`configure_lsb_outputs()` in Python (or `configureLsb9440()` in original MATLAB).  The actual Scanbox call is
`configure_lsb_outputs(lsb0_source=0, lsb1_source=3)` (equivalent to MATLAB `configureLsb9440(boardHandle, 0, 3)`, line 891), which configures:

- **LSB[0] (bit 0):** value 0 → **always zero (disabled).**
- **LSB[1] (bit 1):** value 3 → **AUX_IN[1]** input — external TTL event
  signal.  This records per-frame whether a behavioral or optogenetic
  stimulus was active.  MATLAB stores it in `ttl_log` and reads it from
  `ttlflagnew` (extracted by `alazarReshapeCData2_openmp`).

These bits are embedded in every 16-bit ADC sample in the data stream.  They
are **not** frame or line sync markers — frame/line boundaries are determined
by the trigger architecture (the PSoC5 line trigger at `TRIG IN` defines each
line, and the frame counter is maintained by software).

### Safety: No External Outputs

**You cannot damage external equipment through LSB configuration.** The LSB bits:
- Do not control physical output pins
- Are read-only markers in the data stream
- Map to INPUT signals (AUX_IN[0] and AUX_IN[1])
- Flow only as: External signals → ATS9440 → Digital samples → Computer memory

### Configuration

The LSB bits are configured by writing to Register 29 of the ATS9440
(see `core/configureLsb9440.m`).

**Register 29 source encoding:**
- Bits [13:12]: LSB[0] source — 0=low, 1=ext_trig, 2=AUX_IN[0], 3=AUX_IN[1]
- Bits [15:14]: LSB[1] source — 0=low, 1=ext_trig, 2=AUX_IN[0], 3=AUX_IN[1]

**Scanbox configuration:** `configureLsb9440(boardHandle, 0, 3)` sets
LSB[0]=0 (disabled) and LSB[1]=3 (AUX_IN[1]).

Implementation: See `pyscanbox.hardware.alazar.AlazarDigitizer.configure_lsb_outputs()`

## Input Configuration

### Coupling: DC vs AC

**Scanbox uses DC COUPLING, not AC coupling** (see `core/scanbox.m`, line 807). DC coupling:
- Preserves the absolute signal level from PMTs
- Avoids high-pass filtering that AC coupling introduces
- Maintains signal fidelity for quantitative measurements

### Input Range: 200mV vs 1V

The input range should match your PMT amplifier type:

**Variable gain amplifiers:** `INPUT_RANGE_PM_200_MV (0x6)` - ±200 mV  
**Fixed gain amplifiers:** `INPUT_RANGE_PM_1_V (0xA)` - ±1 V

This is configured based on the `pmt_amp_type` setting in the configuration file (MATLAB `scanbox.m` lines 786-798, pyscanbox `config['pmt']['amplifier_type']`):

```yaml
# In pyscanbox.config.yaml
pmt:
  amplifier_type: 'variable'  # or 'fixed'
```

The Python implementation automatically selects the correct input range based on this setting (see [alazar_digitizer.md](../hardware_protocols/alazar_digitizer.md#3-input-channels)).

### Input Impedance

**50 Ohm impedance** is used for proper signal termination.

Implementation: See `pyscanbox.hardware.alazar.AlazarDigitizer.configure()`

## PMT Output Polarity and Display Inversion

### How a PMT Responds to Light

A photomultiplier tube (PMT) converts photons into electrons and amplifies the
resulting current.  The output **current increases** when more photons arrive.
After transimpedance amplification the voltage at the Alazar input **decreases**
toward 0 V (or goes negative) with brighter illumination.

### ATS9440 Offset-Binary Encoding

The ATS9440 uses **offset-binary encoding**: the 14-bit ADC output is an unsigned
integer centered at 2¹³ = 8192 (mid-scale):

| Signal at input | Raw 14-bit ADC value |
|-----------------|----------------------|
| +200 mV (positive rail) | 16383 (maximum) |
| 0 V (no signal / dark) | ~8192 (mid-scale) |
| −200 mV (negative rail) | 0 (minimum) |

A PMT with no light (zero current, zero voltage) therefore produces values
**near 8192**, not near zero.

### Why the Background Sits at ADC Maximum

In practice the Scanbox PMT amplifier outputs a small **negative** bias voltage
at rest (dark current + circuit offset).  This pushes the ADC output **above**
mid-scale, toward 16383.  When fluorescence arrives:

1. More photons → larger PMT current
2. Larger current → amplifier output goes more negative
3. More negative voltage → ADC value **decreases** toward 0

Consequence: **high ADC value = dark background; low ADC value = bright signal.**

### Display Inversion

The original Scanbox MATLAB code (`alazarReshapeCData2.c`) accounts for this
polarity by explicitly inverting the display pixel:

```c
static unsigned char *vh0 = (unsigned char *)(&v0) + 1;  // high byte of sum
// display value:
255 - *vh0
```

This maps:

| ADC condition | Raw 14-bit ADC | Stored 16-bit wire format | Display byte | Screen |
|---------------|----------------|--------------------------|--------------|--------|
| Dark background (no light) | ≈ 16383 | ≈ 65532 | ≈ 0 | **Black** |
| Fluorescent signal (bright) | ≈ 0 | ≈ 0 | ≈ 255 | **White / channel colour** |

Note: the stored 16-bit value is the raw 14-bit ADC value shifted left by 2
(`adc_14bit << 2`), so it occupies the same 0–65532 range as the wire
format.  The display formula operates on the 16-bit stored value.

pyscanbox applies the same inversion in **Fluorescence** display mode
(`ImageDisplayWidget`, `_invert = True`, the default):

```python
scaled = (65535 - ch) * gain / 256.0   # background → 0 (black), signal → 255
```

This matches MATLAB's `255 - high_byte(v)` = `255 - (v >> 8)` = `(65535 - v) / 256`.

The **Direct (debug)** display mode (`_invert = False`) shows the stored value
directly (high value = bright).  This is useful for verifying signal levels
without a laser or sample: the image should appear nearly white (wire-format
value ≈ 65532) and flicker slightly with electronic noise.

## Trigger Configuration

### External Trigger

The system uses an external trigger from the scanning hardware (see `core/scanbox.m`, lines 835-881). The trigger configuration uses:

- **Engine:** TRIG_ENGINE_OP_J (J engine only, K disabled)
- **Source:** TRIG_EXTERNAL
- **Coupling:** DC_COUPLING  
- **Level:** ETR_TTL (TTL level trigger)

### Configurable Trigger Parameters

Two parameters control the trigger behavior and can be adjusted in `pyscanbox.config.yaml`:

```yaml
alazar:
  trigger_level: 160         # Range 0-255; mid-range default
  trigger_slope: 0           # 0 = positive slope, 1 = negative slope
```

**Trigger Level (0-255):** Controls the voltage threshold at which the external trigger pulse is detected. Default 160 represents mid-range sensitivity. Adjust if:
- Signal too weak: Lower the level (e.g., 100-130)
- False triggers from noise: Raise the level (e.g., 180-200)

**Trigger Slope:** Selects whether the trigger fires on rising (0) or falling (1) edges:
- `0` = TRIGGER_SLOPE_POSITIVE (rising edge) — typical for TTL signals
- `1` = TRIGGER_SLOPE_NEGATIVE (falling edge) — use if trigger pulse polarity is inverted

For details on implementation, see [alazar_digitizer.md#4-trigger-operation](../hardware_protocols/alazar_digitizer.md#4-trigger-operation).

### Acquisition Geometry: Unidirectional vs Bidirectional Scanning

The ATS9440 acquisition layout depends on the scanning mode, which configures how many samples and records fit in each DMA buffer:

**Unidirectional mode** (one scan direction only):
- 1 trigger pulse per scan line (forward sweep only)
- `samplesPerRecord = samples_per_line` (e.g., 5000 ADC samples per channel per line)
- `recordsPerBuffer = lines_per_frame` (e.g., 512 triggers = 512 lines per frame)
- Buffer holds one complete image frame

**Bidirectional mode** (forward and backward sweeps):
- 1 trigger pulse per full resonant cycle (covers both forward and backward sweeps)
- `samplesPerRecord = samples_per_line_bidir` (e.g., 9000 ADC samples per channel per full cycle)
- `recordsPerBuffer = lines_per_frame // 2` (e.g., 256 triggers = 512 output lines per frame)
- Each DMA record yields 2 output lines (one forward, one backward)
- Buffer still holds one complete image frame (512 lines) in the same `bytes_per_buffer`

Configuration in `pyscanbox.config.yaml`:
```yaml
acquisition:
  unidirectional: true        # Set to false for bidirectional mode
  samples_per_line: 5000      # Unidirectional mode
  samples_per_line_bidir: 9000  # Bidirectional mode (if unidirectional: false)
  lines_per_frame: 512
```

For implementation details, see [alazar_digitizer.md#data-acquisition-npt-mode](../hardware_protocols/alazar_digitizer.md#data-acquisition-npt-mode).

### ⚠️ Critical: The Scanner Must Be Running for Acquisition to Work

The SAMPLE TRIGGER pulses are generated by the **PSoC5 controller** in sync with the resonant scanner's line oscillation. The controller only generates these pulses **while the scanner is actively scanning**.

Consequences:
- Without the scanner running, no trigger pulses arrive at `TRIG IN`.
- `AlazarWaitAsyncBufferComplete` will block until it times out (`ApiWaitTimeout`, default 5 s).
- After the first timeout, all subsequent calls return `ApiBufferNotReady` because the board still owns all pending DMA buffers.
- The only recovery is `AlazarAbortAsyncRead()` to reclaim board-owned buffers.

**Correct startup sequence for real hardware:**
1. Configure and allocate buffers (no hardware signals needed yet)
2. Connect to PSoC5 controller and call `start_scan()` — wait ≥2 s for resonant scanner to reach steady state
3. Call `start_acquisition()` — the board immediately starts receiving triggers
4. Read buffers, stop acquisition, then call `stop_scan()`

For implementation details, see [alazar_digitizer.md](../hardware_protocols/alazar_digitizer.md) and `pyscanbox.hardware.alazar.AlazarDigitizer.configure()`.

## DMA Buffer Management

### Memory Requirements

The digitizer uses DMA (Direct Memory Access) for high-speed data transfer. Proper buffer management is critical:

**Real hardware (raw ADC mode):**
- **Record size:** `samples_per_line` (5000) ADC samples per channel, one per scan line
- **Records per buffer:** `lines_per_frame` (512) — one full frame per DMA buffer
- **Buffer size:** 5000 × 512 × 2 channels × 2 bytes = **10,240,000 bytes (~9.77 MB)**
- **Total DMA memory (16 buffers):** ~156 MB

**Emulation / pre-shaped mode (`alazar.raw_mode: false`):**
- **Buffer size:** `samples_per_buffer` × 2 channels × 2 bytes = 407,552 × 2 × 2 = **1,630,208 bytes (~1.55 MB)**
- **Total DMA memory (16 buffers):** ~24.8 MB

**Buffer Count:** 16 buffers (configurable via `alazar.buffer_count`)

These values are calculated automatically by `AlazarDigitizer._bytes_per_buffer` based on the active mode.

### Pinned Memory and Buffer Ring Design

**Important:** Use pinned (page-locked) memory for DMA buffers to prevent Python's garbage collector from moving memory during hardware transfers.

`AlazarDigitizer.allocate_buffers()` delegates this directly to `atsbindings.Buffer`, the class provided by the AlazarTech Python SDK. `Buffer` allocates true page-locked memory through the driver (`VirtualAlloc` + `VirtualLock` on Windows; equivalent mechanism on Linux). No application-level buffer management layer is needed on top of this.

**Circular ring:** `AlazarDigitizer` maintains a plain list `self.buffers[]` of `Buffer.buffer` numpy-array views. After `read_buffer()` consumes a buffer it immediately re-posts it to the board with `postAsyncBuffer`, cycling through the list with a `mod` index. This is exactly what the original MATLAB `scanbox.m` does: it allocates a cell array of C pointers via `AlazarAllocBufferU16` and re-posts each one using `mod(buffersCompleted, bufferCount)` — no buffer management class.

**Producer-consumer threading:** the acquisition loop in `scan.py` processes each frame inline (reshape → write → callback). If a frame-rate test shows that reshape + disk write cannot keep pace with DMA throughput, a two-thread split can be added to `scan.py` at that point — no separate module is required.

## Data Format

### 16-bit Interleaved Data

The ATS9440 outputs 16-bit samples with the PMT data in the upper 14 bits and LSB sync bits in the lower 2 bits:

```
Bit 15-2: 14-bit PMT data (0-16383), i.e. adc_14bit << 2
Bit 1:    LSB[1] = AUX_IN[1] (external TTL event; see LSB Outputs section)
Bit 0:    LSB[0] = 0 (disabled in Scanbox)
```

### Channel Interleaving

Data from Channel A and Channel B are interleaved:

```
[ChanA_sample0, ChanB_sample0, ChanA_sample1, ChanB_sample1, ...]
```

The reshaping code must de-interleave and extract the 14-bit PMT values while preserving the LSB sync information.

## Raw Hardware Data Reshaping

### Pixel LUT (arccosine mapping)

The resonant mirror scans sinusoidally, so raw ADC samples are **not uniformly spaced** in image space.
`pixel_lut_2.m` (and its Python equivalent `reshape.compute_pixel_lut()`) precomputes a lookup table
that maps each of the 796 output pixels to a base raw-sample index:

```matlab
% MATLAB – pixel_lut_2.m
nsamp = round(sbconfig.lasfreq / sbconfig.resfreq);   % ≈ 10112 samples/half-period
n = acos(linspace(1, -1, ncol+2)) * nsamp / (2*pi);
n = n(2:end-1);         % remove endpoints
S = floor(n) - 1;       % MATLAB 1-indexed base sample → Python: floor(n) - 2
S = [S; S+1; S+2; S+3]; % 4 consecutive samples per pixel
```

Each output pixel averages **4 consecutive raw ADC samples**.

### How MATLAB stores and displays the data (`alazarReshapeCData2.c`)

The MATLAB MEX file sums — but does **not** average — the four raw samples and then right-shifts by 2:

```c
// For each output pixel (796 × nlines):
tmp0 =  inMatrix[*inIdx++];  // raw chA sample 0  (format: adc14 << 2 | sync_bits)
tmp0 += inMatrix[*inIdx++];  // raw chA sample 1
tmp0 += inMatrix[*inIdx++];  // raw chA sample 2
tmp0 += inMatrix[*inIdx++];  // raw chA sample 3
v0 = (unsigned short int)(tmp0 >> 2);  // ← keeps 16-bit range (0–65532)
```

The `>> 2` here does **not** strip the sync bits per sample; it divides the 4-sample sum by 4,
yielding a value in **0–65532 (16-bit range)**.  This is what gets written to the `.sbx` file.

For display, MATLAB takes the **high byte** of `v0`:

```c
static unsigned char *vh0 = (unsigned char *)(&v0) + 1;  // high byte
// display pixel: 255 - *vh0
```

`*vh0` is `v0 >> 8`, so the effective display mapping is `sum_of_4_samples >> 10`, which maps
the full 16-bit range to 8-bit.

### How pyscanbox stores the data (`reshape.reshape_pmt_data`)

``reshape_pmt_data()`` matches MATLAB exactly: sums 4 raw samples and right-shifts by 2 (divide by 4),
without stripping the sync bits, retaining the 16-bit wire encoding:

```python
# >> 2 averages 4 samples (divide by 4), matching alazarReshapeCData2.c which does
# exactly `(unsigned short int)(tmp >> 2)`.
# The 2 LSB sync bits are NOT stripped here; the output retains the
# same 16-bit wire encoding as the input (14-bit ADC data in bits 15:2).
output[0, line, px] = np.uint16(sum_a >> 2)
output[1, line, px] = np.uint16(sum_b >> 2)
```

pyscanbox `.sbx` output is byte-compatible with MATLAB.

### Equivalence for display

Both pipelines produce identical stored values and the same 8-bit screen value:

| Step | MATLAB | pyscanbox |
|------|--------|-----------|
| Sum 4 raw samples | `tmp0` (0–65532, sync bits included) | `sum_a` (0–65532, sync bits included) |
| Stored value | `tmp0 >> 2` (0–65532, 16-bit) | `sum_a >> 2` (0–65532, 16-bit) |
| Display mapping | high byte of stored value (`>> 8`) → 8-bit | high byte of stored value (`>> 8`) → 8-bit |
| Effective shift from raw sum | `>> 10` | `>> 10` ✓ |

The stored values and screen pixels are identical.  pyscanbox `.sbx` files are byte-compatible
with MATLAB output and are read correctly by downstream tools (Suite2p, etc.).

### Reference files

| File | Purpose |
|------|---------|
| `Scanbox/core/alazarReshapeCData2.c` | MATLAB MEX reshape + display (raw hardware) |
| `Scanbox/core/pixel_lut_2.m` | Arccosine LUT construction |
| `pyscanbox/acquisition/reshape.py` | Python equivalents (`compute_pixel_lut`, `reshape_pmt_data`, `reshape_pmt_data_emulation`) |

## Design Decisions: Data Format for Saving

### Why uint16, not packed 14-bit

The ATS9440 is a 14-bit ADC, so only 14 of the 16 bits carry ADC data.  It is
tempting to pack the samples into 14-bit words to save ~12.5% disk space.
pyscanbox does not do this, for the following reasons:

- **Tooling compatibility.** Every standard scientific tool (ImageJ/Fiji, numpy,
  MATLAB, Suite2p, etc.) reads uint16 natively.  Packed 14-bit requires a custom
  reader in every downstream tool — a fragile tax on all future users.
- **Negligible benefit.** At 512 × 796 × 2 channels, a 512-frame file is ~840 MB
  as uint16 vs ~735 MB packed.  Modern SSDs have ample headroom and the 12.5%
  saving rarely justifies the complexity.
- **`.sbx` compatibility.** The original Scanbox MATLAB code stores data as
  uint16 (see `sbxread.m`).  Packing to 14-bit would break compatibility with all
  existing MATLAB analysis scripts.

**Decision: always write uint16.**

### Why the sync bits are not stripped before saving

Each stored uint16 word contains two sync bits in the low positions (bits 1:0):

- **Bit 0 (LSB[0]):** frame sync — set on the first sample of each new frame
- **Bit 1 (LSB[1]):** line sync — set on the first sample of each scan line

These could be zeroed out before saving to give a cleaner 14-in-16 encoding.
pyscanbox deliberately does not strip them:

1. **Original Scanbox does not strip them.** `sbxread.m` reads and inverts the
   full uint16 value (`x = intmax('uint16') - x`) without masking.  Stripping
   would break `.sbx` compatibility and change stored values.
2. **The sync bits are silent in images.** They are set on only the *first sample*
   of each frame/line, not on every pixel.  Even when set, they change a pixel
   value by at most ±2 on a 0–65535 scale — far below the PMT noise floor and
   invisible in any rendered image.
3. **They carry useful information.** The sync bits allow post-hoc recovery of
   exact frame and line timing from the raw data file, which is valuable for
   alignment and synchronisation analysis.

**Decision: preserve sync bits in stored data, exactly as MATLAB does.**

## Common Issues and Troubleshooting

### ApiInvalidData from AlazarBeforeAsyncRead

**Symptom:** `Error calling function AlazarBeforeAsyncRead with arguments (...) : b'ApiInvalidData'`

**Causes — all of these will independently trigger this error:**
1. **Wrong ADMA flags:** `ADMA_NPT (0x200)` and `ADMA_CONTINUOUS_MODE (0x100)` are **mutually exclusive** acquisition modes. Combining them produces `ApiInvalidData`. The correct flags (matching MATLAB `scanbox.m` line 2223) must include:
   - `ADMA_EXTERNAL_STARTCAPTURE` (external trigger starts capture)
   - `ADMA_NPT` (No Pre-Trigger mode for streaming)
   - `ADMA_INTERLEAVE_SAMPLES` (interleave channel A and B data)
   
   For exact hex values and implementation, see [alazar_digitizer.md#alazarbeforeasyncread](../hardware_protocols/alazar_digitizer.md#alazarbeforeasyncread).

2. **Wrong `samplesPerRecord`:** Must match the acquisition geometry:
   - Unidirectional: `samples_per_line` (e.g., 5000)
   - Bidirectional: `samples_per_line_bidir` (e.g., 9000)
   
   **NOT** the full-frame sample count (407552).

3. **Wrong `recordsPerBuffer`:** Must match the acquisition geometry:
   - Unidirectional: `lines_per_frame` (e.g., 512)
   - Bidirectional: `lines_per_frame // 2` (e.g., 256)
   
   **NOT** 1.

4. **Missing `setRecordSize` call:** `AlazarSetRecordSize(0, samples_per_record)` or Python equivalent must be called **before** `AlazarBeforeAsyncRead` (matches MATLAB `scanbox.m` sequence).

**Reference:** MATLAB ground truth is `Scanbox/core/scanbox.m` lines 2220–2230. See [alazar_digitizer.md](../hardware_protocols/alazar_digitizer.md) for Python implementation matching this sequence exactly.

### ApiInvalidData from AlazarSetCaptureClock

**Symptom:** `Error calling function AlazarSetCaptureClock ... ApiInvalidData`

**Causes:**
1. Using `INTERNAL_CLOCK (0x1)` instead of `FAST_EXTERNAL_CLOCK (0x2)`
2. Using sample rate constant (e.g., `0x25` for 125 MSPS) instead of `SAMPLE_RATE_USER_DEF (0x40)`
3. Missing external clock connection

**Solution:** Verify external clock configuration and ensure laser sync-out cable is connected to the ECLK input.

### ApiWaitTimeout / ApiBufferNotReady

**Symptom:**
```
Error calling function AlazarWaitAsyncBufferComplete ... : b'ApiWaitTimeout'
Error calling function AlazarWaitAsyncBufferComplete ... : b'ApiBufferNotReady'
```
(The second error floods repeatedly after the first.)

**Cause:** The Alazar board is waiting for trigger pulses that never arrive. After the first `ApiWaitTimeout`, all subsequent DMA buffers are still owned by the board — every further `waitAsyncBufferComplete` call returns `ApiBufferNotReady` immediately.

**Most common cause: the scanner is not running.** The PSoC5 controller generates trigger pulses only while actively scanning (see [Trigger section](#️-critical-the-scanner-must-be-running-for-acquisition-to-work) above).

**Checklist:**
1. Is the resonant scanner powered on and running? (`start_scan()` called, ≥2 s warmup)
2. Is the SAMPLE TRIGGER cable connected from the Scanbox controller box to the Alazar TRIG IN?
3. Is the laser on? (ECLK needs the laser sync-out signal too)
4. After any timeout, call `abortAsyncRead()` before attempting to reuse the board — the Python implementation handles this automatically in `read_buffer()`.

### Board Not Detected

**Symptom:** Cannot open board handle

**Troubleshooting:**
1. Verify PCIe card is properly seated
2. Check Device Manager for ATS9440
3. Reinstall AlazarTech SDK drivers
4. Run AlazarTech diagnostic utilities

### DMA Buffer Overruns

**Symptom:** Dropped frames or buffer overflow errors

**Causes:**
1. CPU too slow to process data
2. Disk write bottleneck
3. Insufficient PCIe bandwidth

**Solutions:**
1. Use PCIe x8 or x16 slot (not x4)
2. Disable power management on PCIe
3. Write data to fast SSD (NVMe recommended)
4. Optimize reshaping code with Numba/Cython
5. Close other applications during acquisition

### Trigger Not Working

**Symptom:** No data acquisition, waiting for trigger (`ApiWaitTimeout`)

**Troubleshooting:**
1. **Is the scanner running?** The PSoC5 only sends trigger pulses while scanning — call `start_scan()` and wait ≥2 s before starting acquisition
2. Verify external trigger cable is connected (Scanbox controller box SAMPLE TRIGGER → Alazar TRIG IN)
3. Check trigger level (0-255, typically 128 for mid-range)
4. Verify trigger slope setting matches signal polarity
5. Check trigger coupling (DC vs AC)
6. Use oscilloscope to verify trigger signal at TRIG IN

## Hardware Installation

### PCIe Slot Requirements

- **Minimum:** PCIe x4 Gen 2
- **Recommended:** PCIe x8 Gen 2 or later
- **Optimal:** PCIe x8 Gen 3

Check PCIe configuration in BIOS and Device Manager to ensure the card is running at full speed.

### Driver Installation

1. Download AlazarTech SDK from manufacturer website
2. Install SDK with administrator privileges
3. Reboot after installation
4. Verify installation by running AlazarTech test utilities
5. Confirm `ATSApi.dll` is in system path

### Signal Connections

The ATS9440 digitizer has multiple input connections that must be properly wired for two-photon imaging.

#### Input Connections

**Clock and Trigger Inputs:**
- **ECLK (External Clock Input):** Connected to the **laser sync-out** (~80 MHz) via a **BBP-70+ band-pass filter** (Mini-circuits). ([source](https://scanbox.org/2014/03/18/synchronize-to-the-laser/))
  - **Critical:** Synchronizes sampling to individual laser pulses, eliminating beat-pattern artifacts from asynchronous clocking. The actual sample rate (~80 MHz) varies with laser wavelength, hence `SAMPLE_RATE_USER_DEF` is used in software.
  - **From MATLAB code:** external clock configuration in `core/scanbox.m` line 757
  - Cable: 50-ohm coaxial (BNC or SMA) **⚠️ UNCONFIRMED: connector type not verified**
  
- **TRIG IN (External Trigger Input):** Connected to **SAMPLE TRIGGER** output from Scanbox controller box
  - **Purpose:** Triggers the start of data acquisition
  - **Signal type:** TTL level (**From MATLAB code:** `core/scanbox.m` lines 856-860)
  - **Coupling:** DC coupling (**From MATLAB code:** `core/scanbox.m` line 857)
  - Cable: 50-ohm coaxial (BNC or SMA) **⚠️ UNCONFIRMED: connector type not verified**

**Data Acquisition Channels:**
- **Channel A:** Connected **⚠️ UNCONFIRMED: signal source - may be direct from PMT or via Scanbox controller box**
  - **Input range:** ±200 mV (variable gain amps) or ±1 V (fixed gain amps) (**From MATLAB code:** `core/scanbox.m` lines 786-798)
  - **Coupling:** DC coupling (**From MATLAB code:** `core/scanbox.m` line 807)
  - **Impedance:** 50 Ohm (**From MATLAB code:** `Scanbox/alazartech/AlazarDefs.m`)
  - Cable: 50-ohm coaxial (BNC) **⚠️ UNCONFIRMED: connector type not verified**

- **Channel B:** Connected **⚠️ UNCONFIRMED: signal source - may be direct from PMT or via Scanbox controller box**
  - Same specifications as Channel A
  - Used for dual-channel imaging
  - Cable: 50-ohm coaxial (BNC) **⚠️ UNCONFIRMED: connector type not verified**

- **Channel C:** Not connected (4-channel boards only)
- **Channel D:** Not connected (4-channel boards only)

#### Auxiliary I/O

- **AUX 0:** Connected to stimulus presentation system **⚠️ UNCONFIRMED: default behavior and configuration not verified**
  - **Configuration:** Can be mapped to LSB[0] for frame sync (**From MATLAB code:** `core/configureLsb9440.m`)
  
- **AUX 1:** Not connected
  - **Configuration:** Can be mapped to LSB[1] for line sync (**From MATLAB code:** `core/configureLsb9440.m`)

**Note:** The AUX inputs/outputs serve a dual purpose and can be configured as either inputs or outputs depending on LSB configuration (see LSB Outputs section above).

#### Connection Diagram

**⚠️ PMT signal path not verified**

```
Scanbox Controller Box              AlazarTech ATS9440
┌─────────────────────┐             ┌─────────────────────┐
│                     │             │                     │
│  SAMPLE TRIGGER ────┼─────────────►  TRIG IN            │
│                     │             │                     │
│  PMT Port A     ────┼─────?───────►  Channel A          │ ⚠️ Signal path unknown
│  PMT Port B     ────┼─────?───────►  Channel B          │ ⚠️ Signal path unknown
│                     │             │                     │
└─────────────────────┘             │  ECLK        ◄──────┼─ Laser
                                    │                     │
                                    │  AUX 0 (out) ───────┼─ Stimulus System
                                    │  AUX 1 (out)        │
                                    │                     │
                                    └─────────────────────┘
```

#### Cable Requirements

**⚠️ UNCONFIRMED** - Cable specifications based on typical practice, not verified for this system:

- Use **50-ohm coaxial cables** (BNC or SMA connectors)
- Keep cable lengths reasonable (**<2m recommended**)
- Ensure proper grounding to minimize noise
- Use high-quality cables for clock and trigger signals to prevent jitter

**Cable Types:**
- **Clock/Trigger:** RG-58 or RG-174 coaxial cable with BNC or SMA connectors
- **PMT Signals:** RG-58 coaxial cable with BNC connectors
- Avoid adapters when possible to maintain signal integrity

## Performance Optimization

### Windows Settings

For optimal performance during acquisition:

1. **Disable Windows Update** during experiments
2. **Disable antivirus** real-time scanning on data directory
3. Use **High Performance** power plan
4. **Disable screen saver** and monitor sleep
5. Close **unnecessary background applications**

### PCIe Configuration

In BIOS/UEFI settings:
1. Enable PCIe Gen 2 or Gen 3
2. Set PCIe link speed to maximum
3. Disable PCIe power management (ASPM)
4. Ensure adequate PCIe lane allocation

### Storage Configuration

For 500 MB/s sustained write:
1. Use dedicated **NVMe SSD** for data (not system drive)
2. Ensure **200+ GB free space**
3. Avoid network drives or slow HDDs
4. Format with NTFS and large cluster size (64 KB)

## API Reference

For code-level implementation details, see:
- **Python API:** `pyscanbox.hardware.alazar.AlazarDigitizer`
- **Protocol Details:** `devel/hardware_protocols.md`
- **Original Implementation:** `Scanbox/core/scanbox.m` (lines 740-900)

## Further Reading

- AlazarTech ATS9440 User Manual
- AlazarTech SDK Programmer's Guide
- `devel/hardware_protocols.md` - Low-level protocol details
- `docs/hardware_setup.md` - Installation quick start
