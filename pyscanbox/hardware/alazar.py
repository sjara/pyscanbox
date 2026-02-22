"""AlazarTech digitizer interface for PMT data acquisition.

This module provides a Python interface to the AlazarTech ATS9440 digitizer
for high-speed PMT data acquisition (~500 MB/s @ 125 MS/s, 14-bit, 2-channel).

Reference:
    Original MATLAB implementation: core/scanbox.m, core/configureLsb9440.m

Example:
    >>> import pyscanbox.hardware.alazar
    >>> digitizer = pyscanbox.hardware.alazar.AlazarDigitizer(config)
    >>> digitizer.configure()
    >>> digitizer.start_acquisition()
"""

import ctypes
import numpy as np
from typing import Tuple, Optional, List


def _get_alazar_module(use_emulation: bool):
    """Get appropriate Alazar module based on emulation setting.
    
    Priority order:
        1. If emulation enabled: use mock_alazar
        2. Try system-installed atsapi (from AlazarTech SDK)
        3. Fall back to vendored atsapi (development)
        4. Raise error if neither available
    
    Args:
        use_emulation: If True, use mock Alazar
        
    Returns:
        Alazar module (either atsapi or mock_alazar)
        
    Raises:
        ImportError: If atsapi not available and not in emulation mode
    """
    if use_emulation:
        from pyscanbox.emulator import mock_alazar
        return mock_alazar
    
    # Try system-installed atsapi first (production)
    try:
        import atsapi
        return atsapi
    except ImportError:
        pass
    
    # Fall back to vendored copy (development)
    try:
        from pyscanbox.vendor.alazar import atsapi
        return atsapi
    except ImportError:
        pass
    
    # Neither available
    raise ImportError(
        "AlazarTech API (atsapi.py) not found. "
        "Please install AlazarTech SDK or place atsapi.py in "
        "pyscanbox/vendor/alazar/ for development."
    )


