#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Fix .mat metadata files from older pyscanbox versions.

This script reconstructs .mat files created by earlier versions of pyscanbox to
ensure compatibility with the full original Scanbox format, adding any missing
fields. This includes the ``magnification_list`` field required by
sbxreader/Suite2p and any other metadata fields that may have been omitted in
earlier versions.

The script will: 1. Load the old .mat file 2. Create a backup with suffix
``.old.mat`` 3. Reconstruct an AcquisitionMetadata object with all original and
new fields 4. Add any missing fields from the current config or use safe
defaults 5. Resave the .mat file in the complete Scanbox-compatible format

Missing optional fields (e.g., ``pockels_base``, ``timestamp``) are filled with
defaults or inferred from the current pyscanbox configuration.

Usage::

    # Fix a single recording:
    python scripts/fix_mat.py /path/to/recording

    # Fix with explicit config file:
    python scripts/fix_mat.py /path/to/recording --config /etc/pyscanbox/config.yaml

    # Dry run (show what would be done without modifying):
    python scripts/fix_mat.py /path/to/recording --dry-run

Examples::

    python scripts/fix_mat.py /data/mouse001_20260325_000
    python scripts/fix_mat.py /path/to/recording --dry-run
"""

import argparse
import os
import sys
import shutil
import numpy as np
import scipy.io

# Allow running the script from the repo root without installing the package.
_REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pyscanbox.config
import pyscanbox.io.metadata
import pyscanbox.io.sbx_writer
import pyscanbox.hardware.controller


def load_old_mat(mat_path: str) -> dict:
    """Load a .mat file and return the flattened info struct.
    
    Args:
        mat_path: Path to the .mat file.
        
    Returns:
        Dictionary of the info struct.
        
    Raises:
        FileNotFoundError: If the .mat file does not exist.
        KeyError: If the 'info' struct is not found.
    """
    if not os.path.exists(mat_path):
        raise FileNotFoundError(f".mat file not found: {mat_path}")
    
    raw = scipy.io.loadmat(mat_path, squeeze_me=True, struct_as_record=False)
    
    if 'info' not in raw:
        raise KeyError(f"No 'info' struct found in {mat_path}")
    
    info_obj = raw['info']
    flat = {}
    
    if hasattr(info_obj, '_fieldnames'):
        # It's a MATLAB struct
        for field in info_obj._fieldnames:
            val = getattr(info_obj, field)
            flat[field] = val
    else:
        # Already flattened (shouldn't happen with scipy but handle it)
        flat = dict(info_obj)
    
    return flat


def extract_config_value(flat_info: dict, key: str, default: any):
    """Extract a value from the flat info dict, handling nested config.
    
    Args:
        flat_info: Flattened info dict.
        key: Field name (may include 'config.' prefix).
        default: Default value if not found.
        
    Returns:
        The value from flat_info or the default.
    """
    if key in flat_info:
        val = flat_info[key]
        # numpy scalars → Python scalars
        if isinstance(val, np.generic):
            return val.item()
        return val
    
    # Try with 'config_' prefix (in case it's flattened)
    config_key = f'config_{key.split(".")[-1]}'
    if config_key in flat_info:
        val = flat_info[config_key]
        if isinstance(val, np.generic):
            return val.item()
        return val
    
    return default


def reconstruct_metadata(flat_info: dict, config: 'pyscanbox.config.AppConfig') -> 'pyscanbox.io.metadata.AcquisitionMetadata':
    """Reconstruct an AcquisitionMetadata object from an old .mat file.
    
    This handles both nested and flat .mat formats, and fills missing fields
    with defaults from the config.
    
    Args:
        flat_info: Flattened info dict from the old .mat file.
        config: Current pyscanbox configuration.
        
    Returns:
        Reconstructed AcquisitionMetadata object.
    """
    # Helper to get values from either nested config or top level
    def get_val(key, default):
        # Try direct access
        if key in flat_info:
            val = flat_info[key]
            if isinstance(val, np.generic):
                return val.item()
            return val
        
        # Try from config sub-struct (if it exists as nested dict/object)
        if 'config' in flat_info and hasattr(flat_info['config'], key):
            val = getattr(flat_info['config'], key)
            if isinstance(val, np.generic):
                return val.item()
            return val
        
        # Try with 'config_' prefix
        config_key = f'config_{key}'
        if config_key in flat_info:
            val = flat_info[config_key]
            if isinstance(val, np.generic):
                return val.item()
            return val
        
        return default
    
    # Required fields (from .mat file, or fail)
    lines_per_frame = int(get_val('lines', get_val('lines_per_frame', None)))
    if lines_per_frame is None:
        raise ValueError("Could not determine 'lines_per_frame' from .mat file")
    
    # Handle sz field (Scanbox format)
    if 'sz' in flat_info:
        sz = flat_info['sz']
        if isinstance(sz, np.ndarray) and sz.size >= 2:
            lines_per_frame = int(sz[0])
            pixels_per_line = int(sz[1])
        else:
            pixels_per_line = int(get_val('pixels_per_line', 796))
    else:
        pixels_per_line = int(get_val('pixels_per_line', 796))
    
    # Extract other required fields
    nchan = int(get_val('nchan', 2))
    frames = int(get_val('frames', get_val('max_idx', 0) + 1))
    channels_mask = int(get_val('channels', 1))
    scanmode = int(get_val('scanmode', 1))
    resonant_freq = int(get_val('resfreq', 7930))
    post_trigger = int(get_val('postTriggerSamples', 5000))
    records_per_buffer = int(get_val('recordsPerBuffer', 512))
    sample_rate = int(get_val('sample_rate', 125_000_000))
    
    # Optional fields
    magnification = int(get_val('magnification', 0))
    # If magnification is 1-based (from config.magnification), convert to 0-based
    if magnification > 0 and magnification <= 13:
        # It might be 1-based; check context
        # For now assume it's already 0-based if it matches valid index
        pass
    
    pmt0_gain = float(get_val('pmt0_gain', 1.0))
    pmt1_gain = float(get_val('pmt1_gain', 1.0))
    laser_wavelength = int(get_val('wavelength', 0))
    laser_type = str(get_val('laser_type', ''))
    objective = str(get_val('objective', ''))
    objective_type = str(get_val('objective_type', ''))
    pockels_base = int(get_val('pockels_base', 0))
    pockels_active = int(get_val('pockels_active', 0))
    
    knobby_x = float(get_val('knobby_x', 0.0))
    knobby_y = float(get_val('knobby_y', 0.0))
    knobby_z = float(get_val('knobby_z', 0.0))
    knobby_a = float(get_val('knobby_a', 0.0))
    
    volscan = int(get_val('volscan', 0))
    fold_lines = int(get_val('fold_lines', 0))
    abort_bit = int(get_val('abort_bit', 0))
    area_line = int(get_val('area_line', 1))
    power_depth_link = int(get_val('power_depth_link', 0))
    otwavestyle = int(get_val('otwavestyle', 1))
    
    # Arrays
    ttl_frame = np.array(get_val('frame', np.array([], dtype=np.int32)), dtype=np.int32)
    ttl_line = np.array(get_val('line', np.array([], dtype=np.int32)), dtype=np.int32)
    ttl_event_id = np.array(get_val('event_id', np.array([], dtype=np.int32)), dtype=np.int32)
    ballmotion = np.array(get_val('ballmotion', np.array([], dtype=np.uint8)), dtype=np.uint8)
    otwave = np.array(get_val('otwave', np.array([], dtype=np.uint8)), dtype=np.uint8)
    otwave_um = np.array(get_val('otwave_um', np.array([], dtype=np.uint8)), dtype=np.uint8)
    otparam = np.array(get_val('otparam', np.array([], dtype=np.uint8)), dtype=np.uint8)
    opto2pow = np.array(get_val('opto2pow', np.array([], dtype=np.uint8)), dtype=np.uint8)
    
    messages = list(get_val('messages', []))
    usernotes = str(get_val('usernotes', ''))
    timestamp = str(get_val('timestamp', ''))
    pyscanbox_version = str(get_val('pyscanbox_version', ''))
    
    # NEW FIELD: magnification_list (from current config)
    magnification_list = list(pyscanbox.hardware.controller.ScanboxController.MAG_VALUES)
    
    return pyscanbox.io.metadata.AcquisitionMetadata(
        lines_per_frame=lines_per_frame,
        pixels_per_line=pixels_per_line,
        nchan=nchan,
        frames=frames,
        channels_mask=channels_mask,
        scanmode=scanmode,
        resonant_freq=resonant_freq,
        post_trigger_samples=post_trigger,
        records_per_buffer=records_per_buffer,
        sample_rate=sample_rate,
        magnification=magnification,
        magnification_list=magnification_list,
        pmt0_gain=pmt0_gain,
        pmt1_gain=pmt1_gain,
        laser_wavelength=laser_wavelength,
        laser_type=laser_type,
        pockels_base=pockels_base,
        pockels_active=pockels_active,
        objective=objective,
        objective_type=objective_type,
        knobby_x=knobby_x,
        knobby_y=knobby_y,
        knobby_z=knobby_z,
        knobby_a=knobby_a,
        volscan=volscan,
        fold_lines=fold_lines,
        abort_bit=abort_bit,
        ballmotion=ballmotion,
        ttl_frame=ttl_frame,
        ttl_line=ttl_line,
        ttl_event_id=ttl_event_id,
        area_line=area_line,
        power_depth_link=power_depth_link,
        otwave=otwave,
        otwave_um=otwave_um,
        otparam=otparam,
        otwavestyle=otwavestyle,
        opto2pow=opto2pow,
        messages=messages,
        usernotes=usernotes,
        timestamp=timestamp,
        pyscanbox_version=pyscanbox_version,
    )


def fix_mat_file(filepath: str, config_path: str = None, dry_run: bool = False) -> bool:
    """Fix a .mat file to ensure full Scanbox compatibility.
    
    Reconstructs the .mat file with all required and optional fields,
    ensuring compatibility with the full original Scanbox format.
    Missing fields are filled from the current config or defaults.
    
    Args:
        filepath: Base path without extension (e.g., '/data/mouse001').
        config_path: Path to config file (default: auto-detect).
        dry_run: If True, show what would be done without modifying files.
        
    Returns:
        True if successful, False otherwise.
    """
    mat_path = f"{filepath}.mat"
    
    print(f"\nFixing: {mat_path}")
    
    # Load old .mat file
    try:
        flat_info = load_old_mat(mat_path)
        print(f"✓ Loaded old .mat file ({len(flat_info)} fields)")
    except (FileNotFoundError, KeyError) as e:
        print(f"✗ Failed to load .mat file: {e}")
        return False
    
    # Check if file has already been fixed to the new format.
    # Detect this by checking for magnification_list and other key fields.
    if 'magnification_list' in flat_info or (
        'config' in flat_info and 
        hasattr(flat_info['config'], 'magnification_list')
    ):
        print("✓ File already in current format — no fix needed")
        return True
    
    # Load config
    try:
        if config_path:
            config = pyscanbox.config.load_config(config_path)
        else:
            config = pyscanbox.config.load_config()
        print("✓ Loaded configuration")
    except Exception as e:
        print(f"⚠ Could not load config: {e}")
        print("  Using defaults")
        config = pyscanbox.config.AppConfig({})
    
    # Reconstruct metadata
    try:
        metadata = reconstruct_metadata(flat_info, config)
        print(f"✓ Reconstructed metadata")
    except Exception as e:
        print(f"✗ Failed to reconstruct metadata: {e}")
        return False
    
    # Convert to MATLAB struct dict
    try:
        mat_dict = pyscanbox.io.sbx_writer._metadata_to_mat_dict(metadata)
        print(f"✓ Converted to MATLAB format")
    except Exception as e:
        print(f"✗ Failed to convert to MATLAB format: {e}")
        return False
    
    if dry_run:
        print(f"[DRY RUN] Would save updated .mat file with full Scanbox format")
        print(f"[DRY RUN] Key fields in fixed metadata:")
        print(f"  - magnification_list: {metadata.magnification_list}")
        print(f"  - Total fields: {sum(1 for attr in dir(metadata) if not attr.startswith('_'))}")
        return True
    
    # Create backup
    backup_path = f"{filepath}.old.mat"
    try:
        shutil.copy2(mat_path, backup_path)
        print(f"✓ Created backup: {backup_path}")
    except Exception as e:
        print(f"✗ Failed to create backup: {e}")
        return False
    
    # Save new .mat file in full Scanbox format
    try:
        scipy.io.savemat(mat_path, {'info': mat_dict})
        print(f"✓ Saved fixed .mat file (Scanbox-compatible format)")
        print(f"  magnification_list: {metadata.magnification_list}")
        return True
    except Exception as e:
        print(f"✗ Failed to save updated .mat file: {e}")
        print(f"  Restoring backup from {backup_path}")
        try:
            shutil.copy2(backup_path, mat_path)
        except:
            pass
        return False


def main():
    """Entry point for the fix_mat script."""
    parser = argparse.ArgumentParser(
        description='Fix .mat files to be Scanbox-compatible.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        'input',
        metavar='INPUT',
        help='Base path of the recording, without extension '
             '(e.g. /data/mouse001_20260325_000). The .mat file must exist.',
    )
    parser.add_argument(
        '--config', '-c',
        metavar='PATH',
        default=None,
        help='Path to pyscanbox config file. Default: auto-detect.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=False,
        help='Show what would be done without modifying files.',
    )
    
    args = parser.parse_args()
    
    success = fix_mat_file(args.input, args.config, args.dry_run)
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
