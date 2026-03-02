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
                 on_frame: Optional[Callable[[int], None]] = None,
                 on_frame_data=None):
        """Initialize scanner with configuration.

        Args:
            config: Configuration dictionary
            output_path: Optional output file path (excluding extension).
                If None, uses config['io']['output_directory'] and
                config['io']['file_prefix'].
            focus_mode: If True, run indefinitely without writing to disk.
                Used for live-preview (Focus button). Sets frames_to_acquire
                to sys.maxsize and skips file-writer initialisation.
            on_frame: Optional callback invoked after each acquired frame
                with the cumulative frame count as the sole argument.
                Used by ScannerThread to emit Qt signals from the loop.
            on_frame_data: Optional callback invoked after each acquired
                frame with the reshaped frame array as the sole argument
                (shape ``(channels, lines, pixels)``, dtype uint16).
                Used by ScannerThread to feed the live-preview display.
        """
        self.config = config
        self.output_path = output_path
        
        # Initialize hardware
        self.alazar = alazar.AlazarDigitizer(config)
        self.controller = controller.ScanboxController(config)
        self.motor: Optional[motor.TrinamicMotor] = None
        
        # Acquisition parameters
        self.lines_per_frame = config['acquisition']['lines_per_frame']
        self.pixels_per_line = config['acquisition']['pixels_per_line']
        self.frames_to_acquire = config['acquisition']['frames']

        # Raw-mode acquisition: use arccosine pixel LUT instead of pre-shaped data.
        # When True, each Alazar buffer contains `lines × samples_per_line × 2`
        # interleaved raw ADC samples and reshape_pmt_data_raw() is called.
        self.raw_mode: bool = config.get('alazar', {}).get('raw_mode', False)
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
        if focus_mode:
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
        
        # Open controller
        self.controller.open()
        
        # Initialize motor if configured
        if 'motor' in self.config:
            self.motor = motor.TrinamicMotor(self.config)
            self.motor.open()

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

    def setup_pockels_and_shutter(self, base_power: int = 0, 
                                  active_power: int = 100) -> None:
        """Configure Pockels cell and open shutter.

        Args:
            base_power: Base Pockels power (0-255) during flyback
            active_power: Active Pockels power (0-255) during scan
        """
        self.controller.set_pockels(base=base_power, active=active_power)
        self.controller.set_shutter(open=True)

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

            print("Configuring Pockels and shutter...")
            self.setup_pockels_and_shutter()
            
            # Start acquisition
            print("Starting acquisition...")
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
            
            # Write to disk
            if self.sbx_writer is not None:
                self.sbx_writer.write_frame(reshaped)
            
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
        
        # Close controller
        if self.controller is not None:
            self.controller.set_shutter(open=False)
            self.controller.close()
        
        # Close motor
        if self.motor is not None:
            self.motor.close()
        
        # Close file writers
        if self.sbx_writer is not None:
            self.sbx_writer.close()
        
        # Write metadata
        if self.mat_writer is not None:
            metadata = self._create_metadata()
            self.mat_writer.write(metadata)
        
        print("Acquisition complete.")
        print(f"Total frames acquired: {self.frames_acquired}")

    def _create_metadata(self) -> dict:
        """Create metadata dictionary for .mat file.

        Returns:
            Dictionary with acquisition metadata for Suite2p compatibility.
        """
        return {
            'config': self.config,
            'frames': self.frames_acquired,
            'lines_per_frame': self.lines_per_frame,
            'pixels_per_line': self.pixels_per_line,
            'sample_rate': self.config['alazar']['sample_rate'],
            'channels': self.config['alazar']['channels'],
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'pockels': self.controller.get_current_pockels(),
        }
