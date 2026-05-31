# Remote Control Plugin

The **Remote Control** plugin binds a [ZeroMQ](https://zeromq.org/) REP socket and accepts acquisition commands from any local or networked process. This allows external scripts (Python, MATLAB, etc.) to start and stop acquisitions, set file storage fields, and query the acquisition state — fully automating experimental workflows without touching the GUI.

When a remote command is received, the GUI updates exactly as if the user had pressed the corresponding button.

## Configuration

```yaml
plugins:
  remote_control:
    enabled: false          # Set true to auto-connect at startup
    host: 127.0.0.1         # Bind address; use 0.0.0.0 to accept connections from the network
    port: 5558              # Port for the REP socket
```

Enable the plugin via the **Plugins > Remote Control** menu or by setting `enabled: true` in the config.

> **Security note:** There is no authentication. When binding to `0.0.0.0`, any machine on the network can send commands. Use firewall rules or a VPN to restrict access.

## Command Reference

All messages are JSON objects sent over a ZeroMQ REQ/REP socket. Every reply is either `{"ok": true}` on success or `{"ok": false, "error": "<message>"}` on failure.

| Command | Request | Notes |
|---|---|---|
| **focus** | `{"cmd": "focus"}` | Starts focus (live preview) mode |
| **grab** | `{"cmd": "grab"}` or `{"cmd": "grab", "n_frames": 500}` | Starts grab acquisition; uses frame count from `set_n_frames` if `n_frames` is omitted |
| **stop** | `{"cmd": "stop"}` | Stops the running acquisition |
| **status** | `{"cmd": "status"}` | Returns `{"ok": true, "state": "idle"\|"focusing"\|"grabbing"}` |
| **set_n_frames** | `{"cmd": "set_n_frames", "n_frames": 500}` | Sets the default frame count for subsequent `grab` commands |
| **set_file_storage** | `{"cmd": "set_file_storage", "subject": "mouse01", "date": "20260530", "session": "003"}` | Updates file storage fields; all four keys (`directory`, `subject`, `date`, `session`) are optional |

## Python Client

The `RemoteControl` class in `pyscanbox.plugins.remote_control` wraps the protocol for Python callers:

```python
from pyscanbox.plugins.remote_control import RemoteControl

rc = RemoteControl(host='127.0.0.1', port=5558)

rc.status()                                # {'ok': True, 'state': 'idle'}
rc.set_file_storage(subject='mouse01',
                    date='20260530',
                    session='003')
rc.set_n_frames(500)
rc.grab()                                  # starts acquisition
rc.status()                                # {'ok': True, 'state': 'grabbing'}

# Wait for completion by polling:
import time
while rc.status()['state'] != 'idle':
    time.sleep(0.5)

rc.close()
```

If pyscanbox is not running or the plugin is not enabled, any call raises a `ConnectionError` with an explanatory message.

See also `examples/example_remote_control.py` for a complete working example.

## Raw Protocol (MATLAB / other languages)

Any language with a ZeroMQ binding can drive the plugin directly:

**MATLAB example:**
```matlab
ctx = zmq.Context();
sock = ctx.socket('ZMQ_REQ');
sock.connect('tcp://127.0.0.1:5558');
sock.send(jsonencode(struct('cmd', 'grab', 'n_frames', 500)));
reply = jsondecode(sock.recv());
```

## Performance

This plugin has no impact on acquisition. Commands are received in a background ZMQ thread and dispatched on the Qt main thread via a 50 ms timer — the acquisition loop is never touched.

---

Back to [Plugins](index.md) | [Table of Contents](../index.md).
