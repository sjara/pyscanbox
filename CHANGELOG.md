# pyscanbox Changelog

All notable changes to this project are documented here. This file is append-only — do not edit past entries.

> **Reminder:** When adding a new version entry, also bump the version string in `pyscanbox/__init__.py` and `pyproject.toml` to match.

---

## v0.5.0 - March 15, 2026 (Current)
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

## v0.4.8 - March 13, 2026 (Current)
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
