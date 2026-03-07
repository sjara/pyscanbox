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

import glob
import os

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
        if self._channel == 2 and n_channels >= 2:
            # Overlay: R = PMT1 (red), G = PMT0 (green), B = 0.
            g = _scale(frame_data[0])
            r = _scale(frame_data[1])
            height, width = g.shape
            rgb = np.zeros((height, width, 3), dtype=np.uint8)
            rgb[:, :, 0] = r
            rgb[:, :, 1] = g
        elif self._channel == 1:
            # PMT1 → red channel only.
            v = _scale(frame_data[min(1, n_channels - 1)])
            height, width = v.shape
            rgb = np.zeros((height, width, 3), dtype=np.uint8)
            rgb[:, :, 0] = v
        else:
            # PMT0 (default) → green channel only.
            v = _scale(frame_data[0])
            height, width = v.shape
            rgb = np.zeros((height, width, 3), dtype=np.uint8)
            rgb[:, :, 1] = v

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
        # linked.  Range and mid-point come from ScanboxController constants,
        # the single source of truth for this value.
        etl_min = hw_controller.ScanboxController.ETL_CURRENT_MIN
        etl_max = hw_controller.ScanboxController.ETL_CURRENT_MAX
        etl_mid = hw_controller.ScanboxController.ETL_CURRENT_MID
        layout.addWidget(QtWidgets.QLabel("ETL current"))

        # Horizontal slider, defaulting to the mid-level value.
        self.etl_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.etl_slider.setRange(etl_min, etl_max)
        self.etl_slider.setValue(etl_mid)
        self.etl_slider.setTickPosition(QtWidgets.QSlider.TickPosition.TicksBelow)
        self.etl_slider.setTickInterval((etl_max - etl_min) // 10)  # 10 ticks
        self.etl_slider.setMinimumWidth(120)
        layout.addWidget(self.etl_slider)

        # Spinbox for precise current entry
        self.etl_spinbox = QtWidgets.QSpinBox()
        self.etl_spinbox.setRange(etl_min, etl_max)
        self.etl_spinbox.setValue(etl_mid)
        self.etl_spinbox.setSuffix('')
        layout.addWidget(self.etl_spinbox)

        # Bidirectional link: slider ↔ spinbox
        self.etl_slider.valueChanged.connect(self.etl_spinbox.setValue)
        self.etl_spinbox.valueChanged.connect(self.etl_slider.setValue)

        layout.addStretch()
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
