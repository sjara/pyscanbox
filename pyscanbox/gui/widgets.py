"""Widget components for pyscanbox GUI.

This module defines individual control groups and display widgets:
- LaserControlGroup: Laser power, shutter, wavelength
- ScannerControlGroup: Scanner parameters (frames, lines, mag, etc.)
- PositionDisplayGroup: Position coordinates display
- AcquisitionControlGroup: Acquisition buttons and status
- FileStorageGroup: File path and metadata
- ImageDisplayWidget: Main image display
- HistogramWidget: Pixel-intensity histogram below the image
- CameraPathGroup: Camera controls
- PMTControlGroup: PMT gain controls
- ImageDisplayControlGroup: Display settings
- OptotuneGroup: ETL control
"""

import numpy as np
import PyQt6.QtWidgets as QtWidgets
import PyQt6.QtCore as QtCore

from pyscanbox.hardware import controller as hw_controller
import PyQt6.QtGui as QtGui


class LaserControlGroup(QtWidgets.QGroupBox):
    """Laser control group box.
    
    Contains:
    - Wavelength spinbox
    - Power slider (horizontal, Pockels control)
    """
    
    def __init__(self, config=None):
        """Initialize the laser control group.
        
        Args:
            config: Optional ScanboxConfig object (unused but kept for compatibility).
        """
        super().__init__("Laser")
        self.config = config
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout()
        
        # Wavelength
        wavelength_layout = QtWidgets.QHBoxLayout()
        wavelength_layout.addWidget(QtWidgets.QLabel("Wavelength:"))
        self.wavelength_spinbox = QtWidgets.QSpinBox()
        self.wavelength_spinbox.setRange(680, 1100)
        self.wavelength_spinbox.setValue(920)
        self.wavelength_spinbox.setSuffix(" nm")
        wavelength_layout.addWidget(self.wavelength_spinbox)
        layout.addLayout(wavelength_layout)
        
        # Power slider (Pockels control)
        power_layout = QtWidgets.QVBoxLayout()
        power_layout.addWidget(QtWidgets.QLabel("Power (Pockels)"))
        
        self.power_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.power_slider.setRange(0, 100)
        self.power_slider.setValue(0)
        self.power_slider.setTickPosition(QtWidgets.QSlider.TickPosition.TicksBelow)
        self.power_slider.setTickInterval(10)
        self.power_slider.setSingleStep(2)  # 2% step for mouse wheel
        power_layout.addWidget(self.power_slider)
        
        self.power_label = QtWidgets.QLabel("0%")
        self.power_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        power_layout.addWidget(self.power_label)
        
        self.power_slider.valueChanged.connect(
            lambda v: self.power_label.setText(f"{v}%")
        )
        
        layout.addLayout(power_layout)
        self.setLayout(layout)


class ScannerControlGroup(QtWidgets.QGroupBox):
    """Scanner control group box.
    
    Contains:
    - Total frames spinbox
    - Lines/frame spinbox
    - Magnification combobox
    - Frame rate label/spinbox
    - Scan mode selector (unidirectional/bidirectional)
    """
    
    def __init__(self):
        """Initialize the scanner control group."""
        super().__init__("Scanner")
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QFormLayout()
        
        # Total frames
        self.total_frames_spinbox = QtWidgets.QSpinBox()
        self.total_frames_spinbox.setRange(0, 1000000)
        self.total_frames_spinbox.setValue(0)
        layout.addRow("Total frames:", self.total_frames_spinbox)
        
        # Lines/frame
        self.lines_per_frame_spinbox = QtWidgets.QSpinBox()
        self.lines_per_frame_spinbox.setRange(16, 2048)
        self.lines_per_frame_spinbox.setValue(512)
        self.lines_per_frame_spinbox.setSingleStep(16)
        layout.addRow("Lines/frame:", self.lines_per_frame_spinbox)
        
        # Magnification — 13 discrete zoom levels.
        # Labels come from ScanboxController.MAG_LABELS, the single source of
        # truth (hardware zoom amplitudes from sbconfig.gain_galvo).
        # Index 0–12 is sent directly to the PSoC5 controller (CMD_MAGNIFICATION).
        self.magnification_combobox = QtWidgets.QComboBox()
        self.magnification_combobox.addItems(
            hw_controller.ScanboxController.MAG_LABELS
        )
        self.magnification_combobox.setCurrentIndex(0)  # index 0 = minimum zoom (1.0x)
        layout.addRow("Magnification:", self.magnification_combobox)
        
        # Frame rate — computed from RESONANT_FREQ / lines * (2 if bidir else 1).
        # Matches MATLAB: frame_rate = sbconfig.resfreq/nlines*(2-scanmode)
        initial_rate = hw_controller.ScanboxController.calculate_frame_rate(
            self.lines_per_frame_spinbox.value(), bidirectional=False
        )
        self.frame_rate_label = QtWidgets.QLabel(f"{initial_rate:.2f} Hz")
        layout.addRow("Frame rate:", self.frame_rate_label)
        
        # Scan mode selector (combo box)
        self.scan_mode_combobox = QtWidgets.QComboBox()
        self.scan_mode_combobox.addItems(["Unidirectional", "Bidirectional"])
        self.scan_mode_combobox.setCurrentIndex(0)
        layout.addRow("Scan mode:", self.scan_mode_combobox)
        
        # Bidirectional alignment control
        self.bidir_alignment_spinbox = QtWidgets.QSpinBox()
        self.bidir_alignment_spinbox.setRange(-100, 100)
        self.bidir_alignment_spinbox.setValue(0)
        layout.addRow("Bidir alignment:", self.bidir_alignment_spinbox)
        
        # Update frame rate whenever lines or scan mode changes.
        self.lines_per_frame_spinbox.valueChanged.connect(self._update_frame_rate)
        self.scan_mode_combobox.currentIndexChanged.connect(self._update_frame_rate)
        
        self.setLayout(layout)

    def _update_frame_rate(self):
        """Recompute and display the frame rate from lines/frame and scan mode.

        Formula (scanbox.m line 503):
            frame_rate = sbconfig.resfreq / nlines * (2 - scanmode)
        where scanmode = 1 (unidirectional) or 0 (bidirectional).
        """
        lines = self.lines_per_frame_spinbox.value()
        bidirectional = self.scan_mode_combobox.currentIndex() == 1  # 0=Uni, 1=Bi
        rate = hw_controller.ScanboxController.calculate_frame_rate(lines, bidirectional)
        self.frame_rate_label.setText(f"{rate:.2f} Hz")


