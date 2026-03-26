# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Tests for mock AlazarTech digitizer emulator.

Tests the mock_alazar module which emulates the AlazarTech ATS9440
digitizer for high-speed PMT data acquisition.
"""

import pytest
import numpy as np
import time
import threading
from pyscanbox.emulator import mock_alazar


class TestBoardInitialization:
    """Test Board class initialization."""

    def test_default_initialization(self):
        """Test board initializes with default parameters."""
        board = mock_alazar._BoardClass()
        
        assert board.system_id == 1
        assert board.board_id == 1
        assert board.is_configured is False
        assert board.is_acquiring is False
        assert board.sample_rate == 125_000_000
        assert board.channels == 2
        assert board.bits_per_sample == 14

    def test_custom_initialization(self):
        """Test board initialization with custom IDs."""
        board = mock_alazar._BoardClass(system_id=2, board_id=3)
        
        assert board.system_id == 2
        assert board.board_id == 3

    def test_buffer_initialization(self):
        """Test buffer management structures are initialized."""
        board = mock_alazar._BoardClass()
        
        assert isinstance(board.posted_buffers, list)
        assert isinstance(board.completed_buffers, list)
        assert len(board.posted_buffers) == 0
        assert len(board.completed_buffers) == 0
        assert isinstance(board.buffer_lock, type(threading.Lock()))


class TestConfigurationMethods:
    """Test board configuration methods."""

    def test_set_capture_clock(self):
        """Test capture clock configuration."""
        board = mock_alazar._BoardClass()
        
        sample_rate = 125_000_000
        # Should not raise exception
        board.set_capture_clock(
            source=1,  # Internal clock
            rate=sample_rate,
            edge=0,
            decimation=0
        )
        
        assert board.sample_rate == sample_rate

    def test_input_control_ex(self):
        """Test input channel configuration."""
        board = mock_alazar._BoardClass()
        
        # Should not raise exception
        board.input_control_ex(
            channel=1,
            coupling=1,  # DC coupling
            inputRange=400,  # 400 mV
            impedance=50
        )
        
        assert board.input_range == 400

    def test_set_trigger_operation(self):
        """Test trigger operation configuration."""
        board = mock_alazar._BoardClass()
        
        # Should not raise exception
        board.set_trigger_operation(
            operation=0,
            engine1=0, source1=0, slope1=1, level1=128,
            engine2=0, source2=0, slope2=1, level2=128
        )

    def test_set_external_trigger(self):
        """Test external trigger configuration."""
        board = mock_alazar._BoardClass()
        
        # Should not raise exception
        board.set_external_trigger(
            coupling=1,  # DC
            range=5  # Range code
        )

    def test_configure_lsb(self):
        """Test LSB output configuration for sync signals."""
        board = mock_alazar._BoardClass()
        
        # Should not raise exception
        board.configure_lsb(
            valueLSB0=1,  # Frame sync
            valueLSB1=2   # Line sync
        )
        
        assert board.is_configured is True


class TestAsyncAcquisitionSetup:
    """Test asynchronous acquisition setup methods."""

    def test_before_async_read(self):
        """Test async read configuration."""
        board = mock_alazar._BoardClass()
        
        samplesPerRecord = 2048
        recordsPerBuffer = 1
        channels_mask = 3  # Both channels (bits 0 and 1 set)
        num_channels = 2  # bin(3).count('1') = 2
        
        # Should not raise exception
        board.before_async_read(
            channels=channels_mask,
            transferOffset=0,
            samplesPerRecord=samplesPerRecord,
            recordsPerBuffer=recordsPerBuffer,
            recordsPerAcquisition=0,  # Continuous
            flags=0x200  # NPT mode
        )
        
        # Buffer size should account for interleaved channels
        assert board.buffer_size_samples == samplesPerRecord * num_channels * recordsPerBuffer

    def test_post_async_buffer(self):
        """Test posting buffers for DMA."""
        board = mock_alazar._BoardClass()
        
        # Create buffers
        buffer1 = np.zeros(2048, dtype=np.uint16)
        buffer2 = np.zeros(2048, dtype=np.uint16)
        
        # Post buffers - should not raise exception
        board.post_async_buffer(buffer1)
        board.post_async_buffer(buffer2)
        
        assert len(board.posted_buffers) == 2

    def test_post_multiple_buffers(self):
        """Test posting multiple buffers."""
        board = mock_alazar._BoardClass()
        
        num_buffers = 10
        buffers = [np.zeros(2048, dtype=np.uint16) for _ in range(num_buffers)]
        
        for buf in buffers:
            board.post_async_buffer(buf)
        
        assert len(board.posted_buffers) == num_buffers


class TestAcquisitionControl:
    """Test acquisition control methods."""

    def test_start_capture(self):
        """Test starting data acquisition."""
        board = mock_alazar._BoardClass()
        board.before_async_read(3, 0, 2048, 1, 0, 0x200)
        
        # Should not raise exception
        board.start_capture()
        
        assert board.is_acquiring is True
        
        # Clean up
        board.abort_async_read()
        time.sleep(0.01)

    def test_abort_async_read(self):
        """Test aborting acquisition."""
        board = mock_alazar._BoardClass()
        board.before_async_read(3, 0, 2048, 1, 0, 0x200)
        board.start_capture()
        
        # Should not raise exception
        board.abort_async_read()
        
        assert board.is_acquiring is False

    def test_wait_async_buffer_complete_success(self):
        """Test waiting for buffer completion successfully."""
        board = mock_alazar._BoardClass()
        board.before_async_read(3, 0, 2048, 1, 0, 0x200)
        
        # Post and start (buffer size = 2048 samples/ch * 2 channels = 4096)
        buffer = np.zeros(4096, dtype=np.uint16)
        board.post_async_buffer(buffer)
        board.start_capture()
        
        # Wait for buffer - should not raise exception
        result_buffer = np.zeros(4096, dtype=np.uint16)
        board.wait_async_buffer_complete(result_buffer, timeout_ms=1000)
        
        # Data should be non-zero (synthetic data generated)
        assert np.any(result_buffer != 0)
        
        # Clean up
        board.abort_async_read()
        time.sleep(0.01)

    def test_wait_async_buffer_complete_timeout(self):
        """Test buffer wait timeout."""
        board = mock_alazar._BoardClass()
        
        # Don't start capture, just wait - should raise exception
        buffer = np.zeros(2048, dtype=np.uint16)
        with pytest.raises(Exception, match="Timeout|Acquisition aborted"):
            board.wait_async_buffer_complete(buffer, timeout_ms=100)

    def test_wait_async_buffer_complete_after_abort(self):
        """Test waiting after acquisition is aborted."""
        board = mock_alazar._BoardClass()
        board.before_async_read(3, 0, 2048, 1, 0, 0x200)
        board.start_capture()
        board.abort_async_read()
        
        buffer = np.zeros(2048, dtype=np.uint16)
        # Should raise exception since acquisition stopped
        with pytest.raises(Exception, match="Timeout|Acquisition aborted"):
            board.wait_async_buffer_complete(buffer, timeout_ms=100)


class TestDataGeneration:
    """Test synthetic data generation."""

    def test_generate_synthetic_frame(self):
        """Test synthetic frame generation."""
        board = mock_alazar._BoardClass()
        board.buffer_size_samples = 2048
        
        data = board._generate_synthetic_frame()
        
        assert data.dtype == np.uint16
        assert len(data) == 2048
        # Data should be non-zero
        assert np.any(data != 0)

    def test_synthetic_data_14bit_range(self):
        """Test synthetic data is in valid 14-bit range (shifted to upper bits)."""
        board = mock_alazar._BoardClass()
        board.buffer_size_samples = 10000
        
        data = board._generate_synthetic_frame()
        
        # Data is 14-bit shifted left by 2, so max value should be <= 16383 << 2
        assert np.all(data <= (16383 << 2))
        # Should use significant bits
        assert np.max(data) > 1000

    def test_synthetic_data_frame_markers(self):
        """Test frame sync markers in LSB."""
        board = mock_alazar._BoardClass()
        board.frame_sync_enabled = True
        # set_frame_shape is required for structured (non-noise) data generation.
        # One interleaved frame = lines * pixels * 2 (channels) samples.
        board.set_frame_shape(512, 796)
        frame_size = 512 * 796 * 2          # samples in one full interleaved frame
        board.buffer_size_samples = frame_size * 2  # request two back-to-back frames

        data = board._generate_synthetic_frame()

        # First sample of each frame must carry the frame-sync marker in bit 0.
        assert (data[0] & 0b01) == 0b01, "Frame 1 marker missing"
        if len(data) > frame_size:
            assert (data[frame_size] & 0b01) == 0b01, "Frame 2 marker missing"

    def test_synthetic_data_variability(self):
        """Test that synthetic data has variability (noise)."""
        board = mock_alazar._BoardClass()
        board.buffer_size_samples = 1000
        
        data1 = board._generate_synthetic_frame()
        data2 = board._generate_synthetic_frame()
        
        # Two frames should be different (random noise)
        assert not np.array_equal(data1, data2)


class TestContinuousAcquisition:
    """Test continuous acquisition with multiple buffers."""

    def test_multiple_buffer_acquisition(self):
        """Test acquiring multiple buffers continuously."""
        board = mock_alazar._BoardClass()
        board.before_async_read(3, 0, 2048, 1, 0, 0x200)
        
        # Post multiple buffers (buffer size = 2048 * 2 channels = 4096)
        num_buffers = 5
        buffers = [np.zeros(4096, dtype=np.uint16) for _ in range(num_buffers)]
        
        for buf in buffers:
            board.post_async_buffer(buf)
        
        # Start acquisition
        board.start_capture()
        
        # Retrieve buffers
        retrieved_buffers = []
        for i in range(num_buffers):
            buf = np.zeros(4096, dtype=np.uint16)
            try:
                board.wait_async_buffer_complete(buf, timeout_ms=1000)
                retrieved_buffers.append(buf.copy())
            except Exception:
                # Timeout or other error
                break
        
        # Should get at least some buffers
        assert len(retrieved_buffers) > 0
        
        # Each buffer should have data
        for buf in retrieved_buffers:
            assert np.any(buf != 0)
        
        # Clean up
        board.abort_async_read()
        time.sleep(0.01)

    def test_acquisition_loop_timing(self):
        """Test that acquisition loop runs continuously."""
        board = mock_alazar._BoardClass()
        board.before_async_read(3, 0, 1024, 1, 0, 0x200)
        
        # Post buffers (buffer size = 1024 * 2 channels = 2048)
        for _ in range(3):
            board.post_async_buffer(np.zeros(2048, dtype=np.uint16))
        
        board.start_capture()
        
        # Wait briefly for generation thread to start
        time.sleep(0.05)
        
        # Should have generated at least one buffer
        assert len(board.completed_buffers) > 0
        
        board.abort_async_read()
        time.sleep(0.01)


class TestThreadSafety:
    """Test thread safety of buffer management."""

    def test_concurrent_buffer_posting(self):
        """Test posting buffers from multiple threads."""
        board = mock_alazar._BoardClass()
        
        def post_buffers(n):
            for _ in range(n):
                buf = np.zeros(2048, dtype=np.uint16)
                board.post_async_buffer(buf)
        
        # Start multiple threads
        threads = [
            threading.Thread(target=post_buffers, args=(10,))
            for _ in range(3)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Should have all 30 buffers
        assert len(board.posted_buffers) == 30

    def test_buffer_lock_prevents_race_conditions(self):
        """Test that buffer lock prevents race conditions."""
        board = mock_alazar._BoardClass()
        board.before_async_read(3, 0, 1024, 1, 0, 0x200)

        # channels=3 (2 active), samplesPerRecord=1024, recordsPerBuffer=1
        # → buffer_size_samples = 1024 * 2 * 1 = 2048
        buffer_size = 2048

        # Post buffers and start
        for _ in range(5):
            board.post_async_buffer(np.zeros(buffer_size, dtype=np.uint16))
        board.start_capture()
        
        # Rapidly access buffers from main thread while generation thread runs
        for _ in range(10):
            with board.buffer_lock:
                posted_count = len(board.posted_buffers)
                completed_count = len(board.completed_buffers)
            time.sleep(0.01)
        
        # Should not crash
        board.abort_async_read()
        time.sleep(0.01)


class TestFactoryFunction:
    """Test Board factory function."""

    def test_factory_function(self):
        """Test Board() factory creates proper instance."""
        board = mock_alazar.Board()
        
        assert isinstance(board, mock_alazar._BoardClass)
        assert board.system_id == 1
        assert board.board_id == 1


class TestAPIConstants:
    """Test API constants."""

    def test_api_success_code(self):
        """Test ApiSuccess constant."""
        assert mock_alazar.ApiSuccess == 512

    def test_api_timeout_code(self):
        """Test ApiWaitTimeout constant."""
        assert mock_alazar.ApiWaitTimeout == 573


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_size_buffer(self):
        """Test handling zero-size buffer."""
        board = mock_alazar._BoardClass()
        board.buffer_size_samples = 0
        
        # Should not crash
        data = board._generate_synthetic_frame()
        assert len(data) == 0

    def test_very_large_buffer(self):
        """Test handling very large buffer."""
        board = mock_alazar._BoardClass()
        board.buffer_size_samples = 10_000_000  # 10M samples
        
        data = board._generate_synthetic_frame()
        assert len(data) == 10_000_000
        assert data.dtype == np.uint16

    def test_abort_without_start(self):
        """Test aborting without starting acquisition."""
        board = mock_alazar._BoardClass()
        
        # Should not crash or raise exception
        board.abort_async_read()

    def test_multiple_start_stop_cycles(self):
        """Test multiple acquisition start/stop cycles."""
        board = mock_alazar._BoardClass()
        board.before_async_read(3, 0, 1024, 1, 0, 0x200)
        
        for _ in range(3):
            board.start_capture()
            time.sleep(0.02)
            board.abort_async_read()
            time.sleep(0.02)
        
        assert board.is_acquiring is False

    def test_wait_with_no_configuration(self):
        """Test waiting for buffer without prior configuration."""
        board = mock_alazar._BoardClass()
        
        buffer = np.zeros(2048, dtype=np.uint16)
        # Should raise exception gracefully
        with pytest.raises(Exception, match="Timeout|Acquisition aborted"):
            board.wait_async_buffer_complete(buffer, timeout_ms=100)

    def test_noise_level_configuration(self):
        """Test that noise level affects generated data."""
        board = mock_alazar._BoardClass()
        board.buffer_size_samples = 10000
        
        # High noise
        board.noise_level = 4000
        data_high_noise = board._generate_synthetic_frame()
        
        # Low noise
        board.noise_level = 100
        data_low_noise = board._generate_synthetic_frame()
        
        # High noise should have more variation
        std_high = np.std(data_high_noise)
        std_low = np.std(data_low_noise)
        assert std_high > std_low
