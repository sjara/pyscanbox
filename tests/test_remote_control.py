# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Tests for the RemoteControlPlugin and RemoteControl client.

The QTimer dispatch loop is bypassed: after each ZMQ send we call
plugin._dispatch() directly on the main thread, avoiding a Qt event loop.
"""

import threading
import time

import pytest
import zmq

from pyscanbox.plugins.remote_control import RemoteControl, RemoteControlPlugin

TEST_PORT = 15558  # non-default port to avoid clashing with a running instance


def _make_plugin(state_ref, start_focus, start_grab, stop_acq, set_n, set_fs=None):
    return RemoteControlPlugin(
        config={'host': '127.0.0.1', 'port': TEST_PORT},
        start_focus=start_focus,
        start_grab=start_grab,
        stop_acquisition=stop_acq,
        get_state=lambda: state_ref[0],
        set_n_frames=set_n,
        set_file_storage=set_fs or (lambda fields: None),
    )


@pytest.fixture()
def app():
    """Plugin instance wired to mock callables, opened and closed around test.

    The QTimer is not started here — tests call plugin._dispatch() manually.
    """
    calls = {'focus': 0, 'grab': [], 'stop': 0, 'n_frames': [], 'file_storage': []}
    state = ['idle']

    plugin = _make_plugin(
        state_ref=state,
        start_focus=lambda: calls.__setitem__('focus', calls['focus'] + 1),
        start_grab=lambda n: calls['grab'].append(n),
        stop_acq=lambda: calls.__setitem__('stop', calls['stop'] + 1),
        set_n=lambda n: calls['n_frames'].append(n),
        set_fs=lambda fields: calls['file_storage'].append(fields),
    )
    # Open without creating a QTimer so no Qt event loop is required.
    plugin._open_no_timer()
    yield plugin, calls, state
    plugin.close()


def _send_and_dispatch(plugin, cmd: dict, timeout_ms: int = 2000) -> dict:
    """Send a ZMQ command, wait for it to be enqueued, dispatch, return reply."""
    reply_holder: list[dict] = []

    def _client():
        ctx = zmq.Context()
        sock = ctx.socket(zmq.REQ)
        sock.set(zmq.RCVTIMEO, timeout_ms)
        sock.connect(f'tcp://127.0.0.1:{TEST_PORT}')
        sock.send_json(cmd)
        reply_holder.append(sock.recv_json())
        sock.close()
        ctx.term()

    t = threading.Thread(target=_client, daemon=True)
    t.start()
    # Give the recv thread time to put the command in the queue.
    time.sleep(0.05)
    plugin._dispatch()
    t.join(timeout=2.0)
    return reply_holder[0] if reply_holder else {}


def test_status_idle(app):
    plugin, calls, state = app
    reply = _send_and_dispatch(plugin, {'cmd': 'status'})
    assert reply == {'ok': True, 'state': 'idle'}


def test_focus(app):
    plugin, calls, state = app
    reply = _send_and_dispatch(plugin, {'cmd': 'focus'})
    assert reply['ok']
    assert calls['focus'] == 1


def test_grab_with_n_frames(app):
    plugin, calls, state = app
    reply = _send_and_dispatch(plugin, {'cmd': 'grab', 'n_frames': 200})
    assert reply['ok']
    assert calls['grab'] == [200]


def test_stop(app):
    plugin, calls, state = app
    reply = _send_and_dispatch(plugin, {'cmd': 'stop'})
    assert reply['ok']
    assert calls['stop'] == 1


def test_set_n_frames(app):
    plugin, calls, state = app
    reply = _send_and_dispatch(plugin, {'cmd': 'set_n_frames', 'n_frames': 500})
    assert reply['ok']
    assert calls['n_frames'] == [500]


def test_grab_without_n_frames(app):
    """grab with no n_frames passes None to the start_grab callable."""
    plugin, calls, state = app
    reply = _send_and_dispatch(plugin, {'cmd': 'grab'})
    assert reply['ok']
    assert calls['grab'] == [None]


def test_unknown_command(app):
    plugin, calls, state = app
    reply = _send_and_dispatch(plugin, {'cmd': 'launch_missiles'})
    assert not reply['ok']
    assert 'unknown command' in reply['error']


def test_status_focusing(app):
    plugin, calls, state = app
    state[0] = 'focusing'
    reply = _send_and_dispatch(plugin, {'cmd': 'status'})
    assert reply == {'ok': True, 'state': 'focusing'}


def test_set_file_storage(app):
    plugin, calls, state = app
    reply = _send_and_dispatch(plugin, {'cmd': 'set_file_storage', 'subject': 'mouse01', 'session': '003'})
    assert reply['ok']
    assert calls['file_storage'] == [{'subject': 'mouse01', 'session': '003'}]


def test_set_file_storage_empty(app):
    plugin, calls, state = app
    reply = _send_and_dispatch(plugin, {'cmd': 'set_file_storage'})
    assert not reply['ok']
    assert 'at least one field' in reply['error']


def test_client(app):
    """RemoteControl client wraps the protocol correctly."""
    plugin, calls, state = app
    rc = RemoteControl(host='127.0.0.1', port=TEST_PORT, timeout_ms=2000)

    # status — no dispatch needed (reply_fn is called before QTimer)
    # Actually we still need to dispatch since the recv loop enqueues.
    reply_holder: list[dict] = []

    def _get_status():
        reply_holder.append(rc.status())

    t = threading.Thread(target=_get_status, daemon=True)
    t.start()
    time.sleep(0.05)
    plugin._dispatch()
    t.join(timeout=2.0)
    assert reply_holder[0] == {'ok': True, 'state': 'idle'}

    rc.close()
