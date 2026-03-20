"""Template: sparse-event device using TTL edge timestamping (Strategy 1).

Copy this file and adapt it for any device that asserts a TTL output pulse on
each event of interest (lick onset, stimulus onset, trial start/stop, etc.).

The PSoC firmware records the frame+line at which the rising edge arrived
(~125 µs accuracy).  Not suitable for high-rate continuous devices; every
event consumes one entry in the PSoC TTL event buffer.

sync_mode is auto-inferred as ['ttl'] because on_ttl_event is overridden.
"""

from __future__ import annotations

import pyscanbox.acquisition.plugin as plugin_module


class TtlDevicePlugin(plugin_module.AcquisitionPlugin):
    """Template: sparse-event device using TTL edge timestamping.

    The device asserts a TTL pulse on each event.  The PSoC records the
    frame+line number at which the rising edge arrived (~125 µs accuracy).

    Use for: lick onset, stimulus onset, trial start/stop.

    Attributes:
        name: Plugin identifier used to name companion data files.
    """

    name = 'ttl_device'

    def on_acquisition_start(self, n_frames: int, frame_rate: float) -> None:
        """Initialise the event list.

        Args:
            n_frames: Total frames to acquire (0 in continuous mode).
            frame_rate: Estimated frame rate in Hz.
        """
        self._events: list[tuple[int, int, int]] = []  # (frame, line, event_id)

    def on_ttl_event(self, frame: int, line: int, event_id: int) -> None:
        """Record a TTL edge timestamp.

        Args:
            frame: Frame index at which the edge was detected.
            line: Scan line within that frame (0 <= line < lines_per_frame).
            event_id: 1 = TTL0, 2 = TTL1, 3 = both.
        """
        self._events.append((frame, line, event_id))

    def on_acquisition_stop(self, n_frames: int) -> None:
        """Save the event list.

        Args:
            n_frames: Actual number of frames acquired.
        """
        # TODO: save self._events to disk
        pass
