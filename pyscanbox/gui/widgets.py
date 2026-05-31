# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Widget components for pyscanbox GUI.

This module defines individual control groups and display widgets:
- LaserControlGroup: Laser power, shutter, wavelength
- ScannerControlGroup: Scanner parameters (frames, lines, mag, etc.)
- PositionDisplayGroup: Position coordinates display
- AcquisitionControlGroup: Acquisition buttons and status
- FileStorageGroup: File path and metadata
- FrameSelectorWidget: Compact slider to browse frames of a loaded recording
- LightPathGroup: Light path controls
- PMTControlGroup: PMT gain controls
- ImageDisplayControlGroup: Display settings
- OptotuneGroup: ETL control

Note: HistogramWidget is defined in histogram_widget.py.
Note: ImageDisplayWidget and _ImageCanvas are defined in image_display_widget.py.
"""

import glob
import os

import PyQt6.QtWidgets as QtWidgets
import PyQt6.QtCore as QtCore

from pyscanbox.hardware import controller as hw_controller
import PyQt6.QtGui as QtGui

from .histogram_widget import HistogramWidget


def _make_combobox() -> QtWidgets.QComboBox:
    """Return a QComboBox with the icon placeholder removed.

    By default Qt reserves space for item icons even when none are set,
    adding visible whitespace before each dropdown entry.  Setting the
    view's icon size to zero eliminates that gap.
    """
    combo = QtWidgets.QComboBox()
    combo.view().setIconSize(QtCore.QSize(0, 0))
    return combo


class LaserControlGroup(QtWidgets.QGroupBox):
    """Laser control group box.
    
    Contains:
    - Wavelength spinbox
    - Power slider (horizontal, Pockels control)
    """
    
    def __init__(self, config=None):
        """Initialize the laser control group.
        
        Args:
            config: Optional AppConfig object (unused but kept for compatibility).
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
        self.wavelength_spinbox.setRange(679, 1100)
        self.wavelength_spinbox.setValue(679)
        self.wavelength_spinbox.setSpecialValueText("Undefined")
        self.wavelength_spinbox.setSuffix(" nm")
        wavelength_layout.addWidget(self.wavelength_spinbox)
        layout.addLayout(wavelength_layout)
        
        # Power slider (Pockels control)
        power_layout = QtWidgets.QVBoxLayout()
        self.power_label = QtWidgets.QLabel("Power (Pockels):  0%")
        power_layout.addWidget(self.power_label)

        self.power_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.power_slider.setRange(0, 100)
        self.power_slider.setValue(0)
        self.power_slider.setTickPosition(QtWidgets.QSlider.TickPosition.TicksBelow)
        self.power_slider.setTickInterval(10)
        self.power_slider.setSingleStep(2)
        power_layout.addWidget(self.power_slider)

        self.power_slider.valueChanged.connect(
            lambda v: self.power_label.setText(f"Power (Pockels):  {v}%")
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
        self.magnification_combobox = _make_combobox()
        self.magnification_combobox.addItems(
            hw_controller.ScanboxController.MAG_LABELS
        )
        self.magnification_combobox.setCurrentIndex(0)  # index 0 = minimum zoom (1.0x)
        layout.addRow("Magnification:", self.magnification_combobox)
        
        # Frame rate — computed from RESONANT_FREQ / lines * (2 if bidir else 1).
        # Matches MATLAB: frame_rate = sbconfig.resfreq/nlines*(2-scanmode)
        self.frame_rate_label = QtWidgets.QLabel()
        layout.addRow("Frame rate:", self.frame_rate_label)
        
        # Scan mode selector (combo box)
        self.scan_mode_combobox = _make_combobox()
        self.scan_mode_combobox.addItems(["Unidirectional", "Bidirectional"])
        self.scan_mode_combobox.setCurrentIndex(0)
        layout.addRow("Scan mode:", self.scan_mode_combobox)
        
        # Bidirectional alignment control
        self.bidir_alignment_spinbox = QtWidgets.QSpinBox()
        self.bidir_alignment_spinbox.setRange(-100, 100)
        self.bidir_alignment_spinbox.setValue(0)
        layout.addRow("Bidir alignment:", self.bidir_alignment_spinbox)

        # Deadband controls (left and right on the same row)
        self.deadband_left_spinbox = QtWidgets.QSpinBox()
        self.deadband_left_spinbox.setRange(0, 255)
        self.deadband_left_spinbox.setValue(40)
        self.deadband_right_spinbox = QtWidgets.QSpinBox()
        self.deadband_right_spinbox.setRange(0, 255)
        self.deadband_right_spinbox.setValue(40)
        deadband_widget = QtWidgets.QWidget()
        deadband_layout = QtWidgets.QHBoxLayout(deadband_widget)
        deadband_layout.setContentsMargins(0, 0, 0, 0)
        deadband_layout.addWidget(self.deadband_left_spinbox)
        deadband_layout.addWidget(self.deadband_right_spinbox)
        layout.addRow("Deadbands:", deadband_widget)

        # Continuous resonant mode checkbox + hsync indicator on the same row
        self.continuous_resonant_checkbox = QtWidgets.QCheckBox("Continuous resonant")
        self.continuous_resonant_checkbox.setToolTip(
            "When checked, the resonant scanner keeps running between acquisitions.\n"
            "This maintains thermal stability and prevents bidirectional alignment drift."
        )
        self.hsync_label = QtWidgets.QPushButton()
        self.hsync_label.setEnabled(False)
        self.hsync_label.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.hsync_label.setToolTip(
            "Indicates whether the image is horizontally flipped.\n"
            "When flipped, the scanner reads lines in the reverse direction,\n"
            "mirroring the image left-to-right.\n"
            "Can be set via hsync_sign in the config file (0 = normal, 1 = flipped)."
        )
        self.hsync_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        resonant_widget = QtWidgets.QWidget()
        resonant_layout = QtWidgets.QHBoxLayout(resonant_widget)
        resonant_layout.setContentsMargins(0, 0, 0, 0)
        resonant_layout.addWidget(self.continuous_resonant_checkbox)
        resonant_layout.addStretch()
        resonant_layout.addWidget(self.hsync_label)
        layout.addRow(resonant_widget)

        # Update frame rate whenever lines or scan mode changes.
        self.lines_per_frame_spinbox.valueChanged.connect(self._update_frame_rate)
        self.scan_mode_combobox.currentIndexChanged.connect(self._update_frame_rate)

        self.setLayout(layout)
        self._update_frame_rate()

    def showEvent(self, event):
        """Recompute the frame rate when the widget is shown."""
        super().showEvent(event)
        self._update_frame_rate()

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
    - **Rotated (μm)**: Coordinates in the objective-aligned frame, computed
      from the Knobby world (X, Z) positions via ``world_to_rotated``.
      ``Z_rot`` runs along the objective axis (positive = away from sample),
      so moving the objective purely along its own axis (Knobby rotated mode)
      only changes ``Z_rot`` while ``X_rot`` stays constant.  ``Y_rot``
      is always equal to world ``Y``.
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
        self.zero_angle_button = QtWidgets.QPushButton("Rotate to 0°")
        self.zero_angle_button.setToolTip("Move angle motor to absolute zero (step 0)")
        self.zero_angle_button.setMaximumWidth(120)
        angle_row.addWidget(self.zero_angle_button)
        outer.addLayout(angle_row)

        # --- Tip-fixed checkbox ---
        self.keep_tip_fixed_checkbox = QtWidgets.QCheckBox("Tip fixed on angle change")
        self.keep_tip_fixed_checkbox.setToolTip(
            "When checked, turning the angle knob also moves X and Z to keep\n"
            "the objective tip at the same absolute position in space.\n"
            "Requires 'objective.length' to be set in the config."
        )
        outer.addWidget(self.keep_tip_fixed_checkbox)

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
        self.world_x_edit.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.world_x_edit, 1, 1)

        self.world_y_edit = QtWidgets.QLineEdit("0.00")
        self.world_y_edit.setReadOnly(True)
        self.world_y_edit.setMaximumWidth(70)
        self.world_y_edit.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.world_y_edit, 1, 2)

        self.world_z_edit = QtWidgets.QLineEdit("0.00")
        self.world_z_edit.setReadOnly(True)
        self.world_z_edit.setMaximumWidth(70)
        self.world_z_edit.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.world_z_edit, 1, 3)

        # Row 2: Absolute motor hardware positions (polled from Trinamic board)
        grid.addWidget(QtWidgets.QLabel("Abs (μm):"), 2, 0)
        self.abs_x_edit = QtWidgets.QLineEdit("0.00")
        self.abs_x_edit.setReadOnly(True)
        self.abs_x_edit.setMaximumWidth(70)
        self.abs_x_edit.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.abs_x_edit, 2, 1)

        self.abs_y_edit = QtWidgets.QLineEdit("0.00")
        self.abs_y_edit.setReadOnly(True)
        self.abs_y_edit.setMaximumWidth(70)
        self.abs_y_edit.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.abs_y_edit, 2, 2)

        self.abs_z_edit = QtWidgets.QLineEdit("0.00")
        self.abs_z_edit.setReadOnly(True)
        self.abs_z_edit.setMaximumWidth(70)
        self.abs_z_edit.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.abs_z_edit, 2, 3)

        # Row 3: Rotated coordinates (reserved — angle-compensated, future)
        grid.addWidget(QtWidgets.QLabel("Rotated (μm):"), 3, 0)
        self.rotated_x_edit = QtWidgets.QLineEdit("0.00")
        self.rotated_x_edit.setReadOnly(True)
        self.rotated_x_edit.setMaximumWidth(70)
        self.rotated_x_edit.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.rotated_x_edit, 3, 1)

        self.rotated_y_edit = QtWidgets.QLineEdit("0.00")
        self.rotated_y_edit.setReadOnly(True)
        self.rotated_y_edit.setMaximumWidth(70)
        self.rotated_y_edit.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.rotated_y_edit, 3, 2)

        self.rotated_z_edit = QtWidgets.QLineEdit("0.00")
        self.rotated_z_edit.setReadOnly(True)
        self.rotated_z_edit.setMaximumWidth(70)
        self.rotated_z_edit.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
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
            "QPushButton { min-height: 28px; font-size: 14px; }"
        )
        self.focus_button.clicked.connect(self._on_focus_toggle)
        top_row.addWidget(self.focus_button)
        
        self.grab_button = QtWidgets.QPushButton("Grab")
        self.grab_button.setCheckable(True)
        self.grab_button.setStyleSheet(
            "QPushButton { min-height: 28px; font-size: 14px; }"
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
    """
    
    def __init__(self, config=None):
        """Initialize the file storage group.

        Args:
            config: Optional configuration dict or AppConfig.  When
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
        
        layout.addWidget(QtWidgets.QLabel("Date/suffix:"), 3, 0)
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

        Scans the output directory for ``*_{date}_snap???.png`` files and
        sets ``_snapshot_index`` past the highest existing number.
        Falls back to ``0`` when the directory is empty or unreachable.
        """
        directory = self.directory_edit.text()
        date = self.date_edit.text() or DEFAULT_DATE
        highest = -1
        pattern = os.path.join(directory, f'*_{date}_snap???.png')
        for filepath in glob.glob(pattern):
            basename = os.path.splitext(os.path.basename(filepath))[0]
            parts = basename.rsplit('_snap', 1)
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

        Combines the output directory, subject, date, the literal token
        ``snap``, and the internal snapshot counter.  For example:
        ``test000_20260413_snap000.png``.  Does not increment the counter;
        call ``increment_snapshot_index()`` after a successful save.

        Returns:
            Absolute file path string ending in .png.
        """
        subject = self.subject_edit.text() or DEFAULT_SUBJECT
        date = self.date_edit.text() or DEFAULT_DATE
        filename = f'{subject}_{date}_snap{self._snapshot_index:03d}.png'
        return os.path.join(self.directory_edit.text(), filename)

    def increment_snapshot_index(self) -> None:
        """Advance the snapshot counter by one."""
        self._snapshot_index += 1


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


class LightPathGroup(QtWidgets.QGroupBox):
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
        "font-weight: bold; font-size: 14px; padding: 4px 18px; "
        "border: 2px solid #5a9bf5; border-radius: 4px; }"
    )
    _STYLE_INACTIVE = (
        "QPushButton { background-color: #2a2a2a; color: #555; "
        "font-size: 14px; padding: 4px 18px; "
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
        self._twop_button.setChecked(True)   # default: 2p (hardware starts in 2p mode)
        self._twop_button.setToolTip("Two-photon imaging path")

        self._epi_button = QtWidgets.QPushButton("Epi")
        self._epi_button.setCheckable(True)
        self._epi_button.setChecked(False)
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

        self.setLayout(layout)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Maximum,
        )

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