class PositionDisplayGroup(QtWidgets.QGroupBox):
    """Position display group box.

    Contains four rows of read-only coordinate fields:

    - **Angle**: A-axis (objective tilt in degrees).
    - **World (μm)**: Knobby ``dpos`` in physical units — relative position
      from the last zero, matching what the Knobby screen displays.
    - **Abs (μm)**: Absolute motor hardware step counter in physical units,
      polled from the Trinamic board every 100 ms.  Useful for debugging to
      confirm that commanded moves reached the hardware.
    - **Rotated (μm)**: Reserved for the future angle-compensation mode
      (Knobby rotate mode, where Z becomes the objective axis when the
      objective is tilted).  Currently mirrors the World row.
    """

    def __init__(self):
        """Initialize the position display group."""
        super().__init__("Objective Position")
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QGridLayout()

        # Objective angle
        layout.addWidget(QtWidgets.QLabel("Angle:"), 0, 0)
        self.objective_angle_edit = QtWidgets.QLineEdit("0.0°")
        self.objective_angle_edit.setReadOnly(True)
        layout.addWidget(self.objective_angle_edit, 0, 1, 1, 3)

        # X, Y, Z column headers
        layout.addWidget(QtWidgets.QLabel("X"), 1, 1, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(QtWidgets.QLabel("Y"), 1, 2, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(QtWidgets.QLabel("Z"), 1, 3, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

        # Row 2: World coordinates (Knobby dpos — matches Knobby screen)
        layout.addWidget(QtWidgets.QLabel("World (μm):"), 2, 0)
        self.world_x_edit = QtWidgets.QLineEdit("0.00")
        self.world_x_edit.setReadOnly(True)
        self.world_x_edit.setMaximumWidth(70)
        layout.addWidget(self.world_x_edit, 2, 1)

        self.world_y_edit = QtWidgets.QLineEdit("0.00")
        self.world_y_edit.setReadOnly(True)
        self.world_y_edit.setMaximumWidth(70)
        layout.addWidget(self.world_y_edit, 2, 2)

        self.world_z_edit = QtWidgets.QLineEdit("0.00")
        self.world_z_edit.setReadOnly(True)
        self.world_z_edit.setMaximumWidth(70)
        layout.addWidget(self.world_z_edit, 2, 3)

        # Row 3: Absolute motor hardware positions (polled from Trinamic board)
        layout.addWidget(QtWidgets.QLabel("Abs (μm):"), 3, 0)
        self.abs_x_edit = QtWidgets.QLineEdit("0.00")
        self.abs_x_edit.setReadOnly(True)
        self.abs_x_edit.setMaximumWidth(70)
        layout.addWidget(self.abs_x_edit, 3, 1)

        self.abs_y_edit = QtWidgets.QLineEdit("0.00")
        self.abs_y_edit.setReadOnly(True)
        self.abs_y_edit.setMaximumWidth(70)
        layout.addWidget(self.abs_y_edit, 3, 2)

        self.abs_z_edit = QtWidgets.QLineEdit("0.00")
        self.abs_z_edit.setReadOnly(True)
        self.abs_z_edit.setMaximumWidth(70)
        layout.addWidget(self.abs_z_edit, 3, 3)

        # Row 4: Rotated coordinates (reserved — angle-compensated, future)
        layout.addWidget(QtWidgets.QLabel("Rotated (μm):"), 4, 0)
        self.rotated_x_edit = QtWidgets.QLineEdit("0.00")
        self.rotated_x_edit.setReadOnly(True)
        self.rotated_x_edit.setMaximumWidth(70)
        layout.addWidget(self.rotated_x_edit, 4, 1)

        self.rotated_y_edit = QtWidgets.QLineEdit("0.00")
        self.rotated_y_edit.setReadOnly(True)
        self.rotated_y_edit.setMaximumWidth(70)
        layout.addWidget(self.rotated_y_edit, 4, 2)

        self.rotated_z_edit = QtWidgets.QLineEdit("0.00")
        self.rotated_z_edit.setReadOnly(True)
        self.rotated_z_edit.setMaximumWidth(70)
        layout.addWidget(self.rotated_z_edit, 4, 3)

        self.setLayout(layout)


class AcquisitionControlGroup(QtWidgets.QGroupBox):
    """Acquisition control group box.
    
    Contains:
    - Focus and Grab buttons
    - Frames collected counter
    - Time recorded counter
    - Snapshot and Load buttons
    """
    
    def __init__(self):
        """Initialize the acquisition control group."""
        super().__init__("Acquisition Control")
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout()
        
        # Top row: Focus and Grab buttons
        top_row = QtWidgets.QHBoxLayout()
        self.focus_button = QtWidgets.QPushButton("Focus")
        self.focus_button.setCheckable(True)
        self.focus_button.setStyleSheet(
            "QPushButton { min-height: 40px; font-size: 14px; }"
        )
        self.focus_button.clicked.connect(self._on_focus_toggle)
        top_row.addWidget(self.focus_button)
        
        self.grab_button = QtWidgets.QPushButton("Grab")
        self.grab_button.setCheckable(True)
        self.grab_button.setStyleSheet(
            "QPushButton { min-height: 40px; font-size: 14px; }"
        )
        self.grab_button.clicked.connect(self._on_grab_toggle)
        top_row.addWidget(self.grab_button)
        layout.addLayout(top_row)
        
        # Middle row: Status labels
        middle_row = QtWidgets.QHBoxLayout()
        
        frames_layout = QtWidgets.QVBoxLayout()
        frames_layout.addWidget(QtWidgets.QLabel("Frames collected:"))
        self.frames_label = QtWidgets.QLabel("0")
        self.frames_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.frames_label.setStyleSheet(
            "QLabel { font-size: 16px; font-weight: bold; }"
        )
        frames_layout.addWidget(self.frames_label)
        middle_row.addLayout(frames_layout)
        
        time_layout = QtWidgets.QVBoxLayout()
        time_layout.addWidget(QtWidgets.QLabel("Time recorded:"))
        self.time_label = QtWidgets.QLabel("0:00:00")
        self.time_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.time_label.setStyleSheet(
            "QLabel { font-size: 16px; font-weight: bold; }"
        )
        time_layout.addWidget(self.time_label)
        middle_row.addLayout(time_layout)
        
        layout.addLayout(middle_row)
        
        # Bottom row: Snapshot and Load buttons
        bottom_row = QtWidgets.QHBoxLayout()
        self.snapshot_button = QtWidgets.QPushButton("Snapshot")
        bottom_row.addWidget(self.snapshot_button)
        
        self.load_button = QtWidgets.QPushButton("Load")
        bottom_row.addWidget(self.load_button)
        layout.addLayout(bottom_row)
        
        self.setLayout(layout)
        
    def _on_focus_toggle(self, checked):
        """Handle focus button toggle.
        
        Args:
            checked: True if focus mode is active.
        """
        if checked:
            self.focus_button.setText("Stop")
        else:
            self.focus_button.setText("Focus")
            
    def _on_grab_toggle(self, checked):
        """Handle grab button toggle.
        
        Args:
            checked: True if grab mode is active.
        """
        if checked:
            self.grab_button.setText("Abort")
        else:
            self.grab_button.setText("Grab")


# Fallback values used when file-storage fields are left empty.
# Defined once here so widgets.py and any caller share the same defaults.
DEFAULT_SUBJECT = "_"
DEFAULT_DATE = "_"
DEFAULT_SESSION = "_"


class FileStorageGroup(QtWidgets.QGroupBox):
    """File storage group box.
    
    Contains:
    - Directory selection button and path display
    - Subject, Date, Session ID fields
    - Save channels selector
    """
    
    def __init__(self, config=None):
        """Initialize the file storage group.

        Args:
            config: Optional configuration dict or ScanboxConfig.  When
                provided, the directory field is seeded from
                config['io']['output_directory'].
        """
        super().__init__("File Storage")
        self.config = config
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QGridLayout()
        
        # Directory selection
        dir_row = 0
        self.directory_button = QtWidgets.QPushButton("Directory")
        self.directory_button.clicked.connect(self._select_directory)
        layout.addWidget(self.directory_button, dir_row, 0)
        
        self.directory_edit = QtWidgets.QLineEdit()
        self.directory_edit.setReadOnly(True)
        default_dir = (
            self.config.get('io', {}).get('output_directory', '/data/')
            if self.config is not None
            else '/data/'
        )
        self.directory_edit.setText(default_dir)
        layout.addWidget(self.directory_edit, dir_row, 1)
        
        # Filename preview label
        self.filename_label = QtWidgets.QLabel("Filename: _.sbx")
        self.filename_label.setStyleSheet("QLabel { color: #666; font-style: italic; }")
        layout.addWidget(self.filename_label, 1, 0, 1, 2)
        
        # Metadata fields
        layout.addWidget(QtWidgets.QLabel("Subject:"), 2, 0)
        self.subject_edit = QtWidgets.QLineEdit()
        self.subject_edit.setPlaceholderText("Subject ID")
        self.subject_edit.textChanged.connect(self._update_filename)
        layout.addWidget(self.subject_edit, 2, 1)
        
        layout.addWidget(QtWidgets.QLabel("Date:"), 3, 0)
        self.date_edit = QtWidgets.QLineEdit()
        self.date_edit.setPlaceholderText("YYYYMMDD")
        from datetime import datetime
        self.date_edit.setText(datetime.now().strftime("%Y%m%d"))
        self.date_edit.textChanged.connect(self._update_filename)
        layout.addWidget(self.date_edit, 3, 1)
        
        layout.addWidget(QtWidgets.QLabel("Session ID:"), 4, 0)
        self.session_edit = QtWidgets.QLineEdit()
        self.session_edit.setPlaceholderText("001")
        self.session_edit.textChanged.connect(self._update_filename)
        layout.addWidget(self.session_edit, 4, 1)
        
        # Save channels selector
        layout.addWidget(QtWidgets.QLabel("Save Channels:"), 5, 0)
        self.channels_combobox = QtWidgets.QComboBox()
        self.channels_combobox.addItems(["PMT0", "PMT1", "PMT0 & PMT1"])
        self.channels_combobox.setCurrentIndex(0)
        layout.addWidget(self.channels_combobox, 5, 1)
        
        self.setLayout(layout)
        
        # Update filename initially
        self._update_filename()
        
    def _update_filename(self):
        """Update the filename preview based on metadata fields."""
        subject = self.subject_edit.text() or DEFAULT_SUBJECT
        date = self.date_edit.text() or DEFAULT_DATE
        session = self.session_edit.text() or DEFAULT_SESSION
        filename = f"{subject}_{date}_{session}.sbx"
        self.filename_label.setText(f"Filename: {filename}")

    def get_output_basename(self):
        """Return the output file base name with fallbacks applied.

        Combines subject, date, and session fields using the same fallback
        constants as the filename preview label.  Callers (e.g. MainWindow)
        should use this rather than reading individual fields directly.

        Returns:
            Base name string without extension, e.g. 'mouse01_20260301_001'.
        """
        subject = self.subject_edit.text() or DEFAULT_SUBJECT
        date = self.date_edit.text() or DEFAULT_DATE
        session = self.session_edit.text() or DEFAULT_SESSION
        return f"{subject}_{date}_{session}"

    def _select_directory(self):
        """Open directory selection dialog."""
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Data Directory", self.directory_edit.text()
        )
        if directory:
            self.directory_edit.setText(directory)


class ImageDisplayWidget(QtWidgets.QWidget):
    """Main image display widget for real-time frame visualization.

    Displays the most recently acquired frame as a grayscale image.  The
    frame data (numpy array) is delivered by calling ``update_frame()``
    which is connected to ``AppController.frame_data_ready`` in
    ``MainWindow._connect_hardware()``.

    Channel selection and other display controls (colormap, histogram, …)
    are deferred to Milestone 2.3.2 (Advanced Visualization).  Currently
    channel 0 (PMT0) is always displayed.
    """

    # Slider range is 1–100; gain = slider_value / 10  (0.1x … 10.0x).
    # Default slider value is 10, giving gain = 1.0 which preserves the
    # original >> 6 behaviour (14-bit → 8-bit with no clipping).
    _GAIN_DIVISOR = 10.0

    def __init__(self):
        """Initialize the image display widget."""
        super().__init__()
        # Holds the current uint8 frame buffer so that the QImage's memory
        # reference stays valid until the next frame arrives.
        self._display_buffer: np.ndarray | None = None
        self._gain: float = 1.0
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout()

        self.image_label = QtWidgets.QLabel()
        self.image_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(1, 1)
        self.image_label.setStyleSheet("background-color: #1e1e1e; color: #969696;")
        self.image_label.setText("Image Display\n(Live preview will appear here)")
        self.image_label.setFont(QtGui.QFont("Arial", 14))

        layout.addWidget(self.image_label)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

    def update_frame(self, frame_data: np.ndarray) -> None:
        """Update the display with a newly acquired frame.

        Converts channel 0 (PMT0) of the 14-bit frame array to an 8-bit
        grayscale QPixmap and scales it to fill the label while preserving
        the aspect ratio.

        This slot is called from the GUI thread via a queued signal
        connection; the numpy array is passed by reference and is safe to
        read because the Scanner creates a fresh array for every frame.

        Args:
            frame_data: Shape ``(channels, lines_per_frame, pixels_per_line)``,
                dtype ``uint16``, values 0-16383 (14-bit).  Only channel 0
                is displayed; channel selection will be added in 2.3.2.
        """
        if frame_data is None:
            return  # stale queued signal delivered after scanner cleanup
        # Extract channel 0 and scale the 14-bit values to 8-bit, applying
        # the display gain set by the Image Display > Gain slider.
        # Base divisor 64 (>> 6) maps full-scale 14-bit to 255; multiplying
        # by _gain before clipping brightens or dims the image accordingly.
        ch0 = frame_data[0]  # shape: (lines, pixels)
        scaled = np.clip(
            ch0.astype(np.float32) * self._gain / 64.0, 0, 255
        )
        self._display_buffer = np.ascontiguousarray(scaled, dtype=np.uint8)
        height, width = self._display_buffer.shape

        # Wrap the numpy buffer in a QImage without copying.
        # _display_buffer keeps the memory alive until the next call.
        img = QtGui.QImage(
            self._display_buffer.data,
            width,
            height,
            width,  # bytes per line (1 byte per pixel, no padding)
            QtGui.QImage.Format.Format_Grayscale8,
        )

        pixmap = QtGui.QPixmap.fromImage(img)
        self.image_label.setPixmap(
            pixmap.scaled(
                self.image_label.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.FastTransformation,
            )
        )

    def set_gain(self, slider_value: int) -> None:
        """Update the display gain from the Image Display gain slider.

        Args:
            slider_value: Integer value from the gain slider (1–100).
                The effective multiplier is ``slider_value / _GAIN_DIVISOR``
                (i.e. 0.1× – 10.0×).  The change takes effect on the next
                call to ``update_frame``.
        """
        self._gain = slider_value / self._GAIN_DIVISOR


class HistogramWidget(QtWidgets.QWidget):
    """Pixel-intensity histogram for the current frame.

    Displays a 256-bin histogram of the raw 14-bit pixel values from
    channel 0 (PMT0) of the most recently acquired frame.  The widget
    repaints itself every time ``update_frame`` is called.

    The y-axis auto-scales to the maximum bin count, excluding the very
    first bin (value == 0) which is often dominated by the dark background
    and would otherwise compress all other bars to near-zero height.
    """

    # Number of histogram bins.  256 gives one bin per 8-bit equivalent level.
    NUM_BINS = 256
    # Full-scale value of the 14-bit ADC.
    _ADC_MAX = 16383

    # Visual constants
    _BG_COLOR = QtGui.QColor("#1a1a1a")
    _BAR_COLOR = QtGui.QColor("#4a7eb5")
    _BORDER_COLOR = QtGui.QColor("#6aaedf")
    _AXIS_COLOR = QtGui.QColor("#555555")
    _PADDING = 4  # px inside the widget edges

    def __init__(self):
        """Initialize the histogram widget."""
        super().__init__()
        self._counts: np.ndarray | None = None
        self.setMinimumHeight(80)
        self.setMaximumHeight(120)
        self.setMinimumWidth(100)
        self.setToolTip("Pixel intensity histogram (channel 0, 256 bins, 14-bit range)")

    def update_frame(self, frame_data: np.ndarray) -> None:
        """Recompute the histogram from a newly acquired frame.

        Accepts the same ``frame_data_ready`` signal payload as
        ``ImageDisplayWidget.update_frame``.  Only channel 0 is used.

        Args:
            frame_data: Shape ``(channels, lines_per_frame, pixels_per_line)``,
                dtype ``uint16``, values 0–16383 (14-bit).
        """
        if frame_data is None:
            return
        ch0 = frame_data[0].ravel()  # flatten to 1-D
        self._counts, _ = np.histogram(
            ch0, bins=self.NUM_BINS, range=(0, self._ADC_MAX + 1)
        )
        self.update()  # schedule a repaint

    def paintEvent(self, event) -> None:  # noqa: N802  (Qt naming convention)
        """Paint the histogram bars using QPainter.

        Draws a filled area chart: a vertical bar for each of the 256 bins
        scaled to fill the available height.  The y-axis is auto-scaled to
        the maximum count across bins 1–255 (bin 0, the zero-valued pixels,
        is excluded from scaling because it is typically orders of magnitude
        larger than the signal bins and would squash the useful part of the
        histogram).

        Args:
            event: QPaintEvent from Qt (unused; we always repaint fully).
        """
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)

        w = self.width()
        h = self.height()
        p = self._PADDING

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

        # Auto-scale: ignore bin 0 (background) for the y-maximum.
        max_count = int(self._counts[1:].max()) if len(self._counts) > 1 else 1
        if max_count == 0:
            max_count = 1

        draw_w = w - 2 * p
        draw_h = h - 2 * p
        n = len(self._counts)

        # Build a polygon for the filled area (faster than n separate fillRect calls).
        # Points go left→right along the top of each bar, then close at the bottom.
        poly = QtGui.QPolygon()
        for i, count in enumerate(self._counts):
            bar_h = int(min(count, max_count) / max_count * draw_h)
            x = p + int(i * draw_w / n)
            y_top = h - p - bar_h
            poly.append(QtCore.QPoint(x, y_top))
            poly.append(QtCore.QPoint(x + max(1, int(draw_w / n)), y_top))
        # Close the polygon along the bottom edge.
        poly.append(QtCore.QPoint(w - p, h - p))
        poly.append(QtCore.QPoint(p, h - p))

        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(self._BAR_COLOR))
        painter.drawPolygon(poly)

        # Thin bright border along the top of the histogram
        painter.setPen(QtGui.QPen(self._BORDER_COLOR, 1))
        for i, count in enumerate(self._counts):
            bar_h = int(min(count, max_count) / max_count * draw_h)
            x = p + int(i * draw_w / n)
            y_top = h - p - bar_h
            x2 = p + int((i + 1) * draw_w / n)
            painter.drawLine(x, y_top, x2, y_top)

        # Baseline
        painter.setPen(QtGui.QPen(self._AXIS_COLOR, 1))
        painter.drawLine(p, h - p, w - p, h - p)

        painter.end()


