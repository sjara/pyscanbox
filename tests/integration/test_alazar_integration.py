#!/usr/bin/env python3
"""Test script for Alazar integration implementation.

Tests the complete acquisition pipeline with emulation mode.
"""

import sys
import os
import numpy as np

# Add pyscanbox to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pyscanbox.hardware.alazar import AlazarDigitizer


def test_basic_acquisition():
    """Test basic acquisition workflow."""
    print("Testing basic acquisition workflow...")
    
    # Create config dict for testing
    config = {
        'alazar': {
            'sample_rate': 125000000,  # 125 MS/s
            'bits_per_sample': 14,
            'channels': 2,
            'buffer_count': 4,
            'samples_per_buffer': 2048
        },
        'emulation': {
            'enabled': True,
            'verbose': False
        }
    }
    
    # Create digitizer instance
    print("  Creating AlazarDigitizer instance...")
    digitizer = AlazarDigitizer(config)
    assert digitizer.use_emulation == True, "Should be in emulation mode"
    print("  ✓ Instance created")
    
    # Open board
    print("  Opening board...")
    digitizer.open()
    assert digitizer.board_handle is not None, "Board handle should not be None"
    print("  ✓ Board opened")
    
    # Configure
    print("  Configuring board...")
    digitizer.configure()
    assert digitizer.is_configured == True, "Should be configured"
    print("  ✓ Board configured")
    
    # Allocate buffers
    print("  Allocating buffers...")
    digitizer.allocate_buffers()
    assert len(digitizer.buffers) == 4, "Should have 4 buffers"
    assert len(digitizer.buffer_pointers) == 4, "Should have 4 buffer pointers"
    print(f"  ✓ Allocated {len(digitizer.buffers)} buffers")
    
    # Start acquisition
    print("  Starting acquisition...")
    digitizer.start_acquisition()
    assert digitizer.is_acquiring == True, "Should be acquiring"
    print("  ✓ Acquisition started")
    
    # Read some buffers
    print("  Reading buffers...")
    buffers_read = 0
    for i in range(10):
        data = digitizer.read_buffer(timeout_ms=1000)
        if data is not None:
            buffers_read += 1
            # Verify data shape
            expected_samples = config['alazar']['samples_per_buffer'] * config['alazar']['channels']
            assert data.shape[0] == expected_samples, f"Expected {expected_samples} samples, got {data.shape[0]}"
            assert data.dtype == np.uint16, f"Expected uint16, got {data.dtype}"
    
    print(f"  ✓ Successfully read {buffers_read} buffers")
    assert buffers_read > 0, "Should have read at least one buffer"
    
    # Stop acquisition
    print("  Stopping acquisition...")
    digitizer.stop_acquisition()
    assert digitizer.is_acquiring == False, "Should not be acquiring"
    print("  ✓ Acquisition stopped")
    
    # Close
    print("  Closing board...")
    digitizer.close()
    assert digitizer.board_handle is None, "Board handle should be None after close"
    print("  ✓ Board closed")
    
    print("✓ All tests passed!\n")


def test_error_conditions():
    """Test error handling."""
    print("Testing error conditions...")
    
    config = {
        'alazar': {
            'sample_rate': 125000000,
            'bits_per_sample': 14,
            'channels': 2,
            'buffer_count': 4,
            'samples_per_buffer': 2048
        },
        'emulation': {
            'enabled': True,
            'verbose': False
        }
    }
    
    digitizer = AlazarDigitizer(config)
    
    # Test configure before open
    print("  Testing configure before open...")
    try:
        digitizer.configure()
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "not opened" in str(e).lower()
        print("  ✓ Correctly raised error for configure before open")
    
    # Test start_acquisition before configure
    print("  Testing start_acquisition before configure...")
    digitizer.open()
    try:
        digitizer.start_acquisition()
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "not configured" in str(e).lower()
        print("  ✓ Correctly raised error for start before configure")
    
    # Test read_buffer before start
    print("  Testing read_buffer before start...")
    digitizer.configure()
    digitizer.allocate_buffers()
    try:
        digitizer.read_buffer()
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "not started" in str(e).lower()
        print("  ✓ Correctly raised error for read before start")
    
    digitizer.close()
    print("✓ All error condition tests passed!\n")


def test_performance():
    """Test basic performance metrics."""
    print("Testing performance...")
    
    config = {
        'alazar': {
            'sample_rate': 125000000,  # 125 MS/s
            'bits_per_sample': 14,
            'channels': 2,
            'buffer_count': 4,
            'samples_per_buffer': 20480  # Larger buffers for performance test
        },
        'emulation': {
            'enabled': True,
            'verbose': False
        }
    }
    
    digitizer = AlazarDigitizer(config)
    digitizer.open()
    digitizer.configure()
    digitizer.allocate_buffers()
    digitizer.start_acquisition()
    
    import time
    start_time = time.time()
    num_buffers = 100
    total_samples = 0
    
    for i in range(num_buffers):
        data = digitizer.read_buffer(timeout_ms=1000)
        if data is not None:
            total_samples += len(data)
    
    elapsed = time.time() - start_time
    samples_per_sec = total_samples / elapsed
    mbytes_per_sec = (total_samples * 2) / (1024 * 1024 * elapsed)  # 2 bytes per sample
    
    print(f"  Read {num_buffers} buffers in {elapsed:.2f} seconds")
    print(f"  {samples_per_sec/1e6:.2f} MS/s")
    print(f"  {mbytes_per_sec:.2f} MB/s")
    
    digitizer.stop_acquisition()
    digitizer.close()
    
    print("✓ Performance test complete!\n")


if __name__ == '__main__':
    print("=" * 60)
    print("Alazar Integration Test Suite")
    print("=" * 60 + "\n")
    
    try:
        test_basic_acquisition()
        test_error_conditions()
        test_performance()
        
        print("=" * 60)
        print("All tests passed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
