# Frame Streamer Plugin

The **Frame Streamer** plugin publishes live imaging frames over a [ZeroMQ](https://zeromq.org/) PUB socket as they are acquired. Any number of external applications can subscribe and receive frames in real time without affecting acquisition performance.

## Configuration

```yaml
plugins:
  frame_streamer:
    enabled: false          # Set true to auto-connect at startup
    host: 127.0.0.1         # IP address to bind to; use 0.0.0.0 to publish on the network
    port: 5555              # Port for the PUB socket
```

Enable the plugin via the **Plugins > Frame Streamer** menu or by setting `enabled: true` in the config. The plugin publishes frames during both **Focus** and **Grab** acquisitions.

## Message Format

Each frame is sent as a two-part ZeroMQ message:

1. **Header** (JSON): frame metadata.
2. **Payload** (binary): raw `uint16` pixel data in row-major order.

```json
{"frame_index": 42, "dtype": "uint16", "shape": [512, 796, 2]}
```

| Header field | Type | Description |
|---|---|---|
| `frame_index` | int | Cumulative frame counter since acquisition started |
| `dtype` | str | NumPy dtype string (always `"uint16"`) |
| `shape` | list | Array dimensions: `[lines, pixels, channels]` |

> **Note:** Pixel values are in *wire format* (higher value = darker signal), matching the raw digitizer output. Invert to restore the standard signal convention: `frame_signal = np.uint16(65535) - frame_data`.

## Subscribing in Python

```python
import zmq
import numpy as np

ctx = zmq.Context()
sock = ctx.socket(zmq.SUB)
sock.connect("tcp://127.0.0.1:5555")
sock.setsockopt_string(zmq.SUBSCRIBE, "")

while True:
    header = sock.recv_json()
    payload = sock.recv(copy=False)
    frame = np.frombuffer(payload, dtype=header['dtype']).reshape(header['shape'])
    frame_signal = np.uint16(65535) - frame   # invert wire format
    print(f"Frame {header['frame_index']}: mean={frame_signal.mean():.1f}")
```

See also `examples/example_frame_subscriber.py` for a complete working example.

---

Back to [Plugins](index.md) | [Table of Contents](../index.md).
