"""Mock AlazarTech digitizer for emulation.

This module provides a mock implementation of the AlazarTech ATS9440 digitizer
for Linux/offline development. It generates synthetic 14-bit PMT data and
mimics the atsbindings interface.

Example:
    >>> import pyscanbox.emulator.mock_alazar as mock_alazar
    >>> board = mock_alazar.Board()
    >>> board.setCaptureClock(...)
    >>> # Start acquisition and receive synthetic data
"""

import numpy as np
import time
import threading
import logging
from typing import Optional, List, Union


logger = logging.getLogger(__name__)

# Background 14-bit value representing the dark state (no laser / no gain).
# Matches the baseline baked into the pre-computed test frames so that
# scaling to 0 produces a perfectly flat output.
_SIGNAL_BASELINE_14BIT = 16383

# Minimum effective signal scale applied even when pockels=0 and pmt_gain=0.
# At this fraction of full scale the image looks like the real rig at roughly
# half Pockels / half PMT — enough to see dark features on a dark background
# without having to touch any sliders immediately after opening the GUI.
_AMBIENT_SCALE = 0.25

# Standard deviation of the per-pixel Gaussian background noise added to
# every pre-computed test frame (14-bit units, full scale = 16383).
# Increase this to make the histogram broader; decrease for a sharper peak.
_BACKGROUND_NOISE_SIGMA = 2000


