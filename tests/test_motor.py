# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Tests for pyscanbox.hardware.motor (TrinamicMotor class).

All tests use emulation mode (mock_serial), so no physical hardware is
required.  The mock serial faithfully simulates the TMCL state machine:
it stores motor positions on MVP commands and returns them on GAP queries,
which lets us verify complete command→response roundtrips.
"""

import time
import unittest

from pyscanbox.hardware.motor import TrinamicMotor


# -- Shared config --------------------------------------------------------------

_CONFIG = {
    'motor': {
        'com_port': 'COM4',
        'baud_rate': 57600,
        'timeout': 1,
    },
    'emulation': {
        'enabled': True,
        'verbose': False,
    },
}


# -- Initialisation -------------------------------------------------------------

class TestTrinamicMotorInit(unittest.TestCase):
    """TrinamicMotor reads config values correctly at construction time."""

    def test_reads_com_port(self):
        motor = TrinamicMotor(_CONFIG)
        self.assertEqual(motor.com_port, 'COM4')

    def test_reads_baud_rate(self):
        motor = TrinamicMotor(_CONFIG)
        self.assertEqual(motor.baud_rate, 57600)

    def test_reads_timeout(self):
        motor = TrinamicMotor(_CONFIG)
        self.assertEqual(motor.timeout, 1)

    def test_emulation_flag_true(self):
        motor = TrinamicMotor(_CONFIG)
        self.assertTrue(motor.use_emulation)

    def test_emulation_flag_false_when_disabled(self):
        cfg = {**_CONFIG, 'emulation': {'enabled': False}}
        motor = TrinamicMotor(cfg)
        self.assertFalse(motor.use_emulation)

    def test_not_open_at_construction(self):
        motor = TrinamicMotor(_CONFIG)
        self.assertFalse(motor.is_open)

    def test_polling_not_active_at_construction(self):
        motor = TrinamicMotor(_CONFIG)
        self.assertFalse(motor.polling_active)


# -- Connection lifecycle -------------------------------------------------------

class TestTrinamicMotorConnection(unittest.TestCase):
    """open(), close(), and the context manager."""

    def test_open_sets_is_open(self):
        motor = TrinamicMotor(_CONFIG)
        motor.open()
        try:
            self.assertTrue(motor.is_open)
            self.assertIsNotNone(motor.port)
        finally:
            motor.close()

    def test_close_clears_is_open(self):
        motor = TrinamicMotor(_CONFIG)
        motor.open()
        motor.close()
        self.assertFalse(motor.is_open)

    def test_context_manager_opens_and_closes(self):
        with TrinamicMotor(_CONFIG) as motor:
            self.assertTrue(motor.is_open)
        self.assertFalse(motor.is_open)

    def test_send_command_raises_when_closed(self):
        motor = TrinamicMotor(_CONFIG)
        with self.assertRaises(RuntimeError):
            motor.send_command('GAP', 1, 0, 0)


# -- TMCL commands --------------------------------------------------------------

class TestTrinamicMotorCommands(unittest.TestCase):
    """TMCL command methods send the correct packets and return sensible values."""

    def setUp(self):
        self.motor = TrinamicMotor(_CONFIG)
        self.motor.open()

    def tearDown(self):
        self.motor.close()

    # -- Move absolute ----------------------------------------------------------

    def test_move_absolute_returns_true_on_success(self):
        self.assertTrue(self.motor.move_absolute(0, 1000))

    def test_move_absolute_all_motors(self):
        for motor_id in range(4):
            with self.subTest(motor_id=motor_id):
                self.assertTrue(self.motor.move_absolute(motor_id, 500))

    # -- Move relative ----------------------------------------------------------

    def test_move_relative_returns_true_on_success(self):
        self.assertTrue(self.motor.move_relative(0, 100))

    def test_move_relative_positive_and_negative(self):
        self.assertTrue(self.motor.move_relative(1, +200))
        self.assertTrue(self.motor.move_relative(1, -200))

    # -- Get position ------------------------------------------------------------

    def test_get_position_returns_int(self):
        pos = self.motor.get_position(0)
        self.assertIsInstance(pos, int)

    def test_get_position_initial_zero(self):
        """Mock serial initialises all motor positions to 0."""
        for motor_id in range(4):
            with self.subTest(motor_id=motor_id):
                self.assertEqual(self.motor.get_position(motor_id), 0)

    def test_get_position_after_move_absolute(self):
        """Position query after move_absolute reflects the commanded position."""
        self.motor.move_absolute(0, 2000)
        self.assertEqual(self.motor.get_position(0), 2000)

    def test_get_position_after_move_absolute_negative(self):
        self.motor.move_absolute(2, -750)
        self.assertEqual(self.motor.get_position(2), -750)

    def test_get_position_after_move_relative(self):
        """Relative moves accumulate correctly."""
        self.motor.move_absolute(1, 1000)
        self.motor.move_relative(1, 200)
        self.assertEqual(self.motor.get_position(1), 1200)

    def test_positions_are_independent_across_axes(self):
        """Moving one axis does not affect another axis's position."""
        self.motor.move_absolute(0, 1000)
        self.motor.move_absolute(2, 500)
        self.assertEqual(self.motor.get_position(0), 1000)
        self.assertEqual(self.motor.get_position(2), 500)

    # -- Rotate / stop ----------------------------------------------------------

    def test_rotate_right_returns_true(self):
        self.assertTrue(self.motor.rotate_right(0, 100))

    def test_rotate_left_returns_true(self):
        self.assertTrue(self.motor.rotate_left(0, 100))

    def test_stop_motor_returns_true(self):
        self.motor.rotate_right(0, 100)
        self.assertTrue(self.motor.stop_motor(0))

    # -- Axis parameters --------------------------------------------------------

    def test_set_axis_parameter_returns_true(self):
        self.assertTrue(self.motor.set_axis_parameter(0, 1, 0))

    def test_get_axis_parameter_returns_int(self):
        result = self.motor.get_axis_parameter(0, 1)
        self.assertIsInstance(result, int)


