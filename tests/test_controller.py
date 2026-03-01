"""Tests for ScanboxController class.

Tests serial communication protocol for Pockels, shutter, and mirror control.
Uses mock serial ports to verify correct byte sequences.
"""

import unittest
import unittest.mock as mock
from pyscanbox.hardware import controller


class TestScanboxController(unittest.TestCase):
    """Test cases for ScanboxController."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            'controller': {
                'com_port': 'COM3',
                'baud_rate': 1_000_000,
                'timeout': 1.0,
            }
        }

    @mock.patch('serial.Serial')
    def test_open_controller(self, mock_serial):
        """Test opening serial connection."""
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        
        # Verify Serial was called with correct parameters
        mock_serial.assert_called_once()
        call_kwargs = mock_serial.call_args[1]
        self.assertEqual(call_kwargs['port'], 'COM3')
        self.assertEqual(call_kwargs['baudrate'], 1_000_000)
        
        self.assertTrue(ctrl.is_open)

    @mock.patch('serial.Serial')
    def test_set_pockels(self, mock_serial):
        """Test Pockels cell command sends correct bytes."""
        # Setup mock
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_pockels(base=50, active=100)
        
        # Verify correct 3-byte packet was sent
        expected_packet = bytes([8, 50, 100])
        mock_port.write.assert_called_with(expected_packet)

    @mock.patch('serial.Serial')
    def test_set_shutter_open(self, mock_serial):
        """Test shutter open command."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_shutter(open=True)
        
        # Verify command: [16, 0, 1]
        expected_packet = bytes([16, 0, 1])
        mock_port.write.assert_called_with(expected_packet)

    @mock.patch('serial.Serial')
    def test_set_shutter_close(self, mock_serial):
        """Test shutter close command."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_shutter(open=False)
        
        # Verify command: [16, 0, 0]
        expected_packet = bytes([16, 0, 0])
        mock_port.write.assert_called_with(expected_packet)

    @mock.patch('serial.Serial')
    def test_set_mirror_2p(self, mock_serial):
        """Test 2P mirror mode command."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_mirror(mode='2p')
        
        # Verify command: [5, 0, 0]
        expected_packet = bytes([5, 0, 0])
        mock_port.write.assert_called_with(expected_packet)

    @mock.patch('serial.Serial')
    def test_set_mirror_epi(self, mock_serial):
        """Test epi mirror mode command."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_mirror(mode='epi')
        
        # Verify command: [5, 0, 1]
        expected_packet = bytes([5, 0, 1])
        mock_port.write.assert_called_with(expected_packet)

    @mock.patch('serial.Serial')
    def test_parameter_validation(self, mock_serial):
        """Test parameter validation."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        
        # Test out-of-range values
        with self.assertRaises(ValueError):
            ctrl._send_command(256, 0, 0)  # cmd_id > 255
        
        with self.assertRaises(ValueError):
            ctrl._send_command(0, -1, 0)  # param1 < 0
        
        with self.assertRaises(ValueError):
            ctrl._send_command(0, 0, 300)  # param2 > 255


class TestScanControl(unittest.TestCase):
    """Test start_scan and stop_scan commands."""

    def setUp(self):
        self.config = {
            'controller': {
                'com_port': 'COM3',
                'baud_rate': 1_000_000,
                'timeout': 1.0,
            }
        }

    # -- Initial state ----------------------------------------------------------

    @mock.patch('serial.Serial')
    def test_scan_state_initial_false(self, mock_serial):
        """Scan state is False before any command is issued."""
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        self.assertFalse(ctrl.get_scan_state())

    # -- start_scan() -----------------------------------------------------------

    @mock.patch('serial.Serial')
    def test_start_scan_sends_correct_packet(self, mock_serial):
        """start_scan sends [4, 0, 1]."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.start_scan()
        mock_port.write.assert_called_with(bytes([4, 0, 1]))

    @mock.patch('serial.Serial')
    def test_start_scan_sets_state(self, mock_serial):
        """start_scan sets scan_running to True."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.start_scan()
        self.assertTrue(ctrl.get_scan_state())

    # -- stop_scan() ------------------------------------------------------------

    @mock.patch('serial.Serial')
    def test_stop_scan_sends_correct_packet(self, mock_serial):
        """stop_scan sends [4, 0, 0]."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.stop_scan()
        mock_port.write.assert_called_with(bytes([4, 0, 0]))

    @mock.patch('serial.Serial')
    def test_stop_scan_clears_state(self, mock_serial):
        """stop_scan sets scan_running to False."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.stop_scan()
        self.assertFalse(ctrl.get_scan_state())

    # -- Roundtrip --------------------------------------------------------------

    @mock.patch('serial.Serial')
    def test_start_then_stop_roundtrip(self, mock_serial):
        """Scan state tracks start → stop transitions correctly."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.start_scan()
        self.assertTrue(ctrl.get_scan_state())
        ctrl.stop_scan()
        self.assertFalse(ctrl.get_scan_state())


if __name__ == '__main__':
    unittest.main()
