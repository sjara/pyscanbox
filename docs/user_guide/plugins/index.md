# Plugins

Plugins extend pyscanbox with auxiliary capabilities that run alongside the main acquisition loop. Each plugin connects to external hardware or software systems and integrates with the acquisition lifecycle.

## Enabling Plugins

Plugins are configured in `config.yaml` under the `plugins:` section. Each plugin entry specifies its module, class, connection parameters, and whether to auto-connect at startup.

To enable a plugin at startup, set `enabled: true` in the config:

```yaml
plugins:
  frame_streamer:
    enabled: true
    host: 127.0.0.1
    port: 5555
```

You can also enable or disable any plugin at runtime via the **Plugins** menu — no restart required. Note that connection parameters (host, port, serial port) must be set in the config file before pyscanbox starts; they cannot be changed from the menu.

## Available Plugins

### ZeroMQ plugins

These plugins communicate with external processes over the network using [ZeroMQ](https://zeromq.org/).

| Plugin | Config key | Description |
|---|---|---|
| [Frame Streamer](frame_streamer.md) | `frame_streamer` | Streams live imaging frames over ZeroMQ |
| [Position Streamer](position_streamer.md) | `position_streamer` | Streams objective position over ZeroMQ |
| [Remote Control](remote_control.md) | `remote_control` | Accepts acquisition commands from external scripts |

### Hardware plugins

These plugins interface with physical hardware connected to the PC.

| Plugin | Config key | Description |
|---|---|---|
| [Quadrature Encoder](quadrature.md) | `quadrature` | Records running wheel / platform rotation via Arduino serial |

## Performance Impact on Acquisition

The acquisition loop runs on a dedicated thread and must sustain ~500 MB/s throughput from the Alazar digitizer. Plugin hooks that execute on this thread add latency to every frame; hooks that run on other threads have no effect on imaging.

| Plugin | Runs on acquisition thread | Impact |
|---|---|---|
| [Remote Control](remote_control.md#performance) | No | None |
| [Position Streamer](position_streamer.md#performance) | No | None |
| [Frame Streamer](frame_streamer.md#performance) | Yes (`on_frame_data`) | Small |
| [Quadrature Encoder](quadrature.md#performance) | Yes (`on_frame`) | Small |

See each plugin's documentation for details.

---

Back to [Table of Contents](../index.md).