class CameraPathGroup(QtWidgets.QGroupBox):
    """Camera path control group box.
    
    Contains:
    - Enable checkbox
    - Exposure slider
    - Camera properties button
    """
    
    def __init__(self):
        """Initialize the light path group."""
        super().__init__("Light Path")
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout()

        # Enable checkbox + current path-state label on the same row.
        # The label shows 'Epi' when the checkbox is checked (camera/epi
        # path active) and '2p' when unchecked (2-photon path active).
        enable_row = QtWidgets.QHBoxLayout()
        self.enable_checkbox = QtWidgets.QCheckBox("Camera Path")
        enable_row.addWidget(self.enable_checkbox)
        self.path_state_label = QtWidgets.QLabel("Path:")
        self.path_state_label.setStyleSheet(
            "QLabel { font-weight: bold; color: #7bf; }"
        )
        enable_row.addWidget(self.path_state_label)
        enable_row.addStretch()
        layout.addLayout(enable_row)

        self.enable_checkbox.stateChanged.connect(self._on_enable_changed)

        # Exposure slider
        exposure_layout = QtWidgets.QVBoxLayout()
        exposure_layout.addWidget(QtWidgets.QLabel("Exposure"))
        
        self.exposure_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.exposure_slider.setRange(1, 100)
        self.exposure_slider.setValue(50)
        exposure_layout.addWidget(self.exposure_slider)
        
        self.exposure_label = QtWidgets.QLabel("50 ms")
        self.exposure_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        exposure_layout.addWidget(self.exposure_label)
        
        self.exposure_slider.valueChanged.connect(
            lambda v: self.exposure_label.setText(f"{v} ms")
        )
        
        layout.addLayout(exposure_layout)
        
        # Camera properties button
        self.properties_button = QtWidgets.QPushButton("Camera Properties")
        layout.addWidget(self.properties_button)

        layout.addStretch()
        self.setLayout(layout)

    def _on_enable_changed(self, state: int) -> None:
        """Update the path-state label when the Enable checkbox changes.

        Args:
            state: Qt.CheckState value emitted by stateChanged.
        """
        checked = state == QtCore.Qt.CheckState.Checked.value
        self.path_state_label.setText("Path: Epi" if checked else "Path: 2p")


