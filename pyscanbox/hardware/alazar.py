# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

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

import sys
import ctypes
import logging

def _import_ats_enums():
    try:
        import atsbindings.enumerations as enum_module
        return enum_module
    except (OSError, RuntimeError):
        # Fallback for systems without the Alazar driver (Linux, or win32 emulation)
        # We must clean up partially loaded modules before re-importing
        for mod in list(sys.modules.keys()):
            if mod.startswith('atsbindings'):
                del sys.modules[mod]
                
        _real_cdll = ctypes.CDLL
        class _DummyFunc:
            def __call__(self, *args, **kwargs): return 0
        _dummy_func = _DummyFunc()
        class MockCDLL:
            def __init__(self, name, *args, **kwargs): pass
            def __getattr__(self, item): return _dummy_func

        ctypes.CDLL = MockCDLL
        try:
            import atsbindings.enumerations as enum_module
            return enum_module
        finally:
            ctypes.CDLL = _real_cdll

ATS_ENUM = _import_ats_enums()
import numpy as np
from typing import Tuple, Optional, List

logger = logging.getLogger(__name__)


def _get_alazar_module(use_emulation: bool):
    if use_emulation:
        from pyscanbox.emulator import mock_alazar as ats
    else:
        import atsbindings as ats
    return ats


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

    def __init__(self, config: dict, on_command=None):
        """Initialize Alazar digitizer.

        Args:
            config: Configuration dictionary with Alazar settings.
                Must contain 'alazar' key with sampling parameters.
            on_command: Optional callback fired when a key API call is made.
                Signature::

                    on_command(event: str, detail: str)

                ``event`` is a short name such as ``'configure'``,
                ``'start_acquisition'``, or ``'stop_acquisition'``.
                ``detail`` carries relevant parameter info.
        """
        self.config = config
        self.on_command = on_command
        self.sample_rate = config['alazar']['sample_rate']
        self.bits_per_sample = config['alazar']['bits_per_sample']
        self.channels = config['alazar']['channels']
        self.buffer_count = config['alazar']['buffer_count']
        
        # Raw ADC parameters (always needed for real hardware)
        self.samples_per_line = config.get('acquisition', {}).get('samples_per_line', 5000)
        self.lines_per_frame = config.get('acquisition', {}).get('lines_per_frame', 512)
        
        # AlazarTech digitizers require samplesPerRecord to be aligned
        # Typically to 64-sample boundaries for optimal DMA performance.
        #
        # In raw_mode the buffer holds one full frame of uncompressed ADC data:
        #   samples_per_buffer (per channel) = lines_per_frame × samples_per_line
        # In emulation / pre-shaped mode the buffer holds one reshaped frame:
        #   samples_per_buffer (per channel) = lines_per_frame × pixels_per_line
        # The interleaved numpy array therefore has samples_per_buffer × channels elements.
        if config.get('emulation', {}).get('raw_mode', False):
            lines = config['acquisition']['lines_per_frame']
            spl   = config.get('acquisition', {}).get('samples_per_line', 5000)
            raw_samples = lines * spl   # per-channel count
        else:
            raw_samples = config['emulation']['samples_per_buffer']
        self.samples_per_buffer = self._align_sample_count(raw_samples)

        if self.samples_per_buffer != raw_samples:
            logger.debug("Aligned buffer size from %d to %d samples",
                        raw_samples, self.samples_per_buffer)
        
        # Check if emulation is enabled
        self.use_emulation = config.get('emulation', {}).get('enabled', False)
        self.emulation_verbose = config.get('emulation', {}).get('verbose', False)
        
        # Get appropriate Alazar module (needed for DMABuffer later)
        self.alazar = _get_alazar_module(self.use_emulation)
        
        self.board_handle = None
        
        # Buffer management
        self.buffers: List[np.ndarray] = []
        self.buffer_pointers: List[ctypes.c_void_p] = []
        self._dma_buffers: List = []  # holds atsbindings.Buffer objects alive (prevents __del__ freeing pinned memory)
        self.current_buffer_index = 0
        
        # Per-record DMA parameters (set in start_acquisition)
        self._samples_per_record: int = 0
        self._records_per_buffer: int = 0
        
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

    @property
    def _use_raw_mode(self) -> bool:
        """True when real hardware is in use, or emulation is set to raw_mode=True.

        Real hardware always operates in raw ADC mode: each DMA record holds
        ``samples_per_line`` ADC samples for one resonant scan line, and
        ``lines_per_frame`` records fill one frame buffer.

        Pre-shaped emulation mode (raw_mode=False) packs a full processed
        frame into a single record for convenience, and is only used when
        ``emulation.enabled=True`` and ``emulation.raw_mode=False``.
        """
        return not self.use_emulation or self.config.get('emulation', {}).get('raw_mode', False)

    @property
    def _bytes_per_buffer(self) -> int:
        """Correct DMA buffer size in bytes based on current mode.

        Bidirectional raw mode uses different geometry than unidirectional:
        - ``records_per_buffer = lines_per_frame // 2`` (256 instead of 512)
        - ``samples_per_record = samples_per_line_bidir`` (9000 instead of 5000)
        so the buffer is ``256 × 9000 × 2 × 2 = 9,216,000 bytes``.
        """
        if self._use_raw_mode:
            unidirectional = self.config.get('acquisition', {}).get(
                'unidirectional', True
            )
            if not unidirectional:
                spl_bi = self.config.get('acquisition', {}).get(
                    'samples_per_line_bidir', 9000
                )
                records = self.lines_per_frame // 2
                return spl_bi * records * self.channels * 2
            return self.samples_per_line * self.lines_per_frame * self.channels * 2
        else:
            return self.samples_per_buffer * self.channels * 2

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

        # Configure raw acquisition mode on the mock board (no-op when
        # raw_mode=False, but always call so the mock knows samples_per_line
        # and laser parameters even in emulation mode).
        if self.use_emulation and hasattr(self.board_handle, 'set_raw_mode'):
            raw_mode         = self.config.get('emulation', {}).get('raw_mode', False)
            samples_per_line = self.config.get('acquisition', {}).get('samples_per_line', 5000)
            spl_bidir        = self.config.get('acquisition', {}).get('samples_per_line_bidir', 9000)
            laser_freq       = self.config.get('laser', {}).get('frequency', 80_180_000)
            res_freq         = self.config.get('scanner', {}).get('resonant_freq', 7930)
            self.board_handle.set_raw_mode(raw_mode, samples_per_line,
                                           laser_freq, res_freq,
                                           samples_per_line_bidir=spl_bidir)

        # Inform the mock board of the scan mode so that odd (backward) lines
        # are generated with reversed pixel order, matching real hardware.
        if self.use_emulation and hasattr(self.board_handle, 'set_scan_mode'):
            bidirectional = not self.config.get('acquisition', {}).get(
                'unidirectional', True
            )
            self.board_handle.set_scan_mode(bidirectional)

        # Let the mock board read any emulation-specific config it cares about.
        # alazar.py deliberately knows nothing about which keys are involved.
        if self.use_emulation and hasattr(self.board_handle, 'configure_from_config'):
            self.board_handle.configure_from_config(self.config)

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
        # Note: Scanbox uses EXTERNAL clock sourced from the laser sync-out
        # (~80 MHz from the Chameleon, filtered by a BBP-70+ bandpass filter).
        # Each ADC sample is thereby synchronised to one laser pulse.
        # The sample rate constant here is ignored when using external clock.
        if hasattr(self.board_handle, 'set_capture_clock'):
            self.board_handle.set_capture_clock(
                ATS_ENUM.ClockSources.FAST_EXTERNAL_CLOCK,
                ATS_ENUM.SampleRates.SAMPLE_RATE_USER_DEF, # (ignored when using external clock)
                ATS_ENUM.ClockEdges.CLOCK_EDGE_RISING,
                0     # decimation
            )
        
        # Set external clock level (required for ATS9440)
        # Reference: scanbox.m lines 771-778
        if hasattr(self.board_handle, 'set_external_clock_level'):
            self.board_handle.set_external_clock_level(65.0)  # 65% level
        
        # Configure input channels (DC coupling, input range)
        # INPUT_RANGE_PM_200_MV (0x6) for variable-gain amps (default)
        # INPUT_RANGE_PM_1_V    (0xA) for fixed-gain amps
        # MATLAB: scanbox.m lines 786-798, selected via sbconfig.pmt_amp_type
        # pyscanbox: config['pmt']['amplifier_type'] = 'variable' or 'fixed'
        pmt_amp_type = self.config.get('pmt', {}).get('amplifier_type', 'variable')
        if pmt_amp_type == 'fixed':
            input_range = ATS_ENUM.InputRanges.INPUT_RANGE_PM_1_V
        else:
            input_range = ATS_ENUM.InputRanges.INPUT_RANGE_PM_200_MV # (default)
        if hasattr(self.board_handle, 'input_control_ex'):
            # Channel A
            self.board_handle.input_control_ex(
                ATS_ENUM.Channels.CHANNEL_A,
                ATS_ENUM.Couplings.DC_COUPLING,
                input_range, # 0x6 = ±200 mV (variable) or 0xA = ±1 V (fixed)
                ATS_ENUM.Impedances.IMPEDANCE_50_OHM
            )
            # Channel B
            self.board_handle.input_control_ex(
                ATS_ENUM.Channels.CHANNEL_B,
                ATS_ENUM.Couplings.DC_COUPLING,
                input_range, # same as channel A
                ATS_ENUM.Impedances.IMPEDANCE_50_OHM
            )
        
        # Configure trigger operation (external trigger, no second engine)
        # TRIG_ENGINE_OP_J = 0 (trigger on J engine only)
        # TRIG_ENGINE_J = 0 (J engine identifier)
        # TRIG_EXTERNAL = 2 (external trigger source)
        # TRIGGER_SLOPE_POSITIVE = 1; trig_slope is an offset (0=positive, 1=negative)
        # matches MATLAB: TRIGGER_SLOPE_POSITIVE + sbconfig.trig_slope (scanbox.m line 840)
        # Second engine (K): disabled with TRIG_ENGINE_K = 1, TRIG_DISABLE = 3
        trig_level = self.config.get('alazar', {}).get('trigger_level', 160)
        trig_slope = self.config.get('alazar', {}).get('trigger_slope', 0)
        if hasattr(self.board_handle, 'set_trigger_operation'):
            self.board_handle.set_trigger_operation(
                ATS_ENUM.TriggerOperations.TRIG_ENGINE_OP_J,
                ATS_ENUM.TriggerEngines.TRIG_ENGINE_J,
                ATS_ENUM.TriggerSources.TRIG_EXTERNAL,
                ATS_ENUM.TriggerSlopes(1 + trig_slope),
                trig_level,      # 0-255; sbconfig.trig_level (default 160)
                ATS_ENUM.TriggerEngines.TRIG_ENGINE_K,
                ATS_ENUM.TriggerSources.TRIG_DISABLE,
                ATS_ENUM.TriggerSlopes.TRIGGER_SLOPE_POSITIVE,
                128              # Level (ignored for engine K)
            )
        
        # Configure external trigger input (DC coupling, TTL range)
        if hasattr(self.board_handle, 'set_external_trigger'):
            self.board_handle.set_external_trigger(
                ATS_ENUM.Couplings.DC_COUPLING,
                ATS_ENUM.ExternalTriggerRanges.ETR_TTL
            )
        
        # Set trigger delay (0 samples = no delay)
        # Reference: scanbox.m lines 853-859
        if hasattr(self.board_handle, 'set_trigger_delay'):
            self.board_handle.set_trigger_delay(0)
        
        # Set trigger timeout (0 = wait forever)
        # Reference: scanbox.m lines 861-874
        if hasattr(self.board_handle, 'set_trigger_time_out'):
            self.board_handle.set_trigger_time_out(0)
        
        # Configure LSB outputs for frame/line sync
        # LSB[0] = AUX_IN[0] (2), LSB[1] = AUX_IN[1] (3)
        self.configure_lsb_outputs(lsb0_source=2, lsb1_source=3)
        
        self.is_configured = True
        if self.on_command is not None:
            detail = (f'sample_rate={self.sample_rate}, bits={self.bits_per_sample}, '
                      f'channels={self.channels}')
            self.on_command('configure', detail)

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

        # Emulation / mock path: mock Board exposes configure_lsb directly.
        if hasattr(self.board_handle, 'configure_lsb'):
            self.board_handle.configure_lsb(lsb0_source, lsb1_source)
            return

        # Real hardware path: atsbindings.Board does not wrap
        # AlazarReadRegister / AlazarWriteRegister, so call the DLL directly.
        # This mirrors core/configureLsb9440.m exactly.
        if hasattr(self.board_handle, 'bsi') and not self.board_handle.bsi.configure_lsb:
            logger.warning('Board does not support LSB configuration; skipping.')
            return

        import atsbindings.bindings as _ats_bindings

        ats_dll = _ats_bindings.ats
        board_h = self.board_handle._handle
        password = ctypes.c_uint32(0x32145876)

        ats_dll.AlazarReadRegister.restype = ctypes.c_uint32
        ats_dll.AlazarReadRegister.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32,
        ]
        ats_dll.AlazarWriteRegister.restype = ctypes.c_uint32
        ats_dll.AlazarWriteRegister.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
        ]

        _API_SUCCESS = 512

        # REG 29 — LSB source selection:
        #   bits [13:12] = lsb0_source, bits [15:14] = lsb1_source
        reg_value = ctypes.c_uint32(0)
        ret = ats_dll.AlazarReadRegister(board_h, 29, ctypes.byref(reg_value), password)
        if ret != _API_SUCCESS:
            raise RuntimeError(f'AlazarReadRegister(29) failed with code {ret}')
        v = reg_value.value
        v = (v & ~(3 << 12)) | ((lsb0_source & 3) << 12)
        v = (v & ~(3 << 14)) | ((lsb1_source & 3) << 14)
        ret = ats_dll.AlazarWriteRegister(board_h, 29, ctypes.c_uint32(v), password)
        if ret != _API_SUCCESS:
            raise RuntimeError(f'AlazarWriteRegister(29) failed with code {ret}')

        # REG 15 — AUX_IN[1] direction: set as input (bit 27 = 1) when
        # either LSB source is 3 (AUX_IN[1]), otherwise set as output.
        reg_value = ctypes.c_uint32(0)
        ret = ats_dll.AlazarReadRegister(board_h, 15, ctypes.byref(reg_value), password)
        if ret != _API_SUCCESS:
            raise RuntimeError(f'AlazarReadRegister(15) failed with code {ret}')
        v = reg_value.value
        if lsb0_source == 3 or lsb1_source == 3:
            v |= (1 << 27)
        else:
            v &= ~(1 << 27)
        ret = ats_dll.AlazarWriteRegister(board_h, 15, ctypes.c_uint32(v), password)
        if ret != _API_SUCCESS:
            raise RuntimeError(f'AlazarWriteRegister(15) failed with code {ret}')

        logger.debug('LSB outputs configured: LSB[0]=%d, LSB[1]=%d',
                     lsb0_source, lsb1_source)

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
        self._dma_buffers.clear()
        
        # Calculate buffer size in bytes.
        # Real hardware always uses raw ADC layout:
        #   samples_per_line (per channel) × lines_per_frame × channels × 2 bytes
        # Pre-shaped emulation uses a single record per frame:
        #   samples_per_buffer (per channel) × channels × 2 bytes
        bytes_per_buffer = self._bytes_per_buffer
        
        # Allocate specified number of DMA buffers
        for i in range(self.buffer_count):
            # Use Buffer from atsbindings if available, otherwise create numpy array
            if hasattr(self.alazar, 'Buffer'):
                # Use atsbindings Buffer class for pinned memory
                # It accepts records_per_buffer and samples_per_record. We calculate these based on mode.
                unidirectional = self.config.get('acquisition', {}).get('unidirectional', True)
                if self._use_raw_mode:
                    if unidirectional:
                        recs = self.lines_per_frame
                        samps = self.samples_per_line
                    else:
                        recs = self.lines_per_frame // 2
                        samps = self.config.get('acquisition', {}).get('samples_per_line_bidir', 9000)
                else:
                    recs = 1
                    samps = self.samples_per_buffer
                    
                dma_buffer = self.alazar.Buffer(self.board_handle, self.channels, recs, samps, interleave_samples=True)
                self._dma_buffers.append(dma_buffer)  # keep object alive so __del__ does not free pinned memory prematurely
                self.buffers.append(dma_buffer.buffer.reshape(-1))
                self.buffer_pointers.append(dma_buffer.address)
            else:
                # Fall back to numpy array (emulation mode).
                # Use bytes_per_buffer to correctly handle bidirectional geometry,
                # which uses a different record layout (256 × 9000 instead of 512 × 5000).
                n_samples = bytes_per_buffer // 2  # uint16 = 2 bytes per sample
                buffer = np.empty(n_samples, dtype=np.uint16)
                self.buffers.append(buffer)
                # For emulation, store the buffer itself (mock expects numpy array)
                self.buffer_pointers.append(buffer)

    def start_acquisition(self, num_frames: Optional[int] = None) -> None:
        """Start continuous acquisition mode.

        Starts asynchronous DMA acquisition with circular buffering.
        Data must be read using read_buffer() before buffers overflow.

        Args:
            num_frames: Number of frames to acquire.  Pass ``None`` (default)
                for near-infinite acquisition (e.g. focus/live mode).

        Raises:
            RuntimeError: If board is not configured or acquisition fails.
        """
        if not self.is_configured:
            raise RuntimeError("Board not configured. Call configure() first.")
        
        if not self.buffers:
            raise RuntimeError("Buffers not allocated. Call allocate_buffers() first.")
        
        # ------------------------------------------------------------------
        # Determine per-record (per-scan-line) and per-buffer parameters.
        #
        # Unidirectional raw hardware: each DMA record = one resonant
        # half-period (forward sweep only):
        #   samplesPerRecord = samples_per_line      (e.g. 5000)
        #   recordsPerBuffer = lines_per_frame       (e.g. 512)
        #
        # Bidirectional raw hardware: ONE trigger fires per FULL resonant
        # cycle.  Each record spans the forward AND backward sweeps:
        #   samplesPerRecord = samples_per_line_bidir (e.g. 9000)
        #   recordsPerBuffer = lines_per_frame // 2   (e.g. 256)
        # Each record yields 2 output lines (one per sweep direction).
        #
        # Pre-shaped emulation packs one processed frame into a single record:
        #   samplesPerRecord = samples_per_buffer    (e.g. 407552)
        #   recordsPerBuffer = 1
        # ------------------------------------------------------------------
        if self._use_raw_mode:
            unidirectional = self.config.get('acquisition', {}).get(
                'unidirectional', True
            )
            if unidirectional:
                samples_per_record = self.samples_per_line
                records_per_buffer = self.lines_per_frame
            else:
                samples_per_record = self.config.get('acquisition', {}).get(
                    'samples_per_line_bidir', 9000
                )
                records_per_buffer = self.lines_per_frame // 2
        else:
            samples_per_record = self.samples_per_buffer
            records_per_buffer = 1

        if num_frames is not None:
            records_per_acquisition = records_per_buffer * num_frames
        else:
            records_per_acquisition = 0x7FFFFFFF  # near-infinite (focus / live mode)

        # Set record size (pre-trigger = 0, post-trigger = samples_per_record)
        # Reference: scanbox.m AlazarSetRecordSize call before AlazarBeforeAsyncRead
        if hasattr(self.board_handle, 'set_record_size'):
            self.board_handle.set_record_size(0, samples_per_record)

        # Configure acquisition mode for NPT streaming with interleaved samples.
        # Flags must match MATLAB scanbox.m line 2223:
        #   admaFlags = ADMA_EXTERNAL_STARTCAPTURE + ADMA_NPT + ADMA_INTERLEAVE_SAMPLES
        # NOTE: ADMA_CONTINUOUS_MODE (0x100) and ADMA_NPT (0x200) are mutually
        # exclusive acquisition modes — combining them causes ApiInvalidData.
        channels_mask = ATS_ENUM.Channels.CHANNEL_A.value | ATS_ENUM.Channels.CHANNEL_B.value   # CHANNEL_A | CHANNEL_B
        adma_flags = (
            ATS_ENUM.ADMAFlags.ADMA_EXTERNAL_STARTCAPTURE |
            ATS_ENUM.ADMAModes.ADMA_NPT |
            ATS_ENUM.ADMAFlags.ADMA_INTERLEAVE_SAMPLES
        )
        if hasattr(self.board_handle, 'before_async_read'):
            self.board_handle.before_async_read(
                channels_mask,          # U32: channels to acquire
                0,                      # c_long: transferOffset (no pre-trigger in NPT)
                samples_per_record,     # U32: samplesPerRecord (per channel, per line)
                records_per_buffer,     # U32: recordsPerBuffer (lines per frame)
                records_per_acquisition, # U32: recordsPerAcquisition
                adma_flags              # U32: ADMA flags
            )
        
        # Post all buffers to the board for DMA
        bytes_per_buffer = samples_per_record * records_per_buffer * self.channels * 2
        for buffer_ptr in self.buffer_pointers:
            if hasattr(self.board_handle, 'post_async_buffer'):
                self.board_handle.post_async_buffer(buffer_ptr, bytes_per_buffer)
        
        # Start the acquisition
        if hasattr(self.board_handle, 'start_capture'):
            self.board_handle.start_capture()
        
        # Persist for use by read_buffer / stop_acquisition
        self._samples_per_record = samples_per_record
        self._records_per_buffer = records_per_buffer
        self.is_acquiring = True
        if self.on_command is not None:
            detail = (
                f'samples_per_record={self._samples_per_record}, '
                f'records_per_buffer={self._records_per_buffer}, '
                f'buffers={self.buffer_count}'
            )
            self.on_command('start_acquisition', detail)


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
            if hasattr(self.board_handle, 'wait_async_buffer_complete'):
                self.board_handle.wait_async_buffer_complete(buffer_ptr, timeout_ms)
            
            # Copy data from DMA buffer (to prevent race conditions)
            data = self.buffers[buffer_index].copy()
            
            # Repost buffer for continuous acquisition
            if hasattr(self.board_handle, 'post_async_buffer'):
                bytes_per_buffer = (
                    self._samples_per_record * self._records_per_buffer * self.channels * 2
                )
                self.board_handle.post_async_buffer(buffer_ptr, bytes_per_buffer)
            
            return data
            
        except Exception as e:
            # Per AlazarTech API: after any waitAsyncBufferComplete failure
            # (timeout, buffer-not-ready, etc.) ALL pending DMA buffers are
            # still owned by the board.  The only way to reclaim them is
            # abortAsyncRead().  Do that here so the board is left in a clean
            # state and callers cannot accidentally loop on a broken session.
            logger.error("Error reading buffer: %s", e)
            try:
                if hasattr(self.board_handle, 'abort_async_read'):
                    self.board_handle.abort_async_read()
            except Exception:
                pass
            # Mirror what stop_acquisition() does so a subsequent call to it
            # (or close()) is safely a no-op.
            self.buffers.clear()
            self.buffer_pointers.clear()
            self._dma_buffers.clear()
            self.current_buffer_index = 0
            self.is_acquiring = False
            return None

    def stop_acquisition(self) -> None:
        """Stop acquisition and release DMA buffers.

        Stops the current acquisition and frees all allocated buffers.
        """
        if not self.is_acquiring:
            return
        
        # Abort the asynchronous acquisition
        if hasattr(self.board_handle, 'abort_async_read'):
            try:
                self.board_handle.abort_async_read()
            except Exception as e:
                logger.warning("Error aborting acquisition: %s", e)
        
        # Clear buffer lists. Clearing _dma_buffers drops the atsbindings.Buffer
        # references, which triggers __del__ → AlazarFreeBufferU16 in the correct order
        # (after abortAsyncRead has already stopped DMA).
        self.buffers.clear()
        self.buffer_pointers.clear()
        self._dma_buffers.clear()
        self.current_buffer_index = 0
        
        self.is_acquiring = False
        if self.on_command is not None:
            self.on_command('stop_acquisition', '')

    def set_signal_scale(self, pockels_hw: int,
                         pmt0_hw: int, pmt1_hw: int) -> None:
        """Propagate Pockels/PMT gain values to the mock board for live scaling.

        Only meaningful in emulation mode.  Normalises the 0–255 hardware
        values to [0.0, 1.0] and delegates to the mock board's
        ``set_signal_scale()`` method.  No-op on real hardware.

        Args:
            pockels_hw: Pockels active power in hardware units (0–255).
            pmt0_hw: PMT0 gain in hardware units (0–255).
            pmt1_hw: PMT1 gain in hardware units (0–255).
        """
        if not self.use_emulation:
            return
        if (self.board_handle is None
                or not hasattr(self.board_handle, 'set_signal_scale')):
            return
        self.board_handle.set_signal_scale(
            pockels_hw / 255.0,
            [pmt0_hw / 255.0, pmt1_hw / 255.0],
        )

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
