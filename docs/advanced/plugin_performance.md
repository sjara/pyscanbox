# Plugin Performance Reference

This document explains how plugins interact with the acquisition loop, where their overhead comes from, and how to reason about whether a plugin is safe to enable during imaging.

## Architecture overview

The acquisition loop runs on a dedicated thread (`ScannerThread`) and must sustain ~500 MB/s throughput from the Alazar digitizer. After each frame is reshaped and queued for disk write, the loop calls two plugin dispatch methods synchronously before moving on to the next Alazar buffer:

```
Alazar buffer ready
  → reshape (Numba, fast)
  → write queue (background thread, non-blocking)
  → plugin_manager.on_frame(frame_index)        ← on acquisition thread
  → plugin_manager.on_frame_data(frame_index, reshaped)  ← on acquisition thread
  → next buffer
```

Any time spent inside `on_frame` or `on_frame_data` delays the next buffer re-post. If the delay exceeds one frame interval (~33 ms at 30 fps), the Alazar's onboard FIFO can accumulate frames, and in bidirectional mode this shifts the frame boundary — causing a vertical image flip.

Hooks that are called elsewhere (`on_position_updated` on the Qt main thread; background ZMQ threads) never touch the acquisition loop.

## Per-plugin analysis

### Remote Control

No `on_frame` or `on_frame_data` override. Commands arrive in a dedicated ZMQ background thread and are dispatched on the Qt main thread via a 50 ms `QTimer`. **No acquisition thread overhead.**

### Position Streamer

No `on_frame` or `on_frame_data` override. `on_position_updated` is fired from the Qt main thread on a ~50 ms timer, independent of acquisition state. **No acquisition thread overhead.**

### Frame Streamer

Overrides `on_frame_data`. Per frame:

- Encodes a small JSON header dict (~1 μs).
- Calls `socket.send_json(header, SNDMORE)` — ZMQ kernel copy of ~100 bytes.
- Calls `socket.send(frame_data, copy=False)` — zero-copy: ZMQ borrows the NumPy buffer reference. Each frame creates a fresh reshaped array, so ZMQ holding a reference to the previous frame's buffer does not cause data corruption.

The PUB socket is configured with `SNDHWM=2`. When the send high-water mark is reached (slow or absent subscriber), ZMQ **drops the message silently** rather than blocking — the acquisition thread never waits. Estimated overhead: < 1 ms per frame on localhost.

### Quadrature Encoder

Overrides `on_frame`. Per frame:

1. `serial.write(b'\x00')` — 1 byte; returns in microseconds.
2. `serial.read(4)` — reads the int32 response from the *previous* frame's poll.

The non-blocking poll pattern (send before the Alazar wait, read after) gives the Arduino the full inter-frame interval to respond. Under normal conditions `read(4)` returns immediately from the UART receive buffer.

The risk is **Windows USB serial latency**. The default USB CDC latency timer is 16 ms, which is within the 33 ms frame budget but leaves little margin for jitter. If the response does not arrive within the 0.1 s `serial` timeout, `read_count()` raises `IOError`; the `PluginManager` catches it, logs an error, and continues — acquisition is not aborted, but that frame's encoder sample is lost.

**Recommended mitigation:** in Device Manager → Ports (COM & LPT) → Arduino port → Properties → Port Settings → Advanced, set the **Latency Timer to 1 ms**.

## Overhead when plugins are disabled

`PluginManager` is always present when running from the GUI. With all plugins disabled, `on_frame` and `on_frame_data` are still called each frame, but `_active()` returns an empty list and the loop body never executes. The cost is two Python function calls and two list comprehensions per frame — on the order of a few microseconds at 30 fps, negligible compared to the reshape and I/O work in the same loop.

## Guidelines for new plugins

| Hook | Thread | Latency budget |
|---|---|---|
| `on_frame` | Acquisition | < 5 ms |
| `on_frame_data` | Acquisition | < 5 ms; do not modify the array in place |
| `on_ttl_event` | Acquisition | < 1 ms (may fire many times per frame) |
| `on_acquisition_start` / `on_acquisition_stop` | Acquisition | No hard limit — called once |
| `on_position_updated` | Qt main thread | No limit |

If a plugin needs to do heavy work per frame (e.g., image processing, network transfer of full frames), it should enqueue data to a worker thread in `on_frame_data` and process it there, never blocking the acquisition thread.
