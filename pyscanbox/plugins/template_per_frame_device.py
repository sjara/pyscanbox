"""Template: continuously streaming device polled once per frame (Strategy 2).

Copy this file and adapt it for any device where one sample per imaging frame
(~33 ms at 30 fps) is sufficient resolution and no TTL input is available.

For serial devices, use the non-blocking poll pattern to overlap the serial
round-trip with the Alazar buffer wait:
  1. Send the request byte BEFORE the Alazar wait  (call poll() at the top of
     on_frame(), before the buffer completes).
  2. Read the response AFTER the buffer completes  (call read_response() at
     the bottom of on_frame(), or at the top of the next on_frame() call).
See QuadraturePlugin in quadrature.py for a concrete example of this pattern.

sync_mode is auto-inferred as ['per_frame'] because on_frame is overridden.
"""

from __future__ import annotations

import pyscanbox.acquisition.plugin as plugin_module


class PerFrameDevicePlugin(plugin_module.AcquisitionPlugin):
    """Template: continuously streaming device polled once per frame.

    One value is sampled per imaging frame (~33 ms at 30 fps).  No TTL input
    is required.

    Attributes:
        name: Plugin identifier used to name companion data files.
    """

    name = 'per_frame_device'

    def on_acquisition_start(self, n_frames: int, frame_rate: float) -> None:
        """Initialise the data buffer.

        Args:
            n_frames: Total frames to acquire (0 in continuous mode).
            frame_rate: Estimated frame rate in Hz.
        """
        self._data: list = []

    def on_frame(self, frame_index: int) -> None:
        """Poll device and/or read response; append one value to the buffer.

        Args:
            frame_index: 0-based index of the just-completed frame.
        """
        # TODO: poll device and/or read previous response; append to self._data
        pass

    def on_acquisition_stop(self, n_frames: int) -> None:
        """Save the data buffer.

        Args:
            n_frames: Actual number of frames acquired.
        """
        # TODO: save self._data to disk
        pass
