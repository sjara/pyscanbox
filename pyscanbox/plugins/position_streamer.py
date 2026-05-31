# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

from __future__ import annotations
import logging
import time
import zmq
from pyscanbox.acquisition.plugin import AcquisitionPlugin
from pyscanbox.utils import coordinate_transform

logger = logging.getLogger(__name__)


class PositionStreamerPlugin(AcquisitionPlugin):
    """Streams objective position (world + rotated frame) over a ZeroMQ PUB socket.

    Publishes a JSON message on every position update (~50 ms) containing world
    XYZ coordinates, the objective tilt angle, and the rotated-frame coordinates
    (aligned with the objective axis).

    Message format::

        {
            "timestamp": <float>,   # seconds since epoch
            "x": <float>,           # world X, Knobby dpos (μm)
            "y": <float>,           # world Y, Knobby dpos (μm)
            "z": <float>,           # world Z, Knobby dpos (μm)
            "angle": <float>,       # objective tilt, Knobby dpos (degrees)
            "x_rot": <float>,       # rotated X (μm)
            "y_rot": <float>,       # rotated Y (μm)
            "z_rot": <float>,       # rotated Z (μm)
            "abs_x": <float>,       # absolute motor X (μm)
            "abs_y": <float>,       # absolute motor Y (μm)
            "abs_z": <float>        # absolute motor Z (μm)
        }

    Knobby dpos values update immediately when a move is commanded.
    Absolute motor values reflect actual hardware position and update as the
    motor settles toward its target, useful for monitoring motion in progress.
    """

    name = 'position_streamer'

    def __init__(self, config: dict):
        self._address = f"tcp://{config.get('host', '127.0.0.1')}:{config.get('port', 5556)}"
        self._context: zmq.Context | None = None
        self._socket: zmq.Socket | None = None

    def open(self) -> None:
        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.PUB)
        self._socket.set(zmq.SNDHWM, 2)
        self._socket.bind(self._address)
        logger.info("PositionStreamerPlugin streaming on %s", self._address)

    def close(self) -> None:
        if self._socket:
            self._socket.close()
            self._socket = None
        if self._context:
            self._context.term()
            self._context = None
        logger.info("PositionStreamerPlugin closed")

    def on_position_updated(self, pos: dict) -> None:
        if self._socket is None:
            return

        x = pos.get('X', 0.0)
        y = pos.get('Y', 0.0)
        z = pos.get('Z', 0.0)
        angle = pos.get('A', 0.0)
        x_rot, y_rot, z_rot = coordinate_transform.world_to_rotated(x, y, z, angle)

        msg = {
            'timestamp': time.time(),
            'x': x,
            'y': y,
            'z': z,
            'angle': angle,
            'x_rot': x_rot,
            'y_rot': y_rot,
            'z_rot': z_rot,
            'abs_x': pos.get('abs_X', 0.0),
            'abs_y': pos.get('abs_Y', 0.0),
            'abs_z': pos.get('abs_Z', 0.0),
        }

        try:
            self._socket.send_json(msg)
        except Exception as e:
            logger.error("PositionStreamerPlugin send error: %s", e)
