"""Tests for pyscanbox.hardware.knobby.

Covers both the module-level utility functions (steps_to_units,
units_to_steps, build_position_packet) and the Knobby class.

All Knobby class tests use emulation mode (mock_serial), so no physical
hardware is required.  Where a test needs the Knobby to appear to have
received a position packet, bytes are injected directly into the mock
serial's _response_buffer, which is what Knobby.read_command() drains.
"""

import unittest
import pyscanbox.hardware.knobby as knobby_module
from pyscanbox.hardware.knobby import (
    MOTOR_GAIN, MOTOR_MSTEP, AXIS_NAMES, AXIS_UNITS,
    steps_to_units, units_to_steps, build_position_packet,
    Knobby,
)


# -- Shared config --------------------------------------------------------------

_CONFIG = {
    'knobby': {
        'com_port': 'COM5',
        'timeout': 1.0,
        'version': 2,
    },
    'emulation': {
        'enabled': True,
        'verbose': False,
    },
}


# -- Module-level constants -----------------------------------------------------

class TestModuleConstants(unittest.TestCase):
    """MOTOR_GAIN, MOTOR_MSTEP, AXIS_NAMES, AXIS_UNITS have correct shapes."""

    def test_motor_gain_length(self):
        self.assertEqual(len(MOTOR_GAIN), 4)

    def test_motor_gain_all_positive(self):
        for i, g in enumerate(MOTOR_GAIN):
            with self.subTest(motor=i):
                self.assertGreater(g, 0)

    def test_motor_mstep_shape(self):
        # 3 velocity modes × 4 motors
        self.assertEqual(len(MOTOR_MSTEP), 3)
        for row in MOTOR_MSTEP:
            self.assertEqual(len(row), 4)

    def test_motor_mstep_coarse_greater_than_fine(self):
        """Coarse steps-per-count > fine > superfine for every axis."""
        for axis in range(4):
            with self.subTest(axis=axis):
                self.assertGreater(MOTOR_MSTEP[0][axis], MOTOR_MSTEP[1][axis])
                self.assertGreater(MOTOR_MSTEP[1][axis], MOTOR_MSTEP[2][axis])

    def test_axis_names_length(self):
        self.assertEqual(len(AXIS_NAMES), 4)

    def test_axis_names_values(self):
        self.assertEqual(AXIS_NAMES, ['Z', 'Y', 'X', 'A'])

    def test_axis_units_length(self):
        self.assertEqual(len(AXIS_UNITS), 4)

    def test_axis_units_xyz_are_um(self):
        for i in range(3):
            self.assertEqual(AXIS_UNITS[i], 'um')

    def test_axis_units_a_is_deg(self):
        self.assertEqual(AXIS_UNITS[3], 'deg')


# -- steps_to_units -------------------------------------------------------------

class TestStepsToUnits(unittest.TestCase):
    """steps_to_units() converts correctly for all four axes."""

    def test_zero_steps_gives_zero(self):
        for motor_id in range(4):
            with self.subTest(motor_id=motor_id):
                self.assertEqual(steps_to_units(motor_id, 0), 0.0)

    def test_positive_steps_positive_result(self):
        for motor_id in range(4):
            with self.subTest(motor_id=motor_id):
                self.assertGreater(steps_to_units(motor_id, 100), 0)

    def test_negative_steps_negative_result(self):
        for motor_id in range(4):
            with self.subTest(motor_id=motor_id):
                self.assertLess(steps_to_units(motor_id, -100), 0)

    def test_z_axis_known_value(self):
        # 1 step × 0.078125 μm/step = 0.078125 μm
        self.assertAlmostEqual(steps_to_units(0, 1), MOTOR_GAIN[0], places=6)

    def test_x_y_axes_equal(self):
        """X and Y share the same gain."""
        self.assertAlmostEqual(
            steps_to_units(1, 1000),
            steps_to_units(2, 1000),
            places=6,
        )

    def test_returns_float(self):
        result = steps_to_units(0, 128)
        self.assertIsInstance(result, float)

    def test_invalid_motor_id_raises(self):
        with self.assertRaises(IndexError):
            steps_to_units(4, 0)


# -- units_to_steps -------------------------------------------------------------

class TestUnitsToSteps(unittest.TestCase):
    """units_to_steps() is the inverse of steps_to_units()."""

    def test_zero_gives_zero(self):
        for motor_id in range(4):
            with self.subTest(motor_id=motor_id):
                self.assertEqual(units_to_steps(motor_id, 0.0), 0)

    def test_returns_int(self):
        result = units_to_steps(0, 10.0)
        self.assertIsInstance(result, int)

    def test_roundtrip_steps_to_units_to_steps(self):
        """Converting steps → units → steps recovers the original (to nearest int)."""
        for motor_id in range(4):
            for original_steps in [0, 100, -250, 10000]:
                with self.subTest(motor_id=motor_id, steps=original_steps):
                    units = steps_to_units(motor_id, original_steps)
                    recovered = units_to_steps(motor_id, units)
                    self.assertEqual(recovered, original_steps)

    def test_positive_units_positive_steps(self):
        self.assertGreater(units_to_steps(0, 100.0), 0)

    def test_negative_units_negative_steps(self):
        self.assertLess(units_to_steps(0, -100.0), 0)

    def test_invalid_motor_id_raises(self):
        with self.assertRaises(IndexError):
            units_to_steps(4, 0.0)


