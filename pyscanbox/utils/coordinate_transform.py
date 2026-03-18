"""Coordinate transformation utilities for objective angle compensation.

This module provides geometry functions for converting between world (stage)
coordinates and the objective-rotated frame, as well as computing the stage
compensation needed to keep the objective tip at a fixed absolute position
when the tilt angle changes.

Sign conventions
----------------
The following physical conventions are used throughout this module and
throughout the pyscanbox GUI.  They match the hardware wiring of the
objective manipulator:

* **+X** — Objective moves to the **left** (from the experimenter's
  perspective facing the microscope).  Positive X knob turns move the
  objective leftward.

* **+Y** — Objective moves **posterior** with respect to the sample
  (away from the experimenter).  Positive Y knob turns retract the
  objective posteriorly.

* **+Z** — Objective moves **up** (retracting focus from the sample).
  Positive Z knob turns raise the objective.

* **Positive angle (θ > 0)** — Objective tilts such that the tip moves
  in the **+X direction** (to the left) **and +Z direction** (upward).
  At θ = 0 the objective points straight down.

These conventions are encoded in ``DEFAULT_POSITIVE_ANGLE_INCREASES_X``
below, which is the single reference used by all functions as their default
parameter value.
"""

import math

# Sign convention flag: True because in our hardware a positive angle rotation
# tilts the objective tip toward +X (left) and +Z (up), as described in the
# module docstring above.  All functions default to this value; override only
# when working with a differently wired manipulator.
DEFAULT_POSITIVE_ANGLE_INCREASES_X = True

def world_to_rotated(x, y, z, angle_deg, positive_angle_increases_x=DEFAULT_POSITIVE_ANGLE_INCREASES_X):
    """Convert from world (knobby) coordinates to the objective-rotated frame.

    Args:
        x, y, z: World coordinates in μm (see module-level sign conventions).
        angle_deg: Objective tilt angle in degrees.  0 = pointing straight
            down.  Positive = tip tilted toward +X (+left) and +Z (+up).
        positive_angle_increases_x: Sign convention.  ``True`` (default)
            matches the pyscanbox hardware: positive angle tilts the tip
            toward +X.  Override only for a differently wired manipulator.

    Returns:
        ``(x_rot, y_rot, z_rot)`` — coordinates in the frame aligned with
        the objective axis, in μm.
    """
    angle_rad = math.radians(angle_deg)
    if not positive_angle_increases_x:
        angle_rad = -angle_rad
    x_rot = x * math.cos(angle_rad) - z * math.sin(angle_rad)
    y_rot = y
    z_rot = x * math.sin(angle_rad) + z * math.cos(angle_rad)
    return (x_rot, y_rot, z_rot)

def rotated_to_world(x_rot, y_rot, z_rot, angle_deg, positive_angle_increases_x=DEFAULT_POSITIVE_ANGLE_INCREASES_X):
    """Convert from the objective-rotated frame back to world (knobby) coordinates.

    Inverse of :func:`world_to_rotated`.

    Args:
        x_rot, y_rot, z_rot: Coordinates in the objective-aligned frame, in μm.
        angle_deg: Objective tilt angle in degrees (same convention as
            :func:`world_to_rotated`).
        positive_angle_increases_x: Sign convention — must match the value
            used when calling :func:`world_to_rotated`.  Defaults to
            ``DEFAULT_POSITIVE_ANGLE_INCREASES_X`` (``True``).

    Returns:
        ``(x, y, z)`` — world coordinates in μm.
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

    Geometry (sign convention: positive angle tilts tip toward +X and +Z)
        When the objective is at angle θ, the tip position relative to the
        pivot is::

            tip_x = +L * sin(θ)   # positive angle → tip moves right (+X = left)
            tip_z = -L * cos(θ)   # tip always below pivot; moves up as θ increases

        The change in tip position from θ_old to θ_new is::

            Δtip_x = +L * (sin(θ_new) - sin(θ_old))   > 0 for positive rotation
            Δtip_z = -L * (cos(θ_new) - cos(θ_old))   > 0 for positive rotation

        To keep the tip fixed in space the stage must move opposite to the tip::

            delta_x_stage = -Δtip_x = -L * (sin(θ_new) - sin(θ_old))
            delta_z_stage = -Δtip_z =  L * (cos(θ_new) - cos(θ_old))

        Both values are negative for a positive rotation (cos(θ_new)<cos(θ_old)
        and sin(θ_new)>sin(θ_old)), meaning the stage moves in -X and -Z
        (objective moves right and down) to compensate for the tip moving
        left and up.

    Args:
        angle_old_deg: Current objective angle in degrees.
        angle_new_deg: New objective angle in degrees after the move.
        obj_length_um: Distance from the rotation center to the objective tip
            in micrometers.  Source: ``config['objective']['length']``.
        positive_angle_increases_x: Sign convention — ``True`` (default)
            means positive angle tilts the tip toward +X, matching the
            pyscanbox hardware.  Flip only for a differently wired rig.

    Returns:
        Tuple ``(delta_x_um, delta_z_um)``: stage displacements in micrometers
        to add to the current X and Z motor targets.  Both are negative for a
        positive rotation (stage moves in -X and -Z to hold the tip fixed).

    Example:
        >>> import pyscanbox.utils.coordinate_transform as ct
        >>> ct.tip_compensation_delta(0.0, 10.0, 98000.0)  # doctest: +ELLIPSIS
        (-17017.52..., -1488.84...)
    """
    old_rad = math.radians(angle_old_deg)
    new_rad = math.radians(angle_new_deg)
    # Compensation for positive_angle_increases_x=True convention:
    #   tip moves in +X → stage must move in -X to hold it fixed.
    #   tip moves in +Z → stage must move in -Z to hold it fixed.
    delta_x_um = -obj_length_um * (math.sin(new_rad) - math.sin(old_rad))
    delta_z_um = obj_length_um * (math.cos(new_rad) - math.cos(old_rad))
    if not positive_angle_increases_x:
        # Flip X for the opposite-wired convention.
        delta_x_um = -delta_x_um
    return (delta_x_um, delta_z_um)
