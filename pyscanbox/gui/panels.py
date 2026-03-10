"""Panel widgets for pyscanbox GUI.

This module defines the major panel components:
- LeftControlPanel: Primary hardware and acquisition controls
- RightDisplayPanel: Image display and secondary controls
"""

import PyQt6.QtWidgets as QtWidgets
import PyQt6.QtCore as QtCore

from pyscanbox.gui import widgets


class LeftControlPanel(QtWidgets.QWidget):
    """Left control panel containing primary controls.
    
    Contains vertically stacked group boxes for:
    - Laser control (power, shutter, wavelength)
    - Light path toggle (2p / Epi)
    - Scanner settings (frames, lines, magnification, etc.)
    - Acquisition control (focus, grab, snapshot)
    - File storage (directory, metadata, channels)
    """
    
    def __init__(self, config=None):
        """Initialize the left control panel.
        
        Args:
            config: Optional ScanboxConfig object.
        """
        super().__init__()
        self.config = config
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Add control group boxes
        self.laser_group = widgets.LaserControlGroup(self.config)
        self.camera_group = widgets.CameraPathGroup()
        self.scanner_group = widgets.ScannerControlGroup()
        self.acquisition_group = widgets.AcquisitionControlGroup()
        self.file_group = widgets.FileStorageGroup(self.config)

        layout.addWidget(self.laser_group)
        layout.addWidget(self.camera_group)
        layout.addWidget(self.scanner_group)
        layout.addWidget(self.acquisition_group)
        layout.addWidget(self.file_group)

        # Add stretch to push everything to the top
        layout.addStretch()
        
        self.setLayout(layout)
        self.setMinimumWidth(250)
        self.setMaximumWidth(400)


class RightDisplayPanel(QtWidgets.QWidget):
    """Right display panel containing image and secondary controls.

    Contains (top to bottom):
    - Main image display area
    - Pixel-intensity histogram (thin strip, full width)
    - Secondary control panels (camera, PMT, display, optotune)
    """
    
    def __init__(self, config=None):
        """Initialize the right display panel.
        
        Args:
            config: Optional ScanboxConfig object.
        """
        super().__init__()
        self.config = config
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        # Create vertical splitter for image display, histogram, and controls
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)

        # Top: Main image display
        self.image_display = widgets.ImageDisplayWidget(config=self.config)
        splitter.addWidget(self.image_display)

        # Middle: Pixel-intensity histogram (full panel width, thin strip)
        self.histogram = widgets.HistogramWidget()
        splitter.addWidget(self.histogram)

        # Middle: Frame selector for browsing loaded recordings (thin strip)
        self.frame_selector = widgets.FrameSelectorWidget()
        splitter.addWidget(self.frame_selector)

        # Bottom: Secondary controls
        controls_panel = self._create_secondary_controls()
        splitter.addWidget(controls_panel)

        # Distribute vertical space: image gets most, histogram and frame
        # selector are thin strips, controls take a fixed chunk.
        splitter.setSizes([500, 90, 36, 200])

        # Wire the Image Display gain slider to the image display widget so
        # that moving the slider re-scales the brightness of the next frame.
        self.image_display_group.gain_slider.valueChanged.connect(
            self.image_display.set_gain
        )

        # Wire the channel combobox so that PMT0 / PMT1 / both selections
        # are forwarded to the display widget.
        self.image_display_group.channel_combobox.currentIndexChanged.connect(
            self.image_display.set_channel
        )

        # Add splitter to layout
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(splitter)
        layout.setContentsMargins(5, 5, 5, 5)
        self.setLayout(layout)
        
    def _create_secondary_controls(self):
        """Create the secondary controls panel.

        A two-item QSplitter gives a single resize handle between Objective
        Position (left, initially 300 px) and the remaining three panels
        (right).  PMT Control, Image Display, and Optotune share the right
        side equally with no handles between them.

        Returns:
            QSplitter containing the secondary control group boxes.
        """
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setContentsMargins(0, 0, 0, 0)

        # Add control group boxes side-by-side
        self.position_group = widgets.PositionDisplayGroup()
        self.pmt_group = widgets.PMTControlGroup()
        self.image_display_group = widgets.ImageDisplayControlGroup()
        # Extract ETL default value from config; OptotuneGroup uses it as its
        # initial slider position.  Falls back to ETL_CURRENT_MID when absent.
        config_dict = (
            self.config.to_dict()
            if hasattr(self.config, 'to_dict')
            else (self.config or {})
        )
        etl_default = config_dict.get('optotune', {}).get('default_value', None)
        self.optotune_group = widgets.OptotuneGroup(default_value=etl_default)

        # Left side: Objective Position (resizable via splitter handle).
        splitter.addWidget(self.position_group)

        # Right side: PMT Control, Image Display, Optotune in a plain
        # QHBoxLayout — equal stretch, no handles between them.
        right_container = QtWidgets.QWidget()
        right_layout = QtWidgets.QHBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        right_layout.addWidget(self.pmt_group)
        right_layout.addWidget(self.image_display_group)
        right_layout.addWidget(self.optotune_group)
        splitter.addWidget(right_container)

        # Objective Position 300 px; right container takes the rest.
        splitter.setSizes([300, 600])

        return splitter
