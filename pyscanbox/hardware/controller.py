# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Main Scanbox controller interface for Pockels, mirror, and scan control.

This module provides serial communication with the main Scanbox controller
(PSoC 5LP) at 1,000,000 baud using 3-byte command packets.

Protocol:
    All commands are 3-byte packets: [Command_ID, Param1, Param2]

    Commands:
        Frame Count (ID 1):   [1, high_byte, low_byte] (16-bit frame count)
        Lines (ID 2):         [2, high_byte, low_byte] (16-bit line count)
        Magnification (ID 3): [3, 0, mag] (0-12; MATLAB popup index minus 1)
        Scan (ID 4):          [4, 0, 1] (start) or [4, 0, 0] (stop)
        Epi/2P Mirror (ID 5): [5, 0, 0] (2P) or [5, 0, 1] (Epi)
        PMT0 Gain (ID 6):     [6, 0, gain] (0-255)
        PMT1 Gain (ID 7):     [7, 0, gain] (0-255)
        Pockels Cell (ID 8):  [8, base_power, active_power]
        Pockels Deadband (ID 9): [9, left, right] (pixels blanked at line margins)
        Shutter (ID 16):      [16, 0, 1] (Open) or [16, 0, 0] (Close)
                              Original system: controls a Uniblitz shutter.
                              On some rigs (e.g., shutter wired to
                              LASER SHUTTER output), this command has no
                              effect; the shutter opens with Scan Control
                              (ID 4) instead.
        Unidirectional (ID 33): [33, 0, 0] — PSoC5 triggers Alazar only on
                              the forward (odd-numbered) sweep.  Default mode.
        Bidirectional (ID 34):  [34, 0, 0] — PSoC5 triggers Alazar on both
                              forward and return sweeps, doubling effective
                              frame rate.  Must be combined with a per-
                              magnification bishift correction in software.
        ETL Current (ID 48):  [48, b1, b2] (Optotune ETL current 0-1760;
                              b1/b2 encode a 16-bit word with 0b0111 prefix
                              in the upper nibble, see sb/sb_current.m)
        TTL Mask (ID 64):     [64, 0, imask] — selects which external TTL
                              inputs generate timestamped events.
                              imask=0: both disabled; 1: TTL0 only;
                              2: TTL1 only; 3: both.
                              When a TTL event fires the PSoC5 sends a 5-byte
                              packet back on the same serial port:
                              [frame_low, frame_high, line_low, line_high,
                               event_id], where event_id encodes which input
                              triggered (1=TTL0, 2=TTL1, 3=both).
                              event_id=255 is a sentinel meaning
                              "acquisition complete".

Reference:
    Original MATLAB implementation: sb/sb_open.m, sb/sb_setframe.m,
    sb/sb_setline.m, sb/sb_setmag.m, sb/sb_pockels.m, sb/sb_deadband.m,
    sb/sb_shutter.m, sb/sb_mirror.m, sb/sb_scan.m, sb/sb_abort.m,
    sb/sb_gain0.m, sb/sb_gain1.m, sb/sb_current.m,
    sb/sb_unidirectional.m, sb/sb_bidirectional.m, sb/sb_imask.m,
    core/serialcb.m, core/scanbox.m (sb_callback function)

Example:
    >>> import pyscanbox.hardware.controller
    >>> controller = pyscanbox.hardware.controller.ScanboxController(config)
    >>> controller.open()
    >>> controller.set_pockels(base=50, active=100)
    >>> controller.set_shutter(open=True)
