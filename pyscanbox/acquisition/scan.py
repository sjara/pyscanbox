# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Main acquisition loop and scanner control.

This module implements the main acquisition loop that coordinates:
    - Alazar digitizer data acquisition
    - Real-time data reshaping
    - File writing
    - Hardware synchronization

Reference:
    Original MATLAB implementation: core/scanbox.m (while ~captureDone loop)

Example:
    >>> import pyscanbox
    >>> config = pyscanbox.config.load_config()
    >>> scanner = pyscanbox.acquisition.scan.Scanner(config.to_dict())
    >>> scanner.run()
"""

import logging
import sys
import time
import numpy as np
from typing import Callable, Optional
import pyscanbox

logger = logging.getLogger(__name__)
from pyscanbox.hardware import alazar
from pyscanbox.hardware import controller
from pyscanbox.hardware import motor
from pyscanbox.acquisition import reshape as data_reshape
from pyscanbox.io import sbx_writer


class Scanner:
    """Main scanner control and acquisition loop.

    This class coordinates all hardware components and manages the
    continuous acquisition loop for two-photon microscopy.

    Attributes:
        config: Configuration object
        alazar: AlazarDigitizer instance
        controller: ScanboxController instance
        motor: TrinamicMotor instance (optional)
        writer: ScanboxOriginalWriter instance
        is_running: Acquisition running flag
        frames_acquired: Counter for acquired frames
    """

    def __init__(self, config: dict, output_path: Optional[str] = None,
                 focus_mode: bool = False,
                 frames_override: Optional[int] = None,
                 on_frame: Optional[Callable[[int], None]] = None,
                 on_frame_data=None,
                 on_command=None,
                 hw_controller=None,
                 hw_motor=None,
                 save_channels: int = 2,
                 plugin_manager=None):
        """Initialize scanner with configuration.

        Args:
            config: Configuration dictionary
            output_path: Optional output file path (excluding extension).
                If None, uses config['io']['output_directory'] and
                config['io']['file_prefix'].
            focus_mode: If True, run indefinitely without writing to disk.
                Used for live-preview (Focus button). Sets frames_to_acquire
                to sys.maxsize and skips file-writer initialisation.
            frames_override: If given, overrides config['acquisition']['frames'].
                0 means "run forever" (MATLAB convention), which maps to
                sys.maxsize internally.  Ignored in focus mode (focus mode
                always runs forever).
            on_frame: Optional callback invoked after each acquired frame
                with the cumulative frame count as the sole argument.
                Used by ScannerThread to emit Qt signals from the loop.
            on_frame_data: Optional callback invoked after each acquired
                frame with the reshaped frame array as the sole argument
                (shape ``(channels, lines, pixels)``, dtype uint16).
                Used by ScannerThread to feed the live-preview display.
            hw_controller: Optional pre-opened ScanboxController to reuse.
                When provided, Scanner will not call open() or close() on it
                (ownership stays with the caller).  Pass this when the GUI
                already holds an open connection so that a second open() on
                the same COM port is avoided on real hardware.
            hw_motor: Optional pre-opened TrinamicMotor to reuse.
                Same ownership semantics as ``hw_controller``: when provided
                Scanner will not call open() or close() on it, preventing a
                second attempt to open the motor COM port.
            save_channels: Which PMT channels to write to disk.  Matches the
                FileStorageGroup combobox index: 0 = PMT0 only, 1 = PMT1
                only, 2 = both channels (default).
        """
        self.config = config
        self.output_path = output_path

        # Initialize hardware
        self.alazar = alazar.AlazarDigitizer(
            config, on_command=self._on_alazar_cmd
        )
        if hw_controller is not None:
            # Reuse an already-open controller (e.g. held by AppController).
            # We temporarily redirect its on_command to our logging path in
            # initialize_hardware() and restore it in cleanup().
            self.controller = hw_controller
            self._controller_owned = False
            self._controller_orig_on_cmd = hw_controller.on_command
        else:
            self.controller = controller.ScanboxController(
                config, on_command=self._on_controller_cmd
            )
            self._controller_owned = True
            self._controller_orig_on_cmd = None
        if hw_motor is not None:
            # Reuse an already-open motor (e.g. held by AppController).
            self.motor: Optional[motor.TrinamicMotor] = hw_motor
            self._motor_owned = False
            self._motor_orig_on_cmd = hw_motor.on_command
        else:
            self.motor = None
            self._motor_owned = True
            self._motor_orig_on_cmd = None
        
        # Acquisition parameters
        self.lines_per_frame = config['acquisition']['lines_per_frame']
        self.pixels_per_line = config['acquisition']['pixels_per_line']
        self.frames_to_acquire = config['acquisition']['frames']
        self.magnification = config['acquisition'].get('magnification', 0)

        # Bidirectional mode: False when unidirectional=True (default).
        # Takes effect immediately; changing the config key at runtime (e.g.
        # from AppController.set_scan_mode) updates the running scanner on
        # the next frame because we read from the config dict each frame.
        acq_cfg = config.get('acquisition', {})
        self.bidirectional: bool = not acq_cfg.get('unidirectional', True)
        # Keep a reference to the bishift list in config so that
        # AppController.set_bishift() updates propagate to the running
        # scanner immediately (both share the same list object).
        acq_cfg.setdefault('bishift', [0] * 13)
        self._bishift: list = acq_cfg['bishift']

        # Raw-mode acquisition: use arccosine pixel LUT instead of pre-shaped data.
        # When True, each Alazar buffer contains `lines × samples_per_line × 2`
        # interleaved raw ADC samples and reshape_pmt_data() is called.
        #
        # IMPORTANT: AlazarDigitizer._use_raw_mode is always True on real
        # hardware (not emulation), regardless of emulation.raw_mode in config.
        # Scanner must use the same logic so the correct reshape function is
        # called.  On emulation, raw_mode=False uses the pre-shaped path.
        emulation_on = config.get('emulation', {}).get('enabled', False)
        self.raw_mode: bool = (
            not emulation_on
            or config.get('emulation', {}).get('raw_mode', False)
        )
        self._pixel_lut: Optional[np.ndarray] = None
        self._pixel_lut_bi: Optional[np.ndarray] = None
        if self.raw_mode:
            laser_freq = config['laser']['frequency']
            res_freq   = config['scanner']['resonant_freq']
            self._pixel_lut = data_reshape.compute_pixel_lut(
                self.pixels_per_line, laser_freq, res_freq
            )
            # Trigger Numba JIT compilation now with a tiny dummy call so the
            # first real acquisition frame doesn't stall.  With cache=True this
            # is a one-time cost (a few seconds on first run, ~0 ms thereafter).
            _dummy_buf = np.zeros(4 * 2, dtype=np.uint16)   # 1 line, 4 samples
            _dummy_lut = np.zeros(1, dtype=np.int32)
            data_reshape.reshape_pmt_data(_dummy_buf, 1, 1, _dummy_lut)
            # Bidirectional pixel LUT: built when bidirectional mode is active.
            # compute_pixel_lut_bi returns an extended LUT covering both
            # forward and backward pixels in a single 9000-sample record.
            if self.bidirectional:
                spl_bi = config.get('acquisition', {}).get(
                    'samples_per_line_bidir', 9000
                )
                self._pixel_lut_bi = data_reshape.compute_pixel_lut_bi(
                    self.pixels_per_line, laser_freq, res_freq, spl_bi
                )
                # JIT warmup for bidirectional reshape.
                _dummy_lut_bi = np.zeros(2, dtype=np.int32)
                data_reshape.reshape_pmt_data_bi(
                    np.zeros(4 * 2, dtype=np.uint16), 1, 1, _dummy_lut_bi, 0
                )

        # Acquisition mode flags.
        self.focus_mode = focus_mode
        self.on_frame = on_frame
        self.on_frame_data = on_frame_data
        self.on_command = on_command
        self.save_channels = save_channels
        self.plugin_manager = plugin_manager
        # Apply GUI override first (0 means "forever", matching MATLAB convention).
        if frames_override is not None:
            self.frames_to_acquire = frames_override
        if focus_mode or self.frames_to_acquire == 0:
            self.frames_to_acquire = sys.maxsize

        # File writers
        self.sbx_writer: Optional[sbx_writer.ScanboxOriginalWriter] = None
        
        # State
        self.is_running = False
        self.frames_acquired = 0
        self.start_time = 0.0

    def initialize_hardware(self) -> None:
        """Initialize and configure all hardware components.

        Opens connections, configures parameters, and prepares for
        acquisition.

        Raises:
            RuntimeError: If hardware initialization fails.
        """
        # Open and configure Alazar
        self.alazar.open()
        self.alazar.configure()
        self.alazar.allocate_buffers()

        # Open controller only if we created it ourselves.  When the caller
        # passes an already-open controller (hw_controller parameter), opening
        # it again would fail on real hardware (port already in use).
        if self._controller_owned:
            self.controller.open()
        else:
            # Redirect command logging to Scanner's path for scan duration.
            self.controller.on_command = self._on_controller_cmd

        # Upload Pockels LUT and range once after the controller is open.
        self.initialize_pockels_lut()

        # Synchronize PSoC5 to resonant scanner phase (deadband period and
        # blanking regions). This is essential for continuous resonant mode.
        self.synchronize_scanner_phase()

        # Initialize motor if configured
        if 'motor' in self.config:
            if self._motor_owned:
                # No pre-opened motor was supplied — create and open one.
                self.motor = motor.TrinamicMotor(
                    self.config, on_command=self._on_motor_cmd
                )
                self.motor.open()
                # Apply per-motor freewheeling from config (TMCL SAP 204).
                motor_cfg = self.config.get('motor', {})
                freewheel = [
                    motor_cfg.get('freewheel_z', False),
                    motor_cfg.get('freewheel_y', False),
                    motor_cfg.get('freewheel_x', False),
                    motor_cfg.get('freewheel_a', False),
                ]
                for motor_id, enabled in enumerate(freewheel):
                    self.motor.set_freewheel(motor_id, bool(enabled))
            else:
                # Reuse the caller's already-open motor; redirect logging.
                self.motor.on_command = self._on_motor_cmd

    def initialize_writers(self) -> None:
        """Initialize the Scanbox-compatible .sbx writer.

        The companion .mat metadata file is written automatically when the
        writer is closed at the end of acquisition.
        """
        if self.output_path is None:
            output_dir = self.config['io']['output_directory']
            file_prefix = self.config['io']['file_prefix']
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            self.output_path = f"{output_dir}/{file_prefix}_{timestamp}"

        nchan = 1 if self.save_channels in (0, 1) else 2
        pmt_channel = self.save_channels if self.save_channels in (0, 1) else 0
        unidirectional = self.config.get('acquisition', {}).get('unidirectional', True)
        scanmode = 1 if unidirectional else 0
        self.sbx_writer = sbx_writer.ScanboxOriginalWriter(
            self.output_path,
            lines_per_frame=self.lines_per_frame,
            pixels_per_line=self.pixels_per_line,
            nchan=nchan,
            scanmode=scanmode,
            pmt_channel=pmt_channel,
        )

    def configure_scan_params(self) -> None:
        """Send scan parameters to the controller before starting acquisition.

        Sends lines-per-frame, frame count, and magnification to the PSoC
        controller, matching the MATLAB ``sb_setparam`` / ``sb_setframe``
        sequence.

        Frame-count behaviour (mirrors MATLAB ``frames_Callback``):
            * Focus mode or ``frames_to_acquire`` > 65535 → sends 0 (run
              forever; controller stops only when ``stop_scan()`` is called).
            * Grab mode with ``frames_to_acquire`` ≤ 65535 → sends the exact
              count; the controller hardware stops the scanner automatically
              after that many frames.
        """
        self.controller.set_lines(self.lines_per_frame)

        if self.focus_mode or self.frames_to_acquire > 65535:
            hw_frame_count = 0          # 0 = run until explicit stop
        else:
            hw_frame_count = self.frames_to_acquire
        self.controller.set_frame_count(hw_frame_count)

        self.controller.set_magnification(self.magnification)

        # Configure TTL interrupt mask so the PSoC5 knows which external
        # TTL inputs to monitor.  imask=0 disables both (safe default).
        # Reference: sb_imask.m; original scanbox.m line 251.
        imask = self.config.get('external_events', {}).get('interrupt_mask', 0)
        self.controller.set_ttl_mask(imask)

        # Horizontal sync polarity: 0 = normal, 1 = flip scan direction.
        # Toggling this is useful for diagnosing Pockels cell phase/timing
        # asymmetry (see devel/guides/pockels_calibration.md).
        # Reference: sb/sb_hsync_sign.m; scanbox.m line 294.
        hsync_sign = self.config.get('scanner', {}).get('hsync_sign', 1)
        self.controller.set_hsync_sign(hsync_sign)

        # Resonant scanner warmup delay: how long the PSoC5 waits (after
        # start_scan) before firing line triggers, giving the mirror time
        # to reach its stable oscillation amplitude.  Without this the
        # first frames will be geometrically distorted.
        # Reference: sb/sb_warmup_delay.m; scanbox.m line 303.
        warmup_delay = self.config.get('scanner', {}).get('warmup_delay', 50)
        self.controller.set_warmup_delay(warmup_delay)

    def initialize_pockels_lut(self) -> None:
        """Upload the Pockels cell LUT and range from config to the PSoC5.

        Reads ``pockels.lut``, ``pockels.lut_enabled``, and
        ``pockels.range`` from config and uploads them in the same order
        as the original MATLAB startup sequence (``core/scanbox.m``
        lines 262–288).

        If ``lut_enabled`` is false or ``lut`` is absent from config,
        the identity LUT is used (linear voltage, non-linear power).
        """
        pockels_cfg = self.config.get('pockels', {})

        # 1. Upload LUT or reset to identity.
        lut = pockels_cfg.get('lut') if pockels_cfg.get('lut_enabled', True) else None
        if lut and len(lut) == 256:
            logger.info('Uploading Pockels LUT (%d entries).', len(lut))
            self.controller.set_pockels_lut(lut)
        else:
            logger.info('No Pockels LUT in config — resetting to identity.')
            self.controller.set_pockels_lut_identity()

        # 2. Set DAC/PGA range.
        prange = pockels_cfg.get('range', [1, 2])
        self.controller.set_pockels_range(int(prange[0]), int(prange[1]))

    def synchronize_scanner_phase(self) -> None:
        """Synchronize PSoC5 to resonant scanner oscillation phase.

        Sets the deadband period (phase sync) once. This is critical for
        correct line trigger timing in continuous resonant mode where the
        scanner is already oscillating when acquisition starts.

        This method is called only on the very first hardware initialization
        to avoid re-synchronizing in the middle of continuous resonant mode,
        which can cause frame shifts.

        Reference:
            Original MATLAB: sb_deadband_period.m (called once at startup)
            scanbox.m line 483
        """
        # Check if we've already synchronized (guard against re-sync)
        if not hasattr(self.controller, '_deadband_period_set'):
            resonant_freq = self.config.get('scanner', {}).get('resonant_freq', 7930)
            deadband_period = round(24e6 / resonant_freq / 2)
            self.controller.set_deadband_period(deadband_period)
            # Mark that we've done the synchronization
            self.controller._deadband_period_set = True

    def synchronize_pockels_blanking(self) -> None:
        """Apply Pockels cell blanking regions at line margins.

        Called before each acquisition to set the blanking width values.
        Must be called AFTER set_deadband_period() (during initialization).

        Reference:
            Original MATLAB: sb_deadband.m
            scanbox.m line 538 (called at each acquisition startup)
        """
        deadband_cfg = self.config.get('scanner', {}).get('deadband', [120, 150])
        self.controller.set_pockels_deadband(deadband_cfg[0], deadband_cfg[1])

    def initialize_pockels(self) -> None:
        """Set Pockels cell to zero power as a safe starting state.

        This is called at the start of every scan session, before the
        scanner begins moving.  Setting power to (0, 0) ensures no laser
        energy reaches the sample until the user explicitly moves the
        Pockels slider.

        Note on shutter handling:
            On this rig the external shutter is wired to the controller's
            LASER SHUTTER output and opens/closes automatically when
            ``start_scan()`` / ``stop_scan()`` (CMD_SCAN, ID 4) are sent —
            no explicit ``set_shutter()`` call is needed.

            In the original Scanbox MATLAB code the laser shutter is also
            user-controlled via the laser head's own serial interface
            (Chameleon/Discovery/MaiTai ``SHUTTER=1``).  The controller's
            ``CMD_SHUTTER`` (ID 16) is a separate signal that on this rig
            produces no effect.

            On rigs where the Uniblitz shutter is driven by CMD_SHUTTER, the
            commented-out ``set_shutter()`` calls below in ``run()`` and
            ``cleanup()`` should be uncommented instead.
        """
        self.controller.set_pockels(base=0, active=0)

    def zero_pockels(self) -> None:
        """Cut laser power immediately by setting Pockels to zero.

        Called during cleanup before the scanner is stopped so that the
        laser is blanked as soon as possible.  Equivalent to the original
        MATLAB behaviour of leaving pockels at a user-defined level during
        the acquisition and returning it to zero on shutdown.
        """
        try:
            self.controller.set_pockels(base=0, active=0)
        except Exception:  # noqa: BLE001 — best-effort safety call
            pass

    def run(self) -> None:
        """Run main acquisition loop.

        This is the main entry point for data acquisition. It:
        1. Initializes all hardware
        2. Starts acquisition
        3. Runs continuous acquisition loop
        4. Handles shutdown and cleanup

        The acquisition loop reads buffers from Alazar, reshapes data,
        and writes to disk in real-time.

        Reference:
            See core/scanbox.m main while loop for logic flow.
        """
        try:
            # Setup
            logger.info("Initializing hardware...")
            self._notify_cmd('System', 'Initializing hardware')
            self.initialize_hardware()

            if not self.focus_mode:
                logger.info("Initializing file writers...")
                self._notify_cmd('System', 'Initializing file writers')
                self.initialize_writers()

            logger.info("Configuring Pockels to zero (safe start)...")
            self.initialize_pockels()
            # Re-apply the Pockels level the user had on the GUI slider.
            # AppController.set_pockels() stores the hw value in
            # config['laser']['pockels_active'] each time the slider moves,
            # so it is already correct even if the slider was not touched
            # since the last acquisition.
            desired_pockels = self.config.get('laser', {}).get('pockels_active', 0)
            if desired_pockels > 0:
                logger.info("Restoring Pockels to hw=%d (from slider).", desired_pockels)
                self.controller.set_pockels(base=0, active=desired_pockels)

            logger.info("Configuring scan parameters...")
            self.configure_scan_params()

            # Notify plugins that acquisition is about to start.  Called
            # after initialize_writers() so output_path is already resolved.
            if self.plugin_manager is not None:
                res_freq = self.config.get('scanner', {}).get('resonant_freq', 7930)
                bidirectional = not self.config.get(
                    'acquisition', {}
                ).get('unidirectional', True)
                frame_rate = (
                    res_freq * (2 if bidirectional else 1)
                    / max(self.lines_per_frame, 1)
                )
                n_frames = (
                    0 if self.frames_to_acquire == sys.maxsize
                    else self.frames_to_acquire
                )
                self.plugin_manager.on_acquisition_start(
                    n_frames, frame_rate, self.output_path or ''
                )

            # Start acquisition — Pockels is at zero so no laser energy
            # reaches the sample yet; the user raises power via the GUI slider.
            # On this rig start_scan() (CMD_SCAN, ID 4) also opens the external
            # shutter automatically via the controller's LASER SHUTTER output.
            # On rigs with a Uniblitz driven by CMD_SHUTTER (ID 16), uncomment:
            #   self.controller.set_shutter(open=True)
            logger.info("Starting acquisition...")
            self._notify_cmd('System', 'Starting acquisition')
            
            # Prepare Alazar digitizer FIRST (equivalent to AlazarStartCapture).
            # The digitizer waits for hardware triggers from the PSoC5.
            self.alazar.start_acquisition()
            
            # Small delay to let digitizer stabilize, matching original MATLAB
            # pause(0.2) at line 2536.
            time.sleep(0.05)  # 50ms delay (conservative)
            
            # Apply Pockels cell blanking before starting scanner, matching original
            # MATLAB sequence (scanbox.m lines 2536-2538).
            self.synchronize_pockels_blanking()
            
            # Start scanner (triggers line captures from digitizer).
            # In continuous resonant mode, this begins capturing at the current
            # scanner phase as established by deadband_period synchronization.
            self.controller.start_scan()
            self.is_running = True
            self.start_time = time.time()

            # Clear any residual TTL events from a previous session and
            # start the background reader that collects 5-byte event
            # packets sent by the PSoC5 over the controller serial port.
            self.controller.clear_ttl_events()
            self.controller.start_ttl_reader()

            # Main acquisition loop
            self._acquisition_loop()
            
        except KeyboardInterrupt:
            logger.info("Acquisition interrupted by user.")
        except Exception as e:
            logger.error("Error during acquisition: %s", e)
            raise
        finally:
            self.cleanup()

    def _acquisition_loop(self) -> None:
        """Main acquisition loop (internal).

        Continuously reads buffers, reshapes data, and writes to disk
        until the target number of frames is acquired.

        This is the performance-critical section that must handle
        ~500 MB/s data throughput.
        """
        samples_per_frame = self.lines_per_frame * self.pixels_per_line
        
        while self.is_running and self.frames_acquired < self.frames_to_acquire:
            # Read buffer from Alazar
            buffer = self.alazar.read_buffer(timeout_ms=5000)
            
            if buffer is None:
                logger.warning("Buffer timeout")
                continue
            
            # Reshape data (performance-critical!)
            if self.raw_mode and self._pixel_lut is not None:
                if self.bidirectional and self._pixel_lut_bi is not None:
                    # Bidirectional raw hardware mode: one Alazar record per
                    # full resonant cycle (forward + backward).  The LUT
                    # extracts both lines, places backward pixels in the
                    # correct column order, and applies bishift in sample
                    # space (matching MATLAB preIdx += bishift*2).
                    records_per_buf = self.lines_per_frame // 2
                    bishift_val = (
                        self._bishift[self.magnification]
                        if self.magnification < len(self._bishift) else 0
                    )
                    reshaped = data_reshape.reshape_pmt_data_bi(
                        buffer,
                        records_per_buf,
                        self.pixels_per_line,
                        self._pixel_lut_bi,
                        bishift_val,
                    )
                else:
                    # Unidirectional raw hardware mode: one record per
                    # resonant half-period (forward sweep only).
                    reshaped = data_reshape.reshape_pmt_data(
                        buffer,
                        self.lines_per_frame,
                        self.pixels_per_line,
                        self._pixel_lut,
                    )
            else:
                # Emulation / pre-shaped mode.
                reshaped = data_reshape.reshape_pmt_data_emulation(
                    buffer,
                    self.lines_per_frame,
                    self.pixels_per_line,
                )

            # Bidirectional alignment: apply bishift to backward lines.
            # Read bidirectional flag from config each frame so that a mode
            # change (AppController.set_scan_mode) takes effect immediately.
            if not self.config.get('acquisition', {}).get('unidirectional', True):
                shift = (
                    self._bishift[self.magnification]
                    if self.magnification < len(self._bishift)
                    else 0
                )
                # On the real hardware path bishift is applied in sample space
                # inside reshape_pmt_data_bi() (matching MATLAB's
                # preIdx += bishift*2), so only the line flip is needed here
                # (shift=0, flip_lines=False since reshape already reversed
                # backward lines). On the emulation path the mock delivers
                # unflipped backward lines, so both steps apply.
                flip = not (self.raw_mode and self._pixel_lut_bi is not None)
                pixel_roll = 0 if (self.raw_mode and self._pixel_lut_bi is not None) else shift
                data_reshape.apply_bidirectional_correction(
                    reshaped, pixel_roll, flip_lines=flip
                )
            
            # Write to disk, selecting only the requested channel(s).
            # ScanboxOriginalWriter.write_frame() accepts wire-format data
            # (high = dark) directly — no inversion needed here.
            if self.sbx_writer is not None:
                if self.save_channels == 0:
                    frame_to_write = reshaped[0:1]   # PMT0 only
                elif self.save_channels == 1:
                    frame_to_write = reshaped[1:2]   # PMT1 only
                else:
                    frame_to_write = reshaped        # both channels
                self.sbx_writer.write_frame(frame_to_write)
            
            # Update counters
            self.frames_acquired += 1

            if self.on_frame is not None:
                self.on_frame(self.frames_acquired)

            if self.plugin_manager is not None:
                self.plugin_manager.on_frame(self.frames_acquired - 1)
                self.plugin_manager.on_frame_data(self.frames_acquired - 1, reshaped)

            if self.on_frame_data is not None:
                self.on_frame_data(reshaped)

            # Progress update
            if self.frames_acquired % 100 == 0:
                elapsed = time.time() - self.start_time
                rate = self.frames_acquired / elapsed
                if self.frames_to_acquire == sys.maxsize:
                    print(f"Frames: {self.frames_acquired} ({rate:.1f} fps)")
                else:
                    print(f"Frames: {self.frames_acquired}/{self.frames_to_acquire} "
                          f"({rate:.1f} fps)")

    def stop(self) -> None:
        """Stop acquisition gracefully.

        Can be called from another thread or signal handler to
        stop the acquisition loop.
        """
        self.is_running = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _notify_cmd(self, direction: str, func_name: str,
                    packet_str: str = '') -> None:
        """Fire the on_command callback if one was provided.

        Args:
            direction: Short label, e.g. ``'PC \u2192 Alazar'``.
            func_name: Name of the function/operation called.
            packet_str: Optional packet or parameter description.
        """
        if self.on_command is not None:
            self.on_command(direction, func_name, packet_str)

    def _on_controller_cmd(self, com_port: str, cmd_id: int,
                           param1: int, param2: int) -> None:
        """Adapter: translate a ScanboxController serial-write event to on_command.

        Fired by ScanboxController._send_command immediately after every
        port.write(), so the logged bytes always match what was transmitted.

        Args:
            com_port: Serial port name, e.g. ``'COM3'``.
            cmd_id: Command ID byte sent.
            param1: First parameter byte sent.
            param2: Second parameter byte sent.
        """
        if self.on_command is None:
            return
        direction = f'PC \u2192 Controller ({com_port})'
        func_call = controller.ScanboxController.format_command(
            cmd_id, param1, param2
        )
        packet_str = f'[{cmd_id:02X} {param1:02X} {param2:02X}]'
        self.on_command(direction, func_call, packet_str)

    def _on_alazar_cmd(self, event: str, detail: str) -> None:
        """Adapter: translate an AlazarDigitizer event to on_command.

        Fired by AlazarDigitizer after configure(), start_acquisition(),
        and stop_acquisition().

        Args:
            event: Short event name (e.g. ``'start_acquisition'``).
            detail: Human-readable parameter string.
        """
        self._notify_cmd('PC \u2192 Alazar', event, detail)

    def _on_motor_cmd(self, com_port: str, cmd: str, cmd_type: int,
                      motor_num: int, value: int) -> None:
        """Adapter: translate a TrinamicMotor serial-write event to on_command.

        Fired by TrinamicMotor.send_command() after every port.write().
        GAP (position read) commands are silently dropped to avoid flooding
        the log at 10 Hz during normal polling.

        Args:
            com_port: Serial port name.
            cmd: TMCL command string (e.g. ``'MVP'``, ``'SAP'``, ``'GAP'``).
            cmd_type: TMCL command type parameter.
            motor_num: Motor number (0-3).
            value: 32-bit value parameter.
        """
        if cmd == 'GAP':
            return  # Routine position read — do not flood the command log.
        if self.on_command is None:
            return
        direction = f'PC \u2192 Motor ({com_port})'
        func_call = motor.TrinamicMotor.format_command(cmd, cmd_type, motor_num, value)
        self.on_command(direction, func_call, '')

    def cleanup(self) -> None:
        """Cleanup and shutdown all hardware and files.

        Stops acquisition, closes hardware connections, and finalizes
        data files.
        """
        logger.info("Cleaning up...")
        
        # Stop acquisition
        if self.alazar is not None:
            self.alazar.stop_acquisition()
            self.alazar.close()

        # Stop scanner and close controller
        if self.controller is not None:
            # Stop the TTL reader before blanking the laser so any final
            # events that arrive while the scanner is still running are
            # captured before the port is closed.
            self.controller.stop_ttl_reader()
            self.zero_pockels()          # blank laser before stopping scanner
            # On rigs with a Uniblitz driven by CMD_SHUTTER (ID 16), uncomment:
            #   self.controller.set_shutter(open=False)
            # On this rig stop_scan() (CMD_SCAN, ID 4) closes the shutter automatically.
            self.controller.stop_scan()
            if self._controller_owned:
                self.controller.close()
            else:
                # Restore the original on_command so AppController resumes
                # logging commands sent via the GUI after the scan ends.
                self.controller.on_command = self._controller_orig_on_cmd
        
        # Close motor only if Scanner created it; if it was passed in by the
        # caller (e.g. AppController) leave it open and restore the original
        # on_command callback so the GUI resumes logging motor commands.
        if self.motor is not None:
            if self._motor_owned:
                self.motor.close()
            else:
                self.motor.on_command = self._motor_orig_on_cmd
        
        # Notify plugins that acquisition has stopped so they can flush
        # and save their companion data files before the .mat is written.
        if self.plugin_manager is not None:
            self.plugin_manager.on_acquisition_stop(self.frames_acquired)

        # Close .sbx file and write companion .mat metadata.
        # extra_info is populated with the full acquisition metadata so that
        # ScanboxOriginalWriter.write_mat() embeds it in the info struct.
        if self.sbx_writer is not None:
            try:
                self.sbx_writer.extra_info = self._create_metadata()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not build metadata for .mat file: %s", exc)
            self.sbx_writer.close()
        
        print("Acquisition complete.")
        print(f"Total frames acquired: {self.frames_acquired}")

    def _create_metadata(self) -> dict:
        """Create metadata dictionary for .mat file.

        Field names mirror the original MATLAB Scanbox ``info`` struct so
        that downstream tools (Suite2p, sbxread.m, etc.) can read pyscanbox
        files without modification.  Extra pyscanbox-only fields are added
        after the MATLAB-compatible block.

        Only scalar / plain-array values are written because
        ``scipy.io.savemat`` cannot serialise nested Python dicts that
        contain ``None`` (from YAML ``null``).

        Returns:
            Dictionary with acquisition metadata.
        """
        pockels = self.controller.get_current_pockels()
        acq_cfg = self.config.get('acquisition', {})
        scanner_cfg = self.config.get('scanner', {})
        alazar_cfg  = self.config.get('alazar', {})

        # ----------------------------------------------------------------
        # channels bitmask — mirrors the original MATLAB encoding:
        #   1 = both PMT0 & PMT1,  2 = PMT0 only,  3 = PMT1 only
        # ----------------------------------------------------------------
        if self.save_channels == 0:
            channels_mask = 2       # PMT0 only
        elif self.save_channels == 1:
            channels_mask = 3       # PMT1 only
        else:
            channels_mask = 1       # both (default)
        # nchan: number of channels actually saved (used by ScanboxOriginalReader)
        nchan = 1 if self.save_channels in (0, 1) else 2

        # ----------------------------------------------------------------
        # Alazar timing parameters
        # ----------------------------------------------------------------
        unidirectional = acq_cfg.get('unidirectional', True)
        scanmode = 1 if unidirectional else 0     # 1 = unidirectional (MATLAB convention)
        # postTriggerSamples: raw ADC samples per scan line per buffer record.
        # Matches the value passed to AlazarSetRecordSize.
        post_trigger = alazar_cfg.get('samples_per_line',
                                      alazar_cfg.get('postTriggerSamples', 5000))
        # recordsPerBuffer: scan lines per DMA buffer.
        #   unidirectional: lines_per_frame
        #   bidirectional:  lines_per_frame / 2  (each buffer covers half a frame)
        records_per_buffer = (self.lines_per_frame if unidirectional
                              else self.lines_per_frame // 2)
        samples_per_buffer = post_trigger * records_per_buffer * nchan
        bytes_per_buffer   = samples_per_buffer * 2   # uint16 = 2 bytes

        # ----------------------------------------------------------------
        # TTL event arrays — mirrors MATLAB sb_timestamps() output
        # ----------------------------------------------------------------
        events = self.controller.get_ttl_events()
        if events:
            ttl_frame    = np.array([e[0] for e in events], dtype=np.int32)
            ttl_line     = np.array([e[1] for e in events], dtype=np.int32)
            ttl_event_id = np.array([e[2] for e in events], dtype=np.int32)
        else:
            ttl_frame    = np.array([], dtype=np.int32)
            ttl_line     = np.array([], dtype=np.int32)
            ttl_event_id = np.array([], dtype=np.int32)

        # ----------------------------------------------------------------
        # Objective label
        # ----------------------------------------------------------------
        obj_cfg = self.config.get('objective', {})
        objective_str = obj_cfg.get('type', '')

        # ----------------------------------------------------------------
        # Metadata dict — MATLAB-compatible fields listed first
        # ----------------------------------------------------------------
        meta = {
            # --- MATLAB info struct fields (original Scanbox) ---
            'resfreq': np.int64(scanner_cfg.get('resonant_freq', 7930)),
            'postTriggerSamples': np.int64(post_trigger),
            'recordsPerBuffer': np.int64(records_per_buffer),
            'bytesPerBuffer': np.int64(bytes_per_buffer),
            # channels bitmask: 1=both, 2=PMT0 only, 3=PMT1 only
            'channels': np.int64(channels_mask),
            'ballmotion': np.array([], dtype=np.uint8),
            'abort_bit': np.int64(0),
            'scanbox_version': np.int64(2),
            'scanmode': np.int64(scanmode),
            # sz: [lines_per_frame, pixels_per_line] — matches size(chA') in MATLAB
            'sz': np.array([[self.lines_per_frame, self.pixels_per_line]],
                           dtype=np.int64),
            'fold_lines': np.int64(0),
            'otwave':      np.array([], dtype=np.uint8),
            'otwave_um':   np.array([], dtype=np.uint8),
            'otparam':     np.array([], dtype=np.uint8),
            'otwavestyle': np.int64(1),
            'volscan': np.int64(0),
            'power_depth_link': np.int64(0),
            'opto2pow': np.array([], dtype=np.uint8),
            'area_line': np.int64(1),
            'objective': objective_str,
            'messages': np.array([], dtype=object),
            'usernotes': '',
            # nchan is derived in sbxread.m from channels bitmask; we store it
            # explicitly for direct use by ScanboxOriginalReader without re-deriving.
            'nchan': np.int64(nchan),
            # TTL event timestamps (mirrors sb_timestamps() field names)
            'frame':    ttl_frame,
            'line':     ttl_line,
            'event_id': ttl_event_id,
            # --- pyscanbox-specific fields (not in original MATLAB info) ---
            'frames': np.int64(self.frames_acquired),
            'lines_per_frame': np.int64(self.lines_per_frame),
            'pixels_per_line': np.int64(self.pixels_per_line),
            'sample_rate': np.int64(alazar_cfg.get('sample_rate', 125000000)),
            'magnification': np.int64(self.magnification),
            'pockels_base':   np.int64(pockels.get('base', 0)),
            'pockels_active': np.int64(pockels.get('active', 0)),
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'pyscanbox_version': pyscanbox.__version__,
            'objective_type': self.config.get('objective', {}).get('type', ''),
            'laser_type': self.config.get('laser', {}).get('type', ''),
        }
        if self.plugin_manager is not None:
            meta.update(self.plugin_manager.collect_metadata())
        return meta
