"""High-speed data reshaping for PMT data.

This module contains optimized functions for reshaping interleaved 16-bit
PMT data from the Alazar digitizer. The reshaping must handle ~500 MB/s
throughput, so performance is critical.

The data from Alazar is interleaved 14-bit samples packed into 16-bit words
(wire format: ``adc_14bit << 2 | lsb_bits``).  In Scanbox, LSB[0] (bit 0) is
always zero (disabled) and LSB[1] (bit 1) carries an external TTL event signal
on AUX_IN[1].  Both LSB bits are preserved in the output, exactly as MATLAB's
``alazarReshapeCData2.c`` does — they are never stripped.

Two acquisition modes are supported:

**Emulation mode (raw_mode=False, default):**
  The mock Alazar pre-delivers already-shaped data at
  ``samples_per_buffer = lines × pixels × 2``.  ``reshape_pmt_data_emulation()``
  de-interleaves the two channels, preserving the 16-bit wire format of
  each sample (range 0–65532).  Output is byte-compatible with
  ``reshape_pmt_data()``.

**Raw hardware mode (raw_mode=True):**
  The real Alazar (and raw-mode mock) delivers ``samples_per_line`` raw ADC
  samples per channel per line (e.g. 5000 for unidirectional scanning at
  80.18 MHz laser / 7930 Hz resonant mirror).  Each raw sample corresponds to
  a non-uniform position along the scan line due to the resonant mirror's
  sinusoidal velocity.

  ``compute_pixel_lut()`` computes the arccosine pixel LUT that maps each of
  the ``pixels_per_line`` (796) output pixels to a base raw-sample index.
  ``reshape_pmt_data()`` then averages 4 consecutive raw samples per
  output pixel for both PMT channels.

  This matches the MATLAB pipeline in ``pixel_lut_2.m`` +
  ``alazarReshapeCData2.c``.

Uses Numba JIT compilation for performance matching MATLAB MEX files.

Reference:
    Original MATLAB implementation: core/alazarReshapeCData2.c,
    core/pixel_lut_2.m

Example:
    >>> import numpy as np
    >>> from pyscanbox.acquisition import reshape
    >>> # Emulation mode (pre-shaped buffer):
    >>> buf = np.zeros(512 * 796 * 2, dtype=np.uint16)
    >>> frame = reshape.reshape_pmt_data_emulation(buf, 512, 796)
    >>> # Raw hardware mode:
    >>> lut = reshape.compute_pixel_lut(796, laser_freq=80180000, res_freq=7930)
    >>> buf_raw = np.zeros(512 * 5000 * 2, dtype=np.uint16)
    >>> frame = reshape.reshape_pmt_data(buf_raw, 512, 796, lut)
"""

import numpy as np
import numba


@numba.njit(nogil=True, cache=True)
def reshape_pmt_data_emulation(buffer: np.ndarray, lines_per_frame: int,
                               pixels_per_line: int) -> np.ndarray:
    """De-interleave pre-shaped PMT data (emulation / non-raw mode).

    Used in emulation mode where the mock Alazar delivers one already-shaped
    wire-format sample per output pixel per channel (buffer size =
    ``lines × pixels × 2``).  De-interleaves channel A (even indices) and
    channel B (odd indices), preserving the full 16-bit wire format of each
    sample.

    Wire format: ``bits 15:2 = 14-bit ADC value; bit 1 = LSB[1] (TTL event);
    bit 0 = LSB[0] (always 0 in Scanbox)``.  Neither LSB bit is stripped,
    matching the behaviour of ``alazarReshapeCData2.c`` and
    ``reshape_pmt_data_raw()``.

    Args:
        buffer: uint16 buffer from mock Alazar (interleaved channels, one
            sample per output pixel).  Shape: ``(lines × pixels × 2,)``.
        lines_per_frame: Number of lines per frame.
        pixels_per_line: Number of pixels per line.

    Returns:
        uint16 array of shape ``(2, lines_per_frame, pixels_per_line)``.
        Values are in 16-bit wire format (0–65532), identical in range and
        encoding to the output of ``reshape_pmt_data()``.

    Note:
        This function is JIT-compiled with Numba for maximum performance.
    """
    # Get dimensions
    total_samples = len(buffer)
    channels = 2  # PMT channels
    samples_per_channel = total_samples // channels
    
    # Allocate output array
    output = np.zeros((channels, lines_per_frame, pixels_per_line),
                     dtype=np.uint16)
    
    # De-interleave channels, preserving 16-bit wire format.
    # Channel A at even indices, Channel B at odd indices.
    sample_idx = 0

    for line in range(lines_per_frame):
        for pixel in range(pixels_per_line):
            if sample_idx < samples_per_channel:
                # Channel A (even index) — preserve wire format, no bit-stripping
                output[0, line, pixel] = buffer[sample_idx * 2]

                # Channel B (odd index)
                output[1, line, pixel] = buffer[sample_idx * 2 + 1]

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
        reshaped_data: Reshaped data from reshape_pmt_data_emulation() or reshape_pmt_data()

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


