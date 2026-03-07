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

import PyQt6.QtCore as QtCore

from pyscanbox.hardware import controller as hw_controller
from pyscanbox.hardware import knobby as hw_knobby
from pyscanbox.hardware import motor as hw_motor
from pyscanbox.acquisition import scan as acq_scan


logger = logging.getLogger(__name__)

# Polling interval for Knobby position updates (milliseconds).
POSITION_POLL_INTERVAL_MS = 100

# Scale factor for mapping 0-100% GUI slider to 0-255 hardware range.
POCKELS_PERCENT_TO_HW = 255.0 / 100.0

# Scale factor for PMT gain sliders (0-100 % -> 0-255 hardware range).
PMT_PERCENT_TO_HW = 255.0 / 100.0


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

    def __init__(self, config: dict, parent=None):
        """Initialize the application controller.

        Hardware objects are created here but not yet connected.
        Call open() before issuing any hardware commands.

        Args:
            config: Configuration dictionary (e.g. from ScanboxConfig.to_dict()).
            parent: Optional Qt parent object.
        """
        super().__init__(parent)
        self.config = config
        self.is_open = False

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

        # Last Knobby dpos in raw steps, used to compute per-packet deltas
        # so we can forward relative moves to the motor controller.
        self._knobby_dpos_steps = {i: 0 for i in range(4)}

        # Absolute motor positions: motor_id → position in physical units,
        # polled from the Trinamic board every timer tick.
        self._abs_positions = {i: 0.0 for i in range(4)}

        # Absolute motor positions in raw steps at the time open() was called.
        # Stored as the hardware origin reference (for display / debugging).
        self._motor_origin_steps = {i: 0 for i in range(4)}

        # Scanner thread (created by start_focus() / start_grab()).
        self._scanner_thread = None

        # Timer for periodic Knobby position polling.
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(POSITION_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_positions)

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
        try:
            self._hw_controller.open()
        except Exception as exc:
            msg = f"Could not open ScanboxController: {exc}"
            logger.error(msg)
            self.hardware_error.emit(msg)
            raise RuntimeError(msg) from exc

        try:
            self._knobby.open()
        except Exception as exc:
            # Non-fatal: GUI can run without Knobby position display.
            msg = f"Could not open Knobby (position display unavailable): {exc}"
            logger.warning(msg)
            self.hardware_error.emit(msg)

        try:
            self._motor.open()
            # Record absolute hardware positions at startup as the origin
            # reference (stored for display/debugging; not used in move logic).
            for motor_id in range(4):
                pos = self._motor.get_position(motor_id)
                self._motor_origin_steps[motor_id] = pos if pos is not None else 0
        except Exception as exc:
            # Non-fatal: GUI can run without motor control.
            msg = f"Could not open motor controller (motor control unavailable): {exc}"
            logger.warning(msg)
            self.hardware_error.emit(msg)

        self.is_open = True
        self._poll_timer.start()
        logger.info("AppController: hardware open, position polling started.")
        emulation = self.config.get('emulation', {}).get('enabled', False)
        suffix = ' (emulation)' if emulation else ''
        self._log_event(f'Hardware connected{suffix}')

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

        self.is_open = False
        logger.info("AppController: hardware closed.")
        self._log_event('Hardware disconnected')

    # ------------------------------------------------------------------
    # Laser / Pockels cell
    # ------------------------------------------------------------------

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

        try:
            self._hw_controller.set_pockels(base=0, active=hw_value)
            logger.debug("Pockels set to %d%% (hw=%d)", percent, hw_value)
        except Exception as exc:
            msg = f"set_pockels failed: {exc}"
            logger.error(msg)
            self.hardware_error.emit(msg)

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

    # ------------------------------------------------------------------
    # Position polling (internal)
    # ------------------------------------------------------------------

    def _poll_positions(self) -> None:
        """Drain Knobby packets, forward moves to motors, poll absolute positions.

        Called every POSITION_POLL_INTERVAL_MS by _poll_timer.

        For each Knobby packet received:
          - Compute the delta since the last known dpos value.
          - Forward that delta to the matching motor axis as a relative
            (MVP Type 1) move.  Startup packets from the Knobby firmware
            always carry dpos=0 (delta=0) so they produce no motor movement.
          - Update the cached Knobby relative position.

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
                    if 0 <= motor_id <= 3:
                        delta = new_dpos_steps - self._knobby_dpos_steps[motor_id]
                        self._knobby_dpos_steps[motor_id] = new_dpos_steps
                        self._positions[motor_id] = hw_knobby.steps_to_units(
                            motor_id, new_dpos_steps
                        )
                        knobby_changed = True
                        # Forward the delta as a relative move.  delta=0 for
                        # firmware startup packets — safe no-op.
                        if self._motor.is_open and delta != 0:
                            try:
                                self._motor.move_relative(motor_id, delta)
                            except Exception as exc:
                                logger.warning(
                                    "move_relative(motor=%d, delta=%d) failed: %s",
                                    motor_id, delta, exc,
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
                   save_channels: int = 2) -> None:
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
                            save_channels=save_channels)
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
                        save_channels: int = 2) -> None:
        """Create and start a ScannerThread (internal helper).

        Args:
            focus_mode: Passed to ScannerThread.
            output_path: Passed to ScannerThread.
            frames_override: Optional frame count override (0 = forever).
            save_channels: Passed to ScannerThread.  Ignored in focus mode
                (focus mode never writes to disk).
        """
        self._scanner_thread = ScannerThread(
            self.config,
            output_path=output_path,
            focus_mode=focus_mode,
            frames_override=frames_override,
            controller=self._hw_controller,
            motor=self._motor if self._motor.is_open else None,
            save_channels=save_channels,
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
