# Hardware Setup Guide

## Overview

This guide covers the hardware setup and connections for the pyscanbox system.

## Hardware Components

### 1. AlazarTech ATS9440 Digitizer
- **Purpose:** High-speed PMT data acquisition
- **Connection:** PCIe card
- **Data Rate:** 125 MS/s, 14-bit, 2-channel
- **Throughput:** ~500 MB/s

**Setup:**
1. Install ATS9440 card in PCIe slot
2. Install AlazarTech SDK and drivers
3. Verify installation with AlazarTech test utilities
4. Configure LSB outputs for frame/line sync

### 2. Main Scanbox Controller (Arduino)
- **Purpose:** Pockels cell, shutter, and mirror control
- **Connection:** USB serial (COM port)
- **Baud Rate:** 1,000,000 baud
- **Protocol:** 3-byte command packets

**Setup:**
1. Connect Arduino via USB
2. Note COM port in Device Manager (e.g., COM3)
3. Update config.yaml with correct COM port
4. Test connection with controller example

**Pinout:**
- Pockels cell control: Digital PWM output
- Shutter control: Digital output
- Mirror control: Firgelli actuator output

### 3. Trinamic Motor Controller
- **Purpose:** Focus motor and positioning control
- **Connection:** USB serial (COM port)
- **Baud Rate:** 57,600 baud
- **Protocol:** TMCL 9-byte packets

**Setup:**
1. Connect Trinamic board via USB
2. Note COM port in Device Manager (e.g., COM4)
3. Update config.yaml with correct COM port
4. Test motors with motor control example

**Motor Configuration:**
- Motor 0: Focus Z-axis
- Motor 1: X-axis positioning
- Motor 2: Y-axis positioning
- Motor 3: Reserved/auxiliary

## Software Requirements

### Windows OS
- **Required:** Windows 10 or later (64-bit)
- **Reason:** Hardware drivers require Windows

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
python examples/test_controller.py
```

Test motors:
```bash
python examples/motor_control.py
```

### 4. Verify Alazar Connection

Run Alazar test (when implemented):
```bash
python examples/test_alazar.py
```

## Troubleshooting

### COM Port Not Found
- Check Device Manager
- Verify USB cable connection
- Try different USB port
- Update drivers

### Alazar Not Detected
- Verify PCIe card is seated properly
- Check BIOS for PCIe configuration
- Reinstall AlazarTech SDK
- Run AlazarTech diagnostic tools

### Motor Not Responding
- Check baud rate (57600)
- Verify TMCL checksum
- Test with Trinamic software
- Check power supply to motors

### High-Speed Acquisition Fails
- Verify PCIe lane configuration (x8 or x16 recommended)
- Check for other PCIe bandwidth users
- Disable power saving on PCIe
- Update AlazarTech firmware

## Performance Optimization

### Windows Settings
1. Disable Windows Update during acquisition
2. Disable antivirus real-time scanning on data directory
3. Use high-performance power plan
4. Disable network adapters during acquisition

### PCIe Optimization
1. Use PCIe x8 or x16 slot
2. Do not share lanes with other high-bandwidth devices
3. Check PCIe link speed in Device Manager
4. Consider PCIe 3.0 or later motherboard

### Storage
1. Use dedicated SSD for data (not system drive)
2. NVMe SSD recommended for 500 MB/s sustained write
3. Ensure sufficient free space (200+ GB recommended)
4. Avoid RAID configurations with high overhead

## Safety

### Laser Safety
- Always verify shutter closes properly
- Test emergency stop procedures
- Post laser safety warnings
- Use appropriate laser safety glasses

### Motor Safety
- Test motor limits before unattended operation
- Implement soft limits in software
- Add emergency stop button
- Keep clear of moving parts

## Next Steps

After hardware setup:
1. Run basic scan example
2. Verify data integrity
3. Calibrate Pockels cell power
4. Adjust motor speeds and limits
5. Perform test acquisitions

For support, see project documentation or contact maintainers.
