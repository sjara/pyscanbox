# File Formats

Each recording session produces two files that share the same base name:

- **`<name>.sbx`** — raw binary PMT data
- **`<name>.mat`** — metadata (MATLAB v5 format)

This format is compatible with the original MATLAB Scanbox software and downstream tools such as [Suite2p](https://github.com/MouseLand/suite2p).

---

## The `.sbx` Binary File

The `.sbx` file is a flat, headerless binary file of raw `uint16` values.

### Value convention

Pixel values are stored as their **bitwise complement**:

```
stored_value = 65535 - signal
```

This means a dark pixel (no fluorescence) is stored near `65535`, and a bright pixel is stored near `0`. When reading the file for analysis (e.g. with Suite2p or `SbxReader`), the complement is automatically reversed so that high values represent bright fluorescence.

### On-disk layout

Frames are written sequentially. Within each frame, data is laid out in MATLAB column-major order, equivalent to the NumPy C-order shape:

```
(lines_per_frame, pixels_per_line, nchan)
```

The `nchan` axis is the fastest-varying (innermost) dimension.

### Number of frames

The `.mat` file stores a `max_idx` field, but **the authoritative frame count is derived from the file size**:

```
nframes = file_size_bytes / (lines_per_frame * pixels_per_line * nchan * 2)
```

This correctly handles recordings that were stopped before the intended number of frames was reached.

### Reading with Python

```python
import pyscanbox.io.sbx_reader

with pyscanbox.io.sbx_reader.SbxReader('mydata') as reader:
    print(reader.num_frames, reader.num_channels)
    frame = reader.get_frame(0)          # shape: (nchan, lines, pixels), uint16
    ch0   = reader.get_channel(0)        # shape: (nframes, lines, pixels), uint16
    all_data = reader.load()             # shape: (nframes, nchan, lines, pixels)
```

---

## The `.mat` Metadata File

The `.mat` file is a standard MATLAB v5 file written by `scipy.io.savemat`. It contains a single top-level variable named `info`, which is a nested struct.

### Core fields (required by `sbxread.m` and Suite2p)

| Field | Type | Description |
|---|---|---|
| `sz` | `[1×2 int64]` | `[lines_per_frame, pixels_per_line]` |
| `recordsPerBuffer` | `int64` | Scan lines per DMA buffer |
| `channels` | `int64` | PMT channel bitmask (see below) |
| `scanbox_version` | `int64` | File format version (always `2`) |
| `scanmode` | `int64` | `0` = bidirectional, `1` = unidirectional |
| `max_idx` | `int64` | Index of the last frame (0-based) |
| `nchan` | `int64` | Number of active PMT channels (1 or 2) |

### `channels` bitmask

| Value | Meaning |
|---|---|
| `1` | Both PMT0 and PMT1 active (`nchan = 2`) |
| `2` | PMT0 only (`nchan = 1`) |
| `3` | PMT1 only (`nchan = 1`) |

### `config` sub-struct

| Field | Type | Description |
|---|---|---|
| `wavelength` | `int64` | Laser wavelength in nm |
| `frames` | `int64` | Number of frames |
| `lines` | `int64` | Lines per frame |
| `magnification` | `int64` | 1-based magnification index |
| `magnification_list` | `float64[]` | Zoom values for each magnification step |
| `pmt0_gain` | `float64` | PMT 0 gain |
| `pmt1_gain` | `float64` | PMT 1 gain |
| `knobby.pos.x/y/z/a` | `float64` | Stage position in microns |

### Additional fields

| Field | Description |
|---|---|
| `resfreq` | Resonant mirror frequency in Hz |
| `postTriggerSamples` | Raw ADC samples per scan line |
| `bytesPerBuffer` | Bytes per DMA buffer |
| `ballmotion` | Ball/rotary encoder data (empty array if not recorded) |
| `abort_bit` | `1` if acquisition was aborted early, `0` otherwise |
| `frame`, `line`, `event_id` | TTL event timestamps (frame index, line index, event type) |
| `volscan` | `1` = volume scan, `0` = single plane |
| `fold_lines` | Lines folded for line-interleaved protocols |
| `messages` | Free-form messages logged during acquisition |
| `usernotes` | User notes entered before saving |
| `timestamp` | Wall-clock time of acquisition start (`YYYY-MM-DD HH:MM:SS`) |
| `pyscanbox_version` | pyscanbox version string |
| `objective` | Objective label (e.g. `"Nikon 16x 0.8NA water"`) |
| `laser_type` | Laser model string |

### Reading the `.mat` file in Python

```python
import scipy.io

raw = scipy.io.loadmat('mydata.mat', squeeze_me=True, struct_as_record=False)
info = raw['info']
print(info.sz)           # [lines_per_frame, pixels_per_line]
print(info.channels)     # PMT bitmask
print(info.config.magnification_list)
```

### Reading the `.mat` file in MATLAB

```matlab
load('mydata.mat');      % loads the 'info' struct
disp(info.sz)
disp(info.channels)
```

---

Back to [Table of Contents](index.md).

