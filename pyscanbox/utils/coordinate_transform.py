"""
Coordinate transformation utilities for objective angle compensation.
"""

import math

DEFAULT_POSITIVE_ANGLE_INCREASES_X = True

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
