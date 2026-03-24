# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Quadrature encoder hardware driver and acquisition plugin.

This module contains two classes:

    QuadratureEncoder  — hardware driver for the Arduino-based encoder reader.
    QuadraturePlugin   — AcquisitionPlugin that records one count per frame
                         using the non-blocking poll pattern (Strategy 2).

Protocol (strictly binary — no text framing):

    PC → Arduino:   1 command byte
    0x00  →  Arduino replies: int32, 4 bytes, little-endian (current count)
    0x01  →  no reply  (zero the counter)
    0x02  →  no reply  (DUE only: lamp OFF)
    0x03  →  no reply  (DUE only: lamp ON)

Non-blocking poll pattern (matches original scanbox.m acquisition loop):
    1. poll()       — send 0x00 BEFORE the Alazar buffer wait.
    2. <Alazar buffer completes — Arduino has the whole frame period to reply>
    3. read_count() — read the 4-byte response AFTER the buffer completes.

Reference:
    Original MATLAB:  sb/sb_quad.m, core/scanbox.m
    Specification:    devel/specifications/quadrature_encoder.md
    Plugin spec:      devel/specifications/plugin_system.md
"""

from __future__ import annotations

import struct

import numpy as np

import pyscanbox.acquisition.plugin as plugin_module

# Serial command bytes
_CMD_REQUEST_COUNT = b'\x00'  # Request current count; 4-byte int32 response
_CMD_ZERO_COUNTER = b'\x01'   # Zero the counter; no response
_CMD_LAMP_OFF = b'\x02'       # (DUE only) turn lamp off; no response
_CMD_LAMP_ON = b'\x03'        # (DUE only) turn lamp on; no response

# Bytes in the count response packet
_COUNT_RESPONSE_BYTES = 4


def _get_serial_module(use_emulation: bool):
    """Return the appropriate serial module.

    Args:
        use_emulation: If True, return the mock_serial module for
            offline/Linux development.

    Returns:
        Module providing a Serial class.
    """
    if use_emulation:
        from pyscanbox.emulator import mock_serial
        return mock_serial
    import serial
    return serial


class QuadratureEncoder:
    """Interface for the Arduino-based quadrature encoder reader.

    Communicates over a dedicated serial port, completely independent of the
    PSoC5 Scanbox controller.  Supports both Arduino DUE (default, 115200
    baud) and Arduino Mega (1,000,000 baud) firmware variants.

    Attributes:
        port: Serial port name (e.g. 'COM8' or '/dev/ttyACM0').
        baud_rate: Baud rate for serial communication.
        calibration: Arc length per encoder count in cm/count.
    """

    # Default calibration: r=10 cm platform, 1440 pulses/rev (Scanbox default).
    # calibration = 2 * pi * radius_cm / pulses_per_revolution
    DEFAULT_CALIBRATION = 20 * np.pi / 1440  # ~0.04363 cm/count

    # Guard timeout for read_count().  The non-blocking poll pattern gives the
    # Arduino the full inter-frame interval (~33 ms at 30 fps) to prepare the
    # reply; 0.1 s is a generous but safe limit.
    _READ_TIMEOUT = 0.1

    def __init__(self, config: dict):
        """Initialise the encoder with configuration.

        Args:
            config: Configuration dictionary with keys:
                port        (str)   Serial port, e.g. 'COM8'.  Default 'COM8'.
                baud_rate   (int)   Baud rate.  Default 115200 (DUE firmware).
                calibration (float) cm/count.  Default DEFAULT_CALIBRATION.
                emulation   (bool)  Use mock serial.  Default False.
        """
        self.port = config.get('port', 'COM8')
        self.baud_rate = config.get('baud_rate', 115200)
        self.calibration = config.get('calibration', self.DEFAULT_CALIBRATION)
        self._use_emulation = config.get('emulation', False)
        self._serial = None

    def open(self) -> None:
        """Open the serial connection to the Arduino."""
        serial_module = _get_serial_module(self._use_emulation)
        self._serial = serial_module.Serial(
            port=self.port,
            baudrate=self.baud_rate,
            timeout=self._READ_TIMEOUT,
        )

    def close(self) -> None:
        """Close the serial connection."""
        if self._serial is not None and self._serial.is_open:
            self._serial.close()
        self._serial = None

    def poll(self) -> None:
        """Send the count-request byte without reading the response.

        Call this BEFORE waiting on the next Alazar buffer to overlap the
        serial round-trip with the buffer wait interval.
        """
        self._serial.write(_CMD_REQUEST_COUNT)

    def read_count(self) -> int:
        """Read the 4-byte int32 response from a preceding poll().

        Call this AFTER the Alazar buffer has completed.

        Returns:
            Accumulated encoder count (positive = clockwise, negative =
            counter-clockwise, depending on encoder wiring).

        Raises:
            IOError: If fewer than 4 bytes are received (timeout or
                disconnect).
        """
        raw = self._serial.read(_COUNT_RESPONSE_BYTES)
        if len(raw) < _COUNT_RESPONSE_BYTES:
            raise IOError(
                f'QuadratureEncoder: expected {_COUNT_RESPONSE_BYTES} bytes, '
                f'got {len(raw)} (port={self.port})'
            )
        (count,) = struct.unpack('<i', raw)
        return count

    def reset_count(self) -> None:
        """Zero the encoder counter on the Arduino (sends command 0x01)."""
        self._serial.write(_CMD_ZERO_COUNTER)

    def set_calibration(self, cm_per_count: float) -> None:
        """Update the calibration factor.

        Args:
            cm_per_count: Arc length per encoder count in centimetres.
                Computed as ``(2 * pi * radius_cm) / pulses_per_revolution``.
        """
        self.calibration = cm_per_count


class QuadraturePlugin(plugin_module.AcquisitionPlugin):
    """Per-frame quadrature encoder recording (Strategy 2).

    One signed int32 count is stored per imaging frame, matching the original
    Scanbox behaviour.  The non-blocking poll pattern is used: poll() is sent
    at the start of on_frame() so the Arduino has the entire inter-frame
    interval (~33 ms at 30 fps) to prepare the response; the response from the
    previous frame's poll is then read and stored.

    Frame alignment note
    --------------------
    Because the read lags the poll by one frame, the saved array contains
    ``n_frames - 1`` elements.  Element [k] is the count sampled at frame k
    (polled during frame k, read during frame k+1).

    Output
    ------
    The raw count array is saved as a .npy file alongside the .sbx file.
    Multiply by ``encoder.calibration`` (cm/count) to convert to arc length.

    Attributes:
        name: Plugin identifier; used to name the companion data file.
    """

    name = 'quadrature'

    def __init__(self, encoder: QuadratureEncoder, output_path: str = ''):
        """Initialise the plugin.

        Args:
            encoder: QuadratureEncoder instance (not yet open; open() will
                call encoder.open() in a background thread).
            output_path: Optional initial output path.  Normally left empty
                here and set via the output_path argument of
                on_acquisition_start() when an acquisition begins.
        """
        self._encoder = encoder
        self._output_path = output_path
        self._data: list[int] = []

    def open(self) -> None:
        """Open the serial connection to the Arduino encoder."""
        self._encoder.open()

    def close(self) -> None:
        """Close the serial connection to the Arduino encoder."""
        self._encoder.close()

    def on_acquisition_start(
        self,
        n_frames: int,
        frame_rate: float,
        output_path: str = '',
    ) -> None:
        """Reset the count buffer, set the output path, and zero the counter.

        Args:
            n_frames: Total frames to acquire (0 in continuous mode).
            frame_rate: Estimated frame rate in Hz.
            output_path: Base path for output files.  The companion .npy
                file is saved as ``output_path + '_quadrature.npy'``.
                Ignored in focus mode (empty string).
        """
        self._data = []
        if output_path:
            self._output_path = output_path + '_quadrature.npy'
        self._encoder.reset_count()

    def on_frame(self, frame_index: int) -> None:
        """Send next poll and read the response from the previous poll.

        On frame 0 there is no prior response to read; only the poll is sent.

        Args:
            frame_index: 0-based index of the just-completed frame.
        """
        self._encoder.poll()
        if frame_index > 0:
            count = self._encoder.read_count()
            self._data.append(count)

    def on_acquisition_stop(self, n_frames: int) -> None:
        """Save the count array to disk.

        Args:
            n_frames: Actual number of frames acquired.
        """
        arr = np.asarray(self._data, dtype=np.int32)
        np.save(self._output_path, arr)

    def get_metadata(self) -> dict:
        """Return quadrature encoder metadata for the .mat sidecar.

        Returns:
            Dictionary with calibration factor, output file path, and
            enabled flag.
        """
        return {
            'quadrature_enabled': True,
            'quadrature_calibration_cm_per_count': self._encoder.calibration,
            'quadrature_file': self._output_path,
        }
