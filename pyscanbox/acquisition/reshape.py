"""High-speed data reshaping for PMT data.

This module contains optimized functions for reshaping interleaved 16-bit
PMT data from the Alazar digitizer. The reshaping must handle ~500 MB/s
throughput, so performance is critical.

The data from Alazar is interleaved 14-bit samples packed into 16-bit words.
The LSB bits contain frame/line sync information that must be extracted.

Uses Numba JIT compilation for performance matching MATLAB MEX files.

Reference:
    Original MATLAB implementation: core/alazarReshapeCData2.c

Example:
    >>> import numpy as np
    >>> from pyscanbox.acquisition import reshape
    >>> raw_buffer = np.zeros(1024, dtype=np.uint16)
    >>> reshaped = reshape.reshape_pmt_data(raw_buffer, 512, 796)
"""

import numpy as np
import numba


@numba.njit(nogil=True, cache=True)
def reshape_pmt_data(buffer: np.ndarray, lines_per_frame: int,
                     pixels_per_line: int) -> np.ndarray:
    """Reshape interleaved PMT data from Alazar digitizer.

    Takes raw 16-bit interleaved data from Alazar and reshapes it into
    a proper frame structure, extracting PMT data and sync signals.

    The Alazar outputs 16-bit words where:
        - Bits 15:2 contain 14-bit PMT data
        - Bits 1:0 contain LSB sync signals (frame/line timing)

    Args:
        buffer: Raw uint16 buffer from Alazar (interleaved channels)
        lines_per_frame: Number of lines per frame
        pixels_per_line: Number of pixels per line

    Returns:
        Reshaped numpy array with dimensions (channels, lines, pixels).
        For 2-channel acquisition: shape is (2, lines_per_frame, pixels_per_line)

    Note:
        This function is JIT-compiled with Numba for maximum performance.
        It must handle ~500 MB/s throughput without dropping frames.

    Reference:
        See core/alazarReshapeCData2.c for bit-shifting logic.
    """
    # Get dimensions
    total_samples = len(buffer)
    channels = 2  # PMT channels
    samples_per_channel = total_samples // channels
    
    # Allocate output array
    output = np.zeros((channels, lines_per_frame, pixels_per_line),
                     dtype=np.uint16)
    
    # De-interleave channels and extract 14-bit PMT data
    # Channel A at even indices, Channel B at odd indices
    sample_idx = 0
    
    for line in range(lines_per_frame):
        for pixel in range(pixels_per_line):
            if sample_idx < samples_per_channel:
                # Extract channel A (even index)
                # Shift right by 2 to get 14-bit PMT data
                output[0, line, pixel] = (buffer[sample_idx * 2] >> 2) & 0x3FFF
                
                # Extract channel B (odd index)
                output[1, line, pixel] = (buffer[sample_idx * 2 + 1] >> 2) & 0x3FFF
                
                sample_idx += 1
    
    return output


@numba.njit(nogil=True, cache=True)
def extract_sync_bits(buffer: np.ndarray) -> np.ndarray:
    """Extract LSB sync bits from raw buffer.

    The LSB bits (bits 1:0) contain frame and line synchronization
    information embedded in the data stream.

    Args:
        buffer: Raw uint16 buffer from Alazar

    Returns:
        Array of uint8 with sync bits (2 bits per sample).

    Reference:
        See core/configureLsb9440.m for LSB configuration.
    """
    sync_bits = np.zeros(len(buffer), dtype=np.uint8)
    
    for i in range(len(buffer)):
        # Extract bits 1:0
        sync_bits[i] = buffer[i] & 0x03
    
    return sync_bits


@numba.njit(nogil=True, cache=True)
def bit_shift_14_to_16(data: np.ndarray) -> np.ndarray:
    """Shift 14-bit data to full 16-bit range.

    For display and processing, it's often useful to scale 14-bit
    data (0-16383) to full 16-bit range (0-65535).

    Args:
        data: Array of 14-bit values in uint16

    Returns:
        Array scaled to 16-bit range.
    """
    # Shift left by 2 to use full 16-bit range
    return data << 2


def reshape_for_display(reshaped_data: np.ndarray) -> np.ndarray:
    """Prepare reshaped data for display.

    Averages channels and scales to 8-bit for visualization.

    Args:
        reshaped_data: Reshaped data from reshape_pmt_data()

    Returns:
        2D array ready for display (lines x pixels), uint8.
    """
    # Average channels
    if reshaped_data.shape[0] == 2:
        averaged = np.mean(reshaped_data, axis=0)
    else:
        averaged = reshaped_data[0]
    
    # Scale from 14-bit to 8-bit
    scaled = (averaged / 16384.0 * 255.0).astype(np.uint8)
    
    return scaled


def validate_buffer_size(buffer: np.ndarray, lines_per_frame: int,
                        pixels_per_line: int, channels: int = 2) -> bool:
    """Validate that buffer size matches expected dimensions.

    Args:
        buffer: Raw buffer from Alazar
        lines_per_frame: Expected lines per frame
        pixels_per_line: Expected pixels per line
        channels: Number of channels (default 2)

    Returns:
        True if buffer size is correct, False otherwise.
    """
    expected_samples = lines_per_frame * pixels_per_line * channels
    return len(buffer) == expected_samples
