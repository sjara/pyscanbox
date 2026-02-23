"""Widget components for pyscanbox GUI.

This module defines individual control groups and display widgets:
- LaserControlGroup: Laser power, shutter, wavelength
- ScannerControlGroup: Scanner parameters (frames, lines, mag, etc.)
- PositionDisplayGroup: Position coordinates display
- AcquisitionControlGroup: Acquisition buttons and status
- FileStorageGroup: File path and metadata
- ImageDisplayWidget: Main image display
- CameraPathGroup: Camera controls
- PMTControlGroup: PMT gain controls
- ImageDisplayControlGroup: Display settings
- OptotuneGroup: ETL control
"""

import PyQt6.QtWidgets as QtWidgets
import PyQt6.QtCore as QtCore
import PyQt6.QtGui as QtGui


class LaserControlGroup(QtWidgets.QGroupBox):
    """Laser control group box.
    
    Contains:
    - Indicator (ON/OFF label)
    - Shutter button (open/close toggle)
    - Wavelength spinbox
    - Power slider (vertical)
    """
    
    def __init__(self):
        """Initialize the laser control group."""
        super().__init__("Laser")
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        main_layout = QtWidgets.QHBoxLayout()
        
        # Left sub-layout (text/button controls)
        left_layout = QtWidgets.QVBoxLayout()
        
        # Indicator
        self.indicator_label = QtWidgets.QLabel("OFF")
        self.indicator_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.indicator_label.setStyleSheet(
            "QLabel { background-color: #444; color: white; "
            "padding: 5px; border-radius: 3px; font-weight: bold; }"
        )
        left_layout.addWidget(self.indicator_label)
        
        # Shutter button
        self.shutter_button = QtWidgets.QPushButton("Open Shutter")
        self.shutter_button.setCheckable(True)
        self.shutter_button.clicked.connect(self._on_shutter_toggle)
        left_layout.addWidget(self.shutter_button)
        
        # Wavelength
        wavelength_layout = QtWidgets.QHBoxLayout()
        wavelength_layout.addWidget(QtWidgets.QLabel("Wavelength:"))
        self.wavelength_spinbox = QtWidgets.QSpinBox()
        self.wavelength_spinbox.setRange(680, 1100)
        self.wavelength_spinbox.setValue(920)
        self.wavelength_spinbox.setSuffix(" nm")
        wavelength_layout.addWidget(self.wavelength_spinbox)
        left_layout.addLayout(wavelength_layout)
        
        main_layout.addLayout(left_layout)
        
        # Right sub-layout (power slider)
        right_layout = QtWidgets.QVBoxLayout()
        right_layout.addWidget(QtWidgets.QLabel("Power"), alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        
        # Add stretch before slider to center it
        right_layout.addStretch()
        
        self.power_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Vertical)
        self.power_slider.setRange(0, 100)
        self.power_slider.setValue(0)
        self.power_slider.setTickPosition(QtWidgets.QSlider.TickPosition.TicksRight)
        self.power_slider.setTickInterval(10)
        self.power_slider.setSingleStep(2)  # 2% step for mouse wheel
        right_layout.addWidget(self.power_slider, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        
        # Add stretch after slider to center it
        right_layout.addStretch()
        
        self.power_label = QtWidgets.QLabel("0%")
        self.power_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self.power_label)
        
        self.power_slider.valueChanged.connect(
            lambda v: self.power_label.setText(f"{v}%")
        )
        
        main_layout.addLayout(right_layout)
        
        self.setLayout(main_layout)
        
    def _on_shutter_toggle(self, checked):
        """Handle shutter button toggle.
        
        Args:
            checked: True if shutter should be open.
        """
        if checked:
            self.shutter_button.setText("Close Shutter")
            self.indicator_label.setText("ON")
            self.indicator_label.setStyleSheet(
                "QLabel { background-color: #2d2; color: white; "
                "padding: 5px; border-radius: 3px; font-weight: bold; }"
            )
        else:
            self.shutter_button.setText("Open Shutter")
            self.indicator_label.setText("OFF")
            self.indicator_label.setStyleSheet(
                "QLabel { background-color: #444; color: white; "
                "padding: 5px; border-radius: 3px; font-weight: bold; }"
            )


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
        
        # Magnification
        self.magnification_combobox = QtWidgets.QComboBox()
        self.magnification_combobox.addItems(["1.0", "2.0", "3.0", "4.0"])
        self.magnification_combobox.setCurrentIndex(0)
        layout.addRow("Magnification:", self.magnification_combobox)
        
        # Frame rate
        self.frame_rate_label = QtWidgets.QLabel("30.5 Hz")
        layout.addRow("Frame rate:", self.frame_rate_label)
        
        # Scan mode selector (combo box)
        self.scan_mode_combobox = QtWidgets.QComboBox()
        self.scan_mode_combobox.addItems(["Unidirectional", "Bidirectional"])
        self.scan_mode_combobox.setCurrentIndex(0)
        layout.addRow("Scan mode:", self.scan_mode_combobox)
        
        self.setLayout(layout)


