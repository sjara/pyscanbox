# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Format-agnostic acquisition metadata for pyscanbox.

:class:`AcquisitionMetadata` is a plain dataclass that captures everything
recorded during one acquisition run.  Attribute names follow Python
conventions (snake_case).  Each file-format writer is responsible for
mapping these to its own format-specific field names — for example,
:meth:`pyscanbox.io.sbx_writer.SbxWriter.write_mat` maps them to the
MATLAB ``info`` struct layout understood by ``sbxread.m``.

Example::

    >>> from pyscanbox.io.metadata import AcquisitionMetadata
    >>> meta = AcquisitionMetadata(
    ...     lines_per_frame=512, pixels_per_line=796, nchan=2, frames=100,
    ...     channels_mask=1, scanmode=1, resonant_freq=7930,
    ...     post_trigger_samples=5000, records_per_buffer=512,
    ...     sample_rate=125_000_000,
    ... )
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np


@dataclass
class AcquisitionMetadata:
    """Format-agnostic description of one acquisition run.

    Attribute names follow Python conventions (snake_case).  Each writer
    maps them to its own format-specific field names.

    Only the fields listed under *Required* must be supplied; everything
    else defaults to a safe value so that only the values that differ
    from the defaults need to be set.

    Required fields
    ---------------
    lines_per_frame, pixels_per_line, nchan, frames, channels_mask,
    scanmode, resonant_freq, post_trigger_samples, records_per_buffer,
    sample_rate

    Optional fields (grouped by topic)
    -----------------------------------
    *Magnification* — magnification, magnification_list

    *PMT gains* — pmt0_gain, pmt1_gain

    *Laser / Pockels* — laser_wavelength, laser_type, pockels_base,
    pockels_active

    *Objective* — objective, objective_type

    *Motor (Knobby)* — knobby_x, knobby_y, knobby_z, knobby_a

    *Volume scanning* — volscan, fold_lines

    *Optogenetics* — otwave, otwave_um, otparam, otwavestyle, opto2pow,
    power_depth_link, area_line

    *Scan quality* — abort_bit, ballmotion

    *TTL events* — ttl_frame, ttl_line, ttl_event_id

    *User annotation* — messages, usernotes

    *Provenance* — timestamp, pyscanbox_version

    *Plugins* — plugin_data
    """

    # ------------------------------------------------------------------
    # Required (no defaults)
    # ------------------------------------------------------------------

    lines_per_frame: int
    """Number of scan lines per frame."""

    pixels_per_line: int
    """Number of pixels per scan line."""

    nchan: int
    """Number of PMT channels saved (1 or 2)."""

    frames: int
    """Total frames acquired."""

    channels_mask: int
    """Scanbox channel bitmask: 1 = both PMT0 & PMT1, 2 = PMT0 only, 3 = PMT1 only."""

    scanmode: int
    """Scan direction: 1 = unidirectional, 0 = bidirectional."""

    resonant_freq: int
    """Resonant mirror frequency in Hz (e.g. 7930)."""

    post_trigger_samples: int
    """Raw ADC samples per scan line (AlazarSetRecordSize post-trigger count)."""

    records_per_buffer: int
    """Scan lines per DMA buffer.

    Unidirectional: equals ``lines_per_frame``.
    Bidirectional: equals ``lines_per_frame // 2``.
    """

    sample_rate: int
    """Alazar ADC sample rate in Hz (e.g. 125_000_000)."""

    # ------------------------------------------------------------------
    # Magnification
    # ------------------------------------------------------------------

    magnification: int = 0
    """0-based index into the magnification list (0 = lowest magnification)."""

    magnification_list: List[float] = field(
        default_factory=list
    )
    """List of magnification values (floats, e.g., [1.0, 1.2, 1.4, ...]).
    
    This list maps magnification indices to their numeric zoom levels.
    Required by sbxreader (used by Suite2p) which reads these values directly.
    """

    # ------------------------------------------------------------------
    # PMT gains
    # ------------------------------------------------------------------

    pmt0_gain: float = 1.0
    """PMT 0 gain value (1.0 = unity)."""

    pmt1_gain: float = 1.0
    """PMT 1 gain value (1.0 = unity)."""

    # ------------------------------------------------------------------
    # Laser / Pockels
    # ------------------------------------------------------------------

    laser_wavelength: int = 0
    """Laser wavelength in nm (0 = unknown/not recorded)."""

    laser_type: str = ''
    """Laser model string (e.g. "Chameleon Ultra II")."""

    pockels_base: int = 0
    """Pockels cell baseline power setting (0–255 DAC units)."""

    pockels_active: int = 0
    """Pockels cell active (imaging) power setting (0–255 DAC units)."""

    # ------------------------------------------------------------------
    # Objective
    # ------------------------------------------------------------------

    objective: str = ''
    """Objective label as shown in the GUI (e.g. "Nikon 16x 0.8NA water")."""

    objective_type: str = ''
    """Objective type string from config (e.g. "16x")."""

    # ------------------------------------------------------------------
    # Motor (Knobby) positions in microns
    # ------------------------------------------------------------------

    knobby_x: float = 0.0
    knobby_y: float = 0.0
    knobby_z: float = 0.0
    knobby_a: float = 0.0

    # ------------------------------------------------------------------
    # Volume / z-stack scanning
    # ------------------------------------------------------------------

    volscan: int = 0
    """1 = volume scan active, 0 = single plane."""

    fold_lines: int = 0
    """Number of lines folded (for line-interleaved protocols)."""

    # ------------------------------------------------------------------
    # Optogenetics (empty arrays by default — matches original Scanbox)
    # ------------------------------------------------------------------

    otwave: np.ndarray = field(
        default_factory=lambda: np.array([], dtype=np.uint8)
    )
    otwave_um: np.ndarray = field(
        default_factory=lambda: np.array([], dtype=np.uint8)
    )
    otparam: np.ndarray = field(
        default_factory=lambda: np.array([], dtype=np.uint8)
    )
    otwavestyle: int = 1

    opto2pow: np.ndarray = field(
        default_factory=lambda: np.array([], dtype=np.uint8)
    )
    power_depth_link: int = 0
    """1 = laser power linked to depth (z), 0 = independent."""

    area_line: int = 1
    """1 = area scan, 0 = line scan."""

    # ------------------------------------------------------------------
    # Scan quality
    # ------------------------------------------------------------------

    abort_bit: int = 0
    """1 if acquisition was aborted before completion, 0 otherwise."""

    ballmotion: np.ndarray = field(
        default_factory=lambda: np.array([], dtype=np.uint8)
    )
    """Ball / rotary encoder motion data (empty if not recorded)."""

    # ------------------------------------------------------------------
    # TTL event timestamps (from PSoC5 event log, mirrors sb_timestamps.m)
    # ------------------------------------------------------------------

    ttl_frame: np.ndarray = field(
        default_factory=lambda: np.array([], dtype=np.int32)
    )
    """Frame index of each captured TTL event."""

    ttl_line: np.ndarray = field(
        default_factory=lambda: np.array([], dtype=np.int32)
    )
    """Line index of each captured TTL event."""

    ttl_event_id: np.ndarray = field(
        default_factory=lambda: np.array([], dtype=np.int32)
    )
    """Event identifier of each captured TTL event."""

    # ------------------------------------------------------------------
    # User-facing annotation
    # ------------------------------------------------------------------

    messages: List[str] = field(default_factory=list)
    """Free-form messages logged during the acquisition."""

    usernotes: str = ''
    """Free-form user notes entered in the GUI before saving."""

    # ------------------------------------------------------------------
    # Provenance / versioning
    # ------------------------------------------------------------------

    timestamp: str = field(
        default_factory=lambda: time.strftime('%Y-%m-%d %H:%M:%S')
    )
    """ISO-style wall-clock time when the metadata object was created."""

    pyscanbox_version: str = ''
    """pyscanbox package version string."""

    # ------------------------------------------------------------------
    # Plugin-supplied supplementary data
    # ------------------------------------------------------------------

    plugin_data: Dict[str, Any] = field(default_factory=dict)
    """Arbitrary key-value pairs contributed by plugins.

    Each plugin adds its own fields here.  Writers decide how to
    serialise them (e.g. merged into the ``.mat`` info struct, or written
    to a sidecar file).  Keys must be strings; values must be
    serialisable by the target format.
    """