class SaveChannelsGroup(QtWidgets.QGroupBox):
    """Save channels group box.

    Contains a PMT channel selector combobox (PMT0, PMT1, PMT0 & PMT1) at
    the top, and independent TTL0/TTL1 toggle buttons below.  TTL buttons are
    seeded from config['external_events']['interrupt_mask'] at startup.
    Callers read ``channels_combobox.currentIndex()`` and ``get_ttl_mask()``
    at grab time.
    """

    _TTL_STYLE_ON = (
        "QPushButton { background-color: #2c6fbb; color: #fff; "
        "font-weight: bold; font-size: 11px; padding: 2px 6px; "
        "border: 2px solid #5a9bf5; border-radius: 3px; }"
    )
    _TTL_STYLE_OFF = (
        "QPushButton { background-color: #2a2a2a; color: #555; "
        "font-size: 11px; padding: 2px 6px; "
        "border: 1px solid #444; border-radius: 3px; }"
    )

    def __init__(self, config=None):
        """Initialize the save channels group.

        Args:
            config: Optional configuration dict or AppConfig.  When provided,
                TTL buttons are seeded from
                config['external_events']['interrupt_mask'].
        """
        super().__init__("Save Channels")
        imask = (
            config.get('external_events', {}).get('interrupt_mask', 0)
            if config is not None
            else 0
        )
        self._init_ui(imask)

    def _init_ui(self, imask: int) -> None:
        """Initialize UI components.

        Args:
            imask: Initial TTL interrupt mask bitmask.
        """
        layout = QtWidgets.QVBoxLayout()
        layout.setSpacing(6)
        layout.addSpacing(10)

        # PMT channel selector
        layout.addWidget(QtWidgets.QLabel("PMT :"))
        self.channels_combobox = _make_combobox()
        self.channels_combobox.addItems(["PMT0", "PMT1", "PMT0 & PMT1"])
        self.channels_combobox.setCurrentIndex(0)
        layout.addWidget(self.channels_combobox)

        # Vertical gap between sections
        layout.addSpacing(18)

        # TTL toggle buttons
        layout.addWidget(QtWidgets.QLabel("TTL :"))
        self.ttl0_button = QtWidgets.QPushButton("TTL0")
        self.ttl0_button.setCheckable(True)
        self.ttl0_button.setChecked(bool(imask & 1))
        self.ttl0_button.toggled.connect(self._update_ttl_styles)

        self.ttl1_button = QtWidgets.QPushButton("TTL1")
        self.ttl1_button.setCheckable(True)
        self.ttl1_button.setChecked(bool(imask & 2))
        self.ttl1_button.toggled.connect(self._update_ttl_styles)

        layout.addWidget(self.ttl0_button)
        layout.addWidget(self.ttl1_button)
        layout.addStretch()
        self.setLayout(layout)
        self._update_ttl_styles()

    def _update_ttl_styles(self) -> None:
        """Apply active/inactive stylesheet to each TTL button."""
        for btn in (self.ttl0_button, self.ttl1_button):
            btn.setStyleSheet(
                self._TTL_STYLE_ON if btn.isChecked() else self._TTL_STYLE_OFF
            )

    def get_ttl_mask(self) -> int:
        """Return the current TTL interrupt mask from button states.

        Returns:
            Bitmask: 0=none, 1=TTL0 only, 2=TTL1 only, 3=both.
        """
        return (1 if self.ttl0_button.isChecked() else 0) | \
               (2 if self.ttl1_button.isChecked() else 0)


