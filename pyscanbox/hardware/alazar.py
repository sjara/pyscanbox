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

def _convert_sample_rate_to_id(sample_rate_hz: int) -> int:
    """Convert sample rate in Hz to AlazarTech API constant.
    
    Args:
        sample_rate_hz: Sample rate in samples per second (Hz)
        
    Returns:
        AlazarTech API constant for the sample rate
        
    Raises:
        ValueError: If sample rate is not supported
    """
    # Mapping from Hz to AlazarTech API constants
    # Based on AlazarDefs.m and atsapi.py
    rate_map = {
        1000: 0x1,          # SAMPLE_RATE_1KSPS
        2000: 0x2,          # SAMPLE_RATE_2KSPS
        5000: 0x4,          # SAMPLE_RATE_5KSPS
        10000: 0x8,         # SAMPLE_RATE_10KSPS
        20000: 0xA,         # SAMPLE_RATE_20KSPS
        50000: 0xC,         # SAMPLE_RATE_50KSPS
        100000: 0xE,        # SAMPLE_RATE_100KSPS
        200000: 0x10,       # SAMPLE_RATE_200KSPS
        500000: 0x12,       # SAMPLE_RATE_500KSPS
        1000000: 0x14,      # SAMPLE_RATE_1MSPS
        2000000: 0x18,      # SAMPLE_RATE_2MSPS
        5000000: 0x1A,      # SAMPLE_RATE_5MSPS
        10000000: 0x1C,     # SAMPLE_RATE_10MSPS
        20000000: 0x1E,     # SAMPLE_RATE_20MSPS
        25000000: 0x21,     # SAMPLE_RATE_25MSPS
        50000000: 0x22,     # SAMPLE_RATE_50MSPS
        100000000: 0x24,    # SAMPLE_RATE_100MSPS
        125000000: 0x25,    # SAMPLE_RATE_125MSPS
        160000000: 0x26,    # SAMPLE_RATE_160MSPS
        180000000: 0x27,    # SAMPLE_RATE_180MSPS
        200000000: 0x28,    # SAMPLE_RATE_200MSPS
        250000000: 0x2B,    # SAMPLE_RATE_250MSPS
        400000000: 0x2D,    # SAMPLE_RATE_400MSPS
        500000000: 0x30,    # SAMPLE_RATE_500MSPS
        800000000: 0x32,    # SAMPLE_RATE_800MSPS
        1000000000: 0x35,   # SAMPLE_RATE_1000MSPS
        1200000000: 0x37,   # SAMPLE_RATE_1200MSPS
        1500000000: 0x3A,   # SAMPLE_RATE_1500MSPS
        1600000000: 0x3B,   # SAMPLE_RATE_1600MSPS
        1800000000: 0x3D,   # SAMPLE_RATE_1800MSPS
        2000000000: 0x3F,   # SAMPLE_RATE_2000MSPS
        2400000000: 0x6A,   # SAMPLE_RATE_2400MSPS
        3000000000: 0x75,   # SAMPLE_RATE_3000MSPS
        3600000000: 0x7B,   # SAMPLE_RATE_3600MSPS
        4000000000: 0x80,   # SAMPLE_RATE_4000MSPS
    }
    
    if sample_rate_hz not in rate_map:
        raise ValueError(
            f"Unsupported sample rate: {sample_rate_hz} Hz. "
            f"Supported rates: {list(rate_map.keys())}"
        )
    
    return rate_map[sample_rate_hz]

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
        
        # AlazarTech digitizers require samplesPerRecord to be aligned
        # Typically to 64-sample boundaries for optimal DMA performance
        raw_samples = config['alazar']['samples_per_buffer']
        self.samples_per_buffer = self._align_sample_count(raw_samples)
        
        if self.samples_per_buffer != raw_samples:
            print(f"Note: Aligned buffer size from {raw_samples} to {self.samples_per_buffer} samples")
        
        # Check if emulation is enabled
        self.use_emulation = config.get('emulation', {}).get('enabled', False)
        self.emulation_verbose = config.get('emulation', {}).get('verbose', False)
        
        # Get appropriate Alazar module (needed for DMABuffer later)
        self.alazar = _get_alazar_module(self.use_emulation)
        
        self.board_handle = None
        
        # Buffer management
        self.buffers: List[np.ndarray] = []
        self.buffer_pointers: List[ctypes.c_void_p] = []
        self.current_buffer_index = 0
        
        # Acquisition state
        self.is_configured = False
        self.is_acquiring = False

    def _align_sample_count(self, samples: int, alignment: int = 64) -> int:
        """Align sample count to required boundary.
        
        AlazarTech digitizers require samplesPerRecord to be aligned to
        specific boundaries (typically 64 samples) for optimal DMA performance.
        Also enforces a minimum size for reliable operation.
        
        Args:
            samples: Requested number of samples
            alignment: Required alignment (default 64)
            
        Returns:
            Aligned sample count (rounded up to nearest multiple of alignment)
        """
        # Enforce minimum buffer size (256 samples is typical minimum)
        min_samples = 256
        if samples < min_samples:
            samples = min_samples
            
        # Align to boundary
        return ((samples + alignment - 1) // alignment) * alignment

    def open(self) -> None:
        """Open connection to Alazar board.

        This method finds and opens a connection to the first available
        ATS9440 board in the system.

        Raises:
            RuntimeError: If no board is found or connection fails.
        """
        # Use the Alazar module stored in __init__
        # Create board instance
        self.board_handle = self.alazar.Board()

        # Configure emulation verbosity if using mock
        if self.use_emulation and hasattr(self.board_handle, 'verbose'):
            self.board_handle.verbose = self.emulation_verbose

        # Pass frame dimensions so the emulator can generate spatially
        # structured test frames rather than pure noise.
        if self.use_emulation and hasattr(self.board_handle, 'set_frame_shape'):
            lines = self.config.get('acquisition', {}).get('lines_per_frame')
            pixels = self.config.get('acquisition', {}).get('pixels_per_line')
            if lines and pixels:
                self.board_handle.set_frame_shape(lines, pixels)

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
        # Note: Scanbox uses EXTERNAL clock (from resonant scanner)
        # Sample rate is determined by external clock frequency, not this parameter
        if hasattr(self.board_handle, 'setCaptureClock'):
            self.board_handle.setCaptureClock(
                2,    # FAST_EXTERNAL_CLOCK (0x2)
                0x40, # SAMPLE_RATE_USER_DEF (ignored when using external clock)
                0,    # CLOCK_EDGE_RISING
                0     # decimation
            )
        
        # Set external clock level (required for ATS9440)
        # Reference: scanbox.m lines 771-778
        if hasattr(self.board_handle, 'setExternalClockLevel'):
            self.board_handle.setExternalClockLevel(65.0)  # 65% level
        
        # Configure input channels (DC coupling, input range)
        # Range depends on amplifier type: 200mV for variable, 1V for fixed
        # Reference: scanbox.m lines 804-827
        # CHANNEL_A = 0x1, CHANNEL_B = 0x2 (not indices 0, 1!)
        if hasattr(self.board_handle, 'inputControl'):
            # Channel A
            self.board_handle.inputControl(
                1,   # CHANNEL_A (0x1)
                2,   # DC_COUPLING (0x2)
                0x6, # INPUT_RANGE_PM_200_MV (default for variable amps)
                2    # IMPEDANCE_50_OHM (0x2)
            )
            # Channel B
            self.board_handle.inputControl(
                2,   # CHANNEL_B (0x2)
                2,   # DC_COUPLING (0x2)
                0x6, # INPUT_RANGE_PM_200_MV (default for variable amps)
                2    # IMPEDANCE_50_OHM (0x2)
            )
        
        # Configure trigger operation (external trigger, no second engine)
        # TRIG_ENGINE_OP_J = 0 (trigger on J engine only)
        # TRIG_ENGINE_J = 0 (J engine identifier)
        # TRIG_EXTERNAL = 2 (external trigger source)
        # TRIGGER_SLOPE_POSITIVE = 1 (rising edge)
        # Level: 128 (mid-range for external trigger)
        # Second engine (K): disabled with TRIG_ENGINE_K = 1, TRIG_DISABLE = 3
        if hasattr(self.board_handle, 'setTriggerOperation'):
            self.board_handle.setTriggerOperation(
                0,    # TRIG_ENGINE_OP_J
                0,    # TRIG_ENGINE_J
                2,    # TRIG_EXTERNAL
                1,    # TRIGGER_SLOPE_POSITIVE
                128,  # Mid-range level
                1,    # TRIG_ENGINE_K
                3,    # TRIG_DISABLE
                1,    # TRIGGER_SLOPE_POSITIVE (ignored)
                128   # Level (ignored)
            )
        
        # Configure external trigger input (DC coupling, TTL range)
        if hasattr(self.board_handle, 'setExternalTrigger'):
            self.board_handle.setExternalTrigger(
                2,  # DC_COUPLING
                2   # ETR_TTL
            )
        
        # Set trigger delay (0 samples = no delay)
        # Reference: scanbox.m lines 853-859
        if hasattr(self.board_handle, 'setTriggerDelay'):
            self.board_handle.setTriggerDelay(0)
        
        # Set trigger timeout (0 = wait forever)
        # Reference: scanbox.m lines 861-874
        if hasattr(self.board_handle, 'setTriggerTimeOut'):
            self.board_handle.setTriggerTimeOut(0)
        
        # Configure LSB outputs for frame/line sync
        # LSB[0] = AUX_IN[0] (2), LSB[1] = AUX_IN[1] (3)
        self.configure_lsb_outputs(lsb0_source=2, lsb1_source=3)
        
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
        if self.board_handle is None:
            raise RuntimeError("Board not opened. Call open() first.")
        
        # Use SDK's built-in configureLSB if available
        if hasattr(self.board_handle, 'configureLSB'):
            self.board_handle.configureLSB(lsb0_source, lsb1_source)
        else:
            # If not available (shouldn't happen with real hardware),
            # this would be where manual register manipulation goes
            raise NotImplementedError("configureLSB not available in this SDK version")

    def allocate_buffers(self) -> None:
        """Allocate DMA buffers for data acquisition.

        Allocates pinned (page-locked) memory buffers to prevent Python's
        garbage collector from moving arrays during DMA transfers.

        Note:
            Must use ctypes to allocate pinned memory for DMA safety.
        """
        if self.board_handle is None:
            raise RuntimeError("Board not opened. Call open() first.")
        
        # Clear any existing buffers
        self.buffers.clear()
        self.buffer_pointers.clear()
        
        # Calculate buffer size in bytes (16-bit samples, 2 channels interleaved)
        bytes_per_buffer = self.samples_per_buffer * self.channels * 2
        
        # Allocate specified number of DMA buffers
        for i in range(self.buffer_count):
            # Use DMABuffer from atsapi if available, otherwise create numpy array
            if hasattr(self.alazar, 'DMABuffer'):
                # Use SDK's DMABuffer class for pinned memory
                dma_buffer = self.alazar.DMABuffer(ctypes.c_uint16, bytes_per_buffer)
                self.buffers.append(dma_buffer.buffer)  # NumPy array view
                self.buffer_pointers.append(dma_buffer.addr)  # C pointer for posting
            else:
                # Fall back to numpy array (emulation mode)
                buffer = np.empty(self.samples_per_buffer * self.channels, dtype=np.uint16)
                self.buffers.append(buffer)
                # For emulation, store the buffer itself (mock expects numpy array)
                self.buffer_pointers.append(buffer)

    def start_acquisition(self) -> None:
        """Start continuous acquisition mode.

        Starts asynchronous DMA acquisition with circular buffering.
        Data must be read using read_buffer() before buffers overflow.

        Raises:
            RuntimeError: If board is not configured or acquisition fails.
        """
        if not self.is_configured:
            raise RuntimeError("Board not configured. Call configure() first.")
        
        if not self.buffers:
            raise RuntimeError("Buffers not allocated. Call allocate_buffers() first.")
        
        # Configure acquisition mode for NPT (No Pre-Trigger) streaming
        # Reference: AlazarTech SDK documentation for NPT mode
        # 
        # channels: bitmask for channels to acquire (CHANNEL_A=1, CHANNEL_B=2)
        # transferOffset: 0 (no pretrigger samples in NPT mode)
        # samplesPerRecord: number of samples per record (must be aligned)
        # recordsPerBuffer: 1 for NPT mode (continuous streaming)
        # recordsPerAcquisition: 0x7FFFFFFF for infinite acquisition
        # flags: ADMA_NPT | ADMA_CONTINUOUS_MODE for streaming mode
        channels_mask = 1 | 2  # CHANNEL_A | CHANNEL_B (bitmask: 3)
        if hasattr(self.board_handle, 'beforeAsyncRead'):
            self.board_handle.beforeAsyncRead(
                channels_mask,              # U32: channels to acquire
                0,                          # c_long: transferOffset (pretrigger samples)
                self.samples_per_buffer,    # U32: samplesPerRecord (aligned)
                1,                          # U32: recordsPerBuffer (1 for NPT)
                0x7FFFFFFF,                 # U32: recordsPerAcquisition (infinite)
                0x200 | 0x100               # U32: ADMA_NPT | ADMA_CONTINUOUS_MODE
            )
        
        # Post all buffers to the board for DMA
        for buffer_ptr in self.buffer_pointers:
            if hasattr(self.board_handle, 'postAsyncBuffer'):
                # Calculate buffer size in bytes
                bytes_per_buffer = self.samples_per_buffer * self.channels * 2
                self.board_handle.postAsyncBuffer(buffer_ptr, bytes_per_buffer)
        
        # Start the acquisition
        if hasattr(self.board_handle, 'startCapture'):
            self.board_handle.startCapture()
        
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
        
        # Rotate to next buffer (circular buffer management)
        buffer_index = self.current_buffer_index
        self.current_buffer_index = (self.current_buffer_index + 1) % self.buffer_count
        
        # Wait for buffer to be filled by the board
        buffer_ptr = self.buffer_pointers[buffer_index]
        try:
            if hasattr(self.board_handle, 'waitAsyncBufferComplete'):
                self.board_handle.waitAsyncBufferComplete(buffer_ptr, timeout_ms)
            
            # Copy data from DMA buffer (to prevent race conditions)
            data = self.buffers[buffer_index].copy()
            
            # Repost buffer for continuous acquisition
            if hasattr(self.board_handle, 'postAsyncBuffer'):
                bytes_per_buffer = self.samples_per_buffer * self.channels * 2
                self.board_handle.postAsyncBuffer(buffer_ptr, bytes_per_buffer)
            
            return data
            
        except Exception as e:
            # Handle timeout or other errors
            # In production, might want to be more specific about exception types
            print(f"Error reading buffer: {e}")
            return None

    def stop_acquisition(self) -> None:
        """Stop acquisition and release DMA buffers.

        Stops the current acquisition and frees all allocated buffers.
        """
        if not self.is_acquiring:
            return
        
        # Abort the asynchronous acquisition
        if hasattr(self.board_handle, 'abortAsyncRead'):
            try:
                self.board_handle.abortAsyncRead()
            except Exception as e:
                print(f"Warning: Error aborting acquisition: {e}")
        
        # Clear buffer lists (actual memory cleanup handled by garbage collector
        # or SDK's DMABuffer.__exit__ when objects are destroyed)
        self.buffers.clear()
        self.buffer_pointers.clear()
        self.current_buffer_index = 0
        
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
