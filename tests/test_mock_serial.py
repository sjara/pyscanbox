"""Tests for mock serial interface emulator.

Tests the mock_serial module which emulates serial communication
with Scanbox controller and Trinamic motor controller.
"""

import pytest
from pyscanbox.emulator import mock_serial


class TestMockSerialBasics:
    """Test basic serial port functionality."""

    def test_initialization(self):
        """Test mock serial port initialization."""
        port = mock_serial.Serial('COM3', 1000000)
        assert port.port == 'COM3'
        assert port.baudrate == 1000000
        assert port.is_open is True
        assert 'pockels' in port.state
        assert 'shutter' in port.state
        assert 'mirror' in port.state
        assert 'motor_positions' in port.state

    def test_close(self):
        """Test closing mock serial port."""
        port = mock_serial.Serial('COM3', 1000000)
        port.close()
        assert port.is_open is False

    def test_write_when_closed(self):
        """Test that writing to closed port raises exception."""
        port = mock_serial.Serial('COM3', 1000000)
        port.close()
        with pytest.raises(RuntimeError, match="not open"):
            port.write(bytes([8, 50, 100]))

    def test_read_when_closed(self):
        """Test that reading from closed port raises exception."""
        port = mock_serial.Serial('COM3', 1000000)
        port.close()
        with pytest.raises(RuntimeError, match="not open"):
            port.read(1)

    def test_context_manager(self):
        """Test using mock serial with context manager."""
        with mock_serial.Serial('COM3', 1000000) as port:
            assert port.is_open is True
            port.write(bytes([8, 50, 100]))
        assert port.is_open is False


class TestScanboxCommands:
    """Test Scanbox controller 3-byte commands."""

    def test_pockels_command(self):
        """Test Pockels cell control command."""
        port = mock_serial.Serial('COM3', 1000000)
        
        # Command ID 8: Pockels [cmd_id, base, active]
        result = port.write(bytes([8, 50, 100]))
        
        assert result == 3  # 3 bytes written
        assert port.state['pockels'] == (50, 100)

    def test_shutter_open(self):
        """Test shutter open command."""
        port = mock_serial.Serial('COM3', 1000000)
        
        # Command ID 16: Shutter [cmd_id, 0, 1=open]
        port.write(bytes([16, 0, 1]))
        
        assert port.state['shutter'] is True

    def test_shutter_close(self):
        """Test shutter close command."""
        port = mock_serial.Serial('COM3', 1000000)
        
        # Command ID 16: Shutter [cmd_id, 0, 0=close]
        port.write(bytes([16, 0, 0]))
        
        assert port.state['shutter'] is False

    def test_mirror_2p_mode(self):
        """Test mirror in 2P mode."""
        port = mock_serial.Serial('COM3', 1000000)
        
        # Command ID 5: Mirror [cmd_id, 0, 0=2P]
        port.write(bytes([5, 0, 0]))
        
        assert port.state['mirror'] == '2p'

    def test_mirror_epi_mode(self):
        """Test mirror in epi mode."""
        port = mock_serial.Serial('COM3', 1000000)
        
        # Command ID 5: Mirror [cmd_id, 0, 1=epi]
        port.write(bytes([5, 0, 1]))
        
        assert port.state['mirror'] == 'epi'

    def test_sequence_of_commands(self):
        """Test executing multiple Scanbox commands."""
        port = mock_serial.Serial('COM3', 1000000)
        
        # Set Pockels
        port.write(bytes([8, 10, 85]))
        assert port.state['pockels'] == (10, 85)
        
        # Open shutter
        port.write(bytes([16, 0, 1]))
        assert port.state['shutter'] is True
        
        # Set mirror to 2P
        port.write(bytes([5, 0, 0]))
        assert port.state['mirror'] == '2p'


