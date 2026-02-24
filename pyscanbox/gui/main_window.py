"""Main window for pyscanbox GUI application.

This module defines the main application window with a two-panel layout:
- Left panel: Primary hardware and acquisition controls
- Right panel: Image display and secondary controls
"""

import PyQt6.QtWidgets as QtWidgets
import PyQt6.QtCore as QtCore
import PyQt6.QtGui as QtGui

import pyscanbox
from pyscanbox.gui import panels


class MainWindow(QtWidgets.QMainWindow):
    """Main application window for pyscanbox.
    
    Provides a two-panel layout with hardware controls on the left
    and real-time image display on the right.
    """
    
    # Default window geometry
    DEFAULT_WINDOW_X = 100
    DEFAULT_WINDOW_Y = 100
    DEFAULT_WINDOW_WIDTH = 1200
    DEFAULT_WINDOW_HEIGHT = 900
    
    # Default panel widths (for splitter)
    DEFAULT_LEFT_PANEL_WIDTH = 250
    DEFAULT_RIGHT_PANEL_WIDTH = DEFAULT_WINDOW_WIDTH - DEFAULT_LEFT_PANEL_WIDTH
    
    def __init__(self, config=None):
        """Initialize the main window.
        
        Args:
            config: Optional ScanboxConfig object for initialization.
        """
        super().__init__()
        self.config = config
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the user interface components."""
        self.setWindowTitle("pyscanbox - Two-Photon Microscope Control")
        self.setGeometry(
            self.DEFAULT_WINDOW_X,
            self.DEFAULT_WINDOW_Y,
            self.DEFAULT_WINDOW_WIDTH,
            self.DEFAULT_WINDOW_HEIGHT
        )
        
        # Create central widget and main layout
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        
        # Create horizontal splitter for left/right panels
        main_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        
        # Create left panel (controls)
        left_panel = panels.LeftControlPanel(self.config)
        main_splitter.addWidget(left_panel)
        
        # Create right panel (display)
        right_panel = panels.RightDisplayPanel(self.config)
        main_splitter.addWidget(right_panel)
        
        # Set initial splitter sizes (left panel narrower than right)
        main_splitter.setSizes([
            self.DEFAULT_LEFT_PANEL_WIDTH,
            self.DEFAULT_RIGHT_PANEL_WIDTH
        ])
        
        # Add splitter to central widget
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(main_splitter)
        layout.setContentsMargins(0, 0, 0, 0)
        central_widget.setLayout(layout)
        
        # Create menu bar
        self._create_menu_bar()
        
        # Create status bar
        self.statusBar = QtWidgets.QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready")
        
    def _create_menu_bar(self):
        """Create the application menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        load_action = QtGui.QAction("&Load Configuration...", self)
        load_action.setShortcut("Ctrl+O")
        file_menu.addAction(load_action)
        
        save_action = QtGui.QAction("&Save Configuration...", self)
        save_action.setShortcut("Ctrl+S")
        file_menu.addAction(save_action)
        
        file_menu.addSeparator()
        
        exit_action = QtGui.QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Hardware menu
        hardware_menu = menubar.addMenu("&Hardware")
        
        connect_action = QtGui.QAction("&Connect All", self)
        hardware_menu.addAction(connect_action)
        
        disconnect_action = QtGui.QAction("&Disconnect All", self)
        hardware_menu.addAction(disconnect_action)
        
        hardware_menu.addSeparator()
        
        calibrate_action = QtGui.QAction("C&alibrate...", self)
        hardware_menu.addAction(calibrate_action)
        
        # View menu
        view_menu = menubar.addMenu("&View")
        
        fullscreen_action = QtGui.QAction("&Fullscreen", self)
        fullscreen_action.setShortcut("F11")
        fullscreen_action.setCheckable(True)
        fullscreen_action.triggered.connect(self._toggle_fullscreen)
        view_menu.addAction(fullscreen_action)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        about_action = QtGui.QAction("&About pyscanbox", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        
    def _toggle_fullscreen(self, checked):
        """Toggle fullscreen mode.
        
        Args:
            checked: True if fullscreen should be enabled.
        """
        if checked:
            self.showFullScreen()
        else:
            self.showNormal()
            
    def _show_about(self):
        """Show the about dialog."""
        QtWidgets.QMessageBox.about(
            self,
            "About pyscanbox",
            "<h2>pyscanbox</h2>"
            "<p>Two-Photon Microscope Control Software</p>"
            f"<p>Version {pyscanbox.__version__}</p>"
            "<p>Python implementation of the Scanbox system</p>"
        )
