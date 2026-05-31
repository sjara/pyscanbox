# Plugins

Plugins extend pyscanbox with auxiliary capabilities that run alongside the main acquisition loop. Each plugin connects to external hardware or software systems and integrates with the acquisition lifecycle without affecting imaging performance.

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

You can also enable or disable any plugin at runtime via the **Plugins** menu — no restart required. Note that connection parameters (host, port) must be set in the config file before pyscanbox starts; they cannot be changed from the menu.

## Available Plugins

| Plugin | Config key | Description |
|---|---|---|
| [Frame Streamer](frame_streamer.md) | `frame_streamer` | Streams live imaging frames over ZeroMQ |
| [Position Streamer](position_streamer.md) | `position_streamer` | Streams objective position over ZeroMQ |
| [Remote Control](remote_control.md) | `remote_control` | Accepts acquisition commands from external scripts |

---

Back to [Table of Contents](../index.md).
