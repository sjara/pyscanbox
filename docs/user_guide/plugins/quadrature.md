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

## Calibration

The calibration factor converts raw encoder counts to arc length (cm/count):

```
calibration = (2 × π × radius_cm) / pulses_per_revolution
```

| Setup | Radius | Pulses/rev | calibration (cm/count) |
|---|---|---|---|
| large | 10 cm | 1440 | 0.04363 |
| small | 7 cm | 2048 | 0.02150 |

Use the formula above to compute the correct value for your encoder and wheel.

## Output Data

During a **Grab** acquisition the plugin saves a NumPy array alongside the `.sbx` file:

```
<basename>_quadrature.npy    # int32, shape (n_frames-1,)
```

The array contains raw encoder counts. To convert to arc length or angle in post-processing:

```python
import numpy as np

quad = np.load('mouse01_000_001_quadrature.npy')   # int32 counts
calibration = 0.04363323   # cm/count — copy from your config

arc_cm = quad * calibration
angle_rad = arc_cm / radius_cm   # if you need angle
```

No data is saved during **Focus** mode.

Calibration metadata (calibration factor, output file path) is also written to the `.mat` sidecar file so post-processing scripts can read it without consulting the config.

## Timing

The plugin samples at the imaging frame rate (one count per frame). Element `[k]` of the saved array corresponds to frame `k`. Because the first poll fires before the frame-0 response is available, the array has `n_frames − 1` elements.

To convert frame index to time: `t[k] = k / frame_rate`.

## Performance

`on_frame` runs on the acquisition thread once per frame. Per call it performs one `serial.write(1 byte)` and one `serial.read(4 bytes)`. The non-blocking poll pattern (command sent before the Alazar buffer wait, response read after) gives the Arduino the full inter-frame interval (~33 ms at 30 fps) to prepare its reply. Under normal conditions the 4 bytes are already in the UART receive buffer when `read_count()` is called, so the read returns in microseconds.

The main risk is **Windows USB serial latency**. USB CDC drivers on Windows introduce up to 16 ms of latency per transaction by default, which is within the 33 ms frame budget but leaves little margin. If the Arduino fails to respond in time and the 0.1 s timeout fires, the sample for that frame is lost and an error is logged — acquisition itself continues.

To reduce latency: in Device Manager, find the Arduino COM port under Ports (COM & LPT), open Properties → Port Settings → Advanced, and set the **Latency Timer** to **1 ms** (default is 16 ms).

---

Back to [Plugins](index.md) | [Table of Contents](../index.md).
