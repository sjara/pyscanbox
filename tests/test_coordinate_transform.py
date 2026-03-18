"""Tests for pyscanbox.utils.coordinate_transform.

Covers world_to_rotated, rotated_to_world, and tip_compensation_delta.
"""

import math
import unittest

import pyscanbox.utils.coordinate_transform as ct


class TestWorldToRotated(unittest.TestCase):
    """world_to_rotated converts world coordinates into the rotated frame."""

    def test_zero_angle_is_identity(self):
        x, y, z = ct.world_to_rotated(10.0, 20.0, 30.0, 0.0)
        self.assertAlmostEqual(x, 10.0)
        self.assertAlmostEqual(y, 20.0)
        self.assertAlmostEqual(z, 30.0)

    def test_y_unchanged(self):
        _, y, _ = ct.world_to_rotated(5.0, 42.0, 7.0, 45.0)
        self.assertAlmostEqual(y, 42.0)

    def test_roundtrip_default_convention(self):
        """world_to_rotated and rotated_to_world are inverses."""
        orig = (100.0, 0.0, -200.0)
        angle = 15.0
        rotated = ct.world_to_rotated(*orig, angle)
        back = ct.rotated_to_world(*rotated, angle)
        for got, expected in zip(back, orig):
            self.assertAlmostEqual(got, expected, places=9)

    def test_roundtrip_positive_angle_increases_x(self):
        orig = (100.0, 0.0, -200.0)
        angle = 30.0
        rotated = ct.world_to_rotated(*orig, angle, positive_angle_increases_x=True)
        back = ct.rotated_to_world(*rotated, angle, positive_angle_increases_x=True)
        for got, expected in zip(back, orig):
            self.assertAlmostEqual(got, expected, places=9)


class TestTipCompensationDelta(unittest.TestCase):
    """tip_compensation_delta returns correct XZ stage offsets."""

    def test_no_angle_change_gives_zero_delta(self):
        dx, dz = ct.tip_compensation_delta(10.0, 10.0, 98000.0)
        self.assertAlmostEqual(dx, 0.0)
        self.assertAlmostEqual(dz, 0.0)

    def test_zero_length_gives_zero_delta(self):
        dx, dz = ct.tip_compensation_delta(0.0, 30.0, 0.0)
        self.assertAlmostEqual(dx, 0.0)
        self.assertAlmostEqual(dz, 0.0)

    def test_small_angle_from_vertical_default_convention(self):
        """From 0° to 10°: dx/dz should match the analytic formula.

        Default: positive_angle_increases_x=True (positive angle → tip moves
        in +X direction).  Stage compensation must move in −X (negative dx)
        to hold the tip fixed.
        """
        L = 98000.0
        old_deg, new_deg = 0.0, 10.0
        old_rad = math.radians(old_deg)
        new_rad = math.radians(new_deg)
        # Default: positive_angle_increases_x=True → dx is negative.
        expected_dx = -L * (math.sin(new_rad) - math.sin(old_rad))
        expected_dz = L * (math.cos(new_rad) - math.cos(old_rad))
        dx, dz = ct.tip_compensation_delta(old_deg, new_deg, L)
        self.assertAlmostEqual(dx, expected_dx, places=6)
        self.assertAlmostEqual(dz, expected_dz, places=6)

    def test_small_angle_positive_x_convention(self):
        """Same range with positive_angle_increases_x=True: X sign negated."""
        L = 98000.0
        old_deg, new_deg = 0.0, 10.0
        old_rad = math.radians(old_deg)
        new_rad = math.radians(new_deg)
        expected_dx = -L * (math.sin(new_rad) - math.sin(old_rad))
        expected_dz = L * (math.cos(new_rad) - math.cos(old_rad))
        dx, dz = ct.tip_compensation_delta(old_deg, new_deg, L,
                                           positive_angle_increases_x=True)
        self.assertAlmostEqual(dx, expected_dx, places=6)
        self.assertAlmostEqual(dz, expected_dz, places=6)

    def test_z_delta_is_second_order_for_small_angles(self):
        """At small angles cos changes by ~θ²/2, so dz is second-order."""
        L = 98000.0
        dx, dz = ct.tip_compensation_delta(0.0, 1.0, L)
        # dz ≈ -L*(1-cosθ) ≈ -L*θ²/2 which is much smaller than dx ≈ -L*sinθ ≈ -L*θ
        self.assertLess(abs(dz), abs(dx))

    def test_symmetry_forward_backward(self):
        """delta(a → b) is the negative of delta(b → a)."""
        L = 98000.0
        dx_fwd, dz_fwd = ct.tip_compensation_delta(0.0, 20.0, L)
        dx_rev, dz_rev = ct.tip_compensation_delta(20.0, 0.0, L)
        self.assertAlmostEqual(dx_fwd, -dx_rev, places=9)
        self.assertAlmostEqual(dz_fwd, -dz_rev, places=9)

    def test_compensation_cancels_tip_displacement(self):
        """Applying the compensation should return the tip to its original position.

        Tip position in world coords (positive_angle_increases_x=True):
            tip_x = +L * sin(θ)   # positive angle → tip moves in +X
            tip_z = -L * cos(θ)   # tip below pivot, moves up as θ increases
        After moving the stage by (delta_x, delta_z) the effective tip
        position shifts back by the same amount, so the net displacement
        from the original tip position should be zero.
        """
        L = 98000.0
        old_deg, new_deg = 5.0, 25.0
        old_rad, new_rad = math.radians(old_deg), math.radians(new_deg)

        # Tip displacement in world (positive_angle_increases_x=True → tip_x = +L*sinθ)
        dtip_x = L * (math.sin(new_rad) - math.sin(old_rad))
        dtip_z = L * (math.cos(old_rad) - math.cos(new_rad))

        dx, dz = ct.tip_compensation_delta(old_deg, new_deg, L)
        # Stage moves cancel tip displacement: net = 0
        self.assertAlmostEqual(dtip_x + dx, 0.0, places=9)
        self.assertAlmostEqual(dtip_z + dz, 0.0, places=9)


if __name__ == '__main__':
    unittest.main()
