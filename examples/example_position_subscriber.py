# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Example: receive and display live objective position from the Position Streamer plugin.

Before running this script:
  1. Set the host and port in your pyscanbox config (parameters must be
     configured before starting pyscanbox):
       plugins:
         position_streamer:
           host: 127.0.0.1   # use 0.0.0.0 to publish to the network
           port: 5556
  2. Enable the plugin — either set enabled: true in the config for
     automatic startup, or toggle it on via Plugins > Position Streamer
     in the pyscanbox menu after launch.
  3. Start pyscanbox (acquisition does not need to be running).
  4. Run this script:
       python example_position_subscriber.py
"""

import zmq

context = zmq.Context()
socket = context.socket(zmq.SUB)

# Connect to the publisher
# This must match the position_streamer config host/port (default 127.0.0.1:5556)
address = "tcp://127.0.0.1:5556"
socket.connect(address)

# Subscribe to everything
socket.setsockopt_string(zmq.SUBSCRIBE, "")

print(f"Subscribed to {address}. Waiting for position updates...")

try:
    while True:
        pos = socket.recv_json()
        # print(pos)
        print(
            f"  world  x={pos['x']:8.2f}  y={pos['y']:8.2f}  z={pos['z']:8.2f}  angle={pos['angle']:6.2f}°"
            f"    rotated  x={pos['x_rot']:8.2f}  y={pos['y_rot']:8.2f}  z={pos['z_rot']:8.2f}"
            f"    abs  x={pos['abs_x']:8.2f}  y={pos['abs_y']:8.2f}  z={pos['abs_z']:8.2f}  (μm)"
        )
except KeyboardInterrupt:
    print("\nStopping subscriber.")
finally:
    socket.close()
    context.term()

