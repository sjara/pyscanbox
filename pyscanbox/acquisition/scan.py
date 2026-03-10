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

import sys
import time
import numpy as np
from typing import Callable, Optional
from pyscanbox.hardware import alazar
from pyscanbox.hardware import controller
from pyscanbox.hardware import motor
from pyscanbox.acquisition import reshape as data_reshape
from pyscanbox.io import sbx_writer
from pyscanbox.io import mat_writer


class Scanner:
    """Main scanner control and acquisition loop.

    This class coordinates all hardware components and manages the
    continuous acquisition loop for two-photon microscopy.

    Attributes:
        config: Configuration object
        alazar: AlazarDigitizer instance
        controller: ScanboxController instance
        motor: TrinamicMotor instance (optional)
        writer: SbxWriter instance
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
                 save_channels: int = 2):
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

        # Raw-mode acquisition: use arccosine pixel LUT instead of pre-shaped data.
        # When True, each Alazar buffer contains `lines × samples_per_line × 2`
        # interleaved raw ADC samples and reshape_pmt_data_raw() is called.
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
            data_reshape.reshape_pmt_data_raw(_dummy_buf, 1, 1, _dummy_lut)

        # Acquisition mode flags.
        self.focus_mode = focus_mode
        self.on_frame = on_frame
        self.on_frame_data = on_frame_data
        self.on_command = on_command
        self.save_channels = save_channels
        # Apply GUI override first (0 means "forever", matching MATLAB convention).
        if frames_override is not None:
            self.frames_to_acquire = frames_override
        if focus_mode or self.frames_to_acquire == 0:
            self.frames_to_acquire = sys.maxsize

        # File writers
        self.sbx_writer: Optional[sbx_writer.SbxWriter] = None
        self.mat_writer: Optional[mat_writer.MatWriter] = None
        
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

        # Initialize motor if configured
        if 'motor' in self.config:
            if self._motor_owned:
                # No pre-opened motor was supplied — create and open one.
                self.motor = motor.TrinamicMotor(
                    self.config, on_command=self._on_motor_cmd
                )
                self.motor.open()
            else:
                # Reuse the caller's already-open motor; redirect logging.
                self.motor.on_command = self._on_motor_cmd

    def initialize_writers(self) -> None:
        """Initialize file writers for data output.

        Creates .sbx and .mat file writers using configured output path.
        """
        if self.output_path is None:
            output_dir = self.config['io']['output_directory']
            file_prefix = self.config['io']['file_prefix']
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            self.output_path = f"{output_dir}/{file_prefix}_{timestamp}"
        
        self.sbx_writer = sbx_writer.SbxWriter(self.output_path)
        self.mat_writer = mat_writer.MatWriter(self.output_path)

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
            print("Initializing hardware...")
            self.initialize_hardware()

            if not self.focus_mode:
                print("Initializing file writers...")
                self.initialize_writers()

            print("Configuring Pockels to zero (safe start)...")
            self.initialize_pockels()
            # Re-apply the Pockels level the user had on the GUI slider.
            # AppController.set_pockels() stores the hw value in
            # config['laser']['pockels_active'] each time the slider moves,
            # so it is already correct even if the slider was not touched
            # since the last acquisition.
            desired_pockels = self.config.get('laser', {}).get('pockels_active', 0)
            if desired_pockels > 0:
                print(f"Restoring Pockels to hw={desired_pockels} (from slider).")
                self.controller.set_pockels(base=0, active=desired_pockels)

            print("Configuring scan parameters...")
            self.configure_scan_params()

            # Start acquisition — Pockels is at zero so no laser energy
            # reaches the sample yet; the user raises power via the GUI slider.
            # On this rig start_scan() (CMD_SCAN, ID 4) also opens the external
            # shutter automatically via the controller's LASER SHUTTER output.
            # On rigs with a Uniblitz driven by CMD_SHUTTER (ID 16), uncomment:
            #   self.controller.set_shutter(open=True)
            print("Starting acquisition...")
            self.controller.start_scan()
            self.alazar.start_acquisition()
            self.is_running = True
            self.start_time = time.time()
            
            # Main acquisition loop
            self._acquisition_loop()
            
        except KeyboardInterrupt:
            print("\nAcquisition interrupted by user.")
        except Exception as e:
            print(f"\nError during acquisition: {e}")
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
                print("Warning: Buffer timeout")
                continue
            
            # Reshape data (performance-critical!)
            if self.raw_mode and self._pixel_lut is not None:
                # Raw hardware mode: apply arccosine pixel LUT.
                reshaped = data_reshape.reshape_pmt_data_raw(
                    buffer,
                    self.lines_per_frame,
                    self.pixels_per_line,
                    self._pixel_lut,
                )
            else:
                # Emulation / pre-shaped mode.
                reshaped = data_reshape.reshape_pmt_data(
                    buffer,
                    self.lines_per_frame,
                    self.pixels_per_line,
                )
            
            # Write to disk, selecting only the requested channel(s).
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

            if self.on_frame_data is not None:
                self.on_frame_data(reshaped)

            # Progress update
            if self.frames_acquired % 100 == 0:
                elapsed = time.time() - self.start_time
                rate = self.frames_acquired / elapsed
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
        print("\nCleaning up...")
        
        # Stop acquisition
        if self.alazar is not None:
            self.alazar.stop_acquisition()
            self.alazar.close()

        # Stop scanner and close controller
        if self.controller is not None:
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
        
        # Close file writers
        if self.sbx_writer is not None:
            self.sbx_writer.close()
        
        # Write metadata
        if self.mat_writer is not None:
            try:
                metadata = self._create_metadata()
                self.mat_writer.write(metadata)
            except Exception as exc:  # noqa: BLE001
                print(f"Warning: could not write metadata .mat file: {exc}")
        
        print("Acquisition complete.")
        print(f"Total frames acquired: {self.frames_acquired}")

    def _create_metadata(self) -> dict:
        """Create metadata dictionary for .mat file.

        Only scalar / simple values are included because
        ``scipy.io.savemat`` cannot serialize nested Python dicts that
        contain ``None`` (which YAML ``null`` values become).  If the
        full config is needed it should be serialised separately (e.g.
        as JSON or YAML alongside the .mat file).

        Returns:
            Dictionary with acquisition metadata for Suite2p compatibility.
        """
        pockels = self.controller.get_current_pockels()
        # Channels actually written to disk: 1 when a single channel was
        # selected in the GUI (save_channels 0 or 1), 2 for both.
        saved_channels = 1 if self.save_channels in (0, 1) else 2
        return {
            'frames': self.frames_acquired,
            'lines_per_frame': self.lines_per_frame,
            'pixels_per_line': self.pixels_per_line,
            'sample_rate': self.config['alazar']['sample_rate'],
            'channels': saved_channels,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'pockels_base': pockels.get('base', 0),
            'pockels_active': pockels.get('active', 0),
        }