class AlazarDigitizer:
    """Interface to AlazarTech ATS9440 digitizer.

    This class wraps the AlazarTech API for high-speed data acquisition
    from PMTs. It handles configuration, DMA buffer management, and
    continuous streaming acquisition.

    Attributes:
        board_handle: Handle to the Alazar board
        sample_rate: Sampling rate in samples per second
        bits_per_sample: Bit depth (14 for ATS9440)
        channels: Number of channels to acquire
        buffer_count: Number of DMA buffers for circular buffering
        samples_per_buffer: Samples per DMA buffer
    """

    def __init__(self, config: dict):
        """Initialize Alazar digitizer.

        Args:
            config: Configuration dictionary with Alazar settings.
                Must contain 'alazar' key with sampling parameters.
        """
        self.config = config
        self.sample_rate = config['alazar']['sample_rate']
        self.bits_per_sample = config['alazar']['bits_per_sample']
        self.channels = config['alazar']['channels']
        self.buffer_count = config['alazar']['buffer_count']
        self.samples_per_buffer = config['alazar']['samples_per_buffer']
        
        # Check if emulation is enabled
        self.use_emulation = config.get('emulation', {}).get('enabled', False)
        self.emulation_verbose = config.get('emulation', {}).get('verbose', False)
        
        self.board_handle = None
        
        # Buffer management
        self.buffers: List[np.ndarray] = []
        self.buffer_pointers: List[ctypes.c_void_p] = []
        
        # Acquisition state
        self.is_configured = False
        self.is_acquiring = False

    def open(self) -> None:
        """Open connection to Alazar board.

        This method finds and opens a connection to the first available
        ATS9440 board in the system.

        Raises:
            RuntimeError: If no board is found or connection fails.
        """
        # Get appropriate Alazar module
        alazar_module = _get_alazar_module(self.use_emulation)
        
        # Create board instance
        self.board_handle = alazar_module.Board()
        
        # Configure emulation verbosity if using mock
        if self.use_emulation and hasattr(self.board_handle, 'verbose'):
            self.board_handle.verbose = self.emulation_verbose

    def configure(self) -> None:
        """Configure Alazar board for PMT acquisition.

        Configures clock, trigger, input channels, and LSB output settings
        according to Scanbox specifications.

        Reference:
            See core/configureLsb9440.m for register configuration details.

        Raises:
            RuntimeError: If configuration fails.
        """
        if self.board_handle is None:
            raise RuntimeError("Board not opened. Call open() first.")
        
        # Configure clock source and sample rate
        if hasattr(self.board_handle, 'setCaptureClock'):
            self.board_handle.setCaptureClock(
                source=1,  # INTERNAL_CLOCK
                sample_rate=self.sample_rate,
                edge=0,  # CLOCK_EDGE_RISING
                decimation=0
            )
        
        # Configure input channels (AC coupling, input range)
        if hasattr(self.board_handle, 'inputControl'):
            for channel in range(self.channels):
                self.board_handle.inputControl(
                    channel=channel,
                    coupling=2,  # AC_COUPLING
                    input_range=7,  # INPUT_RANGE_PM_400_MV
                    impedance=2  # IMPEDANCE_50_OHM
                )
        
        # Configure trigger (external, rising edge)
        # TODO: Implement trigger configuration when needed
        
        # Configure LSB outputs for frame/line sync
        if hasattr(self.board_handle, 'configureLSB'):
            self.board_handle.configureLSB(lsb0_source=2, lsb1_source=3)
        
        self.is_configured = True

    def configure_lsb_outputs(self, lsb0_source: int, lsb1_source: int) -> None:
        """Configure LSB output bits for frame/line synchronization.

        The LSB bits on the ATS9440 can be set to output various signals.
        This is used to embed frame and line timing information in the
        data stream.

        Args:
            lsb0_source: Source for LSB[0] (0=low, 1=ext_trig, 2=aux0, 3=aux1)
            lsb1_source: Source for LSB[1] (0=low, 1=ext_trig, 2=aux0, 3=aux1)

        Reference:
            See core/configureLsb9440.m for implementation details.
        """
        # TODO: Read register 29
        # TODO: Set LSB[0] source (bits 13:12)
        # TODO: Set LSB[1] source (bits 15:14)
        # TODO: Write register 29
        # TODO: Configure AUX_IN_1 as input if needed (register 15, bit 27)
        raise NotImplementedError("LSB configuration pending")

    def allocate_buffers(self) -> None:
        """Allocate DMA buffers for data acquisition.

        Allocates pinned (page-locked) memory buffers to prevent Python's
        garbage collector from moving arrays during DMA transfers.

        Note:
            Must use ctypes to allocate pinned memory for DMA safety.
        """
        bytes_per_buffer = self.samples_per_buffer * 2  # 16-bit samples
        
        for i in range(self.buffer_count):
            # TODO: Allocate pinned memory using ctypes
            # buffer = np.empty(self.samples_per_buffer, dtype=np.uint16)
            # self.buffers.append(buffer)
            pass

    def start_acquisition(self) -> None:
        """Start continuous acquisition mode.

        Starts asynchronous DMA acquisition with circular buffering.
        Data must be read using read_buffer() before buffers overflow.

        Raises:
            RuntimeError: If board is not configured or acquisition fails.
        """
        if not self.is_configured:
            raise RuntimeError("Board not configured. Call configure() first.")
        
        # TODO: Post DMA buffers to board
        # TODO: Start acquisition (AlazarStartCapture)
        
        self.is_acquiring = True

    def read_buffer(self, timeout_ms: int = 5000) -> Optional[np.ndarray]:
        """Read one buffer of acquired data.

        Blocks until a buffer is available or timeout expires.

        Args:
            timeout_ms: Timeout in milliseconds.

        Returns:
            NumPy array of uint16 samples, or None if timeout.

        Raises:
            RuntimeError: If acquisition is not running.
        """
        if not self.is_acquiring:
            raise RuntimeError("Acquisition not started.")
        
        # TODO: Wait for buffer (AlazarWaitAsyncBufferComplete)
        # TODO: Return buffer data
        # TODO: Repost buffer to board
        
        return None

    def stop_acquisition(self) -> None:
        """Stop acquisition and release DMA buffers.

        Stops the current acquisition and frees all allocated buffers.
        """
        if not self.is_acquiring:
            return
        
        # TODO: Abort acquisition (AlazarAbortAsyncRead)
        # TODO: Free DMA buffers
        
        self.is_acquiring = False

    def close(self) -> None:
        """Close connection to Alazar board and cleanup resources."""
        if self.is_acquiring:
            self.stop_acquisition()
        
        # TODO: Close board handle
        self.board_handle = None

    def get_samples_per_second(self) -> float:
        """Get actual samples per second for this configuration.

        Returns:
            Samples per second (total across all channels).
        """
        return self.sample_rate * self.channels
