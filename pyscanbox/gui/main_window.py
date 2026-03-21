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
from pyscanbox.gui import bidir_cal_dialog
from pyscanbox.gui import etl_cal_dialog
from pyscanbox.gui import pockels_cal_dialog
from pyscanbox.gui import scanner_gains_dialog
from pyscanbox.gui import widgets
from pyscanbox.io import sbx_reader
from pyscanbox.utils import coordinate_transform


class MainWindow(QtWidgets.QMainWindow):
    """Main application window for pyscanbox.
    
    Provides a two-panel layout with hardware controls on the left
    and real-time image display on the right.
    """
    
    WINDOW_TITLE = "Two-Photon Microscope Control Software"

    # Default window geometry
    DEFAULT_WINDOW_X = 100
    DEFAULT_WINDOW_Y = 100
    DEFAULT_WINDOW_WIDTH = 1400
    DEFAULT_WINDOW_HEIGHT = 900
    
    # Default panel widths (for splitter)
    DEFAULT_LEFT_PANEL_WIDTH = 300
    DEFAULT_RIGHT_PANEL_WIDTH = DEFAULT_WINDOW_WIDTH - DEFAULT_LEFT_PANEL_WIDTH
    
    def __init__(self, config=None, config_path=None):
        """Initialize the main window.
        
        Args:
            config: Optional ScanboxConfig object for initialization.
            config_path: Path to the config YAML file; passed to
                AppController so bidir calibration can be saved alongside it.
        """
        super().__init__()
        self.config = config
        self._config_path = config_path
        self._init_ui()

        # Hardware controller and acquisition elapsed-time tracking.
        self._ctrl = None
        self._acq_start_time = 0.0
        # ScanboxOriginalReader for a loaded recording; None when no file is open.
        self._sbx_reader: sbx_reader.ScanboxOriginalReader | None = None
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

        # Maps plugin name → QAction (populated in _create_menu_bar).
        # Declared after _create_menu_bar() because it returns a reference
        # to _plugin_actions which is created inside that method.
        # (The attribute is also accessible via self._plugin_actions directly.)

        # Histogram is hidden by default (can be enabled via View menu).
        self._right_panel.histogram.setVisible(False)

        # Frame selector is hidden by default (can be enabled via View menu).
        self._right_panel.frame_selector.setVisible(False)

        # Re-render the current loaded frame whenever the gain slider moves.
        # set_gain (wired in panels.py) updates _gain first; this fires next
        # so update_frame sees the new value immediately.
        self._right_panel.image_display_group.gain_slider.valueChanged.connect(
            self._on_display_gain_changed
        )

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
        
        # load_action = QtGui.QAction("&Load Configuration...", self)
        # load_action.setShortcut("Ctrl+O")
        # file_menu.addAction(load_action)
        
        # save_action = QtGui.QAction("&Save Configuration...", self)
        # save_action.setShortcut("Ctrl+S")
        # file_menu.addAction(save_action)
        
        # file_menu.addSeparator()

        open_data_action = QtGui.QAction("Open &Data...", self)
        open_data_action.setShortcut("Ctrl+D")
        open_data_action.triggered.connect(self._open_data_file)
        file_menu.addAction(open_data_action)

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

        connect_controller_action = QtGui.QAction("Connect &Controller", self)
        connect_controller_action.triggered.connect(self._on_connect_controller)
        hardware_menu.addAction(connect_controller_action)

        disconnect_controller_action = QtGui.QAction("&Disconnect Controller", self)
        disconnect_controller_action.triggered.connect(self._on_disconnect_controller)
        hardware_menu.addAction(disconnect_controller_action)

        hardware_menu.addSeparator()

        connect_knobby_action = QtGui.QAction("Connect &Knobby", self)
        connect_knobby_action.triggered.connect(self._on_connect_knobby)
        hardware_menu.addAction(connect_knobby_action)

        disconnect_knobby_action = QtGui.QAction("Disconnect &Knobby", self)
        disconnect_knobby_action.triggered.connect(self._on_disconnect_knobby)
        hardware_menu.addAction(disconnect_knobby_action)

        hardware_menu.addSeparator()

        connect_motor_action = QtGui.QAction("Connect &Motor", self)
        connect_motor_action.triggered.connect(self._on_connect_motor)
        hardware_menu.addAction(connect_motor_action)

        disconnect_motor_action = QtGui.QAction("Disconnect &Motor", self)
        disconnect_motor_action.triggered.connect(self._on_disconnect_motor)
        hardware_menu.addAction(disconnect_motor_action)

        # Calibration menu
        calibration_menu = menubar.addMenu("&Calibration")

        pockels_cal_action = QtGui.QAction("Calibrate &Pockels Cell...", self)
        pockels_cal_action.triggered.connect(self._on_calibrate_pockels)
        calibration_menu.addAction(pockels_cal_action)

        calibrate_bidir_action = QtGui.QAction("Calibrate &Bidir Scan...", self)
        calibrate_bidir_action.triggered.connect(self._on_calibrate_bidir)
        calibration_menu.addAction(calibrate_bidir_action)

        calibrate_etl_action = QtGui.QAction("Calibrate &ETL...", self)
        calibrate_etl_action.triggered.connect(self._on_calibrate_etl)
        calibration_menu.addAction(calibrate_etl_action)

        calibrate_scanner_gains_action = QtGui.QAction("Calibrate &Scanner Gains...", self)
        calibrate_scanner_gains_action.triggered.connect(self._on_calibrate_scanner_gains)
        calibration_menu.addAction(calibrate_scanner_gains_action)

        # Plugins menu
        # One checkable action per plugin configured under config['plugins'].
        # Toggling connects/disconnects the plugin hardware without restarting
        # the application.  The initial checked state comes from
        # config['plugins'][name]['enabled']; auto-connection is triggered
        # after AppController.open() in _init_app_controller().
        plugins_menu = menubar.addMenu("P&lugins")
        self._plugin_actions: dict[str, QtGui.QAction] = {}
        plugin_cfg = {}
        if self.config is not None:
            raw = (
                self.config.to_dict()
                if hasattr(self.config, 'to_dict')
                else self.config
            )
            plugin_cfg = raw.get('plugins', {})
        for pname, pcfg in plugin_cfg.items():
            label = pname.replace('_', ' ').title()
            action = QtGui.QAction(label, self)
            action.setCheckable(True)
            action.setChecked(bool(pcfg.get('enabled', False)))
            action.toggled.connect(
                lambda checked, n=pname: self._on_plugin_toggled(n, checked)
            )
            plugins_menu.addAction(action)
            self._plugin_actions[pname] = action
        if not plugin_cfg:
            placeholder = QtGui.QAction('(no plugins configured)', self)
            placeholder.setEnabled(False)
            plugins_menu.addAction(placeholder)

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

        frame_selector_action = QtGui.QAction("Show &Frame Selector", self)
        frame_selector_action.setShortcut("Ctrl+F")
        frame_selector_action.setCheckable(True)
        frame_selector_action.setChecked(False)
        frame_selector_action.triggered.connect(self._toggle_frame_selector)
        view_menu.addAction(frame_selector_action)
        self._frame_selector_action = frame_selector_action

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

    def _toggle_frame_selector(self, checked: bool) -> None:
        """Show or hide the frame selector widget.

        Args:
            checked: True to show the frame selector, False to hide it.
        """
        self._right_panel.frame_selector.setVisible(checked)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _open_data_file(self) -> None:
        """Open a file dialog to select an .sbx recording and display it.

        Loads the .sbx/.mat pair via :class:`~pyscanbox.io.sbx_reader.ScanboxOriginalReader`,
        configures the frame selector widget, shows it, and displays the
        first frame.  Any previously loaded recording is closed first.
        """
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open Data File",
            "",
            "Scanbox data (*.sbx);;All files (*)",
        )
        if not path:
            return

        # Strip the .sbx extension to get the base path expected by ScanboxOriginalReader.
        base_path = path[:-4] if path.lower().endswith('.sbx') else path

        # Close any previously loaded recording.
        if self._sbx_reader is not None:
            self._sbx_reader.close()
            self._sbx_reader = None

        try:
            reader = sbx_reader.ScanboxOriginalReader(base_path)
        except (FileNotFoundError, ValueError) as exc:
            QtWidgets.QMessageBox.critical(
                self, "Failed to open data file", str(exc)
            )
            return

        self._sbx_reader = reader
        frame_sel = self._right_panel.frame_selector
        frame_sel.set_recording(reader.num_frames)
        # Wire slider → display (disconnect previous connection first to avoid
        # duplicate connections when a new file is opened).
        try:
            frame_sel.frame_selected.disconnect(self._on_frame_selected)
        except (RuntimeError, TypeError):
            pass  # not yet connected
        frame_sel.frame_selected.connect(self._on_frame_selected)

        # Ensure the frame selector is visible and its menu action is checked.
        frame_sel.setVisible(True)
        self._frame_selector_action.setChecked(True)

        # Display the first frame immediately.
        self._on_frame_selected(0)

        self.statusBar.showMessage(
            f"Loaded: {os.path.basename(base_path)}.sbx  "
            f"({reader.num_frames} frames, "
            f"{reader.num_channels} ch, "
            f"{reader.lines_per_frame}\u00d7{reader.pixels_per_line})"
        )

    def _on_frame_selected(self, index: int) -> None:
        """Display the frame at *index* from the currently loaded recording.

        Retrieves the frame from the memory-mapped ScanboxOriginalReader and forwards it
        to the image display widget using the same array shape that live
        acquisition uses: ``(channels, lines_per_frame, pixels_per_line)``.

        Args:
            index: 0-based frame index.
        """
        if self._sbx_reader is None:
            return
        try:
            # invert=False returns wire-format (high=dark), matching the
            # live acquisition pipeline.  The display widget inverts internally.
            frame_data = self._sbx_reader.get_frame(index, invert=False)
        except IndexError:
            return
        self._right_panel.image_display.update_frame(frame_data)
        self._right_panel.histogram.force_update_frame(frame_data)

    def _on_display_gain_changed(self, slider_value: int) -> None:
        """Re-render the current loaded frame when the display gain changes.

        ``set_gain`` (wired in panels.py) runs first and updates the stored
        gain in ``ImageDisplayWidget``; this slot fires immediately after and
        re-calls ``_on_frame_selected`` so the new gain is applied right away.
        Has no effect when no recording is loaded (live acquisition naturally
        picks up the new gain on its next frame).

        Args:
            slider_value: Raw slider integer (passed through but unused here;
                gain is already updated inside ImageDisplayWidget.set_gain).
        """
        if self._sbx_reader is None:
            return
        self._on_frame_selected(
            self._right_panel.frame_selector.current_frame
        )

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
    # ------------------------------------------------------------------
    # Pockels calibration dialog
    # ------------------------------------------------------------------

    def _on_calibrate_pockels(self) -> None:
        """Open the non-modal Pockels cell calibration dialog.

        Creates the dialog on first call and re-shows it on subsequent
        calls.  Passes the current AppController so the dialog can upload
        a fitted LUT directly to hardware.
        """
        if not hasattr(self, '_pockels_cal_dialog') or self._pockels_cal_dialog is None:
            config_dict = (
                self.config.to_dict() if hasattr(self.config, 'to_dict')
                else (self.config or {})
            )
            cal_filename = config_dict.get('pockels', {}).get('calibration_file', None)
            self._pockels_cal_dialog = pockels_cal_dialog.PockelsCalibrationDialog(
                controller=self._ctrl,
                config_path=self._config_path,
                cal_filename=cal_filename,
                value_getter=lambda: round(
                    self._left_panel.laser_group.power_slider.value() * 2.55
                ),
                parent=None,  # top-level: not blocked by modal state of MainWindow
            )
            self._pockels_cal_dialog.lut_uploaded.connect(
                self._on_pockels_lut_uploaded
            )
        self._pockels_cal_dialog.show()
        self._pockels_cal_dialog.raise_()
        self._pockels_cal_dialog.activateWindow()

    def _on_pockels_lut_uploaded(self, lut: list) -> None:
        """React to a successful Pockels LUT upload from the calibration dialog.

        Args:
            lut: 256-entry LUT that was just uploaded to hardware.
        """
        self.statusBar.showMessage(
            f'Pockels LUT uploaded ({len(lut)} entries)'
        )

    # ------------------------------------------------------------------
    # ETL calibration dialog
    # ------------------------------------------------------------------

    def _on_calibrate_etl(self) -> None:
        """Open the non-modal ETL calibration dialog.

        Creates the dialog on first call and re-shows it on subsequent
        calls.
        """
        if not hasattr(self, '_etl_cal_dialog') or self._etl_cal_dialog is None:
            config_dict = (
                self.config.to_dict() if hasattr(self.config, 'to_dict')
                else (self.config or {})
            )
            cal_filename = config_dict.get('optotune', {}).get('calibration_file', None)
            self._etl_cal_dialog = etl_cal_dialog.EtlCalibrationDialog(
                config_path=self._config_path,
                cal_filename=cal_filename,
                value_getter=lambda: self._right_panel.optotune_group.etl_slider.value(),
                parent=None,
            )
            self._etl_cal_dialog.calibration_saved.connect(
                self._on_etl_calibration_saved
            )
        self._etl_cal_dialog.show()
        self._etl_cal_dialog.raise_()
        self._etl_cal_dialog.activateWindow()

    def _on_etl_calibration_saved(self, coeffs) -> None:
        """Reload ETL calibration in the controller after a save.

        Args:
            coeffs: 3-element ndarray ``[a, b, c]`` from the dialog.
        """
        if self._ctrl is not None:
            self._ctrl.reload_etl_calibration(coeffs)
        self.statusBar.showMessage('ETL calibration updated.')

    # ------------------------------------------------------------------
    # Scanner gains dialog
    # ------------------------------------------------------------------

    def _on_calibrate_scanner_gains(self) -> None:
        """Open the non-modal Scanner Gains calibration dialog.

        Creates the dialog on first call and re-shows it on subsequent
        calls.  Passes the current AppController so the dialog can upload
        gain values directly to hardware.
        """
        if not hasattr(self, '_scanner_gains_dialog') or self._scanner_gains_dialog is None:
            self._scanner_gains_dialog = scanner_gains_dialog.ScannerGainsDialog(
                controller=self._ctrl,
                parent=None,
            )
            self._scanner_gains_dialog.gains_sent.connect(
                self._on_scanner_gains_sent
            )
        else:
            # Refresh the send-button enabled state in case the connection
            # was opened or closed since the dialog was last shown.
            self._scanner_gains_dialog._update_send_button_state()
        self._scanner_gains_dialog.show()
        self._scanner_gains_dialog.raise_()
        self._scanner_gains_dialog.activateWindow()

    def _on_scanner_gains_sent(self, gains: dict) -> None:
        """Update status bar after scanner gains are uploaded from the dialog.

        Args:
            gains: Dict with keys ``gain_galvo``, ``gain_resonant``, and
                ``dv_galvo`` as emitted by :class:`ScannerGainsDialog`.
        """
        self.statusBar.showMessage(
            f"Scanner gains sent to hardware  (dv_galvo={gains['dv_galvo']})"
        )

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
            config_dict, config_path=self._config_path, parent=self
        )

        self._ctrl.plugin_status_changed.connect(self._on_plugin_status_changed)

        # Wire menu actions regardless of whether open() succeeds.
        self._connect_action.triggered.connect(self._on_connect_hardware)
        self._disconnect_action.triggered.connect(self._on_disconnect_hardware)

        # Show a startup progress sequence in the image display placeholder.
        image_display = self._right_panel.image_display
        image_display.set_startup_message('Connecting to hardware...')
        QtWidgets.QApplication.processEvents()

        _startup_lines = []

        def _on_startup_status(msg):
            if _startup_lines and _startup_lines[-1].endswith('...'):
                _startup_lines[-1] += ' ' + msg
            else:
                _startup_lines.append(msg)
            image_display.set_startup_message('\n'.join(_startup_lines))
            QtWidgets.QApplication.processEvents()

        self._ctrl.startup_status.connect(_on_startup_status)

        try:
            self._ctrl.open()
        except RuntimeError as exc:
            image_display.set_startup_message(
                '\n'.join(_startup_lines) + f'\n\nError: {exc}'
            )
            self.statusBar.showMessage(f"Hardware init failed: {exc}")
            return

        # Append the steady-state prompt after all devices are connected.
        _startup_lines.append('\nImage Display\n(Live preview will appear here)')
        image_display.set_startup_message('\n'.join(_startup_lines))

        self._connect_hardware()
        emulation = config_dict.get('emulation', {}).get('enabled', False)
        suffix = " (emulation)" if emulation else ""
        self.statusBar.showMessage(f"Hardware connected{suffix}.")

        # Auto-connect plugins that are checked (enabled: true in config).
        # This runs after open() so hardware is ready, and in a background
        # thread via enable_plugin(), so the GUI remains responsive during
        # the Arduino reset delay.
        for pname, action in self._plugin_actions.items():
            if action.isChecked():
                self._ctrl.enable_plugin(pname)

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

        # Scan mode combobox -> acquisition config
        scanner.scan_mode_combobox.currentIndexChanged.connect(
            self._on_scan_mode_changed
        )
        # Initialise enable state from current combobox selection.
        scanner.bidir_alignment_spinbox.setEnabled(
            scanner.scan_mode_combobox.currentIndex() == 1
        )

        # Bidirectional alignment spinbox -> per-magnification bishift
        scanner.bidir_alignment_spinbox.valueChanged.connect(
            self._on_bishift_changed
        )
        # Set the initial spinbox value from config for the default magnification.
        self._sync_bishift_spinbox(scanner.magnification_combobox.currentIndex())

        # Lines/frame spinbox -> acquisition config
        scanner.lines_per_frame_spinbox.valueChanged.connect(
            self._on_lines_per_frame_changed
        )
        # Initialise spinbox from config so GUI and acquisition agree at startup.
        self._sync_lines_per_frame_spinbox()

        # ETL slider -> hardware (spinbox is bidirectionally linked to slider
        # inside OptotuneGroup, so wiring the slider covers both widgets)
        optotune = self._right_panel.optotune_group
        optotune.etl_slider.valueChanged.connect(self._on_etl_current_changed)
        # Send the initial slider value so hardware matches the GUI at startup.
        self._on_etl_current_changed(optotune.etl_slider.value())

        # Focus stacking controls
        optotune.set_top_btn.clicked.connect(self._on_focus_stack_set_top)
        optotune.set_bottom_btn.clicked.connect(self._on_focus_stack_set_bottom)
        optotune.planes_spinbox.valueChanged.connect(self._update_focus_stack_info)
        optotune.frames_spinbox.valueChanged.connect(self._update_focus_stack_info)
        optotune.enable_checkbox.toggled.connect(self._on_focus_stack_enable)
        self._update_focus_stack_info()

        # Acquisition buttons -> AppController
        acq.focus_button.clicked.connect(self._on_focus_clicked)
        acq.grab_button.clicked.connect(self._on_grab_clicked)
        acq.snapshot_button.clicked.connect(self._on_snapshot_clicked)

        # Zero-angle button -> AppController
        pos_grp = self._right_panel.position_group
        pos_grp.zero_angle_button.clicked.connect(self._on_zero_angle_clicked)
        pos_grp.keep_tip_fixed_checkbox.toggled.connect(
            self._ctrl.set_keep_tip_fixed
        )

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

        # Bidirectional calibration signals.
        self._ctrl.bidir_calibration_progress.connect(
            self._on_bidir_calibration_progress
        )
        self._ctrl.bidir_calibration_done.connect(
            self._on_bidir_calibration_done
        )

    # ------------------------------------------------------------------
    # Bidirectional calibration
    # ------------------------------------------------------------------

    def _on_calibrate_bidir(self) -> None:
        """Open the non-modal bidirectional calibration dialog.

        Creates the dialog on first call and re-shows it on subsequent calls.
        The dialog guides the user through the calibration steps and displays
        live progress as frames are collected.
        """
        if not hasattr(self, '_bidir_cal_dialog') or self._bidir_cal_dialog is None:
            self._bidir_cal_dialog = bidir_cal_dialog.BidirCalibrationDialog(
                controller=self._ctrl,
                parent=None,  # top-level: not blocked by MainWindow modal state
            )
        self._bidir_cal_dialog.show()
        self._bidir_cal_dialog.raise_()
        self._bidir_cal_dialog.activateWindow()

    def _on_bidir_calibration_progress(self, done: int, needed: int) -> None:
        """Forward calibration progress to the dialog and update the status bar.

        Args:
            done: Frames collected so far.
            needed: Total frames needed before measurement.
        """
        self.statusBar.showMessage(
            f'Bidir calibration: {done}/{needed} frames…'
        )
        if hasattr(self, '_bidir_cal_dialog') and self._bidir_cal_dialog is not None:
            self._bidir_cal_dialog.update_progress(done, needed)

    def _on_bidir_calibration_done(self, mag_index: int, shift: int) -> None:
        """Forward calibration result to the dialog, update spinbox and status bar.

        Args:
            mag_index: Magnification index that was calibrated.
            shift: Measured pixel shift stored for that magnification.
        """
        self._sync_bishift_spinbox(mag_index)
        self.statusBar.showMessage(
            f'Bidir calibration complete: mag={mag_index}, bishift={shift} px'
        )
        if hasattr(self, '_bidir_cal_dialog') and self._bidir_cal_dialog is not None:
            self._bidir_cal_dialog.update_done(mag_index, shift)

    def closeEvent(self, event):
        """Stop acquisition and close hardware before the window is destroyed.

        Zeros the PMT gains and Pockels cell before shutting down hardware
        so that the laser and detectors are in a safe state.

        Args:
            event: QCloseEvent from Qt.
        """
        if hasattr(self, '_bidir_cal_dialog') and self._bidir_cal_dialog is not None:
            self._bidir_cal_dialog.close()
            self._bidir_cal_dialog = None
        if hasattr(self, '_pockels_cal_dialog') and self._pockels_cal_dialog is not None:
            self._pockels_cal_dialog.close()
            self._pockels_cal_dialog = None
        if hasattr(self, '_scanner_gains_dialog') and self._scanner_gains_dialog is not None:
            self._scanner_gains_dialog.close()
            self._scanner_gains_dialog = None
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
        if self._sbx_reader is not None:
            self._sbx_reader.close()
            self._sbx_reader = None
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Camera path / mirror
    # ------------------------------------------------------------------

    def _on_camera_path_changed(self, mode: str):
        """Toggle epi/2P mirror when the Light Path toggle changes.

        Disables Focus and Grab in Epi mode (scanning is not available on
        the epifluorescence path) and re-enables them when returning to 2p.
        The enabled state is only changed when no acquisition is currently
        running; if a scan is active the buttons are already managed by the
        acquisition start/stop logic.

        Args:
            mode: ``'epi'`` or ``'2p'`` as emitted by CameraPathGroup.
        """
        in_2p = (mode == '2p')
        acq = self._left_panel.acquisition_group
        # Only update enabled state when no scan is active (buttons unchecked).
        if not (acq.focus_button.isChecked() or acq.grab_button.isChecked()):
            acq.focus_button.setEnabled(in_2p)
            acq.grab_button.setEnabled(in_2p)
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
            # Refresh bidir alignment spinbox to show the stored shift for
            # the newly selected magnification level.
            self._sync_bishift_spinbox(index)
        except RuntimeError:
            pass  # hardware not open yet; silently ignore

    def _on_scan_mode_changed(self, index: int):
        """Handle scan mode combobox selection (Unidirectional / Bidirectional).

        Args:
            index: 0 = Unidirectional, 1 = Bidirectional.
        """
        if self._ctrl is None:
            return
        bidirectional = index == 1
        self._ctrl.set_scan_mode(bidirectional)
        # Enable the bishift spinbox only in bidirectional mode.
        scanner = self._left_panel.scanner_group
        scanner.bidir_alignment_spinbox.setEnabled(bidirectional)

    def _on_bishift_changed(self, shift: int):
        """Handle bidirectional alignment spinbox change.

        Args:
            shift: New pixel shift value for backward scan lines at the
                current magnification.
        """
        if self._ctrl is None:
            return
        self._ctrl.set_bishift(shift)

    def _on_lines_per_frame_changed(self, lines: int) -> None:
        """Handle Lines/frame spinbox change.

        Updates ``config['acquisition']['lines_per_frame']`` so the next
        Focus or Grab uses the value shown in the GUI.

        Args:
            lines: New lines-per-frame value from the spinbox.
        """
        if self._ctrl is None:
            return
        self._ctrl.set_lines_per_frame(lines)

    def _sync_lines_per_frame_spinbox(self) -> None:
        """Initialise the Lines/frame spinbox from the acquisition config.

        Reads ``config['acquisition']['lines_per_frame']`` and sets the
        spinbox value without emitting a signal (to avoid a feedback loop).
        """
        if self._ctrl is None:
            return
        lines = self._ctrl.config.get('acquisition', {}).get(
            'lines_per_frame', 512
        )
        scanner = self._left_panel.scanner_group
        scanner.lines_per_frame_spinbox.blockSignals(True)
        scanner.lines_per_frame_spinbox.setValue(lines)
        scanner.lines_per_frame_spinbox.blockSignals(False)

    def _sync_bishift_spinbox(self, mag_index: int) -> None:
        """Update the bidir alignment spinbox to show the stored bishift.

        Reads ``config['acquisition']['bishift'][mag_index]`` and
        updates the spinbox without emitting a valueChanged signal
        (to avoid a feedback loop).

        Args:
            mag_index: Current magnification index (0–12).
        """
        if self._ctrl is None:
            return
        bishift = self._ctrl.config.get('acquisition', {}).get('bishift', [0] * 13)
        shift = bishift[mag_index] if 0 <= mag_index < len(bishift) else 0
        scanner = self._left_panel.scanner_group
        scanner.bidir_alignment_spinbox.blockSignals(True)
        scanner.bidir_alignment_spinbox.setValue(shift)
        scanner.bidir_alignment_spinbox.blockSignals(False)

    def _on_etl_current_changed(self, current: int):
        """Forward ETL slider / spinbox value to hardware and update depth label.

        The depth label shows depth in µm once a calibration file is loaded
        (via AppController.open from optotune.calibration_file); it is left
        empty when no calibration is available (the raw ETL value is already
        visible in the spinbox).

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
            f'{depth} \u00b5m' if depth is not None else ''
        )
        # Forward to hardware (no-op if not yet connected).
        if self._ctrl is not None:
            try:
                self._ctrl.set_etl_current(current)
            except RuntimeError:
                pass  # hardware not open yet; silently ignore

    # ------------------------------------------------------------------
    # Focus stacking
    # ------------------------------------------------------------------

    def _on_focus_stack_set_top(self) -> None:
        """Capture the current ETL slider value as the top imaging plane."""
        optotune = self._right_panel.optotune_group
        current = optotune.etl_spinbox.value()
        depth = (
            self._ctrl.etl_to_depth(current)
            if self._ctrl is not None
            else None
        )
        label = f'{current} ({depth} \u00b5m)' if depth is not None else str(current)
        optotune.set_top(current, label)
        self._update_focus_stack_info()

    def _on_focus_stack_set_bottom(self) -> None:
        """Capture the current ETL slider value as the bottom imaging plane."""
        optotune = self._right_panel.optotune_group
        current = optotune.etl_spinbox.value()
        depth = (
            self._ctrl.etl_to_depth(current)
            if self._ctrl is not None
            else None
        )
        label = f'{current} ({depth} \u00b5m)' if depth is not None else str(current)
        optotune.set_bottom(current, label)
        self._update_focus_stack_info()

    def _update_focus_stack_info(self, _unused=None) -> None:
        """Refresh the derived step-size display in the focus stacking panel.

        Computes the depth step between planes in µm (when ETL calibration
        is available) and updates the step display label.  Also enforces the
        255-entry constraint by clamping the Planes spinbox when the product
        n_planes × frames_per_plane would exceed 255.
        """
        optotune = self._right_panel.optotune_group
        top, bottom, n_planes, fpp = optotune.get_stack_params()

        # Enforce PSoC5 table size limit: clamp Planes so total ≤ 255.
        max_planes = max(1, 255 // fpp)
        if n_planes > max_planes:
            optotune.planes_spinbox.blockSignals(True)
            optotune.planes_spinbox.setValue(max_planes)
            optotune.planes_spinbox.blockSignals(False)
            n_planes = max_planes

        # Compute per-step depth if calibration is available.
        if (
            self._ctrl is not None
            and top is not None
            and bottom is not None
            and n_planes > 1
        ):
            top_depth = self._ctrl.etl_to_depth(top)
            bot_depth = self._ctrl.etl_to_depth(bottom)
            if top_depth is not None and bot_depth is not None:
                step_um = abs(bot_depth - top_depth) / (n_planes - 1)
                optotune.update_step_display(f'\u2248 {step_um:.1f} \u00b5m')
            else:
                optotune.update_step_display('')
        else:
            optotune.update_step_display('')

    def _on_focus_stack_enable(self, checked: bool) -> None:
        """Upload and enable (or disable) the focus-stacking waveform.

        When ``checked`` is True:
        - Validates that top and bottom planes have been set and parameters
          are in range.
        - Uploads the step waveform to the PSoC5.
        - Activates autonomous ETL cycling.
        - Disables the ETL slider so it cannot interfere.

        When ``checked`` is False:
        - Deactivates waveform cycling.
        - Re-enables the ETL slider and restores its current value.

        Args:
            checked: True when the Enable checkbox is checked.
        """
        optotune = self._right_panel.optotune_group
        if self._ctrl is None:
            optotune.enable_checkbox.blockSignals(True)
            optotune.enable_checkbox.setChecked(False)
            optotune.enable_checkbox.blockSignals(False)
            return

        if checked:
            top, bottom, n_planes, fpp = optotune.get_stack_params()
            if top is None or bottom is None:
                QtWidgets.QMessageBox.warning(
                    self,
                    'Focus Stack',
                    'Please set both the Top and Bottom ETL positions before enabling.',
                )
                optotune.enable_checkbox.blockSignals(True)
                optotune.enable_checkbox.setChecked(False)
                optotune.enable_checkbox.blockSignals(False)
                return
            total = n_planes * fpp
            if total > 255:
                QtWidgets.QMessageBox.warning(
                    self,
                    'Focus Stack',
                    f'Table size {total} exceeds PSoC5 limit of 255 entries.\n'
                    'Reduce the number of planes or frames per plane.',
                )
                optotune.enable_checkbox.blockSignals(True)
                optotune.enable_checkbox.setChecked(False)
                optotune.enable_checkbox.blockSignals(False)
                return
            try:
                self._ctrl.upload_focus_stack(top, bottom, n_planes, fpp)
                self._ctrl.enable_focus_stack(True)
                optotune.set_etl_controls_enabled(False)
                optotune.set_focus_stack_controls_enabled(False)
                self.statusBar.showMessage(
                    f'Focus stack enabled: {n_planes} planes × {fpp} frames/plane.'
                )
            except (RuntimeError, ValueError) as exc:
                QtWidgets.QMessageBox.critical(
                    self, 'Focus Stack', f'Could not enable focus stack:\n{exc}'
                )
                optotune.enable_checkbox.blockSignals(True)
                optotune.enable_checkbox.setChecked(False)
                optotune.enable_checkbox.blockSignals(False)
        else:
            try:
                self._ctrl.enable_focus_stack(False)
                # Restore direct ETL control at the current slider position.
                self._ctrl.set_etl_current(optotune.etl_spinbox.value())
            except RuntimeError:
                pass
            optotune.set_etl_controls_enabled(True)
            optotune.set_focus_stack_controls_enabled(True)
            self.statusBar.showMessage('Focus stack disabled.')

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
            self._left_panel.scanner_group.scan_mode_combobox.setEnabled(False)
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
            self._left_panel.scanner_group.scan_mode_combobox.setEnabled(False)
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

    def _on_zero_angle_clicked(self):
        """Ask for confirmation, then move the angle motor to absolute zero."""
        import PyQt6.QtWidgets as _QtW
        reply = _QtW.QMessageBox.question(
            self,
            "Zero Angle Motor",
            "Move the objective angle motor to absolute step 0 (0°)?\n\n"
            "This will physically rotate the objective and may be dangerous "
            "if the sample or objective is in a position where such movement "
            "could cause damage.\n\n"
            "The Knobby display for X, Y, and Z will also be reset to 0 — "
            "those axes will NOT move.\n\nProceed?",
            _QtW.QMessageBox.StandardButton.Yes | _QtW.QMessageBox.StandardButton.No,
            _QtW.QMessageBox.StandardButton.No,
        )
        if reply == _QtW.QMessageBox.StandardButton.Yes:
            try:
                self._ctrl.zero_angle()
            except Exception as exc:
                _QtW.QMessageBox.warning(self, "Zero Angle Failed", str(exc))

    def _on_position_updated(self, pos):
        """Update the position display group from hardware position data.

        Updates the World (Knobby relative), Abs (motor hardware absolute),
        Angle, and Rotated (objective-frame) fields.

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

        # Rotated row: show coordinates in the objective-rotated frame.
        x = pos.get('X', 0.0)
        y = pos.get('Y', 0.0)
        z = pos.get('Z', 0.0)
        angle = pos.get('A', 0.0)
        x_rot, y_rot, z_rot = coordinate_transform.world_to_rotated(x, y, z, angle)
        pos_grp.rotated_x_edit.setText(f"{x_rot:.2f}")
        pos_grp.rotated_y_edit.setText(f"{y_rot:.2f}")
        pos_grp.rotated_z_edit.setText(f"{z_rot:.2f}")

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
        # Re-enable scan buttons only when in 2p mode; Epi keeps them disabled.
        in_2p = (self._left_panel.camera_group.current_path == '2p')
        acq.focus_button.setEnabled(in_2p)
        acq.grab_button.setEnabled(in_2p)
        self._left_panel.scanner_group.scan_mode_combobox.setEnabled(True)
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

    def _on_plugin_toggled(self, name: str, checked: bool) -> None:
        """Slot for a Plugins menu action being checked or unchecked.

        Delegates to AppController, which manages the background connection
        thread and the PluginManager registration.

        Args:
            name: Plugin name (key in config['plugins']).
            checked: True = enable (connect), False = disable (disconnect).
        """
        if self._ctrl is None:
            return
        if checked:
            self._ctrl.enable_plugin(name)
        else:
            self._ctrl.disable_plugin(name)

    def _on_plugin_status_changed(self, name: str, status: str) -> None:
        """Slot for AppController.plugin_status_changed signal.

        Shows a brief message in the status bar.  If the connection failed,
        the corresponding menu action is unchecked to reflect the true state
        (without re-triggering _on_plugin_toggled).

        Args:
            name: Plugin name.
            status: Status string, e.g. 'connected', 'disconnected',
                'connecting', or 'error: <message>'.
        """
        self.statusBar.showMessage(f"Plugin '{name}': {status}", 4000)
        if status.startswith('error'):
            action = self._plugin_actions.get(name)
            if action is not None:
                action.blockSignals(True)
                action.setChecked(False)
                action.blockSignals(False)

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

    def _on_connect_controller(self):
        """Open just the ScanboxController."""
        if self._ctrl is not None and not self._ctrl._hw_controller.is_open:
            try:
                self._ctrl.open_controller()
                self.statusBar.showMessage("Controller connected.")
            except RuntimeError as exc:
                self.statusBar.showMessage(f"Controller connect failed: {exc}")

    def _on_disconnect_controller(self):
        """Disconnect just the ScanboxController."""
        if self._ctrl is not None and self._ctrl._hw_controller.is_open:
            self._ctrl.close_controller()
            self.statusBar.showMessage("Controller disconnected.")

    def _on_connect_knobby(self):
        """Open just the Knobby position controller."""
        if self._ctrl is not None and not self._ctrl._knobby.is_open:
            self._ctrl.open_knobby()
            self.statusBar.showMessage("Knobby connected.")

    def _on_disconnect_knobby(self):
        """Disconnect just the Knobby position controller."""
        if self._ctrl is not None and self._ctrl._knobby.is_open:
            self._ctrl.close_knobby()
            self.statusBar.showMessage("Knobby disconnected.")

    def _on_connect_motor(self):
        """Open just the Trinamic motor controller."""
        if self._ctrl is not None and not self._ctrl._motor.is_open:
            self._ctrl.open_motor()
            self.statusBar.showMessage("Motor connected.")

    def _on_disconnect_motor(self):
        """Disconnect just the Trinamic motor controller."""
        if self._ctrl is not None and self._ctrl._motor.is_open:
            self._ctrl.close_motor()
            self.statusBar.showMessage("Motor disconnected.")
