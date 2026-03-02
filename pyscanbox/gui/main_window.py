"""Main window for pyscanbox GUI application.

This module defines the main application window with a two-panel layout:
- Left panel: Primary hardware and acquisition controls
- Right panel: Image display and secondary controls
"""

import os
import time

import PyQt6.QtWidgets as QtWidgets
import PyQt6.QtCore as QtCore
import PyQt6.QtGui as QtGui

import pyscanbox
from pyscanbox.gui import app_controller
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

        # Hardware controller and acquisition elapsed-time tracking.
        self._ctrl = None
        self._acq_start_time = 0.0
        self._elapsed_timer = QtCore.QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed_time)

        self._init_app_controller()
        
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
        self._left_panel = panels.LeftControlPanel(self.config)
        main_splitter.addWidget(self._left_panel)

        # Create right panel (display)
        self._right_panel = panels.RightDisplayPanel(self.config)
        main_splitter.addWidget(self._right_panel)

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
        
        self._connect_action = QtGui.QAction("&Connect All", self)
        hardware_menu.addAction(self._connect_action)

        self._disconnect_action = QtGui.QAction("&Disconnect All", self)
        hardware_menu.addAction(self._disconnect_action)
        
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

    # ------------------------------------------------------------------
    # Hardware controller lifecycle
    # ------------------------------------------------------------------

    def _init_app_controller(self):
        """Create AppController from config and open hardware connections.

        Accepts either a ScanboxConfig object or a plain dict. When config
        is None the GUI runs in display-only mode with hardware disabled.
        """
        if self.config is None:
            self.statusBar.showMessage(
                "No configuration loaded — hardware disabled."
            )
            return

        config_dict = (
            self.config.to_dict()
            if hasattr(self.config, 'to_dict')
            else self.config
        )

        self._ctrl = app_controller.AppController(
            config_dict, parent=self
        )

        # Wire menu actions regardless of whether open() succeeds.
        self._connect_action.triggered.connect(self._on_connect_hardware)
        self._disconnect_action.triggered.connect(self._on_disconnect_hardware)

        try:
            self._ctrl.open()
        except RuntimeError as exc:
            self.statusBar.showMessage(f"Hardware init failed: {exc}")
            return

        self._connect_hardware()
        emulation = config_dict.get('emulation', {}).get('enabled', False)
        suffix = " (emulation)" if emulation else ""
        self.statusBar.showMessage(f"Hardware connected{suffix}.")

    def _connect_hardware(self):
        """Wire AppController signals to GUI widgets and vice versa."""
        if self._ctrl is None:
            return

        acq = self._left_panel.acquisition_group
        laser = self._left_panel.laser_group

        # Laser power slider -> Pockels cell
        laser.power_slider.valueChanged.connect(self._on_pockels_changed)

        # Acquisition buttons -> AppController
        acq.focus_button.clicked.connect(self._on_focus_clicked)
        acq.grab_button.clicked.connect(self._on_grab_clicked)

        # AppController -> GUI
        self._ctrl.position_updated.connect(self._on_position_updated)
        self._ctrl.frame_acquired.connect(self._on_frame_acquired)
        self._ctrl.frame_data_ready.connect(
            self._right_panel.image_display.update_frame
        )
        self._ctrl.acquisition_finished.connect(self._on_acquisition_finished)
        self._ctrl.hardware_error.connect(self._on_hardware_error)

    def closeEvent(self, event):
        """Stop acquisition and close hardware before the window is destroyed.

        Args:
            event: QCloseEvent from Qt.
        """
        if self._ctrl is not None and self._ctrl.is_open:
            self._ctrl.close()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Laser / Pockels
    # ------------------------------------------------------------------

    def _on_pockels_changed(self, percent):
        """Forward power-slider value to the Pockels cell.

        Args:
            percent: Slider value 0-100.
        """
        if self._ctrl is not None:
            self._ctrl.set_pockels(percent)

    # ------------------------------------------------------------------
    # Acquisition buttons
    # ------------------------------------------------------------------

    def _on_focus_clicked(self, checked):
        """Handle Focus button toggle.

        Args:
            checked: True when button enters the pressed/checked state.
        """
        if self._ctrl is None:
            return
        acq = self._left_panel.acquisition_group
        if checked:
            try:
                self._ctrl.start_focus()
            except RuntimeError as exc:
                acq.focus_button.setChecked(False)
                acq.focus_button.setText("Focus")
                self.statusBar.showMessage(str(exc))
                return
            acq.grab_button.setEnabled(False)
            self._acq_start_time = time.monotonic()
            self._elapsed_timer.start()
            self.statusBar.showMessage("Focus mode active")
        else:
            self._ctrl.stop_acquisition()

    def _on_grab_clicked(self, checked):
        """Handle Grab button toggle.

        Args:
            checked: True when button enters the pressed/checked state.
        """
        if self._ctrl is None:
            return
        acq = self._left_panel.acquisition_group
        if checked:
            file_grp = self._left_panel.file_group
            output_path = os.path.join(
                file_grp.directory_edit.text(),
                file_grp.get_output_basename()
            )
            try:
                self._ctrl.start_grab(output_path=output_path)
            except RuntimeError as exc:
                acq.grab_button.setChecked(False)
                acq.grab_button.setText("Grab")
                self.statusBar.showMessage(str(exc))
                return
            acq.focus_button.setEnabled(False)
            self._acq_start_time = time.monotonic()
            self._elapsed_timer.start()
            self.statusBar.showMessage(f"Grabbing: {output_path}")
        else:
            self._ctrl.stop_acquisition()

    # ------------------------------------------------------------------
    # AppController signal handlers
    # ------------------------------------------------------------------

    def _on_position_updated(self, pos):
        """Update the position display group from a Knobby position packet.

        Args:
            pos: Dict of axis name -> position in physical units
                e.g. {'X': 10.5, 'Y': -3.2, 'Z': 0.0, 'A': 0.0}.
        """
        pos_grp = self._left_panel.position_group
        pos_grp.world_x_edit.setText(f"{pos.get('X', 0.0):.2f}")
        pos_grp.world_y_edit.setText(f"{pos.get('Y', 0.0):.2f}")
        pos_grp.world_z_edit.setText(f"{pos.get('Z', 0.0):.2f}")
        pos_grp.objective_angle_edit.setText(f"{pos.get('A', 0.0):.3f}°")
        # Rotated coords mirror world until the rotation module is implemented.
        pos_grp.rotated_x_edit.setText(f"{pos.get('X', 0.0):.2f}")
        pos_grp.rotated_y_edit.setText(f"{pos.get('Y', 0.0):.2f}")
        pos_grp.rotated_z_edit.setText(f"{pos.get('Z', 0.0):.2f}")

    def _on_frame_acquired(self, count):
        """Update frame counter label.

        Args:
            count: Cumulative number of frames acquired.
        """
        self._left_panel.acquisition_group.frames_label.setText(str(count))

    def _on_acquisition_finished(self):
        """Reset acquisition controls when the scanner thread exits."""
        self._elapsed_timer.stop()
        acq = self._left_panel.acquisition_group
        # setChecked() does not emit clicked, so reset button text manually.
        acq.focus_button.setChecked(False)
        acq.focus_button.setText("Focus")
        acq.grab_button.setChecked(False)
        acq.grab_button.setText("Grab")
        acq.focus_button.setEnabled(True)
        acq.grab_button.setEnabled(True)
        self.statusBar.showMessage("Acquisition complete")

    def _on_hardware_error(self, message):
        """Show hardware error in the status bar.

        Args:
            message: Human-readable error description.
        """
        self.statusBar.showMessage(f"Hardware error: {message}")

    def _update_elapsed_time(self):
        """Refresh the time-recorded label once per second while acquiring."""
        elapsed = time.monotonic() - self._acq_start_time
        h = int(elapsed // 3600)
        m = int((elapsed % 3600) // 60)
        s = int(elapsed % 60)
        self._left_panel.acquisition_group.time_label.setText(
            f"{h}:{m:02d}:{s:02d}"
        )

    # ------------------------------------------------------------------
    # Hardware menu handlers
    # ------------------------------------------------------------------

    def _on_connect_hardware(self):
        """Re-open hardware if it is currently closed."""
        if self._ctrl is not None and not self._ctrl.is_open:
            try:
                self._ctrl.open()
                self._connect_hardware()
                self.statusBar.showMessage("Hardware reconnected.")
            except RuntimeError as exc:
                self.statusBar.showMessage(f"Reconnect failed: {exc}")

    def _on_disconnect_hardware(self):
        """Close all hardware connections."""
        if self._ctrl is not None and self._ctrl.is_open:
            self._ctrl.close()
            self.statusBar.showMessage("Hardware disconnected.")