class PMTControlGroup(QtWidgets.QGroupBox):
    """PMT control group box.
    
    Contains:
    - PMT0 gain slider
    - PMT1 gain slider
    """
    
    def __init__(self):
        """Initialize the PMT control group."""
        super().__init__("PMT Control")
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout()
        
        # PMT0 gain
        pmt0_layout = QtWidgets.QVBoxLayout()
        pmt0_layout.addWidget(QtWidgets.QLabel("PMT0 Gain"))
        
        self.pmt0_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.pmt0_slider.setRange(0, 100)
        self.pmt0_slider.setValue(0)
        pmt0_layout.addWidget(self.pmt0_slider)
        
        self.pmt0_label = QtWidgets.QLabel("0%")
        self.pmt0_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        pmt0_layout.addWidget(self.pmt0_label)
        
        self.pmt0_slider.valueChanged.connect(
            lambda v: self.pmt0_label.setText(f"{v}%")
        )
        
        layout.addLayout(pmt0_layout)
        
        # PMT1 gain
        pmt1_layout = QtWidgets.QVBoxLayout()
        pmt1_layout.addWidget(QtWidgets.QLabel("PMT1 Gain"))
        
        self.pmt1_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.pmt1_slider.setRange(0, 100)
        self.pmt1_slider.setValue(0)
        pmt1_layout.addWidget(self.pmt1_slider)
        
        self.pmt1_label = QtWidgets.QLabel("0%")
        self.pmt1_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        pmt1_layout.addWidget(self.pmt1_label)
        
        self.pmt1_slider.valueChanged.connect(
            lambda v: self.pmt1_label.setText(f"{v}%")
        )
        
        layout.addLayout(pmt1_layout)
        
        # Zero button
        self.zero_button = QtWidgets.QPushButton("Zero")
        self.zero_button.clicked.connect(self._zero_gains)
        layout.addWidget(self.zero_button)
        
        layout.addStretch()
        self.setLayout(layout)
        
    def _zero_gains(self):
        """Set both PMT gains to zero."""
        self.pmt0_slider.setValue(0)
        self.pmt1_slider.setValue(0)