class TestTMCLCommands:
    """Test Trinamic TMCL 9-byte motor commands."""

    def test_mvp_absolute(self):
        """Test MVP (move to position) absolute command."""
        port = mock_serial.Serial('COM4', 57600)
        
        # Build MVP absolute command: motor 0 to position 1000
        # [module, cmd=4, type=0, motor, value_bytes(4), checksum]
        cmd = bytearray([1, 4, 0, 0])
        cmd.extend((1000).to_bytes(4, byteorder='big'))
        checksum = sum(cmd) % 256
        cmd.append(checksum)
        
        port.write(bytes(cmd))
        
        assert port.state['motor_positions'][0] == 1000

    def test_mvp_relative(self):
        """Test MVP relative move command."""
        port = mock_serial.Serial('COM4', 57600)
        
        # Set initial position
        port.state['motor_positions'][1] = 500
        
        # Build MVP relative command: motor 1, move by +200
        cmd = bytearray([1, 4, 1, 1])
        cmd.extend((200).to_bytes(4, byteorder='big'))
        checksum = sum(cmd) % 256
        cmd.append(checksum)
        
        port.write(bytes(cmd))
        
        assert port.state['motor_positions'][1] == 700

    def test_gap_get_position(self):
        """Test GAP (get axis parameter) to read position."""
        port = mock_serial.Serial('COM4', 57600)
        
        # Set motor position
        port.state['motor_positions'][2] = 5000
        
        # Build GAP command: motor 2, parameter type 1 (position)
        cmd = bytearray([1, 6, 1, 2])
        cmd.extend((0).to_bytes(4, byteorder='big'))
        checksum = sum(cmd) % 256
        cmd.append(checksum)
        
        port.write(bytes(cmd))
        
        # Read response
        response = port.read(9)
        assert len(response) == 9
        
        # Parse returned value
        value = int.from_bytes(response[4:8], byteorder='big')
        assert value == 5000

    def test_ror_rotate_right(self):
        """Test ROR (rotate right) command."""
        port = mock_serial.Serial('COM4', 57600)
        
        # Build ROR command: motor 0, velocity 100
        cmd = bytearray([1, 1, 0, 0])
        cmd.extend((100).to_bytes(4, byteorder='big'))
        checksum = sum(cmd) % 256
        cmd.append(checksum)
        
        port.write(bytes(cmd))
        
        assert port.state['motor_velocities'][0] == 100

    def test_rol_rotate_left(self):
        """Test ROL (rotate left) command."""
        port = mock_serial.Serial('COM4', 57600)
        
        # Build ROL command: motor 1, velocity 50
        cmd = bytearray([1, 2, 0, 1])
        cmd.extend((50).to_bytes(4, byteorder='big'))
        checksum = sum(cmd) % 256
        cmd.append(checksum)
        
        port.write(bytes(cmd))
        
        assert port.state['motor_velocities'][1] == -50

    def test_mst_motor_stop(self):
        """Test MST (motor stop) command."""
        port = mock_serial.Serial('COM4', 57600)
        
        # Set motor velocity
        port.state['motor_velocities'][3] = 200
        
        # Build MST command: motor 3
        cmd = bytearray([1, 3, 0, 3])
        cmd.extend((0).to_bytes(4, byteorder='big'))
        checksum = sum(cmd) % 256
        cmd.append(checksum)
        
        port.write(bytes(cmd))
        
        assert port.state['motor_velocities'][3] == 0

    def test_tmcl_response_format(self):
        """Test TMCL response packet format."""
        port = mock_serial.Serial('COM4', 57600)
        
        # Send any command to generate response
        cmd = bytearray([1, 4, 0, 0])
        cmd.extend((1000).to_bytes(4, byteorder='big'))
        checksum = sum(cmd) % 256
        cmd.append(checksum)
        
        port.write(bytes(cmd))
        response = port.read(9)
        
        assert len(response) == 9
        assert response[0] == 2  # Reply address
        assert response[1] == 1  # Module address
        assert response[2] == 100  # Status (success)
        
        # Verify checksum
        expected_checksum = sum(response[0:8]) % 256
        assert response[8] == expected_checksum

    def test_multiple_motors(self):
        """Test controlling all 4 motors."""
        port = mock_serial.Serial('COM4', 57600)
        
        # Move all 4 motors to different positions
        for motor_id in range(4):
            position = (motor_id + 1) * 1000
            cmd = bytearray([1, 4, 0, motor_id])
            cmd.extend(position.to_bytes(4, byteorder='big'))
            checksum = sum(cmd) % 256
            cmd.append(checksum)
            port.write(bytes(cmd))
        
        assert port.state['motor_positions'][0] == 1000
        assert port.state['motor_positions'][1] == 2000
        assert port.state['motor_positions'][2] == 3000
        assert port.state['motor_positions'][3] == 4000


