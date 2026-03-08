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


class TestConfigurationCommands(unittest.TestCase):
    """Tests for set_frame_count, set_lines, set_magnification, set_pockels_deadband."""

    def setUp(self):
        self.config = {
            'controller': {
                'com_port': 'COM3',
                'baud_rate': 1_000_000,
                'timeout': 1.0,
            }
        }

    # -- set_frame_count --------------------------------------------------------

    @mock.patch('serial.Serial')
    def test_set_frame_count_sends_correct_packet(self, mock_serial):
        """set_frame_count encodes frames as big-endian 16-bit [1, high, low]."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_frame_count(1000)  # 1000 = 0x03E8 → high=3, low=232
        mock_port.write.assert_called_with(bytes([1, 3, 232]))

    @mock.patch('serial.Serial')
    def test_set_frame_count_tracks_state(self, mock_serial):
        """set_frame_count updates frame_count attribute."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_frame_count(500)
        self.assertEqual(ctrl.frame_count, 500)

    @mock.patch('serial.Serial')
    def test_set_frame_count_validation(self, mock_serial):
        """set_frame_count raises ValueError for out-of-range values."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        with self.assertRaises(ValueError):
            ctrl.set_frame_count(-1)
        with self.assertRaises(ValueError):
            ctrl.set_frame_count(65536)

    # -- set_lines --------------------------------------------------------------

    @mock.patch('serial.Serial')
    def test_set_lines_sends_correct_packet(self, mock_serial):
        """set_lines encodes line count as big-endian 16-bit [2, high, low]."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_lines(512)  # 512 = 0x0200 → high=2, low=0
        mock_port.write.assert_called_with(bytes([2, 2, 0]))

    @mock.patch('serial.Serial')
    def test_set_lines_tracks_state(self, mock_serial):
        """set_lines updates lines_per_frame attribute."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_lines(256)
        self.assertEqual(ctrl.lines_per_frame, 256)

    @mock.patch('serial.Serial')
    def test_set_lines_validation(self, mock_serial):
        """set_lines raises ValueError for out-of-range values."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        with self.assertRaises(ValueError):
            ctrl.set_lines(-1)
        with self.assertRaises(ValueError):
            ctrl.set_lines(65536)

    # -- set_magnification ------------------------------------------------------

    @mock.patch('serial.Serial')
    def test_set_magnification_sends_correct_packet(self, mock_serial):
        """set_magnification sends [3, 0, mag]."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_magnification(4)
        mock_port.write.assert_called_with(bytes([3, 0, 4]))

    @mock.patch('serial.Serial')
    def test_set_magnification_tracks_state(self, mock_serial):
        """set_magnification updates magnification attribute."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_magnification(7)
        self.assertEqual(ctrl.magnification, 7)

    @mock.patch('serial.Serial')
    def test_set_magnification_validation(self, mock_serial):
        """set_magnification raises ValueError for out-of-range values.

        Valid range is 0-12 (MATLAB popup.Value - 1 for a 13-item popup).
        """
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        # 0 and 12 are valid endpoints — must not raise.
        ctrl.set_magnification(0)
        ctrl.set_magnification(12)
        # 13 and above are out of range.
        with self.assertRaises(ValueError):
            ctrl.set_magnification(13)
        with self.assertRaises(ValueError):
            ctrl.set_magnification(255)

    # -- set_pockels_deadband ---------------------------------------------------

    @mock.patch('serial.Serial')
    def test_set_pockels_deadband_sends_correct_packet(self, mock_serial):
        """set_pockels_deadband sends [9, left, right]."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_pockels_deadband(left=120, right=150)
        mock_port.write.assert_called_with(bytes([9, 120, 150]))

    @mock.patch('serial.Serial')
    def test_set_pockels_deadband_tracks_state(self, mock_serial):
        """set_pockels_deadband updates pockels_deadband attribute."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_pockels_deadband(left=30, right=40)
        self.assertEqual(ctrl.pockels_deadband, {'left': 30, 'right': 40})

    @mock.patch('serial.Serial')
    def test_set_pockels_deadband_validation(self, mock_serial):
        """set_pockels_deadband raises ValueError for out-of-range values."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        with self.assertRaises(ValueError):
            ctrl.set_pockels_deadband(left=-1, right=0)
        with self.assertRaises(ValueError):
            ctrl.set_pockels_deadband(left=0, right=256)


class TestETLCurrentControl(unittest.TestCase):
    """Tests for set_etl_current() and its format_command() decoder."""

    def setUp(self):
        self.config = {
            'controller': {
                'com_port': 'COM3',
                'baud_rate': 1_000_000,
                'timeout': 1.0,
            }
        }

    # -- Packet encoding --------------------------------------------------------

    @mock.patch('serial.Serial')
    def test_set_etl_current_zero_sends_correct_packet(self, mock_serial):
        """set_etl_current(0) sends [48, 112, 0].

        Encoding: encoded = 0x7000 | 0 = 0x7000; b1=0x70=112, b2=0x00=0.
        """
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_etl_current(0)
        mock_port.write.assert_called_with(bytes([48, 112, 0]))

    @mock.patch('serial.Serial')
    def test_set_etl_current_max_sends_correct_packet(self, mock_serial):
        """set_etl_current(1760) sends [48, 118, 224].

        Encoding: 1760=0x6E0; encoded = 0x7000 | 0x6E0 = 0x76E0;
        b1=0x76=118, b2=0xE0=224.
        """
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_etl_current(1760)
        mock_port.write.assert_called_with(bytes([48, 118, 224]))

    @mock.patch('serial.Serial')
    def test_set_etl_current_mid_sends_correct_packet(self, mock_serial):
        """set_etl_current(860) sends [48, 115, 92].

        860 is the typical resting position (default_current in config).
        Encoding: 860=0x35C; encoded = 0x7000 | 0x35C = 0x735C;
        b1=0x73=115, b2=0x5C=92.
        """
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_etl_current(860)
        mock_port.write.assert_called_with(bytes([48, 115, 92]))

    @mock.patch('serial.Serial')
    def test_set_etl_current_cmd_id_is_48(self, mock_serial):
        """First byte of every ETL packet is the CMD_ETL constant (48)."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_etl_current(256)
        sent_packet = mock_port.write.call_args[0][0]
        self.assertEqual(sent_packet[0], 48)

    # -- State tracking ---------------------------------------------------------

    @mock.patch('serial.Serial')
    def test_set_etl_current_tracks_state(self, mock_serial):
        """set_etl_current updates the etl_current attribute."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_etl_current(500)
        self.assertEqual(ctrl.etl_current, 500)

    @mock.patch('serial.Serial')
    def test_set_etl_current_initial_state_is_zero(self, mock_serial):
        """etl_current is 0 before any command is sent."""
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        self.assertEqual(ctrl.etl_current, 0)

    # -- Validation -------------------------------------------------------------

    @mock.patch('serial.Serial')
    def test_set_etl_current_validation_below_min(self, mock_serial):
        """set_etl_current raises ValueError for current below ETL_CURRENT_MIN."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        with self.assertRaises(ValueError):
            ctrl.set_etl_current(-1)

    @mock.patch('serial.Serial')
    def test_set_etl_current_validation_above_max(self, mock_serial):
        """set_etl_current raises ValueError for current above ETL_CURRENT_MAX."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        with self.assertRaises(ValueError):
            ctrl.set_etl_current(1761)

    @mock.patch('serial.Serial')
    def test_set_etl_current_boundary_values_do_not_raise(self, mock_serial):
        """set_etl_current accepts exact boundary values 0 and 1760."""
        mock_port = mock.Mock()
        mock_serial.return_value = mock_port
        ctrl = controller.ScanboxController(self.config)
        ctrl.open()
        ctrl.set_etl_current(controller.ScanboxController.ETL_CURRENT_MIN)
        ctrl.set_etl_current(controller.ScanboxController.ETL_CURRENT_MAX)

    # -- format_command decoder -------------------------------------------------

    def test_format_command_decodes_etl_zero(self):
        """format_command correctly decodes ETL packet for current=0."""
        result = controller.ScanboxController.format_command(48, 112, 0)
        self.assertEqual(result, 'set_etl_current(current=0)')

    def test_format_command_decodes_etl_max(self):
        """format_command correctly decodes ETL packet for current=1760."""
        result = controller.ScanboxController.format_command(48, 118, 224)
        self.assertEqual(result, 'set_etl_current(current=1760)')

    def test_format_command_decodes_etl_mid(self):
        """format_command correctly decodes ETL packet for current=860."""
        result = controller.ScanboxController.format_command(48, 115, 92)
        self.assertEqual(result, 'set_etl_current(current=860)')

    def test_format_command_etl_roundtrip(self):
        """Encoding via set_etl_current and decoding via format_command is lossless."""
        mock_port = mock.Mock()
        with mock.patch('serial.Serial', return_value=mock_port):
            ctrl = controller.ScanboxController(self.config)
            ctrl.open()
            for current in [0, 1, 255, 256, 860, 1759, 1760]:
                ctrl.set_etl_current(current)
                packet = mock_port.write.call_args[0][0]
                decoded = controller.ScanboxController.format_command(
                    packet[0], packet[1], packet[2]
                )
                self.assertEqual(decoded, f'set_etl_current(current={current})',
                                 f'Round-trip failed for current={current}')


if __name__ == '__main__':
    unittest.main()
