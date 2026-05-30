# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Remote control plugin and client for pyscanbox.

RemoteControlPlugin binds a ZeroMQ REP socket and accepts JSON commands
from any local or networked process.  RemoteControl is a thin client that
speaks the same protocol.

Wire protocol (REQ/REP, JSON):

    {"cmd": "focus"}                         → {"ok": true}
    {"cmd": "grab", "n_frames": 500}         → {"ok": true}
    {"cmd": "stop"}                          → {"ok": true}
    {"cmd": "status"}                        → {"ok": true, "state": "idle"|"focusing"|"grabbing"}
    {"cmd": "set_n_frames", "n_frames": 500} → {"ok": true}

All error replies: {"ok": false, "error": "<message>"}
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable

import zmq
from PyQt6 import QtCore

from pyscanbox.acquisition.plugin import AcquisitionPlugin

logger = logging.getLogger(__name__)

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 5558


class RemoteControlPlugin(AcquisitionPlugin):
    """ZeroMQ REP server that accepts remote acquisition commands.

    Commands (focus, grab, stop, status, set_n_frames) are received in a
    background thread and dispatched on the Qt main thread via a QTimer-
    drained queue, keeping all Qt/controller calls thread-safe.

    Args:
        config: Plugin config dict.  Keys: host (str), port (int).
        start_focus: Callable that starts focus mode (no args).
        start_grab: Callable that starts grab acquisition (n_frames: int).
        stop_acquisition: Callable that stops the running acquisition.
        get_state: Callable that returns the current state string
            ("idle", "focusing", or "grabbing").
        set_n_frames: Callable that sets the default frame count (n: int).
    """

    name = 'remote_control'

    def __init__(
        self,
        config: dict,
        start_focus: Callable[[], None],
        start_grab: Callable[[int], None],
        stop_acquisition: Callable[[], None],
        get_state: Callable[[], str],
        set_n_frames: Callable[[int], None],
    ) -> None:
        self._address = (
            f"tcp://{config.get('host', DEFAULT_HOST)}:{config.get('port', DEFAULT_PORT)}"
        )
        self._start_focus = start_focus
        self._start_grab = start_grab
        self._stop_acquisition = stop_acquisition
        self._get_state = get_state
        self._set_n_frames = set_n_frames

        self._context: zmq.Context | None = None
        self._socket: zmq.Socket | None = None
        self._recv_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._cmd_queue: queue.Queue = queue.Queue()
        self._dispatch_timer: QtCore.QTimer | None = None

    def open(self) -> None:
        """Bind the REP socket and start the background receive thread.

        Called from a background thread by PluginConnectThread — must not
        create Qt objects here.  The QTimer is started separately via
        start_dispatch_timer(), which AppController calls on the main thread
        after open() succeeds.
        """
        self._open_no_timer()

    def start_dispatch_timer(self) -> None:
        """Create and start the QTimer that dispatches commands on the main thread.

        Must be called from the Qt main thread (AppController._on_plugin_connected).
        """
        self._dispatch_timer = QtCore.QTimer()
        self._dispatch_timer.setInterval(50)
        self._dispatch_timer.timeout.connect(self._dispatch)
        self._dispatch_timer.start()

    def _open_no_timer(self) -> None:
        """Bind the socket and start the recv thread without creating a QTimer.

        Used by unit tests that have no Qt event loop.
        """
        self._stop_event.clear()
        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.REP)
        self._socket.set(zmq.RCVTIMEO, 200)  # ms; lets thread notice stop_event
        self._socket.bind(self._address)
        logger.info("RemoteControlPlugin listening on %s", self._address)

        self._recv_thread = threading.Thread(
            target=self._recv_loop, name='remote_control_recv', daemon=True
        )
        self._recv_thread.start()

    def close(self) -> None:
        """Stop the timer and background thread, then close the socket."""
        if self._dispatch_timer is not None:
            self._dispatch_timer.stop()
            self._dispatch_timer = None

        self._stop_event.set()
        if self._recv_thread is not None:
            self._recv_thread.join(timeout=1.0)
            self._recv_thread = None

        if self._socket:
            self._socket.close()
            self._socket = None
        if self._context:
            self._context.term()
            self._context = None
        logger.info("RemoteControlPlugin closed")

    # ------------------------------------------------------------------
    # Background thread: receive commands and enqueue them
    # ------------------------------------------------------------------

    def _recv_loop(self) -> None:
        """Blocking recv loop; runs in background thread."""
        while not self._stop_event.is_set():
            try:
                msg = self._socket.recv_json()
            except zmq.Again:
                continue  # timeout; check stop_event
            except zmq.ZMQError as exc:
                if not self._stop_event.is_set():
                    logger.error("RemoteControlPlugin recv error: %s", exc)
                break

            reply_holder: list[dict] = []
            done = threading.Event()

            def make_reply(holder=reply_holder, ev=done):
                def _reply(result: dict) -> None:
                    holder.append(result)
                    ev.set()
                return _reply

            self._cmd_queue.put((msg, make_reply()))
            done.wait(timeout=5.0)
            reply = reply_holder[0] if reply_holder else {'ok': False, 'error': 'timeout'}
            try:
                self._socket.send_json(reply)
            except zmq.ZMQError as exc:
                logger.error("RemoteControlPlugin send error: %s", exc)

    # ------------------------------------------------------------------
    # Main-thread timer: drain queue and dispatch commands
    # ------------------------------------------------------------------

    def _dispatch(self) -> None:
        """Drain the command queue and execute on the Qt main thread."""
        while not self._cmd_queue.empty():
            try:
                msg, reply_fn = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            reply_fn(self._handle(msg))

    def _handle(self, msg: dict) -> dict:
        """Execute one command and return a reply dict."""
        cmd = msg.get('cmd')
        try:
            if cmd == 'focus':
                self._start_focus()
            elif cmd == 'grab':
                n = msg.get('n_frames')
                self._start_grab(None if n is None else int(n))
            elif cmd == 'stop':
                self._stop_acquisition()
            elif cmd == 'status':
                return {'ok': True, 'state': self._get_state()}
            elif cmd == 'set_n_frames':
                n = msg.get('n_frames')
                if n is None:
                    return {'ok': False, 'error': 'n_frames required'}
                self._set_n_frames(int(n))
            else:
                return {'ok': False, 'error': f'unknown command: {cmd!r}'}
        except Exception as exc:
            logger.error("RemoteControlPlugin command error (%s): %s", cmd, exc)
            return {'ok': False, 'error': str(exc)}
        return {'ok': True}


