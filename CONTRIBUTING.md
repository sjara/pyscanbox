# pyscanbox: Development Guide

## 1. Project Overview & Scope
* **Objective:** Develop a Python software package to collect data using Neurolabware two-photon microscopes, based on the original MATLAB-based Scanbox software (https://scanbox.org/).
* **Project Name:** pyscanbox
* **Target Environment:** Windows OS (to use existing hardware drivers).

### **Original Scanbox System Capabilities**
Reference: https://scanbox.org/2014/03/13/welcome-to-scanbox/
- Two analog and two digital channels sampled at laser frequency (80 MHz) with 16-bit depth
- Control of PMT gains
- Non-uniform spatial sampling correction in real time (raw data streamed to disk)
- Real-time averaging and display of data
- Uniform power density over scan line by Pockels cell modulation
- Control of X, Y, Z stage and tilt angle of objective
- Z-stack data collection
- Movement in rotated coordinate system (keeps x,y plane normal to objective)
- Control of laser parameters (power, shutter, wavelength)
- Two additional TTL signals timestamped with frame and line number
- GigE camera synchronization for eye tracking and ball movement
- Remote control over network
- Motion correction, segmentation, and signal extraction

### **In Scope:** 
  * AlazarTech PMT data acquisition (unidirectional and bidirectional scanning)
  * Knobby motor control (Trinamic motors)
  * Pockels cell control (laser power)
  * External shutter control
  * Epifluorescence / 2P mirror toggling
  * Optotune/ETL control for z-stacks (electrically tunable lens)
  * Bidirectional scan support with pixel shift correction
  * Memory-mapped streaming for real-time data access (advanced feature)
  * TTL events recording
  * Saving data in standard `.sbx` and `.mat` formats
#### **Via Plugins:**
  * Quadrature encoder for rotation platform monitoring
  * Auxiliary cameras (eye/ball/path)
### **Out of Scope:**
  * Laser serial control (use manufacturer software)
  * Optogenetics (SLM, LED)
  * Ephys/external event recording via NI-DAQ
  * Laser automatic gain control

## 2. Development Environment
* **Primary Development OS:** Ubuntu Linux (development is performed mostly on Ubuntu using hardware emulation).
* **Target Deployment OS:** Windows OS (required for actual hardware drivers).
* **Python Virtual Environment Management:** The development Linux system uses `virtualenvwrapper` to manage Python virtual environments. Before running any code, tests, or examples, you must activate the `pyscanbox` virtual environment.
* **Hardware Emulation:** Since the physical hardware (AlazarTech digitizer, Scanbox controller, Trinamic motors) is not accessible during development, all development uses the hardware emulation layer described in Section "Hardware Emulation for Linux/Offline Development" below.
* **Renaming files:** When renaming files, use 'git mv' to keep track of the history.
* **Temporary benchmarks:** Any new files with demonstrations or benchmarks (and associated documentation of these) should be placed in the temporary folder pyscanbox/tmp/ unless we want to explicitly implement that feature in the main code.

## 3. Coding Standards
* **Style Guide:** Strictly follow the Google Python Style Guide.
* **Docstrings:** Use Google-style docstrings for all modules, classes, and functions.
* **Imports:** Import only packages and modules. Do not import individual types, classes, or functions (e.g., use `import serial` and instantiate with `serial.Serial`, do not use `from serial import Serial`).
* **Single Source of Truth:** Every hardware parameter, value range, conversion factor, or lookup table must be defined in exactly one place — always in the lowest-level module that owns the concept (e.g., hardware limits belong in the hardware class, not the GUI). All other code must import and reference that definition. Never duplicate a constant or restate a range in a comment or widget; use the symbol directly. Examples: ETL current limits live in `ScanboxController.ETL_CURRENT_MIN/MAX`; PMT scale factors are module-level constants in `app_controller.py`. Violation of this rule means that changing a hardware parameter requires hunting down multiple copies, which is error-prone.

## 4. Development Phases & Guidelines
* **Phase 1: Core Backend Translation:** Implement the hardware communication and data acquisition logic module-by-module. Implement hardware emulation layer to enable development without physical hardware access. **Write unit tests alongside each module** using the emulator (`mock_serial`, `mock_alazar`, etc) to verify byte-level serial protocols and hardware interactions. All backend modules should have comprehensive test coverage before proceeding to Phase 2.
* **Phase 2: GUI Development:** Build the user interface using **PyQt** and integrate with hardware modules using emulation mode. This allows GUI development to proceed in parallel without waiting for hardware access. Test all GUI functionality using the emulator.
* **Phase 3: Hardware-in-the-Loop (HIL) Testing:** Validate all backend modules and GUI functionality on the actual Windows rig with physical hardware. Replace emulation with real hardware drivers and verify that byte-level protocols work correctly with actual devices. Test performance benchmarks and identify any hardware-specific issues.
* **Phase 4: Integration and Optimization:** Once hardware validation is complete, perform full system integration testing, optimize performance on actual hardware, and conduct long-duration stability testing.
* **Phase 5: Plugins:** Develop plugins for additional functionality.

## 5. Reference File Mapping

When translating logic, refer to these specific files in the original codebase. For example, the main acquisition loop is in `core/scanbox.m` and the high-speed reshaping is in `core/alazarReshapeCData2.c`, while the Alazar configuration is in `core/configureLsb9440.m` and `core/scanbox.m` (lines 743-893).


## 6. Architectural Constraints & Bottlenecks
* **The GIL & High-Speed Data:** The system handles a ~500 MB/s continuous data stream (125 MS/s, 14-bit, 2-channel) from the Alazar card. Standard Python `for` loops will drop frames.
* **Data Reshaping:** The interleaved 16-bit PMT data unpacking must be written using compiled code (e.g., Numba `@njit`, Cython, or C++ extensions via Pybind11) to match the speed of the original MATLAB MEX files.
* **Memory Management:** You must use pinned (page-locked) memory (e.g., via `ctypes`) for Alazar DMA transfers to prevent Python's garbage collector from moving arrays during hardware interrupts.

## 7. Hardware Interfacing & Protocols

For complete protocol specifications, see the [docs/hardware_protocols/](docs/hardware_protocols/) directory.

* **Main Scanbox Controller:** 3-byte serial packets at 1 Mbaud. Use `pyserial`. See [docs/hardware_protocols/scanbox_controller.md](docs/hardware_protocols/scanbox_controller.md).

* **Motor Control & Knobby:** 9-byte TMCL packets at 57600 baud. Use `pyserial` directly and run a dedicated background polling thread. In the original MATLAB implementation, MATLAB could not own the serial port itself, so it launched a Python subprocess (`scanknob/scanknob.py`) and communicated with it via two **memory-mapped files**: `scanknob.pos` (motor positions) and `scanknob.cmd` (commands), with a busy-wait flag handshake. In pyscanbox this entire IPC layer is eliminated — Python owns the serial port directly. See [docs/hardware_protocols/trinamic_motor.md](docs/hardware_protocols/trinamic_motor.md) and [docs/hardware_protocols/knobby.md](docs/hardware_protocols/knobby.md).

* **AlazarTech Digitizer:** Use the wrapper provided by the `atsbindings` package. **External clock comes from the laser sync-out (~80 MHz), not the internal clock**; using the wrong clock source causes beat-pattern artifacts. The line trigger is sent by the Scanbox controller card. See [docs/hardware_protocols/alazar_digitizer.md](docs/hardware_protocols/alazar_digitizer.md).

## 8. Data Output Specification (.sbx format)
* **Binary Dump (`.sbx`):** Write the raw, reshaped `uint16` arrays directly to a headerless binary file (e.g., using `buffer.tofile()`), exactly as MATLAB's `fwrite` does. 
* **Metadata (`.mat`):** Save the acquisition parameters and configuration dictionary at the end of the run using `scipy.io.savemat` to create a `.mat` file with the exact same base name. This guarantees backwards compatibility with existing lab processing pipelines like Suite2p.

## 9. Hardware Command Logging

Every hardware class that sends commands (serial or API-level) must support an optional `on_command` callback so the GUI log, tests, and debug tools can observe traffic without subclassing or monkey-patching.

### 9.1 Pattern

1. **`__init__` accepts `on_command=None`.**  Store it as `self.on_command`.
2. **The lowest-level send method fires the callback** immediately after the real write, passing the raw values (port, command ID, parameters).  This guarantees the logged data is always identical to what was transmitted — there is no separate copy of the byte values at higher layers.
3. **A `format_command(...)` static method** on the hardware class translates raw bytes/values into a human-readable call string (e.g. `set_pockels(base=0, active=100)`).  This is the *single source of truth* for decoding: arguments names, value interpretations, and edge cases all live here and nowhere else.
4. **Adapters at higher layers** (e.g. `Scanner._on_controller_cmd`, `AppController._on_controller_cmd`) call `format_command()` and forward `(direction, func_call, packet_str)` to the GUI log signal.  They never hardcode byte strings.

### 9.2 Callback signature

```python
on_command(port: str, cmd_id: int, param1, param2) -> None
```

Adjust the parameter list to match the device protocol (e.g. a single `value` for the Alazar API, a `(node, cmd, type, motor, value)` tuple for TMCL).

### 9.3 Log entry format

All log helpers accept three arguments and compose the displayed string in one place:

```python
_log_cmd(direction, func_call, packet_str)
# renders as:
# [HH:MM:SS.mmm]  PC → Controller (COM3)  set_pockels(base=0, active=100): [08 00 64]
```

* `direction` — short label including the port, e.g. `'PC → Controller (COM3)'`
* `func_call` — output of `format_command(...)`, e.g. `'set_pockels(base=0, active=100)'`
* `packet_str` — hex representation of the raw packet, e.g. `'[08 00 64]'`

### 9.4 Reference implementation

See `pyscanbox/hardware/controller.py` (`ScanboxController`) for the complete reference:
* `on_command` parameter in `__init__`
* callback fired in `_send_command` after `port.write()`
* `CMD_NAMES` dict and `format_command()` static method decoding all four commands

### 9.5 Applicability

Apply this pattern to every hardware class that sends commands to a device — serial or API-level.  Any class that has a low-level send method (e.g. `_send_command`, `_send_packet`, or a direct `port.write`) should accept `on_command=None` and fire the callback there.

## 10. Hardware Emulation for Linux/Offline Development
Because the physical hardware is not accessible during development, we built a lightweight software emulator. We do not need to build a full-fidelity hardware simulator; focus on a "mock interface" that prevents the software from crashing and generates synthetic data.

### 10.1 Mocking Serial Connections (Scanbox Box & Knobby)
Create a dummy class to replace `serial.Serial` when running in emulation mode. 
* **State Tracking (Scanbox):** When the application sends a 3-byte array (e.g., `[8, 10, 85]` for the Pockels cell), the mock class should not throw an error. Instead, it should parse the command and update an internal state dictionary (`self.state['pockels'] = (10, 85)`). 
* **Polling Loop (Knobby):** The Trinamic motor controller requires constant polling. The mock serial class must intercept the 9-byte Trinamic Motion Control Language (TMCL) queries and immediately return a valid 9-byte TMCL acknowledgment array so the background polling thread does not freeze or timeout.

### 10.2 Mocking the AlazarTech Digitizer (High-Speed Data)
Create a dummy Python class that mirrors the methods of the `atsbindings` wrapper. 
* **Synthetic Data Generation:** Instead of reading from a PCIe bus, the mock `AlazarWaitAsyncBufferComplete` method should yield NumPy arrays populated with random 14-bit integers (e.g., `np.random.randint(0, 16384, size=...)`) to simulate PMT noise.
* **Stress Testing:** Use this synthetic data stream to stress-test the Linux development environment. Verify that:
  1. The C++/Cython/Numba reshaping functions can process the simulated 500 MB/s data rate.
  2. The `.sbx` binary disk writing logic can keep up with the data stream without dropping frames.
  3. The PyQt GUI remains responsive while the mock acquisition loop runs in the background.
