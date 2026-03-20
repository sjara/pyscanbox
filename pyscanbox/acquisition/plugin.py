"""Plugin interface and plugin manager for pyscanbox acquisition.

This module contains two classes:

    AcquisitionPlugin  — abstract base class that every plugin implements.
    PluginManager      — dispatches lifecycle events to registered plugins;
                         owned by AppController.

Plugin authors only need to read AcquisitionPlugin.  Override only the
lifecycle hooks relevant to the synchronisation strategy being used:

    on_frame         → sync_mode includes 'per_frame'   (Strategy 2 & 3)
    on_ttl_event     → sync_mode includes 'ttl'         (Strategy 1)
    both             → sync_mode is ['per_frame', 'ttl']

The sync_mode property is auto-inferred from which hooks the subclass
overrides; plugin writers never set it explicitly.

Async plugins (Strategy 3) also override on_frame to record frame anchors,
so they report ['per_frame'] automatically.  To additionally document the
async nature, a subclass may override sync_mode and return
super().sync_mode + ['async']; this is purely optional.
"""

from __future__ import annotations

import abc
import logging
from typing import Any, Sequence


class AcquisitionPlugin(abc.ABC):
    """Base class for pyscanbox acquisition plugins.

    Lifecycle
    ---------
    on_acquisition_start(n_frames, frame_rate)
        Called once, immediately before the first Alazar buffer is requested.
        Open hardware connections here, zero counters, etc.

    on_frame(frame_index)
        Called once per completed Alazar buffer, AFTER the buffer has been
        processed.  This is the right place to poll serial devices (Strategy 2)
        or record PC-clock anchors (Strategy 3).  Called on the acquisition
        thread — must return quickly (<5 ms).

    on_ttl_event(frame, line, event_id)
        Called whenever the PSoC delivers a TTL-edge timestamp packet.  May be
        called zero or many times between successive on_frame() calls.

    on_acquisition_stop(n_frames)
        Called once after the last frame, before the data file is closed.
        Save any pending data here.

    Attributes:
        name: Short identifier, used to name companion data files.
            Subclasses must set this at class level.
        enabled: If False the PluginManager skips this plugin entirely.
        sync_mode: Read-only property; auto-inferred from which hooks are
            overridden — no need to set it explicitly.  Returns a list:
            'per_frame' if on_frame is overridden (Strategies 2 & 3),
            'ttl' if on_ttl_event is overridden (Strategy 1).
            A plugin that overrides both gets ['per_frame', 'ttl'].
    """

    name: str = 'plugin'
    enabled: bool = True

    @property
    def sync_mode(self) -> list[str]:
        """Return the inferred synchronisation modes.

        Inspects which lifecycle hooks the subclass overrides and returns a
        corresponding list of mode strings.  No override is needed in
        subclasses; the result is always consistent with what the plugin
        actually does.

        Returns:
            List of active sync mode labels.  Empty if only
            on_acquisition_start / on_acquisition_stop are overridden.
        """
        modes = []
        if type(self).on_frame is not AcquisitionPlugin.on_frame:
            modes.append('per_frame')
        if type(self).on_ttl_event is not AcquisitionPlugin.on_ttl_event:
            modes.append('ttl')
        return modes

    def on_acquisition_start(self, n_frames: int, frame_rate: float) -> None:
        """Prepare for acquisition.

        Args:
            n_frames: Total frames to acquire (0 in continuous/focus mode).
            frame_rate: Estimated frame rate in Hz.
        """

    def on_frame(self, frame_index: int) -> None:
        """React to a completed frame.

        Called on the acquisition thread.  Must return quickly (<5 ms).

        Args:
            frame_index: 0-based index of the just-completed frame.
        """

    def on_ttl_event(self, frame: int, line: int, event_id: int) -> None:
        """React to a TTL edge timestamped by the PSoC.

        Args:
            frame: Frame index at which the edge was detected.
            line: Scan line within that frame (0 <= line < lines_per_frame).
            event_id: 1 = TTL0, 2 = TTL1, 3 = both.
        """

    def on_acquisition_stop(self, n_frames: int) -> None:
        """Finalise and save data after acquisition ends.

        Args:
            n_frames: Actual number of frames acquired.
        """

    def get_metadata(self) -> dict[str, Any]:
        """Return metadata to embed in the .mat sidecar file.

        Keys should be prefixed with the plugin name to avoid collisions,
        e.g. ``{'quadrature_calibration': 0.04363, ...}``.

        Returns:
            Dictionary of plugin metadata.
        """
        return {}


