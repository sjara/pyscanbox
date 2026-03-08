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
from pyscanbox.gui import widgets


class MainWindow(QtWidgets.QMainWindow):
    """Main application window for pyscanbox.
    
    Provides a two-panel layout with hardware controls on the left
    and real-time image display on the right.
    """
    
    WINDOW_TITLE = "Two-Photon Microscope Control Software"

    # Default window geometry
    DEFAULT_WINDOW_X = 100
    DEFAULT_WINDOW_Y = 100
    DEFAULT_WINDOW_WIDTH = 1200
    DEFAULT_WINDOW_HEIGHT = 900
    
    # Default panel widths (for splitter)
    DEFAULT_LEFT_PANEL_WIDTH = 300
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
        # True when a Grab (data-saving) acquisition is running; False for Focus.
        # Used to gate post-acquisition actions that only apply to Grab (e.g.
        # Session ID increment).
        self._grab_active = False
        self._elapsed_timer = QtCore.QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed_time)

        self._init_app_controller()
        
    def _init_ui(self):
        """Initialize the user interface components."""
        self.setWindowTitle(self.WINDOW_TITLE)
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

        # Histogram is hidden by default (can be enabled via View menu).
        self._right_panel.histogram.setVisible(False)

        # Create status bar
        self.statusBar = QtWidgets.QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready")

        # Create the command log dock at the bottom of the window.
        self._log_panel = widgets.CommandLogPanel()
        self._log_dock = QtWidgets.QDockWidget('Command Log', self)
        self._log_dock.setObjectName('CommandLogDock')
        self._log_dock.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.BottomDockWidgetArea
            | QtCore.Qt.DockWidgetArea.TopDockWidgetArea
        )
        self._log_dock.setWidget(self._log_panel)
        # Give the dock a reasonable default height.
        self._log_panel.setMinimumHeight(120)
        self.addDockWidget(
            QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock
        )
        # Keep the rest of the window at its current size when the log dock
        # is detached.  topLevelChanged fires before Qt reflows the layout,
        # so we use a zero-delay timer to resize after the layout settles.
        self._log_dock.topLevelChanged.connect(self._on_log_dock_floating)
        
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

        view_menu.addSeparator()

        histogram_action = QtGui.QAction("Show &Histogram", self)
        histogram_action.setShortcut("Ctrl+H")
        histogram_action.setCheckable(True)
        histogram_action.setChecked(False)
        histogram_action.triggered.connect(self._toggle_histogram)
        view_menu.addAction(histogram_action)
        self._histogram_action = histogram_action

        log_action = QtGui.QAction("Show &Command Log", self)
        log_action.setShortcut("Ctrl+L")
        log_action.setCheckable(True)
        log_action.setChecked(True)
        log_action.triggered.connect(self._toggle_log_dock)
        view_menu.addAction(log_action)
        self._log_dock_action = log_action
        
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

    def _toggle_log_dock(self, checked):
        """Show or hide the Command Log dock widget.

        Resizes the main window to compensate for the space the dock
        occupies so the rest of the UI keeps its current size.

        Args:
            checked: True to show the dock, False to hide it.
        """
        if not checked:
            # Snapshot the full window height (dock included) and the dock
            # height *before* anything is hidden, so we have exact numbers.
            self._win_height_with_log = self.height()
            self._log_dock_saved_h = self._log_dock.height()
            self._log_dock.setVisible(False)
            target_h = self._win_height_with_log - self._log_dock_saved_h
            QtCore.QTimer.singleShot(
                0, lambda: self.resize(self.width(), target_h)
            )
        else:
            self._log_dock.setVisible(True)
            # Restore the exact window height that included the log dock.
            restore_h = getattr(self, '_win_height_with_log', self.height())
            QtCore.QTimer.singleShot(
                0, lambda: self.resize(self.width(), restore_h)
            )

    def _toggle_histogram(self, checked: bool) -> None:
        """Show or hide the pixel-intensity histogram.

        The ``frame_data_ready`` signal remains permanently connected;
        ``HistogramWidget.update_frame`` short-circuits immediately when the
        widget is hidden, so no connect/disconnect management is needed here.

        Args:
            checked: True to show the histogram, False to hide it.
        """
        self._right_panel.histogram.setVisible(checked)

    def _on_log_dock_floating(self, floating: bool) -> None:
        """Resize the main window when the log dock is detached or re-docked.

        When the dock becomes a floating window Qt expands the remaining
        content to fill the freed space.  We compensate by shrinking the
        main window back to its pre-float height.  The QTimer delay lets
        the layout reflow complete before we apply the resize.

        Args:
            floating: True when the dock is being detached (made floating).
        """
        if floating:
            dock_h = self._log_dock.height()
            self._win_height_with_log = self.height()
            target_h = self._win_height_with_log - dock_h
            QtCore.QTimer.singleShot(
                0, lambda: self.resize(self.width(), target_h)
            )
            
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

        # CameraPath toggle -> mirror control
        camera = self._left_panel.camera_group
        camera.path_changed.connect(self._on_camera_path_changed)
        # Force the hardware mirror to match the GUI default (Epi) at startup
        # since there is no way to read back the current mirror position.
        self._on_camera_path_changed(camera.current_path)

        # PMT gain sliders -> hardware
        pmt = self._right_panel.pmt_group
        pmt.pmt0_slider.valueChanged.connect(
            lambda v: self._on_pmt_gain_changed(0, v)
        )
        pmt.pmt1_slider.valueChanged.connect(
            lambda v: self._on_pmt_gain_changed(1, v)
        )

        # Magnification combobox -> hardware
        scanner = self._left_panel.scanner_group
        scanner.magnification_combobox.currentIndexChanged.connect(
            self._on_magnification_changed
        )

        # ETL slider -> hardware (spinbox is bidirectionally linked to slider
        # inside OptotuneGroup, so wiring the slider covers both widgets)
        optotune = self._right_panel.optotune_group
        optotune.etl_slider.valueChanged.connect(self._on_etl_current_changed)
        # Send the initial slider value so hardware matches the GUI at startup.
        self._on_etl_current_changed(optotune.etl_slider.value())

        # Acquisition buttons -> AppController
        acq.focus_button.clicked.connect(self._on_focus_clicked)
        acq.grab_button.clicked.connect(self._on_grab_clicked)
        acq.snapshot_button.clicked.connect(self._on_snapshot_clicked)

        # AppController -> GUI
        self._ctrl.position_updated.connect(self._on_position_updated)
        self._ctrl.frame_acquired.connect(self._on_frame_acquired)
        self._ctrl.frame_data_ready.connect(
            self._right_panel.image_display.update_frame
        )
        # Always connected: update_frame is a no-op when the widget is hidden
        # or when the frame-skip counter has not elapsed (see HistogramWidget).
        self._ctrl.frame_data_ready.connect(
            self._right_panel.histogram.update_frame
        )
        self._ctrl.acquisition_finished.connect(self._on_acquisition_finished)
        self._ctrl.hardware_error.connect(self._on_hardware_error)

        # Command log: wire both the typed command signal and hardware errors.
        self._ctrl.command_logged.connect(self._log_panel.append)
        self._ctrl.hardware_error.connect(self._log_panel.append_error)

    def closeEvent(self, event):
        """Stop acquisition and close hardware before the window is destroyed.

        Zeros the PMT gains and Pockels cell before shutting down hardware
        so that the laser and detectors are in a safe state.

        Args:
            event: QCloseEvent from Qt.
        """
        if self._ctrl is not None and self._ctrl.is_open:
            # Zero PMTs and Pockels via hardware calls before closing.
            # Setting the GUI sliders fires valueChanged, which calls the
            # hardware through the existing signal connections.
            pmt = self._right_panel.pmt_group
            pmt.pmt0_slider.setValue(0)
            pmt.pmt1_slider.setValue(0)
            laser = self._left_panel.laser_group
            laser.power_slider.setValue(0)
            self._ctrl.close()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Camera path / mirror
    # ------------------------------------------------------------------

    def _on_camera_path_changed(self, mode: str):
        """Toggle epi/2P mirror when the Light Path toggle changes.

        Args:
            mode: ``'epi'`` or ``'2p'`` as emitted by CameraPathGroup.
        """
        if self._ctrl is None:
            return
        self._ctrl.set_mirror(mode)

    def _on_magnification_changed(self, index: int):
        """Handle magnification combobox selection change.

        Args:
            index: 0-based combobox index (0 = largest FOV, 12 = highest zoom).
        """
        if self._ctrl is None:
            return
        try:
            self._ctrl.set_magnification(index)
        except RuntimeError:
            pass  # hardware not open yet; silently ignore

    def _on_etl_current_changed(self, current: int):
        """Forward ETL slider / spinbox value to hardware and update depth label.

        The depth label shows the raw ETL current value (4 digits) when no
        calibration is loaded, or depth in µm once a calibration file is
        present (loaded by AppController.open from optotune.calibration_file).

        Args:
            current: ETL current level (0–1760 hardware units).
        """
        # Update depth label regardless of hardware state.
        optotune = self._right_panel.optotune_group
        depth = (
            self._ctrl.etl_to_depth(current)
            if self._ctrl is not None
            else None
        )
        optotune.set_depth_display(
            f'{depth} \u00b5m' if depth is not None else f'{current:04d}'
        )
        # Forward to hardware (no-op if not yet connected).
        if self._ctrl is not None:
            try:
                self._ctrl.set_etl_current(current)
            except RuntimeError:
                pass  # hardware not open yet; silently ignore

    def _on_pmt_gain_changed(self, pmt_id: int, percent: int):
        """Forward a PMT gain slider value to the hardware.

        Args:
            pmt_id: PMT channel index (0 or 1).
            percent: Slider value 0-100.
        """
        if self._ctrl is not None:
            self._ctrl.set_pmt_gain(pmt_id, percent)

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
            self._grab_active = False
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
            # 0 = run forever, matching MATLAB convention.
            frames = self._left_panel.scanner_group.total_frames_spinbox.value()
            # Combobox indices: 0 = PMT0 only, 1 = PMT1 only, 2 = both.
            save_channels = file_grp.channels_combobox.currentIndex()
            self._grab_active = True
            try:
                self._ctrl.start_grab(output_path=output_path, frames=frames,
                                      save_channels=save_channels)
            except RuntimeError as exc:
                acq.grab_button.setChecked(False)
                acq.grab_button.setText("Grab")
                self._grab_active = False
                self.statusBar.showMessage(str(exc))
                return
            acq.focus_button.setEnabled(False)
            self._acq_start_time = time.monotonic()
            self._elapsed_timer.start()
            self.statusBar.showMessage(f"Grabbing: {output_path}")
        else:
            self._ctrl.stop_acquisition()

    def _on_snapshot_clicked(self):
        """Save a PNG snapshot of the current frame.

        The file is written to the directory and subject/date fields from
        File Storage, but uses an independently incrementing numeric suffix
        instead of the Session ID, giving filenames like
        ``mouse01_20260306_002.png``.

        Shows a status-bar message on success or failure.
        """
        file_grp = self._left_panel.file_group
        path = file_grp.get_snapshot_path()
        saved = self._right_panel.image_display.save_snapshot(path)
        if saved:
            file_grp.increment_snapshot_index()
            self.statusBar.showMessage(f"Snapshot saved: {path}")
        else:
            self.statusBar.showMessage(
                "Snapshot: no frame available yet — start Focus or Grab first."
            )

    # ------------------------------------------------------------------
    # AppController signal handlers
    # ------------------------------------------------------------------

    def _on_position_updated(self, pos):
        """Update the position display group from hardware position data.

        Updates the World (Knobby relative), Abs (motor hardware absolute),
        and Angle fields.  Rotated coordinates are left at their current
        values — the row is reserved for the future angle-compensation mode.

        Args:
            pos: Dict containing:
                ``'X'``, ``'Y'``, ``'Z'``, ``'A'``: Knobby dpos in physical
                units (relative, matches the Knobby screen display).
                ``'abs_X'``, ``'abs_Y'``, ``'abs_Z'``, ``'abs_A'``: Absolute
                motor hardware positions in physical units.
        """
        pos_grp = self._right_panel.position_group

        # World row — Knobby relative position (matches Knobby screen)
        pos_grp.world_x_edit.setText(f"{pos.get('X', 0.0):.2f}")
        pos_grp.world_y_edit.setText(f"{pos.get('Y', 0.0):.2f}")
        pos_grp.world_z_edit.setText(f"{pos.get('Z', 0.0):.2f}")
        pos_grp.objective_angle_edit.setText(f"{pos.get('A', 0.0):.3f}°")

        # Abs row — motor hardware absolute positions
        pos_grp.abs_x_edit.setText(f"{pos.get('abs_X', 0.0):.2f}")
        pos_grp.abs_y_edit.setText(f"{pos.get('abs_Y', 0.0):.2f}")
        pos_grp.abs_z_edit.setText(f"{pos.get('abs_Z', 0.0):.2f}")

        # Rotated row: reserved for angle-compensation mode (future).
        # Mirror World values until the rotation module is implemented.
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
        # Advance the session ID only after a data-saving Grab, not Focus.
        if self._grab_active:
            self._left_panel.file_group.increment_session_id()
        self._grab_active = False
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
