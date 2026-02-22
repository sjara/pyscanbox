# API Reference

## Core Modules

### pyscanbox.config

Configuration management for pyscanbox.

#### ScanboxConfig

Configuration container class.

**Methods:**
- `__init__(config_dict)` - Initialize with configuration dictionary
- `to_dict()` - Convert to dictionary

**Functions:**
- `find_config()` - Find configuration file in standard locations
- `load_config(filepath=None)` - Load configuration from YAML file
- `save_config(config, filepath)` - Save configuration to YAML file

---

## Hardware Modules

### pyscanbox.hardware.alazar

AlazarTech digitizer interface.

#### AlazarDigitizer

Interface to ATS9440 digitizer.

**Methods:**
- `__init__(config)` - Initialize with configuration
- `open()` - Open connection to board
- `configure()` - Configure board for acquisition
- `configure_lsb_outputs(lsb0, lsb1)` - Configure LSB sync outputs
- `allocate_buffers()` - Allocate DMA buffers
- `start_acquisition()` - Start continuous acquisition
- `read_buffer(timeout_ms)` - Read one buffer of data
- `stop_acquisition()` - Stop acquisition
- `close()` - Close board connection

---

### pyscanbox.hardware.controller

Main Scanbox controller (Arduino) interface.

#### ScanboxController

Serial interface to controller at 1 Mbaud.

**Methods:**
- `__init__(config)` - Initialize with configuration
- `open()` - Open serial connection
- `close()` - Close serial connection
- `set_pockels(base, active)` - Set Pockels cell power (0-255)
- `set_shutter(open)` - Set shutter state (True/False)
- `set_mirror(mode)` - Set mirror mode ('2p' or 'epi')
- `get_current_pockels()` - Get current Pockels settings
- `get_shutter_state()` - Get shutter state
- `get_mirror_mode()` - Get mirror mode

**Command IDs:**
- `CMD_POCKELS = 8`
- `CMD_MIRROR = 5`
- `CMD_SHUTTER = 16`

---

### pyscanbox.hardware.motor

Trinamic motor controller interface.

#### TrinamicMotor

TMCL protocol interface at 57600 baud.

**Methods:**
- `__init__(config)` - Initialize with configuration
- `open()` - Open serial connection
- `close()` - Close serial connection
- `send_command(cmd, type, motor, value)` - Send TMCL command
- `get_axis_parameter(motor, param_type)` - Get axis parameter (GAP)
- `set_axis_parameter(motor, param_type, value)` - Set axis parameter (SAP)
- `get_position(motor)` - Get current position
- `move_absolute(motor, position)` - Move to absolute position (MVP)
- `move_relative(motor, distance)` - Move relative distance (MVP)
- `rotate_right(motor, velocity)` - Rotate right (ROR)
- `rotate_left(motor, velocity)` - Rotate left (ROL)
- `stop_motor(motor)` - Stop motor (MST)
- `start_polling(callback)` - Start background polling
- `stop_polling()` - Stop background polling
- `get_cached_positions()` - Get cached positions from polling

---

### pyscanbox.hardware.protocols

Low-level protocol implementations.

**Functions:**
- `build_tmcl_packet(cmd, type, motor, value)` - Build TMCL 9-byte packet
- `parse_tmcl_response(response)` - Parse TMCL response packet
- `calculate_checksum(data)` - Calculate TMCL checksum

**Constants:**
- `TMCL_COMMANDS` - Dictionary mapping command names to IDs

---

## Acquisition Modules

### pyscanbox.acquisition.scan

Main acquisition loop and scanner control.

#### Scanner

Coordinates hardware and manages acquisition.

**Methods:**
- `__init__(config, output_path)` - Initialize scanner
- `initialize_hardware()` - Initialize all hardware
- `initialize_writers()` - Initialize file writers
- `setup_pockels_and_shutter(base, active)` - Configure Pockels and shutter
- `run()` - Run main acquisition loop
- `stop()` - Stop acquisition
- `cleanup()` - Cleanup and shutdown

---

### pyscanbox.acquisition.reshape

High-speed data reshaping (Numba-optimized).