class ImageDisplayControlGroup(QtWidgets.QGroupBox):
    """Image display control group box.
    
    Contains:
    - Channel display selector
    - Display gain slider
    """
    
    def __init__(self):
        """Initialize the image display control group."""
        super().__init__("Image Display")
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout()
        
        # Channel display selector
        layout.addWidget(QtWidgets.QLabel("Channel:"))
        self.channel_combobox = QtWidgets.QComboBox()
        self.channel_combobox.addItems(["PMT0", "PMT1", "PMT0 & PMT1"])
        self.channel_combobox.setCurrentIndex(0)
        layout.addWidget(self.channel_combobox)
        
        # Display gain
        gain_layout = QtWidgets.QVBoxLayout()
        gain_layout.addWidget(QtWidgets.QLabel("Gain"))
        
        self.gain_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.gain_slider.setRange(1, 100)
        self.gain_slider.setValue(10)
        gain_layout.addWidget(self.gain_slider)
        
        self.gain_label = QtWidgets.QLabel("1.0x")
        self.gain_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        gain_layout.addWidget(self.gain_label)
        
        self.gain_slider.valueChanged.connect(
            lambda v: self.gain_label.setText(f"{v/10:.1f}x")
        )
        
        layout.addLayout(gain_layout)
        
        layout.addStretch()
        self.setLayout(layout)


