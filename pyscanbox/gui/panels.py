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
    - Scanner settings (frames, lines, magnification, etc.)
    - Position display (objective angle, coordinates)
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
        self.scanner_group = widgets.ScannerControlGroup()
        self.position_group = widgets.PositionDisplayGroup()
        self.acquisition_group = widgets.AcquisitionControlGroup()
        self.file_group = widgets.FileStorageGroup(self.config)

        layout.addWidget(self.laser_group)
        layout.addWidget(self.scanner_group)
        layout.addWidget(self.position_group)
        layout.addWidget(self.acquisition_group)
        layout.addWidget(self.file_group)

        # Add stretch to push everything to the top
        layout.addStretch()
        
        self.setLayout(layout)
        self.setMinimumWidth(250)
        self.setMaximumWidth(400)


class RightDisplayPanel(QtWidgets.QWidget):
    """Right display panel containing image and secondary controls.
    
    Contains:
    - Top: Main image display area
    - Bottom: Secondary control panels (camera, PMT, display, optotune)
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
        # Create vertical splitter for image display and controls
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        
        # Top: Main image display
        self.image_display = widgets.ImageDisplayWidget()
        splitter.addWidget(self.image_display)
        
        # Bottom: Secondary controls
        controls_panel = self._create_secondary_controls()
        splitter.addWidget(controls_panel)
        
        # Set initial sizes (image takes most space)
        splitter.setSizes([600, 200])
        
        # Add splitter to layout
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(splitter)
        layout.setContentsMargins(5, 5, 5, 5)
        self.setLayout(layout)
        
    def _create_secondary_controls(self):
        """Create the secondary controls panel.
        
        Returns:
            QWidget containing the secondary control group boxes.
        """
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout()
        layout.setSpacing(10)
        
        # Add control group boxes side-by-side
        self.camera_group = widgets.CameraPathGroup()
        self.pmt_group = widgets.PMTControlGroup()
        self.image_display_group = widgets.ImageDisplayControlGroup()
        self.optotune_group = widgets.OptotuneGroup()

        layout.addWidget(self.camera_group)
        layout.addWidget(self.pmt_group)
        layout.addWidget(self.image_display_group)
        layout.addWidget(self.optotune_group)
        
        panel.setLayout(layout)
        return panel
