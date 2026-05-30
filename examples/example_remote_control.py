# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Example: control pyscanbox acquisition remotely via RemoteControl.

Before running this script:
  1. Set the host and port in your pyscanbox config (parameters must be
     configured before starting pyscanbox):
       plugins:
         remote_control:
           host: 127.0.0.1   # use 0.0.0.0 to publish to the network
           port: 5558
  2. Enable the plugin — either set enabled: true in the config for
     automatic startup, or toggle it on via Plugins > Remote Control in
     the pyscanbox menu after launch.
  3. Start pyscanbox (with --emulation for testing without hardware).
  4. Run this script, optionally passing the host:
       python remote_control_example.py
       python remote_control_example.py 192.168.1.5

You can test that the server is running with:  ss -tlnp | grep 5558   
You should see something like:
 LISTEN 0      100        127.0.0.1:5558       0.0.0.0:*    users:(("pyscanbox",pid=736830,fd=25))   
"""

import sys
import time
from pyscanbox.plugins.remote_control import RemoteControl


host = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
port = 5558

print(f"Connecting to pyscanbox at {host}:{port} ...")
rc = RemoteControl(host=host, port=port, timeout_ms=2000)

sys.exit()

# Check current state before doing anything.
reply = rc.status()
print(f"Status: {reply}")

# Start focus (live preview) mode and let it run for a few seconds.
print("\nStarting focus mode ...")
reply = rc.focus()
print(f"focus() → {reply}")
time.sleep(3)

# Stop focus mode.
print("\nStopping ...")
reply = rc.stop()
print(f"stop() → {reply}")
time.sleep(0.5)

# Set the default frame count, then trigger a grab without specifying n_frames.
print("\nSetting default frame count to 100 ...")
reply = rc.set_n_frames(100)
print(f"set_n_frames(100) → {reply}")

print("\nStarting grab (using default frame count) ...")
reply = rc.grab()
print(f"grab() → {reply}")

# Poll until acquisition finishes (state returns to 'idle').
print("Waiting for grab to complete ", end='', flush=True)
while True:
    state = rc.status().get('state', 'unknown')
    if state == 'idle':
        break
    print('.', end='', flush=True)
    time.sleep(0.5)
print(" done.")

# Alternatively, pass n_frames directly to grab().
print("\nStarting grab with explicit frame count ...")
reply = rc.grab(n_frames=50)
print(f"grab(n_frames=50) → {reply}")
time.sleep(1)
reply = rc.stop()
print(f"stop() → {reply}")

rc.close()
print("\nDone.")