# ----------------------------------------------------------------------
# Thin client
# ----------------------------------------------------------------------

class RemoteControl:
    """Thin ZMQ client for RemoteControlPlugin.

    Args:
        host: IP or hostname of the pyscanbox machine.
        port: REP socket port (default 5558).
        timeout_ms: Reply timeout in milliseconds.

    Example::

        from pyscanbox.plugins.remote_control import RemoteControl
        rc = RemoteControl('192.168.1.5')
        rc.set_n_frames(500)
        rc.grab()
    """

    def __init__(
        self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout_ms: int = 5000
    ) -> None:
        self._address = f'tcp://{host}:{port}'
        self._timeout_ms = timeout_ms
        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.REQ)
        self._socket.set(zmq.RCVTIMEO, timeout_ms)
        self._socket.connect(self._address)

    def _send(self, msg: dict) -> dict:
        self._socket.send_json(msg)
        return self._socket.recv_json()

    def focus(self) -> dict:
        """Start focus mode."""
        return self._send({'cmd': 'focus'})

    def grab(self, n_frames: int | None = None) -> dict:
        """Start a grab acquisition.

        Args:
            n_frames: Frame count.  If None, the server uses the value set
                by a previous set_n_frames() call.
        """
        msg: dict = {'cmd': 'grab'}
        if n_frames is not None:
            msg['n_frames'] = n_frames
        return self._send(msg)

    def stop(self) -> dict:
        """Stop the running acquisition."""
        return self._send({'cmd': 'stop'})

    def status(self) -> dict:
        """Return the current acquisition state."""
        return self._send({'cmd': 'status'})

    def set_n_frames(self, n_frames: int) -> dict:
        """Set the default frame count used by subsequent grab() calls."""
        return self._send({'cmd': 'set_n_frames', 'n_frames': n_frames})

    def close(self) -> None:
        """Close the ZMQ socket and context."""
        self._socket.close()
        self._context.term()