def extract_raw_sync_bits(buffer: np.ndarray, lines_per_frame: int,
                          samples_per_line: int) -> np.ndarray:
    """Extract frame- and line-sync bits from a raw Alazar line buffer.

    The Alazar card embeds two hardware sync signals in the two LSBs of each
    acquired sample (see ``configure_lsb_outputs()``).  These bits are only
    meaningful in the raw interleaved buffer — they are lost during the
    four-sample averaging performed by ``reshape_pmt_data()``.

    Sync bits are read from the **very first interleaved sample** of each
    line (``buffer[line_start]``, which is channel-A sample 0 of that line).
    The PSoC5 line-trigger fires at the beginning of each acquisition window,
    so the sync flags are reliably present at sample index 0.

    Note: the first ``lut_base[0]`` raw samples of each line (≈ 112 for
    standard parameters) are in the "dead zone" before the leftmost output
    pixel.  These samples are discarded by ``reshape_pmt_data()`` but
    they carry the sync markers, which is why this function reads them
    directly from the raw buffer.

    Args:
        buffer: Raw uint16 buffer from the Alazar, 1-D, length
            ``lines_per_frame × samples_per_line × 2`` (channels
            interleaved, line-major order).
        lines_per_frame: Number of scan lines per frame (e.g. 512).
        samples_per_line: Raw ADC samples per channel per line (e.g. 10112).

    Returns:
        uint8 array of shape ``(lines_per_frame, 2)`` where column 0 is
        LSB0 (frame-sync, AUX_IN[0]) and column 1 is LSB1 (line-sync,
        AUX_IN[1]), extracted from sample 0 of each line.
    """
    sync = np.empty((lines_per_frame, 2), dtype=np.uint8)
    stride = samples_per_line * 2   # interleaved samples per line
    for line in range(lines_per_frame):
        first_sample = int(buffer[line * stride])
        sync[line, 0] = first_sample & 0x01   # bit 0 — LSB0 / frame-sync
        sync[line, 1] = (first_sample >> 1) & 0x01  # bit 1 — LSB1 / line-sync
    return sync


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


def compute_pixel_lut(n_pixels: int, laser_freq: float,
                      res_freq: float) -> np.ndarray:
    """Compute the arccosine pixel LUT for resonant-scanner raw data.

    The resonant mirror scans sinusoidally, so raw ADC samples are not
    uniformly spaced in image space.  This function computes, for each of the
    ``n_pixels`` output pixels, the 0-indexed position of the first of four
    consecutive raw ADC samples that are averaged to produce that pixel.

    Translation of ``pixel_lut_2.m``:

    .. code-block:: matlab

        ncol  = 796;
        nsamp = round(sbconfig.lasfreq / sbconfig.resfreq);  % ≈ 10112
        M     = ncol + 2;
        n     = acos(linspace(1, -1, M)) * nsamp / (2*pi);
        n     = n(2:end-1);           % remove endpoints
        S     = floor(n) - 1;         % MATLAB 1-indexed base sample

    The ``-1`` in MATLAB (which is 1-indexed) translates to ``-2`` in Python
    (0-indexed), giving the same 0-indexed position.

    Args:
        n_pixels: Number of output pixels per line (e.g. 796).
        laser_freq: Laser repetition frequency in Hz (e.g. 80_180_000).
        res_freq: Resonant mirror frequency in Hz (e.g. 7930).

    Returns:
        Integer array of shape ``(n_pixels,)`` giving the 0-indexed base raw
        sample index for each output pixel.  Each pixel averages samples
        ``[lut[i], lut[i]+1, lut[i]+2, lut[i]+3]``.
    """
    nsamp = round(laser_freq / res_freq)     # samples per half-period ≈ 10112
    angles = np.arccos(np.linspace(1.0, -1.0, n_pixels + 2))[1:-1]  # (n_pixels,)
    n = angles * nsamp / (2.0 * np.pi)
    # MATLAB: S = floor(n) - 1  (1-indexed).  Python 0-indexed: floor(n) - 2.
    lut_base = np.floor(n).astype(np.int32) - 2
    return lut_base


