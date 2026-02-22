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

        logger.info(f"Mock Alazar board initialized: System {system_id}, Board {board_id}")

    def setCaptureClock(self, source: int, sample_rate: int,
                       edge: int = 0, decimation: int = 0) -> int:
        """Configure capture clock.

        Args:
            source: Clock source
            sample_rate: Sample rate code or value
            edge: Clock edge (0 = rising)
            decimation: Decimation factor

        Returns:
            Status code (512 = success)
        """
        self.sample_rate = sample_rate
        logger.debug(f"Clock configured: {sample_rate} S/s")
        return 512  # ApiSuccess

    def inputControl(self, channel: int, coupling: int, input_range: int,
                    impedance: int) -> int:
        """Configure input channel.

        Args:
            channel: Channel ID
            coupling: Coupling mode
            input_range: Input range code
            impedance: Input impedance

        Returns:
            Status code (512 = success)
        """
        self.input_range = input_range
        logger.debug(f"Channel {channel} configured")
        return 512

    def setTriggerOperation(self, operation: int, engine1: int, source1: int,
                           slope1: int, level1: int, engine2: int,
                           source2: int, slope2: int, level2: int) -> int:
        """Configure trigger operation.

        Args:
            operation: Trigger operation mode
            engine1-2: Engine parameters
            source1-2: Trigger sources
            slope1-2: Trigger slopes
            level1-2: Trigger levels

        Returns:
            Status code (512 = success)
        """
        logger.debug("Trigger configured")
        return 512

    def setExternalTrigger(self, coupling: int, range: int) -> int:
        """Configure external trigger.

        Args:
            coupling: Coupling mode
            range: Input range

        Returns:
            Status code (512 = success)
        """
        logger.debug("External trigger configured")
        return 512

    def configureLSB(self, lsb0_source: int, lsb1_source: int) -> bool:
        """Configure LSB output bits for frame/line sync.

        Args:
            lsb0_source: Source for LSB[0]
            lsb1_source: Source for LSB[1]

        Returns:
            True on success.
        """
        logger.debug(f"LSB configured: LSB0={lsb0_source}, LSB1={lsb1_source}")
        self.is_configured = True
        return True

    def beforeAsyncRead(self, channels: int, transfer_offset: int,
                       samples_per_record: int, records_per_buffer: int,
                       records_per_acquisition: int, flags: int) -> int:
        """Setup asynchronous acquisition.

        Args:
            channels: Channel mask
            transfer_offset: Transfer offset in samples
            samples_per_record: Samples per record
            records_per_buffer: Records per buffer
            records_per_acquisition: Total records (or infinite)
            flags: Configuration flags

        Returns:
            Status code (512 = success)
        """
        self.buffer_size_samples = samples_per_record * records_per_buffer
        logger.debug(f"Async read configured: {self.buffer_size_samples} samples/buffer")
        return 512

    def postAsyncBuffer(self, buffer: np.ndarray) -> int:
        """Post buffer for DMA.

        Args:
            buffer: NumPy array to fill with data

        Returns:
            Status code (512 = success)
        """
        with self.buffer_lock:
            self.posted_buffers.append(buffer)
        return 512

    def startCapture(self) -> int:
        """Start data acquisition.

        Returns:
            Status code (512 = success)
        """
        self.is_acquiring = True
        logger.info("Mock acquisition started")

        # Start background thread to generate data
        self._generation_thread = threading.Thread(
            target=self._generate_data_loop,
            daemon=True
        )
        self._generation_thread.start()

        return 512

    def waitAsyncBufferComplete(self, buffer: np.ndarray,
                               timeout_ms: int = 5000) -> int:
        """Wait for buffer to be filled with data.

        Args:
            buffer: Buffer to wait for
            timeout_ms: Timeout in milliseconds

        Returns:
            Status code (512 = success, 573 = timeout)
        """
        start_time = time.time()
        timeout_sec = timeout_ms / 1000.0

        while self.is_acquiring:
            with self.buffer_lock:
                if len(self.completed_buffers) > 0:
                    # Fill buffer with generated data
                    data = self.completed_buffers.pop(0)
                    np.copyto(buffer, data)
                    return 512  # ApiSuccess

            # Check timeout
            if time.time() - start_time > timeout_sec:
                logger.warning("Buffer wait timeout")
                return 573  # ApiWaitTimeout

            time.sleep(0.001)  # 1ms sleep

        return 573

    def abortAsyncRead(self) -> int:
        """Abort asynchronous acquisition.

        Returns:
            Status code (512 = success)
        """
        self.is_acquiring = False
        logger.info("Mock acquisition aborted")
        return 512

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

        Returns:
            Array of uint16 data with 14-bit values.
        """
        # Generate random noise (14-bit)
        noise = np.random.normal(
            self.dc_offset,
            self.noise_level,
            self.buffer_size_samples
        ).astype(np.int32)

        # Clip to 14-bit range
        noise = np.clip(noise, 0, 16383)

        # Pack into 16-bit with LSB sync bits
        data = np.zeros(self.buffer_size_samples, dtype=np.uint16)

        # Shift PMT data to upper 14 bits
        data = (noise << 2).astype(np.uint16)

        # Add synthetic sync bits in LSB positions
        if self.frame_sync_enabled:
            # Add frame markers periodically
            frame_size = 512 * 796  # typical frame size
            for i in range(0, len(data), frame_size):
                if i < len(data):
                    data[i] |= 0b01  # Frame start marker

        return data

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
