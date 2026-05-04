# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Histogram widget for pixel-intensity visualization.

Displays a 256-bin histogram of 16-bit PMT data with configurable
y-scale (linear/logarithmic), channel selection, and zoom controls.
"""

import math
import numpy as np
import PyQt6.QtWidgets as QtWidgets
import PyQt6.QtCore as QtCore
import PyQt6.QtGui as QtGui


def _build_colormap_lut(name: str, red_boost: float | None = None) -> np.ndarray:
    """Build a 256×3 uint8 lookup table for a named colormap.

    This is the single source of truth for all display colormaps; both
    ``HistogramWidget`` and ``ImageDisplayWidget`` (via import in
    ``widgets.py``) use this function.

    Args:
        name: Colormap name ('green', 'green_white', 'red', 'red_white', 'gray').
        red_boost: Optional scaling factor for red channel (red_white only).

    Returns:
        256×3 uint8 array where lut[i] = [R, G, B] for intensity i.
    """
    v = np.arange(256, dtype=np.float32)
    lut = np.zeros((256, 3), dtype=np.uint8)
    if name == 'green_white':
        # G ramps 0→255 linearly (same as plain green).
        lut[:, 1] = v.astype(np.uint8)
        # R and B stay 0 until v=128, then ramp to 255 — creates the
        # transition from green to white in the upper half of the range.
        white = np.clip(2.0 * v - 255.0, 0.0, 255.0).astype(np.uint8)
        lut[:, 0] = white
        lut[:, 2] = white
    elif name == 'red_white':
        # R ramps 0→255 scaled by the module-level _RED_BOOST constant.
        # Tune _RED_BOOST to adjust perceived brightness independently of the
        # white blend.  The white onset is fixed at v=128 (same fraction as
        # green_white) so changing _RED_BOOST never shifts when the colour
        # saturates to white.
        boost = red_boost if red_boost is not None else _RED_BOOST
        r = np.clip(v * boost, 0.0, 255.0).astype(np.uint8)
        lut[:, 0] = r
        # White blend: G and B kick in at v=128, independent of boost.
        white = np.clip(2.0 * v - 255.0, 0.0, 255.0).astype(np.uint8)
        lut[:, 1] = white
        lut[:, 2] = white
    elif name == 'red':
        lut[:, 0] = v.astype(np.uint8)
    elif name == 'gray':
        lut[:, 0] = v.astype(np.uint8)
        lut[:, 1] = v.astype(np.uint8)
        lut[:, 2] = v.astype(np.uint8)
    else:  # 'green' (default)
        lut[:, 1] = v.astype(np.uint8)
    return lut


# Module-level display configuration (matching widgets.py conventions)
_DISPLAY_COLORMAP: str = 'green_white'
_DISPLAY_COLORMAP_PMT1: str = 'red_white'
_RED_BOOST: float = 1.963
_HISTOGRAM_COLOR_LEVEL: float = 0.4
_DISPLAY_LUT: np.ndarray = _build_colormap_lut(_DISPLAY_COLORMAP)
# Plain single-colour LUTs used for the overlay (ch==2) colourbar, where the
# canvas draws pure R/G channels without the white-blend transition.
_GREEN_LUT: np.ndarray = _build_colormap_lut('green')
_RED_LUT: np.ndarray = _build_colormap_lut('red')


class HistogramWidget(QtWidgets.QWidget):
    """Pixel-intensity histogram for the current frame.

    Displays a 256-bin histogram of the raw 16-bit pixel values from
    the selected PMT channel(s) of the most recently acquired frame.

    Display conventions
    -------------------
    * The x-axis spans the full 16-bit wire-format range with a **fixed
      scale**: raw value 0 on the left, 65535 on the right.  This makes it
      easy to see how the distribution shifts when PMT gain or Pockels power
      changes.
    * Fixed axis labels "0" and "65535" are painted at the bottom corners.
    * The y-axis can be toggled between linear and logarithmic scale using
      the small button in the top-right corner (labeled "Lin" or "Log").
    * When in logarithmic mode, the scale is ``1 + log10(max(1, count))`` so
      that empty bins (count = 0) map to y = 0 and the display remains
      readable down to single-photon events.

    Performance design
    ------------------
    * ``update_frame`` is a no-op when the widget is hidden, so connecting
      it unconditionally to ``frame_data_ready`` is safe.
    * The histogram is recomputed only every ``UPDATE_EVERY`` frames to keep
      the main thread load negligible even at high frame rates.
    * Data reduction: only every 4th pixel is sampled (``SUBSAMPLE``).
      At 512×512 this reduces the working set from 262 K to 65 K elements
      with no perceptible change in histogram shape.
    * Bin counts use ``np.bincount`` on 16-bit integers, which is 3–5× faster
      than ``np.histogram`` for integer data.
    * ``paintEvent`` uses fully vectorised numpy arithmetic; no per-bin Python
      loop remains.  The polygon and border lines are built from numpy arrays
      converted to Qt objects in a single pass.
    """

    # Number of histogram bins.  256 gives one bin per 8-bit equivalent level.
    NUM_BINS = 256
    # Full-scale value of the 16-bit wire-format data (2^16 - 1).
    # Data from reshape_pmt_data() is in 0–65535 range, matching MATLAB.
    _ADC_MAX = 65535
    # Recompute the histogram only once every this many frames.
    UPDATE_EVERY = 5
    # Stride for pixel subsampling (every Nth pixel used for the histogram).
    SUBSAMPLE = 4

    # Visual constants
    _BG_COLOR = QtGui.QColor("#1a1a1a")
    _AXIS_COLOR = QtGui.QColor("#555555")
    _PADDING = 4        # px inside the widget edges (left / right / top)
    _LABEL_HEIGHT = 11  # px reserved at the bottom for axis tick labels

    # Number of 16-bit values per histogram bin (65536 / 256 = 256).
    _VALUES_PER_BIN = (_ADC_MAX + 1) // NUM_BINS

    def __init__(self):
        """Initialize the histogram widget."""
        super().__init__()
        self._counts: np.ndarray | None = None
        self._counts1: np.ndarray | None = None   # PMT1 counts (overlay mode)
        self._channel: int = 0
        self._frame_counter: int = 0
        self._last_frame: np.ndarray | None = None  # last received frame (used on show)
        self._log_scale: bool = False  # Linear by default
        self.setMinimumHeight(80)
        self.setMinimumWidth(100)
        self.setToolTip(
            "Pixel intensity histogram (256 bins, 16-bit wire-format range)\n"
            "X-axis: 0 = dark background (left) → 65535 = max signal (right)\n"
            "Tracks the channel selected in Image Display > Channel.\n"
            "Mouse wheel to zoom y-axis, double-click to reset.\n"
            "Click 'Linear'/'Log' button to toggle y-scale."
        )
        self._y_zoom = 1.0

        # PMT0 bar/border colours (derived from _DISPLAY_LUT / green_white).
        _bar_idx = int(_HISTOGRAM_COLOR_LEVEL * 255)
        _bar_rgb = _DISPLAY_LUT[_bar_idx]
        self._bar_color = QtGui.QColor(
            int(_bar_rgb[0]), int(_bar_rgb[1]), int(_bar_rgb[2])
        )
        self._border_color = self._bar_color.lighter(130)

        # PMT1 bar/border colours and LUT (red_white, module-level _RED_BOOST).
        _lut1 = _build_colormap_lut(_DISPLAY_COLORMAP_PMT1, red_boost=_RED_BOOST)
        _bar_rgb1 = _lut1[_bar_idx]
        self._bar_color1 = QtGui.QColor(
            int(_bar_rgb1[0]), int(_bar_rgb1[1]), int(_bar_rgb1[2])
        )
        self._border_color1 = self._bar_color1.lighter(130)
        self._lut_pmt1 = _lut1

        # Small toggle button overlaid on the top-right corner.
        self._scale_button = QtWidgets.QPushButton("Linear", self)
        self._scale_button.setCheckable(True)
        self._scale_button.setFixedSize(48, 20)
        self._scale_button.setToolTip(
            "Toggle y-scale between linear and logarithmic.\n"
            "Log scale shows fine structure in weak signal regions."
        )
        self._scale_button.setStyleSheet(
            "QPushButton {"
            "  background: rgba(40,40,40,180);"
            "  color: #cccccc;"
            "  border: 1px solid #555;"
            "  border-radius: 3px;"
            "  font-size: 9px;"
            "}"
            "QPushButton:checked {"
            "  background: rgba(180,140,0,200);"
            "  color: #ffffff;"
            "  border: 1px solid #ffcc00;"
            "}"
            "QPushButton:hover { border: 1px solid #888; }"
        )
        self._scale_button.toggled.connect(self._on_scale_toggled)
        self._reposition_scale_button()

    def _reposition_scale_button(self) -> None:
        """Keep the scale button in the top-right corner of the widget."""
        margin = 4
        btn = self._scale_button
        btn.move(self.width() - btn.width() - margin, margin)
        btn.raise_()

    def _on_scale_toggled(self, checked: bool) -> None:
        """Handle log/linear scale toggle."""
        self._log_scale = checked
        self._scale_button.setText("Log" if checked else "Linear")
        #self._y_zoom = 1.0  # Reset zoom so the full range is visible in the new scale
        self.update()  # Repaint with new scale

    def resizeEvent(self, event) -> None:
        """Reposition the scale button when widget is resized."""
        super().resizeEvent(event)
        self._reposition_scale_button()

    def setVisible(self, visible: bool) -> None:  # noqa: N802 (Qt naming)
        """Show or hide the histogram; render the last frame immediately on show.

        When the widget is made visible after being hidden (e.g. via the View
        menu toggle), the histogram is populated with the most recently
        received frame so it never appears empty after acquisition has stopped.

        Args:
            visible: True to show, False to hide.
        """
        super().setVisible(visible)
        if visible and self._last_frame is not None:
            self._compute_histogram(self._last_frame)

    def update_frame(self, frame_data: np.ndarray) -> None:
        """Recompute the histogram from a newly acquired frame.

        This slot is safe to connect permanently to ``frame_data_ready``:
        it returns immediately when the widget is hidden or when the
        frame-skip counter has not yet reached ``UPDATE_EVERY``.

        Accepts the same ``frame_data_ready`` signal payload as
        ``ImageDisplayWidget.update_frame``.  Only channel 0 is used.

        Args:
            frame_data: Shape ``(channels, lines_per_frame, pixels_per_line)``,
                dtype ``uint16``, values 0–65535 (16-bit wire format).
        """
        if frame_data is None:
            return
        self._last_frame = frame_data  # always cache for on-show rendering
        if not self.isVisible():
            return
        self._frame_counter += 1
        if self._frame_counter % self.UPDATE_EVERY != 0:
            return
        self._compute_histogram(frame_data)

    def force_update_frame(self, frame_data: np.ndarray) -> None:
        """Recompute the histogram immediately, bypassing the frame throttle.

        Use this when displaying a specific frame from a loaded recording so
        that every slider move produces an instant histogram update regardless
        of ``UPDATE_EVERY``.  The frame is always cached in ``_last_frame``
        so that opening the histogram widget after loading a recording shows
        the current frame even if the widget was hidden when this was called.

        Args:
            frame_data: Shape ``(channels, lines_per_frame, pixels_per_line)``,
                dtype ``uint16``, values 0–65535 (16-bit wire format).
        """
        if frame_data is None:
            return
        self._last_frame = frame_data  # always cache for on-show rendering
        if not self.isVisible():
            return
        self._compute_histogram(frame_data)

    def set_channel(self, index: int) -> None:
        """Set the channel shown in the histogram to match the image display.

        Args:
            index: 0 = PMT0 (green colormap), 1 = PMT1 (red colormap),
                2 = both channels overlaid with semi-transparency and a
                vertically split colourbar.
        """
        self._channel = index
        self.update()

    def _compute_histogram(self, frame_data: np.ndarray) -> None:
        """Compute bin counts from *frame_data* and schedule a repaint.

        Always computes counts for both channels so the display can switch
        channel without waiting for the next frame.

        Args:
            frame_data: Shape ``(channels, lines_per_frame, pixels_per_line)``,
                dtype ``uint16``, values 0–65535 (16-bit wire format).
        """
        def _bincount(ch_data: np.ndarray) -> np.ndarray:
            flat = ch_data.ravel()[::self.SUBSAMPLE]
            flat = np.clip(flat, 0, self._ADC_MAX)
            full = np.bincount(flat, minlength=self._ADC_MAX + 1)
            return full.reshape(self.NUM_BINS, self._VALUES_PER_BIN).sum(axis=1)

        n_ch = frame_data.shape[0]
        self._counts = _bincount(frame_data[0])
        self._counts1 = _bincount(frame_data[min(1, n_ch - 1)]) if n_ch >= 2 else None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802  (Qt naming convention)
        """Paint the histogram bars and axis labels using QPainter.

        Rendering depends on the active channel:

        * **PMT0 (channel 0)**: green bars, green_white colourbar.
        * **PMT1 (channel 1)**: red bars, red_white colourbar.
        * **Both (channel 2)**: both histograms drawn at 60 % opacity over
          each other; colourbar split vertically (green_white left, red_white
          right).

        Args:
            event: QPaintEvent from Qt (unused; full repaint every time).
        """
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)

        w = self.width()
        h = self.height()
        p = self._PADDING
        lh = self._LABEL_HEIGHT

        # Background
        painter.fillRect(0, 0, w, h, self._BG_COLOR)

        if self._counts is None:
            painter.setPen(QtGui.QPen(self._AXIS_COLOR))
            painter.drawText(
                QtCore.QRect(0, 0, w, h),
                QtCore.Qt.AlignmentFlag.AlignCenter,
                "Histogram",
            )
            painter.end()
            return

        # --- Select which counts / colours to use ---
        ch = self._channel
        use_both = (ch in (2, 3) and self._counts1 is not None)
        if ch == 1:
            # PMT1: use _counts1 for two-channel recordings, _counts for
            # single-channel PMT1 recordings (where nchan=1 and the single
            # stored channel is physically PMT1).
            counts_a   = (self._counts1 if self._counts1 is not None
                          else self._counts)[::-1].copy()
            bar_col_a  = self._bar_color1
            brd_col_a  = self._border_color1
            lut_a      = self._lut_pmt1
            counts_b   = None
        elif use_both:
            counts_a   = self._counts[::-1].copy()
            bar_col_a  = self._bar_color
            brd_col_a  = self._border_color
            lut_a      = _DISPLAY_LUT
            counts_b   = self._counts1[::-1].copy()
        else:  # PMT0 (default)
            counts_a   = self._counts[::-1].copy()
            bar_col_a  = self._bar_color
            brd_col_a  = self._border_color
            lut_a      = _DISPLAY_LUT
            counts_b   = None

        # --- Chart geometry ---
        chart_bottom = h - lh
        draw_w = w - 2 * p
        draw_h = chart_bottom - p
        n = self.NUM_BINS

        # --- Compute y-scale ---
        if self._log_scale:
            # Logarithmic scale: 1 + log10(max(1, count)) so that 0 → 0, 1 → 1, 10 → 2, etc.
            log_counts_a = np.log10(np.maximum(counts_a, 1.0)) + 1.0
            max_a = float(log_counts_a[1:].max()) if n > 1 else 1.0
            if counts_b is not None:
                log_counts_b = np.log10(np.maximum(counts_b, 1.0)) + 1.0
                max_b = float(log_counts_b[1:].max()) if n > 1 else 1.0
                auto_max = max(max_a, max_b, 1.0)
            else:
                auto_max = max(max_a, 1.0)
        else:
            # Linear scale: exclude bin 0 (dark background spike).
            max_a = int(counts_a[1:].max()) if n > 1 else 1
            if counts_b is not None:
                max_b = int(counts_b[1:].max()) if n > 1 else 1
                auto_max = max(max_a, max_b, 1)
            else:
                auto_max = max(max_a, 1)

        # Apply user zoom (wheel scroll)
        max_count = max(1, int(auto_max / self._y_zoom))

        # --- Vectorised x coordinates (shared for both channels) ---
        indices  = np.arange(n)
        xs_left  = (p + indices       * draw_w // n).astype(np.int32)
        xs_right = (p + (indices + 1) * draw_w // n).astype(np.int32)
        xs_right = np.maximum(xs_right, xs_left + 1)

        def _draw_bars(
            cnt: np.ndarray,
            bar_color: QtGui.QColor,
            border_color: QtGui.QColor,
        ) -> None:
            """Draw one set of histogram bars at the current painter opacity."""
            if self._log_scale:
                scaled = np.log10(np.maximum(cnt, 1.0)) + 1.0
            else:
                scaled = cnt.astype(np.float32)
            clamped     = np.minimum(scaled, max_count)
            bar_heights = (clamped * draw_h / max_count).astype(np.int32)
            y_tops      = (chart_bottom - bar_heights).astype(np.int32)

            pts = np.empty((2 * n + 2, 2), dtype=np.int32)
            pts[0:2*n:2, 0] = xs_left
            pts[1:2*n:2, 0] = xs_right
            pts[0:2*n:2, 1] = y_tops
            pts[1:2*n:2, 1] = y_tops
            pts[2*n]     = [w - p, chart_bottom]
            pts[2*n + 1] = [p, chart_bottom]

            poly = QtGui.QPolygon([QtCore.QPoint(x, y) for x, y in pts.tolist()])
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QBrush(bar_color))
            painter.drawPolygon(poly)

            painter.setPen(QtGui.QPen(border_color, 1))
            painter.drawLines([
                QtCore.QLine(x1, y, x2, y)
                for x1, y, x2 in zip(xs_left.tolist(), y_tops.tolist(), xs_right.tolist())
            ])

        if use_both:
            painter.setOpacity(0.6)
            _draw_bars(counts_a, bar_col_a, brd_col_a)
            _draw_bars(counts_b, self._bar_color1, self._border_color1)
            painter.setOpacity(1.0)
        else:
            _draw_bars(counts_a, bar_col_a, brd_col_a)

        # --- Baseline ---
        painter.setPen(QtGui.QPen(self._AXIS_COLOR, 1))
        painter.drawLine(p, chart_bottom, w - p, chart_bottom)

        # --- Colourbar in the label strip ---
        if use_both:
            half_h = lh // 2
            # Overlay (ch==2): the canvas composites pure R and G channels
            # without the white-blend LUT, so use plain green/red colorbars.
            # Side-by-side (ch==3): the canvas applies the full green_white /
            # red_white LUTs, so the colorbars match.
            if ch == 2:
                cb0 = np.ascontiguousarray(_GREEN_LUT)
                cb1 = np.ascontiguousarray(_RED_LUT)
            else:  # ch == 3, dual-canvas
                cb0 = np.ascontiguousarray(_DISPLAY_LUT)
                cb1 = np.ascontiguousarray(self._lut_pmt1)
            img0 = QtGui.QImage(cb0.data, 256, 1, 256*3, QtGui.QImage.Format.Format_RGB888)
            img1 = QtGui.QImage(cb1.data, 256, 1, 256*3, QtGui.QImage.Format.Format_RGB888)
            painter.drawImage(QtCore.QRect(p, chart_bottom,          draw_w, half_h),       img0)
            painter.drawImage(QtCore.QRect(p, chart_bottom + half_h, draw_w, lh - half_h),  img1)
        else:
            cb = np.ascontiguousarray(lut_a)
            cb_img = QtGui.QImage(cb.data, 256, 1, 256*3, QtGui.QImage.Format.Format_RGB888)
            painter.drawImage(QtCore.QRect(p, chart_bottom, draw_w, lh), cb_img)

        # --- Axis labels: "0" (left) and "65535" (right) ---
        def _label_pen(lut: np.ndarray, idx: int) -> QtGui.QPen:
            r, g, b = int(lut[idx, 0]), int(lut[idx, 1]), int(lut[idx, 2])
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            c = QtGui.QColor(0, 0, 0) if lum > 128 else QtGui.QColor(255, 255, 255)
            return QtGui.QPen(c)

        font = painter.font()
        font.setPointSize(7)
        painter.setFont(font)
        painter.setPen(_label_pen(lut_a, 0))
        painter.drawText(
            QtCore.QRect(p, chart_bottom, draw_w // 2, lh),
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            "0",
        )
        right_lut = self._lut_pmt1 if use_both else lut_a
        painter.setPen(_label_pen(right_lut, 255))
        painter.drawText(
            QtCore.QRect(p + draw_w // 2, chart_bottom, draw_w // 2, lh),
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
            str(self._ADC_MAX),
        )

        painter.end()

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: N802
        """Adjust the y-axis zoom factor on mouse wheel scroll.

        Scrolling up zooms in (makes bars taller); scrolling down zooms out.
        """
        delta = event.angleDelta().y()
        if delta > 0:
            self._y_zoom *= 1.2
        elif delta < 0:
            self._y_zoom /= 1.2

        # Clamp zoom to sensible limits (0.1x to 100x)
        self._y_zoom = max(0.1, min(self._y_zoom, 100.0))
        self.update()

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        """Reset the y-axis zoom to 1.0 on double-click."""
        self._reset_y_zoom()

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:  # noqa: N802
        """Show the right-click context menu."""
        menu = QtWidgets.QMenu(self)
        reset_action = menu.addAction("Reset y-zoom")
        reset_action.triggered.connect(self._reset_y_zoom)
        menu.exec(event.globalPos())

    def _reset_y_zoom(self) -> None:
        """Reset the y-axis zoom factor to 1.0."""
        self._y_zoom = 1.0
        self.update()
