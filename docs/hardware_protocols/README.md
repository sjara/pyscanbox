# Hardware Communication Protocols

Low-level protocol specifications for Scanbox hardware components.

## Protocol Documentation

This directory contains detailed protocol specifications for each hardware device:

- **[Scanbox Controller](scanbox_controller.md)** - PSoC 5LP controller for scan control, Pockels cell, shutter, and PMT gain
- **[Trinamic Motor](trinamic_motor.md)** - TMCL protocol for focus motor positioning
- **[Knobby Controller](knobby.md)** - Physical knob interface and position reporting
- **[AlazarTech Digitizer](alazar_digitizer.md)** - ATS9440 high-speed PMT data acquisition
- **[Quadrature Encoder](quadrature_encoder.md)** - Arduino-based rotary encoder reader for running wheel / rotating platform

## Quick Reference

### Communication Parameters

| Device | Baud Rate | Protocol | Port Type |
|--------|-----------|----------|-----------|
| Scanbox Controller | 1,000,000 | 3-byte commands | Serial |
| Trinamic Motor | 57,600 | 9-byte TMCL | Serial |
| Knobby Controller | 57,600 | 5-byte/9-byte packets | Serial |
| AlazarTech Digitizer | N/A | C API | PCIe |
| Quadrature Encoder (DUE) | 115,200 | Binary command/response | Serial |
| Quadrature Encoder (Mega) | 1,000,000 | Binary command/response | Serial |

### Example Implementations

- **Python:** `pyscanbox/hardware/`
  - `controller.py` - Scanbox controller
  - `motor.py` - Trinamic motor
  - `knobby.py` - Knobby controller
  - `alazar.py` - AlazarTech digitizer

- **Examples:** `examples/`
  - `check_controller.py` - Controller connection check with emulation support
  - `check_motor.py` - Motor connection check and control examples (with emulation support)
  - `check_knobby_motor.py` - Knobby connection and motor control check
  - `check_alazar.py` - Digitizer connection check with emulation support

### Original MATLAB References

- **Scanbox Controller:** `Scanbox/sb/*.m`
- **Trinamic Motor:** `Scanbox/trinamic/*.m`
- **Knobby Controller:** `Scanbox/scanknob/knobby2.ino`
- **AlazarTech Digitizer:** `Scanbox/core/scanbox.m`, `Scanbox/alazartech/*.m`
