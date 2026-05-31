# Position Streamer Plugin

The **Position Streamer** plugin publishes objective position updates over a [ZeroMQ](https://zeromq.org/) PUB socket approximately every 50 ms. Subscribers receive world-frame and rotated-frame coordinates in real time, independently of whether an acquisition is running.

## Configuration

```yaml
plugins:
  position_streamer:
    enabled: false          # Set true to auto-connect at startup
    host: 127.0.0.1         # IP address to bind to; use 0.0.0.0 to publish on the network
    port: 5556              # Port for the PUB socket
```

Enable the plugin via the **Plugins > Position Streamer** menu or by setting `enabled: true` in the config. Position updates are broadcast continuously as long as the plugin is enabled — no acquisition needs to be running.

## Message Format

Each update is a single JSON message:

```json
{
    "timestamp": 1748649600.123,
    "x":      150.0,
    "y":     -320.5,
    "z":       42.0,
    "angle":    0.0,
    "x_rot":  150.0,
    "y_rot":  -320.5,
    "z_rot":   42.0,
    "abs_x": 1234.0,
    "abs_y": 5678.0,
    "abs_z":  910.0
}
```

| Field | Unit | Description |
|---|---|---|
| `timestamp` | s | Unix timestamp (seconds since epoch) |
| `x`, `y`, `z` | μm | World-frame position (Knobby displacement from origin) |
| `angle` | degrees | Objective tilt angle (Knobby displacement) |
| `x_rot`, `y_rot`, `z_rot` | μm | Rotated-frame coordinates aligned with the objective axis |
| `abs_x`, `abs_y`, `abs_z` | μm | Absolute motor positions (updates as motor settles) |

**Knobby displacement** values (`x`, `y`, `z`, `angle`) update immediately when a move is commanded. **Absolute motor** values (`abs_x`, `abs_y`, `abs_z`) reflect actual hardware position and lag slightly while the motor is moving.

## Subscribing in Python

```python
import zmq

ctx = zmq.Context()
sock = ctx.socket(zmq.SUB)
sock.connect("tcp://127.0.0.1:5556")
sock.setsockopt_string(zmq.SUBSCRIBE, "")

while True:
    pos = sock.recv_json()
    print(f"x={pos['x']:8.2f}  y={pos['y']:8.2f}  z={pos['z']:8.2f}  (μm)")
```

See also `examples/example_position_subscriber.py` for a complete working example.

## Performance

This plugin has no impact on acquisition. Position updates are published on the Qt main thread (~50 ms timer), completely independent of the acquisition loop.

---

Back to [Plugins](index.md) | [Table of Contents](../index.md).
