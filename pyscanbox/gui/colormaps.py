# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Shared colormap lookup-table utilities for pyscanbox GUI.

Provides the single source of truth for PMT display colormaps used by
both ImageDisplayWidget and HistogramWidget.
"""

import numpy as np


# Scaling factor applied to the red channel in the 'red_white' colormap.
# Compensates for the lower perceived brightness of red vs. green so that
# PMT1 (red) and PMT0 (green) appear equally bright at the same gain.
_RED_BOOST: float = 1.963


def _build_colormap_lut(name: str, red_boost: float | None = None) -> np.ndarray:
    """Build a 256×3 uint8 lookup table for a named colormap.

    This is the single source of truth for all display colormaps; both
    ``HistogramWidget`` and ``ImageDisplayWidget`` use this function.

    Args:
        name: Colormap name ('green', 'green_white', 'red', 'red_white', 'gray').
        red_boost: Optional scaling factor for red channel (red_white only).
            Defaults to the module-level ``_RED_BOOST`` constant.

    Returns:
        256×3 uint8 array where lut[i] = [R, G, B] for intensity i.
    """
    v = np.arange(256, dtype=np.float32)
    lut = np.zeros((256, 3), dtype=np.uint8)
    if name == 'green_white':
        # G ramps 0→255 linearly (same as plain green).
        lut[:, 1] = v.astype(np.uint8)
        # R and B stay 0 until v=128, then ramp to 255 — creates the
        # transition from green to white in the upper half of the range.
        white = np.clip(2.0 * v - 255.0, 0.0, 255.0).astype(np.uint8)
        lut[:, 0] = white
        lut[:, 2] = white
    elif name == 'red_white':
        # R ramps 0→255 scaled by _RED_BOOST.
        # Tune _RED_BOOST to adjust perceived brightness independently of the
        # white blend.  The white onset is fixed at v=128 (same fraction as
        # green_white) so changing _RED_BOOST never shifts when the colour
        # saturates to white.
        boost = red_boost if red_boost is not None else _RED_BOOST
        r = np.clip(v * boost, 0.0, 255.0).astype(np.uint8)
        lut[:, 0] = r
        # White blend: G and B kick in at v=128, independent of boost.
        white = np.clip(2.0 * v - 255.0, 0.0, 255.0).astype(np.uint8)
        lut[:, 1] = white
        lut[:, 2] = white
    elif name == 'red':
        lut[:, 0] = v.astype(np.uint8)
    elif name == 'gray':
        lut[:, 0] = v.astype(np.uint8)
        lut[:, 1] = v.astype(np.uint8)
        lut[:, 2] = v.astype(np.uint8)
    else:  # 'green' (default)
        lut[:, 1] = v.astype(np.uint8)
    return lut
