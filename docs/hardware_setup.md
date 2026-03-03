# Hardware Setup Guide

## Overview

This guide covers basic hardware installation and configuration for the pyscanbox system. For detailed technical information about specific components, see:

- **AlazarTech Digitizer:** [alazar_digitizer.md](alazar_digitizer.md) - Clock configuration, LSB outputs, troubleshooting
- **Knobby Controller:** [knobby_architecture.md](knobby_architecture.md) - Motor control architecture
- **Communication Protocols:** [../devel/hardware_protocols.md](../devel/hardware_protocols.md) - Low-level protocol details

## Hardware Components

### 1. AlazarTech ATS9440 Digitizer

- **Purpose:** High-speed PMT data acquisition
- **Connection:** PCIe x8 card
- **Data Rate:** 125 MS/s, 14-bit, 2-channel
- **Throughput:** ~500 MB/s
- **Sampling:** Two analog and two digital channels sampled at laser frequency (80 MHz) with 16-bit depth **[Reference: https://scanbox.org/2014/03/13/welcome-to-scanbox/]**

**Quick Setup:**
1. Install ATS9440 card in PCIe x8 or x16 slot
2. Install AlazarTech SDK and drivers
3. Connect external clock from laser sync-out (~80 MHz) via BBP-70+ band-pass filter ([source](https://scanbox.org/2014/03/18/synchronize-to-the-laser/))
4. Connect trigger from Scanbox controller SAMPLE TRIGGER output and AUX inputs for frame/line sync
5. Verify installation with AlazarTech test utilities

**⚠️ Important:** The ATS9440 uses **external clock from the laser sync-out**, not the internal clock. See [alazar_digitizer.md](alazar_digitizer.md) for critical configuration details.

### 2. Main Scanbox Controller (PSoC 5LP)

- **Purpose:** Pockels cell, shutter, and mirror control
- **Connection:** USB serial (COM port)
- **Baud Rate:** 1,000,000 baud (1 Mbaud)
- **Hardware:** Custom PSoC 5LP 32-bit ARM-based processor card (Cypress) **[Reference: https://scanbox.org/2014/03/13/welcome-to-scanbox/]**
  - Generates scan signals
  - Generates trigger signals for cameras
  - Timestamps external TTL events
  - Communicates via USB serial line

**Quick Setup:**
1. Connect controller via USB
2. Note COM port in Device Manager (e.g., COM3)
3. Update config.yaml with correct COM port
4. Check connection with `examples/check_controller.py`

**For protocol details:** See [hardware_protocols.md](../devel/hardware_protocols.md#scanbox-controller-protocol)

### 3. Trinamic Motor Controller

- **Purpose:** Focus motor and positioning control
- **Connection:** USB serial (COM port)
- **Baud Rate:** 57,600 baud

**Quick Setup:**
1. Connect Trinamic board via USB
2. Note COM port in Device Manager (e.g., COM4)
3. Update config.yaml with correct COM port
4. Check motors with `examples/check_motor.py`

**For protocol details:** See [hardware_protocols.md](../devel/hardware_protocols.md#trinamic-tmcl-protocol)

## Physical Connections

### Scanbox Controller Box

The Scanbox controller box has multiple front panel connectors that interface with various hardware components.

#### Front Panel Ports

**Multipin Connectors:**
- **RESONANT SCANNER:** Connection to resonant scanner hardware **⚠️ UNCONFIRMED: likely carries drive signals to the scanner and sync signal back; does NOT provide the Alazar external clock (that comes from the laser sync-out)**
- **SERVO:** Dual connectors (one multipin, one additional) **⚠️ UNCONFIRMED: purpose not verified**
- **FIRGELLI MIRROR:** Controls the Firgelli linear actuator that switches between 2P and epifluorescence paths
- **PHOTOMULTIPLIER TUBES:** Two separate Phoenix-style connectors **⚠️ UNCONFIRMED: may be for power only, signal path not verified**

**SMA Connectors:**
- **CURRENT SOURCE:** Connected **⚠️ UNCONFIRMED: purpose not verified**
- **TTL1:** Connected **⚠️ UNCONFIRMED: purpose not verified**
- **TTL0:** (not connected)
- **POCKELS CELL:** Connected **⚠️ UNCONFIRMED: controls laser power via Pockels cell - not verified**
- **SAMPLE TRIGGER:** Timing signal for data acquisition (connected to AlazarTech digitizer TRIG IN)
- **LASER SHUTTER:** Connected to external ThorLabs shutter in laser path
- **CAMERA TRIG1:** (not connected)
- **CAMERA TRIG0:** Connected **⚠️ UNCONFIRMED: purpose not verified**

**Other Connectors:**
- **I2C BUS:** I2C communication bus (typically not connected)

#### Critical Connections for Two-Photon Imaging

1. **SAMPLE TRIGGER** → AlazarTech digitizer **TRIG IN**
2. **LASER SHUTTER** → External ThorLabs shutter in laser path
   *(On this rig the shutter opens in response to Scan Control (CMD 4),
   not the dedicated Shutter command (CMD 16). See
   [scanbox_controller.md](../devel/protocols/scanbox_controller.md#shutter-control-id-16)
   for details.)*

**⚠️ UNCONFIRMED - Typical connections (to be verified):**
- **POCKELS CELL** → **Conoptics 302RM** Pockels cell driver — confirmed connected
  - Input signal: **0–2 V, unipolar positive** (set the driver to "unipolar positive input signal" mode)
  - Software bytes 0–255 map to this voltage range via the PSoC5 controller
  - ⚠️ Output not yet measured; plan: use power meter to measure laser power after Pockels cell at several command values to calibrate the byte→power relationship
- **FIRGELLI MIRROR** → Mirror actuator
- **PHOTOMULTIPLIER TUBES** → PMT amplifier outputs or power supply (signal path unknown)
- **TTL1** → External stimulus/trigger systems
- **CAMERA TRIG0/1** → Camera triggers

### AlazarTech Digitizer Connections

See [alazar_digitizer.md](alazar_digitizer.md#signal-connections) for complete digitizer connection details.

**Summary of connections:**
- **ECLK (External Clock):** Connected to laser
- **Channel A:** Connected **⚠️ UNCONFIRMED: signal source unknown - may be direct from PMT or via controller box**
- **Channel B:** Connected **⚠️ UNCONFIRMED: signal source unknown - may be direct from PMT or via controller box**
- **TRIG IN:** Connected to **SAMPLE TRIGGER** from Scanbox controller box
- **AUX 0:** Connected to stimulus presentation system **⚠️ UNCONFIRMED: default behavior as TRIG OUT not verified**
- **AUX 1:** Not connected

## Software Requirements

### Windows OS
- **Required:** Windows 10 or later (64-bit)
- **Reason:** The physical hardware rig runs Windows; deployment and HIL testing require a Windows machine

### Python Environment
- **Version:** Python 3.8 or later
- **Recommended:** Python 3.10 or 3.11

### AlazarTech SDK
- Download from AlazarTech website
- Install SDK before running pyscanbox
- Verify atsapi.py is accessible

## Installation Steps

### 1. Install Python Dependencies

```bash
cd pyscanbox
pip install -e .
```

### 2. Configure COM Ports

Edit `config.yaml`:

```yaml
controller:
  com_port: COM3  # Update with your port

motor:
  com_port: COM4  # Update with your port
```

### 3. Test Hardware Connections

Test controller:
```bash
python examples/check_controller.py
```

Test motors:
```bash
python examples/check_motor.py
```

### 4. Verify Alazar Connection

Run Alazar test (when implemented):
```bash
python examples/check_alazar.py
```

## Troubleshooting

### COM Port Not Found
- Check Device Manager
- Verify USB cable connection
- Try different USB port
- Update drivers

### Alazar Not Detected
See detailed troubleshooting in [alazar_digitizer.md](alazar_digitizer.md#common-issues-and-troubleshooting)

### Motor Not Responding
- Check baud rate (57600)
- Verify TMCL checksum calculation
- Test with Trinamic software
- Check power supply to motors
- See [hardware_protocols.md](../devel/hardware_protocols.md#trinamic-tmcl-protocol) for protocol details

### Configuration Errors
See [alazar_digitizer.md](alazar_digitizer.md#apiinvaliddata-error) for AlazarTech-specific errors

## Performance Optimization

For detailed performance tuning, see [alazar_digitizer.md](alazar_digitizer.md#performance-optimization)

**Key recommendations:**
- Use PCIe x8 or x16 slot (not x4)
- Disable Windows Update during acquisition
- Use NVMe SSD for data storage
- Disable power saving on PCIe
- Close unnecessary applications

## Next Steps

After hardware setup:
1. Run basic scan example
2. Verify data integrity
3. Calibrate Pockels cell power
4. Adjust motor speeds and limits
5. Perform test acquisitions

## Additional Documentation

- **AlazarTech Details:** [alazar_digitizer.md](alazar_digitizer.md)
- **Knobby Architecture:** [knobby_architecture.md](knobby_architecture.md)
- **Communication Protocols:** [../devel/hardware_protocols.md](../devel/hardware_protocols.md)
- **API Reference:** [api_reference.md](api_reference.md)

For support, see project documentation or contact maintainers.
