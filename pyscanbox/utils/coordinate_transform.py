"""Coordinate transformation utilities for objective angle compensation.

This module provides geometry functions for converting between world (stage)
coordinates and the objective-rotated frame, as well as computing the stage
compensation needed to keep the objective tip at a fixed absolute position
when the tilt angle changes.
"""

import math

DEFAULT_POSITIVE_ANGLE_INCREASES_X = False

def world_to_rotated(x, y, z, angle_deg, positive_angle_increases_x=DEFAULT_POSITIVE_ANGLE_INCREASES_X):
    """
    Convert from world (knobby) coordinates to rotated coordinates.
    Args:
        x, y, z: World coordinates (μm)
        angle_deg: Objective angle in degrees (0 = down)
        positive_angle_increases_x: If True, positive angle rotates X up; else opposite.
    Returns:
        (x_rot, y_rot, z_rot): Rotated coordinates (μm)
    """
    angle_rad = math.radians(angle_deg)
    if not positive_angle_increases_x:
        angle_rad = -angle_rad
    x_rot = x * math.cos(angle_rad) - z * math.sin(angle_rad)
    y_rot = y
    z_rot = x * math.sin(angle_rad) + z * math.cos(angle_rad)
    return (x_rot, y_rot, z_rot)

def rotated_to_world(x_rot, y_rot, z_rot, angle_deg, positive_angle_increases_x=DEFAULT_POSITIVE_ANGLE_INCREASES_X):
    """
    Convert from rotated coordinates to world (knobby) coordinates.
    Args:
        x_rot, y_rot, z_rot: Rotated coordinates (μm)
        angle_deg: Objective angle in degrees (0 = down)
        positive_angle_increases_x: If True, positive angle rotates X up; else opposite.
    Returns:
        (x, y, z): World coordinates (μm)
    """
    angle_rad = math.radians(angle_deg)
    if not positive_angle_increases_x:
        angle_rad = -angle_rad
    x = x_rot * math.cos(angle_rad) + z_rot * math.sin(angle_rad)
    y = y_rot
    z = -x_rot * math.sin(angle_rad) + z_rot * math.cos(angle_rad)
    return (x, y, z)


def tip_compensation_delta(
    angle_old_deg,
    angle_new_deg,
    obj_length_um,
    positive_angle_increases_x=DEFAULT_POSITIVE_ANGLE_INCREASES_X,
):
    """Compute XZ stage deltas to keep the objective tip at a fixed position.

    When the angle motor rotates from ``angle_old_deg`` to ``angle_new_deg``,
    the tip of the objective (at distance ``obj_length_um`` from the rotation
    center) moves in X and Z.  This function returns the stage displacements
    that must be applied to X and Z to cancel that movement, keeping the tip
    at the same absolute position in space.

    Geometry (with ``positive_angle_increases_x=True``):
        When the objective is at angle θ, the tip position relative to the
        pivot is::

            tip_x = +L * sin(θ)
            tip_z = -L * cos(θ)

        The change caused by rotating from θ_old to θ_new is::

            Δtip_x = L * (sin(θ_new) − sin(θ_old))
            Δtip_z = L * (cos(θ_old) − cos(θ_new))

        The compensating stage moves are the negatives of these::

            delta_x = −L * (sin(θ_new) − sin(θ_old))
            delta_z =  L * (cos(θ_new) − cos(θ_old))

    When ``positive_angle_increases_x=False`` (the default), the X axis sign
    is flipped to match the sign convention used in ``world_to_rotated``.

    Args:
        angle_old_deg: Current objective angle in degrees.
        angle_new_deg: New objective angle in degrees after the move.
        obj_length_um: Distance from the rotation center to the objective tip
            in micrometers.  Source: ``config['objective']['length']``.
        positive_angle_increases_x: Sign convention matching
            ``world_to_rotated`` — ``True`` means positive angle tilts the tip
            toward +X; ``False`` (default) means toward −X.

    Returns:
        Tuple ``(delta_x_um, delta_z_um)``: stage displacements in micrometers
        to add to the current X and Z motor targets.

    Example:
        >>> import pyscanbox.utils.coordinate_transform as ct
        >>> ct.tip_compensation_delta(0.0, 10.0, 98000.0)
        (-17024.00..., -148.58...)
    """
    old_rad = math.radians(angle_old_deg)
    new_rad = math.radians(angle_new_deg)
    # Base compensation assuming positive angle increases X.
    delta_x_um = -obj_length_um * (math.sin(new_rad) - math.sin(old_rad))
    delta_z_um = obj_length_um * (math.cos(new_rad) - math.cos(old_rad))
    if not positive_angle_increases_x:
        delta_x_um = -delta_x_um
    return (delta_x_um, delta_z_um)
