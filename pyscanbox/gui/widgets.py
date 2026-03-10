"""Widget components for pyscanbox GUI.

This module defines individual control groups and display widgets:
- LaserControlGroup: Laser power, shutter, wavelength
- ScannerControlGroup: Scanner parameters (frames, lines, mag, etc.)
- PositionDisplayGroup: Position coordinates display
- AcquisitionControlGroup: Acquisition buttons and status
- FileStorageGroup: File path and metadata
- ImageDisplayWidget: Main image display
- HistogramWidget: Pixel-intensity histogram below the image
- FrameSelectorWidget: Compact slider to browse frames of a loaded recording
- CameraPathGroup: Camera controls
- PMTControlGroup: PMT gain controls
- ImageDisplayControlGroup: Display settings
- OptotuneGroup: ETL control
"""

import glob
import os

import numpy as np
import PyQt6.QtWidgets as QtWidgets
import PyQt6.QtCore as QtCore

from pyscanbox.hardware import controller as hw_controller
import PyQt6.QtGui as QtGui


def _build_colormap_lut(name: str) -> np.ndarray:
    """Return a 256×3 uint8 lookup table for the named display colormap.

    Colormaps available:

    ``'green'``
        Black → green.  The current default: only the G channel is set.
        Matches the original Scanbox MATLAB display convention.

    ``'green_white'``
        Black → green → white.  Intensity 0=black, ~128=pure green,
        255=white.  Similar in spirit to matplotlib's ``hot`` colormap
        but using green as the midpoint colour.  Useful when bright
        fluorescence should saturate to white rather than stay green.

    ``'gray'``
        Black → white.  Grayscale reference colormap.

    Args:
        name: One of ``'green'``, ``'green_white'``, ``'gray'``.

    Returns:
        numpy array of shape (256, 3), dtype uint8 (R, G, B columns).
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
    elif name == 'gray':
        lut[:, 0] = v.astype(np.uint8)
        lut[:, 1] = v.astype(np.uint8)
        lut[:, 2] = v.astype(np.uint8)
    else:  # 'green' (default)
        lut[:, 1] = v.astype(np.uint8)
    return lut


# ---------------------------------------------------------------------------
# Module-level display configuration
# ---------------------------------------------------------------------------

# Colormap used for both the image display and the histogram colourbar.
# Allowed values: 'green', 'green_white', 'gray'  (see _build_colormap_lut).
_DISPLAY_COLORMAP: str = 'green_white'

# Fraction (0.0–1.0) of the colormap range used for the histogram bar colour.
# 0.80 → the bar is drawn with the LUT colour at index int(0.80 × 255) = 204.
_HISTOGRAM_COLOR_LEVEL: float = 0.4

# Precomputed lookup table for _DISPLAY_COLORMAP.  Used by both
# ImageDisplayWidget and HistogramWidget so derived colours stay consistent.
_DISPLAY_LUT: np.ndarray = _build_colormap_lut(_DISPLAY_COLORMAP)


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
    - **Knobby (μm)**: Knobby ``dpos`` in physical units — relative position
      from the last zero, matching what the Knobby screen displays.
    - **Abs (μm)**: Absolute motor hardware step counter in physical units,
      polled from the Trinamic board every 100 ms.  Useful for debugging to
      confirm that commanded moves reached the hardware.
    - **Rotated (μm)**: Reserved for the future angle-compensation mode
      (Knobby rotate mode, where Z becomes the objective axis when the
      objective is tilted).  Currently mirrors the Knobby row.
    """

    def __init__(self):
        """Initialize the position display group."""
        super().__init__("Objective Position")
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI components."""
        outer = QtWidgets.QVBoxLayout()
        outer.setSpacing(6)

        # --- Angle row (separate from coordinate grid) ---
        angle_row = QtWidgets.QHBoxLayout()
        angle_row.addWidget(QtWidgets.QLabel("Angle:"))
        self.objective_angle_edit = QtWidgets.QLineEdit("0.0°")
        self.objective_angle_edit.setReadOnly(True)
        angle_row.addWidget(self.objective_angle_edit)
        outer.addLayout(angle_row)

        # --- Coordinate grid: bold X/Y/Z headers immediately above rows ---
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(4)

        def _bold_label(text: str) -> QtWidgets.QLabel:
            lbl = QtWidgets.QLabel(text)
            font = lbl.font()
            font.setBold(True)
            lbl.setFont(font)
            lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            return lbl

        # Row 0: bold X, Y, Z column headers
        grid.addWidget(_bold_label("X"), 0, 1)
        grid.addWidget(_bold_label("Y"), 0, 2)
        grid.addWidget(_bold_label("Z"), 0, 3)

        # Row 1: Knobby coordinates (Knobby dpos — matches Knobby screen)
        grid.addWidget(QtWidgets.QLabel("Knobby (μm):"), 1, 0)
        self.world_x_edit = QtWidgets.QLineEdit("0.00")
        self.world_x_edit.setReadOnly(True)
        self.world_x_edit.setMaximumWidth(70)
        grid.addWidget(self.world_x_edit, 1, 1)

        self.world_y_edit = QtWidgets.QLineEdit("0.00")
        self.world_y_edit.setReadOnly(True)
        self.world_y_edit.setMaximumWidth(70)
        grid.addWidget(self.world_y_edit, 1, 2)

        self.world_z_edit = QtWidgets.QLineEdit("0.00")
        self.world_z_edit.setReadOnly(True)
        self.world_z_edit.setMaximumWidth(70)
        grid.addWidget(self.world_z_edit, 1, 3)

        # Row 2: Absolute motor hardware positions (polled from Trinamic board)
        grid.addWidget(QtWidgets.QLabel("Abs (μm):"), 2, 0)
        self.abs_x_edit = QtWidgets.QLineEdit("0.00")
        self.abs_x_edit.setReadOnly(True)
        self.abs_x_edit.setMaximumWidth(70)
        grid.addWidget(self.abs_x_edit, 2, 1)

        self.abs_y_edit = QtWidgets.QLineEdit("0.00")
        self.abs_y_edit.setReadOnly(True)
        self.abs_y_edit.setMaximumWidth(70)
        grid.addWidget(self.abs_y_edit, 2, 2)

        self.abs_z_edit = QtWidgets.QLineEdit("0.00")
        self.abs_z_edit.setReadOnly(True)
        self.abs_z_edit.setMaximumWidth(70)
        grid.addWidget(self.abs_z_edit, 2, 3)

        # Row 3: Rotated coordinates (reserved — angle-compensated, future)
        grid.addWidget(QtWidgets.QLabel("Rotated (μm):"), 3, 0)
        self.rotated_x_edit = QtWidgets.QLineEdit("0.00")
        self.rotated_x_edit.setReadOnly(True)
        self.rotated_x_edit.setMaximumWidth(70)
        grid.addWidget(self.rotated_x_edit, 3, 1)

        self.rotated_y_edit = QtWidgets.QLineEdit("0.00")
        self.rotated_y_edit.setReadOnly(True)
        self.rotated_y_edit.setMaximumWidth(70)
        grid.addWidget(self.rotated_y_edit, 3, 2)

        self.rotated_z_edit = QtWidgets.QLineEdit("0.00")
        self.rotated_z_edit.setReadOnly(True)
        self.rotated_z_edit.setMaximumWidth(70)
        grid.addWidget(self.rotated_z_edit, 3, 3)

        outer.addLayout(grid)
        outer.addStretch()
        self.setLayout(outer)


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
        
        # Bottom row: Snapshot button
        bottom_row = QtWidgets.QHBoxLayout()
        self.snapshot_button = QtWidgets.QPushButton("Snapshot")
        bottom_row.addWidget(self.snapshot_button)
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
        self.date_edit.textChanged.connect(self._auto_set_session_id)
        self.date_edit.textChanged.connect(self._auto_set_snapshot_index)
        layout.addWidget(self.date_edit, 3, 1)

        layout.addWidget(QtWidgets.QLabel("Session ID:"), 4, 0)
        self.session_edit = QtWidgets.QLineEdit()
        self.session_edit.setPlaceholderText("000")
        self.session_edit.textChanged.connect(self._update_filename)
        layout.addWidget(self.session_edit, 4, 1)
        
        # Save channels selector
        layout.addWidget(QtWidgets.QLabel("Save Channels:"), 5, 0)
        self.channels_combobox = QtWidgets.QComboBox()
        self.channels_combobox.addItems(["PMT0", "PMT1", "PMT0 & PMT1"])
        self.channels_combobox.setCurrentIndex(2)
        layout.addWidget(self.channels_combobox, 5, 1)
        
        self.setLayout(layout)

        # Set initial filename and auto-detect next session/snapshot IDs.
        self._snapshot_index = 0
        self._update_filename()
        self._auto_set_session_id()
        self._auto_set_snapshot_index()

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
            self._auto_set_session_id()
            self._auto_set_snapshot_index()

    def _auto_set_session_id(self) -> None:
        """Set Session ID to the next 3-digit number not already on disk.

        Scans the output directory for ``*_{date}_???.sbx`` files and
        advances past the highest existing three-digit session number.
        Falls back to ``000`` when the directory is empty or unreachable.
        """
        directory = self.directory_edit.text()
        date = self.date_edit.text() or DEFAULT_DATE
        highest = -1
        pattern = os.path.join(directory, f'*_{date}_???.sbx')
        for filepath in glob.glob(pattern):
            basename = os.path.splitext(os.path.basename(filepath))[0]
            parts = basename.rsplit('_', 1)
            if len(parts) == 2:
                try:
                    n = int(parts[1])
                    if n > highest:
                        highest = n
                except ValueError:
                    pass
        self.session_edit.setText(f'{highest + 1:03d}')

    def increment_session_id(self) -> None:
        """Increment the Session ID field by one.

        Called by ``MainWindow`` after each completed Grab acquisition so
        that the next run automatically receives a unique session number.
        """
        try:
            current = int(self.session_edit.text())
        except ValueError:
            current = 0
        self.session_edit.setText(f'{current + 1:03d}')

    def _auto_set_snapshot_index(self) -> None:
        """Initialise the snapshot counter to the next available number.

        Scans the output directory for ``*_{date}_???.png`` files and
        sets ``_snapshot_index`` past the highest existing number.
        Falls back to ``0`` when the directory is empty or unreachable.
        """
        directory = self.directory_edit.text()
        date = self.date_edit.text() or DEFAULT_DATE
        highest = -1
        pattern = os.path.join(directory, f'*_{date}_???.png')
        for filepath in glob.glob(pattern):
            basename = os.path.splitext(os.path.basename(filepath))[0]
            parts = basename.rsplit('_', 1)
            if len(parts) == 2:
                try:
                    n = int(parts[1])
                    if n > highest:
                        highest = n
                except ValueError:
                    pass
        self._snapshot_index = highest + 1

    def get_snapshot_path(self) -> str:
        """Return the full path for the next snapshot PNG file.

        Combines the output directory, subject, date, and the internal
        snapshot counter.  Does not increment the counter; call
        ``increment_snapshot_index()`` after a successful save.

        Returns:
            Absolute file path string ending in .png.
        """
        subject = self.subject_edit.text() or DEFAULT_SUBJECT
        date = self.date_edit.text() or DEFAULT_DATE
        filename = f'{subject}_{date}_{self._snapshot_index:03d}.png'
        return os.path.join(self.directory_edit.text(), filename)

    def increment_snapshot_index(self) -> None:
        """Advance the snapshot counter by one."""
        self._snapshot_index += 1


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

    _ZOOM_FACTOR = 1.25  # scale multiplier per wheel step

    # Nominal scene size used for the placeholder text before the first frame.
    _PLACEHOLDER_W = 512
    _PLACEHOLDER_H = 512

    def __init__(self, parent=None):
        super().__init__(parent)
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
        self._markers: list = []   # list of (QGraphicsEllipseItem, QGraphicsTextItem)
        self._marker_count: int = 0

        # Small toggle button overlaid on the top-right corner of the view.
        # It is a direct child widget of _ImageCanvas so it floats above the
        # scene without affecting the layout of ImageDisplayWidget.
        self._mark_button = QtWidgets.QPushButton("✛", self)
        self._mark_button.setCheckable(True)
        self._mark_button.setFixedSize(28, 28)
        self._mark_button.setToolTip(
            "Marker mode — click to place numbered markers\n"
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

    def fit_to_window(self) -> None:
        """Switch to fit mode and scale the image to fill the view."""
        self._is_fit = True
        self._fit_in_view()

    # ------------------------------------------------------------------
    # Qt event overrides
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._is_fit:
            self._fit_in_view()
        self._reposition_mark_button()

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """Zoom in or out centred on the cursor position."""
        if event.angleDelta().y() > 0:
            factor = self._ZOOM_FACTOR
        else:
            factor = 1.0 / self._ZOOM_FACTOR
        self._is_fit = False
        self.scale(factor, factor)

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
        """Show a right-click context menu with zoom/view actions."""
        menu = QtWidgets.QMenu(self)
        fit_action       = menu.addAction("Fit to Window")
        menu.addSeparator()
        zoom_in_action   = menu.addAction("Zoom In")
        zoom_out_action  = menu.addAction("Zoom Out")
        actual_action    = menu.addAction("Actual Size (1:1)")
        menu.addSeparator()
        clear_action     = menu.addAction("Clear Markers")
        action = menu.exec(event.globalPos())
        if action == fit_action:
            self.fit_to_window()
        elif action == zoom_in_action:
            self._is_fit = False
            self.scale(self._ZOOM_FACTOR, self._ZOOM_FACTOR)
        elif action == zoom_out_action:
            self._is_fit = False
            self.scale(1.0 / self._ZOOM_FACTOR, 1.0 / self._ZOOM_FACTOR)
        elif action == actual_action:
            self._is_fit = False
            self.resetTransform()
        elif action == clear_action:
            self.clear_markers()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fit_in_view(self) -> None:
        rect = self._pixmap_item.boundingRect()
        if not rect.isNull():
            self.fitInView(rect, QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    def _reposition_mark_button(self) -> None:
        """Keep the Mark button in the top-right corner of the viewport."""
        margin = 6
        btn = self._mark_button
        btn.move(self.width() - btn.width() - margin, margin)
        btn.raise_()

    def _on_mark_toggled(self, enabled: bool) -> None:
        """Switch between marker mode and normal pan mode."""
        self._marker_mode = enabled
        if enabled:
            self.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)
            self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
        else:
            self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
            self.unsetCursor()

    def _add_marker(self, scene_pos: QtCore.QPointF) -> None:
        """Add a circular marker at *scene_pos* (image coordinates)."""
        self._marker_count += 1
        r = 5   # radius in image pixels
        color = QtGui.QColor(255, 220, 0)   # yellow
        pen = QtGui.QPen(color, 1.5)

        ellipse = self._scene.addEllipse(
            scene_pos.x() - r, scene_pos.y() - r, r * 2, r * 2,
            pen,
            QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush),
        )
        ellipse.setZValue(2)
        self._markers.append(ellipse)
        print(f"Marker {self._marker_count}: "
              f"({scene_pos.x():.1f}, {scene_pos.y():.1f}) px")

    def clear_markers(self) -> None:
        """Remove all markers from the scene and reset the counter."""
        for ellipse in self._markers:
            self._scene.removeItem(ellipse)
        self._markers.clear()
        self._marker_count = 0


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
    # original >> 6 behaviour (14-bit → 8-bit with no clipping).
    _GAIN_DIVISOR = 10.0

    # Maximum 14-bit value (2^14 - 1).
    _MAX_14BIT = 16383

    def __init__(self):
        """Initialize the image display widget."""
        super().__init__()
        # Holds the current uint8 frame buffer so that the QImage's memory
        # reference stays valid until the next frame arrives.
        self._display_buffer: np.ndarray | None = None
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
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout()
        self._canvas = _ImageCanvas()
        layout.addWidget(self._canvas)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

    def update_frame(self, frame_data: np.ndarray) -> None:
        """Update the display with a newly acquired frame.

        Converts the selected PMT channel(s) of the 14-bit frame array to an
        8-bit RGB QPixmap coloured by channel convention:

        - **PMT0** → green pixels  (R=0, G=intensity, B=0)
        - **PMT1** → red pixels    (R=intensity, G=0, B=0)
        - **PMT0 & PMT1** → red/green overlay (R=PMT1, G=PMT0, B=0)

        In **fluorescence mode** (default) the display is *inverted*: a PMT
        produces a current that *decreases* the ADC value when light is
        present (the raw offset-binary background sits near 16383 with no
        light).  We compensate with ``(16383 - ch) * gain / 64`` so that the
        dark background maps to 0 (black) and bright fluorescence maps to the
        channel colour, matching the original Scanbox display.

        In **direct mode** the raw ADC value is shown without inversion
        (high ADC value = bright / saturated colour).  Useful for debugging.

        This slot is called from the GUI thread via a queued signal
        connection; the numpy array is passed by reference and is safe to
        read because the Scanner creates a fresh array for every frame.

        Args:
            frame_data: Shape ``(channels, lines_per_frame, pixels_per_line)``,
                dtype ``uint16``, values 0-16383 (14-bit).
        """
        if frame_data is None:
            return  # stale queued signal delivered after scanner cleanup

        n_channels = frame_data.shape[0]

        def _scale(ch: np.ndarray) -> np.ndarray:
            """Map a 14-bit channel array to uint8, applying inversion + gain."""
            c = ch.astype(np.float32)
            if self._invert:
                # Fluorescence mode: background (high ADC) → 0 (black),
                # signal (low ADC) → 255.  Matches Scanbox MATLAB display.
                return np.clip(
                    (self._MAX_14BIT - c) * self._gain / 64.0, 0, 255
                ).astype(np.uint8)
            # Direct mode: high ADC → bright (for debugging).
            return np.clip(c * self._gain / 64.0, 0, 255).astype(np.uint8)

        # Build a 3-channel RGB array coloured by PMT channel convention.
        # PMT0 = green (typical fluorescence ch1: GFP, FITC, …)
        # PMT1 = red   (typical fluorescence ch2: tdTomato, RFP, …)
        # Colormap is applied via NumPy fancy indexing (lut[grayscale]) which
        # runs in compiled C code — fast enough for real-time display.
        if self._channel == 2 and n_channels >= 2:
            # Overlay: R = PMT1 (red), G = PMT0 (green), B = 0.
            # Colormap is not applied to overlay; channel colours are fixed.
            g = _scale(frame_data[0])
            r = _scale(frame_data[1])
            height, width = g.shape
            rgb = np.zeros((height, width, 3), dtype=np.uint8)
            rgb[:, :, 0] = r
            rgb[:, :, 1] = g
        elif self._channel == 1:
            # PMT1 → apply colormap (intensity maps as per selected LUT).
            v = _scale(frame_data[min(1, n_channels - 1)])
            rgb = self._lut[v]  # fancy indexing: (H, W) → (H, W, 3)
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
                (i.e. 0.1× – 10.0×).  The change takes effect on the next
                call to ``update_frame``.
        """
        self._gain = slider_value / self._GAIN_DIVISOR

    def set_channel(self, index: int) -> None:
        """Set the PMT channel to display.

        Args:
            index: 0 = PMT0, 1 = PMT1, 2 = average of PMT0 & PMT1.
        """
        self._channel = index

    def set_display_mode(self, index: int) -> None:
        """Switch between fluorescence (inverted) and direct display modes.

        Args:
            index: 0 = Fluorescence (inverted, black background + bright
                signal, matches Scanbox MATLAB display).
                   1 = Direct (raw ADC value, high = bright, for debugging).
        """
        self._invert = (index == 0)

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