_logger = logging.getLogger(__name__)


class PluginManager:
    """Dispatches acquisition lifecycle events to registered plugins.

    Owned by AppController; connected to Scanner so that every registered
    plugin receives the same lifecycle calls at the right moments.  Each
    dispatch call is wrapped in a try/except so that a misbehaving plugin
    cannot abort imaging.  Plugins are called in registration order.  A
    plugin with enabled=False is silently skipped on every dispatch.

    Example:
        >>> manager = PluginManager()
        >>> manager.register(MyPlugin())
        >>> manager.on_acquisition_start(n_frames=1000, frame_rate=30.0)
    """

    def __init__(
        self,
        plugins: Sequence[AcquisitionPlugin] | None = None,
    ):
        """Initialise with an optional pre-built list of plugins.

        Args:
            plugins: Initial set of plugins; additional plugins may be added
                later via register().
        """
        self._plugins: list[AcquisitionPlugin] = list(plugins or [])

    def register(self, plugin: AcquisitionPlugin) -> None:
        """Register a plugin.

        Args:
            plugin: Plugin instance to add.
        """
        self._plugins.append(plugin)

    def on_acquisition_start(self, n_frames: int, frame_rate: float) -> None:
        """Dispatch on_acquisition_start to all active plugins.

        Args:
            n_frames: Total frames to acquire (0 in continuous/focus mode).
            frame_rate: Estimated frame rate in Hz.
        """
        for p in self._active():
            try:
                p.on_acquisition_start(n_frames, frame_rate)
            except Exception:
                _logger.exception(
                    'Plugin %s: on_acquisition_start failed', p.name
                )

    def on_frame(self, frame_index: int) -> None:
        """Dispatch on_frame to all active plugins.

        Args:
            frame_index: 0-based index of the just-completed frame.
        """
        for p in self._active():
            try:
                p.on_frame(frame_index)
            except Exception:
                _logger.exception('Plugin %s: on_frame failed', p.name)

    def on_ttl_event(self, frame: int, line: int, event_id: int) -> None:
        """Dispatch on_ttl_event to all active plugins.

        Args:
            frame: Frame index at which the edge was detected.
            line: Scan line within that frame.
            event_id: 1 = TTL0, 2 = TTL1, 3 = both.
        """
        for p in self._active():
            try:
                p.on_ttl_event(frame, line, event_id)
            except Exception:
                _logger.exception('Plugin %s: on_ttl_event failed', p.name)

    def on_acquisition_stop(self, n_frames: int) -> None:
        """Dispatch on_acquisition_stop to all active plugins.

        Args:
            n_frames: Actual number of frames acquired.
        """
        for p in self._active():
            try:
                p.on_acquisition_stop(n_frames)
            except Exception:
                _logger.exception(
                    'Plugin %s: on_acquisition_stop failed', p.name
                )

    def collect_metadata(self) -> dict:
        """Collect and merge metadata dicts from all active plugins.

        Returns:
            Merged dictionary of plugin metadata.  Later entries overwrite
            earlier ones on key collision; prefix plugin names in keys to
            avoid this.
        """
        meta = {}
        for p in self._active():
            try:
                meta.update(p.get_metadata())
            except Exception:
                _logger.exception('Plugin %s: get_metadata failed', p.name)
        return meta

    def _active(self) -> list[AcquisitionPlugin]:
        return [p for p in self._plugins if p.enabled]
