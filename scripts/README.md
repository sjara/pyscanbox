# Scripts

Standalone command-line scripts for working with pyscanbox recordings.
These scripts are thin CLI wrappers around the `pyscanbox.io` library modules
and do not contain any logic of their own.

## `sbx_to_tiff.py` — Convert .sbx to TIFF

Exports one multi-page TIFF per PMT channel.  Frames are written
incrementally so that large recordings (many GB) can be exported without
loading the entire dataset into RAM.

```bash
# Export all channels (creates <recording>_ch0.tif, _ch1.tif, ...):
python scripts/sbx_to_tiff.py /path/to/recording

# Export only PMT channel 0:
python scripts/sbx_to_tiff.py /path/to/recording --channel 0

# Explicit output path (requires --channel):
python scripts/sbx_to_tiff.py /path/to/recording --channel 0 --out /out/my.tif

# Force BigTIFF format (auto-selected for files > 4 GB):
python scripts/sbx_to_tiff.py /path/to/recording --bigtiff

# Export raw wire-format values (high = dark) instead of signal convention:
python scripts/sbx_to_tiff.py /path/to/recording --raw

# Suppress progress output:
python scripts/sbx_to_tiff.py /path/to/recording --quiet
```

**Requires:** `tifffile` (`pip install tifffile`)

**Output convention:** By default pixel values are written in **signal
convention** (high = bright fluorescence), matching Suite2p and other
downstream tools.  Pass `--raw` to write unmodified wire-format values.

---

## `mat_to_json.py` — Convert .mat metadata to JSON or YAML

Converts the `.mat` companion file produced by Scanbox or pyscanbox to a
human-readable format.  Both the original Scanbox nested-struct format and
the pyscanbox flat-key format are handled automatically.

```bash
# Convert to JSON (default):
python scripts/mat_to_json.py /path/to/recording

# Convert to YAML (more human-readable):
python scripts/mat_to_json.py /path/to/recording --format yaml

# Explicit output path:
python scripts/mat_to_json.py /path/to/recording --out /out/metadata.json

# Also accepts the .mat path directly:
python scripts/mat_to_json.py /path/to/recording.mat
```

**Requires:** `PyYAML` for YAML output (`pip install PyYAML`).
JSON output has no additional dependencies.

---

## Quick reference

| Script | Purpose | Requires |
|---|---|---|
| `sbx_to_tiff.py` | `.sbx` → multi-page TIFF | `tifffile` |
| `mat_to_json.py` | `.mat` → JSON or YAML | `PyYAML` (YAML only) |

---

## Design notes

All conversion logic lives in `pyscanbox/io/`:

- `tiff_exporter.py` — `save_channel_as_tiff()`, `save_all_channels_as_tiff()`
- `meta_exporter.py` — `load_mat_as_dict()`, `save_as_json()`, `save_as_yaml()`

The scripts in this directory only parse CLI arguments and call those
functions.  If you need to integrate conversion into a larger pipeline,
import from `pyscanbox.io` directly instead of calling these scripts.