class PMTControlGroup(QtWidgets.QGroupBox):
    """PMT control group box.

    Contains:
    - PMT0 gain slider
    - PMT1 gain slider
    """

    _DEFAULT_PRESETS = [0, 50, 70]

    def __init__(self, config=None):
        """Initialize the PMT control group.

        Args:
            config: Optional AppConfig or plain dict.  When provided,
                ``pmt.gain_presets`` is used to set the quick-access button
                values.  Defaults to ``[0, 50, 70]``.
        """
        super().__init__("PMT Control")
        config_dict = (
            config.to_dict() if hasattr(config, 'to_dict') else (config or {})
        )
        presets = config_dict.get('pmt', {}).get('gain_presets', self._DEFAULT_PRESETS)
        self._presets = list(presets)[:3]  # use at most three preset values
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout()
        
        # PMT0 gain
        pmt0_layout = QtWidgets.QVBoxLayout()
        pmt0_top_layout = QtWidgets.QHBoxLayout()
        self.pmt0_label = QtWidgets.QLabel("PMT0 Gain:  0%")
        pmt0_top_layout.addWidget(self.pmt0_label)
        pmt0_top_layout.addStretch()
        self.pmt0_preset0_btn = QtWidgets.QPushButton(f"{self._presets[0]}%")
        self.pmt0_preset0_btn.setMaximumWidth(42)
        self.pmt0_preset0_btn.clicked.connect(lambda: self.pmt0_slider.setValue(self._presets[0]))
        pmt0_top_layout.addWidget(self.pmt0_preset0_btn)
        self.pmt0_preset1_btn = QtWidgets.QPushButton(f"{self._presets[1]}%")
        self.pmt0_preset1_btn.setMaximumWidth(42)
        self.pmt0_preset1_btn.clicked.connect(lambda: self.pmt0_slider.setValue(self._presets[1]))
        pmt0_top_layout.addWidget(self.pmt0_preset1_btn)
        self.pmt0_preset2_btn = QtWidgets.QPushButton(f"{self._presets[2]}%")
        self.pmt0_preset2_btn.setMaximumWidth(42)
        self.pmt0_preset2_btn.clicked.connect(lambda: self.pmt0_slider.setValue(self._presets[2]))
        pmt0_top_layout.addWidget(self.pmt0_preset2_btn)
        pmt0_layout.addLayout(pmt0_top_layout)

        self.pmt0_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.pmt0_slider.setRange(0, 100)
        self.pmt0_slider.setValue(0)
        self.pmt0_slider.setSingleStep(1)
        pmt0_layout.addWidget(self.pmt0_slider)

        self.pmt0_slider.valueChanged.connect(
            lambda v: self.pmt0_label.setText(f"PMT0 Gain:  {v}%")
        )
        
        layout.addLayout(pmt0_layout)
        
        # PMT1 gain
        pmt1_layout = QtWidgets.QVBoxLayout()
        pmt1_top_layout = QtWidgets.QHBoxLayout()
        self.pmt1_label = QtWidgets.QLabel("PMT1 Gain:  0%")
        pmt1_top_layout.addWidget(self.pmt1_label)
        pmt1_top_layout.addStretch()
        self.pmt1_preset0_btn = QtWidgets.QPushButton(f"{self._presets[0]}%")
        self.pmt1_preset0_btn.setMaximumWidth(42)
        self.pmt1_preset0_btn.clicked.connect(lambda: self.pmt1_slider.setValue(self._presets[0]))
        pmt1_top_layout.addWidget(self.pmt1_preset0_btn)
        self.pmt1_preset1_btn = QtWidgets.QPushButton(f"{self._presets[1]}%")
        self.pmt1_preset1_btn.setMaximumWidth(42)
        self.pmt1_preset1_btn.clicked.connect(lambda: self.pmt1_slider.setValue(self._presets[1]))
        pmt1_top_layout.addWidget(self.pmt1_preset1_btn)
        self.pmt1_preset2_btn = QtWidgets.QPushButton(f"{self._presets[2]}%")
        self.pmt1_preset2_btn.setMaximumWidth(42)
        self.pmt1_preset2_btn.clicked.connect(lambda: self.pmt1_slider.setValue(self._presets[2]))
        pmt1_top_layout.addWidget(self.pmt1_preset2_btn)
        pmt1_layout.addLayout(pmt1_top_layout)

        self.pmt1_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.pmt1_slider.setRange(0, 100)
        self.pmt1_slider.setValue(0)
        self.pmt1_slider.setSingleStep(1)
        pmt1_layout.addWidget(self.pmt1_slider)

        self.pmt1_slider.valueChanged.connect(
            lambda v: self.pmt1_label.setText(f"PMT1 Gain:  {v}%")
        )
        
        layout.addLayout(pmt1_layout)

        self.setLayout(layout)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Maximum,
        )
        

