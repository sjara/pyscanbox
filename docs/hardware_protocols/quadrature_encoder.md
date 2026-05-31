# Quadrature Encoder Protocol

The quadrature encoder system reads a rotary encoder (typically mounted on a running wheel or rotating platform) through a dedicated Arduino (DUE or Mega). The Arduino decodes the two-phase signals and reports an accumulated count over serial.

The encoder is **completely independent of the PSoC5 Scanbox controller** — it uses its own serial port and can be opened before or after the main hardware.

---

## Arduino Firmware Installation

The firmware sketches live in the Scanbox MATLAB repository under `Scanbox/quad/`:

| Sketch | Board | Baud rate | Notes |
|---|---|---|---|
| `quad_encoder/quad_encoder.ino` | Arduino DUE | 115,200 | Lamp control (0x02/0x03); listens on both `Serial` and `SerialUSB` |
| `quad_encoder_mega/quad_encoder_mega.ino` | Arduino Mega | 1,000,000 | Higher baud rate for faster polling |

**To upload firmware:**

1. Open Arduino IDE and install the **Encoder** library (Sketch → Include Library → Manage Libraries → search "Encoder" by Paul Stoffregen).
2. Open the appropriate `.ino` sketch for your board.
3. Select the correct board and port (Tools → Board / Port).
4. Click **Upload**.

Both variants use the Encoder library on pins 8/9 (DUE) or 2/3 (Mega).

---

## Serial Protocol

**Protocol is strictly binary — no text framing.**

| Command byte | Action | Response |
|---|---|---|
| `0x00` | Request current count | 4 bytes, signed `int32`, little-endian |
| `0x01` | Zero the counter | *(none)* |
| `0x02` | Lamp OFF (DUE only) | *(none)* |
| `0x03` | Lamp ON (DUE only) | *(none)* |

### Non-blocking poll pattern

To avoid adding serial latency to the imaging loop, the command byte is sent *before* waiting on the Alazar buffer, and the response is read *after* the buffer completes:

```
quad_poll()            ← send 0x00 (fire-and-forget)
↓
wait for Alazar buffer...
↓
count = quad_get()     ← read 4-byte int32 response
```

By the time the Alazar buffer is ready (~33 ms at 30 fps), the Arduino response has almost certainly arrived in the UART receive buffer. This matches the original `scanbox.m` acquisition loop.

---

## Calibration

The calibration factor converts encoder counts to arc length (cm/count):

```
calibration = (2 × π × radius_cm) / pulses_per_revolution
```

| Setup | Radius | PPR | calibration (cm/count) |
|---|---|---|---|
| Scanbox default | 10 cm | 1440 | 0.04363 |
| Jaralab | 7 cm | 2048 | 0.02150 |

Post-processing: `arc_cm = quad_data × calibration`

---

## Configuration

```yaml
plugins:
  quadrature:
    enabled: false
    port: 'COM8'
    baud_rate: 115200        # 115200 for DUE, 1000000 for Mega
    timeout: 1.0
    calibration: 0.04363323  # cm/count; see table above
```

---

## Output Data

During a Grab acquisition the plugin records one count per frame (n_frames − 1 samples, since the first poll fires before frame 0 is complete). The array is saved as:

```
<basename>_quadrature.npy    # int32, shape (n_frames-1,)
```

Calibration metadata (calibration factor, baud rate, port) is written to the `.mat` sidecar.

---

## References

- **Python implementation:** `pyscanbox/plugins/quadrature.py`
- **Arduino firmware (DUE):** `Scanbox/quad/quad_encoder/quad_encoder.ino`
- **Arduino firmware (Mega):** `Scanbox/quad/quad_encoder_mega/quad_encoder_mega.ino`
- **User guide:** `docs/user_guide/plugins/quadrature.md` *(to be added)*