# -- build_position_packet ------------------------------------------------------

class TestBuildPositionPacket(unittest.TestCase):
    """build_position_packet() produces the correct 5-byte wire format."""

    def test_length_is_five(self):
        self.assertEqual(len(build_position_packet(0, 0)), 5)

    def test_first_byte_is_motor_id(self):
        for motor_id in range(4):
            with self.subTest(motor_id=motor_id):
                pkt = build_position_packet(motor_id, 0)
                self.assertEqual(pkt[0], motor_id)

    def test_steps_encoded_little_endian(self):
        pkt = build_position_packet(0, 256)
        # 256 little-endian = 0x00 0x01 0x00 0x00
        self.assertEqual(pkt[1], 0x00)
        self.assertEqual(pkt[2], 0x01)
        self.assertEqual(pkt[3], 0x00)
        self.assertEqual(pkt[4], 0x00)

    def test_negative_steps_roundtrip(self):
        pkt = build_position_packet(2, -1)
        steps_back = int.from_bytes(pkt[1:5], byteorder='little', signed=True)
        self.assertEqual(steps_back, -1)

    def test_known_positive_value(self):
        pkt = build_position_packet(0, 1000)
        steps_back = int.from_bytes(pkt[1:5], byteorder='little', signed=True)
        self.assertEqual(steps_back, 1000)

    def test_returns_bytes(self):
        self.assertIsInstance(build_position_packet(0, 0), bytes)


# -- Knobby class: initialisation -----------------------------------------------

class TestKnobbyInit(unittest.TestCase):

    def test_reads_com_port(self):
        k = Knobby(_CONFIG)
        self.assertEqual(k.com_port, 'COM5')

    def test_baud_rate_fixed(self):
        """Knobby always uses 57600 baud regardless of config."""
        k = Knobby(_CONFIG)
        self.assertEqual(k.baud_rate, 57600)

    def test_emulation_flag_true(self):
        k = Knobby(_CONFIG)
        self.assertTrue(k.use_emulation)

    def test_not_open_at_construction(self):
        k = Knobby(_CONFIG)
        self.assertFalse(k.is_open)

    def test_network_flag_false_for_com_port(self):
        k = Knobby(_CONFIG)
        self.assertFalse(k.is_network)

    def test_network_flag_true_for_ip(self):
        cfg = {**_CONFIG, 'knobby': {**_CONFIG['knobby'], 'com_port': '192.168.1.10'}}
        k = Knobby(cfg)
        self.assertTrue(k.is_network)


# -- Knobby class: connection lifecycle -----------------------------------------

class TestKnobbyConnection(unittest.TestCase):

    def test_open_sets_is_open(self):
        k = Knobby(_CONFIG)
        k.open()
        try:
            self.assertTrue(k.is_open)
            self.assertIsNotNone(k.port)
        finally:
            k.close()

    def test_close_clears_is_open(self):
        k = Knobby(_CONFIG)
        k.open()
        k.close()
        self.assertFalse(k.is_open)

    def test_context_manager(self):
        with Knobby(_CONFIG) as k:
            self.assertTrue(k.is_open)
        self.assertFalse(k.is_open)

    def test_network_knobby_raises_not_implemented(self):
        cfg = {**_CONFIG, 'knobby': {**_CONFIG['knobby'], 'com_port': '192.168.1.10'}}
        k = Knobby(cfg)
        with self.assertRaises(NotImplementedError):
            k.open()

    def test_send_command_raises_when_closed(self):
        k = Knobby(_CONFIG)
        with self.assertRaises(RuntimeError):
            k.send_command(0)

    def test_read_command_raises_when_closed(self):
        k = Knobby(_CONFIG)
        with self.assertRaises(RuntimeError):
            k.read_command()


# -- Knobby class: send_command wire format -------------------------------------

class TestKnobbySendCommand(unittest.TestCase):
    """send_command() writes the correct 9-byte packet to the serial port."""

    def setUp(self):
        self.k = Knobby(_CONFIG)
        self.k.open()

    def tearDown(self):
        self.k.close()

    def _last_written(self):
        """Return the most-recently written bytes from the mock port."""
        return self.k.port._last_written  # mock_serial stores this

    def test_fixed_header_bytes(self):
        self.k.send_command(0)
        data = self.k.port._last_written
        self.assertEqual(data[0], 0x01)
        self.assertEqual(data[1], 0xC8)

    def test_packet_length(self):
        self.k.send_command(0)
        self.assertEqual(len(self.k.port._last_written), 9)

    def test_command_id_in_byte_3(self):
        self.k.send_command(30)   # zero_xyz
        self.assertEqual(self.k.port._last_written[3], 30)

    def test_value_high_low_bytes(self):
        # value = 0x0102 → high=0x01 low=0x02
        self.k.send_command(1, 0x0102)
        data = self.k.port._last_written
        self.assertEqual(data[4], 0x01)
        self.assertEqual(data[5], 0x02)

    def test_returns_true_on_success(self):
        self.assertTrue(self.k.send_command(20))