class ImageDisplayControlGroup(QtWidgets.QGroupBox):
    """Image display control group box.

    Contains:
    - Channel display selector
    - Display gain slider
    - Rolling average selector
    """

    # Default tau values (in frames) used when not set by config.
    _DEFAULT_TAUS = [5, 10, 20]

    def __init__(self, config=None):
        """Initialize the image display control group.

        Args:
            config: Optional AppConfig (or plain dict).  When provided the
                ``display.rolling_avg_taus`` list is used to populate the
                rolling average combobox.
        """
        super().__init__("Image Display")
        config_dict = (
            config.to_dict() if hasattr(config, 'to_dict') else (config or {})
        )
        display_cfg = config_dict.get('display', {})
        taus = display_cfg.get('rolling_avg_taus', self._DEFAULT_TAUS)
        # rolling_avg_taus maps combobox index → tau; index 0 is always "Off" (tau=0).
        self.rolling_avg_taus = [0] + list(taus)
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout()

        # Channel display selector
        layout.addWidget(QtWidgets.QLabel("Channel:"))
        self.channel_combobox = _make_combobox()
        self.channel_combobox.addItems(["PMT0", "PMT1", "PMT0 & PMT1", "PMT0 | PMT1"])
        self.channel_combobox.setCurrentIndex(0)
        layout.addWidget(self.channel_combobox)

        # NOTE: Display mode (Fluorescence / Direct) is intentionally not
        # exposed in the GUI.  The display always uses fluorescence mode
        # (inverted: dark background, bright signal).  See
        # ImageDisplayWidget.set_display_mode() for programmatic access.

        # Display gain
        gain_layout = QtWidgets.QVBoxLayout()
        gain_top_layout = QtWidgets.QHBoxLayout()
        self.gain_label = QtWidgets.QLabel("Gain:  1.0x")
        gain_top_layout.addWidget(self.gain_label)
        gain_top_layout.addStretch()
        self.gain_reset_btn = QtWidgets.QPushButton("Reset")
        self.gain_reset_btn.setMaximumWidth(50)
        self.gain_reset_btn.clicked.connect(lambda: self.gain_slider.setValue(10))
        gain_top_layout.addWidget(self.gain_reset_btn)
        gain_top_layout.addStretch()
        gain_layout.addLayout(gain_top_layout)

        self.gain_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.gain_slider.setRange(1, 100)
        self.gain_slider.setValue(10)
        gain_layout.addWidget(self.gain_slider)

        self.gain_slider.valueChanged.connect(
            lambda v: self.gain_label.setText(f"Gain:  {v/10:.1f}x")
        )

        layout.addLayout(gain_layout)

        # Rolling average selector
        layout.addWidget(QtWidgets.QLabel("Rolling avg:"))
        self.rolling_avg_combobox = _make_combobox()
        items = ["Off"] + [f"\u03c4 = {t} frames" for t in self.rolling_avg_taus[1:]]
        self.rolling_avg_combobox.addItems(items)
        self.rolling_avg_combobox.setCurrentIndex(0)
        layout.addWidget(self.rolling_avg_combobox)

        layout.addStretch()
        self.setLayout(layout)

    def configure_channels(self, channels: int) -> None:
        """Restrict the channel combobox to match the recorded channels.

        Disables items that cannot be shown for the given recording and
        auto-selects a valid item.  Call this after opening an .sbx file.

        Args:
            channels: Value of the ``channels`` field in the Scanbox .mat
                file: ``1`` = both PMT0 & PMT1, ``2`` = PMT0 only,
                ``3`` = PMT1 only.
        """
        model = self.channel_combobox.model()
        if channels == 2:
            # PMT0 only: keep PMT0 (0), disable PMT1 (1), overlay (2), dual-canvas (3).
            for idx in (1, 2, 3):
                item = model.item(idx)
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.channel_combobox.setCurrentIndex(0)
        elif channels == 3:
            # PMT1 only: disable PMT0 (0), keep PMT1 (1), disable overlay (2) and
            # dual-canvas (3).
            for idx in (0, 2, 3):
                item = model.item(idx)
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.channel_combobox.setCurrentIndex(1)
        else:
            # Both channels: enable everything.
            self.reset_channels()

    def reset_channels(self) -> None:
        """Re-enable all channel combobox items without changing the selection.

        Call this when switching back to live-acquisition mode or when no
        file is loaded so that all four display modes are available again.
        """
        model = self.channel_combobox.model()
        for idx in range(self.channel_combobox.count()):
            item = model.item(idx)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEnabled)


