# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Tests for pyscanbox.hardware.protocols.

Covers all encode/decode functions for the three wire formats used in
the Knobby system:

    PC ←→ Knobby (Arduino)   : parse_knobby_position_packet,
                                parse_knobby_command_packet, KNOBBY_CMD_NAMES
    PC ←→ Trinamic controller : build_tmcl_packet, parse_tmcl_command,
                                parse_tmcl_response, calculate_checksum
"""

import unittest
from pyscanbox.hardware import protocols
from pyscanbox.hardware.knobby import build_position_packet


# -- TMCL encode ----------------------------------------------------------------

class TestBuildTmclPacket(unittest.TestCase):
    """Tests for build_tmcl_packet()."""

    def test_mvp_packet_structure(self):
        """MVP packet has correct address, command, type, motor, and value."""
        packet = protocols.build_tmcl_packet('MVP', 0, 0, 1000)

        self.assertEqual(len(packet), 9)
        self.assertEqual(packet[0], 1)    # module address
        self.assertEqual(packet[1], 4)    # MVP command number
        self.assertEqual(packet[2], 0)    # type
        self.assertEqual(packet[3], 0)    # motor 0
        value = int.from_bytes(packet[4:8], byteorder='big')
        self.assertEqual(value, 1000)

    def test_gap_packet_fields(self):
        """GAP packet has correct command, type, and motor fields."""
        packet = protocols.build_tmcl_packet('GAP', 1, 2, 0)

        self.assertEqual(packet[1], 6)    # GAP command number
        self.assertEqual(packet[2], 1)    # type 1
        self.assertEqual(packet[3], 2)    # motor 2

    def test_negative_value_two_complement(self):
        """Negative values are encoded as unsigned 32-bit two's complement."""
        packet = protocols.build_tmcl_packet('MVP', 1, 0, -500)

        raw = int.from_bytes(packet[4:8], byteorder='big', signed=False)
        signed = raw - (1 << 32) if raw >= (1 << 31) else raw
        self.assertEqual(signed, -500)

    def test_checksum_is_sum_mod_256(self):
        """Checksum equals sum of first 8 bytes mod 256."""
        packet = protocols.build_tmcl_packet('MST', 0, 0, 0)

        expected = sum(packet[0:8]) % 256
        self.assertEqual(packet[8], expected)

    def test_all_standard_commands_build(self):
        """Every standard command string produces a valid 9-byte packet."""
        for cmd in ['ROR', 'ROL', 'MST', 'MVP', 'SAP', 'GAP']:
            with self.subTest(cmd=cmd):
                packet = protocols.build_tmcl_packet(cmd, 0, 0, 0)
                self.assertEqual(len(packet), 9)

    def test_invalid_command_raises(self):
        """Unknown command string raises ValueError."""
        with self.assertRaises(ValueError):
            protocols.build_tmcl_packet('INVALID', 0, 0, 0)


# -- TMCL checksum --------------------------------------------------------------

class TestCalculateChecksum(unittest.TestCase):
    """Tests for calculate_checksum()."""

    def test_zero_bytes(self):
        self.assertEqual(protocols.calculate_checksum(b'\x00' * 8), 0)

    def test_known_sum(self):
        # 1+2+3 = 6
        self.assertEqual(protocols.calculate_checksum(b'\x01\x02\x03'), 6)

    def test_overflow_wraps_to_byte(self):
        # 255 + 1 = 256 → 0
        self.assertEqual(protocols.calculate_checksum(b'\xff\x01'), 0)

    def test_matches_packet_checksum(self):
        """calculate_checksum on first 8 bytes matches the packet's byte 8."""
        packet = protocols.build_tmcl_packet('GAP', 1, 3, 9999)
        self.assertEqual(protocols.calculate_checksum(packet[:8]), packet[8])


# -- TMCL decode ----------------------------------------------------------------

