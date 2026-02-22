"""Tests for TMCL protocol implementation.

Tests the low-level TMCL packet building and parsing functions.
"""

import unittest
from pyscanbox.hardware import protocols


class TestTMCLProtocol(unittest.TestCase):
    """Test cases for TMCL protocol functions."""

    def test_build_tmcl_packet_mvp(self):
        """Test building MVP (move to position) packet."""
        packet = protocols.build_tmcl_packet('MVP', 0, 0, 1000)
        
        # Verify packet structure
        self.assertEqual(len(packet), 9)
        self.assertEqual(packet[0], 1)  # Module address
        self.assertEqual(packet[1], 4)  # MVP command
        self.assertEqual(packet[2], 0)  # Type
        self.assertEqual(packet[3], 0)  # Motor 0
        
        # Verify 32-bit value (big-endian)
        value = int.from_bytes(packet[4:8], byteorder='big')
        self.assertEqual(value, 1000)
        
        # Verify checksum
        expected_checksum = sum(packet[0:8]) % 256
        self.assertEqual(packet[8], expected_checksum)

    def test_build_tmcl_packet_gap(self):
        """Test building GAP (get axis parameter) packet."""
        packet = protocols.build_tmcl_packet('GAP', 1, 2, 0)
        
        self.assertEqual(packet[1], 6)  # GAP command
        self.assertEqual(packet[2], 1)  # Type 1
        self.assertEqual(packet[3], 2)  # Motor 2

    def test_build_tmcl_packet_negative_value(self):
        """Test building packet with negative value."""
        packet = protocols.build_tmcl_packet('MVP', 1, 0, -500)
        
        # Verify negative value is encoded correctly (two's complement)
        value = int.from_bytes(packet[4:8], byteorder='big', signed=False)
        # Convert back to signed
        if value >= (1 << 31):
            value -= (1 << 32)
        self.assertEqual(value, -500)

    def test_build_tmcl_checksum(self):
        """Test checksum calculation."""
        packet = protocols.build_tmcl_packet('MST', 0, 0, 0)
        
        # Manually verify checksum
        expected = sum(packet[0:8]) % 256
        self.assertEqual(packet[8], expected)

    def test_parse_tmcl_response(self):
        """Test parsing TMCL response packet."""
        # Construct a response packet
        response = bytearray(9)
        response[0] = 2  # Reply address
        response[1] = 1  # Module address
        response[2] = 100  # Status (success)
        response[3] = 6  # Command (GAP)
        response[4:8] = (12345).to_bytes(4, byteorder='big')
        response[8] = sum(response[0:8]) % 256  # Checksum
        
        parsed = protocols.parse_tmcl_response(bytes(response))
        
        self.assertEqual(parsed['status'], 100)
        self.assertEqual(parsed['value'], 12345)
        self.assertEqual(parsed['command'], 6)
        self.assertTrue(parsed['valid'])

    def test_parse_tmcl_response_invalid_checksum(self):
        """Test parsing response with invalid checksum."""
        response = bytearray(9)
        response[0] = 2
        response[1] = 1
        response[2] = 100
        response[3] = 6
        response[4:8] = (0).to_bytes(4, byteorder='big')
        response[8] = 0  # Wrong checksum
        
        parsed = protocols.parse_tmcl_response(bytes(response))
        self.assertFalse(parsed['valid'])

    def test_invalid_command(self):
        """Test that invalid commands raise ValueError."""
        with self.assertRaises(ValueError):
            protocols.build_tmcl_packet('INVALID', 0, 0, 0)

    def test_command_mapping(self):
        """Test that all expected commands are mapped."""
        expected_commands = ['ROR', 'ROL', 'MST', 'MVP', 'SAP', 'GAP']
        
        for cmd in expected_commands:
            # Should not raise exception
            packet = protocols.build_tmcl_packet(cmd, 0, 0, 0)
            self.assertEqual(len(packet), 9)


if __name__ == '__main__':
    unittest.main()
