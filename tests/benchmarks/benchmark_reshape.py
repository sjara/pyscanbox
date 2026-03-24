#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Benchmark script for reshape_pmt_data_emulation performance.

Tests the high-speed data reshaping operation to verify it can handle
the target 500 MB/s throughput (125 MS/s × 2 bytes × 2 channels).

This benchmark:
- Tests with realistic frame sizes (512 lines × 796 pixels)
- Measures throughput in MB/s
- Tests cold start (JIT compilation) vs warm runs
- Profiles different buffer sizes
- Identifies bottlenecks
"""

import sys
import os
import time
import numpy as np

# Add pyscanbox to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pyscanbox.acquisition import reshape


def generate_synthetic_buffer(lines_per_frame, pixels_per_line, channels=2):
    """Generate synthetic interleaved PMT data.
    
    Args:
        lines_per_frame: Number of lines per frame
        pixels_per_line: Number of pixels per line
        channels: Number of PMT channels (default 2)
        
    Returns:
        NumPy array of uint16 with interleaved channel data
    """
    total_samples = lines_per_frame * pixels_per_line * channels
    
    # Generate random 14-bit PMT data
    pmt_data = np.random.randint(0, 2**14, size=total_samples, dtype=np.uint16)
    
    # Shift left by 2 to simulate how Alazar packs data
    # (14-bit PMT in bits 15:2, sync signals in bits 1:0)
    buffer = (pmt_data << 2).astype(np.uint16)
    
    # Add some sync signals in LSB bits (alternating pattern)
    for i in range(0, len(buffer), 2):
        buffer[i] |= 0b01  # Frame sync on channel A
    for i in range(1, len(buffer), 2):
        buffer[i] |= 0b10  # Line sync on channel B
    
    return buffer


def benchmark_single_frame(lines_per_frame, pixels_per_line, num_iterations=100):
    """Benchmark reshape operation for a single frame size.
    
    Args:
        lines_per_frame: Number of lines per frame
        pixels_per_line: Number of pixels per line
        num_iterations: Number of iterations to average over
        
    Returns:
        Dict with benchmark results
    """
    print(f"\n{'='*70}")
    print(f"Benchmarking: {lines_per_frame} lines × {pixels_per_line} pixels")
    print(f"{'='*70}")
    
    # Generate test buffer
    buffer = generate_synthetic_buffer(lines_per_frame, pixels_per_line)
    buffer_size_bytes = buffer.nbytes
    buffer_size_mb = buffer_size_bytes / (1024 * 1024)
    
    print(f"Buffer size: {buffer_size_bytes:,} bytes ({buffer_size_mb:.2f} MB)")
    print(f"Total samples: {len(buffer):,}")
    
    # Cold start (first run includes JIT compilation)
    print("\n[Cold Start - includes JIT compilation]")
    start_time = time.perf_counter()
    result_cold = reshape.reshape_pmt_data_emulation(buffer, lines_per_frame, pixels_per_line)
    cold_time = time.perf_counter() - start_time
    
    print(f"  Time: {cold_time*1000:.2f} ms")
    print(f"  Output shape: {result_cold.shape}")
    
    # Verify output
    assert result_cold.shape == (2, lines_per_frame, pixels_per_line), "Output shape mismatch"
    assert result_cold.dtype == np.uint16, "Output dtype mismatch"
    
    # Warm runs (JIT compiled, realistic performance)
    print(f"\n[Warm Runs - {num_iterations} iterations]")
    times = []
    
    for i in range(num_iterations):
        start_time = time.perf_counter()
        result = reshape.reshape_pmt_data_emulation(buffer, lines_per_frame, pixels_per_line)
        elapsed = time.perf_counter() - start_time
        times.append(elapsed)
    
    times = np.array(times)
    
    # Calculate statistics
    mean_time = np.mean(times)
    std_time = np.std(times)
    min_time = np.min(times)
    max_time = np.max(times)
    median_time = np.median(times)
    
    # Calculate throughput
    mean_throughput_mbs = buffer_size_mb / mean_time
    min_throughput_mbs = buffer_size_mb / max_time  # Worst case
    max_throughput_mbs = buffer_size_mb / min_time  # Best case
    
    # Print results
    print(f"  Mean time: {mean_time*1000:.3f} ms (± {std_time*1000:.3f} ms)")
    print(f"  Median time: {median_time*1000:.3f} ms")
    print(f"  Min time: {min_time*1000:.3f} ms")
    print(f"  Max time: {max_time*1000:.3f} ms")
    print(f"\n  Mean throughput: {mean_throughput_mbs:.1f} MB/s")
    print(f"  Best case: {max_throughput_mbs:.1f} MB/s")
    print(f"  Worst case: {min_throughput_mbs:.1f} MB/s")
    
    # Target comparison
    target_mbs = 500.0
    percentage = (mean_throughput_mbs / target_mbs) * 100
    
    if mean_throughput_mbs >= target_mbs:
        status = "✓ PASS"
    else:
        status = "✗ FAIL"
    
    print(f"\n  Target: {target_mbs:.1f} MB/s")
    print(f"  Status: {status} ({percentage:.1f}% of target)")
    
    return {
        'lines': lines_per_frame,
        'pixels': pixels_per_line,
        'buffer_size_mb': buffer_size_mb,
        'cold_time_ms': cold_time * 1000,
        'mean_time_ms': mean_time * 1000,
        'std_time_ms': std_time * 1000,
        'mean_throughput_mbs': mean_throughput_mbs,
        'min_throughput_mbs': min_throughput_mbs,
        'max_throughput_mbs': max_throughput_mbs,
        'percentage_of_target': percentage,
        'passes_target': mean_throughput_mbs >= target_mbs
    }


def benchmark_continuous_acquisition(lines_per_frame, pixels_per_line, 
                                     num_frames=1000, target_fps=30):
    """Simulate continuous acquisition to test sustained throughput.
    
    Args:
        lines_per_frame: Number of lines per frame
        pixels_per_line: Number of pixels per line
        num_frames: Number of frames to process
        target_fps: Target frame rate (for comparison)
        
    Returns:
        Dict with benchmark results
    """
    print(f"\n{'='*70}")
    print(f"Continuous Acquisition Benchmark")
    print(f"{'='*70}")
    print(f"Processing {num_frames} frames @ {lines_per_frame}×{pixels_per_line}")
    
    # Generate test buffer (reuse for all frames)
    buffer = generate_synthetic_buffer(lines_per_frame, pixels_per_line)
    buffer_size_mb = buffer.nbytes / (1024 * 1024)
    
    # Warmup
    reshape.reshape_pmt_data_emulation(buffer, lines_per_frame, pixels_per_line)

    # Process frames
    start_time = time.perf_counter()

    for i in range(num_frames):
        result = reshape.reshape_pmt_data_emulation(buffer, lines_per_frame, pixels_per_line)
    
    total_time = time.perf_counter() - start_time
    
    # Calculate stats
    total_data_mb = buffer_size_mb * num_frames
    mean_throughput_mbs = total_data_mb / total_time
    achieved_fps = num_frames / total_time
    time_per_frame_ms = (total_time / num_frames) * 1000
    
    print(f"\n  Total time: {total_time:.2f} s")
    print(f"  Total data: {total_data_mb:.1f} MB")
    print(f"  Mean throughput: {mean_throughput_mbs:.1f} MB/s")
    print(f"  Time per frame: {time_per_frame_ms:.3f} ms")
    print(f"  Achieved frame rate: {achieved_fps:.1f} fps")
    print(f"  Target frame rate: {target_fps:.1f} fps")
    
    target_mbs = 500.0
    if mean_throughput_mbs >= target_mbs and achieved_fps >= target_fps:
        status = "✓ PASS"
    else:
        status = "✗ FAIL"
    
    print(f"\n  Status: {status}")
    
    return {
        'num_frames': num_frames,
        'total_time_s': total_time,
        'total_data_mb': total_data_mb,
        'mean_throughput_mbs': mean_throughput_mbs,
        'time_per_frame_ms': time_per_frame_ms,
        'achieved_fps': achieved_fps,
        'target_fps': target_fps,
        'passes_target': mean_throughput_mbs >= target_mbs and achieved_fps >= target_fps
    }


def main():
    """Run comprehensive reshape benchmarks."""
    print("="*70)
    print("PYSCANBOX RESHAPE PERFORMANCE BENCHMARK")
    print("="*70)
    print(f"Target: 500 MB/s (125 MS/s × 2 bytes × 2 channels)")
    print(f"NumPy version: {np.__version__}")
    
    try:
        import numba
        print(f"Numba version: {numba.__version__}")
    except ImportError:
        print("ERROR: Numba not installed!")
        return
    
    results = []
    
    # Test 1: Standard Scanbox frame size
    print("\n\n" + "="*70)
    print("TEST 1: Standard Frame Size (512×796)")
    print("="*70)
    result = benchmark_single_frame(512, 796, num_iterations=100)
    results.append(result)
    
    # Test 2: Smaller frame (for faster scanning)
    print("\n\n" + "="*70)
    print("TEST 2: Small Frame Size (256×512)")
    print("="*70)
    result = benchmark_single_frame(256, 512, num_iterations=100)
    results.append(result)
    
    # Test 3: Larger frame (higher resolution)
    print("\n\n" + "="*70)
    print("TEST 3: Large Frame Size (1024×1024)")
    print("="*70)
    result = benchmark_single_frame(1024, 1024, num_iterations=50)
    results.append(result)
    
    # Test 4: Continuous acquisition simulation
    result = benchmark_continuous_acquisition(512, 796, num_frames=1000, target_fps=30)
    
    # Summary
    print("\n\n" + "="*70)
    print("BENCHMARK SUMMARY")
    print("="*70)
    
    print(f"\n{'Frame Size':<20} {'Throughput':<15} {'Status':<10} {'% Target':<10}")
    print("-"*70)
    
    for r in results:
        frame_size = f"{r['lines']}×{r['pixels']}"
        throughput = f"{r['mean_throughput_mbs']:.1f} MB/s"
        status = "✓ PASS" if r['passes_target'] else "✗ FAIL"
        percentage = f"{r['percentage_of_target']:.1f}%"
        print(f"{frame_size:<20} {throughput:<15} {status:<10} {percentage:<10}")
    
    # Overall verdict
    all_pass = all(r['passes_target'] for r in results)
    
    print("\n" + "="*70)
    if all_pass:
        print("✓ ALL TESTS PASSED - Ready for 500 MB/s acquisition!")
    else:
        print("✗ SOME TESTS FAILED - Optimization needed")
        print("\nRecommendations:")
        print("  - Consider parallel processing with numba.prange")
        print("  - Optimize memory layout (ensure contiguous arrays)")
        print("  - Profile with line_profiler for bottlenecks")
        print("  - Consider C++ extension if Python can't reach target")
    print("="*70)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nBenchmark interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