class TestParseTmclResponse(unittest.TestCase):
    """Tests for parse_tmcl_response()."""

    def _make_response(self, status=100, command=6, value=0):
        r = bytearray(9)
        r[0] = 2   # reply address
        r[1] = 1   # module address
        r[2] = status
        r[3] = command
        if value < 0:
            value = (1 << 32) + value
        r[4] = (value >> 24) & 0xFF
        r[5] = (value >> 16) & 0xFF
        r[6] = (value >> 8)  & 0xFF
        r[7] =  value        & 0xFF
        r[8] = sum(r[:8]) % 256
        return bytes(r)

    def test_successful_response_fields(self):
        response = self._make_response(status=100, command=6, value=12345)
        parsed = protocols.parse_tmcl_response(response)

        self.assertEqual(parsed['status'], 100)
        self.assertEqual(parsed['value'], 12345)
        self.assertEqual(parsed['command'], 6)
        self.assertTrue(parsed['valid'])

    def test_invalid_checksum_flagged(self):
        response = bytearray(self._make_response(value=0))
        response[8] = (response[8] + 1) % 256   # corrupt checksum
        parsed = protocols.parse_tmcl_response(bytes(response))

        self.assertFalse(parsed['valid'])

    def test_negative_value(self):
        response = self._make_response(value=-500)
        parsed = protocols.parse_tmcl_response(response)

        self.assertEqual(parsed['value'], -500)


class TestParseTmclCommand(unittest.TestCase):
    """Tests for parse_tmcl_command() — symmetric counterpart to build_tmcl_packet."""

    def test_roundtrip_mvp(self):
        """parse_tmcl_command correctly decodes a packet built by build_tmcl_packet."""
        packet = protocols.build_tmcl_packet('MVP', 0, 1, 2000)
        parsed = protocols.parse_tmcl_command(packet)

        self.assertEqual(parsed['command_name'], 'MVP')
        self.assertEqual(parsed['command'], 4)
        self.assertEqual(parsed['cmd_type'], 0)
        self.assertEqual(parsed['motor'], 1)
        self.assertEqual(parsed['value'], 2000)
        self.assertTrue(parsed['valid'])

    def test_roundtrip_gap(self):
        packet = protocols.build_tmcl_packet('GAP', 1, 2, 0)
        parsed = protocols.parse_tmcl_command(packet)

        self.assertEqual(parsed['command_name'], 'GAP')
        self.assertEqual(parsed['cmd_type'], 1)
        self.assertEqual(parsed['motor'], 2)

    def test_negative_value(self):
        packet = protocols.build_tmcl_packet('MVP', 0, 0, -1000)
        parsed = protocols.parse_tmcl_command(packet)

        self.assertEqual(parsed['value'], -1000)
        self.assertTrue(parsed['valid'])

    def test_invalid_checksum_flagged(self):
        packet = bytearray(protocols.build_tmcl_packet('MST', 0, 0, 0))
        packet[8] = (packet[8] + 1) % 256
        parsed = protocols.parse_tmcl_command(bytes(packet))

        self.assertFalse(parsed['valid'])

    def test_unknown_command_number(self):
        """A command number not in TMCL_COMMANDS yields a 'cmd#N' name."""
        packet = bytearray(protocols.build_tmcl_packet('MST', 0, 0, 0))
        packet[1] = 99   # replace with unknown command number
        packet[8] = sum(packet[:8]) % 256
        parsed = protocols.parse_tmcl_command(bytes(packet))

        self.assertEqual(parsed['command_name'], 'cmd#99')

    def test_wrong_length_raises(self):
        with self.assertRaises(ValueError):
            protocols.parse_tmcl_command(b'\x00' * 8)


# -- Knobby position packet -----------------------------------------------------