def apply_bidirectional_correction(frame: np.ndarray,
                                   pixel_shift: int = 0) -> np.ndarray:
    """Apply bidirectional alignment correction to a reshaped frame.

    Backward scan lines (odd-indexed lines 1, 3, 5, …) are acquired while
    the resonant mirror sweeps in reverse, so their pixels arrive in
    reversed spatial order.  This function corrects for that by:

    1. **Flipping** each backward line horizontally (always required in
       bidirectional mode).
    2. **Shifting** the flipped backward lines by ``pixel_shift`` pixels
       to compensate for residual timing offset — the ``bishift``
       calibration parameter from ``sbconfig.bishift`` in MATLAB.

    The ``pixel_shift`` value is per-magnification.  Typical values span
    −10 (low zoom) to +58 (high zoom) and must be measured on real
    hardware (see Milestone 3.8).  In emulation the correction is still
    applied so alignment can be verified visually before HIL testing.

    Args:
        frame: Reshaped data array of shape ``(channels, lines, pixels)``
            dtype uint16, as returned by ``reshape_pmt_data_emulation()`` or
            ``reshape_pmt_data()``.  Modified in-place.
        pixel_shift: Integer pixel shift applied to backward lines after
            flipping.  Positive = shift right, negative = shift left.
            Zero = flip only (no timing correction).

    Returns:
        The same ``frame`` array after in-place modification.

    Reference:
        MATLAB ``pixel_lut_bi_2.m`` line
        ``postIdx(:,:,2:2:end) = postIdx(:,end:-1:1,2:2:end);`` for the
        flip; ``sbconfig.bishift`` for the shift calibration.
    """
    # Step 1: Flip odd (backward) lines horizontally to correct reverse-scan
    # order.  np.flip returns a view; the assignment copies into the frame.
    frame[:, 1::2, :] = frame[:, 1::2, ::-1].copy()

    # Step 2: Apply sub-pixel timing correction (bishift).
    if pixel_shift != 0:
        backward = np.roll(frame[:, 1::2, :], pixel_shift, axis=2)
        # Zero out the wrap-around edge introduced by np.roll so that
        # edge pixels do not bleed from the opposite side of the image.
        if pixel_shift > 0:
            backward[:, :, :pixel_shift] = 0
        else:  # pixel_shift < 0
            backward[:, :, pixel_shift:] = 0
        frame[:, 1::2, :] = backward

    return frame


@numba.njit(nogil=True, cache=True)
def reshape_pmt_data(buffer: np.ndarray, lines_per_frame: int,
                         pixels_per_line: int,
                         lut_base: np.ndarray) -> np.ndarray:
    """Reshape raw Alazar buffer using the arccosine pixel LUT.

    For each output pixel, averages 4 consecutive raw ADC samples from both
    PMT channels.  This corrects the sinusoidal scan-velocity distortion of
    the resonant mirror, matching ``alazarReshapeCData2.c``.

    Buffer layout (from Alazar NPT streaming mode):
        Interleaved channels, line-major order::

            [chA_s0_l0, chB_s0_l0, chA_s1_l0, chB_s1_l0, ...,
             chA_s(N-1)_l(L-1), chB_s(N-1)_l(L-1)]

        where N = ``samples_per_line`` and L = ``lines_per_frame``.

    Args:
        buffer: 1-D uint16 array of length
            ``lines_per_frame × samples_per_line × 2`` (channels interleaved).
        lines_per_frame: Number of scan lines per frame (e.g. 512).
        pixels_per_line: Number of output pixels per line (e.g. 796).
        lut_base: 0-indexed base raw-sample index for each pixel, shape
            ``(pixels_per_line,)`` int32.  Computed by ``compute_pixel_lut()``.

    Returns:
        uint16 array of shape ``(2, lines_per_frame, pixels_per_line)``.
        Values are in wire format: bits 15:2 carry the averaged 14-bit ADC
        value, but bits 1:0 are **not** reliable sync flags — they reflect the
        low-order arithmetic bits of the four-sample sum and should be ignored.
        See ``extract_raw_sync_bits()`` if you need sync information.

    Note:
        This function is JIT-compiled with Numba.  Pass ``lut_base`` as a
        contiguous ``np.int32`` array for best performance.

    Reference:
        See ``core/alazarReshapeCData2.c`` (inner loop) and
        ``core/pixel_lut_2.m`` (LUT construction).
    """
    samples_per_line = len(buffer) // (lines_per_frame * 2)
    output = np.zeros((2, lines_per_frame, pixels_per_line), dtype=np.uint16)

    for line in range(lines_per_frame):
        line_start = line * samples_per_line * 2   # byte offset into buffer
        for px in range(pixels_per_line):
            s = lut_base[px]                       # base raw sample (0-indexed)
            # Interleaved layout: chA at 2*s, chB at 2*s+1
            sum_a = (np.uint32(buffer[line_start + 2 * s])
                     + np.uint32(buffer[line_start + 2 * (s + 1)])
                     + np.uint32(buffer[line_start + 2 * (s + 2)])
                     + np.uint32(buffer[line_start + 2 * (s + 3)]))
            sum_b = (np.uint32(buffer[line_start + 2 * s + 1])
                     + np.uint32(buffer[line_start + 2 * (s + 1) + 1])
                     + np.uint32(buffer[line_start + 2 * (s + 2) + 1])
                     + np.uint32(buffer[line_start + 2 * (s + 3) + 1]))
            # >> 2 averages 4 samples (divide by 4), matching alazarReshapeCData2.c
            # which does exactly `(unsigned short int)(tmp >>2)`.
            # NOTE: The hardware sync bits (bits 1:0) from the raw samples are
            # NOT preserved by this operation.  Each raw sample is
            # (ADC_14bit << 2) | sync_2bit.  Summing 4 such values and shifting
            # right by 2 produces bits 1:0 that reflect the low-order ADC bits
            # of the sum, NOT the original sync flags.  Sync information must be
            # extracted from the raw buffer BEFORE calling this function (e.g.
            # from buffer[line_start] for the first sample of each line).
            output[0, line, px] = np.uint16(sum_a >> 2)
            output[1, line, px] = np.uint16(sum_b >> 2)

    return output