class OptotuneGroup(QtWidgets.QGroupBox):
    """Optotune/Volumetric control group box.

    Contains:
    - ETL (electrotunable lens) slider + spinbox
    - Depth display label (shows raw current or µm when calibration loaded)
    - Focus stacking controls: Top/Bottom capture, planes, frames/plane, Enable
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
        # Focus stacking state — set by Set Top / Set Bottom buttons.
        self.etl_top = None     # int | None
        self.etl_bottom = None  # int | None
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI components."""
        main_layout = QtWidgets.QHBoxLayout()

        # ------------------------------------------------------------------
        # Left column: ETL current controls + Enable volumetric checkbox
        # ------------------------------------------------------------------
        left_layout = QtWidgets.QVBoxLayout()

        # ETL current — slider (coarse) + spinbox (fine), bidirectionally
        # linked.  Range from ScanboxController constants (single source of
        # truth); initial value from config (optotune.default_value).
        etl_min = hw_controller.ScanboxController.ETL_CURRENT_MIN
        etl_max = hw_controller.ScanboxController.ETL_CURRENT_MAX
        left_layout.addWidget(QtWidgets.QLabel("ETL current"))

        # Horizontal slider starting at the config default value.
        self.etl_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.etl_slider.setRange(etl_min, etl_max)
        self.etl_slider.setValue(self._default_value)
        self.etl_slider.setTickPosition(QtWidgets.QSlider.TickPosition.TicksBelow)
        self.etl_slider.setTickInterval((etl_max - etl_min) // 10)  # 10 ticks
        self.etl_slider.setMinimumWidth(120)
        left_layout.addWidget(self.etl_slider)

        # Spinbox for precise current entry
        self.etl_spinbox = QtWidgets.QSpinBox()
        self.etl_spinbox.setRange(etl_min, etl_max)
        self.etl_spinbox.setValue(self._default_value)
        self.etl_spinbox.setSuffix('')
        left_layout.addWidget(self.etl_spinbox)

        # Depth display: shows depth in µm (e.g. "42 µm") once a calibration
        # file is loaded; empty when no calibration is available (the raw ETL
        # value is already visible in the spinbox above).
        self.depth_label = QtWidgets.QLabel('Not calibrated')
        self.depth_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self.depth_label)

        # Bidirectional link: slider ↔ spinbox
        self.etl_slider.valueChanged.connect(self.etl_spinbox.setValue)
        self.etl_spinbox.valueChanged.connect(self.etl_slider.setValue)

        left_layout.addStretch()

        main_layout.addLayout(left_layout)

        # ------------------------------------------------------------------
        # Right column: Focus stacking controls
        # ------------------------------------------------------------------
        right_layout = QtWidgets.QVBoxLayout()

        # Grid layout aligns the spinboxes for Planes and Frames/plane in
        # the same column as the Set buttons for Top/Bottom.
        grid = QtWidgets.QGridLayout()
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(0, 1)  # combined label column expands

        # Top row: combined label (spans value col) + Set button
        self.etl_top_label = QtWidgets.QLabel("Top:  \u2014")
        grid.addWidget(self.etl_top_label, 0, 0)
        self.set_top_btn = QtWidgets.QPushButton("Set")
        self.set_top_btn.setFixedWidth(46)
        grid.addWidget(self.set_top_btn, 0, 1)

        # Bottom row: same pattern
        self.etl_bottom_label = QtWidgets.QLabel("Bottom:  \u2014")
        grid.addWidget(self.etl_bottom_label, 1, 0)
        self.set_bottom_btn = QtWidgets.QPushButton("Set")
        self.set_bottom_btn.setFixedWidth(46)
        grid.addWidget(self.set_bottom_btn, 1, 1)

        # Planes row: label (with step-size appended by update_step_display)
        # + spinbox.  Both spinboxes share col 1 for vertical alignment.
        self.planes_label = QtWidgets.QLabel("Planes:")
        grid.addWidget(self.planes_label, 2, 0)
        self.planes_spinbox = QtWidgets.QSpinBox()
        self.planes_spinbox.setRange(2, 255)
        self.planes_spinbox.setValue(10)
        self.planes_spinbox.setFixedWidth(60)
        grid.addWidget(self.planes_spinbox, 2, 1)

        # Frames/plane row: spinbox aligned with Planes spinbox above
        grid.addWidget(QtWidgets.QLabel("Frames/plane:"), 3, 0)
        self.frames_spinbox = QtWidgets.QSpinBox()
        self.frames_spinbox.setRange(1, 255)
        self.frames_spinbox.setValue(5)
        self.frames_spinbox.setFixedWidth(60)
        grid.addWidget(self.frames_spinbox, 3, 1)

        # Checkbox to send data to controller for volumetric acquisition.
        # While checked, the spinboxes and Set buttons are disabled to prevent
        # silent parameter drift — the user must uncheck, adjust, then re-check
        # to re-upload the waveform.
        self.enable_checkbox = QtWidgets.QCheckBox("Enable volumetric")
        right_layout.addLayout(grid)
        right_layout.addWidget(self.enable_checkbox)
        right_layout.addStretch()

        main_layout.addLayout(right_layout)

        self.setLayout(main_layout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_depth_display(self, text: str) -> None:
        """Update the ETL depth display label.

        Called on every slider move by MainWindow._on_etl_current_changed.
        Shows depth in µm once a calibration file is loaded; 'Not calibrated'
        when no calibration is available (the raw ETL value is already
        visible in the spinbox).

        Args:
            text: Formatted string, e.g. ``'42 µm'`` (calibrated) or
                ``'Not calibrated'`` (uncalibrated).
        """
        self.depth_label.setText(text)

    def set_top(self, etl_value: int, label: str = '') -> None:
        """Store the top ETL value and update the display label.

        Args:
            etl_value: Raw ETL current (0–1760).
            label: Human-readable string shown next to "Top:", e.g.
                ``'880 (42 µm)'`` when calibrated, ``'880'`` otherwise.
        """
        self.etl_top = etl_value
        self.etl_top_label.setText(f"Top:  {label or str(etl_value)}")

    def set_bottom(self, etl_value: int, label: str = '') -> None:
        """Store the bottom ETL value and update the display label.

        Args:
            etl_value: Raw ETL current (0–1760).
            label: Human-readable string shown next to "Bottom:".
        """
        self.etl_bottom = etl_value
        self.etl_bottom_label.setText(f"Bottom:  {label or str(etl_value)}")

    def update_step_display(self, text: str) -> None:
        """Update the per-step depth display appended to the Planes label.

        Args:
            text: E.g. ``'≈ 1.2 µm'`` when calibrated, or ``''``.
        """
        if text:
            self.planes_label.setText(f"Planes: {text}")
        else:
            self.planes_label.setText("Planes:")

    def get_stack_params(self):
        """Return the current focus-stacking parameters.

        Returns:
            Tuple ``(top_etl, bottom_etl, n_planes, frames_per_plane)``
            where ``top_etl`` and ``bottom_etl`` are ``int | None``.
        """
        return (
            self.etl_top,
            self.etl_bottom,
            self.planes_spinbox.value(),
            self.frames_spinbox.value(),
        )

    def set_etl_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable the direct ETL slider and spinbox.

        Should be disabled while focus stacking is active so the user
        does not accidentally send a direct current command while the
        PSoC5 is cycling the waveform.

        Args:
            enabled: True to allow manual control, False to lock it.
        """
        self.etl_slider.setEnabled(enabled)
        self.etl_spinbox.setEnabled(enabled)

    def set_focus_stack_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable the focus-stacking parameter widgets.

        Should only be called by MainWindow after a successful enable or
        on disable/failure, so that controls are never locked due to a
        validation error.

        Args:
            enabled: True to allow editing, False to lock.
        """
        self.planes_spinbox.setEnabled(enabled)
        self.frames_spinbox.setEnabled(enabled)
        self.set_top_btn.setEnabled(enabled)
        self.set_bottom_btn.setEnabled(enabled)


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


class LogWindow(QtWidgets.QDialog):
    """Standalone window containing a CommandLogPanel.

    Closing the window hides it rather than destroying it so it can be
    reopened via the keyboard shortcut.
    """

    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.WindowType.Tool)
        self.setWindowTitle('Command Log')
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._log_panel = CommandLogPanel()
        layout.addWidget(self._log_panel)

    @property
    def panel(self):
        """Return the embedded CommandLogPanel."""
        return self._log_panel

    def closeEvent(self, event):
        event.ignore()
        self.hide()
