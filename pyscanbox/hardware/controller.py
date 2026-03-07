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
        ETL Current (ID 48):  [48, b1, b2] (Optotune ETL current 0-1760;
                              b1/b2 encode a 16-bit word with 0b0111 prefix
                              in the upper nibble, see sb/sb_current.m)

Reference:
    Original MATLAB implementation: sb/sb_open.m, sb/sb_setframe.m,
    sb/sb_setline.m, sb/sb_setmag.m, sb/sb_pockels.m, sb/sb_deadband.m,
    sb/sb_shutter.m, sb/sb_mirror.m, sb/sb_scan.m, sb/sb_abort.m,
    sb/sb_gain0.m, sb/sb_gain1.m, sb/sb_current.m

Example:
    >>> import pyscanbox.hardware.controller
    >>> controller = pyscanbox.hardware.controller.ScanboxController(config)
    >>> controller.open()
    >>> controller.set_pockels(base=50, active=100)
    >>> controller.set_shutter(open=True)
"""

import time
from typing import Optional


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
    CMD_ETL = 48  # Electrically tunable lens (Optotune) current

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
        CMD_ETL: 'set_etl_current',
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
        if cmd_id == ScanboxController.CMD_ETL:
            # Decode 16-bit encoded value: bits 15-12 are always 0b0111
            current = ((param1 & 0x0F) << 8) | param2
            return f'set_etl_current(current={current})'
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
