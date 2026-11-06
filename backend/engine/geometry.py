"""Pallet constants and rotation helpers.

Coordinate system (same as the robot workobject):
  origin  = bottom-right corner of the pallet seen from above, on the top deck surface
  +X      = along the 1200 mm edge
  +Y      = along the 800 mm edge
  +Z      = up
Rotation 0 deg: box length along X, box width along Y.
"""

PALLET_LENGTH_X = 1200.0  # EUR pallet, mm
PALLET_WIDTH_Y = 800.0
PALLET_HEIGHT = 144.0     # visual only, the pallet body lies below Z = 0

ALLOWED_ROTATIONS = (-90, 0, 90, 180)
EPS = 1e-6


def normalize_rotation(rot: float) -> int:
    """Map any multiple of 90 deg to one of -90, 0, 90, 180."""
    r = int(round(rot)) % 360
    if r not in (0, 90, 180, 270):
        raise ValueError(f"Rotation must be a multiple of 90 degrees, got {rot}")
    return -90 if r == 270 else r


def is_lengthwise(rot: float) -> bool:
    """True if the box length runs along X for this rotation."""
    return normalize_rotation(rot) in (0, 180)