class OptotuneGroup(QtWidgets.QGroupBox):
    """Optotune/Volumetric control group box.
    
    Contains:
    - ETL (electrotunable lens) vertical slider
    - Placeholder for future volumetric parameters
    """
    
    def __init__(self):
        """Initialize the optotune group."""
        super().__init__("Optotune / Volumetric")
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout()

        # ETL current — slider (coarse) + spinbox (fine), bidirectionally
        # linked.  Range is taken from ScanboxController.ETL_CURRENT_MIN/MAX,
        # which is the single source of truth for this value.
        etl_min = hw_controller.ScanboxController.ETL_CURRENT_MIN
        etl_max = hw_controller.ScanboxController.ETL_CURRENT_MAX
        layout.addWidget(QtWidgets.QLabel("ETL current"))

        # Vertical slider: high value = top, low value = bottom.
        slider_layout = QtWidgets.QHBoxLayout()
        slider_layout.addStretch()

        self.etl_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Vertical)
        self.etl_slider.setRange(etl_min, etl_max)
        self.etl_slider.setValue(etl_min)
        self.etl_slider.setTickPosition(QtWidgets.QSlider.TickPosition.TicksRight)
        self.etl_slider.setTickInterval((etl_max - etl_min) // 10)  # 10 ticks
        self.etl_slider.setMinimumHeight(120)
        slider_layout.addWidget(self.etl_slider)
        slider_layout.addStretch()
        layout.addLayout(slider_layout)

        # Spinbox for precise current entry
        self.etl_spinbox = QtWidgets.QSpinBox()
        self.etl_spinbox.setRange(etl_min, etl_max)
        self.etl_spinbox.setValue(etl_min)
        self.etl_spinbox.setSuffix('')
        layout.addWidget(self.etl_spinbox)

        # Bidirectional link: slider ↔ spinbox
        self.etl_slider.valueChanged.connect(self.etl_spinbox.setValue)
        self.etl_spinbox.valueChanged.connect(self.etl_slider.setValue)

        self.setLayout(layout)


class CommandLogPanel(QtWidgets.QWidget):
    """Scrollable log panel showing commands sent to and received from hardware.

    Displays HTML-formatted log entries with timestamps, direction labels,
    and color-coded text.  Designed to be embedded in a QDockWidget which
    already provides the panel title.

    Usage::

        log_panel = CommandLogPanel()
        log_panel.append('<b>hello</b>')  # add an HTML line
        log_panel.append_command('PC → Controller', 'set_pockels(50)')
        log_panel.append_event('Acquisition started')
        log_panel.append_error('Connection lost')
    """

    def __init__(self, parent=None):
        """Initialize the command log panel.

        Args:
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        """Build the panel layout."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._text = QtWidgets.QTextEdit()
        self._text.setReadOnly(True)
        self._text.document().setDefaultFont(QtGui.QFont('Monospace', 9))
        self._text.setMinimumHeight(100)
        self._text.setStyleSheet('border:1px solid #444;')
        layout.addWidget(self._text)

        bar = QtWidgets.QHBoxLayout()
        # self._hint_label = QtWidgets.QLabel(
        #     '<small>Hardware commands and events will appear here.</small>'
        # )
        # bar.addWidget(self._hint_label)
        bar.addStretch()
        btn_clear = QtWidgets.QPushButton('Clear')
        btn_clear.setMaximumWidth(60)
        btn_clear.clicked.connect(self._text.clear)
        bar.addWidget(btn_clear)
        layout.addLayout(bar)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, html: str) -> None:
        """Append a pre-formatted HTML line and scroll to the bottom.

        Args:
            html: HTML-formatted string to append.
        """
        self._text.append(html)
        sb = self._text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def append_command(self, direction: str, detail: str) -> None:
        """Append a hardware command entry.

        Args:
            direction: Short direction label, e.g. ``'PC → Controller'``.
            detail: Human-readable description of the command.
        """
        ts = self._timestamp()
        # Orange for outgoing commands (PC → hardware)
        self.append(
            f'<span style="color:#888">[{ts}]</span>&nbsp;'
            f'<b><span style="color:#fa8">{direction}</span></b>&nbsp;'
            f'<span style="color:#fd8;font-family:monospace">{detail}</span>'
        )

    def append_event(self, text: str) -> None:
        """Append an acquisition / lifecycle event entry.

        Args:
            text: Plain-text event description.
        """
        ts = self._timestamp()
        self.append(
            f'<span style="color:#888">[{ts}]</span>&nbsp;'
            f'<span style="color:#e8a;font-weight:bold">─── {text} ───</span>'
        )

    def append_error(self, text: str) -> None:
        """Append a hardware error entry.

        Args:
            text: Error message.
        """
        ts = self._timestamp()
        self.append(
            f'<span style="color:#888">[{ts}]</span>&nbsp;'
            f'<span style="color:#f66"><b>ERROR:</b> {text}</span>'
        )

    def append_receive(self, direction: str, detail: str) -> None:
        """Append a data-received entry (e.g. position update from hardware).

        Args:
            direction: Short direction label, e.g. ``'Controller → PC'``.
            detail: Human-readable description of the received data.
        """
        ts = self._timestamp()
        # Blue for incoming data (hardware → PC)
        self.append(
            f'<span style="color:#888">[{ts}]</span>&nbsp;'
            f'<b><span style="color:#7bf">{direction}</span></b>&nbsp;'
            f'<span style="color:#bbb">{detail}</span>'
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _timestamp() -> str:
        """Return a ``HH:MM:SS.mmm`` timestamp string."""
        import datetime
        return datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
