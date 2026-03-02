"""Mock AlazarTech digitizer for emulation.

This module provides a mock implementation of the AlazarTech ATS9440 digitizer
for Linux/offline development. It generates synthetic 14-bit PMT data and
mimics the atsapi interface.

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


class Board:
    """Mock AlazarTech board interface.

    Emulates the AlazarTech Python API (atsapi) for development without
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

        # Data generation parameters
        self.noise_level = 1000  # RMS noise level (14-bit scale)
        self.dc_offset = 8192  # Center at middle of 14-bit range
        self.frame_sync_enabled = True

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
        self.samples_per_line: int = 5000   # postTriggerSamples (real hardware)
        self._pixel_lut: np.ndarray | None = None  # (pixels,) int32 base indices

        logger.info(f"Mock Alazar board initialized: System {system_id}, Board {board_id}")

    def setCaptureClock(self, source: int, rate: int,
                       edge: int = 0, decimation: int = 0) -> int:
        """Configure capture clock.

        Args:
            source: Clock source
            rate: Sample rate code or value
            edge: Clock edge (0 = rising)
            decimation: Decimation factor

        Returns:
            Status code (512 = success)
        """
        self.sample_rate = rate
        logger.debug(f"Clock configured: {rate} S/s")
        return 512  # ApiSuccess

    def inputControl(self, channel: int, coupling: int, inputRange: int,
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

    def setTriggerOperation(self, operation: int, engine1: int, source1: int,
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

    def setExternalTrigger(self, coupling: int, range: int) -> None:
        """Configure external trigger.

        Args:
            coupling: Coupling mode
            range: Input range
        """
        logger.debug("External trigger configured")

    def configureLSB(self, valueLSB0: int, valueLSB1: int) -> None:
        """Configure LSB output bits for frame/line sync.

        Args:
            valueLSB0: Value for LSB[0]
            valueLSB1: Value for LSB[1]
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
                     laser_freq: float, res_freq: float) -> None:
        """Configure raw acquisition mode to match real hardware buffer layout.

        When ``raw_mode=True``, each buffer contains
        ``lines_per_frame × samples_per_line × 2`` interleaved uint16 raw ADC
        samples (channels A and B interleaved per sample, lines sequential).
        Spot images are pre-warped using the inverse of the arccosine pixel LUT
        so that after ``reshape_pmt_data_raw()`` the spots appear at the correct
        display positions.

        Must be called **after** ``set_frame_shape()`` and **before**
        ``startCapture()``.

        Args:
            raw_mode: ``True`` to generate raw-format buffers.
            samples_per_line: Raw ADC samples per scan line (e.g. 5000).
            laser_freq: Laser repetition frequency in Hz (e.g. 80_180_000).
            res_freq: Resonant mirror frequency in Hz (e.g. 7930).
        """
        self.raw_mode = raw_mode
        self.samples_per_line = samples_per_line
        self._test_frames = None   # force regeneration on next call

        if raw_mode and self.frame_shape is not None:
            from pyscanbox.acquisition.reshape import compute_pixel_lut
            pixels = self.frame_shape[1]
            self._pixel_lut = compute_pixel_lut(pixels, laser_freq, res_freq)
            # Adjust buffer size to raw mode: lines × samples_per_line × channels
            lines = self.frame_shape[0]
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
            # Re-compute shaped test frames if frame_shape is already known,
            # so a switch back to non-raw mode is reflected immediately.
            if not raw_mode and self.frame_shape is not None:
                self._prepare_test_frames()

        logger.info(
            "Mock Alazar raw mode %s (samples_per_line=%d)",
            "enabled" if raw_mode else "disabled",
            samples_per_line,
        )

    def beforeAsyncRead(self, channels: int, transferOffset: int,
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

    def postAsyncBuffer(self, buffer: np.ndarray, bufferLength: Optional[int] = None) -> None:
        """Post buffer for DMA.

        Args:
            buffer: NumPy array or pointer to fill with data
            bufferLength: Buffer length in bytes (optional for numpy arrays)
        """
        with self.buffer_lock:
            self.posted_buffers.append(buffer)

    def startCapture(self) -> None:
        """Start data acquisition."""
        self.is_acquiring = True
        logger.info("Mock acquisition started")

        # Start background thread to generate data
        self._generation_thread = threading.Thread(
            target=self._generate_data_loop,
            daemon=True
        )
        self._generation_thread.start()

    def waitAsyncBufferComplete(self, buffer: np.ndarray,
                               timeout_ms: int = 5000) -> None:
        """Wait for buffer to be filled with data.

        Args:
            buffer: Buffer to wait for
            timeout_ms: Timeout in milliseconds
            
        Raises:
            Exception: If timeout occurs (matching atsapi behavior)
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

    def abortAsyncRead(self) -> None:
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

            return buf

        # --- Fallback: pure noise (no frame shape set) ---
        noise = np.random.normal(
            self.dc_offset,
            self.noise_level,
            self.buffer_size_samples
        ).astype(np.int32)
        noise = np.clip(noise, 0, 16383)
        return (noise << 2).astype(np.uint16)

    def _prepare_test_frames(self) -> None:
        """Pre-compute a bank of synthetic test frames.

        Generates self._n_test_frames frames, each containing ~15 Gaussian
        spots (simulated neurons) whose intensities vary sinusoidally across
        the frame bank — mimicking calcium fluorescence dynamics.  Channel 0
        (PMT0) is bright; channel 1 (PMT1) is ~40 % of channel 0 intensity.

        The results are stored as Alazar wire-format buffers in self._test_frames
        (interleaved channels, values left-shifted by 2 into bits 15:2).
        """
        lines, pixels = self.frame_shape
        n = self._n_test_frames
        rng = np.random.default_rng(42)   # fixed seed → reproducible layout

        # --- Fixed neuron positions and baseline intensities ---
        n_neurons = 15
        ny = rng.integers(2, max(3, lines  - 2), n_neurons).astype(np.float32)
        nx = rng.integers(2, max(3, pixels - 2), n_neurons).astype(np.float32)
        peak = rng.uniform(4000, 12000, n_neurons).astype(np.float32)  # 14-bit
        sigma = rng.uniform(4, 10, n_neurons).astype(np.float32)       # px

        # 1-D coordinate arrays for outer-product Gaussian computation.
        yy = np.arange(lines,  dtype=np.float32)   # (lines,)
        xx = np.arange(pixels, dtype=np.float32)   # (pixels,)

        frames = []
        for f in range(n):
            imgs = np.zeros((2, lines, pixels), dtype=np.float32)

            for i in range(n_neurons):
                dy2 = (yy - ny[i]) ** 2           # (lines,)
                dx2 = (xx - nx[i]) ** 2           # (pixels,)
                gauss = np.outer(np.exp(-dy2 / (2 * sigma[i] ** 2)),
                                 np.exp(-dx2 / (2 * sigma[i] ** 2)))  # (lines, pixels)

                # Sinusoidal modulation per neuron simulates calcium transients.
                phase = 2 * np.pi * f / n + i * 0.7
                activity = 0.7 + 0.3 * np.sin(phase)

                imgs[0] += peak[i] * activity * gauss
                imgs[1] += peak[i] * activity * 0.4 * gauss   # ch1 dimmer

            # Low background + photon shot-noise.
            imgs += rng.normal(300, 150, imgs.shape).astype(np.float32)
            imgs = np.clip(imgs, 0, 16383)

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
        LUT.  After passing through ``reshape_pmt_data_raw()`` the spots will
        appear at the correct display positions.

        Buffer layout: interleaved channels (chA, chB per sample), line-major,
        with each sample left-shifted by 2 (14-bit value in bits 15:2).
        Shape: ``(lines * samples_per_line * 2,)`` uint16.
        """
        lines, pixels = self.frame_shape
        n_samp = self.samples_per_line
        n = self._n_test_frames
        rng = np.random.default_rng(42)   # same seed as _prepare_test_frames

        n_neurons = 15
        ny = rng.integers(2, max(3, lines  - 2), n_neurons).astype(np.float32)
        nx = rng.integers(2, max(3, pixels - 2), n_neurons).astype(np.float32)
        peak = rng.uniform(4000, 12000, n_neurons).astype(np.float32)
        sigma = rng.uniform(4, 10, n_neurons).astype(np.float32)

        yy = np.arange(lines,  dtype=np.float32)
        xx = np.arange(pixels, dtype=np.float32)

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
        valid_samples = np.where(valid_mask)[0]          # raw sample indices
        mapped_pixels = sample_to_pixel[valid_mask]      # corresponding pixel

        frames = []
        for f in range(n):
            imgs = np.zeros((2, lines, pixels), dtype=np.float32)

            for i in range(n_neurons):
                dy2 = (yy - ny[i]) ** 2
                dx2 = (xx - nx[i]) ** 2
                gauss = np.outer(np.exp(-dy2 / (2 * sigma[i] ** 2)),
                                 np.exp(-dx2 / (2 * sigma[i] ** 2)))
                phase = 2 * np.pi * f / n + i * 0.7
                activity = 0.7 + 0.3 * np.sin(phase)
                imgs[0] += peak[i] * activity * gauss
                imgs[1] += peak[i] * activity * 0.4 * gauss

            imgs += rng.normal(300, 150, imgs.shape).astype(np.float32)
            imgs = np.clip(imgs, 0, 16383)

            # Map display pixels → raw sample positions (vectorised).
            # Uninitialised raw samples get a background level of 300.
            bg = 300.0
            raw_ch0 = np.full((lines, n_samp), bg, dtype=np.float32)
            raw_ch1 = np.full((lines, n_samp), bg, dtype=np.float32)
            raw_ch0[:, valid_samples] = imgs[0][:, mapped_pixels]
            raw_ch1[:, valid_samples] = imgs[1][:, mapped_pixels]

            # Add noise to fill sparse gaps between LUT samples.
            raw_ch0 += rng.normal(0, 150, raw_ch0.shape).astype(np.float32)
            raw_ch1 += rng.normal(0, 150, raw_ch1.shape).astype(np.float32)
            raw_ch0 = np.clip(raw_ch0, 0, 16383)
            raw_ch1 = np.clip(raw_ch1, 0, 16383)

            # Pack into Alazar wire format: interleaved channels, line-major.
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

    def getChannelInfo(self) -> dict:
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