class PositionDisplayGroup(QtWidgets.QGroupBox):
    """Position display group box.
    
    Contains:
    - Objective angle
    - World coordinates (x, y, z)
    - Rotated coordinates (x, y, z)
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
        
        # X, Y, Z labels above coordinate fields
        layout.addWidget(QtWidgets.QLabel("X"), 1, 1, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(QtWidgets.QLabel("Y"), 1, 2, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(QtWidgets.QLabel("Z"), 1, 3, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        
        # World coordinates
        layout.addWidget(QtWidgets.QLabel("World:"), 2, 0)
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
        
        # Rotated coordinates
        layout.addWidget(QtWidgets.QLabel("Rotated:"), 3, 0)
        self.rotated_x_edit = QtWidgets.QLineEdit("0.00")
        self.rotated_x_edit.setReadOnly(True)
        self.rotated_x_edit.setMaximumWidth(70)
        layout.addWidget(self.rotated_x_edit, 3, 1)
        
        self.rotated_y_edit = QtWidgets.QLineEdit("0.00")
        self.rotated_y_edit.setReadOnly(True)
        self.rotated_y_edit.setMaximumWidth(70)
        layout.addWidget(self.rotated_y_edit, 3, 2)
        
        self.rotated_z_edit = QtWidgets.QLineEdit("0.00")
        self.rotated_z_edit.setReadOnly(True)
        self.rotated_z_edit.setMaximumWidth(70)
        layout.addWidget(self.rotated_z_edit, 3, 3)
        
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


class FileStorageGroup(QtWidgets.QGroupBox):
    """File storage group box.
    
    Contains:
    - Directory selection button and path display
    - Subject, Date, Session ID fields
    - Save channels selector
    """
    
    def __init__(self):
        """Initialize the file storage group."""
        super().__init__("File Storage")
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
        self.directory_edit.setText("/data/")
        layout.addWidget(self.directory_edit, dir_row, 1)
        
        # Metadata fields
        layout.addWidget(QtWidgets.QLabel("Subject:"), 1, 0)
        self.subject_edit = QtWidgets.QLineEdit()
        self.subject_edit.setPlaceholderText("Subject ID")
        layout.addWidget(self.subject_edit, 1, 1)
        
        layout.addWidget(QtWidgets.QLabel("Date:"), 2, 0)
        self.date_edit = QtWidgets.QLineEdit()
        self.date_edit.setPlaceholderText("YYYY-MM-DD")
        from datetime import datetime
        self.date_edit.setText(datetime.now().strftime("%Y-%m-%d"))
        layout.addWidget(self.date_edit, 2, 1)
        
        layout.addWidget(QtWidgets.QLabel("Session ID:"), 3, 0)
        self.session_edit = QtWidgets.QLineEdit()
        self.session_edit.setPlaceholderText("001")
        layout.addWidget(self.session_edit, 3, 1)
        
        # Save channels selector
        layout.addWidget(QtWidgets.QLabel("Save Channels:"), 4, 0)
        self.channels_combobox = QtWidgets.QComboBox()
        self.channels_combobox.addItems(["PMT0", "PMT1", "PMT0 & PMT1"])
        self.channels_combobox.setCurrentIndex(2)
        layout.addWidget(self.channels_combobox, 4, 1)
        
        self.setLayout(layout)
        
    def _select_directory(self):
        """Open directory selection dialog."""
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Data Directory", self.directory_edit.text()
        )
        if directory:
            self.directory_edit.setText(directory)


class ImageDisplayWidget(QtWidgets.QWidget):
    """Main image display widget.
    
    Uses a QGraphicsView for high-performance image rendering.
    This is a placeholder that will be expanded for real-time display.
    """
    
    def __init__(self):
        """Initialize the image display widget."""
        super().__init__()
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout()
        
        # Create graphics view for image display
        self.graphics_view = QtWidgets.QGraphicsView()
        self.graphics_scene = QtWidgets.QGraphicsScene()
        self.graphics_view.setScene(self.graphics_scene)
        
        # Set background and basic properties
        self.graphics_view.setBackgroundBrush(QtGui.QBrush(QtGui.QColor(30, 30, 30)))
        self.graphics_view.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.graphics_view.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        
        # Add placeholder text
        text_item = self.graphics_scene.addText(
            "Image Display\n(Live preview will appear here)",
            QtGui.QFont("Arial", 16)
        )
        text_item.setDefaultTextColor(QtGui.QColor(150, 150, 150))
        
        layout.addWidget(self.graphics_view)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)


class CameraPathGroup(QtWidgets.QGroupBox):
    """Camera path control group box.
    
    Contains:
    - Enable checkbox
    - Exposure slider
    - Camera properties button
    """
    
    def __init__(self):
        """Initialize the camera path group."""
        super().__init__("Camera Path")
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout()
        
        # Enable checkbox
        self.enable_checkbox = QtWidgets.QCheckBox("Enable")
        layout.addWidget(self.enable_checkbox)
        
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
        
        layout.addStretch()
        self.setLayout(layout)


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
        
        # ETL control label
        layout.addWidget(QtWidgets.QLabel("ETL"))
        
        # Vertical slider
        slider_layout = QtWidgets.QHBoxLayout()
        slider_layout.addStretch()
        
        self.etl_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Vertical)
        self.etl_slider.setRange(-100, 100)
        self.etl_slider.setValue(0)
        self.etl_slider.setTickPosition(QtWidgets.QSlider.TickPosition.TicksRight)
        self.etl_slider.setTickInterval(20)
        slider_layout.addWidget(self.etl_slider)
        
        slider_layout.addStretch()
        layout.addLayout(slider_layout)
        
        # Value label
        self.etl_label = QtWidgets.QLabel("0")
        self.etl_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.etl_label)
        
        self.etl_slider.valueChanged.connect(
            lambda v: self.etl_label.setText(str(v))
        )
        
        self.setLayout(layout)
