# pyscanbox Changelog

All notable changes to this project are documented here. This file is append-only, do not edit past entries.

> **Reminder:** When adding a new version entry, also bump the version string in `pyscanbox/__init__.py` to match.


## v1.17.0.dev0 - Jun 4, 2026
- **Enhancement: Quadrature plugin output format**
  - Saved `.npy` file is now a 2-column int32 array `(n_samples, 2)`: col 0 = frame index, col 1 = raw encoder count. Dropped samples (USB latency timeouts) are detectable by inspecting gaps in column 0.
  - Fixed off-by-one: the last frame's poll response was never read; `on_acquisition_stop` now reads it before saving.
  - Fixed `.mat` sidecar corruption: `quadrature_calibration_cm_per_count` (35 chars) exceeded MATLAB's 31-char field name limit; renamed to `quadrature_cal_cm_per_count`.
  - `quadrature_file` in the `.mat` sidecar now stores the filename only, not the full path.
  - Updated user guide (`docs/user_guide/plugins/quadrature.md`) to reflect new array shape, clarify raw integer units, and move the Calibration section after Output Data.

## v1.16.0.dev0 - May 31, 2026
- **Enhancement: PMT Control preset buttons**
  - Replaced the fixed "Zero" button with a configurable set of preset buttons driven by `pmt.gain_presets` in config.
  - Number of buttons is dynamic — determined by how many values are listed in `gain_presets`.
  - Default presets changed to `[0, 70]`; config template updated to `[0, 50, 70]` with a note that more values can be added.

## v1.15.0.dev0 - May 31, 2026
- **Feature: Remote Control plugin**
  - Added `RemoteControlPlugin` (ZeroMQ REQ/REP, default port 5558) accepting JSON commands: `focus`, `grab`, `stop`, `status`, `set_n_frames`, `set_file_storage`.
  - Added `RemoteControl` Python client class in the same module for driving the plugin from external scripts or IPython.
  - GUI updates (button states, status bar, elapsed timer, frames spinbox, file storage fields) are applied identically whether the command comes from the GUI or from a remote client.
- **Enhancement: ZMQ plugin rename**
  - Renamed `ZmqFrameStreamerPlugin` → `FrameStreamerPlugin` (module `zmq_frame_streamer` → `frame_streamer`).
  - Renamed `ZmqPositionStreamerPlugin` → `PositionStreamerPlugin` (module `zmq_position_streamer` → `position_streamer`).
  - Config keys updated accordingly (`zmq_frame_streamer` → `frame_streamer`, `zmq_position_streamer` → `position_streamer`).
- **Feature: Quadrature Encoder plugin**
  - Added `QuadraturePlugin` recording one int32 encoder count per frame using the non-blocking poll pattern (matches original Scanbox behaviour).
  - Saves `<basename>_quadrature.npy` alongside the `.sbx` file; calibration metadata written to the `.mat` sidecar.
- **Documentation**
  - Added user guide for all four plugins (`docs/user_guide/plugins/`), including configuration, usage examples, and performance impact sections.
  - Added quadrature encoder protocol reference (`docs/hardware_protocols/quadrature_encoder.md`) with Arduino firmware installation instructions.
  - Added advanced plugin performance reference (`docs/advanced/plugin_performance.md`) documenting acquisition thread overhead and guidelines for plugin authors.

## v1.14.0.dev0 - May 10, 2026
- **Enhancement: Virtual Knobby always available via menu**
  - The Virtual Knobby dialog and its menu action (Hardware > Virtual Knobby..., Ctrl+K) are now always instantiated, regardless of the `knobby.virtual` config setting.
  - `knobby.virtual: true` now only controls whether the dialog is shown automatically on startup (previously it also gated creation of the menu item entirely).

## v1.13.0.dev0 - May 10, 2026
- **Feature: ZMQ position streaming**
  - Added `on_position_updated` hook to `AcquisitionPlugin` base class and `PluginManager`, enabling plugins to subscribe to motor position updates independently of acquisition.
  - Added `ZmqPositionStreamerPlugin` that publishes objective position over a ZMQ PUB socket (default port 5556) as JSON: world XYZ, angle, rotated-frame XYZ, and absolute motor positions.
  - Position is streamed only when it actually changes (fixed spurious emissions from the abs-position poll when the motor is stationary).
  - Renamed `ZmqStreamerPlugin` → `ZmqFrameStreamerPlugin` (module `zmq_streamer` → `zmq_frame_streamer`) to clearly distinguish frame streaming from position streaming.

## v1.12.0.dev0 - May 9, 2026
- **Enhancement: Virtual Knobby dialog**
  - Floating on-screen dialog (`VirtualKnobbyDialog`) that emulates the physical Knobby rotary-encoder controller, usable in both emulation and hardware modes.
  - Provides +/− buttons for X, Y, Z axes (Position group) and A axis (Rotation group), with Coarse/Fine/Superfine velocity modes.
  - Normal and Rotated movement modes; Rotated mode projects Z/X moves onto world axes using the current A-axis angle.
  - Zero XYZ and Zero XYZA buttons reset the Knobby relative-position origin without moving motors.
  - Enabled via `knobby.virtual: true` in config; toggled with Ctrl+K (application-wide shortcut, works even when the dialog has focus).

## v1.11.0.dev0 - May 8, 2026
- **Enhancement: Command log as independent window**
  - The command log is now a standalone `Tool` window (`LogWindow`) instead of a dock widget embedded at the bottom of the main window.
  - Opening or closing the log no longer resizes the main window.
  - On first open (Ctrl+L), the log window is placed to the right of the main window at the same height; it can be freely repositioned thereafter.

## v1.10.0.dev0 - May 7, 2026
- **Enhancement: Crosshair overlay for image canvas**
  - Full-image crosshair (horizontal + vertical lines spanning the scene) toggled via right-click context menu or View > Toggle Crosshair (Ctrl+X).
  - Crosshair color matches the dark blue used by the slider fill (`#192d50`), configurable via `display.crosshair_color` in the config file.
  - Menu bar checkbox stays in sync when the crosshair is toggled via the context menu.
  - Crosshair is synced to the PMT1 canvas when switching to dual-panel mode.

## v1.9.1.dev0 - May 6, 2026
- **Fix: Snapshot context menu not working in 'PMT0 | PMT1' mode**
  - Right-clicking 'Save Snapshot' on either canvas in dual-panel mode now triggers the save dialog (the PMT1 canvas signal was never connected).
- **Fix: Snapshot saves only one channel in 'PMT0 | PMT1' mode**
  - In dual-panel mode, saving a snapshot now writes two PNG files: `snap000_pmt0.png` (green/PMT0) and `snap000_pmt1.png` (red/PMT1). The index uniqueness check verifies both files before suggesting a filename.
- **Fix: Markers not included in snapshots**
  - Snapshots now render via `QGraphicsScene.render()` instead of the raw display buffer, so placed markers (crosshair overlays) appear in the saved image for all display modes.

## v1.9.0.dev0 - May 3, 2026
- **Enhancement: Synchronized dual-canvas two-channel display ('PMT0 | PMT1')**
  - New channel display mode renders PMT0 and PMT1 in two equal side-by-side canvases instead of compositing them into a single image. Zoom, pan, marker placement, and marker-mode toggle are fully synchronized between the two panels.
  - Zoom uses AnchorUnderMouse on the active canvas; the peer receives the exact resulting transform so both panels always show the identical region.
  - Entering the mode copies the current zoom/pan state from the primary canvas so both panels start in sync.
  - The older single-canvas composite 'PMT0 : PMT1' mode has been removed; 'PMT0 | PMT1' replaces it with a superior synchronized experience.

## v1.8.5.dev0 - May 2, 2026
- **Enhancement: Configurable terminal output via `terminal.log_level`**
  - New `terminal` config section controls what the pyscanbox logger prints to the terminal, independent of the `--verbose` CLI flag.
  - `log_level: INFO` (default) shows acquisition start/stop, frame progress, file loads, and safety resets. `DEBUG` adds every hardware command. `WARNING` silences routine output.
  - `frame_progress_interval` controls how often frame-count progress lines are printed (default: 1000 frames).
  - PMT gains, Pockels, and continuous resonant are now explicitly reset on disconnect/shutdown, with a confirmation line printed at INFO level.
  - Loading an `.sbx` recording logs filename, frame count, channel count, resolution, and file size.
  - Pockels LUT upload (256 entries) is collapsed to two summary lines in the acquisition command log; manual uploads from the calibration dialog still show all entries.
  - Welcome message printed to terminal on startup.
- **Enhancement: Deadband controls added to Scanner panel**
  - Two spinboxes (left and right) in the "Deadbands" row of the Scanner group let users adjust the Pockels cell deadband margins directly from the GUI without editing the config file.
  - Values are always in visual (image) order. When `hsync_sign=1` the hardware call swaps left/right so the Pockels cell timing matches the reversed scan direction. The config and saved metadata store deadbands in visual order so downstream tools can apply them directly to the image data without needing to know `hsync_sign`.
  - A read-only indicator button next to "Continuous resonant" shows whether the horizontal sync is normal or flipped. Can be configured via `hsync_sign` in the config file.