"""

import threading
import time
from typing import List, Optional, Tuple


def _get_serial_module(use_emulation: bool):
    """Get appropriate serial module based on emulation setting.
    
    Args:
        use_emulation: If True, use mock serial
        
    Returns:
        Serial module (either serial or mock_serial)
    """
    if use_emulation:
        from pyscanbox.emulator import mock_serial
        return mock_serial
    else:
        import serial
        return serial


class ScanboxController:
    """Interface to main Scanbox controller box.

    This class handles serial communication with the PSoC 5LP-based
    controller for Pockels cell, shutter, and epi/2P mirror control.

    Attributes:
        port: Serial port object
        com_port: COM port name (e.g., 'COM3')
        baud_rate: Baud rate (1,000,000 for Scanbox)
        timeout: Serial communication timeout in seconds
    """

    # Command IDs
    CMD_FRAME_COUNT = 1
    CMD_LINES = 2
    CMD_MAGNIFICATION = 3
    CMD_SCAN = 4
    CMD_MIRROR = 5
    CMD_GAIN0 = 6
    CMD_GAIN1 = 7
    CMD_POCKELS = 8
    CMD_DEADBAND = 9
    CMD_SHUTTER = 16
    CMD_WARMUP_DELAY = 11  # [11, 0, delay] — resonant scanner warmup delay (×10 ms)
    CMD_UNIDIRECTIONAL = 33  # Set PSoC5 to trigger on forward sweep only
    CMD_BIDIRECTIONAL = 34   # Set PSoC5 to trigger on both forward and return sweeps
    CMD_POCKELS_RANGE = 13         # [13, vdac, pga] — set DAC/PGA range
    CMD_ETL = 48  # Electrically tunable lens (Optotune) current
    CMD_OPTOWAVE_ENTRY = 21   # [21, high, low] — write one entry to ETL waveform table (sb_optowave)
    CMD_OPTOPERIOD = 22       # [22, period, 0] — set ETL waveform period in frames (sb_optoperiod)
    CMD_OPTOTUNE_ACTIVE = 23  # [23, active, 0] — enable (1) / disable (0) ETL waveform (sb_optotune_active)
    CMD_OPTOWAVE_RESET = 24   # [24, 0, 0] — reset waveform table index to 0 (sb_optowave_init)
    CMD_TTL_MASK = 64  # TTL interrupt mask (which external TTL inputs fire events)
    CMD_POCKELS_LUT_ENTRY = 0x43    # [0x43, idx, val] — set one LUT entry
    CMD_POCKELS_LUT_IDENTITY = 0x44 # [0x44, 0, 0] — reset LUT to identity
    CMD_HSYNC_SIGN = 0x80           # [0x80, val, 0] — flip horizontal scan axis
    CMD_GALVO_DV = 0x66             # [0x66, dv, 0] — galvo voltage step per line
    CMD_MAG_X_GAIN_BASE = 0xB0      # [0xB0+i, xh, xl] — resonant (X) gain for zoom i
    CMD_MAG_Y_GAIN_BASE = 0xC0      # [0xC0+i, yh, yl] — galvo (Y) gain for zoom i
    CMD_VERSION = 120               # [120, 0xAA, 0x55] — firmware version query

    # Maximum galvo differential voltage value (hardware limit).
    # Reference: sbconfig.dv_galvo = 64; % dv per line (64 is the maximum) -- don't touch!
    DV_GALVO_MAX = 64

    # Default resonant/galvo aspect-ratio multiplier.
    # Compensates for the resonant mirror having a different voltage-to-angle
    # curve than the galvo.  Reference: sbconfig.gain_resonant_mult = 1.42
    GAIN_RESONANT_MULT_DEFAULT = 1.42

    # Default per-zoom galvo gain table: 13 values logspace(1, 8, 13).
    # Reference: sbconfig.gain_galvo = logspace(log10(1), log10(8), 13)
    # These are the single source of truth consumed by the scanner gains
    # dialog and the startup gain-override sequence.
    GAIN_GALVO_DEFAULT = (
        1.0, 1.189, 1.414, 1.682, 2.0, 2.378, 2.828,
        3.364, 4.0, 4.757, 5.657, 6.727, 8.0,
    )

    # Number of bytes in one TTL event packet returned by the PSoC5 over serial.
    # Packet layout: [frame_low, frame_high, line_low, line_high, event_id]
    # event_id: 1=TTL0, 2=TTL1, 3=both, 255=acquisition-complete sentinel.
    # Reference: core/serialcb.m and core/scanbox.m (sb_callback function).
    TTL_EVENT_BYTES = 5

    # Poll interval (seconds) for the background TTL-event reader thread.
    _TTL_POLL_INTERVAL = 0.005  # 5 ms — fine-grained at ~125 µs line period

    # ETL current range (hardware units, ~61.5 µA per count).
    # These are the single source of truth for the ETL range used by
    # set_etl_current() validation and by GUI widgets.
    ETL_CURRENT_MIN = 0
    ETL_CURRENT_MAX = 1760
    ETL_CURRENT_MID = (ETL_CURRENT_MIN + ETL_CURRENT_MAX) // 2

    # Magnification labels for the 13 discrete zoom levels (index 0–12).
    # Derived from sbconfig.gain_galvo = logspace(log10(1), log10(8), 13) in
    # scanbox_config.m, formatted as "%.1f" (same as MATLAB's sprintf).
    # Index 0 = largest FOV (1.0x); index 12 = smallest FOV (8.0x).
    # This is the single source of truth consumed by GUI combo boxes.
    MAG_LABELS = (
        '1.0x', '1.2x', '1.4x', '1.7x', '2.0x', '2.4x', '2.8x',
        '3.4x', '4.0x', '4.8x', '5.7x', '6.7x', '8.0x',
    )

    # Resonant mirror frequency (Hz). Source: sbconfig.resfreq in scanbox_config.m.
    # Frame-rate formula (scanbox.m line 503):
    #   frame_rate = resfreq / nlines * (2 - scanmode)
    # where scanmode = 1 (unidirectional) or 0 (bidirectional).
    # Examples at 512 lines:
    #   Unidirectional: 7930 / 512 * 1 = 15.49 Hz  (~15 Hz in practice)
    #   Bidirectional:  7930 / 512 * 2 = 30.98 Hz
    RESONANT_FREQ = 7930

    # Human-readable names for each command ID, used by log callbacks.
    CMD_NAMES = {
        CMD_FRAME_COUNT: 'set_frame_count',
        CMD_LINES: 'set_lines',
        CMD_MAGNIFICATION: 'set_magnification',
        CMD_SCAN: 'scan',
        CMD_MIRROR: 'set_mirror',
        CMD_GAIN0: 'set_pmt_gain',
        CMD_GAIN1: 'set_pmt_gain',
        CMD_POCKELS: 'set_pockels',
        CMD_DEADBAND: 'set_pockels_deadband',
        CMD_SHUTTER: 'set_shutter',
        CMD_WARMUP_DELAY: 'set_warmup_delay',
        CMD_UNIDIRECTIONAL: 'set_scan_mode',
        CMD_BIDIRECTIONAL: 'set_scan_mode',
        CMD_POCKELS_RANGE: 'set_pockels_range',
        CMD_ETL: 'set_etl_current',
        CMD_OPTOWAVE_ENTRY: 'etl_waveform_entry',
        CMD_OPTOPERIOD: 'set_etl_waveform_period',
        CMD_OPTOTUNE_ACTIVE: 'set_etl_waveform_active',
        CMD_OPTOWAVE_RESET: 'etl_waveform_reset',
        CMD_TTL_MASK: 'set_ttl_mask',
        CMD_POCKELS_LUT_ENTRY: 'set_pockels_lut_entry',
        CMD_POCKELS_LUT_IDENTITY: 'set_pockels_lut_identity',
        CMD_HSYNC_SIGN: 'set_hsync_sign',
        CMD_GALVO_DV: 'set_galvo_dv',
        CMD_VERSION: 'get_version',
    }

    @staticmethod
    def calculate_frame_rate(lines_per_frame: int, bidirectional: bool = False) -> float:
        """Calculate scan frame rate in Hz.

        Matches the MATLAB formula from scanbox.m:
            frame_rate = sbconfig.resfreq / nlines * (2 - scanmode)
        where scanmode = 1 for unidirectional, 0 for bidirectional.

        Args:
            lines_per_frame: Number of scan lines per frame.
            bidirectional: True for bidirectional scan mode.

        Returns:
            Frame rate in Hz.
        """
        multiplier = 2 if bidirectional else 1
        return ScanboxController.RESONANT_FREQ / lines_per_frame * multiplier

    @staticmethod
    def format_command(cmd_id: int, param1: int, param2: int) -> str:
        """Decode a 3-byte packet as a human-readable function call string.

        This is the single authoritative decoder for the Scanbox serial
        protocol.  It is used by logging adapters so the displayed call
        (including argument names and values) always matches the actual
        bytes on the wire.

        Args:
            cmd_id: Command ID byte.
            param1: First parameter byte.
            param2: Second parameter byte.

        Returns:
            Human-readable call string, e.g.
            ``'set_pockels(base=0, active=100)'``.
        """
        if cmd_id == ScanboxController.CMD_FRAME_COUNT:
            frames = (param1 << 8) | param2
            return f'set_frame_count(frames={frames})'
        if cmd_id == ScanboxController.CMD_LINES:
            lines = (param1 << 8) | param2
            return f'set_lines(lines={lines})'
        if cmd_id == ScanboxController.CMD_MAGNIFICATION:
            return f'set_magnification(magnification={param2})'
        if cmd_id == ScanboxController.CMD_SCAN:
            func = 'start_scan' if param2 else 'stop_scan'
            return f'{func}()'
        if cmd_id == ScanboxController.CMD_MIRROR:
            mode = 'epi' if param2 else '2p'
            return f"set_mirror(mode='{mode}')"
        if cmd_id == ScanboxController.CMD_GAIN0:
            return f'set_pmt_gain(pmt_id=0, value={param2})'
        if cmd_id == ScanboxController.CMD_GAIN1:
            return f'set_pmt_gain(pmt_id=1, value={param2})'
        if cmd_id == ScanboxController.CMD_POCKELS:
            return f'set_pockels(base={param1}, active={param2})'
        if cmd_id == ScanboxController.CMD_DEADBAND:
            return f'set_pockels_deadband(left={param1}, right={param2})'
        if cmd_id == ScanboxController.CMD_SHUTTER:
            open_val = 'True' if param2 else 'False'
            return f'set_shutter(open={open_val})'
        if cmd_id == ScanboxController.CMD_UNIDIRECTIONAL:
            return "set_scan_mode(bidirectional=False)"
        if cmd_id == ScanboxController.CMD_BIDIRECTIONAL:
            return "set_scan_mode(bidirectional=True)"
        if cmd_id == ScanboxController.CMD_ETL:
            # Decode 16-bit encoded value: bits 15-12 are always 0b0111
            current = ((param1 & 0x0F) << 8) | param2
            return f'set_etl_current(current={current})'
        if cmd_id == ScanboxController.CMD_OPTOWAVE_ENTRY:
            val = (param1 << 8) | param2
            return f'etl_waveform_entry(value={val})'
        if cmd_id == ScanboxController.CMD_OPTOPERIOD:
            return f'set_etl_waveform_period(frames={param1})'
        if cmd_id == ScanboxController.CMD_OPTOTUNE_ACTIVE:
            return f'set_etl_waveform_active(active={bool(param1)})'
        if cmd_id == ScanboxController.CMD_OPTOWAVE_RESET:
            return 'etl_waveform_reset()'
        if cmd_id == ScanboxController.CMD_TTL_MASK:
            return f'set_ttl_mask(imask={param2})'
        if cmd_id == ScanboxController.CMD_POCKELS_RANGE:
            return f'set_pockels_range(vdac={param1}, pga={param2})'
        if cmd_id == ScanboxController.CMD_POCKELS_LUT_ENTRY:
            return f'set_pockels_lut_entry(idx={param1}, val={param2})'
        if cmd_id == ScanboxController.CMD_POCKELS_LUT_IDENTITY:
            return 'set_pockels_lut_identity()'
        if cmd_id == ScanboxController.CMD_HSYNC_SIGN:
            return f'set_hsync_sign(flip={bool(param1)})'
        if cmd_id == ScanboxController.CMD_WARMUP_DELAY:
            return f'set_warmup_delay(delay={param2})'
        if cmd_id == ScanboxController.CMD_GALVO_DV:
            return f'set_galvo_dv(dv={param1})'
        if cmd_id == ScanboxController.CMD_VERSION:
            return 'get_version() '
        base_x = ScanboxController.CMD_MAG_X_GAIN_BASE
        base_y = ScanboxController.CMD_MAG_Y_GAIN_BASE
        if base_x <= cmd_id < base_x + 13:
            value = param1 + param2 / 10.0
            return f'set_mag_x_gain(index={cmd_id - base_x}, value={value:.1f})'
        if base_y <= cmd_id < base_y + 13:
            value = param1 + param2 / 10.0
            return f'set_mag_y_gain(index={cmd_id - base_y}, value={value:.1f})'
        name = ScanboxController.CMD_NAMES.get(cmd_id, f'cmd_{cmd_id}')
        return f'{name}(param1={param1}, param2={param2})'

    def __init__(self, config: dict, on_command=None):
        """Initialize Scanbox controller.

        Args:
            config: Configuration dictionary with controller settings.
                Must contain 'controller' key with COM port and parameters.
            on_command: Optional callback fired after every serial write.
                Signature: ``on_command(com_port, cmd_id, param1, param2)``.
                Useful for logging and testing without subclassing.
        """
        self.config = config
        self.com_port = config['controller']['com_port']
        self.baud_rate = config['controller']['baud_rate']
        self.timeout = config['controller']['timeout']
        self.on_command = on_command
        
        # Check if emulation is enabled
        self.use_emulation = config.get('emulation', {}).get('enabled', False)
        self.emulation_verbose = config.get('emulation', {}).get('verbose', False)
        
        self.port: Optional[object] = None
        self.is_open = False
        
        # State tracking
        self.frame_count = 0
        self.lines_per_frame = 0
        self.magnification = 0  # Index 0 = minimum zoom (MATLAB popup item 1)
        self.current_pockels = {'base': 0, 'active': 0}
        self.pockels_deadband = {'left': 0, 'right': 0}
        self.shutter_open = False
        self.mirror_mode = '2p'  # '2p' or 'epi'
        self.scan_running = False
        self.pmt_gains = [0, 0]  # hardware gain values (0-255) for PMT0 and PMT1
        self.etl_current = 0  # ETL current (0-1760)
        self.etl_waveform_active = False  # True when PSoC5 is cycling ETL waveform
        self.ttl_mask = 0  # interrupt mask (0=disabled)
        self.hsync_sign = 0  # horizontal sync polarity (0=normal, 1=flip)
        self.pockels_range = (1, 2)  # (vdac, pga) DAC/PGA range

        # TTL event reader thread state
        self._ttl_events: List[Tuple[int, int, int]] = []
        self._ttl_events_lock = threading.Lock()
        self._ttl_thread: Optional[threading.Thread] = None
        self._ttl_stop_event: Optional[threading.Event] = None

    def open(self) -> None:
        """Open serial connection to controller.

        Opens the serial port with appropriate settings for Scanbox
        controller communication.

        Reference:
            See sb/sb_open.m for serial port settings.

        Raises:
            serial.SerialException: If port cannot be opened.
        """
        # Get appropriate serial module
        serial_module = _get_serial_module(self.use_emulation)
        
        self.port = serial_module.Serial(
            port=self.com_port,
            baudrate=self.baud_rate,
            timeout=self.timeout,
            bytesize=serial_module.EIGHTBITS if not self.use_emulation else 8,
            parity=serial_module.PARITY_NONE if not self.use_emulation else 'N',
            stopbits=serial_module.STOPBITS_ONE if not self.use_emulation else 1,
        )
        
        # Configure emulation verbosity if using mock
        if self.use_emulation and hasattr(self.port, 'verbose'):
            self.port.verbose = self.emulation_verbose
        
        self.is_open = True
        
        # Wait for controller to reset after serial connection (real hardware only)
        if not self.use_emulation:
            time.sleep(2.0)
        
        # Flush any startup data
        self.port.reset_input_buffer()
        self.port.reset_output_buffer()

    def close(self) -> None:
        """Close serial connection to controller."""
        if self.port is not None and self.port.is_open:
            self.port.close()
        
        self.is_open = False

    def _send_command(self, cmd_id: int, param1: int, param2: int) -> None:
        """Send 3-byte command packet to controller.

        Args:
            cmd_id: Command ID byte
            param1: First parameter byte
            param2: Second parameter byte

        Raises:
            RuntimeError: If port is not open.
            ValueError: If parameters are out of range.
        """
        if not self.is_open or self.port is None:
            raise RuntimeError("Controller port not open. Call open() first.")
        
        # Validate byte values
        if not (0 <= cmd_id <= 255):
            raise ValueError(f"Command ID must be 0-255, got {cmd_id}")
        if not (0 <= param1 <= 255):
            raise ValueError(f"Parameter 1 must be 0-255, got {param1}")
        if not (0 <= param2 <= 255):
            raise ValueError(f"Parameter 2 must be 0-255, got {param2}")
        
        # Send 3-byte packet
        packet = bytes([cmd_id, param1, param2])
        self.port.write(packet)
        if self.on_command is not None:
            self.on_command(self.com_port, cmd_id, param1, param2)

    def get_version(self) -> str:
        """Query the firmware version from the controller.

        Returns:
            Firmware version string (e.g., '1.5').
            Returns 'Unknown' if the controller does not respond or is closed.
            
        Raises:
            RuntimeError: If port is not open.
        """
        if not self.is_open or self.port is None:
            raise RuntimeError("Controller port not open. Call open() first.")
            
        self._send_command(self.CMD_VERSION, 0xAA, 0x55)
        response = self.port.read(3)
        if len(response) == 3:
            return f"{response[1]}.{response[2]}"
        return "Unknown"

    def set_frame_count(self, frames: int) -> None:
        """Set the number of frames to acquire.

        Args:
            frames: Number of frames (0-65535, 16-bit).

        Reference:
            See sb/sb_setframe.m

        Raises:
            ValueError: If frames is outside 0-65535.
        """
        if not (0 <= frames <= 65535):
            raise ValueError(f"Frame count must be 0-65535, got {frames}")
        high = (frames >> 8) & 0xFF
        low = frames & 0xFF
        self._send_command(self.CMD_FRAME_COUNT, high, low)
        self.frame_count = frames

    def set_lines(self, lines: int) -> None:
        """Set the number of scan lines per frame.

        Args:
            lines: Lines per frame (0-65535, 16-bit).

        Reference:
            See sb/sb_setline.m

        Raises:
            ValueError: If lines is outside 0-65535.
        """
        if not (0 <= lines <= 65535):
            raise ValueError(f"Lines per frame must be 0-65535, got {lines}")
        high = (lines >> 8) & 0xFF
        low = lines & 0xFF
        self._send_command(self.CMD_LINES, high, low)
        self.lines_per_frame = lines

    def set_magnification(self, magnification: int) -> None:
        """Set the magnification (zoom) level.

        The value is a 0-based index into 13 discrete zoom levels that
        map to fixed scan-mirror amplitudes inside the PSoC5 firmware.
        It corresponds to the MATLAB popup ``Value - 1`` (popup is
        1-indexed, 13 items).  Index 0 is the largest field-of-view
        (lowest zoom); index 12 is the smallest FOV (highest zoom).

        Args:
            magnification: Zoom-level index (0-12).

        Reference:
            See sb/sb_setmag.m; MATLAB sends
            ``sb_setmag(popup.Value - 1)``.

        Raises:
            ValueError: If magnification is outside 0-12.
        """
        if not (0 <= magnification <= 12):
            raise ValueError(
                f"Magnification must be 0-12, got {magnification}"
            )
        self._send_command(self.CMD_MAGNIFICATION, 0, magnification)
        self.magnification = magnification

    def set_pockels(self, base: int, active: int) -> None:
        """Set Pockels cell power levels.

        Args:
            base: Base power level (0-255). Power during flyback/idle.
            active: Active power level (0-255). Power during line scan.

        Reference:
            See sb/sb_pockels.m
        """
        self._send_command(self.CMD_POCKELS, base, active)
        self.current_pockels = {'base': base, 'active': active}

    def set_pockels_deadband(self, left: int, right: int) -> None:
        """Set the Pockels cell deadband (blanking) regions.

        Defines the number of pixels at the left and right margins of each
        scan line where the laser is blanked to avoid edge artifacts.

        Args:
            left: Left deadband width in pixels (0-255).
            right: Right deadband width in pixels (0-255).

        Reference:
            See sb/sb_deadband.m

        Raises:
            ValueError: If either value is outside 0-255.
        """
        if not (0 <= left <= 255):
            raise ValueError(f"Left deadband must be 0-255, got {left}")
        if not (0 <= right <= 255):
            raise ValueError(f"Right deadband must be 0-255, got {right}")
        self._send_command(self.CMD_DEADBAND, left, right)
        self.pockels_deadband = {'left': left, 'right': right}

    def set_shutter(self, open: bool) -> None:
        """Set laser shutter state.

        Args:
            open: True to open shutter, False to close.

        Reference:
            See sb/sb_shutter.m
        """
        param2 = 1 if open else 0
        self._send_command(self.CMD_SHUTTER, 0, param2)
        self.shutter_open = open

    def set_scan_mode(self, bidirectional: bool) -> None:
        """Set the PSoC5 scan trigger mode.

        Sends either CMD_UNIDIRECTIONAL [33, 0, 0] or CMD_BIDIRECTIONAL
        [34, 0, 0] to configure whether the PSoC5 issues an Alazar line
        trigger on the forward sweep only (unidirectional) or on both the
        forward and return sweeps (bidirectional).

        This must be called before starting acquisition whenever the scan
        mode changes.  In MATLAB it is called once at startup from
        ``scanbox.m`` based on ``sbconfig.unidirectional``.

        Args:
            bidirectional: True to enable bidirectional mode ([34, 0, 0]),
                False for unidirectional ([33, 0, 0]).

        Reference:
            See ``sb/sb_unidirectional.m`` and ``sb/sb_bidirectional.m``.
        """
        if bidirectional:
            self._send_command(self.CMD_BIDIRECTIONAL, 0, 0)
        else:
            self._send_command(self.CMD_UNIDIRECTIONAL, 0, 0)

    def set_pmt_gain(self, pmt_id: int, value: int) -> None:
        """Set the gain for a PMT channel.

        Args:
            pmt_id: PMT channel index (0 or 1).
            value: Gain level (0-255).

        Reference:
            See sb/sb_gain0.m and sb/sb_gain1.m

        Raises:
            ValueError: If pmt_id is not 0 or 1, or value is out of range.
        """
        if pmt_id not in (0, 1):
            raise ValueError(f"pmt_id must be 0 or 1, got {pmt_id}")
        if not (0 <= value <= 255):
            raise ValueError(f"PMT gain value must be 0-255, got {value}")
        cmd_id = self.CMD_GAIN0 if pmt_id == 0 else self.CMD_GAIN1
        self._send_command(cmd_id, 0, value)
        self.pmt_gains[pmt_id] = value

    def set_mirror(self, mode: str) -> None:
        """Set epi/2P mirror position using Firgelli actuator.

        Args:
            mode: Mirror mode, either '2p' or 'epi'.

        Reference:
            See sb/sb_mirror.m

        Raises:
            ValueError: If mode is not '2p' or 'epi'.
        """
        if mode not in ['2p', 'epi']:
            raise ValueError(f"Mode must be '2p' or 'epi', got '{mode}'")
        
        param2 = 0 if mode == '2p' else 1
        self._send_command(self.CMD_MIRROR, 0, param2)
        self.mirror_mode = mode

    def get_current_pockels(self) -> dict:
        """Get current Pockels cell settings.

        Returns:
            Dictionary with 'base' and 'active' power levels.
        """
        return self.current_pockels.copy()

    def get_shutter_state(self) -> bool:
        """Get current shutter state.

        Returns:
            True if shutter is open, False if closed.
        """
        return self.shutter_open

    def get_mirror_mode(self) -> str:
        """Get current mirror mode.

        Returns:
            Current mirror mode ('2p' or 'epi').
        """
        return self.mirror_mode

    def start_scan(self) -> None:
        """Start scanning.

        Sends command to start the resonant scanner and galvo mirrors.
        Does NOT start PMTs or data acquisition - this only starts
        the physical scanning mechanism.

        Reference:
            See sb/sb_scan.m (sends [4, 0, 1])
        """
        self._send_command(self.CMD_SCAN, 0, 1)
        self.scan_running = True

    def stop_scan(self) -> None:
        """Stop scanning.

        Sends abort command to stop the scanning system.

        Reference:
            See sb/sb_abort.m
        """
        self._send_command(self.CMD_SCAN, 0, 0)
        self.scan_running = False

    def get_scan_state(self) -> bool:
        """Get current scan state.

        Returns:
            True if scanning is running, False if stopped.
        """
        return self.scan_running

    def set_etl_current(self, current: int) -> None:
        """Set the electrically tunable lens (Optotune ETL) current.

        The ETL current controls axial focus position without mechanical
        objective movement.  The value is encoded as a 16-bit word with
        a fixed ``0b0111`` prefix in the upper nibble, matching the
        hardware convention used by the PSoC5 DAC for the ETL driver.

        Encoding (from ``sb/sb_current.m``)::

            encoded = 0x7000 | (current & 0x0FFF)
            b1 = (encoded >> 8) & 0xFF   # upper byte
            b2 =  encoded       & 0xFF   # lower byte
            send [48, b1, b2]

        Args:
            current: ETL current level (0–1760 arbitrary units, ~61.5 µA
                per count).

        Reference:
            See sb/sb_current.m

        Raises:
            ValueError: If current is outside 0–1760.
        """
        if not (self.ETL_CURRENT_MIN <= current <= self.ETL_CURRENT_MAX):
            raise ValueError(
                f'ETL current must be {self.ETL_CURRENT_MIN}-'
                f'{self.ETL_CURRENT_MAX}, got {current}'
            )
        encoded = 0x7000 | (current & 0x0FFF)
        b1 = (encoded >> 8) & 0xFF
        b2 = encoded & 0xFF
        self._send_command(self.CMD_ETL, b1, b2)
        self.etl_current = current

    def upload_etl_waveform(self, values: list) -> None:
        """Upload a focus-stacking ETL waveform table to the PSoC5.

        Resets the waveform table index (CMD_OPTOWAVE_RESET), then uploads
        each ETL current value as one 3-byte packet (CMD_OPTOWAVE_ENTRY),
        and finally sets the waveform period in frames (CMD_OPTOPERIOD).

        The PSoC5 will cycle through the table automatically on each frame
        trigger once ``set_etl_waveform_active(True)`` is called.  The table
        represents a step waveform: each entry is held for exactly one frame.
        To hold a position for N frames, repeat the same value N times.

        Encoding (from ``sb/sb_optowave.m`` and ``sb/sb_optowave_init.m``)::

            reset:  [24, 0, 0]
            entry:  [21, high_byte, low_byte]  for each uint16 ETL value
            period: [22, len(values), 0]

        Args:
            values: List of ETL current values (each 0–1760).  Length must
                be 1–255 (PSoC5 period register is one byte).

        Raises:
            ValueError: If values is empty, longer than 255, or contains
                out-of-range entries.
        """
        if not (1 <= len(values) <= 255):
            raise ValueError(
                f'ETL waveform must have 1–255 entries, got {len(values)}'
            )
        for i, v in enumerate(values):
            if not (self.ETL_CURRENT_MIN <= v <= self.ETL_CURRENT_MAX):
                raise ValueError(
                    f'ETL waveform entry {i} out of range '
                    f'({self.ETL_CURRENT_MIN}–{self.ETL_CURRENT_MAX}): {v}'
                )

        self._send_command(self.CMD_OPTOWAVE_RESET, 0, 0)
        for v in values:
            high = (v >> 8) & 0xFF
            low = v & 0xFF
            self._send_command(self.CMD_OPTOWAVE_ENTRY, high, low)
        self._send_command(self.CMD_OPTOPERIOD, len(values), 0)

    def set_etl_waveform_active(self, active: bool) -> None:
        """Enable or disable autonomous ETL waveform cycling.

        When active, the PSoC5 advances through the uploaded waveform table
        on every frame trigger, producing the focus-stacking depth sequence.
        When inactive, direct ``set_etl_current()`` commands control the lens.

        Reference:
            See ``sb/sb_optotune_active.m`` (sends ``[23, active, 0]``).

        Args:
            active: True to enable waveform cycling, False to disable.
        """
        self._send_command(self.CMD_OPTOTUNE_ACTIVE, 1 if active else 0, 0)
        self.etl_waveform_active = active

    def set_ttl_mask(self, imask: int) -> None:
        """Set the interrupt mask that controls which TTL inputs fire events.

        Tells the PSoC5 which of its two external TTL input lines (TTL0 and
        TTL1) should be monitored and generate timestamped event packets.
        When an enabled TTL input transitions, the PSoC5 sends a 5-byte
        packet back over the same serial port::

            [frame_low, frame_high, line_low, line_high, event_id]

        The packet encodes the current frame and line at which the event
        occurred.  ``event_id`` values: 1 = TTL0, 2 = TTL1, 3 = both
        fired within the same frame/line.  ``event_id = 255`` is a sentinel
        that signals acquisition-complete (not a user TTL event).

        Args:
            imask: Interrupt mask value.
                0 = both inputs disabled.
                1 = TTL0 only (rising edge).
                2 = TTL1 only (rising and falling edges).
                3 = both TTL0 and TTL1.

        Reference:
            See sb/sb_imask.m: ``fwrite(sb, uint8([64 0 v]))``.

        Raises:
            ValueError: If imask is not 0–3.
        """
        if imask not in (0, 1, 2, 3):
            raise ValueError(f'imask must be 0, 1, 2, or 3, got {imask}')
        self._send_command(self.CMD_TTL_MASK, 0, imask)
        self.ttl_mask = imask

    def set_hsync_sign(self, flip: int) -> None:
        """Set horizontal sync polarity (scan direction).

        Flipping the scan direction is useful for diagnosing Pockels cell
        phase/timing asymmetry: if the dark side of the image flips with
        the scan direction, the cause is a Pockels timing issue in the
        PSoC5 firmware rather than an optical/mechanical asymmetry.

        Args:
            flip: 0 = normal scan direction, 1 = flip horizontal axis.

        Reference:
            See sb/sb_hsync_sign.m: ``fwrite(sb, uint8([0x80, val, 0]))``.
            Config key: ``scanner.hsync_sign`` in YAML config.

        Raises:
            ValueError: If flip is not 0 or 1.
        """
        if flip not in (0, 1):
            raise ValueError(f'hsync_sign must be 0 or 1, got {flip}')
        self._send_command(self.CMD_HSYNC_SIGN, flip, 0)
        self.hsync_sign = flip

    def set_warmup_delay(self, delay: int) -> None:
        """Set the resonant scanner warmup delay.

        Tells the PSoC5 to wait before firing the first line trigger after
        ``start_scan()`` is called, giving the resonant mirror time to reach
        its stable oscillation amplitude.  Without this delay the first
        several frames will have distorted geometry.

        Args:
            delay: Warmup period in units of 10 ms (e.g. 50 = 500 ms).
                Valid range: 0–255.

        Reference:
            See sb/sb_warmup_delay.m: ``fwrite(sb, uint8([11 0 p]))``.\n            Config key: ``scanner.warmup_delay`` in YAML config.

        Raises:
            ValueError: If delay is outside 0–255.
        """
        if not (0 <= delay <= 255):
            raise ValueError(f'warmup_delay must be 0-255, got {delay}')
        self._send_command(self.CMD_WARMUP_DELAY, 0, delay)
        self.warmup_delay = delay

    def set_pockels_range(self, vdac: int, pga: int) -> None:
        """Set Pockels cell DAC voltage range and PGA gain.

        The lab default is vdac=1, pga=2.  Only change this if the laser
        wavelength or Pockels cell hardware changes.

        Args:
            vdac: DAC range selector byte (0–255).
            pga:  PGA gain selector byte (0–255).

        Reference:
            See sb/sb_pockels_range.m: ``fwrite(sb, uint8([13, r(1), r(2)]))``.
            Config key: ``pockels.range`` in YAML config.
        """
        self._send_command(self.CMD_POCKELS_RANGE, vdac, pga)
        self.pockels_range = (vdac, pga)

    def set_pockels_lut_identity(self) -> None:
        """Reset the Pockels cell LUT to the identity mapping.

        Sends a single ``[0x44, 0, 0]`` packet.  The PSoC5 resets all
        256 LUT entries to the identity (linear voltage, non-linear
        power).  Use this when no calibration LUT is available.

        Reference:
            See sb/sb_pockels_lut_identity.m.
        """
        self._send_command(self.CMD_POCKELS_LUT_IDENTITY, 0, 0)

    def set_pockels_lut(self, lut: list) -> None:
        """Upload the 256-entry Pockels cell linearisation LUT to the PSoC5.

        Sends one ``[0x43, idx, val]`` packet per entry (256 packets total).
        The LUT maps each requested power level (0–255) to the DAC voltage
        required to produce linearly-scaled laser output, compensating for
        the Pockels cell's sinusoidal voltage-to-power response.

        The LUT is 0-indexed (indices 0–255).  The original MATLAB
        implementation uses 1-indexed arrays and sends indices 1–256
        (``core/scanbox.m`` lines 269–273).  Python uses 0-indexed to
        avoid uint8 overflow on the 256th entry.

        Args:
            lut: List of exactly 256 integers in the range 0–255.

        Reference:
            See sb/sb_pockels_lut.m: ``fwrite(sb, uint8([0x43, idx, val]))``.
            Calibration procedure: ``core/pockels_920nm.m``.
            Config key: ``pockels.lut`` in YAML config.

        Raises:
            ValueError: If lut does not have exactly 256 entries, or any
                entry is outside 0–255.
        """
        if len(lut) != 256:
            raise ValueError(
                f'Pockels LUT must have exactly 256 entries, got {len(lut)}'
            )
        for idx, val in enumerate(lut):
            if not (0 <= val <= 255):
                raise ValueError(
                    f'LUT entry {idx} must be 0-255, got {val}'
                )
            self._send_command(self.CMD_POCKELS_LUT_ENTRY, idx, val)

    # ------------------------------------------------------------------
    # Scanner gain / amplitude control
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_gain(x: float) -> tuple:
        """Encode a float gain value as the two-byte PSoC5 wire format.

        The PSoC5 expects the integer part in byte 1 and the tenths digit
        in byte 2: ``xh = floor(x)``, ``xl = floor((x - xh) * 10)``.
        Only one decimal digit of precision is representable.

        Reference: sb/sb_set_mag_x_i.m, sb/sb_set_mag_y_i.m

        Args:
            x: Gain value (non-negative float with up to one decimal digit).

        Returns:
            Tuple (xh, xl) of byte values (each 0–255).
        """
        xh = int(x)
        xl = int((x - xh) * 10)
        return xh, xl

    def set_galvo_dv(self, dv: int) -> None:
        """Set the galvo mirror voltage step per scan line.

        Controls how far the Y-axis (galvo) mirror advances between
        consecutive scan lines.  The hardware maximum is 64; the standard
        value used in all normal configurations is 64.

        Args:
            dv: Differential voltage value (0–64).

        Reference:
            See sb/sb_galvo_dv.m: ``fwrite(sb, uint8([0x66, val, 0]))``.
            Config key: ``scanner.dv_galvo`` (default 64).

        Raises:
            ValueError: If dv is outside 0–DV_GALVO_MAX.
        """
        if not (0 <= dv <= self.DV_GALVO_MAX):
            raise ValueError(
                f'dv_galvo must be 0–{self.DV_GALVO_MAX}, got {dv}'
            )
        self._send_command(self.CMD_GALVO_DV, dv, 0)

    def set_mag_x_gain(self, index: int, value: float) -> None:
        """Set the resonant (X-axis) gain for one zoom level.

        Encodes *value* using the PSoC5 float format (integer part + tenths
        digit) and sends ``[0xB0 + index, xh, xl]``.

        Args:
            index: Zoom-level index (0–12; 0 = widest FOV).
            value: Resonant-axis gain amplitude (float, e.g. 1.42–11.36).

        Reference:
            See sb/sb_set_mag_x_i.m.
            Config key: ``scanner.gain_galvo`` + ``scanner.gain_resonant_mult``.

        Raises:
            ValueError: If index is outside 0–12 or value is negative.
        """
        if not (0 <= index <= 12):
            raise ValueError(f'Zoom index must be 0–12, got {index}')
        if value < 0:
            raise ValueError(f'Gain value must be non-negative, got {value}')
        xh, xl = self._encode_gain(value)
        self._send_command(self.CMD_MAG_X_GAIN_BASE + index, xh, xl)

    def set_mag_y_gain(self, index: int, value: float) -> None:
        """Set the galvo (Y-axis) gain for one zoom level.

        Encodes *value* using the PSoC5 float format (integer part + tenths
        digit) and sends ``[0xC0 + index, yh, yl]``.

        Args:
            index: Zoom-level index (0–12; 0 = widest FOV).
            value: Galvo-axis gain amplitude (float, e.g. 1.0–8.0).

        Reference:
            See sb/sb_set_mag_y_i.m.
            Config key: ``scanner.gain_galvo``.

        Raises:
            ValueError: If index is outside 0–12 or value is negative.
        """
        if not (0 <= index <= 12):
            raise ValueError(f'Zoom index must be 0–12, got {index}')
        if value < 0:
            raise ValueError(f'Gain value must be non-negative, got {value}')
        yh, yl = self._encode_gain(value)
        self._send_command(self.CMD_MAG_Y_GAIN_BASE + index, yh, yl)

    def update_scanner_gains(
        self,
        gain_galvo: list,
        gain_resonant: list,
        dv_galvo: int = 64,
    ) -> None:
        """Upload the full per-zoom-level gain table to the PSoC5.

        Mirrors the ``gain_override`` block in ``core/scanbox.m``:

        1. Send the galvo differential voltage (``[0x66, dv_galvo, 0]``).
        2. For each of the 13 zoom levels, send the resonant (X) gain
           (``[0xB0 + i, xh, xl]``).
        3. For each of the 13 zoom levels, send the galvo (Y) gain
           (``[0xC0 + i, yh, yl]``).

        Args:
            gain_galvo: 13-element sequence of Y-axis galvo gain values
                (one per zoom level, logspaced 1.0–8.0 by default).
            gain_resonant: 13-element sequence of X-axis resonant gain
                values (typically ``gain_resonant_mult × gain_galvo``).
            dv_galvo: Galvo voltage step per line (default 64, hardware max).

        Reference:
            MATLAB: ``core/scanbox.m`` lines 253–262, ``sb/sb_update_gains.m``.
            Config keys: ``scanner.gain_override``, ``scanner.dv_galvo``,
            ``scanner.gain_galvo``, ``scanner.gain_resonant_mult``.

        Raises:
            ValueError: If either gain list does not have exactly 13 entries.
        """
        if len(gain_galvo) != 13:
            raise ValueError(
                f'gain_galvo must have 13 entries, got {len(gain_galvo)}'
            )
        if len(gain_resonant) != 13:
            raise ValueError(
                f'gain_resonant must have 13 entries, got {len(gain_resonant)}'
            )
        self.set_galvo_dv(dv_galvo)
        for i, gx in enumerate(gain_resonant):
            self.set_mag_x_gain(i, gx)
        for i, gy in enumerate(gain_galvo):
            self.set_mag_y_gain(i, gy)

    # ------------------------------------------------------------------
    # TTL event reader
    # ------------------------------------------------------------------

    def start_ttl_reader(self) -> None:
        """Start the background thread that collects TTL event packets.

        The PSoC5 sends unsolicited 5-byte packets back on the controller
        serial port whenever a TTL event fires (see ``set_ttl_mask()``).
        This method starts a daemon thread that polls ``in_waiting``,
        reads complete 5-byte packets, and appends them to an internal
        list protected by a thread lock.

        Call ``stop_ttl_reader()`` before closing the serial port.
        Events can be retrieved with ``get_ttl_events()``.

        Note:
            Use ``clear_ttl_events()`` before each acquisition so events
            from a previous run are not mixed with the current one.
        """
        if self._ttl_thread is not None and self._ttl_thread.is_alive():
            return  # Reader already running
        self._ttl_stop_event = threading.Event()
        self._ttl_thread = threading.Thread(
            target=self._ttl_reader_loop,
            daemon=True,
            name='TTLEventReader',
        )
        self._ttl_thread.start()

    def stop_ttl_reader(self) -> None:
        """Stop the background TTL event reader thread.

        Signals the reader thread to exit and waits for it to finish
        (up to 1 second).  Safe to call even if the reader was never
        started.
        """
        if self._ttl_stop_event is not None:
            self._ttl_stop_event.set()
        if self._ttl_thread is not None:
            self._ttl_thread.join(timeout=1.0)
            self._ttl_thread = None
        self._ttl_stop_event = None

    def _ttl_reader_loop(self) -> None:
        """Background loop: read 5-byte TTL event packets from serial port.

        Runs until ``_ttl_stop_event`` is set.  Packets with
        ``event_id == 255`` are silently discarded (acquisition-complete
        sentinel).  All other complete packets are appended to
        ``_ttl_events``.
        """
        while not self._ttl_stop_event.is_set():
            try:
                if self.port is not None and self.is_open:
                    n_available = self.port.in_waiting
                    n_packets = n_available // self.TTL_EVENT_BYTES
                    if n_packets > 0:
                        raw = self.port.read(n_packets * self.TTL_EVENT_BYTES)
                        for i in range(n_packets):
                            chunk = raw[i * self.TTL_EVENT_BYTES:
                                        (i + 1) * self.TTL_EVENT_BYTES]
                            frame_num = chunk[0] + chunk[1] * 256
                            line_num = chunk[2] + chunk[3] * 256
                            event_id = chunk[4]
                            # 255 is the acquisition-complete sentinel —
                            # not a user TTL event; discard silently.
                            if event_id != 255:
                                with self._ttl_events_lock:
                                    self._ttl_events.append(
                                        (frame_num, line_num, event_id)
                                    )
            except Exception:  # noqa: BLE001 — best-effort background thread
                pass
            self._ttl_stop_event.wait(self._TTL_POLL_INTERVAL)

    def get_ttl_events(self) -> List[Tuple[int, int, int]]:
        """Return a snapshot of collected TTL events.

        Returns:
            List of ``(frame, line, event_id)`` tuples in arrival order.
            ``frame`` and ``line`` are the PSoC5 frame/line counters at the
            moment the event fired.  ``event_id`` is 1 (TTL0), 2 (TTL1),
            or 3 (both).
        """
        with self._ttl_events_lock:
            return list(self._ttl_events)

    def clear_ttl_events(self) -> None:
        """Discard all previously collected TTL events.

        Call this at the start of each acquisition so events from a prior
        run (e.g., a focus session) are not included in the saved metadata.
        """
        with self._ttl_events_lock:
            self._ttl_events.clear()