class TestBufferManagement:
    """Test read/write buffer operations."""

    def test_read_empty_buffer(self):
        """Test reading from empty buffer returns empty bytes."""
        port = mock_serial.Serial('COM3', 1000000)
        data = port.read(10)
        assert data == b''

    def test_read_with_data(self):
        """Test reading data from response buffer."""
        port = mock_serial.Serial('COM4', 57600)
        
        # Generate response by sending command
        cmd = bytearray([1, 4, 0, 0])
        cmd.extend((1000).to_bytes(4, byteorder='big'))
        checksum = sum(cmd) % 256
        cmd.append(checksum)
        port.write(bytes(cmd))
        
        # Read response in chunks
        chunk1 = port.read(4)
        assert len(chunk1) == 4
        
        chunk2 = port.read(5)
        assert len(chunk2) == 5
        
        # Buffer should be empty now
        chunk3 = port.read(10)
        assert len(chunk3) == 0

    def test_reset_input_buffer(self):
        """Test resetting input buffer."""
        port = mock_serial.Serial('COM4', 57600)
        
        # Generate response
        cmd = bytearray([1, 4, 0, 0])
        cmd.extend((1000).to_bytes(4, byteorder='big'))
        checksum = sum(cmd) % 256
        cmd.append(checksum)
        port.write(bytes(cmd))
        
        # Reset buffer
        port.reset_input_buffer()
        
        # Should return empty
        data = port.read(10)
        assert data == b''


class TestFactoryFunction:
    """Test factory function for creating mock serial ports."""

    def test_get_mock_serial(self):
        """Test factory function creates proper instance."""
        port = mock_serial.get_mock_serial(port='COM3', baudrate=1000000)
        assert isinstance(port, mock_serial.Serial)
        assert port.port == 'COM3'
        assert port.baudrate == 1000000


class TestVerboseLogging:
    """Test verbose logging functionality."""

    def test_verbose_flag(self):
        """Test setting verbose flag."""
        port = mock_serial.Serial('COM3', 1000000)
        port.verbose = True
        
        # Should not raise exception
        port.write(bytes([8, 50, 100]))
        assert port.state['pockels'] == (50, 100)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_negative_motor_position(self):
        """Test handling negative motor positions."""
        port = mock_serial.Serial('COM4', 57600)
        
        # Build MVP with negative value (-1000)
        value = -1000
        # Convert to unsigned 32-bit
        unsigned_value = (1 << 32) + value if value < 0 else value
        
        cmd = bytearray([1, 4, 0, 0])
        cmd.extend(unsigned_value.to_bytes(4, byteorder='big'))
        checksum = sum(cmd) % 256
        cmd.append(checksum)
        
        port.write(bytes(cmd))
        
        assert port.state['motor_positions'][0] == -1000

    def test_large_motor_position(self):
        """Test handling large motor positions."""
        port = mock_serial.Serial('COM4', 57600)
        
        large_pos = 1000000
        cmd = bytearray([1, 4, 0, 0])
        cmd.extend(large_pos.to_bytes(4, byteorder='big'))
        checksum = sum(cmd) % 256
        cmd.append(checksum)
        
        port.write(bytes(cmd))
        
        assert port.state['motor_positions'][0] == large_pos

    def test_unknown_scanbox_command(self):
        """Test handling unknown Scanbox command ID."""
        port = mock_serial.Serial('COM3', 1000000)
        
        # Send command with unknown ID (99)
        # Should not crash
        port.write(bytes([99, 0, 0]))

    def test_invalid_motor_index(self):
        """Test handling commands to invalid motor index."""
        port = mock_serial.Serial('COM4', 57600)
        
        # Send command to motor 10 (only 0-3 exist)
        # Should not crash
        cmd = bytearray([1, 4, 0, 10])
        cmd.extend((1000).to_bytes(4, byteorder='big'))
        checksum = sum(cmd) % 256
        cmd.append(checksum)
        
        port.write(bytes(cmd))
        
        # Valid motors should be unchanged
        assert port.state['motor_positions'] == [0, 0, 0, 0]
