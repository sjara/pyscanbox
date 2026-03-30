# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

from __future__ import annotations
import logging
import zmq
import numpy as np
from pyscanbox.acquisition.plugin import AcquisitionPlugin

logger = logging.getLogger(__name__)

class ZmqStreamerPlugin(AcquisitionPlugin):
    """Streams real-time imaging data over a ZeroMQ PUB socket.

    Follows the publisher/subscriber pattern to allow external applications
    to subscribe to the data stream without blocking the main acquisition thread.
    Multi-part message: JSON header + numpy array.
    """

    name = 'zmq_streamer'

    def __init__(self, config: dict):
        self._address = f"tcp://{config.get('host', '127.0.0.1')}:{config.get('port', 5555)}"
        self._context: zmq.Context | None = None
        self._socket: zmq.Socket | None = None

    def open(self) -> None:
        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.PUB)
        # Set High Water Mark to prevent memory bloat if subscribers are slow
        self._socket.set(zmq.SNDHWM, 2)
        self._socket.bind(self._address)
        logger.info("ZmqStreamerPlugin streaming on %s", self._address)

    def close(self) -> None:
        if self._socket:
            self._socket.close()
            self._socket = None
        if self._context:
            self._context.term()
            self._context = None
        logger.info("ZmqStreamerPlugin closed")

    def on_acquisition_start(self, n_frames: int, frame_rate: float, output_path: str = '') -> None:
        pass

    def on_frame_data(self, frame_index: int, frame_data: np.ndarray) -> None:
        if self._socket is None:
            return

        md = {
            'frame_index': frame_index,
            'dtype': str(frame_data.dtype),
            'shape': frame_data.shape
        }
        
        try:
            # Zero-copy send multi-part: JSON header, then array buffer
            self._socket.send_json(md, zmq.SNDMORE)
            self._socket.send(frame_data, copy=False)
        except Exception as e:
            # Swallow exceptions to not crash the imaging loop
            logger.error("ZmqStreamerPlugin send error: %s", e)

    def on_acquisition_stop(self, n_frames: int) -> None:
        pass