## v1.8.4 - April 30, 2026
- **Fix: Vertical image flip in bidirectional + continuous resonant mode (issue #1)**
  - In continuous resonant mode the resonant mirror keeps oscillating between acquisitions. Thermal drift shifts the mirror frequency slightly, causing the PSoC5's fixed deadband period to gradually slip out of phase. After ~1–2 minutes the phase error causes the PSoC5 to fire line triggers on the backward sweep instead of the forward one, swapping odd and even lines in bidirectional mode and producing a vertical image flip.
  - `synchronize_scanner_phase()` now calls `set_deadband_period()` before every acquisition (previously guarded to run only once per controller lifetime), re-locking the PSoC5 to the mirror's current phase.
  - `configure_scan_params()` now sends `set_scan_mode(bidirectional)` before every acquisition to reset the PSoC5 frame-counter alignment to the forward sweep.
  - `AppController.open()` now calls `set_continuous_resonant(False)` at hardware startup, matching the original MATLAB `scanbox.m` line 300 behavior and ensuring a known state regardless of previous hardware sessions.
- **Fix: Vertical image flip in two-channel bidirectional mode (issue #1)**
  - When recording both PMT channels in bidirectional mode, the disk write rate (~51 MB/s at 31 fps) saturates the OS write-behind cache after ~1 minute (~3 GB written). Each `write_frame()` call then blocks for several milliseconds while the OS flushes dirty pages, preventing the Alazar buffer from being re-posted promptly. The Alazar's onboard FIFO accumulates records during the stall; when control returns, the number of accumulated records is not a multiple of `records_per_buffer` (256), permanently shifting the bidirectional frame boundary and causing a vertical image flip. The gradual onset (shift increasing by a few lines per frame over ~0.5–1 second) reflects the incremental nature of the cache saturation.
  - Disk writes are now handled by a dedicated background thread (`_write_loop`) fed through `_write_queue`. The acquisition loop copies each reshaped frame into the queue (non-blocking) and returns immediately; the Alazar buffer re-post is never delayed by disk I/O.
  - The write thread logs a warning if queue depth exceeds 8 frames (~250 ms of backlog), giving early notice of a disk bottleneck without dropping data.

## v1.8.3 - April 16, 2026
- **Enhancement: TTL input selector added to GUI**
  - Added a new "Save Channels" widget in the secondary controls bar (to the left of Objective Position) that groups PMT channel selection and TTL input toggles together.
  - Two independent toggle buttons (TTL0, TTL1) allow enabling or disabling each TTL input. Buttons are seeded from `config['external_events']['interrupt_mask']` at startup and override the config value at grab time.
  - The PMT channel combobox previously in the File Storage panel has been moved into the new widget, freeing vertical space in the left panel.
  - Removed the extra icon-placeholder whitespace from all combobox dropdowns.
- **Docs: Updated user guide to reflect new Save Channels widget**
  - Added Save Channels section to `visualization_and_tools.md` describing the PMT selector and TTL toggles.
  - Removed the now-moved Save Channels entry from the File Storage section of `hardware_controls.md`.

## v1.8.2 - April 15, 2026
- **Enhancement: Link Image Display channel selector to Save Channels**
  - When the user selects a channel in Image Display, the Save Channels selector in File Storage updates automatically to match. Only responds to explicit user selections (not programmatic resets).
  - Controlled by the new config key `io.link_display_save_channels` (default: `true`).
  - Pressing Focus no longer resets the Image Display channel selection; it only re-enables all channel options if they were restricted by a previously loaded file.
  - A warning dialog is shown before Grab if Save Channels differs from what Image Display is showing, allowing the user to confirm or cancel. A "Don't show this again" checkbox suppresses the dialog for the rest of the session.
- **Maintenance: Remove `file_prefix` config key**
  - Removed the unused `io.file_prefix` parameter from `config_template.yaml`. The fallback output path in `scan.py` now uses a hardcoded `scan_` prefix with a timestamp; in normal use the GUI always provides an explicit output path.

## v1.8.1 - April 13, 2026
- **Enhancement: GUI layout optimization for 1200px height displays**
  - Reduced Focus/Grab button minimum height from 40px to 28px and font size from 14px to 13px.
  - Reduced 2p/Epi light-path toggle button vertical padding from 8px to 4px for more compact vertical footprint.
  - Set `LightPathGroup` size policy to `Maximum` on vertical axis so it no longer stretches when there is available space.
- **Refactor: Snapshot feature moved from button to File menu with auto-increment**
  - Removed "Snapshot" button from `AcquisitionControlGroup` to reduce clutter in the left panel.
  - Added "Save Snapshot" action to File menu (keyboard shortcut: **Ctrl+S**) that opens a file save dialog.
  - Added "Save Snapshot" context menu item to the image canvas (right-click) for quick access.
  - Snapshot filename now auto-increments when a file already exists on disk, using format `<subject>_<date>_snap<NNN>.png` (e.g., `test000_20260413_snap000.png`). The proposed filename is shown in the dialog, but the user can override it.
  - Snapshot is saved at the original frame resolution using `ImageDisplayWidget.save_snapshot()` (renders from `_display_buffer`), not the scaled screen pixmap.
  - File save dialog defaults to the directory and naming scheme set in the File Storage widget, with auto-increment preventing overwrite surprises.
  - Removed stale `_on_snapshot_clicked()` handler that was wired to the deleted button.
- **Enhancement: Mouse wheel step control for gain adjustment**
  - Power (Pockels) slider now increments/decrements by 4% per mouse wheel step (via `setSingleStep(4)`).
  - PMT0 and PMT1 gain sliders now increment/decrement by 2% per mouse wheel step (via `setSingleStep(2)`), improved from 1% for faster adjustment.
- **Enhancement: Configurable PMT gain preset buttons**
  - Added `pmt.gain_presets` configuration parameter (array of two integers, default: `[50, 70]`) in `config_template.yaml` to set the values of the "quick-access" PMT gain preset buttons.
  - `PMTControlGroup` now reads `config['pmt']['gain_presets']` to label and wire the two preset buttons, allowing users to customize the buttons for their setup without code changes. Buttons previously hardcoded to 50% and 75%.
  - Updated `LeftControlPanel` to pass the config object to `PMTControlGroup` so it can access preset values.

## v1.8.0 - April 12, 2026
- **Maintenance: Tighten Python version requirements**
  - Updated `requires-python` from `>=3.8` to `>=3.11` to reflect actual tested versions (3.11 and 3.12). The codebase uses `X | Y` union type annotations which are a runtime error on Python < 3.10, and `list[T]`/`dict[K, V]` generic aliases which require Python 3.9+.
  - Updated `[tool.black]` `target-version` to `['py311', 'py312']`, removing untested 3.8–3.10 targets.
  - Updated `[tool.mypy]` `python_version` to `"3.12"` (primary tested version) so mypy type-checks against the correct stdlib.
  - Removed Python 3.8, 3.9, and 3.10 `Programming Language :: Python :: 3.x` PyPI classifiers.
  - Updated installation instructions in `docs/user_guide/installation.md`.
  - Set default deadbands to 40 in `config_template.yaml`.

## v1.7.3 - April 12, 2026
- **Enhancement: Configurable mock neuron size and shape in emulator**
  - **Uniform neuron size:** Synthetic neuron spots in `mock_alazar.py` now all share the same size instead of random per-neuron sizes. Controlled by the new `mock_neuron_size_px` parameter (diameter / twice the characteristic scale, consistent across both spot modes).
  - **Circle spot mode:** Added a second spot profile alongside the existing Gaussian: `'circle'` renders a uniform filled disk with a hard edge. Controlled by the new `mock_neuron_shape` parameter (`'gaussian'` or `'circle'`). A new `_compute_spot_mask()` helper is the single source of truth for the profile geometry.
  - **Module-level defaults:** `_MOCK_NEURON_SIZE_PX = 24` and `_MOCK_NEURON_SHAPE = 'gaussian'` can be changed as a quick override without touching the config file.
  - **Config-file support:** Both parameters are read from the `emulation` section of `config.yaml` via `configure_from_config()`. Added `mock_neuron_size_px` and `mock_neuron_shape` entries (with comments) to `config_template.yaml`.
- **Bug Fix & Enhancement: Multi-Channel Data Display and Histogram**
  - **Channel-aware display configuration:** When loading a `.sbx` file with only PMT0 or PMT1 recorded, the Image Display channel combobox now automatically disables unavailable options and auto-selects the only available channel. Implemented via new `configure_channels()` and `reset_channels()` methods in `ImageDisplayControlGroup`. When live acquisition starts (Focus/Grab), all channel options are restored.
  - **Fixed histogram colorbar repetition:** The `histogram_widget.py` had its own (incorrect) `_build_colormap_lut()` implementation that used value doubling, causing uint8 overflow and repeated patterns in the red colorbar. Synchronized with `widgets.py` to use the correct formula: channel ramps 0→255 linearly with white blend computed as `2v - 255`.
  - **Single source of truth for colormaps:** Moved `_build_colormap_lut()` and `_RED_BOOST` constant to `histogram_widget.py` as the authoritative definition; `widgets.py` now imports them instead of duplicating. Both `HistogramWidget` and `ImageDisplayWidget` now use identical colormap logic.
  - **Fixed PMT1-only histogram color:** Single-channel PMT1 recordings now correctly display a red histogram instead of green. The histogram's channel selector (`set_channel()`) now properly handles both two-channel recordings (`_counts1 is not None`) and single-channel PMT1 recordings (`_counts` with red styling).
  - **Overlay colorbar consistency:** The histogram colorbar for overlay mode (ch==2, both channels fused with semi-transparency) now uses plain green/red LUTs to match the canvas rendering (which composites pure R+G without the white-blend transition). Side-by-side mode (ch==3) continues to use the full green_white/red_white LUTs.

## v1.7.2 - April 11, 2026
- **Enhancement: Add `--version` flag and application icon**
  - **Added `--version` command-line flag:** Displays the current version (e.g., `pyscanbox --version` → `pyscanbox 1.7.2`) and exits. Invokes argparse with `action='version'`.
  - **Set application icon:** The app now displays `docs/assets/icon_gray.svg` in Alt-TAB switcher, taskbar, and window title bar. Path is resolved at runtime with a safety check; icon is optional (app runs without it if file is missing).
  - **Performance optimization:** Deferred heavy imports (`PyQt6`, `qdarktheme`, `pyscanbox.gui`) into `run()` so `--version` is fast (~40 ms instead of ~1 s). Non-GUI entry points no longer pay the import cost.
  - **Added clarity comments:** Top-level imports now document why PyQt modules are absent; `pylint: disable=import-outside-toplevel` suppresses linter warnings for deferred imports.

## v1.7.1 - April 11, 2026
- **Refactor & Enhancement: HistogramWidget extracted to its own module with new features**
  - **Extracted `HistogramWidget`** from `pyscanbox/gui/widgets.py` into a new dedicated module `pyscanbox/gui/histogram_widget.py`. `widgets.py` re-exports it via `from .histogram_widget import HistogramWidget` so all existing callers are unaffected.
  - **Added linear/log y-scale toggle:** Small "Linear"/"Log" button overlaid in the top-right corner of the histogram. Log scale uses `1 + log10(max(1, count))` so empty bins map to 0 and weak signals remain visible. Switching scale resets the y-zoom to show the full range.
  - **Histogram shown immediately on widget open:** `force_update_frame` now caches the frame in `_last_frame` before the `isVisible()` check, matching the behaviour of `update_frame`. Opening the histogram after loading a recording now populates it immediately from the cached frame.
  - **Removed `setMaximumHeight(120)` limit** from `HistogramWidget` so the user can drag the splitter handle to make it taller.
  - **Controls panel moved outside the vertical splitter** in `RightDisplayPanel`: the secondary controls strip now lives in a fixed `QVBoxLayout` below the splitter, so it cannot be accidentally resized. A `QFrame(HLine)` separator is placed between the splitter and the controls panel for visual clarity.

## v1.7.0 - April 11, 2026
- **Bug Fix: Suite2p / sbxreader compatibility — missing `magnification_list` in config**
  - `sbxreader` (used by Suite2p for .sbx import) expects `float(info.config.magnification_list[magidx])` to retrieve zoom levels; absence of this field caused `AttributeError: 'mat_struct' object has no attribute 'magnification_list'`.
  - **Added `magnification_list` field to `AcquisitionMetadata`:** New `magnification_list: List[float]` field populated during acquisition with zoom levels from controller (13 values: 1.0, 1.2, 1.4, ..., 8.0 via logspace(1, 8, 13)).
  - **Updated `sbx_writer._metadata_to_mat_dict()`:** Now includes `magnification_list` in the `config` sub-struct with dtype `np.float64` for numeric compatibility.
  - **Established single source of truth:** Added `MAG_VALUES` tuple to `ScanboxController` (13-element magnification array); refactored `MAG_LABELS` to auto-generate from `MAG_VALUES` using f-string formatting, eliminating manual sync risk.
  - **Updated `scan.py`:** `AcquisitionMetadata` instantiation now populates `magnification_list=list(controller.ScanboxController.MAG_VALUES)` at acquisition start.
  - **Migration tool for old files:** New `scripts/fix_mat.py` reconstructs old `.mat` files (created before this fix) to include missing `magnification_list` and other config fields. Features idempotent operation (skips already-fixed files), automatic backup to `.old.mat`, and `--dry-run` preview mode. Resolves Suite2p import failures on legacy recordings.

## v1.6.8 - April 10, 2026
- **Refactor: Format-Agnostic Metadata Layer (Single Source of Truth)**
  - **New module:** `pyscanbox/io/metadata.py` containing `AcquisitionMetadata`, a format-agnostic dataclass that defines all metadata fields captured during acquisition.  Attribute names follow Python conventions (snake_case); format-specific mapping to `.mat` field names happens in the writer, not in the acquisition code.
  - **Eliminates duplication:** Metadata field definitions were previously scattered between `scan.py` (`_create_metadata()` returning a dict with `.mat` field names) and implicit in `sbx_writer.py`. Now there is one authoritative definition in `AcquisitionMetadata`.
  - **Enables future formats:** Any format writer (HDF5, Zarr, etc.) can import `AcquisitionMetadata` and define its own field mapping without touching acquisition code.
  - **Updated `sbx_writer.py`:**
    - New `_metadata_to_mat_dict(meta: AcquisitionMetadata)` function maps `AcquisitionMetadata` fields to the MATLAB `info` struct layout (nested `config` sub-struct, 1-based `magnification`, camelCase field names, etc.).
    - `write_mat(metadata=None)` refactored: when `AcquisitionMetadata` is provided it uses the complete mapping; when `None` it falls back to minimal legacy behavior for standalone/low-level use.
    - `close(metadata=None)` forwards metadata to `write_mat()`.
  - **Updated `scan.py`:**
    - Replaced `_create_metadata()` (returned raw dict with `.mat` field names) with `_create_acquisition_metadata()` (returns `AcquisitionMetadata`).
    - `scan.py` no longer knows `.mat` field names — only logical attribute names.
    - `cleanup()` passes `AcquisitionMetadata` to `sbx_writer.close()`.
    - Added motor (Knobby) position reading at end-of-acquisition for metadata; positions are stored in `AcquisitionMetadata.knobby_x/y/z/a` and mapped to `config.knobby.pos` sub-struct in the `.mat` file.
  - **Code style:** Imports adjusted to follow pyscanbox convention (`from pyscanbox.io import metadata` instead of direct class import).

## v1.6.7 - April 10, 2026
- **Bug Fix: .mat file missing `info.config` sub-struct (Suite2p / sbxreader incompatibility)**
  - `sbxreader` (used by Suite2p) unconditionally accesses `info.config.magnification` and `info.config.lines` when reading a Scanbox `.mat` file; without these the import fails with `AttributeError: 'mat_struct' object has no attribute 'config'`.
  - Added the `config` nested struct to `_create_metadata()` in `scan.py`, mirroring the `scanbox_getconfig()` function in the original `core/scanbox.m` (line 6416).
  - `config.magnification` is the 1-based magnification index (MATLAB convention; pyscanbox stores it 0-based internally, so +1 is applied on write).
  - `config.lines` matches `lines_per_frame`; `config.frames`, `config.pmt0_gain`, and `config.pmt1_gain` are also populated.
  - `info.resfreq` was already written correctly; no change needed there.
  - Updated the `_create_metadata()` docstring to clarify that nested dicts (without `None` values) are supported by `scipy.io.savemat` and written as MATLAB sub-structs.

## v1.6.6 - April 10, 2026
- **API Cleanup: Renamed Core I/O Classes**
  - Renamed `ScanboxOriginalWriter` → `SbxWriter` and `ScanboxOriginalReader` → `SbxReader` to simplify the API now that the obsolete `SbxWriterObsolete` and `SbxReaderObsolete` classes have been removed.
  - Removed deprecated `load_sbx_obsolete()` convenience function.
  - Updated all docstrings, type annotations, and cross-references throughout the codebase (`pyscanbox/acquisition/scan.py`, `pyscanbox/gui/main_window.py`, `pyscanbox/io/tiff_exporter.py`, `pyscanbox/scripts/sbx_to_tiff.py`, and tests).
  - All 20 existing unit tests continue to pass without modification.

## v1.6.5 - April 9, 2026
- **Mock signal parameters configurable from config file**
  - Mock frame generation parameters (`mock_n_neurons`, `mock_noise_sigma_16bit`, `mock_signal_min_brightness_16bit`, `mock_signal_max_brightness_16bit`) are now defined in the `emulation` section of `config.yaml` and expressed in intuitive 16-bit non-inverted units (0 = dark, 65535 = bright).
  - A `_to_14bit()` helper converts user-facing values to the 14-bit inverted ADC scale used internally.
  - Added `Board.configure_from_config(config)` to `mock_alazar.py` as the single entry-point for applying emulation config; `alazar.py` calls it with one stable line and no longer enumerates individual mock keys.
  - Added `_N_MOCK_NEURONS` module-level constant; both `_prepare_test_frames()` and `_prepare_test_frames_raw()` now use per-instance attributes so parameters take effect without modifying code.
- **Bug Fix: Quadrature plugin creating spurious output file**
  - `QuadraturePlugin.save_data()` now returns early when `_output_path` is not set, preventing an empty `.npy` file from being written when a session is stopped before any frames are acquired.
- **Documentation: Hardware Protocols**
  - Expanded `docs/hardware_protocols/alazar_digitizer.md` with detailed buffer geometry, bidirectional mode description, and LSB output configuration.
  - Revised `docs/hardware_protocols/knobby.md` for clarity and accuracy.

## v1.6.4 - April 9, 2026
- **Continuous Resonant Mode Phase Synchronization**
  - Implemented missing `CMD_DEADBAND_PERIOD` (ID 10) command to synchronize PSoC5 hardware to resonant scanner oscillation phase.
  - This command is critical for continuous resonant mode, where the scanner is already oscillating when acquisition starts; without it, the first line trigger fires at an unpredictable phase, causing vertical frame shifts.
  - Deadband period synchronization now occurs once during hardware initialization (matching original MATLAB behavior) via guard flag `_deadband_period_set` to prevent re-synchronization during each acquisition.
  - Formula: `period = round(24e6 / resonant_freq / 2)`; for default 7930 Hz, period ≈ 1513 (auto-clamped to valid hardware range 1245 < p < 1500).
- **Fixed Acquisition Startup Sequence**
  - Corrected the order of operations to match original MATLAB (`core/scanbox.m` lines 2517–2586):
    - Previously: `start_scan()` → `start_acquisition()`
    - Now: `start_acquisition()` (arm digitizer) → 50ms delay → set Pockels blanking → `start_scan()` (begin triggering)
  - This ensures the digitizer is armed and ready before the scanner generates line triggers.
- **Pockels Deadband Organization**
  - Split deadband synchronization into two methods:
    - `synchronize_scanner_phase()`: Sets phase (deadband_period) once during initialization.
    - `synchronize_pockels_blanking()`: Sets blanking region widths (left/right) per acquisition, matching original MATLAB behavior.
  - Added `set_deadband_period(period)` to `ScanboxController` with automatic clamping to valid hardware range.
- **Bug Fix: Vertical Frame Shift in Continuous Resonant Mode**
  - Fixed critical bug where images acquired in continuous resonant mode showed a vertical cyclic shift (top lines appeared at ~line 100, bottom wrapped to top).
  - Root cause: Deadband period was being re-synchronized before every acquisition, disrupting phase relationship in continuous mode; and startup sequence was incorrect.
  - With this fix, images are now aligned identically whether continuous resonant mode is enabled or disabled.

## v1.6.3 - April 4, 2026
- **User Guide and Documentation Enhancements**
  - Created comprehensive User Guide with installation instructions, typical workflow, GUI overview, and feature-specific guides.
  - Added volumetric imaging limitations documentation explaining the 255-entry hardware constraint.
  - Updated README.md with complete feature list including bidirectional scanning, volumetric imaging, TTL timestamping, and real-time plugin streaming.
  - Fixed license information in README (MIT → GPL-3.0-or-later).
  - Added version display to application status bar and About dialog.
- **Miscellaneous Improvements**
  - Completed incomplete sentence in CONTRIBUTING.md.
  - Fixed markdown formatting in branching_strategy.md.

## v1.6.2 - April 4, 2026
- **Configuration synchronization on application startup**
  - GUI spinboxes (`total_frames`, `magnification`, `scan_mode`) now initialize from config values at startup, ensuring GUI and acquisition parameters are synchronized (fixing frame rate calculation on app start).
  - Added `_sync_total_frames_spinbox()`, `_sync_magnification_combobox()`, and `_sync_scan_mode_combobox()` methods to `MainWindow` following the existing pattern of `_sync_lines_per_frame_spinbox()`.
- **Controller firmware version verification**
  - Added version check that compares `config['controller']['version']` with the actual hardware version queried at startup.
  - Logs warning if versions mismatch, indicating potential feature incompatibility.
  - Emulation mode skips mismatch warning and reports emulation status instead.
  - Emulator version identifier changed to 0.0 for clarity (0.0 is never a valid hardware version).
- **Configuration cleanup**
  - Removed unused `pockels:base_power` and `pockels:active_power` parameters from `config_template.yaml` (MATLAB had no equivalent; laser power is controlled only via GUI slider).
  - Removed `pockels:lut_enabled` parameter (redundant; use presence/absence of `pockels:lut` instead).

## v1.6.1 - April 3, 2026
- **Continuous Resonant Mode Fixes**
  - Updated `ScanboxController` to use `CMD_CONTINUOUS_RESONANT = 0x34` (52) natively, fixing the erroneous override of `CMD_BIDIRECTIONAL = 0x22` (34).
  - Removed deprecated software-side timer "kick" hacks in `AppController` that were artificially starting and stopping scanning to initialize the resonant mirror.
  - Decoupled "Continuous Resonant" state from "Bidirectional" scan mode in the GUI (`main_window.py`); the two options can now be toggled completely autonomously.
  - Formatted the Command Summary hardware protocol table uniformly with `DEC / HEX` IDs.

## v1.6.0 - April 3, 2026
- **Histogram Visualization Enhancements**
  - Added Y-axis zooming to the Histogram widget via mouse wheel.
  - Added a right-click context menu to the Histogram for "Reset Y Zoom", making it easier to return to the full dynamic range view.
- **Continuous Resonant Scanning Mode**
  - Implemented "Continuous Resonant" mode to maintain thermal stability in the resonant scanner during inter-acquisition periods.
  - New "Continuous resonant" checkbox in the Scanner control panel.
  - Added `set_continuous_resonant(enabled)` to `ScanboxController` (CMD ID 34, sub-mode 1).
  - Synchronized "Continuous Resonant" state with "Scan Mode": enabling continuous mode automatically switches to Bidirectional (as required by the PSoC5), and switching to Unidirectional automatically disables the continuous flag.
- **Documentation Updates**
  - Added `docs/advanced/bidirectional_drift.md` covering the thermal causes and solutions for scan alignment drift.

## v1.5.0 - March 30, 2026
- **Real-time plugin data access**
  - Extended the `AcquisitionPlugin` interface with the `on_frame_data` hook, providing direct access to raw imaging buffers.
  - Fixed a bug in `Scanner._acquisition_loop` where plugin data hooks were not being dispatched to the `PluginManager`.
  - Implemented `ZmqFrameStreamerPlugin` for high-performance, real-time image streaming via ZeroMQ.
  - Clarified that `on_frame_data` delivers raw "inverted wire-format" values (high = dark) to minimize acquisition overhead; inversion to signal convention is deferred to consumers.
  - Added `examples/check_zmq_subscriber.py` to demonstrate subscribing to and inverting the ZMQ stream.
 
 ## v1.4.0 - March 25, 2026
- **GUI visualization and layout improvements**
  - Added new "PMT0 | PMT1" side-by-side mode to the Image Display channel selector
  - Side-by-side mode automatically inherits the application's active theme background color for the image gap
  - Integrated Histogram widget support for side-by-side mode (displays both PMT lines simultaneously)
  - Refactored persistent image markers to use logical coordinates: markers robustly mirror and map correctly when toggling between single-channel and side-by-side views
  - The Command Log dock widget is now hidden by default on startup for a cleaner interface (still quickly accessible via `Ctrl+L`)
- **Bug fixes and mock testing**
  - Updated the mock digitizer unit test suite (`tests/test_mock_alazar.py`) to properly call the new `atsbindings` snake_case API (33 tests fixed and passing)

## v1.3.2 - March 25, 2026
- **Configuration and metadata improvements**
  - Renamed `ScanboxConfig` to `AppConfig` across the entire codebase for clarity
  - Standardized configuration: moved the template to `config_template.yaml` at the project root and updated installation documentation
  - Audited and cleaned up `config_template.yaml`: removed unused parameters (`pmt:channels`, `io:memory_mapped`, `laser:com_port`, etc.)
  - Added logic to save `objective.type` and `laser.type` to `.mat` metadata files
  - Implemented `io.auto_increment` setting: file numbers now only increment post-acquisition if this toggle is enabled in the config
  - Added overwrite protection: the GUI now prompts for confirmation before overwriting existing `.sbx`, `.mat`, or `.png` (snapshot) files

## v1.3.1 - March 22, 2026
- **GUI enhancements and layout adjustments**
  - Moved "Light Path" to the top of the left control panel, and "PMT Control" below the "Laser" group
  - Added 50% and 75% quick-set buttons for both PMT gains, right-justified for better layout
  - Added a "Reset" button to the Image Display gain control
  - Set the Optotune depth label to display "Not calibrated" instead of remaining blank
  - Modified the initial Laser wavelength spinbox to show "Undefined" and require user input
  - Adjusted RightDisplayPanel splitter width so the "Objective Position" panel initializes correctly
  - Renamed `CameraPathGroup` to `LightPathGroup` throughout the application for clarity
- **atsbindings bug fixes**
  - Updated `wait_async_buffer_complete` exception handling in `mock_alazar.py` to match `atsbindings` behavior
  - Fixed references checking for `Buffer` instead of `DMABuffer`

## v1.3.0 - March 21, 2026
- **Alazar bindings update**
  - Replaced proprietary `atsapi.py` with open-source `atsbindings` library for AlazarTech ATS9440 communication
  - Updated codebase, documentation, and emulation to use `atsbindings` and `atsbindings.Buffer`


## v1.2.0 - March 20, 2026 (Current)
- **Scanner gain override — `gain_override`, `gain_galvo`, `gain_resonant`, `dv_galvo`**
  - `ScanboxController`: new constants `CMD_GALVO_DV = 0x66`, `CMD_MAG_X_GAIN_BASE = 0xB0`, `CMD_MAG_Y_GAIN_BASE = 0xC0`; `DV_GALVO_MAX = 64`, `GAIN_RESONANT_MULT_DEFAULT = 1.42`, `GAIN_GALVO_DEFAULT` (13-element logspaced tuple)
  - New methods: `_encode_gain(x)` (static; encodes float as `(xh, xl)` with 1-digit fractional precision), `set_galvo_dv(dv)`, `set_mag_x_gain(index, value)`, `set_mag_y_gain(index, value)`, `update_scanner_gains(gain_galvo, gain_resonant, dv_galvo)` (sends 27 packets: 1 dv + 13 X gains + 13 Y gains)
  - `CMD_GALVO_DV: 'set_galvo_dv'` added to `CMD_NAMES`; `format_command()` updated to decode dv and indexed X/Y gain packets
  - `AppController.update_scanner_gains(gain_galvo, gain_resonant_mult, dv_galvo)`: new public method; computes `gain_resonant = mult × gain_galvo` and delegates to `ScanboxController.update_scanner_gains()`
  - `AppController.open()`: gain-override startup block runs when `scanner.gain_override: true` in config, mirroring `core/scanbox.m` lines 253–262
  - `examples/config_examples/default_config.yaml`: new `scanner` keys `gain_override`, `dv_galvo`, `gain_galvo` (13-element list), `gain_resonant_mult`
  - New `pyscanbox/gui/scanner_gains_dialog.py`: non-modal `ScannerGainsDialog`; shows `dv_galvo` spinbox, `gain_resonant_mult` spinbox, and a 13-row table (Zoom, Galvo Y, Resonant X); "Recompute X Gains" reapplies the multiplier; "Reset to Defaults" restores factory log-spaced values; "Send to Hardware" writes the table directly via `ScanboxController.update_scanner_gains()`; `gains_sent` signal emitted on success
  - `MainWindow`: `scanner_gains_dialog` import; "Calibrate &Scanner Gains…" entry added to Calibration menu; `_on_calibrate_scanner_gains()` / `_on_scanner_gains_sent()` handlers; dialog closed in `closeEvent`
  - 14 new tests in `tests/test_controller.py::TestScannerGains`: `_encode_gain` (4 cases), `set_galvo_dv` (max, zero, exceeds-max ValueError), `set_mag_x/y_gain` (index 0, index 12/3), `update_scanner_gains` (packet count = 27, first packet = dv, wrong-length ValueError)
- **Bug fix: Lines/frame spinbox not connected**
  - `MainWindow._connect_hardware()`: added missing `lines_per_frame_spinbox.valueChanged` → `_on_lines_per_frame_changed` → `AppController.set_lines_per_frame()` signal connection; spinbox was live in the GUI but silently had no effect on the acquisition
  - Added `_sync_lines_per_frame_spinbox()` to initialise the spinbox from `config['acquisition']['lines_per_frame']` at startup so GUI and acquisition agree from the first frame

## v1.1.0 - March 19, 2026
- **Plugin system for auxiliary device integration**
  - New `pyscanbox/acquisition/plugin.py`: `AcquisitionPlugin` abstract base class and `PluginManager` dispatcher in a single module
  - `AcquisitionPlugin` defines four lifecycle hooks: `on_acquisition_start`, `on_frame`, `on_ttl_event`, `on_acquisition_stop`; all have no-op defaults so a plugin only overrides what it needs
  - `sync_mode` is a `@property` on the base class that auto-infers active synchronisation strategies by inspecting which hooks the subclass overrides (`'per_frame'` if `on_frame` is overridden, `'ttl'` if `on_ttl_event` is overridden); plugin authors never set it explicitly
  - `PluginManager` dispatches all lifecycle events to registered plugins in registration order; each call is wrapped in `try/except` so a misbehaving plugin cannot abort imaging
  - Three synchronisation strategies supported: Strategy 1 (TTL edge timestamping, ~125 µs), Strategy 2 (per-frame polling, ~33 ms), Strategy 3 (PC-clock alignment, ~1–5 ms)
  - New `pyscanbox/plugins/` package with three template plugins covering each strategy: `template_ttl_device.py`, `template_per_frame_device.py`, `template_async_device.py`
- **Quadrature encoder plugin**
  - New `pyscanbox/plugins/quadrature.py`: `QuadratureEncoder` hardware driver and `QuadraturePlugin` acquisition integration
  - `QuadratureEncoder` communicates with an Arduino-based encoder reader over a dedicated serial port (115200 baud for DUE, 1 Mbaud for Mega); binary protocol only (`0x00` request count, `0x01` zero counter, `0x02`/`0x03` lamp off/on)
  - Non-blocking poll pattern: `poll()` sends the request byte before the Alazar buffer wait; `read_count()` reads the 4-byte int32 response after the buffer completes, overlapping serial latency with Alazar wait
  - `QuadraturePlugin` stores one int32 count per frame; saves a companion `.npy` file after acquisition; embeds calibration factor (cm/count) in `.mat` sidecar via `get_metadata()`
  - Default calibration: `2π × 10 cm / 1440 ppr ≈ 0.04363 cm/count` (Scanbox default rig); Jaralab config: `2π × 7 cm / 2048 ppr ≈ 0.02150 cm/count`
  - `mock_serial.Serial` extended with quadrature emulation: 1-byte command dispatch, `quad_count` state tracking, correct 4-byte little-endian int32 response for `0x00` requests
- **Specification updated**
  - `devel/specifications/plugin_system.md` updated to reflect auto-inferred `sync_mode`, merged module structure, and corrected `QuadraturePlugin` constructor signature

## v1.0.0 - March 18, 2026
- **First production-ready release — core milestones complete and validated on real hardware**
  - All Phase 1 (backend) and Phase 2 (GUI) milestones complete; Phase 3 HIL testing substantially validated; selected Phase 4 integration testing verified
- **Application entry point**
  - New `pyscanbox/app.py`: `run(cfg, config_path, frame_data_callback=None)` creates the Qt application and enters the event loop; `main()` parses `--config`, `--emulation` (opt-in; real hardware is the default), and `--verbose` flags
  - New `pyscanbox/__main__.py`: enables `python -m pyscanbox`
  - `[project.scripts]` entry added to `pyproject.toml` registers the `pyscanbox` console command; `pyscanbox` runs on real hardware, `pyscanbox --emulation` for development
  - `examples/gui_example.py` refactored as a developer-only launcher: own `main()` with `--no-emulation` (disables emulation), `--print-frames N` (prints per-frame statistics every N frames), `--verbose`, `--config`; emulation is ON by default, making it safe to run without hardware
- **Hardware startup messages in Image Display placeholder**
  - `AppController.startup_status = QtCore.pyqtSignal(str)`: new signal emitted before and after each device `open()` call; pre-open emits `"Connecting to X (portN)..."`, post-open emits `"Connected!"` or `"Not available."`; messages for the same device are collapsed onto one line: `"Connecting to ScanboxController (COM6)... Connected!"`
  - `ImageDisplayWidget.set_startup_message(text)` / `_ImageCanvas.set_startup_message(text)`: replaces and re-centres placeholder text in real time during startup; `processEvents()` ensures GUI updates are visible before blocking `open()` calls complete

## v0.10.0 - March 18, 2026
- **Bidirectional calibration improvements** (Milestone 1.7.2 complete)
  - `BidirCalibration.save(hsync_sign=None)`: adds `"hsync_sign"` field to `bidir_cal.json`; `_load_from_disk()` reads it back; new `check_hsync_sign(current_hsync_sign)` returns `False` and logs `WARNING` when the stored sign differs from the active config (stored shifts may have the wrong sign and re-calibration is recommended)
  - `AppController.save_manual_bidir_calibration()`: new public method; reads the live `config['acquisition']['bishift']` list (as set by the per-magnification spinbox), calls `BidirCalibration.set_shift()` for each magnification, saves to `bidir_cal.json` with the current `hsync_sign`, logs the saved path, and returns the path for confirmation dialogs
  - `BidirCalibrationDialog`: "Start Calibration" renamed → "Auto Calibrate" (flagged as experimental in the instructions panel); new "Save Manual Calibration" button (primary workflow) triggers `save_manual_bidir_calibration()` and shows a `QMessageBox` with the saved path; instructions panel rewritten to lead with the manual per-magnification workflow (adjust spinbox → Save Manual Calibration); buttons disable each other during active runs

## v0.9.0 - March 17, 2026
- **Bidirectional calibration dialog**
  - New `pyscanbox/gui/bidir_cal_dialog.py`: non-modal `BidirCalibrationDialog` replaces the bare status-bar-only feedback; features a numbered instruction panel (switch to bidir mode → set magnification → start Focus → image a suitable sample → click Start), a live `QProgressBar` showing `N / M frames`, and a result panel displaying the calibrated magnification label and measured bishift in pixels after convergence
  - Start button validates preconditions (hardware connected, bidirectional mode active, Focus running) with informative dialogs before launching; becomes a Cancel button while running; closing the window also cancels an in-progress run
  - `MainWindow._on_calibrate_bidir()` now opens and raises the dialog (singleton pattern matching `PockelsCalibrationDialog`) instead of calling `start_bidir_calibration()` directly
  - `_on_bidir_calibration_progress()` and `_on_bidir_calibration_done()` forward updates to the dialog in addition to the status bar
- **Tip-fixed angle rotation (Milestone 2.8)**
  - `coordinate_transform.tip_compensation_delta(angle_old_deg, angle_new_deg, obj_length_um)`: new function in `pyscanbox/utils/coordinate_transform.py`; computes the X and Z stage displacements that cancel the tip displacement caused by a change in objective angle; objective length sourced from `config['objective']['length']`
  - `AppController.set_keep_tip_fixed(enabled)`: enables/disables tip-fixed mode; when enabled, each angle-knob delta also drives X (motor 2) and Z (motor 0) by the compensating step counts via `tip_compensation_delta()` + `units_to_steps()`; has no effect when `config['objective']['length']` is zero or absent
  - `PositionDisplayGroup.keep_tip_fixed_checkbox` ("Keep tip fixed"): new `QCheckBox` in the Objective Position widget, wired to `AppController.set_keep_tip_fixed()` via `MainWindow`
  - 11 unit tests in `tests/test_coordinate_transform.py` covering `world_to_rotated`, `rotated_to_world`, and all cases of `tip_compensation_delta` (zero delta, zero length, sign conventions, forward/backward symmetry, and the key property that applying the compensation exactly cancels the tip displacement)
- **Focus stacking / volumetric scanning GUI (Milestone 2.4)**
  - `ScanboxController`: four new ETL waveform commands — `CMD_OPTOWAVE_ENTRY` (21), `CMD_OPTOPERIOD` (22), `CMD_OPTOTUNE_ACTIVE` (23), `CMD_OPTOWAVE_RESET` (24) — mirroring MATLAB `sb_optowave.m`, `sb_optoperiod.m`, `sb_optotune_active.m`, `sb_optowave_init.m`
  - `ScanboxController.upload_etl_waveform(values)`: resets table, uploads 1–255 ETL entries, sets period; `set_etl_waveform_active(active)`: enables/disables autonomous PSoC5 waveform cycling
  - `AppController.upload_focus_stack(top, bottom, n_planes, frames_per_plane)`: generates equally-spaced step waveform and uploads to PSoC5
  - `AppController.enable_focus_stack(active)`: enables/disables waveform cycling; disabling restores direct ETL control
  - `OptotuneGroup` widget extended with "Focus Stacking" section: Set Top / Set Bottom capture buttons, Planes spinbox, Frames/plane spinbox, derived step-size label (µm when ETL calibration is loaded), table-size info label, Enable checkbox; ETL slider disabled while focus stack is active

## v0.8.0 - March 17, 2026
- **Pockels cell calibration module (Milestone 2.7)**
  - New `pyscanbox/calibration/pockels.py`: fits `P = A·sin(V·k)²` curve to power-meter measurements, generates 256-entry linearisation LUT via `scipy.optimize.curve_fit + arcsin inversion`; validated against MATLAB `pockels_920nm.m` (A=1537.4 mW, k=1.098 rad/V)
  - New `pyscanbox/gui/pockels_cal_dialog.py`: non-modal `PockelsCalibrationDialog` with measurement table, Fit button, dual-panel matplotlib preview (graceful degradation without matplotlib), Upload / Save / Load actions
  - `AppController.upload_pockels_lut(lut)`: sends 256-entry LUT to hardware and persists to config
  - Saves/loads calibration to `pockels_cal.json` alongside the active YAML config (same pattern as `etl_cal.json` and `bidir_cal.json`)
  - 20 unit tests in `tests/test_pockels_calibration.py`
  - `matplotlib>=3.5.0` added to `requirements.txt`
- **Calibration menu reorganisation**
  - "Calibrate Bidir Scan..." moved from Hardware menu to the new **Calibration** menu alongside "Calibrate Pockels Cell..."
- **Per-device Hardware connect/disconnect (Milestone 2.7)**
  - `AppController`: new `open_controller()`, `close_controller()`, `open_knobby()`, `close_knobby()`, `open_motor()`, `close_motor()` methods
  - Hardware menu now exposes six per-device connect/disconnect entries (Controller, Knobby, Motor) in addition to the existing "Connect All" / "Disconnect All"

## v0.7.0 - March 16, 2026
- **Bidirectional calibration system (Milestone 1.7.2)**
- Added `pyscanbox/calibration/` package — new home for all calibration modules, replacing `pyscanbox/hardware/bidir_calibration.py` and `pyscanbox/hardware/etl_calibration.py`; `app_controller.py` imports updated to `from pyscanbox.calibration import bidir/etl`.
- Added `pyscanbox/calibration/bidir.py` — `measure_bishift(frame, max_shift=64)` computes the bidirectional line-shift via zero-padded FFT cross-correlation of even/odd row profiles (`xcorr = IFFT(conj(FFT(even)) * FFT(odd))`; positive peak = backward lines shifted right). `BidirCalibration` class accumulates frames via exponential rolling average (tau=5, ~25 frames to converge), stores per-magnification shifts (13 total), saves/loads `bidir_cal.json` alongside the active config YAML.
- `AppController` now accepts `config_path` and exposes `start_bidir_calibration()` / `stop_bidir_calibration()`; signals `bidir_calibration_progress(done, needed)` and `bidir_calibration_done(mag_index, shift)`. `open()` loads `bidir_cal.json` and populates `config['acquisition']['bishift']` on startup.
- `MainWindow` Calibrate menu triggers calibration for the current magnification; three new slots handle progress display and completion.
- **Fixed bidirectional emulation buffer size mismatch**
- Root cause: `AlazarDigitizer.allocate_buffers()` was sizing numpy DMA buffers as `samples_per_buffer × channels` — a unidirectional geometry (`512 × 5000 × 2 = 5,120,000` elements). In bidirectional raw-mode emulation, `start_acquisition()` correctly posted 4,608,000-byte buffers (`256 × 9000 × 2`) to the mock, but the pre-allocated arrays were 5,120,000 elements, causing `ValueError: could not broadcast input array from shape (4608000,) into shape (5120000,)` on the first frame.
- `allocate_buffers()` now sizes the fallback numpy buffers as `_bytes_per_buffer // 2`, which already accounts for the correct geometry in all modes (unidirectional, bidirectional, emulation).
- `alazar.py open()` now passes `samples_per_line_bidir` from config to `mock_alazar.set_raw_mode()`.
- `mock_alazar.set_raw_mode()` accepts a new `samples_per_line_bidir` parameter (default 9000); stores it and pre-computes `_pixel_lut_bi` via `compute_pixel_lut_bi()`. When `bidirectional=True`, sets `buffer_size_samples = (lines // 2) × samples_per_line_bidir × 2`.
- `mock_alazar.set_scan_mode()` now recomputes `buffer_size_samples` when toggling bidir with `raw_mode=True`, and clears cached test frames.
- `mock_alazar._prepare_test_frames_raw()` added a bidirectional branch generating `(lines // 2) × samples_per_line_bidir × 2`-sized buffers using `_pixel_lut_bi` for correct forward+backward pixel placement; the existing unidirectional branch is unchanged.
- **Pockels cell LUT and range wired from config to hardware at startup**
- Added `set_pockels_lut(lut)` to `ScanboxController` — uploads a 256-entry linearisation LUT to the PSoC5 via 256 × `[0x43, idx, val]` packets, matching `sb/sb_pockels_lut.m` and the startup sequence in `core/scanbox.m` lines 269–273.
- Added `set_pockels_lut_identity()` — resets the PSoC5 LUT to the identity map via `[0x44, 0, 0]`, matching `sb/sb_pockels_lut_identity.m`.
- Added `set_pockels_range(vdac, pga)` — sets the Pockels DAC/PGA range via `[13, vdac, pga]`, matching `sb/sb_pockels_range.m`.
- Added `Scanner.initialize_pockels_lut()` — called in `initialize_hardware()` right after controller open; reads `pockels.lut`, `pockels.lut_enabled`, and `pockels.range` from config and uploads them in MATLAB startup order; falls back to identity LUT if none provided.
- Added 256-entry linearisation LUT (from `scanbox_config.jaralab.m`) to `pockels.lut` in `default_config.yaml`; removed `⚠️ not yet used` from the `pockels:` section.
- **Horizontal scan direction (hsync_sign) wired from config to hardware at startup**
- Added `set_hsync_sign(flip)` to `ScanboxController` — sends `[0x80, flip, 0]`, matching `sb/sb_hsync_sign.m`; `flip=0` = normal, `flip=1` = flip horizontal axis.
- `Scanner.configure_scan_params()` now reads `scanner.hsync_sign` from config and calls `set_hsync_sign()`, matching `core/scanbox.m` line 294.
- Removed `⚠️ not yet used` from `scanner.hsync_sign` in `default_config.yaml`.
- Toggling `hsync_sign` between 0 and 1 is the recommended first diagnostic step for left/right brightness asymmetry (see `devel/guides/pockels_calibration.md`).
- **New diagnostics guide: Pockels calibration and scan-direction asymmetry**
- Added `devel/guides/pockels_calibration.md` documenting: why Pockels phase/timing causes left/right image asymmetry; the `hsync_sign` flip test; LUT linearisation calibration procedure; DAC value limits; and a reference table of all relevant MATLAB files (`sb/sb_pockels_lut.m`, `sb/sb_pockels_range.m`, `sb/sb_hsync_sign.m`, `core/pockels_920nm.m`, etc.).
- **New command constants and mock support**
- Added `CMD_POCKELS_RANGE = 13`, `CMD_POCKELS_LUT_ENTRY = 0x43`, `CMD_POCKELS_LUT_IDENTITY = 0x44`, `CMD_HSYNC_SIGN = 0x80` to `ScanboxController`; all added to `CMD_NAMES` and `format_command()`.
- `mock_serial.Serial` now tracks `hsync_sign`, `pockels_range`, and `pockels_lut` state and handles all four new command IDs.

## v0.6.3 - March 15, 2026
- **Fixed non-uniform bidirectional alignment (sample-space bishift)**
- Root cause: pyscanbox was applying `np.roll` (uniform pixel-space shift) to correct backward-scan line timing, but MATLAB applies the bishift in raw-sample space (`preIdx += bishift*2`) *before* the arccosine LUT remapping. Because the resonant mirror slows near its turning points, a fixed sample shift produces a spatially non-uniform correction — left side aligned but right side drifted. Matching MATLAB's sample-space approach produces correct and uniform alignment across the full line width.
- `reshape_pmt_data_bi()` now accepts a `bishift: int` parameter; each backward-pixel sample index is offset by `bishift` (clamped to `[0, s_max]`) before LUT lookup, matching `alazarReshapeCData2bi.c` / `preIdx += bishift*2`.
- `Scanner._acquisition_loop` passes `bishift_val` directly to `reshape_pmt_data_bi()`; the post-reshape `np.roll` call on the hardware path is removed.
- All 8 `reshape_pmt_data_bi(...)` call sites in `tests/test_reshape.py` updated with the new `bishift=0` parameter; 43 tests pass.
- **Fixed white/black alternating band on left side of bidirectional images (skip-column fill)**
- Root cause: the backward sweep covers only the right ~706 of 796 columns; the remaining ~90 left "skip" columns were left as zero (the ADC idle fill value). After the `65535−x` wire-format inversion used by the display pipeline, zeros appear as maximum brightness (white), and this alternated with the zero-filled forward lines (dark), producing a strong alternating band on the left edge.
- Fix: after each backward-scan loop in `reshape_pmt_data_bi()`, the skip columns of the odd (backward) output line are filled by copying the corresponding pixels from the preceding forward (even) output line. The skip region therefore shows the same content as the forward pass rather than ADC idle noise.
- **Fixed .mat file integer type error (MATLAB int32 × int64 type mismatch)**
- Root cause: `_create_metadata()` in `scan.py` was writing `info.sz` as `uint16` (bare Python int via `np.array(..., dtype=np.uint16)`). When MATLAB loaded the file and computed `sz(1) * sz(2)`, the product of a `uint16` and an `int64` raised a type-mismatch error that prevented data loading.
- Fix: all integer scalar fields in `_create_metadata()` are now `np.int64`; `sz` is `np.array([[lines, pixels]], dtype=np.int64)` — matching the `write_mat()` layout that was already correct. Ensured `extra_info.update()` cannot overwrite the corrected `sz` with the wrong type.
- **Wired Pockels deadband from config to hardware at startup**
- `AppController.open()` now reads `config['scanner']['deadband']` and calls `controller.set_pockels_deadband(left, right)` after the scan-mode initialization, matching MATLAB's startup sequence in `scanbox.m`. The call is skipped gracefully if the `deadband` key is absent.
- Removed `scanner.unidirectional` from `default_config.yaml` — this field was never read by any Python code; `acquisition.unidirectional` is the single source of truth for scan mode.

## v0.6.2 - March 15, 2026
- **Fixed bidirectional scan mode hardware buffer parameters (Milestone 1.7 HIL bug fix)**
- Root cause: pyscanbox was using unidirectional Alazar parameters (`records_per_buffer=512`, `samples_per_record=5000`) for bidirectional mode; MATLAB `scanbox.m` uses `records_per_buffer=lines/2=256` and `postTriggerSamples=9000` because the PSoC5 fires ONE trigger per full resonant cycle (capturing both forward + backward sweeps in a single 9000-sample record). This caused all three reported HIL bugs.
- `AlazarDigitizer.start_acquisition()` now uses `samples_per_record=9000` and `records_per_buffer=lines//2=256` in bidirectional raw mode; unidirectional and emulation paths unchanged.
- `AlazarDigitizer._bytes_per_buffer` updated to use `samples_per_line_bidir × (lines//2) × channels × 2` in bidirectional raw mode.
- Added `samples_per_line_bidir: 9000` to `acquisition:` section of `default_config.yaml`.
- Added `compute_pixel_lut_bi(n_pixels, laser_freq, res_freq, bidir_samples=9000)` to `reshape.py` — translates MATLAB `pixel_lut_bi_2.m`; returns flat int32 LUT `(n_pixels + n_bwd_pixels,)` with forward section (same as unidirectional LUT) followed by backward section (samples offset by `nsamp/2`; ~706 backward columns due to 9000-sample window).
- Added `reshape_pmt_data_bi(buffer, records_per_buffer, pixels_per_line, lut_bi)` to `reshape.py` — Numba JIT; translates `alazarReshapeCData2bi.c`; places forward pixels on even output lines, backward pixels reversed onto odd output lines (right-edge aligned); output shape `(2, records_per_buffer*2, pixels_per_line)`.
- Added `flip_lines=True` parameter to `apply_bidirectional_correction()` — hardware bidir path passes `flip_lines=False` (line orientation is already handled by `reshape_pmt_data_bi`); emulation path is unchanged (default `True`).
- `Scanner.__init__` pre-computes `_pixel_lut_bi` and JIT-warms `reshape_pmt_data_bi` when `raw_mode=True` and `bidirectional=True`.
- `Scanner._acquisition_loop` now dispatches on three paths: (a) raw bidir → `reshape_pmt_data_bi` + `flip_lines=False`; (b) raw unidirectional → `reshape_pmt_data` unchanged; (c) emulation → `reshape_pmt_data_emulation` with `flip_lines=True` unchanged.
- **Bugs fixed by this change:** (1) Every other line was mirrored left-right — `apply_bidirectional_correction` was flipping forward-scan lines that should not be flipped. (2) Image appeared repeated twice vertically — 256-trigger PSoC5 frame was mapped to a 512-record buffer, doubling the image. (3) Grab recorded only half the specified frame count — PSoC5 exhausted its trigger budget at half the expected buffer count.
- New unit tests: `TestComputePixelLutBi` (7 tests), `TestReshapePmtDataBi` (7 tests), `test_flip_lines_false_skips_flip`, `test_flip_lines_false_still_applies_shift` — all 43 `test_reshape.py` tests pass.

## v0.6.1 - March 15, 2026
- **PMT gains no longer zeroed at end of Focus / Grab**
- Removed `set_pmt_gain(0, 0)` / `set_pmt_gain(1, 0)` from `Scanner.cleanup()` in `scan.py`; PMT gains now retain their acquisition values after Focus or Grab completes.
- PMTs are still zeroed on application close via `AppController.close()`, ensuring a safe hardware state on shutdown or crash.
- Added `AppController.zero_angle()`: moves A-axis motor to absolute step 0, sends Knobby `zero_xyza` (cmd 31) to reset Knobby's display counters, and resets all PC-side position tracking; X/Y/Z motors are not moved.
- Added "Rotate to 0°" button (`PositionGroup.zero_angle_button`) in the GUI; shows a confirmation dialog before moving, warning that physical rotation may be dangerous.
- Wired `zero_angle_button.clicked` → `MainWindow._on_zero_angle_clicked` → `AppController.zero_angle()` in `main_window.py`.
- **Knobby Normal/Rotated mode — documented hardware limitation**
- Investigated whether Knobby sends a packet to the PC when the Normal/Rotated mode button is pressed; confirmed it does not (firmware only updates the Nextion touchscreen via `Serial1`; no byte is written to `Serial`).
- The Rotated-coordinates panel in the GUI is always shown and always valid; it cannot be disabled conditionally because the PC has no way to observe the current Knobby mode.
- Added note 7 to `docs/knobby_architecture.md` documenting this finding and the GUI design decision.

## v0.6.0 - March 15, 2026
- **Rolling average display in Image Display widget**
- Added `ImageDisplayWidget.set_rolling_avg(tau)`: exponential rolling average `avg = delta * avg + (1-delta) * frame` (delta = exp(-1/tau)); tau=0 disables; accumulator resets on tau change or frame-shape change.
- Added "Rolling avg" combobox to `ImageDisplayControlGroup` with "Off" and configurable tau choices.
- `ImageDisplayControlGroup` now accepts `config` parameter; reads `display.rolling_avg_taus` list (defaults: 5, 10, 20 frames).
- Added `rolling_avg_taus: [5, 10, 20]` to `display:` section of `default_config.yaml`.
- Wired combobox → `ImageDisplayWidget.set_rolling_avg()` in `panels.py`.
- **Optotune depth label: only show when calibration is loaded**
- `OptotuneGroup.depth_label` is now empty when no ETL calibration file is loaded (raw ETL value is already shown in the spinbox; the label is redundant).
- `MainWindow._on_etl_current_changed` passes `''` instead of `f'{current:04d}'` when `etl_to_depth` returns None.

## v0.5.0 - March 15, 2026
- **Fixed polarity bug in mock data saving (scan.py, sbx_writer.py, sbx_reader.py)**
- `ScanboxOriginalWriter.write_frame()` previously applied `65535 − frame_data` before writing, expecting signal-convention input (low = dark). The acquisition loop delivered wire-format data (high = dark), causing a double-inversion: dark pixels were stored as low values on disk and appeared inverted when loaded back.
- Writer now accepts **wire-format convention** (high = dark) directly and writes values to disk as-is, matching the original MATLAB `fwrite` output with zero extra operations in the save path.
- `ScanboxOriginalReader.get_frame()`, `get_channel()`, and `load()`: renamed parameter `raw` → `invert`. `invert=True` (default) applies `65535 −` and returns signal convention (low = dark), matching `sbxread.m` and Suite2p. `invert=False` returns wire-format (high = dark) for the GUI display pipeline, which applies its own inversion.
- `MainWindow._on_frame_selected()` updated to call `get_frame(invert=False)`.
- Round-trip tests updated: wire-format data written and verified with `invert=False`; new test `test_round_trip_invert_two_channels` verifies `invert=True` returns the complement.

## v0.4.9 - March 15, 2026
- **Full compatibility with original Scanbox .sbx/.mat file formats**
- All reading and writing of Scanbox data now uses ScanboxOriginalReader and ScanboxOriginalWriter, matching the original MATLAB Scanbox conventions (bitwise complement, shape, and metadata).
- Obsolete/legacy read/write code paths renamed (SbxReaderObsolete, SbxWriterObsolete); all usages updated to use the new compatible classes.
- Removed mat_writer.py and all related test code; all metadata is now written in MATLAB-compatible format via ScanboxOriginalWriter.
- GUI and all examples now load Scanbox files using raw=True to avoid double inversion; display inversion is applied only once, matching Scanbox display logic.
- Added debug print statements to verify pixel value polarity in the display pipeline (removed after verification).
- All tests updated and passing; file I/O is now fully Scanbox-compatible.

## v0.4.8 - March 13, 2026
- **Reshape function renaming for clarity (Milestone 1.3.1/1.3.3)**
- Renamed `reshape_pmt_data_raw()` → `reshape_pmt_data()`: real-hardware Numba JIT path (sums 4 raw ADC samples per pixel, `>> 2`, 16-bit wire format output); now the canonical function name for the hardware path.
- Renamed `reshape_pmt_data()` → `reshape_pmt_data_emulation()`: emulation-only shortcut that de-interleaves a pre-shaped buffer with no bit operations.
- Fixed `reshape_pmt_data_emulation()` body: was incorrectly applying `(buffer >> 2) & 0x3FFF` (14-bit output, 0–16383); now correctly de-interleaves without bit ops, preserving full 16-bit wire format (0–65532), consistent with the real hardware path.
- Updated all call sites: `scan.py` warmup JIT call, `benchmark_reshape.py`, `main_window.py`, `widgets.py`, `mock_alazar.py`. Test class renamed `TestReshapePmtDataRaw` → `TestReshapePmtData`; test assertion corrected `0x3FFF` → `0xFFFC`.
- **LSB bit description corrected (docs/alazar_digitizer.md, mock_alazar.py)**
- **Correction to v0.4.7 clarification:** LSB bits are NOT frame/line sync. `configureLsb9440(boardHandle, 0, 3)` in `scanbox.m` sets LSB[0]=disabled (always 0), LSB[1]=AUX_IN[1] (external TTL behavioral/trial event). Frame boundaries are tracked in software; the line trigger arrives at Alazar `TRIG IN`, not via LSB bits.
- Fixed display formula in docs: `(16383 - ch) * gain / 64` → `(65535 - ch) * gain / 256` (16-bit wire format throughout).
- Updated `configureLSB` docstring in `mock_alazar.py` to document correct LSB assignment.
- **Numba debug log suppression (examples/gui_example.py)**
- Added `logging.getLogger('numba').setLevel(logging.WARNING)` under `--verbose` flag to suppress JIT compilation bytecode traces at DEBUG level (these are not errors).

## v0.4.7 - March 11, 2026
- **External TTL event recording (Milestone 1.3.4)**
- Added `CMD_TTL_MASK = 64` constant and `set_ttl_mask(imask)` to `ScanboxController`; sends `[64, 0, imask]` to PSoC5 (mirrors `sb/sb_imask.m`); imask 0=disabled, 1=TTL0, 2=TTL1, 3=both.
- Added background daemon thread `TTLEventReader` to `ScanboxController` (started/stopped via `start_ttl_reader()` / `stop_ttl_reader()`): polls `in_waiting` every 5 ms, reads complete 5-byte event packets `[frame_low, frame_high, line_low, line_high, event_id]` sent by PSoC5, discards `event_id=255` acquisition-complete sentinel, stores the rest as `(frame, line, event_id)` tuples in a thread-safe list.
- Added `get_ttl_events()` and `clear_ttl_events()` to `ScanboxController`.
- `Scanner.configure_scan_params()` now calls `set_ttl_mask()` from `config['external_events']['interrupt_mask']` (default 0).
- `Scanner.run()` calls `clear_ttl_events()` + `start_ttl_reader()` after `start_acquisition()`; `cleanup()` calls `stop_ttl_reader()` before `stop_scan()`.
- `Scanner._create_metadata()` saves TTL events as int32 numpy arrays `frame`, `line`, `event_id` in the `.mat` file (MATLAB-compatible field names matching `sb_timestamps.m`).
- `mock_serial.Serial` handles `CMD_TTL_MASK` (records `state['ttl_mask']`) and gains `inject_ttl_event(frame, line, event_id)` helper for tests.
- Updated `CMD_NAMES`, `format_command()` for `CMD_TTL_MASK`.
- Added `TestTtlMaskCommand` and `TestTtlEventReader` test classes to `tests/test_controller.py` (11 new tests).
- Updated `devel/protocols/scanbox_controller.md`: replaced stub "Input Mask" section with "TTL Interrupt Mask" + "TTL Event Packet" protocol reference; updated command summary table.
- **Clarification documented:** The 2 LSBs of each Alazar ADC sample carry hardware sync signals (frame-sync on AUX_IN[0], line-sync on AUX_IN[1]) from the PSoC5 — these are NOT external TTL events. Full explanation in `examples/check_lsb_sync_bits.py`.

## v0.4.6 - March 11, 2026
- **Per-channel histogram, PMT1 red colourmap, config-driven red_boost, UX refinements (Milestone 2.3.2)**
- **PMT1 colourmap (`red_white`):** Added `red` and `red_white` colormaps to `_build_colormap_lut()`; the `red_white` ramp uses a configurable `red_boost` exponent so the red channel appears visually as bright as the green one despite the eye's lower red sensitivity. `_DISPLAY_COLORMAP_PMT1 = 'red_white'` and `_RED_BOOST = 1.963` added as module-level constants.
- **Config-driven `red_boost`:** Added `display.red_boost: 1.963` to `default_config.yaml`. `ScanboxConfig.__init__` now stores `self.display` and `to_dict()` exports it (both were previously missing). `ImageDisplayWidget.__init__` reads `display.red_boost` from config and builds `_lut_pmt1` per-widget so the config value is respected rather than the module-level default.
- **White-onset decoupled from red_boost:** White onset is fixed at ADC value 128 (`2.0*v - 255`); `_RED_BOOST` only affects the red ramp steepness, so changing boost does not shift the saturation point.
- **Mock data equalized:** Removed the 0.4× amplitude factor on ch1 in both `MockAlazar._prepare_test_frames` and `_prepare_test_frames_raw`; both PMT channels now have equal signal magnitude in emulation.
- **Per-channel histogram (Milestone 2.3.2):** Rewrote `HistogramWidget` for channel-aware display:
  - `__init__` now builds PMT1 colours (`_bar_color1`, `_border_color1`) and `_lut_pmt1` alongside the existing PMT0 ones; adds `_counts1` and `_channel` state.
  - New `set_channel(index)` method (0=PMT0, 1=PMT1, 2=both) triggers an immediate repaint without waiting for the next frame.
  - `_compute_histogram` always computes counts for both channels so channel switching is instant.
  - `paintEvent` selects bars, LUT, and colours based on active channel; overlay mode (channel 2) draws both histograms at 60 % opacity over each other.
  - Split colourbar in overlay mode: top half shows `green_white` (PMT0), bottom half shows `red_white` (PMT1), each at half the label-strip height.
- **Histogram wired to channel combobox:** `panels.py` connects `channel_combobox.currentIndexChanged` to `histogram.set_channel` alongside the existing `image_display.set_channel` connection, so the histogram always matches the displayed channel.
- **Objective Position X/Y/Z right-justified:** All nine coordinate `QLineEdit` fields (Knobby, Abs, Rotated × X/Y/Z) now use `AlignRight` so numbers stay anchored to the right edge as their values grow; Angle field is unchanged.
- Total: 290 tests passing (100% pass rate; no logic added to tested modules)
- **Status:** Live histogram and image display are colour-matched and channel-synchronised; PMT0/PMT1 visual balance tuned via `display.red_boost` in config

---

## v0.4.5 - March 10, 2026
- **Bidirectional scan mode — PSoC5 hardware command now sent on mode change**
- Added `CMD_UNIDIRECTIONAL = 33` and `CMD_BIDIRECTIONAL = 34` constants to `ScanboxController`; `set_scan_mode(bidirectional)` sends `[33, 0, 0]` or `[34, 0, 0]` to PSoC5 (mirrors MATLAB `sb_unidirectional.m` / `sb_bidirectional.m`)
- `AppController.set_scan_mode()` now calls `self._hw_controller.set_scan_mode()` when hardware is open, guarded by `try/except` that emits `hardware_error`; falls back to config-only update when hardware is not connected
- `AppController.open()` sends the configured scan mode to PSoC5 at startup, matching the MATLAB startup sequence in `scanbox.m`
- Added `format_command()` decoders for CMD 33 and CMD 34; updated protocol header docstring in `controller.py` and `Reference:` list
- `MockSerial._handle_scanbox_command()` now handles CMD 33/34: updates `state['scan_mode']` to `'unidirectional'` or `'bidirectional'`
- Added `state['scan_mode']` field (default `'unidirectional'`) to `MockSerial` initial state
- Added `TestScanModeControl` class in `tests/test_controller.py` (5 tests: unidirectional packet, bidirectional packet, CMD ID constants, `format_command` decoders for both modes)
- Total: 290 tests passing (100% pass rate)

---

## v0.4.4 - March 10, 2026
- **Bidirectional alignment — flip+shift correction wired to GUI**
- Added `apply_bidirectional_correction(frame, pixel_shift)` to `reshape.py`: flips odd (backward) lines horizontally (required because the resonant scanner traverses those lines in reverse), then applies a configurable `pixel_shift` (bishift) with edge-zeroing to correct for residual timing offset
- Added `acquisition.unidirectional` (default `true`) and `acquisition.bishift` (13-element int list, default all zeros) to `default_config.yaml`
- `Scanner._acquisition_loop` now reads `unidirectional` from config each frame and calls `apply_bidirectional_correction` when in bidirectional mode; zero overhead in unidirectional mode (the `if` branch is not entered)
- `Scanner.__init__` initialises `self._bishift` as a reference to `config['acquisition']['bishift']`, so `AppController.set_bishift()` updates propagate to the running scanner on the very next frame
- Added `AppController.set_scan_mode(bidirectional)` and `AppController.set_bishift(shift)`
- Wired `ScannerControlGroup.scan_mode_combobox` and `bidir_alignment_spinbox` in `main_window.py`; spinbox is enabled only in bidirectional mode and auto-updates when the magnification combobox changes
- Added 8 unit tests in `TestApplyBidirectionalCorrection` (`tests/test_reshape.py`): shape/dtype, even lines unchanged, odd lines flipped, zero-shift only flips, positive shift, negative shift, in-place return, multichannel
- Total: 285 tests passing (100% pass rate)

---

## v0.4.3 - March 10, 2026
- **Structured logging — hardware events routed to GUI log, terminal silenced by default**
- Replaced `print()` calls in `pyscanbox/hardware/knobby.py` with `logger.info/warning()`: connection open/close and command errors no longer go to the terminal; they appear as `logging.INFO` records (visible only with `--verbose`) and are captured by the GUI log panel via the existing `on_command` / `_log_event` plumbing
- Replaced `print()` calls in `pyscanbox/hardware/alazar.py` with `logger.info/error/warning()`: buffer-alignment notes, read errors, and abort warnings no longer reach the terminal except with `--verbose`
- Replaced hardware-lifecycle `print()` calls in `pyscanbox/acquisition/scan.py` (initializing hardware, file writers, Pockels, scan parameters, start/stop, cleanup) with `logger.info/error()` **and** `self._notify_cmd('System', ...)` so they also appear in the GUI command-log panel during acquisition
- Kept three intentional `print()` calls in `scan.py` for live debugging: fps counter every 100 frames, "Acquisition complete.", and "Total frames acquired: N"
- `AppController.open()` now emits individual GUI log events as each device connects: `Controller connected (COMx)`, `Knobby connected (COMx)`, `Motor connected (COMx)`, `ETL calibration loaded (...)`, and a final `All hardware ready (emulation)` summary — replacing the single generic `Hardware connected` entry
- Terminal output at startup limited to config path, emulation flag, and real-hardware warning; all other informational output requires `--verbose`
- Total: 277 tests passing (100% pass rate)
- **Status:** GUI log shows granular connection and initialization events; terminal is quiet by default

---

## v0.4.2 - March 9, 2026
- **Zoom/pan via QGraphicsView, image markers with toggle button (Milestone 2.3.2 complete)**
- `ImageDisplayWidget` now uses an embedded `_ImageCanvas(QGraphicsView)` instead of `QLabel`: mouse-wheel zoom (×1.25 per step, anchored under cursor), left-click-drag pan, right-click context menu (Fit / Zoom In / Zoom Out / Actual Size), window-resize re-fit
- Toggleable "✛" marker button in top-right corner of canvas: activates crosshair cursor; left-click places a persistent yellow circle anchored in image coordinates (survives zoom/pan); `Esc` or re-click exits marker mode; "Clear Markers" added to right-click menu; marker pixel coordinates printed to stdout
- Total: 277 tests passing (100% pass rate)
- **Status:** Milestone 2.3 (Live Preview) fully complete

---

## v0.4.1 - March 8, 2026
- **Data playback / review mode (Milestone 2.3.3)**
- Added "Open Data..." (Ctrl+D) to File menu; opens `.sbx` recordings via `SbxReader` (memory-mapped)
- New `FrameSelectorWidget`: compact 28–40 px horizontal slider + "N / M" counter; toggled via View → Show Frame Selector (Ctrl+F); disabled until a recording is loaded
- Wire-format → 14-bit conversion (`>> 2`) applied in `_on_frame_selected` before passing frames to `ImageDisplayWidget` and `HistogramWidget`; fixes binary display caused by raw on-disk encoding (14-bit PMT value in bits 15:2, sync bits in 1:0)
- `HistogramWidget.force_update_frame()` added — bypasses `UPDATE_EVERY` throttle so the histogram repaints on every frame-selector move; live-acquisition path unchanged
- Image Display Gain slider re-renders the current loaded frame immediately via new `_on_display_gain_changed` slot
- `SbxReader` handle properly closed on window exit and when a new file is opened
- Total: 264 tests passing (100% pass rate; no logic added to tested modules)
- **Status:** `.sbx` recordings can be browsed frame-by-frame with correct display scaling, histogram, and gain control

---

## v0.4.0 - March 7, 2026
- **Critical fix — `reshape_pmt_data_raw` shift (Milestone 3.4):** Pixel values in `.sbx` files were 4× lower than the MATLAB reference, causing signals to appear very low on real hardware. `reshape_pmt_data_raw` now uses `>> 2` (divide 4-sample sum by 4), matching `alazarReshapeCData2.c` exactly (`(unsigned short)(tmp >> 2)`). The 2 LSB sync bits are not stripped; the output retains the 16-bit wire encoding (14-bit ADC data in bits 15:2). pyscanbox `.sbx` files are now byte-compatible with MATLAB output.
- Total: 264 tests passing (100% pass rate)
- **Status:** `.sbx` pixel values match MATLAB reference; confirmed on real hardware

---

## v0.3.7 - March 5, 2026
- **HIL display bugs fixed; GUI visualization improvements (Milestones 2.3.2, 3.2, 3.4, 3.5)**
- **Critical fix — PMT display inversion (Milestone 3.5):** PMT current *decreases* with more light; the ATS9440 offset-binary encoding places the no-light background at ADC ≈ 16383 (maximum), not zero. `ImageDisplayWidget.update_frame()` was displaying raw ADC values (high = bright), making background white and fluorescence invisible. Fixed with `(16383 - ch) * gain / 64` in Fluorescence mode — background maps to 0 (black), signal to 255 (bright), matching MATLAB `alazarReshapeCData2.c` (`255 - high_byte`). Documented in new `docs/alazar_digitizer.md` section "PMT Output Polarity and Display Inversion".
- **Critical fix — `Scanner.raw_mode` always False (Milestone 3.4):** `Scanner.__init__` read `alazar.raw_mode` from config (default `false`), causing the emulation reshape path to run on the 5 MB raw hardware buffer — every pixel saturated. Fixed: `raw_mode = not emulation_on or config.get('alazar', {}).get('raw_mode', False)` so real hardware always uses the raw path.
- **Fix — COM4 `PermissionError` on Focus/Grab (Milestone 3.2):** `Scanner` was opening a second connection to the Trinamic motor port already held open by `AppController`; fixed by adding `hw_motor` parameter to `Scanner.__init__()` / `ScannerThread.__init__()`, mirroring the `hw_controller` pattern.
- **Fix — motor GAP command log flooding (Milestone 3.2):** Background polling emits hundreds of `GAP` queries per second; `Scanner._on_motor_cmd` lacked a filter; fixed with `if cmd == 'GAP': return` in both `AppController._on_motor_cmd` and `Scanner._on_motor_cmd`.
- **Alazar input range config-driven (Milestone 3.4):** Hardcoded ±200 mV replaced by `pmt.amplifier_type` from config; confirmed correct for this rig (`variable` = ±200 mV).
- **Color display (Milestone 2.3.2):** PMT0 rendered green, PMT1 red; overlay mixes both channels (R=PMT1, G=PMT0, B=0); uses `QImage.Format_RGB888`.
- **Channel combobox wired (Milestone 2.3.2):** `ImageDisplayControlGroup.channel_combobox` was present but never connected; now wired to `ImageDisplayWidget.set_channel()`.
- **Display mode selector (Milestone 2.3.2):** New "Display mode" combobox: "Fluorescence" (inverted, default) and "Direct (debug)" (raw ADC); wired to `ImageDisplayWidget.set_display_mode()`.
- **Histogram toggle (Milestone 2.3.2):** View → Show Histogram (Ctrl+H); hidden by default; signal disconnected when hidden to prevent freeze on low-spec hardware.
- **`--print-frames` debug flag:** Added to `gui_example.py`; prints min/max/mean and inverted display statistics for both channels every N frames.
- Total: 264 tests passing (100% pass rate; no logic added to tested modules)
- **Status:** Live image display confirmed working on real hardware with fluorescent pollen sample

---

## v0.3.6 - March 3, 2026
- **Bug fix — check_knobby_motor.py startup motor-to-zero (Milestone 3.3)**
- Root cause: Knobby firmware (`knobby2.ino`) initialises `page=1` and `oldpage=-1`. On the
  first `loop()` iteration this triggers the `oldpage != page` branch which immediately
  transmits one 5-byte position packet per axis with `dpos=0` — before any knob has been
  turned. `check_knobby_motor.py` was forwarding these as `motor.move_absolute(motor_id, 0)`,
  driving all axes to hardware step position 0 (dangerous on real hardware).
- Fix: changed `move_absolute(motor_id, target_steps)` →
  `move_relative(motor_id, delta_steps)` in `examples/check_knobby_motor.py`.
  `delta_steps` is the difference between the new and previous Knobby `dpos` value; a
  startup packet where `dpos=0` (and `last_knobby_steps=0`) produces `delta=0` and no
  motor movement. This also correctly decouples the Knobby's accumulated-offset
  coordinate from the Trinamic board's absolute hardware step counter.
- Documentation: updated `docs/knobby_architecture.md` — "Knobby Display Update Flow"
  now specifies relative moves; added Important Notes 5 and 6 explaining the startup
  zero-packet quirk and the `dpos` vs hardware-counter distinction.
- Total: 264 tests passing (100% pass rate; no new tests required — no logic added,
  only the dangerous call site changed)
- **Status:** `check_knobby_motor.py` safe for real hardware use

---

## v0.3.5 - March 3, 2026
- **Interpretable magnification labels, ETL current control, single-source-of-truth enforcement**
- **Magnification labels (Milestone 1.2.2, 2.2):** Changed combobox from integer indices ("1"–"13") to
  human-readable zoom labels ("1.0x"–"8.0x") matching MATLAB's `sprintf('%.1f', gain_galvo)` where
  `gain_galvo = logspace(log10(1), log10(8), 13)`; moved labels to `ScanboxController.MAG_LABELS`
  tuple as the single source of truth; `widgets.py` now reads them via `hw_controller.ScanboxController.MAG_LABELS`
- **ETL current control (Milestone 2.5.1, 2.5.3):**
  - Added `CMD_ETL = 48`, `ETL_CURRENT_MIN = 0`, `ETL_CURRENT_MAX = 1760` to `ScanboxController`
  - Added `set_etl_current(current)` method with 16-bit encoding matching `sb/sb_current.m`
    (0b0111 prefix in upper nibble)
  - Added CMD_ETL to `CMD_NAMES` and `format_command()` decoder
  - `OptotuneGroup` slider range fixed (was -100..100, now 0–1760 read from `ETL_CURRENT_MIN/MAX`)
  - Added `QSpinBox` bidirectionally linked to the ETL slider
  - Added `AppController.set_etl_current()` method
  - Wired `OptotuneGroup.etl_slider` → `AppController.set_etl_current()` in `main_window.py`
- **Protocol documentation:** Added ETL Current Control (ID 48) section to `scanbox_controller.md`;
  updated `optotune.md` status and corrected protocol description (ETL goes through PSoC5 controller,
  not a separate serial device)
- **Single source of truth rule (development_guide.md §3):** Added explicit coding standard bullet:
  hardware parameters, value ranges, conversion factors and lookup tables must be defined in exactly
  one place — always in the lowest-level module that owns the concept
- Total: 264 tests passing (100% pass rate)
- **Status:** ETL current control functional end-to-end in emulation mode; magnification combobox shows interpretable values

---

## v0.3.4 - March 3, 2026
- **Controller protocol audit, GUI-hardware wiring completions, scanner lifecycle fixes, acquisition bug fixes**
- **Protocol audit (Milestone 1.2.2):** Cross-referenced all MATLAB `sb_*.m` source files against
  `controller.py`; added four missing commands: CMD_FRAME_COUNT (ID 1, `sb_setframe.m`),
  CMD_LINES (ID 2, `sb_setline.m`), CMD_MAGNIFICATION (ID 3, `sb_setmag.m`), CMD_DEADBAND
  (ID 9, `sb_deadband.m`); added `set_frame_count()`, `set_lines()`, `set_magnification()`,
  `set_pockels_deadband()` methods; 12 new tests in `TestConfigurationCommands`
- **PMT gain commands (1.2.2):** Added CMD_GAIN0 (ID 6) / CMD_GAIN1 (ID 7) from `sb_gain0.m` /
  `sb_gain1.m`; `set_pmt_gain(pmt_id, value)` method
- **GUI-hardware wiring (Milestone 2.2):**
  - `CameraPathGroup.enable_checkbox` → `set_mirror('epi'/'2p')`
  - `PMTControlGroup` sliders → `AppController.set_pmt_gain()` (0–100% → 0–255 HW)
  - `ScannerControlGroup.total_frames_spinbox` wired through `start_grab(frames=)` →
    `ScannerThread(frames_override=)` → `Scanner`; 0 = run forever (MATLAB convention)
- **Scanner lifecycle (Milestone 1.3.3):** Added `configure_scan_params()` (sends lines,
  frame_count, magnification); corrected startup order; added `stop_scan()` in cleanup;
  replaced `setup_pockels_and_shutter()` with `initialize_pockels()` / `zero_pockels()`;
  commented stubs for Uniblitz-style rigs
- **Bug fix — grab stop:** `total_frames_spinbox` was disconnected from Scanner; Python loop
  with `frames=0` never ran (vs MATLAB 0=forever); fixed by threading frames through the
  full call chain and mapping 0 → `sys.maxsize`
- **Bug fix — None crash on Abort:** stale queued `frame_data_ready` signals arriving after
  cleanup caused `update_frame()` to crash on `frame_data[0]`; fixed with early-return guard
- **Bug fix — scipy.io.savemat crash:** `_create_metadata()` included `self.config` (nested dict
  with YAML `null` → Python `None`); `scipy.io.savemat` cannot serialize `None`; removed
  `config` key, flattened `pockels` dict to scalars; wrapped `mat_writer.write()` in
  try/except so a metadata failure is a warning, not an acquisition error
- **Magnification combobox (Milestone 2.2):** Corrected from 4 arbitrary float items to 13
  discrete integer-index items ("1"–"13") matching the MATLAB popup exactly; corrected
  controller validation from 1–255 to 0–12 (MATLAB sends `popup.Value - 1`; 0 = largest
  FOV, 12 = highest zoom); wired `magnification_combobox.currentIndexChanged` →
  `AppController.set_magnification(index)` which also writes back to
  `config['acquisition']['magnification']` so Scanner picks up the current value at scan
  start; updated `default_config.yaml` and `scan.py` defaults from 1 → 0
- Total: 264 tests passing (100% pass rate)
- **Status:** Grab and Focus workflows fully functional end-to-end in emulation mode; all main control widgets wired to hardware

---

## v0.3.3 - March 2, 2026
- **AlazarBeforeAsyncRead HIL fixes + scanner auto-start + full HIL confirmation of controller/motor/knobby/Alazar (Milestones 3.1–3.4 partial)**
- Fixed `AlazarBeforeAsyncRead ApiInvalidData` on real hardware: corrected ADMA flags
  (`ADMA_NPT|ADMA_INTERLEAVE_SAMPLES|ADMA_EXTERNAL_STARTCAPTURE = 0x1201`),
  `samplesPerRecord` (5000, per scan line) and `recordsPerBuffer` (512, lines per frame)
  to match MATLAB `scanbox.m` line 2223; added missing `setRecordSize` call
- Fixed `_bytes_per_buffer` to use correct raw-hardware layout
  (5000 × 512 × 2ch × 2 bytes = ~9.77 MB) vs emulation layout (~1.55 MB)
- Fixed `mock_alazar.setCaptureClock`: ignored `SAMPLE_RATE_USER_DEF=0x40` (API placeholder,
  not Hz), preventing 12,736 s sleep between buffers in emulation mode
- Added `abortAsyncRead()` call on `waitAsyncBufferComplete` failure in `read_buffer()`,
  per AlazarTech API contract (board owns all pending DMA buffers after any timeout)
- Added `open_scanner()` / `close_scanner()` to `check_alazar.py`; `--full-test` now
  connects to the PSoC5 controller, starts the scanner (2 s warmup), runs acquisition,
  then stops the scanner in a `finally` block
- Updated `alazar_digitizer.md`: corrected buffer size section, expanded trigger section
  with scanner-dependency explanation, added `ApiInvalidData` (BeforeAsyncRead) and
  `ApiWaitTimeout` troubleshooting entries
- **Milestone 3.1 (Controller):** mirror actuation and scan start/stop confirmed; shutter CMD
  confirmed no-op (ThorLabs shutter opens via scan command as expected); Pockels commands
  accepted — output measurement pending (Conoptics 302RM, 0–2 V unipolar)
- **Milestone 3.2 (Motor):** movement and position polling confirmed on all 4 axes (X, Y, Z, A);
  distance accuracy not yet measured
- **Milestone 3.3 (Knobby):** serial comms, position reads, and full knobby→motor integration
  confirmed via `check_knobby_motor.py`; step-to-micron accuracy not yet validated
- **Milestone 3.4 (Alazar):** full DMA acquisition confirmed — `check_alazar.py --full-test
  --no-emulation` acquired frames successfully with laser and scanner running; formal
  throughput benchmarking pending
- Total: 252 tests passing (100% pass rate)
- **Status:** Phase 3 well underway; remaining items: (1) measure Pockels output with power
  meter, (2) measure motor distance accuracy, (3) benchmark Alazar throughput, (4) verify LSB outputs

---

## v0.3.2 - March 1, 2026
- **Pixel LUT + raw-mode emulation (Milestone 1.3.1 additions, 1.3.3 partial, 1.6.1)**
- Added `compute_pixel_lut()` (arccosine LUT, translation of `pixel_lut_2.m`) and
  `reshape_pmt_data_raw()` (Numba JIT, matches `alazarReshapeCData2.c`) to `reshape.py`
- `Scanner` reads `alazar.raw_mode` from config; precomputes LUT at init; dispatches
  `_acquisition_loop` to `reshape_pmt_data_raw()` when enabled
- `mock_alazar.Board` gains `set_frame_shape()` (Gaussian-spot test frames) and
  `set_raw_mode()` (pre-warped raw-format buffers using inverse pixel LUT)
- `alazar.py` `open()` calls `set_raw_mode()` on the mock, propagating laser frequency,
  resonant frequency, and `samples_per_line` from config
- Both config files gain `alazar.raw_mode: false` and `acquisition.samples_per_line: 5000`
- 13 new unit tests: `TestComputePixelLut` (7) + `TestReshapePmtDataRaw` (6); all 19
  reshape tests passing; LUT verified: pixel 0 → sample 112, pixel 795 → sample 4939

---

## v0.3.1 - March 1, 2026
- **Test coverage: hardware and I/O modules fully covered** (preceded by GUI work recorded in v0.4.1)
- Created `tests/test_protocols.py` — tests for all functions in `protocols.py`
- Rewrote `tests/test_motor.py` — now tests `TrinamicMotor` via `mock_serial` (previously tested `protocols.py`)
- Created `tests/test_knobby.py` — tests for `Knobby` class and unit conversion functions
- Created `tests/test_mat_writer.py` — tests for `MatWriter`, `write_mat_file()`, and `create_suite2p_metadata()`
- Added `start_scan()` / `stop_scan()` tests to `test_controller.py`
- Created `examples/check_knobby_motor.py` — end-to-end hardware check script (polls Knobby → forwards to motor → queries back → prints table)
- Minor fixes: added `TrinamicMotor` context manager, `mock_serial._last_written`, `ScanboxConfig.setdefault()`, fixed `mat_writer.append()` scipy key stripping
- Total: 239 tests passing (100% pass rate)
- **Status:** Phase 1 test gaps closed; ready for Phase 2 GUI–hardware integration (Milestone 2.2)

---

## v0.3.0 - February 23, 2026
- **Development Phase Reorganization**
- Restructured phases to enable GUI development before hardware access
- New phase order: Phase 1 (Backend) → Phase 2 (GUI) → Phase 3 (HIL Testing) → Phase 4 (Integration)
- GUI development now proceeds using emulation mode in parallel with hardware preparation
- **PyQt6 GUI Implementation (Phase 2.1 Complete)**
- Created complete GUI framework following GUI_SPECIFICATION.md
- Implemented main_window.py with QMainWindow and menu system
- Implemented panels.py with LeftControlPanel and RightDisplayPanel
- Implemented widgets.py with all 10 control group boxes:
  - LaserControlGroup (power, shutter, wavelength)
  - ScannerControlGroup (frames, lines, magnification, scan mode)
  - PositionDisplayGroup (objective angle, world/rotated coordinates)
  - AcquisitionControlGroup (focus/grab buttons, status displays)
  - FileStorageGroup (directory, metadata, channel selection)
  - ImageDisplayWidget (QGraphicsView for real-time display)
  - CameraPathGroup (enable, exposure, properties)
  - PMTControlGroup (PMT0/PMT1 gain sliders)
  - ImageDisplayControlGroup (channel selector, display gain)
  - OptotuneGroup (ETL slider for volumetric imaging)
- Created gui_example.py launcher script
- All GUI controls functional at UI level (backend integration pending)
- Two-panel splitter layout with adjustable panel widths
- **Status:** Phase 2.1 (GUI Framework) complete, ready for emulation-mode integration

---

## v0.2.2 - February 22, 2026
- **Performance optimization complete — exceeds target by 9-10×**
- Installed Numba 0.64.0 for JIT compilation
- Created comprehensive benchmark suite (benchmark_reshape.py)
- Validated reshape_pmt_data() performance: 4,500–5,400 MB/s sustained
- All 6 reshape unit tests passing
- Performance results demonstrate Python implementation is production-ready
- No C++ extensions needed — Numba JIT exceeds requirements
- Total: 88 tests passing (100% pass rate)
- **Status:** Core backend complete, ready for HIL testing and GUI integration

---

## v0.2.1 - February 22, 2026
- **Complete Alazar integration implementation**
- Implemented configure() with full trigger and LSB configuration
- Implemented configure_lsb_outputs() using SDK's configureLSB method
- Implemented allocate_buffers() with DMABuffer support (pinned memory for DMA)
- Implemented start_acquisition() with async DMA setup and buffer posting
- Implemented read_buffer() with circular buffer management and auto-reposting
- Implemented stop_acquisition() with proper cleanup
- Fixed mock_alazar buffer size calculation for interleaved multi-channel data
- Updated all Alazar tests to account for interleaved channel data (4 tests fixed)
- Created comprehensive integration test suite (test_alazar_integration.py)
- Integration tests demonstrate: basic workflow, error handling, performance (83.5 MB/s)
- Total: 82 tests passing (100% pass rate), ready for hardware-in-the-loop testing
- **Status:** Alazar integration complete in emulation mode, pending HIL testing on Windows rig

---

## v0.2.0 - February 22, 2026
- Hardware emulation system implemented and fully tested
- Mock serial interface for controller and motor (92% coverage)
- Mock Alazar digitizer with synthetic data generation (98% coverage)
- Emulation configuration support in ScanboxConfig
- Conditional hardware imports based on emulation mode
- Example code demonstrating emulation usage
- Comprehensive test suite: 62 emulator tests added (28 mock_serial, 34 mock_alazar)
- API alignment with atsapi.py (camelCase parameters, exception handling)
- Vendor directory structure for development-time atsapi.py
- Fixed emulation_example.py Board factory function bug
- Total: 88 tests passing (100% pass rate), 19% overall coverage
- **Status:** Linux development enabled without hardware dependencies, production-ready emulation

---

## v0.1.0 - February 21, 2026
- Initial project structure created
- Core hardware interfaces implemented (controller, motor, protocols)
- Data acquisition framework established
- File I/O system completed
- Unit tests for completed modules
- **Status:** Phase 1 foundation complete, ready for Alazar integration
