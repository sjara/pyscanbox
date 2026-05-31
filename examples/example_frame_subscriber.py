# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Example: receive and display live imaging frames from the Frame Streamer plugin.

Before running this script:
  1. Set the host and port in your pyscanbox config (parameters must be
     configured before starting pyscanbox):
       plugins:
         frame_streamer:
           host: 127.0.0.1   # use 0.0.0.0 to publish to the network
           port: 5555
  2. Enable the plugin — either set enabled: true in the config for
     automatic startup, or toggle it on via Plugins > Frame Streamer in
     the pyscanbox menu after launch.
  3. Start a Focus or Grab acquisition.
  4. Run this script:
       python example_frame_subscriber.py
"""

import zmq
import json
import numpy as np

context = zmq.Context()
socket = context.socket(zmq.SUB)

# Connect to the publisher
# This must match the frame_streamer config host/port (default 127.0.0.1:5555)
address = "tcp://127.0.0.1:5555"
socket.connect(address)

# Subscribe to everything
socket.setsockopt_string(zmq.SUBSCRIBE, "")

print(f"Subscribed to {address}. Waiting for frames...")

try:
    while True:
        # Receive multi-part message (JSON header + numpy array payload)
        # part 1: header
        header_json = socket.recv_json()
        # part 2: array payload
        payload = socket.recv(copy=False)
        
        # Construct a numpy array from the buffer using the metadata
        frame_data = np.frombuffer(payload, dtype=header_json['dtype'])
        frame_data = frame_data.reshape(header_json['shape'])
        
        # The continuous data acquisition loop relies on the zero-copy performance
        # of FrameStreamerPlugin to avoid frame drops. Thus it sends raw "wire-format"
        # values from the digitizer (where higher values = darker).
        # We invert it here on the consumer side to restore standard signal convention:
        frame_signal = np.uint16(65535) - frame_data
        
        frame_idx = header_json.get('frame_index', '?')
        print(f"Received frame {frame_idx}: shape={frame_signal.shape}, dtype={frame_signal.dtype}, "
                f"min={frame_signal.min()}, max={frame_signal.max()}, mean={frame_signal.mean():.2f}")
        
except KeyboardInterrupt:
    print("\nStopping subscriber.")
finally:
    socket.close()
    context.term()

