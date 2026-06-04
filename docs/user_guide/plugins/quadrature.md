# Quadrature Encoder Plugin

The **Quadrature Encoder** plugin records running wheel or rotating platform position during acquisition. It communicates with a dedicated **Arduino** (DUE or Mega) over serial, completely independently of the main Scanbox hardware. One encoder count is saved per imaging frame, matching the original Scanbox behavior.

## Hardware Setup

You will need:

- A quadrature encoder mounted on your running wheel or rotating platform.
- An **Arduino DUE** (recommended) or **Arduino Mega** connected to the PC via USB.
- The appropriate firmware uploaded to the Arduino — see [Quadrature Encoder Protocol](../../hardware_protocols/quadrature_encoder.md) for installation instructions.

## Configuration

```yaml
plugins:
  quadrature:
    enabled: false
    port: 'COM8'              # Serial port of the Arduino
    baud_rate: 115200         # 115200 for DUE, 1000000 for Mega
    timeout: 1.0
    calibration: 0.04363323  # cm/count; see Calibration section below
```

Enable the plugin via the **Plugins > Quadrature** menu or by setting `enabled: true` in the config. The serial port and baud rate must be configured before pyscanbox starts.

## Output Data

During a **Grab** acquisition the plugin saves a NumPy array alongside the `.sbx` file:

```
<basename>_quadrature.npy    # int32, shape (n_samples, 2)
```

Column 0 is the frame index; column 1 is the **raw encoder count** (a dimensionless integer). Under normal conditions `n_samples == n_frames`. If a USB latency timeout causes a sample to be dropped, that frame's row is simply absent — detectable by inspecting gaps in column 0.

No data is saved during **Focus** mode.

Calibration metadata (calibration factor, output file path) is also written to the `.mat` sidecar file so post-processing scripts can read it without consulting the config.

## Calibration

The raw counts saved in the `.npy` file must be multiplied by a calibration factor to obtain physical units. The factor has units of cm/count and is set in the config:

```yaml
calibration: 0.04363323  # cm/count
```

Compute it from your wheel geometry:

```
calibration = (2 × π × radius_cm) / pulses_per_revolution
```

| Setup | Radius | Pulses/rev | calibration (cm/count) |
|---|---|---|---|
| large | 10 cm | 1440 | 0.04363 |
| small | 7 cm | 2048 | 0.02150 |

To convert the saved data to arc length or angle in post-processing:

```python
import numpy as np

quad = np.load('mouse01_000_001_quadrature.npy')   # int32, shape (n_frames, 2)
frame_indices = quad[:, 0]
counts        = quad[:, 1]

calibration = 0.04363323   # cm/count — copy from your config
arc_cm    = counts * calibration
angle_rad = arc_cm / radius_cm   # if you need angle
```

## Timing

The plugin samples at the imaging frame rate (one count per frame). Row `[k]` of the saved array has `[frame_index, count]` for that sample. The frame index in column 0 is the ground truth for timing — use it rather than the row number when samples may be dropped.

To convert frame index to time: `t = frame_indices / frame_rate`.

## Performance

`on_frame` runs on the acquisition thread once per frame. Per call it performs one `serial.write(1 byte)` and one `serial.read(4 bytes)`. The non-blocking poll pattern (command sent before the Alazar buffer wait, response read after) gives the Arduino the full inter-frame interval (~33 ms at 30 fps) to prepare its reply. Under normal conditions the 4 bytes are already in the UART receive buffer when `read_count()` is called, so the read returns in microseconds.

The main risk is **Windows USB serial latency**. USB CDC drivers on Windows introduce up to 16 ms of latency per transaction by default, which is within the 33 ms frame budget but leaves little margin. If the Arduino fails to respond in time and the 0.1 s timeout fires, the sample for that frame is lost and an error is logged — acquisition itself continues.

To reduce latency: in Device Manager, find the Arduino COM port under Ports (COM & LPT), open Properties → Port Settings → Advanced, and set the **Latency Timer** to **1 ms** (default is 16 ms).

---

Back to [Plugins](index.md) | [Table of Contents](../index.md).
