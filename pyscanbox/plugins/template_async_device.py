# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Template: high-rate device with PC-clock alignment (Strategy 3).

Copy this file and adapt it for any device that runs faster than the frame
rate and cannot use a TTL input.

The device thread samples at its own rate and timestamps every value with
time.perf_counter().  Each frame callback records a (frame_index,
perf_counter()) anchor pair.  Post-processing interpolates device timestamps
against the anchor sequence to assign a frame.fractional_line to every sample.

Accuracy: ~1–5 ms PC-clock jitter under typical loads.  Always save both the
raw device timestamps and the frame anchor pairs so the alignment can be
audited or re-done in post-processing.

sync_mode is auto-inferred as ['per_frame'] because on_frame is overridden.
To additionally document the async nature, override sync_mode as shown below
(optional — it has no effect on dispatch).
"""

from __future__ import annotations

import threading
import time

import numpy as np

import pyscanbox.acquisition.plugin as plugin_module


class AsyncDevicePlugin(plugin_module.AcquisitionPlugin):
    """Template: high-rate device sampled on a background thread.

    The device thread runs at its own rate.  Frame callbacks record
    (frame_index, perf_counter) anchors.  Post-processing uses these
    anchors to assign fractional frame indices to device samples.

    Attributes:
        name: Plugin identifier used to name companion data files.
    """

    name = 'async_device'

    # Optional: override sync_mode to document the async strategy.
    # Not required for correct behaviour — remove if not needed.
    @property
    def sync_mode(self) -> list[str]:
        """Return sync modes, including the async label.

        Returns:
            List containing 'per_frame' and 'async'.
        """
        return super().sync_mode + ['async']

    def __init__(self, device, output_path: str, sample_rate_hz: float):
        """Initialise the plugin.

        Args:
            device: Device object with a read() method.
            output_path: Full path for the output .npz file.
            sample_rate_hz: Device sampling rate in Hz.
        """
        self._device = device
        self._output_path = output_path
        self._sample_rate = sample_rate_hz
        self._device_samples: list[tuple[float, float]] = []  # (t, value)
        self._frame_anchors: list[tuple[int, float]] = []     # (frame, t)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def on_acquisition_start(self, n_frames: int, frame_rate: float) -> None:
        """Start the background sampling thread.

        Args:
            n_frames: Total frames to acquire (0 in continuous mode).
            frame_rate: Estimated frame rate in Hz.
        """
        self._device_samples.clear()
        self._frame_anchors.clear()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._sample_loop, daemon=True
        )
        self._thread.start()

    def _sample_loop(self) -> None:
        interval = 1.0 / self._sample_rate
        while not self._stop_event.is_set():
            t = time.perf_counter()
            value = self._device.read()
            self._device_samples.append((t, value))
            time.sleep(interval)

    def on_frame(self, frame_index: int) -> None:
        """Record a (frame, PC-clock) anchor.

        Called as close to buffer-complete as possible so anchors accurately
        represent when each frame finished acquisition.

        Args:
            frame_index: 0-based index of the just-completed frame.
        """
        self._frame_anchors.append((frame_index, time.perf_counter()))

    def on_acquisition_stop(self, n_frames: int) -> None:
        """Stop the sampling thread and save all data.

        Args:
            n_frames: Actual number of frames acquired.
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        np.savez(
            self._output_path,
            device_times=np.array([s[0] for s in self._device_samples]),
            device_values=np.array([s[1] for s in self._device_samples]),
            anchor_frames=np.array([a[0] for a in self._frame_anchors]),
            anchor_times=np.array([a[1] for a in self._frame_anchors]),
        )
