# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Image display widget for pyscanbox GUI.

Defines the main real-time frame display components:
- _ImageCanvas: Internal QGraphicsView with zoom, pan, markers, and dual-canvas sync
- ImageDisplayWidget: Public widget that wraps one or two _ImageCanvas instances

Note: HistogramWidget is defined in histogram_widget.py.
"""

import math

import numpy as np
import PyQt6.QtWidgets as QtWidgets
import PyQt6.QtCore as QtCore
import PyQt6.QtGui as QtGui

from .colormaps import _build_colormap_lut, _RED_BOOST


# ---------------------------------------------------------------------------
# Module-level display configuration
# ---------------------------------------------------------------------------

# Colormap used for PMT0 display and the histogram colourbar.
# Allowed values: 'green', 'green_white', 'gray'  (see _build_colormap_lut).
_DISPLAY_COLORMAP: str = 'green_white'

# Colormap used for PMT1 display.
# Allowed values: 'red', 'red_white', 'gray'  (see _build_colormap_lut).
_DISPLAY_COLORMAP_PMT1: str = 'red_white'

# Precomputed lookup table for PMT0 display.  The PMT1 LUT is built
# per-widget in ImageDisplayWidget.__init__ so that the config-file red_boost
# value (display.red_boost) is applied correctly.
_DISPLAY_LUT: np.ndarray = _build_colormap_lut(_DISPLAY_COLORMAP)


class _ImageCanvas(QtWidgets.QGraphicsView):
    """Internal QGraphicsView used by ImageDisplayWidget for zoom and pan.

    Gestures:
    - **Mouse wheel**: zoom in/out centred on the cursor position.
    - **Left-click drag**: pan the image.
    - **Right-click**: context menu — Fit to Window, Zoom In, Zoom Out,
      Actual Size (1:1).

    The view starts in *fit mode*: the image is automatically scaled to fill
    the available space while preserving aspect ratio.  Any zoom gesture
    switches to *manual zoom* mode.  "Fit to Window" in the context menu
    (or ``fit_to_window()``) restores fit mode.
    """

    # Emitted when the user selects "Save Snapshot" from the context menu.
    snapshot_requested = QtCore.pyqtSignal()

    _ZOOM_FACTOR = 1.25    # scale multiplier per wheel step
    _MARKER_COLOR = QtGui.QColor("#80AAAA00")   # Qt uses ARGB not RGBA
    _MARKER_SIZE = 5        # plus-arm half-length in image pixels

    # Nominal scene size used for the placeholder text before the first frame.
    _PLACEHOLDER_W = 512
    _PLACEHOLDER_H = 512

    def __init__(self, parent=None, display_config=None):
        super().__init__(parent)
        # Shadow class-level defaults with per-instance values from config.
        cfg = display_config or {}
        if 'zoom_factor' in cfg:
            self._ZOOM_FACTOR = float(cfg['zoom_factor'])
        if 'marker_color' in cfg:
            self._MARKER_COLOR = QtGui.QColor(cfg['marker_color'])
        if 'marker_size' in cfg:
            self._MARKER_SIZE = int(cfg['marker_size'])
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)

        # Placeholder text shown before the first frame arrives.
        self._placeholder = self._scene.addText(
            "Image Display\n(Live preview will appear here)"
        )
        self._placeholder.setDefaultTextColor(QtGui.QColor("#969696"))
        self._placeholder.setFont(QtGui.QFont("Arial", 14))
        self._scene.setSceneRect(0, 0, self._PLACEHOLDER_W, self._PLACEHOLDER_H)
        br = self._placeholder.boundingRect()
        self._placeholder.setPos(
            (self._PLACEHOLDER_W - br.width()) / 2,
            (self._PLACEHOLDER_H - br.height()) / 2,
        )

        # Pixmap item sits above the placeholder.
        self._pixmap_item = QtWidgets.QGraphicsPixmapItem()
        self._pixmap_item.setZValue(1)
        self._scene.addItem(self._pixmap_item)

        # True = auto-fit; any user zoom sets this to False.
        self._is_fit: bool = True

        self.setStyleSheet("background-color: #1e1e1e; border: none;")
        self.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        # No smooth scaling during live acquisition — FastTransformation is
        # fast enough and avoids blurring at 1:1 or lower zoom levels.
        self.setRenderHint(
            QtGui.QPainter.RenderHint.SmoothPixmapTransform, False
        )
        # Zoom anchored to whichever pixel the cursor is over.
        self.setTransformationAnchor(
            QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setResizeAnchor(
            QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter
        )
        # Left-click drag = pan.
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)

        # ------------------------------------------------------------------
        # Marker state
        # ------------------------------------------------------------------
        self._marker_mode: bool = False
        self._markers: list = []   # deprecated
        self._marker_count: int = 0 # deprecated

        self._logical_markers: list[QtCore.QPointF] = []
        self._drawn_markers: list = []

        # Peer canvas for synchronized dual-canvas mode ("PMT0 | PMT1").
        self._peer: "_ImageCanvas | None" = None
        self._syncing: bool = False

        # Small toggle button overlaid on the top-right corner of the view.
        # It is a direct child widget of _ImageCanvas so it floats above the
        # scene without affecting the layout of ImageDisplayWidget.
        self._mark_button = QtWidgets.QPushButton("✛", self)
        self._mark_button.setCheckable(True)
        self._mark_button.setFixedSize(28, 28)
        self._mark_button.setToolTip(
            "Marker mode — click to place markers\n"
            "Press Esc or click again to exit"
        )
        self._mark_button.setStyleSheet(
            "QPushButton {"
            "  background: rgba(40,40,40,180);"
            "  color: #cccccc;"
            "  border: 1px solid #555;"
            "  border-radius: 4px;"
            "  font-size: 14px;"
            "}"
            "QPushButton:checked {"
            "  background: rgba(180,140,0,200);"
            "  color: #ffffff;"
            "  border: 1px solid #ffcc00;"
            "}"
            "QPushButton:hover { border: 1px solid #888; }"
        )
        self._mark_button.toggled.connect(self._on_mark_toggled)
        self._reposition_mark_button()

        # Small zoom-level label overlaid on the bottom-right corner.
        self._zoom_label = QtWidgets.QLabel("100%", self)
        self._zoom_label.setStyleSheet(
            "QLabel {"
            "  background: rgba(30,30,30,160);"
            "  color: #cccccc;"
            "  border: 1px solid #555;"
            "  border-radius: 3px;"
            "  padding: 2px 5px;"
            "  font-size: 11px;"
            "}"
        )
        self._zoom_label.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._reposition_zoom_label()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_pixmap(self, pixmap: QtGui.QPixmap) -> None:
        """Replace the displayed image with *pixmap*.

        Called from ``ImageDisplayWidget.update_frame`` on every new frame.
        The view's scene rectangle is updated to match the pixmap dimensions
        so that ``fitInView`` works correctly.
        """
        self._pixmap_item.setPixmap(pixmap)
        if self._placeholder.isVisible():
            self._placeholder.setVisible(False)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        if self._is_fit:
            self._fit_in_view()

    def set_startup_message(self, text: str) -> None:
        """Replace the placeholder text shown before the first frame.

        Used during startup to report hardware connection progress.
        The text is re-centred automatically after the change.

        Args:
            text: Multi-line string to display in the placeholder area.
        """
        self._placeholder.setPlainText(text)
        br = self._placeholder.boundingRect()
        self._placeholder.setPos(
            (self._PLACEHOLDER_W - br.width()) / 2,
            (self._PLACEHOLDER_H - br.height()) / 2,
        )

    def fit_to_window(self) -> None:
        """Switch to fit mode and scale the image to fill the view."""
        self._is_fit = True
        self._fit_in_view()
        if self._peer and not self._syncing:
            self._syncing = True
            self._peer._syncing = True
            self._peer.fit_to_window()
            self._peer._syncing = False
            self._syncing = False

    # ------------------------------------------------------------------
    # Qt event overrides
    # ------------------------------------------------------------------

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        """Pan sync: mirror every scroll to the peer canvas."""
        super().scrollContentsBy(dx, dy)
        if self._peer and not self._syncing:
            self._syncing = True
            self._peer._syncing = True  # prevent peer from back-syncing into self
            self._peer.horizontalScrollBar().setValue(self.horizontalScrollBar().value())
            self._peer.verticalScrollBar().setValue(self.verticalScrollBar().value())
            self._peer._syncing = False
            self._syncing = False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._is_fit:
            self._fit_in_view()
        self._reposition_mark_button()
        self._reposition_zoom_label()

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """Zoom in or out centred on the cursor position."""
        if event.angleDelta().y() > 0:
            factor = self._ZOOM_FACTOR
        else:
            factor = 1.0 / self._ZOOM_FACTOR
        self._is_fit = False
        self.scale(factor, factor)
        self._update_zoom_label()
        self._sync_peer_view()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """Place a marker on left-click when marker mode is active."""
        if (self._marker_mode
                and event.button() == QtCore.Qt.MouseButton.LeftButton):
            scene_pos = self.mapToScene(event.pos())
            self._add_marker(scene_pos)
            return  # do not pan
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        """Exit marker mode on Esc."""
        if event.key() == QtCore.Qt.Key.Key_Escape and self._marker_mode:
            self._mark_button.setChecked(False)
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        """Show a right-click context menu with zoom/view and snapshot actions."""
        menu = QtWidgets.QMenu(self)
        fit_action       = menu.addAction("Fit to Window")
        menu.addSeparator()
        zoom_in_action   = menu.addAction("Zoom In")
        zoom_out_action  = menu.addAction("Zoom Out")
        actual_action    = menu.addAction("Actual Size (1:1)")
        menu.addSeparator()
        clear_action     = menu.addAction("Clear Markers")
        menu.addSeparator()
        snapshot_action  = menu.addAction("Save Snapshot")
        action = menu.exec(event.globalPos())
        if action == fit_action:
            self.fit_to_window()
        elif action == zoom_in_action:
            self._is_fit = False
            self.scale(self._ZOOM_FACTOR, self._ZOOM_FACTOR)
            self._update_zoom_label()
            self._sync_peer_view()
        elif action == zoom_out_action:
            self._is_fit = False
            self.scale(1.0 / self._ZOOM_FACTOR, 1.0 / self._ZOOM_FACTOR)
            self._update_zoom_label()
            self._sync_peer_view()
        elif action == actual_action:
            self._is_fit = False
            self.resetTransform()
            self._update_zoom_label()
            self._sync_peer_view()
        elif action == clear_action:
            self.clear_markers()
        elif action == snapshot_action:
            # Emit a signal that will be connected to MainWindow._on_save_snapshot
            self.snapshot_requested.emit()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fit_in_view(self) -> None:
        rect = self._pixmap_item.boundingRect()
        if not rect.isNull():
            self.fitInView(rect, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            self._update_zoom_label()
        if self._peer and not self._syncing and self._peer._is_fit:
            self._syncing = True
            self._peer._syncing = True
            self._peer._fit_in_view()
            self._peer._syncing = False
            self._syncing = False

    def _reposition_mark_button(self) -> None:
        """Keep the Mark button in the top-right corner of the viewport."""
        margin = 6
        btn = self._mark_button
        btn.move(self.width() - btn.width() - margin, margin)
        btn.raise_()

    def _reposition_zoom_label(self) -> None:
        """Keep the zoom label in the bottom-right corner of the viewport."""
        margin = 6
        lbl = self._zoom_label
        lbl.adjustSize()
        lbl.move(self.width() - lbl.width() - margin,
                 self.height() - lbl.height() - margin)
        lbl.raise_()

    def _update_zoom_label(self) -> None:
        """Refresh the zoom label text to reflect the current transform."""
        scale = self.transform().m11()
        self._zoom_label.setText(f"{scale * 100:.0f}%")
        self._reposition_zoom_label()

    def _on_mark_toggled(self, enabled: bool) -> None:
        """Switch between marker mode and normal pan mode."""
        self._marker_mode = enabled
        if enabled:
            self.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)
            self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
        else:
            self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
            self.unsetCursor()
        if self._peer and not self._syncing:
            self._syncing = True
            self._peer._mark_button.setChecked(enabled)
            self._syncing = False

    def _draw_markers(self) -> None:
        """Clear and redraw all markers based on logical positions."""
        for item in self._drawn_markers:
            self._scene.removeItem(item)
        self._drawn_markers.clear()

        r = self._MARKER_SIZE
        pen = QtGui.QPen(self._MARKER_COLOR, 1.5)

        def make_marker(pos):
            line_h = QtWidgets.QGraphicsLineItem(
                pos.x() - r, pos.y(),
                pos.x() + r, pos.y(),
            )
            line_v = QtWidgets.QGraphicsLineItem(
                pos.x(), pos.y() - r,
                pos.x(), pos.y() + r,
            )
            line_h.setPen(pen)
            line_v.setPen(pen)
            group = self._scene.createItemGroup([line_h, line_v])
            group.setZValue(2)
            self._drawn_markers.append(group)

        for log_pos in self._logical_markers:
            make_marker(log_pos)

    def _add_marker(self, scene_pos: QtCore.QPointF) -> None:
        """Add a plus-sign marker at *scene_pos* (image coordinates)."""
        x = scene_pos.x()
        y = scene_pos.y()
        self._logical_markers.append(QtCore.QPointF(x, y))
        self._draw_markers()
        if self._peer and not self._syncing:
            self._syncing = True
            self._peer._logical_markers.append(QtCore.QPointF(x, y))
            self._peer._draw_markers()
            self._syncing = False

    def clear_markers(self) -> None:
        """Remove all markers from the scene and reset the counter."""
        for item in self._drawn_markers:
            self._scene.removeItem(item)
        self._drawn_markers.clear()
        self._logical_markers.clear()
        if self._peer and not self._syncing:
            self._syncing = True
            self._peer.clear_markers()
            self._syncing = False

    def _sync_peer_view(self) -> None:
        """Copy this canvas's exact transform and scroll position to the peer.

        Called after any zoom action so the peer shows the identical region
        without being affected by where the mouse cursor is.
        """
        if not self._peer or self._syncing:
            return
        self._syncing = True
        self._peer._syncing = True
        self._peer._is_fit = self._is_fit
        self._peer.setTransform(self.transform())
        self._peer._update_zoom_label()
        self._peer.horizontalScrollBar().setValue(self.horizontalScrollBar().value())
        self._peer.verticalScrollBar().setValue(self.verticalScrollBar().value())
        self._peer._syncing = False
        self._syncing = False

    def set_peer(self, peer: "_ImageCanvas | None") -> None:
        """Link or unlink a peer canvas for synchronized zoom/pan/markers.

        When a peer is set both canvases mirror each other's scroll position,
        zoom level, marker placement, and marker-mode state.  Pass ``None``
        to disconnect.
        """
        if self._peer is peer:
            return
        if self._peer is not None:
            self._peer._peer = None
        self._peer = peer
        if peer is not None:
            peer._peer = self


class ImageDisplayWidget(QtWidgets.QWidget):
    """Main image display widget for real-time frame visualization.

    Displays the most recently acquired frame as a coloured image.  The
    frame data (numpy array) is delivered by calling ``update_frame()``
    which is connected to ``AppController.frame_data_ready`` in
    ``MainWindow._connect_hardware()``.

    Zoom and pan are handled by the embedded :class:`_ImageCanvas`
    (``QGraphicsView``):

    - **Mouse wheel**: zoom in/out centred on the cursor.
    - **Left-click drag**: pan.
    - **Right-click**: context menu — Fit to Window, Zoom In, Zoom Out,
      Actual Size (1:1).
    """

    # Slider range is 1–100; gain = slider_value / 10  (0.1x … 10.0x).
    # Default slider value is 10, giving gain = 1.0 which preserves the
    # original >> 8 behaviour (16-bit wire format → 8-bit with no clipping).
    _GAIN_DIVISOR = 10.0

    # Maximum 16-bit value (2^16 - 1).  Data is stored in wire format
    # (0–65535) matching MATLAB alazarReshapeCData2.c (see alazar_digitizer.md).
    _MAX_VALUE = 65535

    def __init__(self, config=None):
        """Initialize the image display widget."""
        super().__init__()
        # Holds the current uint8 frame buffer so that the QImage's memory
        # reference stays valid until the next frame arrives.
        self._display_buffer: np.ndarray | None = None
        self._display_buffer2: np.ndarray | None = None
        self._gain: float = 1.0
        # Channel index: 0=PMT0, 1=PMT1, 2=average of both.
        self._channel: int = 0
        # Invert display: True = fluorescence mode (PMT output decreases with
        # more light, so we flip: background=0/black, signal=bright).
        # False = direct/debug mode (high ADC value = bright).
        self._invert: bool = True
        # Active colormap name and precomputed 256×3 uint8 LUT.
        # Initialised from the module-level _DISPLAY_COLORMAP constant; can
        # still be changed at runtime via set_colormap().
        self._colormap: str = _DISPLAY_COLORMAP
        self._lut: np.ndarray = _DISPLAY_LUT
        # Separate LUT for PMT1 (red_white by default).
        # red_boost can be overridden via the 'display.red_boost' config key.
        # Extract the display sub-section from the config (supports both plain
        # dicts and objects with a to_dict() method such as AppConfig).
        config_dict = (
            config.to_dict() if hasattr(config, 'to_dict') else (config or {})
        )
        self._display_cfg: dict = config_dict.get('display', {})
        _cfg_red_boost = self._display_cfg.get('red_boost', None)
        self._lut_pmt1: np.ndarray = _build_colormap_lut(
            _DISPLAY_COLORMAP_PMT1,
            red_boost=_cfg_red_boost,
        )
        # Raw 16-bit frame kept so that gain/channel changes can re-render
        # the last frame without waiting for the next acquisition.
        self._raw_frame: np.ndarray | None = None
        # Rolling average state.  tau=0 means disabled.
        # _rolling_avg holds the float32 exponential accumulator;
        # _rolling_tau=0 bypasses averaging entirely.
        self._rolling_tau: int = 0
        self._rolling_delta: float = 0.0
        self._rolling_avg: np.ndarray | None = None
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI components."""
        outer = QtWidgets.QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        self._canvas_row = QtWidgets.QHBoxLayout()
        self._canvas_row.setContentsMargins(0, 0, 0, 0)
        self._canvas_row.setSpacing(0)
        self._canvas = _ImageCanvas(display_config=self._display_cfg)
        self._canvas2 = _ImageCanvas(display_config=self._display_cfg)
        self._canvas_row.addWidget(self._canvas, stretch=1)
        self._canvas_row.addWidget(self._canvas2, stretch=1)
        self._canvas2.hide()
        outer.addLayout(self._canvas_row)
        self.setLayout(outer)

    def set_startup_message(self, text: str) -> None:
        """Update the placeholder text shown before the first frame arrives.

        Args:
            text: Status string to display (may contain newlines).
        """
        self._canvas.set_startup_message(text)

    def update_frame(self, frame_data: np.ndarray) -> None:
        """Update the display with a newly acquired frame.

        Converts the selected PMT channel(s) of the 16-bit wire-format frame
        array to an 8-bit RGB QPixmap coloured by channel convention:

        - **PMT0** → green pixels  (R=0, G=intensity, B=0)
        - **PMT1** → red pixels    (R=intensity, G=0, B=0)
        - **PMT0 & PMT1** → red/green overlay (R=PMT1, G=PMT0, B=0)

        In **fluorescence mode** (default) the display is *inverted*: a PMT
        produces a current that *decreases* the ADC value when light is
        present (the raw offset-binary background sits near 65535 with no
        light).  We compensate with ``(65535 - ch) * gain / 256`` so that the
        dark background maps to 0 (black) and bright fluorescence maps to the
        channel colour, matching the original Scanbox display (which takes the
        high byte of the stored 16-bit value and inverts it).

        In **direct mode** the raw ADC value is shown without inversion
        (high ADC value = bright / saturated colour).  Useful for debugging.

        This slot is called from the GUI thread via a queued signal
        connection; the numpy array is passed by reference and is safe to
        read because the Scanner creates a fresh array for every frame.

        Args:
            frame_data: Shape ``(channels, lines_per_frame, pixels_per_line)``,
                dtype ``uint16``, values 0–65535 (16-bit wire format).
        """
        if frame_data is None:
            return  # stale queued signal delivered after scanner cleanup

        self._raw_frame = frame_data
        if self._rolling_tau > 0:
            f = frame_data.astype(np.float32)
            if self._rolling_avg is None or self._rolling_avg.shape != f.shape:
                self._rolling_avg = f.copy()
            else:
                delta = self._rolling_delta
                self._rolling_avg = delta * self._rolling_avg + (1.0 - delta) * f
        self._render_frame()

    def _render_frame(self) -> None:
        """Re-render ``_raw_frame`` with the current gain, channel and LUT.

        Called by ``update_frame`` on every new frame and by ``set_gain`` /
        ``set_channel`` so that display-setting changes take effect
        immediately on the frozen last frame after acquisition stops.
        """
        if self._rolling_tau > 0 and self._rolling_avg is not None:
            frame_data = np.clip(self._rolling_avg, 0, self._MAX_VALUE).astype(
                np.uint16
            )
        else:
            frame_data = self._raw_frame
        if frame_data is None:
            return

        n_channels = frame_data.shape[0]

        def _scale(ch: np.ndarray) -> np.ndarray:
            """Map a 16-bit wire-format channel array to uint8, applying inversion + gain."""
            c = ch.astype(np.float32)
            if self._invert:
                # Fluorescence mode: background (high ADC ≈ 65535) → 0 (black),
                # signal (low ADC ≈ 0) → 255.  Matches Scanbox MATLAB display
                # which takes 255 - high_byte(v), i.e. (65535 - v) / 256.
                return np.clip(
                    (self._MAX_VALUE - c) * self._gain / 256.0, 0, 255
                ).astype(np.uint8)
            # Direct mode: high ADC → bright (for debugging).
            return np.clip(c * self._gain / 256.0, 0, 255).astype(np.uint8)

        # Build a 3-channel RGB array coloured by PMT channel convention.
        # PMT0 = green (typical fluorescence ch1: GFP, FITC, …)
        # PMT1 = red   (typical fluorescence ch2: tdTomato, RFP, …)
        # Colormap is applied via NumPy fancy indexing (lut[grayscale]) which
        # runs in compiled C code — fast enough for real-time display.
        if self._channel == 3 and n_channels >= 2:
            # Dual synchronized canvases: PMT0 in left canvas, PMT1 in right canvas.
            g_rgb = np.ascontiguousarray(self._lut[_scale(frame_data[0])])
            r_rgb = np.ascontiguousarray(self._lut_pmt1[_scale(frame_data[1])])
            h, w = g_rgb.shape[:2]
            img0 = QtGui.QImage(g_rgb.data, w, h, w * 3, QtGui.QImage.Format.Format_RGB888)
            img1 = QtGui.QImage(r_rgb.data, w, h, w * 3, QtGui.QImage.Format.Format_RGB888)
            # Keep references alive until the next frame.
            self._display_buffer = g_rgb
            self._display_buffer2 = r_rgb
            self._canvas.set_pixmap(QtGui.QPixmap.fromImage(img0))
            self._canvas2.set_pixmap(QtGui.QPixmap.fromImage(img1))
            return
        elif self._channel == 2 and n_channels >= 2:
            # Overlay: R = PMT1 (red), G = PMT0 (green), B = 0.
            # Colormap is not applied to overlay; channel colours are fixed.
            g = _scale(frame_data[0])
            r = _scale(frame_data[1])
            height, width = g.shape
            rgb = np.zeros((height, width, 3), dtype=np.uint8)
            rgb[:, :, 0] = r
            rgb[:, :, 1] = g
        elif self._channel == 1:
            # PMT1 → apply the PMT1-specific colormap (red_white by default).
            v = _scale(frame_data[min(1, n_channels - 1)])
            rgb = self._lut_pmt1[v]  # fancy indexing: (H, W) → (H, W, 3)
        else:
            # PMT0 (default) → apply colormap.
            v = _scale(frame_data[0])
            rgb = self._lut[v]  # fancy indexing: (H, W) → (H, W, 3)

        self._display_buffer = np.ascontiguousarray(rgb)
        height, width = self._display_buffer.shape[:2]

        # Wrap the numpy RGB buffer in a QImage without copying.
        # _display_buffer keeps the memory alive until the next call.
        img = QtGui.QImage(
            self._display_buffer.data,
            width,
            height,
            width * 3,  # bytes per line: 3 bytes per pixel (R, G, B)
            QtGui.QImage.Format.Format_RGB888,
        )

        pixmap = QtGui.QPixmap.fromImage(img)
        self._canvas.set_pixmap(pixmap)

    def set_gain(self, slider_value: int) -> None:
        """Update the display gain from the Image Display gain slider.

        Args:
            slider_value: Integer value from the gain slider (1–100).
                The effective multiplier is ``slider_value / _GAIN_DIVISOR``
                (i.e. 0.1× – 10.0×).  Re-renders the last frame immediately.
        """
        self._gain = slider_value / self._GAIN_DIVISOR
        self._render_frame()

    def set_channel(self, index: int) -> None:
        """Set the PMT channel to display.  Re-renders the last frame.

        Args:
            index: 0 = PMT0, 1 = PMT1, 2 = overlay, 3 = dual synchronized canvases.
        """
        self._channel = index
        if index == 3:
            self._canvas2.show()
            # Copy the current zoom/pan state from canvas1 to canvas2 before
            # linking them as peers, so both start in sync.
            self._canvas2._is_fit = self._canvas._is_fit
            self._canvas2.setTransform(self._canvas.transform())
            self._canvas2.horizontalScrollBar().setValue(
                self._canvas.horizontalScrollBar().value()
            )
            self._canvas2.verticalScrollBar().setValue(
                self._canvas.verticalScrollBar().value()
            )
            self._canvas.set_peer(self._canvas2)
        else:
            self._canvas2.hide()
            self._canvas.set_peer(None)
        self._render_frame()

    def set_display_mode(self, index: int) -> None:
        """Switch between fluorescence (inverted) and direct display modes.

        Not connected to the GUI — the display is always in fluorescence mode
        (``_invert = True``).  Kept for programmatic use or future debugging.

        Args:
            index: 0 = Fluorescence (inverted), 1 = Direct (raw ADC).
        """
        self._invert = (index == 0)

    def set_rolling_avg(self, tau: int) -> None:
        """Enable or disable the rolling average display.

        When enabled, each new frame passed to ``update_frame`` is blended
        with the exponential accumulator:

            avg = delta * avg + (1 - delta) * frame,  delta = exp(-1/tau)

        The rendered image comes from the averaged data rather than the raw
        frame, smoothing out shot noise over several consecutive frames.
        Changing tau resets the accumulator so the display responds
        immediately with the new setting.

        Args:
            tau: Time constant in frames.  0 disables averaging (default).
        """
        self._rolling_tau = tau
        if tau > 0:
            self._rolling_delta = math.exp(-1.0 / tau)
        self._rolling_avg = None   # reset accumulator on every tau change
        self._render_frame()

    def set_colormap(self, index: int) -> None:
        """Set the display colormap from the Colormap combobox index.

        Colormaps (indices match the combobox order in
        ``ImageDisplayControlGroup``):

        * 0 – **Green** (default): black → green.  Matches the original
          Scanbox MATLAB convention for PMT0.
        * 1 – **Green-White**: black → green → white.  Lower half of the
          intensity range maps to shades of green; upper half adds equal
          red and blue so the brightest pixels saturate to white.
          Useful for seeing fine structure that would otherwise clip to
          a single saturated colour.
        * 2 – **Gray**: black → white.  Standard grayscale reference.

        The change takes effect on the next call to ``update_frame``.

        Args:
            index: 0 = Green, 1 = Green-White, 2 = Gray.
        """
        names = ['green', 'green_white', 'gray']
        name = names[index] if 0 <= index < len(names) else 'green'
        self._colormap = name
        self._lut = _build_colormap_lut(name)

    def save_snapshot(self, path: str) -> bool:
        """Save the current frame as a PNG file at its original resolution.

        The image is saved from ``_display_buffer`` (the last rendered RGB
        frame) rather than from the scaled pixmap in the display label, so
        the output is always at the raw frame resolution.

        Args:
            path: Absolute path to the output ``.png`` file.  The parent
                directory must already exist.

        Returns:
            True if the image was saved successfully, False if no frame has
            been acquired yet.
        """
        if self._display_buffer is None:
            return False
        height, width = self._display_buffer.shape[:2]
        img = QtGui.QImage(
            self._display_buffer.data,
            width,
            height,
            width * 3,
            QtGui.QImage.Format.Format_RGB888,
        )
        return img.save(path, 'PNG')