class HistogramWidget(QtWidgets.QWidget):
    """Pixel-intensity histogram for the current frame.

    Displays a 256-bin histogram of the raw 14-bit pixel values from
    channel 0 (PMT0) of the most recently acquired frame.

    Display conventions
    -------------------
    * The x-axis spans the full 14-bit range with a **fixed scale**: raw
      value 0 on the left, 16383 on the right.  This makes it easy to see
      how the distribution shifts when PMT gain or Pockels power changes.
    * Fixed axis labels "0" and "16383" are painted at the bottom corners.
    * A small "zeros" checkbox in the top-right corner controls whether bin 0
      (pixels at raw value 0) is included in the display and the y-scale.
      Bin 0 is often dominated by the zero-padding / sync pixels and can
      dwarf the signal bins; hiding it reveals fine structure elsewhere.
    * The y-axis always auto-scales, excluding bin 0 from the scaling
      reference regardless of whether it is shown.

    Performance design
    ------------------
    * ``update_frame`` is a no-op when the widget is hidden, so connecting
      it unconditionally to ``frame_data_ready`` is safe.
    * The histogram is recomputed only every ``UPDATE_EVERY`` frames to keep
      the main thread load negligible even at high frame rates.
    * Data reduction: only every 4th pixel is sampled (``SUBSAMPLE``).
      At 512×512 this reduces the working set from 262 K to 65 K elements
      with no perceptible change in histogram shape.
    * Bin counts use ``np.bincount`` on 14-bit integers, which is 3–5× faster
      than ``np.histogram`` for integer data.
    * ``paintEvent`` uses fully vectorised numpy arithmetic; no per-bin Python
      loop remains.  The polygon and border lines are built from numpy arrays
      converted to Qt objects in a single pass.
    """

    # Number of histogram bins.  256 gives one bin per 8-bit equivalent level.
    NUM_BINS = 256
    # Full-scale value of the 14-bit ADC.
    _ADC_MAX = 16383
    # Recompute the histogram only once every this many frames.
    UPDATE_EVERY = 5
    # Stride for pixel subsampling (every Nth pixel used for the histogram).
    SUBSAMPLE = 4

    # Visual constants
    _BG_COLOR = QtGui.QColor("#1a1a1a")
    _AXIS_COLOR = QtGui.QColor("#555555")
    _PADDING = 4        # px inside the widget edges (left / right / top)
    _LABEL_HEIGHT = 11  # px reserved at the bottom for axis tick labels

    # Number of 14-bit values per histogram bin (16384 / 256 = 64).
    _VALUES_PER_BIN = (_ADC_MAX + 1) // NUM_BINS

    def __init__(self):
        """Initialize the histogram widget."""
        super().__init__()
        self._counts: np.ndarray | None = None
        self._frame_counter: int = 0
        self.setMinimumHeight(80)
        self.setMaximumHeight(120)
        self.setMinimumWidth(100)
        self.setToolTip(
            "Pixel intensity histogram (channel 0, 256 bins, 14-bit range)\n"
            "X-axis: display value 0 = dark background (left) → 16383 = max signal (right)"
        )

        # Bar and border colours derived from the module-level display colormap.
        _bar_idx = int(_HISTOGRAM_COLOR_LEVEL * 255)
        _bar_rgb = _DISPLAY_LUT[_bar_idx]
        self._bar_color = QtGui.QColor(
            int(_bar_rgb[0]), int(_bar_rgb[1]), int(_bar_rgb[2])
        )
        self._border_color = self._bar_color.lighter(130)

    def update_frame(self, frame_data: np.ndarray) -> None:
        """Recompute the histogram from a newly acquired frame.

        This slot is safe to connect permanently to ``frame_data_ready``:
        it returns immediately when the widget is hidden or when the
        frame-skip counter has not yet reached ``UPDATE_EVERY``.

        Accepts the same ``frame_data_ready`` signal payload as
        ``ImageDisplayWidget.update_frame``.  Only channel 0 is used.

        Args:
            frame_data: Shape ``(channels, lines_per_frame, pixels_per_line)``,
                dtype ``uint16``, values 0–16383 (14-bit).
        """
        if frame_data is None or not self.isVisible():
            return
        self._frame_counter += 1
        if self._frame_counter % self.UPDATE_EVERY != 0:
            return
        self._compute_histogram(frame_data)

    def force_update_frame(self, frame_data: np.ndarray) -> None:
        """Recompute the histogram immediately, bypassing the frame throttle.

        Use this when displaying a specific frame from a loaded recording so
        that every slider move produces an instant histogram update regardless
        of ``UPDATE_EVERY``.

        Args:
            frame_data: Shape ``(channels, lines_per_frame, pixels_per_line)``,
                dtype ``uint16``, values 0–16383 (14-bit).
        """
        if frame_data is None or not self.isVisible():
            return
        self._compute_histogram(frame_data)

    def _compute_histogram(self, frame_data: np.ndarray) -> None:
        """Compute bin counts from *frame_data* and schedule a repaint.

        Args:
            frame_data: Shape ``(channels, lines_per_frame, pixels_per_line)``,
                dtype ``uint16``, values 0–16383 (14-bit).
        """
        # Subsample then bin-count.  bincount on integer data is ~4× faster
        # than np.histogram and requires no range argument.
        ch0 = frame_data[0].ravel()[::self.SUBSAMPLE]
        # Clamp to valid 14-bit range so bincount index is always in-bounds.
        ch0 = np.clip(ch0, 0, self._ADC_MAX)
        full_counts = np.bincount(ch0, minlength=self._ADC_MAX + 1)
        # Fold 16 384 fine bins into NUM_BINS coarse bins by summing groups.
        self._counts = (
            full_counts.reshape(self.NUM_BINS, self._VALUES_PER_BIN).sum(axis=1)
        )
        self.update()  # schedule a repaint

    def paintEvent(self, event) -> None:  # noqa: N802  (Qt naming convention)
        """Paint the histogram bars and axis labels using QPainter.

        The x-axis has a fixed scale: bin 0 (raw value 0) on the left,
        bin 255 (raw value 16383) on the right.  The y-axis auto-scales to
        the maximum count across bins 1–255; bin 0 is excluded from the
        scaling reference so a dominant zero-pixel spike does not compress
        the rest of the chart.  When the "zeros" checkbox is unchecked, bin 0
        is drawn as zero.

        All per-bin coordinate arithmetic is fully vectorised with numpy;
        no Python loop iterates over individual bins.

        Args:
            event: QPaintEvent from Qt (unused; we always repaint fully).
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

        # Flip so that high raw ADC values (dark background) sit on the left
        # and low raw ADC values (bright signal) sit on the right.  After the
        # flip, index 0 corresponds to raw ≈ 16383 (display value ≈ 0, dark).
        disp_counts = self._counts[::-1].copy()

        # Chart area sits above the label strip.
        chart_bottom = h - lh          # leave lh px for axis labels
        draw_w = w - 2 * p
        draw_h = chart_bottom - p      # chart top = p (top padding)
        n = len(disp_counts)           # always NUM_BINS = 256

        # Y auto-scale: bin 0 is always excluded from the reference maximum
        # so a large zero-pixel spike never compresses the signal bars.
        max_count = int(disp_counts[1:].max()) if n > 1 else 1
        if max_count == 0:
            max_count = 1

        # --- Vectorised coordinate computation ---
        indices = np.arange(n)
        xs_left = (p + indices * draw_w // n).astype(np.int32)
        xs_right = (p + (indices + 1) * draw_w // n).astype(np.int32)
        xs_right = np.maximum(xs_right, xs_left + 1)
        clamped = np.minimum(disp_counts, max_count)
        bar_heights = (clamped * draw_h // max_count).astype(np.int32)
        y_tops = (chart_bottom - bar_heights).astype(np.int32)

        # --- Filled polygon ---
        # Vertices: left-top and right-top of each bar, then two closing
        # points along the baseline.
        pts = np.empty((2 * n + 2, 2), dtype=np.int32)
        pts[0:2 * n:2, 0] = xs_left
        pts[1:2 * n:2, 0] = xs_right
        pts[0:2 * n:2, 1] = y_tops
        pts[1:2 * n:2, 1] = y_tops
        pts[2 * n] = [w - p, chart_bottom]
        pts[2 * n + 1] = [p, chart_bottom]

        poly_pts = [QtCore.QPoint(x, y) for x, y in pts.tolist()]
        poly = QtGui.QPolygon(poly_pts)

        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(self._bar_color))
        painter.drawPolygon(poly)

        # --- Thin bright border along the top of each bar ---
        xs_l = xs_left.tolist()
        xs_r = xs_right.tolist()
        yt = y_tops.tolist()
        painter.setPen(QtGui.QPen(self._border_color, 1))
        border_lines = [
            QtCore.QLine(x1, y, x2, y)
            for x1, y, x2 in zip(xs_l, yt, xs_r)
        ]
        painter.drawLines(border_lines)

        # --- Baseline ---
        painter.setPen(QtGui.QPen(self._AXIS_COLOR, 1))
        painter.drawLine(p, chart_bottom, w - p, chart_bottom)

        # --- Colourbar + axis labels in the label strip ---
        # Render the full display colormap as a scaled 1-row image, then
        # overlay "0" (left) and "16383" (right) with luminance-based text
        # colours so labels are readable against the gradient.
        cb_data = np.ascontiguousarray(_DISPLAY_LUT)  # (256, 3) uint8
        cb_img = QtGui.QImage(
            cb_data.data, 256, 1, 256 * 3,
            QtGui.QImage.Format.Format_RGB888,
        )
        painter.drawImage(QtCore.QRect(p, chart_bottom, draw_w, lh), cb_img)

        def _label_pen(lut_idx: int) -> QtGui.QPen:
            r = int(_DISPLAY_LUT[lut_idx, 0])
            g = int(_DISPLAY_LUT[lut_idx, 1])
            b = int(_DISPLAY_LUT[lut_idx, 2])
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            color = QtGui.QColor(0, 0, 0) if lum > 128 else QtGui.QColor(255, 255, 255)
            return QtGui.QPen(color)

        font = painter.font()
        font.setPointSize(7)
        painter.setFont(font)
        painter.setPen(_label_pen(0))   # left edge — LUT[0] (darkest)
        painter.drawText(
            QtCore.QRect(p, chart_bottom, draw_w // 2, lh),
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
            "0",
        )
        painter.setPen(_label_pen(255))  # right edge — LUT[255] (brightest)
        painter.drawText(
            QtCore.QRect(p + draw_w // 2, chart_bottom, draw_w // 2, lh),
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter,
            str(self._ADC_MAX),
        )

        painter.end()


class FrameSelectorWidget(QtWidgets.QWidget):
    """Compact frame selector for browsing loaded .sbx recordings.

    Displays a horizontal slider and a frame counter (e.g. ``"12 / 300"``)
    so the user can scrub through frames of a previously saved recording.

    The widget is hidden by default and shown via the View menu (similar to
    the histogram).  It is disabled until :meth:`set_recording` is called
    with a valid frame count.

    Signals:
        frame_selected: Emitted with the 0-based frame index whenever the
            slider is moved.
    """

    frame_selected = QtCore.pyqtSignal(int)

    _BG_COLOR = "#1a1a1a"
    _TEXT_COLOR = "#aaaaaa"

    def __init__(self):
        """Initialize the frame selector widget."""
        super().__init__()
        self._num_frames: int = 0
        self._init_ui()
        self.setMinimumHeight(28)
        self.setMaximumHeight(40)
        self.setMinimumWidth(100)
        # Dark background matching the histogram.
        palette = self.palette()
        palette.setColor(
            self.backgroundRole(), QtGui.QColor(self._BG_COLOR)
        )
        self.setAutoFillBackground(True)
        self.setPalette(palette)
        self.setEnabled(False)

    def _init_ui(self) -> None:
        """Build the widget layout."""
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(8)

        self._label = QtWidgets.QLabel("Frame:")
        self._label.setStyleSheet(f"color: {self._TEXT_COLOR};")
        layout.addWidget(self._label)

        self._slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.setValue(0)
        self._slider.setTickPosition(QtWidgets.QSlider.TickPosition.NoTicks)
        self._slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self._slider, stretch=1)

        self._counter_label = QtWidgets.QLabel("0 / 0")
        self._counter_label.setStyleSheet(f"color: {self._TEXT_COLOR};")
        self._counter_label.setMinimumWidth(70)
        self._counter_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self._counter_label)

        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def current_frame(self) -> int:
        """Current 0-based frame index shown in the slider."""
        return self._slider.value()

    def set_recording(self, num_frames: int) -> None:
        """Configure the slider for a loaded recording.

        Resets the slider to frame 0 and enables the widget when
        ``num_frames`` is positive.

        Args:
            num_frames: Total number of frames in the recording.
        """
        self._num_frames = num_frames
        self._slider.setMinimum(0)
        self._slider.setMaximum(max(0, num_frames - 1))
        self._slider.setValue(0)
        self._update_counter(0)
        self.setEnabled(num_frames > 0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_slider_changed(self, value: int) -> None:
        """Handle slider movement and emit frame_selected.

        Args:
            value: New 0-based frame index.
        """
        self._update_counter(value)
        self.frame_selected.emit(value)

    def _update_counter(self, index: int) -> None:
        """Refresh the ``N / M`` counter label.

        Args:
            index: Current 0-based frame index.
        """
        if self._num_frames > 0:
            self._counter_label.setText(f"{index + 1} / {self._num_frames}")
        else:
            self._counter_label.setText("0 / 0")


class CameraPathGroup(QtWidgets.QGroupBox):
    """Light path toggle group box.

    Presents two large labeled buttons — ``2p`` and ``Epi`` — as an
    exclusive toggle pair.  The active path is highlighted in bright blue;
    the inactive path is visually dimmed.  Emits ``path_changed`` with the
    new mode string (``'2p'`` or ``'epi'``) whenever the selection changes.
    """

    # Emitted with '2p' or 'epi' whenever the selected light path changes.
    path_changed = QtCore.pyqtSignal(str)

    _STYLE_ACTIVE = (
        "QPushButton { background-color: #2c6fbb; color: #fff; "
        "font-weight: bold; font-size: 14px; padding: 8px 18px; "
        "border: 2px solid #5a9bf5; border-radius: 4px; }"
    )
    _STYLE_INACTIVE = (
        "QPushButton { background-color: #2a2a2a; color: #555; "
        "font-size: 14px; padding: 8px 18px; "
        "border: 1px solid #444; border-radius: 4px; }"
    )

    def __init__(self):
        """Initialize the light path group."""
        super().__init__("Light Path")
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout()
        layout.setSpacing(6)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(4)

        self._twop_button = QtWidgets.QPushButton("2p")
        self._twop_button.setCheckable(True)
        self._twop_button.setChecked(False)
        self._twop_button.setToolTip("Two-photon imaging path")

        self._epi_button = QtWidgets.QPushButton("Epi")
        self._epi_button.setCheckable(True)
        self._epi_button.setChecked(True)   # default: Epi (can't read hardware state)
        self._epi_button.setToolTip("Epifluorescence path (camera active)")

        # Exclusive toggle: only one button checked at a time.
        self._button_group = QtWidgets.QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._button_group.addButton(self._twop_button)
        self._button_group.addButton(self._epi_button)

        btn_row.addWidget(self._twop_button)
        btn_row.addWidget(self._epi_button)
        layout.addLayout(btn_row)

        self._update_styles()
        self._button_group.buttonClicked.connect(self._on_button_clicked)

        layout.addStretch()
        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def current_path(self) -> str:
        """Active light path: ``'2p'`` or ``'epi'``."""
        return 'epi' if self._epi_button.isChecked() else '2p'

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_button_clicked(self, button) -> None:
        """Handle button group click: refresh styles and emit path_changed.

        Args:
            button: The QPushButton that was just clicked.
        """
        self._update_styles()
        mode = 'epi' if button is self._epi_button else '2p'
        self.path_changed.emit(mode)

    def _update_styles(self) -> None:
        """Apply active/inactive stylesheet to each button."""
        if self._twop_button.isChecked():
            self._twop_button.setStyleSheet(self._STYLE_ACTIVE)
            self._epi_button.setStyleSheet(self._STYLE_INACTIVE)
        else:
            self._twop_button.setStyleSheet(self._STYLE_INACTIVE)
            self._epi_button.setStyleSheet(self._STYLE_ACTIVE)


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

        # Display mode selector: fluorescence (inverted) vs direct (raw ADC).
        # "Fluorescence" matches Scanbox MATLAB display: PMT background is
        # dark, fluorescent signal is bright.  "Direct" shows raw ADC values
        # (high ADC = bright) and is useful for debugging signal levels.
        layout.addWidget(QtWidgets.QLabel("Display mode:"))
        self.display_mode_combobox = QtWidgets.QComboBox()
        self.display_mode_combobox.addItems(["Fluorescence", "Direct (debug)"])
        self.display_mode_combobox.setCurrentIndex(0)
        self.display_mode_combobox.setToolTip(
            "Fluorescence: inverted display matching Scanbox (dark background, "
            "bright signal).\nDirect: raw ADC value (high ADC = bright, for "
            "debugging)."
        )
        layout.addWidget(self.display_mode_combobox)

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
    - ETL (electrotunable lens) slider + spinbox
    - Depth display label (shows raw current or µm when calibration loaded)
    """

    def __init__(self, default_value=None):
        """Initialize the optotune group.

        Args:
            default_value: Initial ETL current value from config
                (``optotune.default_value``).  Falls back to
                ``ETL_CURRENT_MID`` when ``None``.
        """
        super().__init__("Optotune / Volumetric")
        if default_value is None:
            default_value = hw_controller.ScanboxController.ETL_CURRENT_MID
        self._default_value = default_value
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout()

        # ETL current — slider (coarse) + spinbox (fine), bidirectionally
        # linked.  Range from ScanboxController constants (single source of
        # truth); initial value from config (optotune.default_value).
        etl_min = hw_controller.ScanboxController.ETL_CURRENT_MIN
        etl_max = hw_controller.ScanboxController.ETL_CURRENT_MAX
        layout.addWidget(QtWidgets.QLabel("ETL current"))

        # Horizontal slider starting at the config default value.
        self.etl_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.etl_slider.setRange(etl_min, etl_max)
        self.etl_slider.setValue(self._default_value)
        self.etl_slider.setTickPosition(QtWidgets.QSlider.TickPosition.TicksBelow)
        self.etl_slider.setTickInterval((etl_max - etl_min) // 10)  # 10 ticks
        self.etl_slider.setMinimumWidth(120)
        layout.addWidget(self.etl_slider)

        # Spinbox for precise current entry
        self.etl_spinbox = QtWidgets.QSpinBox()
        self.etl_spinbox.setRange(etl_min, etl_max)
        self.etl_spinbox.setValue(self._default_value)
        self.etl_spinbox.setSuffix('')
        layout.addWidget(self.etl_spinbox)

        # Depth display: shows raw ETL value (4 digits) when uncalibrated,
        # or depth in µm (e.g. "42 µm") once a calibration file is loaded.
        self.depth_label = QtWidgets.QLabel(f'{self._default_value:04d}')
        self.depth_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.depth_label)

        # Bidirectional link: slider ↔ spinbox
        self.etl_slider.valueChanged.connect(self.etl_spinbox.setValue)
        self.etl_spinbox.valueChanged.connect(self.etl_slider.setValue)

        layout.addStretch()
        self.setLayout(layout)

    def set_depth_display(self, text: str) -> None:
        """Update the ETL depth display label.

        Called on every slider move by MainWindow._on_etl_current_changed.
        Shows the raw ETL current when no calibration is loaded, or depth
        in µm once a calibration file is present.

        Args:
            text: Formatted string, e.g. ``'0860'`` (uncalibrated) or
                ``'42 µm'`` (calibrated).
        """
        self.depth_label.setText(text)


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