**Functions:**
- `reshape_pmt_data(buffer, lines, pixels)` - Reshape PMT data (JIT compiled)
- `extract_sync_bits(buffer)` - Extract LSB sync bits (JIT compiled)
- `bit_shift_14_to_16(data)` - Shift to 16-bit range (JIT compiled)
- `reshape_for_display(data)` - Prepare for display (uint8)
- `validate_buffer_size(buffer, lines, pixels, channels)` - Validate buffer

---

### pyscanbox.acquisition.buffer

DMA buffer management.

#### BufferPool

Pool of pinned DMA buffers.

**Methods:**
- `__init__(buffer_size, buffer_count)` - Initialize pool
- `acquire_buffer(timeout)` - Get available buffer
- `release_buffer(index)` - Release buffer back to pool
- `get_buffer(index)` - Get buffer array
- `get_buffer_pointer(index)` - Get buffer pointer for DMA
- `reset()` - Reset pool

#### CircularBufferQueue

Thread-safe circular buffer queue.

**Methods:**
- `__init__(max_size)` - Initialize queue
- `put(buffer_index, timeout)` - Put buffer in queue
- `get(timeout)` - Get buffer from queue
- `size()` - Get queue size
- `is_empty()` - Check if empty
- `is_full()` - Check if full

---

## I/O Modules

### pyscanbox.io.sbx_writer

Binary .sbx file writer.

#### SbxWriter

Writes raw uint16 data to .sbx files.

**Methods:**
- `__init__(filepath)` - Initialize writer
- `write_frame(frame_data)` - Write one frame
- `write_buffer(buffer)` - Write raw buffer
- `flush()` - Flush to disk
- `close()` - Close file
- `get_frames_written()` - Get frame count

**Functions:**
- `write_sbx_file(filepath, data)` - Convenience function for full dataset

---

### pyscanbox.io.mat_writer

MATLAB metadata writer.

#### MatWriter

Writes metadata in MATLAB format.

**Methods:**
- `__init__(filepath)` - Initialize writer
- `write(metadata)` - Write metadata dictionary
- `append(metadata)` - Append to existing file

**Functions:**
- `write_mat_file(filepath, metadata)` - Convenience function
- `create_suite2p_metadata(config, frames)` - Create Suite2p-compatible metadata

---

## Utility Modules

### pyscanbox.utils.logging

Logging utilities.

**Functions:**
- `setup_logging(level, log_file)` - Setup logging configuration
- `get_logger(name)` - Get logger for module
- `log_hardware_event(component, event, details)` - Log hardware event
- `log_acquisition_stats(frames, duration, size)` - Log acquisition statistics

#### ProgressReporter

Progress tracking for acquisitions.

**Methods:**
- `__init__(total, report_interval)` - Initialize reporter
- `update(count)` - Update progress
- `finish()` - Mark complete

---

### pyscanbox.utils.threading

Threading utilities.

#### BackgroundWorker

Background worker thread for continuous tasks.

**Methods:**
- `__init__(func, interval)` - Initialize worker
- `start()` - Start worker thread
- `stop(timeout)` - Stop worker thread
- `is_running()` - Check if running

#### ThreadSafeCounter

Thread-safe counter.

**Methods:**
- `__init__(initial)` - Initialize counter
- `increment(amount)` - Increment and return value
- `get()` - Get current value
- `reset()` - Reset to zero

#### RateLimiter

Rate limiter for operations.

**Methods:**
- `__init__(rate)` - Initialize with max ops/sec
- `wait()` - Wait to maintain rate limit

---

## Example Usage

### Basic Scanning

```python
import pyscanbox

config = pyscanbox.config.load_config()
scanner = pyscanbox.acquisition.scan.Scanner(
    config.to_dict(),
    output_path='data/my_scan'
)
scanner.run()
```

### Motor Control

```python
import pyscanbox

config = pyscanbox.config.load_config()
motors = pyscanbox.hardware.motor.TrinamicMotor(config.to_dict())
motors.open()
motors.move_absolute(motor=0, position=1000)
motors.close()
```

### Controller Operations

```python
import pyscanbox

config = pyscanbox.config.load_config()
ctrl = pyscanbox.hardware.controller.ScanboxController(config.to_dict())
ctrl.open()
ctrl.set_pockels(base=50, active=100)
ctrl.set_shutter(open=True)
ctrl.close()
```

---

For more examples, see the `examples/` directory.