# -- Knobby class: read_command -------------------------------------------------

class TestKnobbyReadCommand(unittest.TestCase):
    """read_command() correctly decodes injected 5-byte position packets."""

    def setUp(self):
        self.k = Knobby(_CONFIG)
        self.k.open()

    def tearDown(self):
        self.k.close()

    def _inject(self, motor_id, steps):
        """Push a position packet into the mock serial RX buffer."""
        self.k.port._response_buffer.extend(build_position_packet(motor_id, steps))

    def test_returns_none_when_no_data(self):
        self.assertIsNone(self.k.read_command())

    def test_returns_tuple_when_data_available(self):
        self._inject(0, 100)
        result = self.k.read_command()
        self.assertIsNotNone(result)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_motor_id_decoded_correctly(self):
        for motor_id in range(4):
            with self.subTest(motor_id=motor_id):
                self._inject(motor_id, 0)
                got_id, _ = self.k.read_command()
                self.assertEqual(got_id, motor_id)

    def test_positive_steps_decoded(self):
        self._inject(1, 1234)
        _, steps = self.k.read_command()
        self.assertEqual(steps, 1234)

    def test_negative_steps_decoded(self):
        self._inject(2, -500)
        _, steps = self.k.read_command()
        self.assertEqual(steps, -500)

    def test_returns_none_with_partial_packet(self):
        """Fewer than 5 bytes available → None (no partial reads)."""
        self.k.port._response_buffer.extend(b'\x00\x01\x02')
        self.assertIsNone(self.k.read_command())

    def test_sequential_packets(self):
        """Two consecutive packets are each decoded correctly."""
        self._inject(0, 100)
        self._inject(1, 200)
        r0 = self.k.read_command()
        r1 = self.k.read_command()
        self.assertEqual(r0, (0, 100))
        self.assertEqual(r1, (1, 200))


# -- Knobby class: high-level command helpers -----------------------------------

class TestKnobbyCommandHelpers(unittest.TestCase):
    """High-level helper methods send the correct command IDs."""

    def setUp(self):
        self.k = Knobby(_CONFIG)
        self.k.open()

    def tearDown(self):
        self.k.close()

    def _cmd_id(self):
        return self.k.port._last_written[3]

    def test_set_velocity_coarse(self):
        self.k.set_velocity_coarse()
        self.assertEqual(self._cmd_id(), 10)

    def test_set_velocity_fine(self):
        self.k.set_velocity_fine()
        self.assertEqual(self._cmd_id(), 11)

    def test_set_velocity_superfine(self):
        self.k.set_velocity_superfine()
        self.assertEqual(self._cmd_id(), 12)

    def test_set_mode_normal(self):
        self.k.set_mode_normal()
        self.assertEqual(self._cmd_id(), 20)

    def test_set_mode_rotate(self):
        self.k.set_mode_rotate()
        self.assertEqual(self._cmd_id(), 21)

    def test_zero_xyz(self):
        self.k.zero_xyz()
        self.assertEqual(self._cmd_id(), 30)

    def test_zero_xyza(self):
        self.k.zero_xyza()
        self.assertEqual(self._cmd_id(), 31)

    def test_lock(self):
        self.k.lock()
        self.assertEqual(self._cmd_id(), 60)

    def test_unlock(self):
        self.k.unlock()
        self.assertEqual(self._cmd_id(), 61)

    def test_store_position_slots(self):
        for slot in range(3):
            with self.subTest(slot=slot):
                self.k.store_position(slot)
                self.assertEqual(self._cmd_id(), 40 + slot)

    def test_recall_position_slots(self):
        for slot in range(3):
            with self.subTest(slot=slot):
                self.k.recall_position(slot)
                self.assertEqual(self._cmd_id(), 50 + slot)

    def test_store_position_invalid_slot_raises(self):
        with self.assertRaises(ValueError):
            self.k.store_position(3)

    def test_recall_position_invalid_slot_raises(self):
        with self.assertRaises(ValueError):
            self.k.recall_position(-1)

    def test_move_motor_valid(self):
        self.assertTrue(self.k.move_motor(0, 100.0))

    def test_move_motor_invalid_id_raises(self):
        with self.assertRaises(ValueError):
            self.k.move_motor(3, 10.0)   # A-axis not supported

    def test_move_motor_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            self.k.move_motor(0, 40000.0)  # > 32767


if __name__ == '__main__':
    unittest.main()
