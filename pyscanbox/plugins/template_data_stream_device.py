# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

from __future__ import annotations
import numpy as np
from pyscanbox.acquisition.plugin import AcquisitionPlugin


class DataStreamDevicePlugin(AcquisitionPlugin):
    """Template: streaming device that processes or broadcasts imaging data.

    This plugin implements the `on_frame_data` hook, which provides access to
    the reshaped image data for the most recently completed frame. Because
    this hook runs on the main acquisition thread, the plugin must:
    1. NEVER perform heavy computations inline.
    2. NEVER modify the `frame_data` array.
    3. Return within < 5 ms.

    If heavy processing or network transmission is needed, the plugin should
    enqueue a deep copy of the array (or a serialized view) to a background
    thread/process. Outputting via asynchronous mechanisms (like ZeroMQ PUB)
    is also highly recommended to prevent blocking.
    """

    name = 'data_stream_device'
    # sync_mode auto-inferred as ['frame_data'] because on_frame_data is overridden.

    def open(self) -> None:
        """Initialize communication sockets, file handles, or network connections."""
        pass

    def close(self) -> None:
        """Close connections cleanly."""
        pass

    def on_acquisition_start(self, n_frames: int, frame_rate: float, output_path: str = '') -> None:
        """Prepare for acquisition."""
        pass

    def on_frame_data(self, frame_index: int, frame_data: np.ndarray) -> None:
        """React to newly acquired image data.

        Send this data over a socket or push it into a thread-safe Queue here.
        """
        pass

    def on_acquisition_stop(self, n_frames: int) -> None:
        """Clean up active acquisition tasks if any."""
        pass