class TestParseKnobbyPositionPacket(unittest.TestCase):
    """Tests for parse_knobby_position_packet()."""

    def test_positive_steps(self):
        # motor 2, +1000 steps little-endian
        data = bytes([2]) + (1000).to_bytes(4, byteorder='little', signed=True)
        p = protocols.parse_knobby_position_packet(data)

        self.assertEqual(p['motor_id'], 2)
        self.assertEqual(p['steps'], 1000)

    def test_negative_steps(self):
        data = bytes([1]) + (-500).to_bytes(4, byteorder='little', signed=True)
        p = protocols.parse_knobby_position_packet(data)

        self.assertEqual(p['motor_id'], 1)
        self.assertEqual(p['steps'], -500)

    def test_zero_steps(self):
        data = bytes([0]) + (0).to_bytes(4, byteorder='little', signed=True)
        p = protocols.parse_knobby_position_packet(data)

        self.assertEqual(p['steps'], 0)

    def test_roundtrip_with_build_position_packet(self):
        """parse_knobby_position_packet correctly decodes build_position_packet output."""
        for motor_id, steps in [(0, 128), (1, -256), (2, 0), (3, 32767)]:
            with self.subTest(motor_id=motor_id, steps=steps):
                raw = build_position_packet(motor_id, steps)
                p = protocols.parse_knobby_position_packet(raw)
                self.assertEqual(p['motor_id'], motor_id)
                self.assertEqual(p['steps'], steps)

    def test_wrong_length_raises(self):
        with self.assertRaises(ValueError):
            protocols.parse_knobby_position_packet(b'\x00' * 4)


# -- Knobby command packet ------------------------------------------------------

class TestParseKnobbyCommandPacket(unittest.TestCase):
    """Tests for parse_knobby_command_packet()."""

    def _make_packet(self, cmd_id, value):
        hi = (value >> 8) & 0xFF
        lo = value & 0xFF
        return bytes([0x01, 0xC8, 0x00, cmd_id, hi, lo, 0, 0, 0])

    def test_known_command_name(self):
        packet = self._make_packet(cmd_id=1, value=10)
        p = protocols.parse_knobby_command_packet(packet)

        self.assertEqual(p['cmd_id'], 1)
        self.assertEqual(p['cmd_name'], 'Move Y')
        self.assertEqual(p['value'], 10)
        self.assertTrue(p['valid_header'])

    def test_negative_value(self):
        # value = -10 as signed 16-bit big-endian
        value = -10 & 0xFFFF
        packet = self._make_packet(cmd_id=0, value=value)
        p = protocols.parse_knobby_command_packet(packet)

        self.assertEqual(p['value'], -10)

    def test_invalid_header_flagged(self):
        packet = bytes([0xFF, 0xFF, 0x00, 0, 0, 0, 0, 0, 0])
        p = protocols.parse_knobby_command_packet(packet)

        self.assertFalse(p['valid_header'])

    def test_unknown_cmd_id_gives_fallback_name(self):
        packet = self._make_packet(cmd_id=99, value=0)
        p = protocols.parse_knobby_command_packet(packet)

        self.assertEqual(p['cmd_name'], 'cmd#99')

    def test_wrong_length_raises(self):
        with self.assertRaises(ValueError):
            protocols.parse_knobby_command_packet(b'\x00' * 5)


# -- KNOBBY_CMD_NAMES dict ------------------------------------------------------

class TestKnobbyCmdNames(unittest.TestCase):
    """Tests for the KNOBBY_CMD_NAMES constant."""

    def test_move_axes_present(self):
        for cmd_id, expected_name in [(0, 'Move Z'), (1, 'Move Y'), (2, 'Move X')]:
            with self.subTest(cmd_id=cmd_id):
                self.assertEqual(protocols.KNOBBY_CMD_NAMES[cmd_id], expected_name)

    def test_zero_and_lock_present(self):
        self.assertIn(30, protocols.KNOBBY_CMD_NAMES)   # Zero XYZ
        self.assertIn(60, protocols.KNOBBY_CMD_NAMES)   # Lock
        self.assertIn(61, protocols.KNOBBY_CMD_NAMES)   # Unlock

    def test_all_values_are_strings(self):
        for cmd_id, name in protocols.KNOBBY_CMD_NAMES.items():
            with self.subTest(cmd_id=cmd_id):
                self.assertIsInstance(name, str)
                self.assertGreater(len(name), 0)


if __name__ == '__main__':
    unittest.main()