class Board:
    """Mock AlazarTech board interface.

    Emulates the atsbindings Python API for development without
    hardware. Generates synthetic 14-bit data streams.

    Attributes:
        board_id: Board identifier (1-based)
        is_configured: Configuration state
        is_acquiring: Acquisition state
        sample_rate: Configured sample rate
        channels: Number of channels
        bits_per_sample: Bit depth (14 for ATS9440)
    """

    def __init__(self, system_id: int = 1, board_id: int = 1):
        """Initialize mock Alazar board.

        Args:
            system_id: System ID (default 1)
            board_id: Board ID (default 1)
        """
        self.system_id = system_id
        self.board_id = board_id
        self.is_configured = False
        self.is_acquiring = False

        # Configuration parameters
        self.sample_rate = 125_000_000  # 125 MS/s
        self.channels = 2
        self.bits_per_sample = 14
        self.input_range = 400  # 400 mV

        # Buffer management
        self.buffer_size_samples = 2048
        self.buffers_per_acquisition = 4
        self.posted_buffers: List[np.ndarray] = []
        self.completed_buffers: List[np.ndarray] = []
        self.buffer_lock = threading.Lock()

        # Data generation parameters (inverted PMT: high = dark, low = bright)
        self.noise_level = 200  # RMS noise level (14-bit scale)
        self.dc_offset = 16383  # Full-dark baseline (inverted PMT signal)
        self.frame_sync_enabled = True

        # Signal scaling: simulate effect of Pockels cell power and PMT gain.
        # pockels_level and each pmt_gains entry are normalised to [0.0, 1.0].
        # At 0.0 the emulator outputs a flat dark field; at 1.0 the
        # pre-computed test frames are emitted unmodified.
        self.pockels_level: float = 0.0
        self.pmt_gains: list = [0.0, 0.0]

        # Frame-aware synthetic data.  Set via set_frame_shape() before
        # startCapture() to enable realistic test frames instead of noise.
        self.frame_shape: tuple | None = None   # (lines_per_frame, pixels_per_line)
        self._test_frames: list | None = None   # list of packed uint16 arrays
        self._frame_idx: int = 0
        self._sample_pos: int = 0  # current position within the current test frame
        self._n_test_frames: int = 4

        # Raw hardware mode: generate pre-warped data at real buffer sizes.
        # Set via set_raw_mode() after set_frame_shape().
        self.raw_mode: bool = False
        self.samples_per_line: int = 5000       # postTriggerSamples unidirectional
        self.samples_per_line_bidir: int = 9000  # postTriggerSamples bidirectional
        self._pixel_lut: np.ndarray | None = None     # (pixels,) int32, unidirectional
        self._pixel_lut_bi: np.ndarray | None = None  # (pixels+n_bwd,) int32, bidir

        # Bidirectional scan mode: odd lines are acquired right-to-left.
        # When True, _prepare_test_frames*() uses the bidir buffer layout
        # (records_per_frame = lines//2, samples_per_record = samples_per_line_bidir).
        self.bidirectional: bool = False

        logger.info(f"Mock Alazar board initialized: System {system_id}, Board {board_id}")

    def set_capture_clock(self, source: int, rate: int,
                       edge: int = 0, decimation: int = 0) -> int:
        """Configure capture clock.

        Args:
            source: Clock source
            rate: Sample rate code (API constant) or actual frequency in Hz.
                When source indicates an external clock (FAST_EXTERNAL_CLOCK=2
                etc.) the rate may be the placeholder SAMPLE_RATE_USER_DEF
                constant (0x40 = 64), which is NOT a real frequency.
                In that case we keep the internal simulation rate unchanged.
            edge: Clock edge (0 = rising)
            decimation: Decimation factor

        Returns:
            Status code (512 = success)
        """
        # Only treat 'rate' as an actual sample frequency when it looks like
        # one (> 1 kHz).  API placeholder constants (e.g. SAMPLE_RATE_USER_DEF
        # = 0x40 = 64) are tiny integers and would cause the generation thread
        # to sleep for hours if used for timing.
        if getattr(rate, "value", rate) > 1000:
            self.sample_rate = getattr(rate, "value", rate)
        # else: external-clock mode — keep the default 125 MS/s for timing
        logger.debug(f"Clock configured: source={getattr(source, 'name', source)}, rate={getattr(rate, 'name', rate)}, "
                     f"effective_sample_rate={self.sample_rate}")
        return 512  # ApiSuccess

    def input_control_ex(self, channel: int, coupling: int, inputRange: int,
                    impedance: int) -> int:
        """Configure input channel.

        Args:
            channel: Channel ID
            coupling: Coupling mode
            inputRange: Input range code
            impedance: Input impedance

        Returns:
            Status code (512 = success)
        """
        self.input_range = inputRange
        logger.debug(f"Channel {channel} configured")
        return 512

    def set_trigger_operation(self, operation: int, engine1: int, source1: int,
                           slope1: int, level1: int, engine2: int,
                           source2: int, slope2: int, level2: int) -> None:
        """Configure trigger operation.

        Args:
            operation: Trigger operation mode
            engine1-2: Engine parameters
            source1-2: Trigger sources
            slope1-2: Trigger slopes
            level1-2: Trigger levels
        """
        logger.debug("Trigger configured")

    def set_external_trigger(self, coupling: int, range: int) -> None:
        """Configure external trigger.

        Args:
            coupling: Coupling mode
            range: Input range
        """
        logger.debug("External trigger configured")

    def configure_lsb(self, valueLSB0: int, valueLSB1: int) -> None:
        """Configure LSB output bits embedded in the data stream.

        In Scanbox, called as configureLsb9440(boardHandle, 0, 3):
        LSB[0] = 0 (disabled/always zero) and LSB[1] = AUX_IN[1]
        (external TTL event signal).

        Args:
            valueLSB0: Source for LSB[0] (0=low, 1=ext_trig, 2=AUX_IN[0], 3=AUX_IN[1])
            valueLSB1: Source for LSB[1] (0=low, 1=ext_trig, 2=AUX_IN[0], 3=AUX_IN[1])
        """
        logger.debug(f"LSB configured: LSB0={valueLSB0}, LSB1={valueLSB1}")
        self.is_configured = True

    def set_frame_shape(self, lines_per_frame: int, pixels_per_line: int) -> None:
        """Tell the mock board the frame dimensions for realistic data generation.

        Must be called before startCapture().  When set, _generate_synthetic_frame
        produces pre-computed Gaussian-spot test frames (simulating labelled
        neurons) that cycle during the acquisition, making the live-preview
        display meaningful for visual tuning.

        Args:
            lines_per_frame: Number of scan lines per frame.
            pixels_per_line: Number of pixels per scan line.
        """
        self.frame_shape = (lines_per_frame, pixels_per_line)
        self._test_frames = None   # will be built lazily by _prepare_test_frames()
        self._frame_idx = 0
        self._sample_pos = 0
        logger.info("Mock Alazar frame shape set to %d x %d", lines_per_frame, pixels_per_line)

    def set_raw_mode(self, raw_mode: bool, samples_per_line: int,
                     laser_freq: float, res_freq: float,
                     samples_per_line_bidir: int = 9000) -> None:
        """Configure raw acquisition mode to match real hardware buffer layout.

        When ``raw_mode=True``, unidirectional buffers contain
        ``lines_per_frame × samples_per_line × 2`` interleaved uint16 raw ADC
        samples; bidirectional buffers contain
        ``(lines_per_frame // 2) × samples_per_line_bidir × 2`` samples (one
        record per full resonant cycle covering both sweeps).

        Must be called **after** ``set_frame_shape()`` and **before**
        ``startCapture()``.

        Args:
            raw_mode: ``True`` to generate raw-format buffers.
            samples_per_line: Raw ADC samples per forward scan line (e.g. 5000).
            laser_freq: Laser repetition frequency in Hz (e.g. 80_180_000).
            res_freq: Resonant mirror frequency in Hz (e.g. 7930).
            samples_per_line_bidir: Raw ADC samples per full resonant cycle
                (forward + backward), used when bidirectional=True (e.g. 9000).
        """
        self.raw_mode = raw_mode
        self.samples_per_line = samples_per_line
        self.samples_per_line_bidir = samples_per_line_bidir
        self._test_frames = None   # force regeneration on next call

        if raw_mode and self.frame_shape is not None:
            from pyscanbox.acquisition.reshape import compute_pixel_lut, compute_pixel_lut_bi
            pixels = self.frame_shape[1]
            self._pixel_lut = compute_pixel_lut(pixels, laser_freq, res_freq)
            self._pixel_lut_bi = compute_pixel_lut_bi(
                pixels, laser_freq, res_freq,
                bidir_samples=samples_per_line_bidir,
            )
            lines = self.frame_shape[0]
            if self.bidirectional:
                self.buffer_size_samples = (lines // 2) * samples_per_line_bidir * 2
            else:
                self.buffer_size_samples = lines * samples_per_line * 2
            # Pre-compute test frames now so the generation thread doesn't stall
            # on the first buffer request.
            self._prepare_test_frames_raw()
            logger.info(
                "Mock Alazar raw mode enabled: buffer_size_samples=%d",
                self.buffer_size_samples,
            )
        else:
            self._pixel_lut = None
            self._pixel_lut_bi = None
            # Re-compute shaped test frames if frame_shape is already known,
            # so a switch back to non-raw mode is reflected immediately.
            if not raw_mode and self.frame_shape is not None:
                self._prepare_test_frames()

        logger.info(
            "Mock Alazar raw mode %s (samples_per_line=%d, samples_per_line_bidir=%d)",
            "enabled" if raw_mode else "disabled",
            samples_per_line,
            samples_per_line_bidir,
        )

    def set_scan_mode(self, bidirectional: bool) -> None:
        """Configure bidirectional scan mode for test frame generation.

        In bidirectional mode each DMA record spans a full resonant cycle
        (``samples_per_line_bidir`` samples) and the frame has
        ``lines_per_frame // 2`` records — a different buffer geometry from
        unidirectional mode.  Updating this flag recalculates
        ``buffer_size_samples`` so that ``_generate_synthetic_frame`` slices
        the correct number of samples and the pre-allocated DMA buffers match.

        Must be called before ``startCapture()``.

        Args:
            bidirectional: True to simulate bidirectional hardware output;
                False (default) for unidirectional output.
        """
        if self.bidirectional != bidirectional:
            self.bidirectional = bidirectional
            self._test_frames = None  # force regeneration on next call
            if self.raw_mode and self.frame_shape is not None:
                lines = self.frame_shape[0]
                if bidirectional:
                    self.buffer_size_samples = (
                        (lines // 2) * self.samples_per_line_bidir * 2
                    )
                else:
                    self.buffer_size_samples = lines * self.samples_per_line * 2
        logger.info(
            "Mock Alazar scan mode: %s",
            "bidirectional" if bidirectional else "unidirectional",
        )

    def before_async_read(self, channels: int, transferOffset: int,
                       samplesPerRecord: int, recordsPerBuffer: int,
                       recordsPerAcquisition: int, flags: int) -> None:
        """Setup asynchronous acquisition.

        Args:
            channels: Channel mask (bit 0 = Ch A, bit 1 = Ch B)
            transferOffset: Transfer offset in samples
            samplesPerRecord: Samples per record PER CHANNEL
            recordsPerBuffer: Records per buffer
            recordsPerAcquisition: Total records (or infinite)
            flags: Configuration flags
        """
        # Count active channels from bitmask
        num_channels = bin(channels).count('1')
        
        # In interleaved mode, buffer size = samplesPerRecord * channels * recordsPerBuffer
        self.buffer_size_samples = samplesPerRecord * num_channels * recordsPerBuffer
        logger.debug(f"Async read configured: {self.buffer_size_samples} samples/buffer ({num_channels} channels interleaved)")

    def post_async_buffer(self, buffer: np.ndarray, bufferLength: Optional[int] = None) -> None:
        """Post buffer for DMA.

        Args:
            buffer: NumPy array or pointer to fill with data
            bufferLength: Buffer length in bytes (optional for numpy arrays)
        """
        with self.buffer_lock:
            self.posted_buffers.append(buffer)

    def start_capture(self) -> None:
        """Start data acquisition."""
        self.is_acquiring = True
        logger.info("Mock acquisition started")

        # Start background thread to generate data
        self._generation_thread = threading.Thread(
            target=self._generate_data_loop,
            daemon=True
        )
        self._generation_thread.start()

    def wait_async_buffer_complete(self, buffer: np.ndarray,
                               timeout_ms: int = 5000) -> None:
        """Wait for buffer to be filled with data.

        Args:
            buffer: Buffer to wait for
            timeout_ms: Timeout in milliseconds
            
        Raises:
            Exception: If timeout occurs (matching atsbindings behavior)
        """
        start_time = time.time()
        timeout_sec = timeout_ms / 1000.0

        while self.is_acquiring:
            with self.buffer_lock:
                if len(self.completed_buffers) > 0:
                    # Fill buffer with generated data
                    data = self.completed_buffers.pop(0)
                    np.copyto(buffer, data)
                    return  # Success

            # Check timeout
            if time.time() - start_time > timeout_sec:
                logger.warning("Buffer wait timeout")
                raise Exception(f"Timeout waiting for buffer (code {ApiWaitTimeout})")

            time.sleep(0.001)  # 1ms sleep

        # Acquisition stopped
        raise Exception(f"Acquisition aborted (code {ApiWaitTimeout})")

    def abort_async_read(self) -> None:
        """Abort asynchronous acquisition."""
        self.is_acquiring = False
        logger.info("Mock acquisition aborted")

    def _generate_data_loop(self) -> None:
        """Background thread to generate synthetic data.

        Generates 14-bit PMT data and fills buffers continuously.
        """
        buffer_interval = self.buffer_size_samples / self.sample_rate

        while self.is_acquiring:
            # Generate synthetic 14-bit data
            data = self._generate_synthetic_frame()

            # Add to completed buffers
            with self.buffer_lock:
                if len(self.posted_buffers) > 0:
                    # Use pre-allocated buffer if available
                    buffer = self.posted_buffers.pop(0)
                    np.copyto(buffer, data)
                    self.completed_buffers.append(buffer)
                else:
                    # Create new buffer
                    self.completed_buffers.append(data)

            # Simulate acquisition timing
            time.sleep(buffer_interval * 0.9)  # 90% of real time

    def _generate_synthetic_frame(self) -> np.ndarray:
        """Generate one buffer of synthetic PMT data.

        When set_frame_shape() has been called, slices ``buffer_size_samples``
        samples from the pre-generated test-frame bank, advancing a position
        pointer so successive calls stream through the frames continuously.
        Each returned buffer has exactly ``buffer_size_samples`` samples, so
        it fits the pre-allocated DMA buffer regardless of whether
        ``buffer_size_samples`` equals a full frame or a small DMA chunk.

        When frame_shape is unknown, falls back to Gaussian noise.

        Returns:
            Array of exactly ``buffer_size_samples`` uint16 values in Alazar
            wire format (14-bit PMT data left-shifted by 2, channels A and B
            interleaved).
        """
        if self.frame_shape is not None:
            if self._test_frames is None:
                if self.raw_mode:
                    self._prepare_test_frames_raw()
                else:
                    self._prepare_test_frames()

            n = self.buffer_size_samples
            frame = self._test_frames[self._frame_idx % self._n_test_frames]
            frame_len = len(frame)
            start = self._sample_pos
            end = start + n

            if end <= frame_len:
                buf = frame[start:end].copy()
                self._sample_pos = end
                if self._sample_pos >= frame_len:
                    # Finished this test frame — advance to the next.
                    self._frame_idx += 1
                    self._sample_pos = 0
            else:
                # Wrap: take the tail of this frame, then the head of the next.
                part1 = frame[start:].copy()
                self._frame_idx += 1
                self._sample_pos = 0
                next_frame = self._test_frames[self._frame_idx % self._n_test_frames]
                needed = n - len(part1)
                part2 = next_frame[:needed].copy()
                buf = np.concatenate([part1, part2])
                self._sample_pos = needed

            return self._apply_signal_scale(buf)

        # --- Fallback: pure noise (no frame shape set) ---
        # Apply the same ambient floor as _apply_signal_scale so that the
        # fallback path is consistent with the framed path.
        pmt_max = max(self.pmt_gains[0], self.pmt_gains[1])
        raw_scale = self.pockels_level * pmt_max
        effective_scale = _AMBIENT_SCALE + (1.0 - _AMBIENT_SCALE) * raw_scale
        effective_noise = max(1, round(self.noise_level * effective_scale))
        noise = np.random.normal(
            _SIGNAL_BASELINE_14BIT,
            effective_noise,
            self.buffer_size_samples
        ).astype(np.int32)
        noise = np.clip(noise, 0, 16383)
        return (noise << 2).astype(np.uint16)

    def set_signal_scale(self, pockels_level: float,
                         pmt_gains: list) -> None:
        """Update Pockels and PMT gain levels used for live signal scaling.

        Takes effect on the very next buffer without regenerating the
        pre-computed test frames.  Call this whenever the GUI Pockels or
        PMT gain controls change so the emulated image responds in real time.

        Args:
            pockels_level: Normalised laser power (0.0 = off, 1.0 = maximum).
            pmt_gains: Two-element list [pmt0_gain, pmt1_gain], each 0.0–1.0.
        """
        self.pockels_level = float(np.clip(pockels_level, 0.0, 1.0))
        self.pmt_gains = [
            float(np.clip(pmt_gains[0], 0.0, 1.0)),
            float(np.clip(pmt_gains[1], 0.0, 1.0)),
        ]
        logger.debug(
            "Mock Alazar signal scale: pockels=%.3f pmt=[%.3f, %.3f]",
            self.pockels_level, self.pmt_gains[0], self.pmt_gains[1],
        )

    def _apply_signal_scale(self, buf: np.ndarray) -> np.ndarray:
        """Scale the fluorescence dip in a wire-format buffer.

        The pre-computed frames represent maximum-signal data.  This method
        blends each buffer back toward the flat dark baseline according to
        the current ``pockels_level`` and ``pmt_gains``, so that lower
        laser power or PMT gain visibly reduces image brightness.

        Channels are scaled independently: even-indexed samples are PMT0,
        odd-indexed samples are PMT1.

        Args:
            buf: Wire-format uint16 array (interleaved ch0/ch1, 14-bit values
                left-shifted by 2, frame-sync bits in the two LSBs of
                sample 0).

        Returns:
            Scaled uint16 array of the same length.
        """
        BASELINE = _SIGNAL_BASELINE_14BIT << 2  # in wire units (4 × 14-bit)

        # Mix the raw pockels*pmt product with the ambient floor so that even
        # at (pockels=0, pmt=0) the image shows _AMBIENT_SCALE of full signal.
        raw_ch0 = self.pockels_level * self.pmt_gains[0]
        raw_ch1 = self.pockels_level * self.pmt_gains[1]
        ch0_scale = _AMBIENT_SCALE + (1.0 - _AMBIENT_SCALE) * raw_ch0
        ch1_scale = _AMBIENT_SCALE + (1.0 - _AMBIENT_SCALE) * raw_ch1

        data = buf.astype(np.int32)
        sync_bits = data & 3
        data_bits = data & ~3  # isolate the 14-bit value (bits 15:2)

        # dip > 0 where there is signal (low ADC = bright fluorescence dip)
        dip_ch0 = BASELINE - data_bits[0::2]
        dip_ch1 = BASELINE - data_bits[1::2]
        result = data_bits.copy()
        result[0::2] = BASELINE - np.round(dip_ch0 * ch0_scale).astype(np.int32)
        result[1::2] = BASELINE - np.round(dip_ch1 * ch1_scale).astype(np.int32)
        result = np.clip(result, 0, 65532) & ~3  # stay within 14-bit wire range
        result |= sync_bits
        return result.astype(np.uint16)

    def _prepare_test_frames(self) -> None:
        """Pre-compute a bank of synthetic test frames.

        Generates self._n_test_frames frames, each containing ~15 Gaussian
        spots (simulated neurons) whose intensities vary sinusoidally across
        the frame bank — mimicking calcium fluorescence dynamics.  Both
        channels are generated with the same signal magnitude so the two
        display colormaps can be tuned for equal apparent brightness.

        The results are stored as Alazar wire-format buffers in self._test_frames
        (interleaved channels, values left-shifted by 2 into bits 15:2).

        Note: PMT signals are inverted - high values = no light (dark),
        low values = bright signal. Neurons appear as dips below baseline.
        """
        lines, pixels = self.frame_shape
        n = self._n_test_frames
        rng = np.random.default_rng(42)   # fixed seed → reproducible layout

        # --- Fixed neuron positions and signal strengths ---
        n_neurons = 15
        ny = rng.integers(2, max(3, lines  - 2), n_neurons).astype(np.float32)
        nx = rng.integers(2, max(3, pixels - 2), n_neurons).astype(np.float32)
        # Signal strength: how much the signal dips below baseline (inverted PMT)
        signal_strength = rng.uniform(8000, 16383, n_neurons).astype(np.float32)  
        sigma = rng.uniform(8, 20, n_neurons).astype(np.float32)       # px

        # 1-D coordinate arrays for outer-product Gaussian computation.
        yy = np.arange(lines,  dtype=np.float32)   # (lines,)
        xx = np.arange(pixels, dtype=np.float32)   # (pixels,)

        frames = []
        for f in range(n):
            # Start with full-dark baseline (inverted PMT: high = dark)
            imgs = np.full((2, lines, pixels), 16383.0, dtype=np.float32)
            imgs += rng.normal(0, _BACKGROUND_NOISE_SIGMA, imgs.shape).astype(np.float32)

            for i in range(n_neurons):
                dy2 = (yy - ny[i]) ** 2           # (lines,)
                dx2 = (xx - nx[i]) ** 2           # (pixels,)
                gauss = np.outer(np.exp(-dy2 / (2 * sigma[i] ** 2)),
                                 np.exp(-dx2 / (2 * sigma[i] ** 2)))  # (lines, pixels)

                # Sinusoidal modulation per neuron simulates calcium transients.
                phase = 2 * np.pi * f / n + i * 0.7
                activity = 0.7 + 0.3 * np.sin(phase)

                # Subtract signal (bright spots are dips in PMT signal)
                imgs[0] -= signal_strength[i] * activity * gauss
                imgs[1] -= signal_strength[i] * activity * gauss   # ch1 same magnitude as ch0

            imgs = np.clip(imgs, 0, 16383)

            # In bidirectional mode, odd (backward) scan lines are acquired
            # right-to-left, so their pixels arrive in reversed order in the
            # hardware buffer.  Reverse those rows now to faithfully simulate
            # real hardware output before apply_bidirectional_correction().
            if self.bidirectional:
                imgs[:, 1::2, :] = imgs[:, 1::2, ::-1]

            # Pack into Alazar wire format:
            # interleaved [chA_px0, chB_px0, chA_px1, chB_px1, …],
            # each sample left-shifted by 2 (14-bit value in bits 15:2).
            ch0 = imgs[0].ravel().astype(np.uint16) << 2
            ch1 = imgs[1].ravel().astype(np.uint16) << 2
            packed = np.empty(lines * pixels * 2, dtype=np.uint16)
            packed[0::2] = ch0
            packed[1::2] = ch1
            # Embed frame-sync marker in the two LSBs of the first sample,
            # matching the Alazar LSB output behaviour (configureLSB).
            if self.frame_sync_enabled:
                packed[0] |= np.uint16(0x0001)
            frames.append(packed)

        self._test_frames = frames
        logger.info(
            "Mock Alazar: prepared %d test frames (%d x %d, %d neurons)",
            n, lines, pixels, n_neurons
        )

    def _prepare_test_frames_raw(self) -> None:
        """Pre-compute a bank of raw-mode test frames.

        Generates the same 15-neuron Gaussian-spot layout as
        ``_prepare_test_frames()``, but maps each display-space pixel value
        back to raw ADC sample space using the inverse of the arccosine pixel
        LUT so that after ``reshape_pmt_data()`` / ``reshape_pmt_data_bi()``
        the spots appear at the correct display positions.

        **Unidirectional** (``bidirectional=False``):
          Shape: ``(lines × samples_per_line × 2,)`` uint16.

        **Bidirectional** (``bidirectional=True``):
          Each DMA record covers one full resonant cycle (forward + backward).
          Shape: ``((lines // 2) × samples_per_line_bidir × 2,)`` uint16.
          Uses ``_pixel_lut_bi`` for correct forward+backward pixel placements.

        Note: PMT signals are inverted — high values = dark, low = bright.
        """
        lines, pixels = self.frame_shape
        n = self._n_test_frames
        rng = np.random.default_rng(42)   # same seed as _prepare_test_frames

        n_neurons = 15
        ny = rng.integers(2, max(3, lines  - 2), n_neurons).astype(np.float32)
        nx = rng.integers(2, max(3, pixels - 2), n_neurons).astype(np.float32)
        signal_strength = rng.uniform(8000, 16383, n_neurons).astype(np.float32)
        sigma = rng.uniform(8, 20, n_neurons).astype(np.float32)

        yy = np.arange(lines,  dtype=np.float32)
        xx = np.arange(pixels, dtype=np.float32)

        # ------------------------------------------------------------------ #
        # BIDIRECTIONAL path                                                   #
        # Each record spans a full resonant cycle → different buffer geometry. #
        # ------------------------------------------------------------------ #
        if self.bidirectional and self._pixel_lut_bi is not None:
            records = lines // 2
            n_samp  = self.samples_per_line_bidir
            lut_bi  = self._pixel_lut_bi.astype(np.int64)
            n_bwd   = len(lut_bi) - pixels

            # Forward LUT: lut_bi[0:pixels] → sample indices in [0, n_samp)
            fwd_lut = lut_bi[:pixels]
            fwd_valid = (fwd_lut >= 0) & (fwd_lut + 3 < n_samp)
            fwd_valid_px   = np.where(fwd_valid)[0]
            fwd_valid_samp = fwd_lut[fwd_valid]

            # Backward LUT: lut_bi[pixels:] → sample indices in [n_samp/2, n_samp)
            # reshape_pmt_data_bi maps lut_bi[pixels+bx] → output pixel (pixels-1-bx)
            bwd_lut = lut_bi[pixels:]
            bwd_valid = (bwd_lut >= 0) & (bwd_lut + 3 < n_samp)
            bwd_valid_bx   = np.where(bwd_valid)[0]
            bwd_valid_samp = bwd_lut[bwd_valid]
            bwd_display_px = pixels - 1 - bwd_valid_bx  # display pixel column

            frames = []
            for f in range(n):
                imgs = np.full((2, lines, pixels), 16383.0, dtype=np.float32)
                imgs += rng.normal(0, _BACKGROUND_NOISE_SIGMA,
                                   imgs.shape).astype(np.float32)
                for i in range(n_neurons):
                    dy2 = (yy - ny[i]) ** 2
                    dx2 = (xx - nx[i]) ** 2
                    gauss = np.outer(
                        np.exp(-dy2 / (2 * sigma[i] ** 2)),
                        np.exp(-dx2 / (2 * sigma[i] ** 2)),
                    )
                    phase = 2 * np.pi * f / n + i * 0.7
                    activity = 0.7 + 0.3 * np.sin(phase)
                    imgs[0] -= signal_strength[i] * activity * gauss
                    imgs[1] -= signal_strength[i] * activity * gauss
                imgs = np.clip(imgs, 0, 16383)

                bg = 16383.0
                raw_ch0 = np.full((records, n_samp), bg, dtype=np.float32)
                raw_ch1 = np.full((records, n_samp), bg, dtype=np.float32)

                # Forward sweep: even display lines (0, 2, 4, …)
                # imgs[ch, 0::2, fwd_valid_px] → raw_ch[ch, :, fwd_valid_samp]
                raw_ch0[:, fwd_valid_samp] = imgs[0, 0::2, :][:, fwd_valid_px]
                raw_ch1[:, fwd_valid_samp] = imgs[1, 0::2, :][:, fwd_valid_px]

                # Backward sweep: odd display lines (1, 3, 5, …)
                # reshape_pmt_data_bi maps bwd sample → reversed column order,
                # so place display pixel bwd_display_px at bwd_valid_samp.
                raw_ch0[:, bwd_valid_samp] = imgs[0, 1::2, :][:, bwd_display_px]
                raw_ch1[:, bwd_valid_samp] = imgs[1, 1::2, :][:, bwd_display_px]

                raw_ch0 += rng.normal(0, _BACKGROUND_NOISE_SIGMA,
                                      raw_ch0.shape).astype(np.float32)
                raw_ch1 += rng.normal(0, _BACKGROUND_NOISE_SIGMA,
                                      raw_ch1.shape).astype(np.float32)
                raw_ch0 = np.clip(raw_ch0, 0, 16383)
                raw_ch1 = np.clip(raw_ch1, 0, 16383)

                # Pack: [chA_s0_r0, chB_s0_r0, chA_s1_r0, …, chA_sN_rR, chB_sN_rR]
                packed = np.empty(records * n_samp * 2, dtype=np.uint16)
                packed[0::2] = raw_ch0.ravel().astype(np.uint16) << 2
                packed[1::2] = raw_ch1.ravel().astype(np.uint16) << 2
                if self.frame_sync_enabled:
                    packed[0] |= np.uint16(0x0001)
                frames.append(packed)

            self._test_frames = frames
            logger.info(
                "Mock Alazar: prepared %d bidir raw test frames "
                "(%d records × %d samples, %d neurons)",
                n, records, n_samp, n_neurons,
            )
            return

        # ------------------------------------------------------------------ #
        # UNIDIRECTIONAL path                                                  #
        # ------------------------------------------------------------------ #
        n_samp = self.samples_per_line

        # Build a vectorised reverse map: raw_sample_index → display_pixel_index.
        # Each pixel occupies 4 consecutive raw samples starting at lut_base[px].
        sample_to_pixel = np.full(n_samp, -1, dtype=np.int32)
        if self._pixel_lut is not None:
            lut = self._pixel_lut.astype(np.int64)   # safe arithmetic
            for px in range(pixels):
                for offset in range(4):
                    s = int(lut[px]) + offset
                    if 0 <= s < n_samp:
                        sample_to_pixel[s] = px

        valid_mask    = sample_to_pixel >= 0
        valid_samples = np.where(valid_mask)[0]     # raw sample indices
        mapped_pixels = sample_to_pixel[valid_mask] # corresponding pixel

        frames = []
        for f in range(n):
            imgs = np.full((2, lines, pixels), 16383.0, dtype=np.float32)
            imgs += rng.normal(0, _BACKGROUND_NOISE_SIGMA,
                               imgs.shape).astype(np.float32)
            for i in range(n_neurons):
                dy2 = (yy - ny[i]) ** 2
                dx2 = (xx - nx[i]) ** 2
                gauss = np.outer(
                    np.exp(-dy2 / (2 * sigma[i] ** 2)),
                    np.exp(-dx2 / (2 * sigma[i] ** 2)),
                )
                phase = 2 * np.pi * f / n + i * 0.7
                activity = 0.7 + 0.3 * np.sin(phase)
                imgs[0] -= signal_strength[i] * activity * gauss
                imgs[1] -= signal_strength[i] * activity * gauss
            imgs = np.clip(imgs, 0, 16383)

            bg = 16383.0
            raw_ch0 = np.full((lines, n_samp), bg, dtype=np.float32)
            raw_ch1 = np.full((lines, n_samp), bg, dtype=np.float32)
            raw_ch0[:, valid_samples] = imgs[0][:, mapped_pixels]
            raw_ch1[:, valid_samples] = imgs[1][:, mapped_pixels]

            raw_ch0 += rng.normal(0, _BACKGROUND_NOISE_SIGMA,
                                  raw_ch0.shape).astype(np.float32)
            raw_ch1 += rng.normal(0, _BACKGROUND_NOISE_SIGMA,
                                  raw_ch1.shape).astype(np.float32)
            raw_ch0 = np.clip(raw_ch0, 0, 16383)
            raw_ch1 = np.clip(raw_ch1, 0, 16383)

            packed = np.empty(lines * n_samp * 2, dtype=np.uint16)
            packed[0::2] = raw_ch0.ravel().astype(np.uint16) << 2
            packed[1::2] = raw_ch1.ravel().astype(np.uint16) << 2
            if self.frame_sync_enabled:
                packed[0] |= np.uint16(0x0001)
            frames.append(packed)

        self._test_frames = frames
        logger.info(
            "Mock Alazar: prepared %d raw test frames (%d lines × %d samples, %d neurons)",
            n, lines, n_samp, n_neurons,
        )

    def get_channel_info(self) -> dict:
        """Get channel configuration info.

        Returns:
            Dictionary with channel settings.
        """
        return {
            'channels': self.channels,
            'bits_per_sample': self.bits_per_sample,
            'sample_rate': self.sample_rate,
            'max_sample_rate': 125_000_000,
        }


# Store reference to Board class before defining factory function
_BoardClass = Board


def Board() -> Board:
    """Factory function to create mock board.

    Returns:
        Mock Board instance.
    """
    return _BoardClass(system_id=1, board_id=1)


# API success code
ApiSuccess = 512
ApiWaitTimeout = 573

class Buffer:
    def __init__(self, board, channels, records_per_buffer, samples_per_record, **kwargs):
        self.board = board
        size = records_per_buffer * samples_per_record * channels
        self.buffer = np.empty(size, dtype=np.uint16)
        # Mock exposes the numpy array as `address` so post_async_buffer gets the array directly
        self.address = self.buffer
