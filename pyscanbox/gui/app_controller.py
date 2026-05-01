# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Application controller for pyscanbox GUI.

This module bridges the GUI widgets and the hardware backend modules.
It owns the hardware object lifetimes, translates GUI-level actions into
hardware calls, and emits Qt signals to update the GUI when hardware state
changes.

All hardware is opened in emulation mode when config['emulation']['enabled']
is True, so this module works fully on Linux without physical hardware.

Example:
    >>> import pyscanbox.config
    >>> import pyscanbox.gui.app_controller
    >>> cfg = pyscanbox.config.load_config('config.yaml')
    >>> ctrl = pyscanbox.gui.app_controller.AppController(cfg.to_dict())
    >>> ctrl.open()
    >>> ctrl.set_pockels(50)  # 50% laser power
    >>> ctrl.close()
"""

import datetime
import logging
from typing import Optional

import PyQt6.QtCore as QtCore

from pyscanbox.calibration import bidir as bidir_calibration
from pyscanbox.calibration import etl as etl_calibration
from pyscanbox.hardware import controller as hw_controller
from pyscanbox.hardware import knobby as hw_knobby
from pyscanbox.hardware import motor as hw_motor
from pyscanbox.acquisition import scan as acq_scan
from pyscanbox.acquisition import plugin as acq_plugin
from pyscanbox.utils import coordinate_transform


logger = logging.getLogger(__name__)

# Polling interval for Knobby position updates (milliseconds).
POSITION_POLL_INTERVAL_MS = 100

# Scale factor for mapping 0-100% GUI slider to 0-255 hardware range.
POCKELS_PERCENT_TO_HW = 255.0 / 100.0

# Scale factor for PMT gain sliders (0-100 % -> 0-255 hardware range).
PMT_PERCENT_TO_HW = 255.0 / 100.0


class PluginConnectThread(QtCore.QThread):
    """Opens a plugin's hardware connection in a background thread.

    After AppController.enable_plugin() builds a plugin instance, this
    thread calls plugin.open() so that slow hardware setup (e.g. Arduino
    reset on USB connect, ~2 s) does not block the GUI event loop.

    Signals:
        succeeded: Emitted on successful open(); carries the plugin instance.
        failed: Emitted on exception; carries a human-readable error string.
    """

    succeeded = QtCore.pyqtSignal(object)  # AcquisitionPlugin instance
    failed = QtCore.pyqtSignal(str)        # error description

    def __init__(self, plugin, parent=None):
        """Initialise the thread.

        Args:
            plugin: The plugin whose open() should be called.
            parent: Optional Qt parent.
        """
        super().__init__(parent)
        self._plugin = plugin

    def run(self) -> None:
        """Call plugin.open() in the background thread."""
        try:
            self._plugin.open()
            self.succeeded.emit(self._plugin)
        except Exception as exc:
            self.failed.emit(str(exc))


class ScannerThread(QtCore.QThread):
    """Runs Scanner in a background QThread.

    Wraps pyscanbox.acquisition.scan.Scanner so that the blocking
    acquisition loop runs off the main (GUI) thread.  Emits Qt signals
    to allow the GUI to track progress and react when acquisition ends.

    Signals:
        frame_acquired: Emitted after each frame, carrying the cumulative
            frame count (int).
        acquisition_finished: Emitted when the acquisition loop exits
            (normally, via stop request, or on error).
        acquisition_error: Emitted if an unhandled exception occurs inside
            the acquisition loop, carrying a human-readable message (str).

    Note:
        Scanner creates its own AlazarDigitizer instance.  The
        ScanboxController is shared with AppController (passed via the
        ``controller`` constructor argument) so that the same serial port is
        not opened twice on real hardware.  In emulation mode the
        ``controller`` argument may be omitted and Scanner will create its
        own mock instance (backward-compatible behaviour used in tests).
    """

    frame_acquired = QtCore.pyqtSignal(int)
    acquisition_finished = QtCore.pyqtSignal()
    acquisition_error = QtCore.pyqtSignal(str)
    frame_data_ready = QtCore.pyqtSignal(object)  # carries np.ndarray
    command_logged = QtCore.pyqtSignal(str)       # carries HTML-formatted entry

    def __init__(self, config: dict, output_path=None,
                 focus_mode: bool = False,
                 frames_override: int = None,
                 controller=None,
                 motor=None,
                 save_channels: int = 2,
                 ttl_mask: int = 0,
                 plugin_manager=None,
                 parent=None):
        """Initialize the scanner thread.

        Args:
            config: Configuration dictionary (emulation flag is read from
                config['emulation']['enabled']).
            output_path: File path prefix for .sbx/.mat output.  Passed
                directly to Scanner.  Ignored in focus mode.
            focus_mode: If True, run indefinitely without writing to disk
                (used for the Focus button / live preview).
            frames_override: If given, overrides config frames setting.
                0 means "run forever" (MATLAB convention).
            controller: Optional pre-opened ScanboxController to share with
                Scanner so that the same serial port is not opened twice on
                real hardware.  When None, Scanner creates its own instance
                (backward-compatible behaviour used in emulation and tests).
            motor: Optional pre-opened TrinamicMotor to share with Scanner
                so that the motor COM port is not opened twice on real
                hardware.  When None, Scanner creates its own instance.
            save_channels: Which PMT channels to write to disk.  Matches the
                FileStorageGroup combobox index: 0 = PMT0 only, 1 = PMT1
                only, 2 = both channels (default).
            ttl_mask: Which TTL inputs fire timestamped event records.
                Bitmask: 0=none, 1=TTL0, 2=TTL1, 3=both.  Overrides the
                config interrupt_mask value.
            parent: Optional Qt parent object.
        """
        super().__init__(parent)
        self._config = config
        self._output_path = output_path
        self._focus_mode = focus_mode
        self._frames_override = frames_override
        self._controller = controller
        self._motor = motor
        self._save_channels = save_channels
        self._ttl_mask = ttl_mask
        self._plugin_manager = plugin_manager
        self._scanner = None

    def run(self) -> None:
        """Entry point executed in the background thread by QThread.start()."""
        try:
            self._scanner = acq_scan.Scanner(
                self._config,
                output_path=self._output_path,
                focus_mode=self._focus_mode,
                frames_override=self._frames_override,
                on_frame=self.frame_acquired.emit,
                on_frame_data=self.frame_data_ready.emit,
                on_command=self._emit_command,
                hw_controller=self._controller,
                hw_motor=self._motor,
                save_channels=self._save_channels,
                ttl_mask=self._ttl_mask,
                plugin_manager=self._plugin_manager,
            )
            self._scanner.run()
        except Exception as exc:
            self.acquisition_error.emit(str(exc))
        finally:
            self.acquisition_finished.emit()

    def _emit_command(self, direction: str, func_name: str,
                      packet_str: str = '') -> None:
        """Format a hardware command as HTML and emit command_logged.

        Called from the Scanner background thread; PyQt6 signal emission
        is thread-safe so no explicit locking is needed.

        Args:
            direction: Short label, e.g. ``'PC \u2192 Controller (COM3)'``.
            func_name: Name of the function/operation called.
            packet_str: Optional packet or parameter description.
        """
        ts = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
        detail = f'{func_name} : {packet_str}' if packet_str else func_name
        html = (
            f'<span style="color:#888">[{ts}]</span>&nbsp;'
            f'<b><span style="color:#fa8">{direction}</span></b>&nbsp;'
            f'<span style="color:#fd8;font-family:monospace">{detail}</span>'
        )
        self.command_logged.emit(html)

    def request_stop(self) -> None:
        """Thread-safe stop request; safe to call from the main thread.

        Sets the Scanner's stop flag.  The acquisition loop exits after
        the current buffer completes, then cleanup() runs and
        acquisition_finished is emitted.
        """
        if self._scanner is not None:
            self._scanner.stop()


class AppController(QtCore.QObject):
    """Bridge between the pyscanbox GUI and hardware backend modules.

    Owns the lifetimes of ScanboxController and Knobby instances.
    Translates GUI actions (slider changes, button clicks) into hardware
    calls and emits Qt signals to propagate hardware state back to the GUI.

    Signals:
        position_updated: Emitted when any motor position changes.
            Carries a dict mapping axis name (str) to position in μm or
            degrees (float). Example: {'X': 10.5, 'Y': -3.2, 'Z': 0.0, 'A': 0.0}.
        hardware_error: Emitted when a hardware call raises an exception.
            Carries a human-readable error message (str).
        frame_acquired: Emitted after each frame during acquisition.
            Carries the cumulative frame count (int).
        acquisition_finished: Emitted when the acquisition loop exits
            (normally, via stop request, or on error).

    Attributes:
        config: Configuration dictionary passed at construction.
        is_open: True after open() succeeds and before close().
    """

    position_updated = QtCore.pyqtSignal(dict)
    hardware_error = QtCore.pyqtSignal(str)
    frame_acquired = QtCore.pyqtSignal(int)
    acquisition_finished = QtCore.pyqtSignal()
    frame_data_ready = QtCore.pyqtSignal(object)  # carries np.ndarray
    command_logged = QtCore.pyqtSignal(str)  # carries HTML-formatted log entry
    #: Emitted each frame during calibration: (frames_done, frames_needed).
    bidir_calibration_progress = QtCore.pyqtSignal(int, int)
    #: Emitted when calibration completes: (mag_index, measured_shift).
    bidir_calibration_done = QtCore.pyqtSignal(int, int)
    #: Emitted during open() before and after each device connection.
    #: Carries a single human-readable status line (str).
    startup_status = QtCore.pyqtSignal(str)
    #: Emitted when a plugin's connection status changes.
    #: Carries (plugin_name, status) where status is one of:
    #:   'connecting'  — background thread started
    #:   'connected'   — open() succeeded; plugin is active
    #:   'disconnected'— plugin disabled and close() called
    #:   'error: ...'  — open() raised an exception
    plugin_status_changed = QtCore.pyqtSignal(str, str)

    def __init__(self, config: dict, config_path: str | None = None, parent=None):
        """Initialize the application controller.

        Hardware objects are created here but not yet connected.
        Call open() before issuing any hardware commands.

        Args:
            config: Configuration dictionary (e.g. from AppConfig.to_dict()).
            config_path: Path to the active YAML config file.  When provided,
                bidirectional calibration is loaded from ``bidir_cal.json`` in
                the same directory and saved there after each calibration run.
                If ``None``, calibration results are held in memory only.
            parent: Optional Qt parent object.
        """
        super().__init__(parent)
        self.config = config
        self.is_open = False
        self._config_path: str | None = config_path

        # Hardware objects (not yet connected).
        self._hw_controller = hw_controller.ScanboxController(
            config, on_command=self._on_controller_cmd
        )
        self._knobby = hw_knobby.Knobby(config, on_command=self._on_knobby_cmd)
        self._motor = hw_motor.TrinamicMotor(config, on_command=self._on_motor_cmd)

        # Knobby relative positions (dpos): motor_id → position in physical
        # units.  Matches what the Knobby screen displays.  Updated whenever
        # a 5-byte position packet arrives from the Knobby.
        self._positions = {i: 0.0 for i in range(4)}

        # Last Knobby dpos in raw steps, used to compute per-packet deltas.
        self._knobby_dpos_steps = {i: 0 for i in range(4)}

        # PC-side desired absolute motor position in hardware steps.
        # Accumulated from Knobby deltas; used to drive move_absolute() so
        # that a correctly-targeted command is always sent to the motor even
        # when knobs are turned faster than the motor can settle.
        # Seeded from actual motor positions in open().
        self._desired_steps = {i: 0 for i in range(4)}

        # Absolute motor positions: motor_id → position in physical units,
        # polled from the Trinamic board every timer tick.
        self._abs_positions = {i: 0.0 for i in range(4)}

        # Absolute motor positions in raw steps at the time open() was called.
        # Stored as the hardware origin reference (for display / debugging).
        self._motor_origin_steps = {i: 0 for i in range(4)}

        # Scanner thread (created by start_focus() / start_grab()).
        self._scanner_thread = None

        # Plugin management.  The PluginManager is long-lived (owned here
        # for the session) and passed to each ScannerThread so the Scanner
        # can call lifecycle hooks.  _active_plugins maps plugin name to the
        # live instance; _plugin_connect_threads tracks in-progress open()
        # background threads to prevent duplicate connects.
        self._plugin_manager: acq_plugin.PluginManager = acq_plugin.PluginManager()
        self._active_plugins: dict[str, acq_plugin.AcquisitionPlugin] = {}
        self._plugin_connect_threads: dict[str, PluginConnectThread] = {}

        # Most-recently sent hardware values for Pockels and PMT gains.
        # Used in emulation mode to scale mock signal brightness in real time.
        self._pockels_hw: int = 0
        self._pmt_hw: list = [0, 0]

        # ETL calibration: 3-element numpy array of polynomial coefficients
        # [a, b, c] loaded from etl_cal.json on open(), or None if absent.
        self._etl_calibration = None

        # Bidirectional scan calibration object.  Created in open() when
        # config_path is known; None otherwise.
        self._bidir_cal: bidir_calibration.BidirCalibration | None = None
        # True while a calibration run is in progress.
        self._bidir_cal_active: bool = False

        # Timer for periodic Knobby position polling.
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(POSITION_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_positions)

        # Tip-fixed rotation mode: when enabled, turning the angle knob also
        # moves X and Z to keep the objective tip at the same absolute position.
        self._keep_tip_fixed = False
        obj_config = config.get('objective', {})
        self._objective_length_um = float(obj_config.get('length', 0.0))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open all hardware connections and start background polling.

        In emulation mode (config['emulation']['enabled'] = True) this
        connects to the mock serial interfaces instead of real hardware.

        After a successful open(), the position-poll timer is started so
        that position_updated signals will begin arriving immediately.

        Raises:
            RuntimeError: If the ScanboxController connection cannot be opened.
                Knobby failures are non-fatal — position display will be
                unavailable but the rest of the GUI continues to work.
        """
        self.startup_status.emit(
            f'Connecting to Scanbox controller ({self._hw_controller.com_port})...'
        )
        print(f'Connecting to Scanbox controller ({self._hw_controller.com_port})... ', end='', flush=True)
        try:
            self._hw_controller.open()
            version = self._hw_controller.get_version()
            msg = f'Controller connected ({self._hw_controller.com_port}) - Firmware {version}'
            self._log_event(msg)
            self.startup_status.emit(f'Connected! (v{version})')
            print(f'Connected! (v{version})')
            
            # Check if configured version matches hardware version
            configured_version = self.config.get('controller', {}).get('version')
            emulation_enabled = self.config.get('emulation', {}).get('enabled', False)
            
            # Skip version mismatch warning if in emulation mode (emulator sends 99.99)
            if emulation_enabled:
                info_msg = f'Running in emulation mode (v{version})'
                logger.info(info_msg)
                self._log_event(info_msg)
            elif configured_version and version != str(configured_version):
                warn_msg = (
                    f'⚠️  Controller firmware version mismatch: '
                    f'config expects v{configured_version}, but hardware is v{version}. '
                    f'Some features may not work as expected.'
                )
                logger.warning(warn_msg)
                self._log_event(warn_msg)
        except Exception as exc:
            msg = f"Could not open ScanboxController: {exc}"
            print('Failed!')
            logger.error(msg)
            self.hardware_error.emit(msg)
            raise RuntimeError(msg) from exc

        self.startup_status.emit(
            f'Connecting to Knobby ({self._knobby.com_port})...'
        )
        print(f'Connecting to Knobby ({self._knobby.com_port})... ', end='', flush=True)
        try:
            self._knobby.open()
            self._log_event(
                f'Knobby connected ({self._knobby.com_port})'
            )
            self.startup_status.emit('Connected!')
            print('Connected!')
        except Exception as exc:
            # Non-fatal: GUI can run without Knobby position display.
            msg = f"Could not open Knobby (position display unavailable): {exc}"
            logger.warning(msg)
            self.hardware_error.emit(msg)
            self.startup_status.emit('Not available.')
            print('Not available.')

        self.startup_status.emit(
            f'Connecting to motors ({self._motor.com_port})...'
        )
        print(f'Connecting to motors ({self._motor.com_port})... ', end='', flush=True)
        try:
            self._motor.open()
            self._log_event(
                f'Motor connected ({self._motor.com_port})'
            )
            self.startup_status.emit('Connected!')
            print('Connected!')
            # Apply per-motor freewheeling from config (TMCL SAP 204).
            motor_cfg = self.config.get('motor', {})
            freewheel = [
                motor_cfg.get('freewheel_z', False),
                motor_cfg.get('freewheel_y', False),
                motor_cfg.get('freewheel_x', False),
                motor_cfg.get('freewheel_a', False),
            ]
            for motor_id, enabled in enumerate(freewheel):
                self._motor.set_freewheel(motor_id, bool(enabled))
            # Seed desired_steps and origin reference from actual hardware
            # positions so the first move_absolute() targets a sensible value.
            for motor_id in range(4):
                pos = self._motor.get_position(motor_id)
                steps = pos if pos is not None else 0
                self._motor_origin_steps[motor_id] = steps
                self._desired_steps[motor_id] = steps
        except Exception as exc:
            # Non-fatal: GUI can run without motor control.
            msg = f"Could not open motor controller (motor control unavailable): {exc}"
            logger.warning(msg)
            self.hardware_error.emit(msg)
            self.startup_status.emit('Not available.')
            print('Not available.')

        # Load ETL calibration coefficients from JSON file if available.
        # Resolve the filename relative to the config directory so that
        # moving the config folder keeps everything together.
        cal_filename = self.config.get('optotune', {}).get('calibration_file', None)
        if self._config_path is not None:
            cal_path = etl_calibration.calibration_path(self._config_path, cal_filename)
        else:
            cal_path = cal_filename or etl_calibration.DEFAULT_CALIBRATION_FILE
        self._etl_calibration = etl_calibration.load_calibration(cal_path)
        if self._etl_calibration is not None:
            logger.info("ETL calibration loaded from %s", cal_path)
            self._log_event(f'ETL calibration loaded ({cal_path})')
        else:
            logger.info(
                "No ETL calibration at %s; depth label shows raw current",
                cal_path,
            )

        # Load bidirectional calibration and populate config['acquisition']['bishift']
        # so the running Scanner picks up the stored values immediately.
        if self._config_path is not None:
            bidir_filename = self.config.get('acquisition', {}).get(
                'bidir_calibration_file', None
            )
            self._bidir_cal = bidir_calibration.BidirCalibration(
                self._config_path, filename=bidir_filename
            )
            acq = self.config.setdefault('acquisition', {})
            acq.setdefault('bishift', [0] * bidir_calibration.NUM_MAGNIFICATIONS)
            stored = self._bidir_cal.shifts
            for i, shift in enumerate(stored):
                acq['bishift'][i] = shift
            logger.info(
                'Bidir calibration loaded from %s', self._bidir_cal.calib_path
            )
            self._log_event(
                f'Bidir calibration loaded ({self._bidir_cal.calib_path})'
            )
            # Warn if hsync_sign differs from what was used at calibration time.
            current_hsync = self.config.get('scanner', {}).get('hsync_sign', None)
            if current_hsync is not None:
                self._bidir_cal.check_hsync_sign(current_hsync)

        self.is_open = True
        self._poll_timer.start()
        logger.info("AppController: hardware open, position polling started.")

        # Disable continuous resonant mode at startup (mirrors MATLAB
        # scanbox.m line 300: sb_continuous_resonant(0)).  This ensures a
        # known state even if the hardware was left in continuous resonant
        # mode from a previous session.
        try:
            self._hw_controller.set_continuous_resonant(False)
        except Exception as exc:
            msg = f"Could not reset continuous resonant mode: {exc}"
            logger.error(msg)
            self.hardware_error.emit(msg)

        # Initialize PSoC5 to the configured scan mode (mirrors the MATLAB
        # startup sequence in scanbox.m that calls sb_unidirectional /
        # sb_bidirectional based on sbconfig.unidirectional).
        unidirectional = self.config.get('acquisition', {}).get('unidirectional', True)
        try:
            self._hw_controller.set_scan_mode(bidirectional=not unidirectional)
        except Exception as exc:
            msg = f"Could not set initial scan mode: {exc}"
            logger.error(msg)
            self.hardware_error.emit(msg)

        deadband = self.config.get('scanner', {}).get('deadband', None)
        if deadband is not None:
            try:
                self._hw_controller.set_pockels_deadband(int(deadband[0]), int(deadband[1]))
            except Exception as exc:
                msg = f"Could not set Pockels deadband: {exc}"
                logger.error(msg)
                self.hardware_error.emit(msg)

        # Upload per-zoom-level scanner gain tables when gain_override is true.
        # Mirrors the gain_override block in core/scanbox.m (lines 253–262).
        scanner_cfg = self.config.get('scanner', {})
        if scanner_cfg.get('gain_override', False):
            try:
                self.update_scanner_gains(
                    gain_galvo=scanner_cfg.get(
                        'gain_galvo',
                        list(hw_controller.ScanboxController.GAIN_GALVO_DEFAULT),
                    ),
                    gain_resonant_mult=scanner_cfg.get(
                        'gain_resonant_mult',
                        hw_controller.ScanboxController.GAIN_RESONANT_MULT_DEFAULT,
                    ),
                    dv_galvo=int(scanner_cfg.get(
                        'dv_galvo',
                        hw_controller.ScanboxController.DV_GALVO_MAX,
                    )),
                )
            except Exception as exc:
                msg = f"Could not upload scanner gain tables: {exc}"
                logger.error(msg)
                self.hardware_error.emit(msg)

        emulation = self.config.get('emulation', {}).get('enabled', False)
        suffix = ' (emulation)' if emulation else ''
        self._log_event(f'All hardware ready{suffix}')

    def close(self) -> None:
        """Stop polling, stop any running acquisition, and close all hardware.

        Before closing, zeros both PMT gains and the Pockels cell so that
        the laser and detectors are in a safe state even when the shutdown
        is triggered by a crash handler rather than a clean UI close.
        """
        self._poll_timer.stop()

        # Stop any running acquisition and wait for the thread to finish
        # before closing the hardware it depends on.
        if self._scanner_thread is not None and self._scanner_thread.isRunning():
            self._scanner_thread.request_stop()
            self._scanner_thread.wait(5000)  # Up to 5 s for clean shutdown.
        self._scanner_thread = None

        if self._hw_controller.is_open:
            # Zero PMT gains and Pockels before disconnecting.
            try:
                self._hw_controller.set_pmt_gain(0, 0)
                self._hw_controller.set_pmt_gain(1, 0)
                self._hw_controller.set_pockels(base=0, active=0)
            except Exception:
                pass  # best-effort; do not block the rest of shutdown
            self._hw_controller.close()

        if self._knobby.is_open:
            self._knobby.close()

        if self._motor.is_open:
            self._motor.close()

        # Close all active plugins and rebuild a fresh empty PluginManager.
        for plugin in list(self._active_plugins.values()):
            try:
                plugin.close()
            except Exception:
                pass  # best-effort; do not block shutdown
        self._active_plugins.clear()
        self._plugin_manager = acq_plugin.PluginManager()

        self.is_open = False
        logger.info("AppController: hardware closed.")
        self._log_event('Hardware disconnected')

    # ------------------------------------------------------------------
    # Per-device connect / disconnect
    # ------------------------------------------------------------------

    def open_controller(self) -> None:
        """Open only the ScanboxController and run the PSoC5 init sequence.

        Starts the position-poll timer and sets ``is_open = True`` so that
        all hardware commands become available.  Call this to reconnect the
        controller without disturbing the Knobby or motor connection.

        Raises:
            RuntimeError: If the ScanboxController connection fails.
        """
        try:
            self._hw_controller.open()
            self._log_event(
                f'Controller connected ({self._hw_controller.com_port})'
            )
        except Exception as exc:
            msg = f"Could not open ScanboxController: {exc}"
            logger.error(msg)
            self.hardware_error.emit(msg)
            raise RuntimeError(msg) from exc

        self.is_open = True
        if not self._poll_timer.isActive():
            self._poll_timer.start()

        unidirectional = self.config.get('acquisition', {}).get('unidirectional', True)
        try:
            self._hw_controller.set_scan_mode(bidirectional=not unidirectional)
        except Exception as exc:
            msg = f"Could not set initial scan mode: {exc}"
            logger.error(msg)
            self.hardware_error.emit(msg)

        deadband = self.config.get('scanner', {}).get('deadband', None)
        if deadband is not None:
            try:
                self._hw_controller.set_pockels_deadband(int(deadband[0]), int(deadband[1]))
            except Exception as exc:
                msg = f"Could not set Pockels deadband: {exc}"
                logger.error(msg)
                self.hardware_error.emit(msg)

        logger.info("AppController: controller connected.")

    def close_controller(self) -> None:
        """Zero laser/PMT outputs, then disconnect the ScanboxController.

        Sets ``is_open = False`` and stops the position-poll timer.  Knobby
        and motor connections are left unchanged.
        """
        if not self._hw_controller.is_open:
            return

        self._poll_timer.stop()
        try:
            self._hw_controller.set_pmt_gain(0, 0)
            self._hw_controller.set_pmt_gain(1, 0)
            self._hw_controller.set_pockels(base=0, active=0)
        except Exception:
            pass  # best-effort; do not block disconnect
        self._hw_controller.close()
        self.is_open = False
        logger.info("AppController: controller disconnected.")
        self._log_event('Controller disconnected')

    def open_knobby(self) -> None:
        """Open only the Knobby position controller.

        Non-fatal: failures emit ``hardware_error`` but do not raise.
        """
        try:
            self._knobby.open()
            self._log_event(
                f'Knobby connected ({self._knobby.com_port})'
            )
            logger.info("AppController: Knobby connected.")
        except Exception as exc:
            msg = f"Could not open Knobby: {exc}"
            logger.warning(msg)
            self.hardware_error.emit(msg)

    def close_knobby(self) -> None:
        """Disconnect the Knobby position controller."""
        if not self._knobby.is_open:
            return
        self._knobby.close()
        logger.info("AppController: Knobby disconnected.")
        self._log_event('Knobby disconnected')

    def open_motor(self) -> None:
        """Open only the Trinamic motor controller.

        Applies the per-motor freewheeling configuration from ``config`` and
        seeds the desired-steps tracker from current hardware positions.
        Non-fatal: failures emit ``hardware_error`` but do not raise.
        """
        try:
            self._motor.open()
            self._log_event(
                f'Motor connected ({self._motor.com_port})'
            )
            motor_cfg = self.config.get('motor', {})
            freewheel = [
                motor_cfg.get('freewheel_z', False),
                motor_cfg.get('freewheel_y', False),
                motor_cfg.get('freewheel_x', False),
                motor_cfg.get('freewheel_a', False),
            ]
            for motor_id, enabled in enumerate(freewheel):
                self._motor.set_freewheel(motor_id, bool(enabled))
            for motor_id in range(4):
                pos = self._motor.get_position(motor_id)
                steps = pos if pos is not None else 0
                self._motor_origin_steps[motor_id] = steps
                self._desired_steps[motor_id] = steps
            logger.info("AppController: motor connected.")
        except Exception as exc:
            msg = f"Could not open motor controller: {exc}"
            logger.warning(msg)
            self.hardware_error.emit(msg)

    def close_motor(self) -> None:
        """Disconnect the Trinamic motor controller."""
        if not self._motor.is_open:
            return
        self._motor.close()
        logger.info("AppController: motor disconnected.")
        self._log_event('Motor disconnected')

    # ------------------------------------------------------------------
    # Plugin management
    # ------------------------------------------------------------------

    def enable_plugin(self, name: str) -> None:
        """Connect a plugin's hardware and register it with the PluginManager.

        Starts a background thread that calls plugin.open() so that slow
        hardware setup (e.g. Arduino USB reset) does not block the GUI.
        plugin_status_changed is emitted with 'connecting', then either
        'connected' or 'error: <message>' when the thread finishes.

        Calling enable_plugin() for an already-active plugin is a no-op.

        Args:
            name: Plugin name matching a key under config['plugins'].
        """
        if name in self._active_plugins or name in self._plugin_connect_threads:
            return
        plugin = self._build_plugin(name)
        if plugin is None:
            msg = f"Plugin '{name}' is not configured or not supported."
            logger.warning(msg)
            self.hardware_error.emit(msg)
            return
        self.plugin_status_changed.emit(name, 'connecting')
        thread = PluginConnectThread(plugin, parent=self)
        thread.succeeded.connect(
            lambda p, n=name: self._on_plugin_connected(n, p)
        )
        thread.failed.connect(
            lambda msg, n=name: self._on_plugin_connect_failed(n, msg)
        )
        # Remove thread reference after it finishes (success or failure).
        thread.finished.connect(
            lambda n=name: self._plugin_connect_threads.pop(n, None)
        )
        self._plugin_connect_threads[name] = thread
        thread.start()
        logger.info("AppController: starting connection for plugin '%s'.", name)

    def disable_plugin(self, name: str) -> None:
        """Close a plugin's hardware connection and remove it from the manager.

        Calling disable_plugin() for a plugin that is not active is a no-op.

        Args:
            name: Plugin name to disable.
        """
        plugin = self._active_plugins.pop(name, None)
        if plugin is None:
            return
        try:
            plugin.close()
        except Exception as exc:
            logger.warning("Plugin '%s': close() raised: %s", name, exc)
        self._plugin_manager.unregister(name)
        self.plugin_status_changed.emit(name, 'disconnected')
        logger.info("AppController: plugin '%s' disabled.", name)
        self._log_event(f"Plugin '{name}' disconnected")

    def _build_plugin(
        self, name: str
    ) -> 'acq_plugin.AcquisitionPlugin | None':
        """Instantiate a plugin from config without opening hardware.

        Args:
            name: Plugin name matching a key under config['plugins'].

        Returns:
            A new plugin instance, or None if the plugin is not supported.
        """
        plugin_cfg = dict(self.config.get('plugins', {}).get(name, {}))
        # Inherit the global emulation flag unless the plugin overrides it.
        if 'emulation' not in plugin_cfg:
            plugin_cfg['emulation'] = (
                self.config.get('emulation', {}).get('enabled', False)
            )
        module_name = plugin_cfg.get('module')
        class_name = plugin_cfg.get('class')

        if not module_name or not class_name:
            logger.warning(
                "AppController: plugin '%s' is missing 'module' or 'class' in config.", name
            )
            return None

        import importlib
        try:
            module = importlib.import_module(module_name)
            plugin_class = getattr(module, class_name)
            
            # Special case for quadrature since it requires a QuadratureEncoder object
            if name == 'quadrature':
                encoder = module.QuadratureEncoder(plugin_cfg)
                return plugin_class(encoder)
            else:
                return plugin_class(plugin_cfg)
                
        except Exception as e:
            logger.error("AppController: failed to load plugin '%s': %s", name, e)
            return None

    def _on_plugin_connected(
        self, name: str, plugin: 'acq_plugin.AcquisitionPlugin'
    ) -> None:
        """Slot called when PluginConnectThread.succeeded fires."""
        self._active_plugins[name] = plugin
        self._plugin_manager.register(plugin)
        self.plugin_status_changed.emit(name, 'connected')
        logger.info("AppController: plugin '%s' connected.", name)
        self._log_event(f"Plugin '{name}' connected")

    def _on_plugin_connect_failed(self, name: str, msg: str) -> None:
        """Slot called when PluginConnectThread.failed fires."""
        error_msg = f"Plugin '{name}': connection failed: {msg}"
        self.hardware_error.emit(error_msg)
        self.plugin_status_changed.emit(name, f'error: {msg}')
        logger.error("AppController: %s", error_msg)



    def set_pockels(self, percent: int) -> None:
        """Set laser power via the Pockels cell.

        Translates the GUI slider value (0–100 %) to the hardware's 0–255
        range and sends the Pockels command.  The base power (applied
        during scanner flyback) is always kept at 0.

        Args:
            percent: Laser power as a percentage (0–100).

        Raises:
            RuntimeError: If hardware is not open.
            ValueError: If percent is outside 0–100.
        """
        if not self.is_open:
            raise RuntimeError("AppController is not open. Call open() first.")

        if not (0 <= percent <= 100):
            raise ValueError(f"Pockels percent must be 0-100, got {percent}")

        hw_value = round(percent * POCKELS_PERCENT_TO_HW)

        # Cache in config so the Scanner can restore the value after its
        # own initialize_pockels() zeros the cell at acquisition start.
        self.config.setdefault('laser', {})['pockels_active'] = hw_value

        try:
            self._hw_controller.set_pockels(base=0, active=hw_value)
            logger.debug("Pockels set to %d%% (hw=%d)", percent, hw_value)
        except Exception as exc:
            msg = f"set_pockels failed: {exc}"
            logger.error(msg)
            self.hardware_error.emit(msg)

        self._pockels_hw = hw_value
        self._update_mock_signal_scale()

    # ------------------------------------------------------------------
    # Mirror control
    # ------------------------------------------------------------------

    def set_mirror(self, mode: str) -> None:
        """Set the epi/2P mirror position.

        Args:
            mode: ``'epi'`` to enable epifluorescence path,
                ``'2p'`` for two-photon path.

        Raises:
            RuntimeError: If hardware is not open.
            ValueError: If mode is not ``'epi'`` or ``'2p'``.
        """
        if not self.is_open:
            raise RuntimeError("AppController is not open. Call open() first.")

        try:
            self._hw_controller.set_mirror(mode)
            logger.debug("Mirror set to '%s'", mode)
        except Exception as exc:
            msg = f"set_mirror failed: {exc}"
            logger.error(msg)
            self.hardware_error.emit(msg)

    # ------------------------------------------------------------------
    # PMT gain
    # ------------------------------------------------------------------

    def set_pmt_gain(self, pmt_id: int, percent: int) -> None:
        """Set the gain for a PMT channel.

        Translates the GUI slider value (0–100 %) to the hardware's 0–255
        range and sends the gain command for the specified channel.

        Args:
            pmt_id: PMT channel index (0 or 1).
            percent: Gain as a percentage (0–100).

        Raises:
            RuntimeError: If hardware is not open.
            ValueError: If pmt_id or percent are out of range.
        """
        if not self.is_open:
            raise RuntimeError("AppController is not open. Call open() first.")

        if pmt_id not in (0, 1):
            raise ValueError(f"pmt_id must be 0 or 1, got {pmt_id}")
        if not (0 <= percent <= 100):
            raise ValueError(f"PMT gain percent must be 0-100, got {percent}")

        hw_value = round(percent * PMT_PERCENT_TO_HW)

        try:
            self._hw_controller.set_pmt_gain(pmt_id, hw_value)
            logger.debug("PMT%d gain set to %d%% (hw=%d)", pmt_id, percent, hw_value)
        except Exception as exc:
            msg = f"set_pmt_gain(pmt_id={pmt_id}) failed: {exc}"
            logger.error(msg)
            self.hardware_error.emit(msg)

        self._pmt_hw[pmt_id] = hw_value
        self._update_mock_signal_scale()

    def _update_mock_signal_scale(self) -> None:
        """Propagate current Pockels/PMT values to the mock Alazar board.

        Only meaningful in emulation mode while a scanner thread is active.
        Walks the thread → scanner → alazar chain and calls
        ``set_signal_scale()`` so the live-preview image responds
        immediately to Pockels and PMT gain slider movements.
        """
        if self._scanner_thread is None or not self._scanner_thread.isRunning():
            return
        scanner = self._scanner_thread._scanner
        if scanner is None:
            return
        scanner.alazar.set_signal_scale(
            self._pockels_hw, self._pmt_hw[0], self._pmt_hw[1]
        )

    def set_magnification(self, index: int) -> None:
        """Set the zoom level from the magnification combobox selection.

        Sends the 0-based combobox index directly to the controller
        (valid range 0-12, matching MATLAB's ``popup.Value - 1``).
        Also updates ``config['acquisition']['magnification']`` so the
        Scanner picks up the current value when a new scan starts.

        Args:
            index: Combobox currentIndex() value (0 = largest FOV,
                12 = smallest FOV / highest zoom).

        Raises:
            RuntimeError: If hardware is not open.
        """
        if not self.is_open:
            raise RuntimeError("AppController is not open. Call open() first.")

        try:
            self._hw_controller.set_magnification(index)
            self.config['acquisition']['magnification'] = index
            logger.debug("Magnification set to index %d", index)
        except Exception as exc:
            msg = f"set_magnification failed: {exc}"
            logger.error(msg)
            self.hardware_error.emit(msg)

    def set_scan_mode(self, bidirectional: bool) -> None:
        """Set scan mode to unidirectional or bidirectional.

        Sends CMD_UNIDIRECTIONAL [33, 0, 0] or CMD_BIDIRECTIONAL [34, 0, 0]
        to the PSoC5 controller so it triggers the Alazar on the correct
        sweep(s), then updates ``config['acquisition']['unidirectional']``
        so the Scanner reshape path is also switched.

        Calling this while an acquisition is running is safe — the PSoC5
        applies the new mode from the next line trigger onward, and the
        Scanner reads the config flag each frame.

        Args:
            bidirectional: True for bidirectional mode, False for
                unidirectional.
        """
        self.config.setdefault('acquisition', {})['unidirectional'] = not bidirectional
        mode_str = 'bidirectional' if bidirectional else 'unidirectional'
        logger.debug("Scan mode set to %s", mode_str)
        if self.is_open:
            try:
                self._hw_controller.set_scan_mode(bidirectional)
            except Exception as exc:
                msg = f"set_scan_mode failed: {exc}"
                logger.error(msg)
                self.hardware_error.emit(msg)

    def set_continuous_resonant(self, enabled: bool) -> None:
        """Enable or disable continuous resonant mode.

        Toggles whether the PSoC5 keeps the resonant scanner oscillating even
        when the acquisition system is not actively running. Helps maintain
        thermal stability for consistent bidirectional alignment.

        Args:
            enabled: True to enable continuous resonant mode, False for
                standard bidirectional scan mode.
        """
        self.config.setdefault('acquisition', {})['continuous_resonant'] = enabled
        if self.is_open:
            try:
                self._hw_controller.set_continuous_resonant(enabled)
            except Exception as exc:
                msg = f"set_continuous_resonant failed: {exc}"
                logger.error(msg)
                self.hardware_error.emit(msg)

    def set_lines_per_frame(self, lines: int) -> None:
        """Set the number of scan lines per frame in the acquisition config.

        Updates ``config['acquisition']['lines_per_frame']`` so the next
        scan started via :meth:`start_focus` or :meth:`start_grab` uses
        the new value.  Does not affect an already-running acquisition.

        Args:
            lines: Lines per frame (must be a positive even integer, e.g.
                16–2048 in steps of 16).
        """
        self.config.setdefault('acquisition', {})['lines_per_frame'] = lines
        logger.debug("Lines per frame set to %d", lines)

    def set_bishift(self, shift: int) -> None:
        """Set the bidirectional pixel shift for the current magnification.

        Stores ``shift`` in ``config['acquisition']['bishift'][mag_index]``.
        Because the running scanner holds a reference to the same list
        object, the correction takes effect on the very next frame without
        restarting the acquisition.

        Args:
            shift: Pixel shift for backward scan lines at the current
                magnification.  Positive = shift right, negative = shift
                left.  Corresponds to ``sbconfig.bishift[mag]`` in MATLAB.
        """
        acq = self.config.setdefault('acquisition', {})
        acq.setdefault('bishift', [0] * 13)
        bishift = acq['bishift']
        mag_index = acq.get('magnification', 0)
        if 0 <= mag_index < len(bishift):
            bishift[mag_index] = shift
        logger.debug("Bishift[%d] set to %d", mag_index, shift)

    def set_deadband(self, left: int, right: int) -> None:
        """Set the Pockels cell deadband for left and right margins.

        Updates ``config['scanner']['deadband']`` and sends the new values
        to hardware via ``set_pockels_deadband``.

        Args:
            left: Left deadband width (0–255).
            right: Right deadband width (0–255).
        """
        scanner = self.config.setdefault('scanner', {})
        scanner['deadband'] = [left, right]
        if self._hw_controller is None:
            return
        try:
            self._hw_controller.set_pockels_deadband(left, right)
        except Exception as exc:
            msg = f"Could not set Pockels deadband: {exc}"
            logger.error(msg)
            self.hardware_error.emit(msg)

    def update_scanner_gains(
        self,
        gain_galvo: list,
        gain_resonant_mult: float,
        dv_galvo: int = 64,
    ) -> None:
        """Upload the per-zoom-level scanner gain tables to the PSoC5.

        Computes ``gain_resonant = gain_resonant_mult × gain_galvo`` and then
        calls :meth:`~pyscanbox.hardware.controller.ScanboxController.update_scanner_gains`.
        The call is a no-op if the hardware is not yet open, allowing this
        method to be invoked safely by the scanner gains dialog at any time.

        Args:
            gain_galvo: 13-element list of Y-axis galvo gain values
                (one per zoom level, logspaced 1.0–8.0 by default).
            gain_resonant_mult: Resonant/galvo aspect-ratio multiplier
                (default 1.42).
            dv_galvo: Galvo voltage step per line (default 64, hardware max).

        Raises:
            RuntimeError: If hardware is not open.
        """
        if not self.is_open:
            raise RuntimeError('AppController is not open. Call open() first.')
        gain_resonant = [gain_resonant_mult * g for g in gain_galvo]
        try:
            self._hw_controller.update_scanner_gains(
                gain_galvo=gain_galvo,
                gain_resonant=gain_resonant,
                dv_galvo=dv_galvo,
            )
            logger.debug(
                'Scanner gains uploaded (mult=%.3f, dv=%d)', gain_resonant_mult, dv_galvo
            )
        except Exception as exc:
            msg = f'update_scanner_gains failed: {exc}'
            logger.error(msg)
            self.hardware_error.emit(msg)

    # ------------------------------------------------------------------
    # Bidirectional calibration
    # ------------------------------------------------------------------

    def start_bidir_calibration(self) -> None:
        """Begin bidirectional pixel-shift calibration for the current magnification.

        Resets the bishift to 0 for the current magnification (so the raw
        scanner timing offset is visible), then connects to the live frame
        stream and accumulates an exponential rolling average (tau = 5 frames).
        After :attr:`~bidir_calibration.BidirCalibration.frames_needed` frames
        the shift is measured automatically, stored, and saved to
        ``bidir_cal.json``.  Progress is reported via
        :attr:`bidir_calibration_progress`; completion via
        :attr:`bidir_calibration_done`.

        Raises:
            RuntimeError: If the system is not currently in bidirectional mode.
        """
        if self._bidir_cal_active:
            logger.warning('Bidir calibration already in progress.')
            return

        unidirectional = self.config.get('acquisition', {}).get('unidirectional', True)
        if unidirectional:
            raise RuntimeError(
                'Switch to bidirectional mode before running calibration.'
            )

        if self._bidir_cal is None:
            # No config_path was given; create an in-memory-only calibration.
            logger.warning(
                'No config_path set — calibration results will NOT be saved to disk.'
            )
            import tempfile
            tmp = tempfile.NamedTemporaryFile(
                suffix='.yaml', delete=False
            )
            tmp.close()
            self._bidir_cal = bidir_calibration.BidirCalibration(tmp.name)

        mag_index = self.config.get('acquisition', {}).get('magnification', 0)
        logger.info(
            'Starting bidir calibration for magnification index %d', mag_index
        )

        # Zero out the current magnification's bishift so the raw offset is
        # visible during frame collection.
        self.set_bishift(0)

        self._bidir_cal.reset()
        self._bidir_cal_active = True
        self.frame_data_ready.connect(self._on_bidir_calibration_frame)

    def stop_bidir_calibration(self) -> None:
        """Cancel an in-progress bidirectional calibration without saving."""
        if not self._bidir_cal_active:
            return
        self._bidir_cal_active = False
        try:
            self.frame_data_ready.disconnect(self._on_bidir_calibration_frame)
        except (RuntimeError, TypeError):
            pass
        logger.info('Bidir calibration cancelled.')

    def _on_bidir_calibration_frame(self, frame) -> None:
        """Internal slot: feed one live frame into the calibration accumulator."""
        if not self._bidir_cal_active:
            return
        # Use PMT channel 0 only; frame shape is (2, lines, pixels).
        channel0 = frame[0] if getattr(frame, 'ndim', 1) == 3 else frame
        self._bidir_cal.add_frame(channel0)

        done = self._bidir_cal.frame_count
        needed = self._bidir_cal.frames_needed
        self.bidir_calibration_progress.emit(done, needed)

        if self._bidir_cal.is_converged:
            self._bidir_cal_active = False
            try:
                self.frame_data_ready.disconnect(self._on_bidir_calibration_frame)
            except (RuntimeError, TypeError):
                pass

            mag_index = self.config.get('acquisition', {}).get('magnification', 0)
            shift = self._bidir_cal.calibrate_magnification(mag_index)
            hsync_sign = self.config.get('scanner', {}).get('hsync_sign', None)
            self._bidir_cal.save(hsync_sign=hsync_sign)
            self.set_bishift(shift)
            self.bidir_calibration_done.emit(mag_index, shift)
            self._log_event(
                f'Bidir calibration done: mag={mag_index}, bishift={shift}'
            )
            logger.info(
                'Bidir calibration complete: mag=%d, shift=%d', mag_index, shift
            )

    def save_manual_bidir_calibration(self) -> str:
        """Save the current per-magnification bishift values to ``bidir_cal.json``.

        Copies the live ``config['acquisition']['bishift']`` list (which
        holds both auto-calibrated and manually adjusted values) into the
        :class:`~pyscanbox.calibration.bidir.BidirCalibration` object and
        writes it to disk alongside the config file.

        Returns:
            The absolute path of the file that was written.

        Raises:
            RuntimeError: If no calibration object is available (no
                ``config_path`` was provided at construction time).
        """
        if self._bidir_cal is None:
            raise RuntimeError(
                'No calibration file path available — provide a config_path '
                'when constructing AppController to enable saving.'
            )
        bishift = self.config.get('acquisition', {}).get('bishift', [])
        for i, shift in enumerate(bishift):
            self._bidir_cal.set_shift(i, int(shift))
        hsync_sign = self.config.get('scanner', {}).get('hsync_sign', None)
        self._bidir_cal.save(hsync_sign=hsync_sign)
        path = self._bidir_cal.calib_path
        self._log_event(f'Bidir calibration saved manually ({path})')
        logger.info('Manual bidir calibration saved to %s', path)
        return path

    # ------------------------------------------------------------------
    # ETL / Optotune
    # ------------------------------------------------------------------

    def set_etl_current(self, current: int) -> None:
        """Set the Optotune ETL current level.

        The value is forwarded directly to the ScanboxController which
        encodes it using the 16-bit wire format expected by CMD_ETL (ID 48)
        and sends three bytes over the serial link.

        Args:
            current: ETL current in hardware units (0–1760,
                approximately 61.5 µA per count).

        Raises:
            RuntimeError: If hardware is not open.
        """
        if not self.is_open:
            raise RuntimeError("AppController is not open. Call open() first.")

        try:
            self._hw_controller.set_etl_current(current)
            logger.debug("ETL current set to %d", current)
        except Exception as exc:
            msg = f"set_etl_current failed: {exc}"
            logger.error(msg)
            self.hardware_error.emit(msg)

    def upload_focus_stack(
        self,
        top: int,
        bottom: int,
        n_planes: int,
        frames_per_plane: int,
    ) -> None:
        """Compute and upload a step-waveform focus-stacking table.

        Generates ``n_planes`` equally-spaced ETL current values between
        ``top`` and ``bottom``, each repeated ``frames_per_plane`` times,
        and uploads the resulting table to the PSoC5 via
        ``upload_etl_waveform()``.  The PSoC5 will advance through the
        table one entry per frame trigger once ``enable_focus_stack(True)``
        is called.

        Constraint: ``n_planes × frames_per_plane ≤ 255`` (PSoC5 period
        register is one byte).

        Args:
            top: ETL current at the top (nearest) imaging plane (0–1760).
            bottom: ETL current at the bottom (furthest) imaging plane.
            n_planes: Number of depth planes.
            frames_per_plane: Frames to acquire at each plane before
                stepping to the next.

        Raises:
            RuntimeError: If hardware is not open.
            ValueError: If the table would exceed 255 entries, or any ETL
                value is out of range.
        """
        if not self.is_open:
            raise RuntimeError("AppController is not open. Call open() first.")

        total = n_planes * frames_per_plane
        if total > 255:
            raise ValueError(
                f'Focus stack table too large: {n_planes} planes × '
                f'{frames_per_plane} frames = {total} entries (max 255)'
            )

        import numpy as np
        etl_vals = np.round(np.linspace(top, bottom, n_planes)).astype(int).tolist()
        waveform = [v for v in etl_vals for _ in range(frames_per_plane)]

        try:
            self._hw_controller.upload_etl_waveform(waveform)
            self._log_event(
                f'Focus stack uploaded: {n_planes} planes × '
                f'{frames_per_plane} frames/plane '
                f'(ETL {top}\u2192{bottom}, {total} entries)'
            )
            logger.info(
                "Focus stack uploaded: %d planes × %d frames, ETL %d→%d",
                n_planes, frames_per_plane, top, bottom,
            )
        except Exception as exc:
            msg = f"upload_focus_stack failed: {exc}"
            logger.error(msg)
            self.hardware_error.emit(msg)
            raise

    def enable_focus_stack(self, active: bool) -> None:
        """Enable or disable autonomous ETL waveform cycling on the PSoC5.

        When enabled the PSoC5 advances through the uploaded waveform on
        every frame trigger.  When disabled the ETL returns to direct
        manual control via ``set_etl_current()``.

        Args:
            active: True to start cycling, False to stop.

        Raises:
            RuntimeError: If hardware is not open.
        """
        if not self.is_open:
            raise RuntimeError("AppController is not open. Call open() first.")

        try:
            self._hw_controller.set_etl_waveform_active(active)
            state = 'enabled' if active else 'disabled'
            self._log_event(f'Focus stack {state}')
            logger.info("Focus stack %s", state)
        except Exception as exc:
            msg = f"enable_focus_stack failed: {exc}"
            logger.error(msg)
            self.hardware_error.emit(msg)
            raise

    def etl_to_depth(self, current: int) -> Optional[int]:
        """Convert an ETL current value to focal depth in microns.

        Returns ``None`` when no calibration file has been loaded (the GUI
        then falls back to displaying the raw ETL current value).

        Args:
            current: ETL current level (0–1760 hardware units).

        Returns:
            Depth in microns as an ``int``, or ``None`` if uncalibrated.
        """
        return etl_calibration.etl_to_depth(current, self._etl_calibration)

    def reload_etl_calibration(self, coeffs) -> None:
        """Replace the in-memory ETL calibration coefficients.

        Called by the main window after the user saves a new calibration from
        the ETL calibration dialog, so the depth display updates immediately
        without requiring a hardware reconnect.

        Args:
            coeffs: 3-element array ``[a, b, c]`` as returned by
                :func:`~pyscanbox.calibration.etl.fit_etl_curve`.
        """
        import numpy as np
        self._etl_calibration = np.asarray(coeffs, dtype=float)
        logger.info('ETL calibration reloaded (live update): %s', self._etl_calibration)

    # ------------------------------------------------------------------
    # Pockels cell LUT upload
    # ------------------------------------------------------------------

    def upload_pockels_lut(self, lut: list) -> None:
        """Upload a 256-entry Pockels cell linearisation LUT to the PSoC5.

        Sends 256 ``[0x43, idx, val]`` packets to the PSoC5 controller so
        that every subsequent active-power DAC value is linearised by the
        hardware.  Also stores the new LUT in ``config['pockels']['lut']``
        so it is re-uploaded automatically on the next scan start
        (``Scanner.initialize_pockels_lut()``).

        Args:
            lut: List of exactly 256 integers in the range 0–255.

        Raises:
            RuntimeError: If hardware is not open.
            ValueError: If *lut* does not have exactly 256 entries or any
                entry is outside 0–255.
        """
        if not self.is_open:
            raise RuntimeError("AppController is not open. Call open() first.")

        try:
            self._hw_controller.set_pockels_lut(lut)
        except Exception as exc:
            msg = f"upload_pockels_lut failed: {exc}"
            logger.error(msg)
            self.hardware_error.emit(msg)
            raise

        # Persist in config so Scanner re-uploads on the next acquisition start.
        self.config.setdefault('pockels', {})['lut'] = [int(v) for v in lut]
        self.config['pockels']['lut_enabled'] = True

        self._log_event(
            f'Pockels LUT uploaded ({len(lut)} entries)'
        )
        logger.info('Pockels LUT uploaded (%d entries).', len(lut))

    # ------------------------------------------------------------------
    # Angle motor
    # ------------------------------------------------------------------

    def set_keep_tip_fixed(self, enabled: bool) -> None:
        """Enable or disable tip-fixed rotation mode.

        When enabled, turning the angle knob (motor 3) also moves the X
        (motor 2) and Z (motor 0) motors by the amounts required to keep the
        tip of the objective at the same absolute position in space.  The
        compensation is computed from the objective length stored in
        ``config['objective']['length']``.

        Has no effect if ``config['objective']['length']`` is zero or
        absent.

        Args:
            enabled: ``True`` to activate tip-fixed mode; ``False`` to
                return to normal angle-only rotation.
        """
        self._keep_tip_fixed = enabled
        logger.info("set_keep_tip_fixed: %s", enabled)

    def zero_angle(self) -> bool:
        """Move the angle motor (A-axis, motor 3) to absolute step 0.

        Issues an MVP Type 0 (absolute) command targeting step 0, then
        resets the PC-side Knobby and desired-step tracking for motor 3
        so that subsequent Knobby packets are interpreted correctly from
        the new zero reference.

        Also sends the Knobby ``zero_xyza`` command (cmd 31) so the Knobby
        display resets its A-axis counter to 0.  As a side effect the Knobby
        display will also show 0 for X, Y, and Z — those motors are NOT
        moved; only the Knobby's internal ``dpos`` counters are cleared.

        Returns:
            True if the motor command was sent successfully, False otherwise.

        Raises:
            RuntimeError: If hardware is not open.
        """
        if not self.is_open:
            raise RuntimeError("AppController is not open. Call open() first.")

        success = False
        if self._motor.is_open:
            try:
                success = self._motor.move_absolute(3, 0)
            except Exception as exc:
                msg = f"zero_angle: move_absolute(motor=3, pos=0) failed: {exc}"
                logger.error(msg)
                self.hardware_error.emit(msg)
                return False
        else:
            logger.warning("zero_angle: motor controller not open.")

        # Send zero_xyza to Knobby so its display resets A (and X/Y/Z) to 0.
        # The X/Y/Z motors are NOT moved — only the Knobby dpos counters are
        # cleared, so subsequent knob-turn deltas start from the new origin.
        if self._knobby.is_open:
            try:
                self._knobby.zero_xyza()
            except Exception as exc:
                logger.warning("zero_angle: zero_xyza command failed: %s", exc)

        # Reset PC-side dpos tracking for all axes so that deltas from
        # subsequent Knobby packets are computed from the new Knobby origin.
        for _i in range(4):
            self._knobby_dpos_steps[_i] = 0
            self._positions[_i] = 0.0
        # Keep _desired_steps for X/Y/Z unchanged so those motors hold position.
        self._desired_steps[3] = 0

        self._emit_positions()
        self._log_event('zero_angle(): A-axis motor → step 0')
        logger.info("zero_angle: motor 3 commanded to step 0.")
        return success

    # ------------------------------------------------------------------
    # Position polling (internal)
    # ------------------------------------------------------------------

    def _poll_positions(self) -> None:
        """Drain Knobby packets, forward moves to motors, poll absolute positions.

        Called every POSITION_POLL_INTERVAL_MS by _poll_timer.

        For each normal axis packet (motor_id 0-3):
          - Compute the delta since the last known dpos value.
          - Accumulate the delta into _desired_steps[motor_id] and issue
            move_absolute() to that target.  Using move_absolute() instead
            of move_relative() is smoother: even when knobs are turned faster
            than the motor can settle, every command targets the correct final
            position rather than compounding errors from intermediate ones.
          - Startup packets (dpos=0) produce delta=0 — safe no-ops.
          - Update the cached Knobby relative position.

        For zero-button packets (motor_id 10 = zero XYZ, 11 = zero XYZA):
          - Reset _knobby_dpos_steps to 0 so subsequent deltas are computed
            from the new Knobby origin.
          - Leave _desired_steps unchanged so motors do NOT move.

        After draining all pending Knobby packets, query all four motors for
        their current absolute step positions.  At 57600 baud each TMCL
        roundtrip (9 bytes out + 9 bytes back) takes ~3 ms, so four motors
        take ~12 ms — well within the 100 ms timer budget.

        Emits position_updated on every tick when at least one device is
        open, so both the World (Knobby) and Abs rows in the GUI refresh at
        10 Hz.
        """
        knobby_changed = False

        if self._knobby.is_open:
            try:
                while True:
                    result = self._knobby.read_command()
                    if result is None:
                        break
                    motor_id, new_dpos_steps = result
                    # Zero-button packets: motor_id=10 (XYZ) or 11 (XYZA).
                    # Reset dpos tracking so deltas are relative to the new
                    # Knobby origin; leave _desired_steps so motors hold still.
                    # Update _positions to 0 and flag knobby_changed so the
                    # GUI refreshes immediately to show the new zero values.
                    if motor_id == 10:
                        for _i in (0, 1, 2):
                            self._knobby_dpos_steps[_i] = 0
                            self._positions[_i] = 0.0
                        knobby_changed = True
                        logger.debug("Knobby zero XYZ — motor positions held")
                        continue
                    if motor_id == 11:
                        for _i in range(4):
                            self._knobby_dpos_steps[_i] = 0
                            self._positions[_i] = 0.0
                        knobby_changed = True
                        logger.debug("Knobby zero XYZA — motor positions held")
                        continue
                    if not (0 <= motor_id <= 3):
                        logger.warning("Knobby: unexpected motor_id=%d, skipping", motor_id)
                        continue
                    delta = new_dpos_steps - self._knobby_dpos_steps[motor_id]
                    self._knobby_dpos_steps[motor_id] = new_dpos_steps
                    self._positions[motor_id] = hw_knobby.steps_to_units(
                        motor_id, new_dpos_steps
                    )
                    knobby_changed = True
                    # Accumulate delta and drive motor to the absolute target.
                    # delta=0 for firmware startup packets — safe no-op.
                    if self._motor.is_open and delta != 0:
                        self._desired_steps[motor_id] += delta
                        try:
                            self._motor.move_absolute(
                                motor_id, self._desired_steps[motor_id]
                            )
                        except Exception as exc:
                            logger.warning(
                                "move_absolute(motor=%d, pos=%d) failed: %s",
                                motor_id, self._desired_steps[motor_id], exc,
                            )
                        # Tip-fixed mode: when the angle motor moves, also
                        # compensate X (motor 2) and Z (motor 0) so the
                        # objective tip stays at the same absolute position.
                        if (
                            motor_id == 3
                            and self._keep_tip_fixed
                            and self._objective_length_um > 0
                        ):
                            angle_old_deg = hw_knobby.steps_to_units(
                                3, self._desired_steps[3] - delta
                            )
                            angle_new_deg = hw_knobby.steps_to_units(
                                3, self._desired_steps[3]
                            )
                            dx_um, dz_um = coordinate_transform.tip_compensation_delta(
                                angle_old_deg, angle_new_deg,
                                self._objective_length_um,
                            )
                            dx_steps = hw_knobby.units_to_steps(2, dx_um)
                            dz_steps = hw_knobby.units_to_steps(0, dz_um)
                            if dx_steps != 0:
                                self._desired_steps[2] += dx_steps
                                try:
                                    self._motor.move_absolute(
                                        2, self._desired_steps[2]
                                    )
                                except Exception as exc:
                                    logger.warning(
                                        "tip-fix move_absolute(X, %d) failed: %s",
                                        self._desired_steps[2], exc,
                                    )
                            if dz_steps != 0:
                                self._desired_steps[0] += dz_steps
                                try:
                                    self._motor.move_absolute(
                                        0, self._desired_steps[0]
                                    )
                                except Exception as exc:
                                    logger.warning(
                                        "tip-fix move_absolute(Z, %d) failed: %s",
                                        self._desired_steps[0], exc,
                                    )
            except Exception as exc:
                logger.warning("Knobby poll error: %s", exc)

        # Poll all four motor absolute positions every tick.
        abs_changed = False
        if self._motor.is_open:
            for motor_id in range(4):
                try:
                    steps = self._motor.get_position(motor_id)
                    if steps is not None:
                        self._abs_positions[motor_id] = hw_knobby.steps_to_units(
                            motor_id, steps
                        )
                        abs_changed = True
                except Exception as exc:
                    logger.warning(
                        "get_position(motor=%d) failed: %s", motor_id, exc
                    )

        if knobby_changed or abs_changed:
            self._emit_positions(log_knobby=knobby_changed)

    def _emit_positions(self, log_knobby: bool = False) -> None:
        """Emit position_updated with current Knobby and absolute positions.

        The emitted dict contains:
          - ``'X'``, ``'Y'``, ``'Z'``, ``'A'``: Knobby dpos in physical
            units (relative, matches the Knobby screen display).
          - ``'abs_X'``, ``'abs_Y'``, ``'abs_Z'``, ``'abs_A'``: Absolute
            motor hardware positions in physical units (polled from the
            Trinamic board).

        Args:
            log_knobby: When True, write a 'Knobby → PC' entry to the command
                log.  Should only be True when at least one real Knobby
                position packet was received in the current timer tick, to
                avoid flooding the log with repeated entries during quiet
                periods when only abs-position polling is running.
        """
        units = hw_knobby.AXIS_UNITS
        pos = {}
        for i in range(4):
            name = hw_knobby.AXIS_NAMES[i]
            pos[name] = self._positions[i]
            pos[f'abs_{name}'] = self._abs_positions[i]
        self.position_updated.emit(pos)
        if log_knobby:
            detail = '  '.join(
                f'{hw_knobby.AXIS_NAMES[i]}={self._positions[i]:.2f}\u202f{units[i]}'
                for i in range(4)
            )
            self._log_receive('Knobby \u2192 PC', detail)

    # ------------------------------------------------------------------
    # Acquisition control
    # ------------------------------------------------------------------

    def start_focus(self) -> None:
        """Start continuous focus (live preview) mode.

        Starts Scanner in focus mode: acquisition runs indefinitely,
        no data is written to disk, and frame_acquired signals are emitted
        so the GUI can update a live preview.  Call stop_acquisition() to
        end focus mode.

        Raises:
            RuntimeError: If hardware is not open or acquisition is already
                running.
        """
        if not self.is_open:
            raise RuntimeError("AppController is not open. Call open() first.")
        if self.is_acquiring:
            raise RuntimeError(
                "Acquisition already running. Call stop_acquisition() first."
            )
        self._start_scanner(focus_mode=True, output_path=None)
        logger.info("AppController: focus mode started.")
        self._log_event('Focus mode started')

    def start_grab(self, output_path: str = None,
                   frames: int = None,
                   save_channels: int = 2,
                   ttl_mask: int = 0) -> None:
        """Start a timed grab acquisition and save data to disk.

        Acquires the number of frames specified by ``frames`` (or
        config['acquisition']['frames'] when ``frames`` is None), writes
        .sbx/.mat files, and emits acquisition_finished when done.
        Pass ``frames=0`` to run forever (MATLAB convention).

        Args:
            output_path: File path prefix for output files (no extension).
                If None, Scanner auto-generates a path from the io config.
            frames: Frame count override.  0 = run until Stop is pressed.
                If None, the value from config is used.
            save_channels: Which PMT channels to write to disk.  Matches the
                FileStorageGroup combobox index: 0 = PMT0 only, 1 = PMT1
                only, 2 = both channels (default).
            ttl_mask: Which TTL inputs fire timestamped event records.
                Bitmask: 0=none, 1=TTL0, 2=TTL1, 3=both.  Overrides the
                config interrupt_mask value.

        Raises:
            RuntimeError: If hardware is not open or acquisition is already
                running.
        """
        if not self.is_open:
            raise RuntimeError("AppController is not open. Call open() first.")
        if self.is_acquiring:
            raise RuntimeError(
                "Acquisition already running. Call stop_acquisition() first."
            )
        self._start_scanner(focus_mode=False, output_path=output_path,
                            frames_override=frames,
                            save_channels=save_channels,
                            ttl_mask=ttl_mask)
        logger.info("AppController: grab started, output_path=%s", output_path)
        self._log_event(f'Grab started  →  {output_path}')

    def stop_acquisition(self) -> None:
        """Request the running acquisition to stop gracefully.

        Returns immediately; acquisition_finished is emitted once
        Scanner.cleanup() completes.  Safe to call when idle.
        """
        if self._scanner_thread is not None and self._scanner_thread.isRunning():
            self._scanner_thread.request_stop()
            logger.info("AppController: stop requested.")
            self._log_event('Stop requested')

    @property
    def is_acquiring(self) -> bool:
        """True if an acquisition thread is currently running."""
        return (
            self._scanner_thread is not None
            and self._scanner_thread.isRunning()
        )

    def _start_scanner(self, focus_mode: bool, output_path,
                        frames_override: int = None,
                        save_channels: int = 2,
                        ttl_mask: int = 0) -> None:
        """Create and start a ScannerThread (internal helper).

        Args:
            focus_mode: Passed to ScannerThread.
            output_path: Passed to ScannerThread.
            frames_override: Optional frame count override (0 = forever).
            save_channels: Passed to ScannerThread.  Ignored in focus mode
                (focus mode never writes to disk).
            ttl_mask: TTL interrupt mask bitmask passed to ScannerThread.
        """
        self._scanner_thread = ScannerThread(
            self.config,
            output_path=output_path,
            focus_mode=focus_mode,
            frames_override=frames_override,
            controller=self._hw_controller,
            motor=self._motor if self._motor.is_open else None,
            save_channels=save_channels,
            ttl_mask=ttl_mask,
            plugin_manager=self._plugin_manager,
            parent=self,
        )
        self._scanner_thread.frame_acquired.connect(self.frame_acquired)
        self._scanner_thread.frame_data_ready.connect(self.frame_data_ready)
        self._scanner_thread.command_logged.connect(self.command_logged)
        self._scanner_thread.acquisition_finished.connect(
            self._on_acquisition_finished
        )
        self._scanner_thread.acquisition_error.connect(self.hardware_error)
        self._scanner_thread.start()
        # Apply the current Pockels/PMT values to the mock Alazar once the
        # thread has had time to initialise its alazar object (~100 ms).
        QtCore.QTimer.singleShot(150, self._update_mock_signal_scale)

    def _on_acquisition_finished(self) -> None:
        """Slot called when ScannerThread emits acquisition_finished."""
        frames = "?"
        if (
            self._scanner_thread is not None
            and self._scanner_thread._scanner is not None
        ):
            frames = self._scanner_thread._scanner.frames_acquired
        logger.info("AppController: acquisition finished (frames=%s)", frames)
        self._log_event(f'Acquisition finished  ({frames} frames)')
        self.acquisition_finished.emit()

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log_cmd(self, direction: str, func_name: str,
                 packet_str: str = '') -> None:
        """Emit command_logged with an outgoing-command HTML entry.

        Args:
            direction: Short label, e.g. ``'PC \u2192 Controller (COM3)'``.
            func_name: Name of the function/operation called.
            packet_str: Optional packet or parameter description.
        """
        ts = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
        detail = f'{func_name}: {packet_str}' if packet_str else func_name
        html = (
            f'<span style="color:#888">[{ts}]</span>&nbsp;'
            f'<b><span style="color:#fa8">{direction}</span></b>&nbsp;'
            f'<span style="color:#fd8;font-family:monospace">{detail}</span>'
        )
        self.command_logged.emit(html)

    def _on_controller_cmd(self, com_port: str, cmd_id: int,
                           param1: int, param2: int) -> None:
        """Adapter: translate a ScanboxController serial-write event to _log_cmd.

        Fired by ScanboxController._send_command immediately after every
        port.write(), so the logged bytes always match what was transmitted.

        Args:
            com_port: Serial port name, e.g. ``'COM3'``.
            cmd_id: Command ID byte sent.
            param1: First parameter byte sent.
            param2: Second parameter byte sent.
        """
        direction = f'PC \u2192 Controller ({com_port})'
        func_call = hw_controller.ScanboxController.format_command(
            cmd_id, param1, param2
        )
        packet_str = f'[{cmd_id:02X} {param1:02X} {param2:02X}]'
        self._log_cmd(direction, func_call, packet_str)

    def _on_knobby_cmd(self, com_port: str, command_id: int, value: int) -> None:
        """Adapter: translate a Knobby serial-write event to _log_cmd.

        Fired by Knobby.send_command() after every port.write().

        Args:
            com_port: Serial port name, e.g. ``'COM5'``.
            command_id: Command ID byte sent.
            value: 16-bit value parameter.
        """
        direction = f'PC \u2192 Knobby ({com_port})'
        func_call = hw_knobby.Knobby.format_command(command_id, value)
        packet_str = f'[{command_id:02X} val={value}]'
        self._log_cmd(direction, func_call, packet_str)

    def _on_motor_cmd(self, com_port: str, cmd: str, cmd_type: int,
                      motor: int, value: int) -> None:
        """Adapter: translate a TrinamicMotor serial-write event to _log_cmd.

        Fired by TrinamicMotor.send_command() after every port.write().
        GAP (position read) commands are silently dropped to avoid flooding
        the log at 10 Hz during normal polling.

        Args:
            com_port: Serial port name, e.g. ``'COM4'``.
            cmd: TMCL command string (e.g. ``'MVP'``, ``'GAP'``).
            cmd_type: Command type parameter.
            motor: Motor number (0-3).
            value: 32-bit value parameter.
        """
        if cmd == 'GAP':
            return  # Routine position read — do not flood the command log.
        direction = f'PC \u2192 Motor ({com_port})'
        func_call = hw_motor.TrinamicMotor.format_command(cmd, cmd_type, motor, value)
        packet_str = f'[{cmd} type={cmd_type} motor={motor} val={value}]'
        self._log_cmd(direction, func_call, packet_str)

    def _log_event(self, text: str) -> None:
        """Emit command_logged with a lifecycle-event HTML entry.

        Args:
            text: Plain-text event description.
        """
        ts = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
        html = (
            f'<span style="color:#888">[{ts}]</span>&nbsp;'
            f'<span style="color:#e8a;font-weight:bold">\u2500\u2500\u2500 '
            f'{text} \u2500\u2500\u2500</span>'
        )
        self.command_logged.emit(html)

    def _log_receive(self, direction: str, detail: str) -> None:
        """Emit command_logged with an incoming-data HTML entry.

        Args:
            direction: Short label, e.g. ``'Knobby → PC'``.
            detail: Human-readable description of the received data.
        """
        ts = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
        html = (
            f'<span style="color:#888">[{ts}]</span>&nbsp;'
            f'<b><span style="color:#7bf">{direction}</span></b>&nbsp;'
            f'<span style="color:#bbb">{detail}</span>'
        )
        self.command_logged.emit(html)

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self):
        """Context manager entry."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