# -- Background polling ---------------------------------------------------------

class TestTrinamicMotorPolling(unittest.TestCase):
    """start_polling(), stop_polling(), and get_cached_positions()."""

    def setUp(self):
        self.motor = TrinamicMotor(_CONFIG)
        self.motor.open()

    def tearDown(self):
        if self.motor.polling_active:
            self.motor.stop_polling()
        self.motor.close()

    def test_start_polling_sets_flag(self):
        self.motor.start_polling()
        self.assertTrue(self.motor.polling_active)

    def test_stop_polling_clears_flag(self):
        self.motor.start_polling()
        self.motor.stop_polling()
        self.assertFalse(self.motor.polling_active)

    def test_double_start_is_harmless(self):
        """Calling start_polling() twice should not raise or start a second thread."""
        self.motor.start_polling()
        thread_before = self.motor.polling_thread
        self.motor.start_polling()   # second call — should be a no-op
        self.assertIs(self.motor.polling_thread, thread_before)

    def test_polling_populates_cache(self):
        """After a short wait the polling thread has populated motor_positions."""
        self.motor.start_polling()
        time.sleep(0.2)   # let polling thread run at least once
        self.motor.stop_polling()

        positions = self.motor.get_cached_positions()
        self.assertEqual(len(positions), 4)
        for motor_id in range(4):
            self.assertIn(motor_id, positions)

    def test_polling_reflects_move(self):
        """Cached position after a move_absolute matches the commanded value."""
        self.motor.move_absolute(0, 3000)
        self.motor.start_polling()
        time.sleep(0.2)
        self.motor.stop_polling()

        positions = self.motor.get_cached_positions()
        self.assertEqual(positions[0], 3000)

    def test_callback_is_called(self):
        """Polling thread invokes the registered callback with a positions dict."""
        received = []
        self.motor.start_polling(callback=lambda pos: received.append(pos))
        time.sleep(0.2)
        self.motor.stop_polling()

        self.assertGreater(len(received), 0)
        self.assertIsInstance(received[0], dict)

    def test_get_cached_positions_returns_copy(self):
        """Mutating the returned dict does not affect the internal cache."""
        self.motor.start_polling()
        time.sleep(0.15)
        self.motor.stop_polling()

        copy1 = self.motor.get_cached_positions()
        copy1[99] = 999   # mutate the copy
        copy2 = self.motor.get_cached_positions()
        self.assertNotIn(99, copy2)


if __name__ == '__main__':
    unittest.main()
