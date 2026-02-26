# pyscanbox

Python implementation of Scanbox two-photon microscope software.

## Overview

pyscanbox is a complete rewrite of the MATLAB-based Scanbox system in Python, providing:
- AlazarTech PMT data acquisition at ~500 MB/s
- Knobby motor control (Trinamic motors)
- Pockels cell and laser shutter control
- Data saving in standard `.sbx` and `.mat` formats for compatibility with existing analysis pipelines

## Installation

### Requirements
- Python 3.8 or later
- Windows OS (required for hardware drivers)
- AlazarTech SDK installed 
  https://docs.alazartech.com/ats-sdk-user-guide/latest/getting-started.html

### Install from source

```bash
git clone <repository-url>
cd pyscanbox
pip install -e .
```

For development with GUI support:
```bash
pip install -e .[gui,dev]
```

## Quick Start

```python
import pyscanbox

# Load configuration (searches standard locations automatically)
config = pyscanbox.config.load_config()

# Or specify a custom config file path
# config = pyscanbox.config.load_config('my_config.yaml')

# Initialize hardware
alazar = pyscanbox.hardware.alazar.AlazarDigitizer(config.to_dict())
controller = pyscanbox.hardware.controller.ScanboxController(config.to_dict())

# Run acquisition
scanner = pyscanbox.acquisition.scan.Scanner(config.to_dict(), alazar, controller)
scanner.run()
```

## Configuration

### Creating a Configuration File

Copy the example configuration and customize for your rig:

```bash
# Linux/Mac
mkdir -p ~/.config/pyscanbox
cp examples/config_examples/default_config.yaml ~/.config/pyscanbox/config.yaml

# Windows
mkdir %APPDATA%\pyscanbox
copy examples\config_examples\default_config.yaml %APPDATA%\pyscanbox\config.yaml
```

### Configuration File Locations

pyscanbox searches for configuration files in the following locations:

**Option A: User configuration directory (Recommended)**
- Linux/Mac: `~/.config/pyscanbox/config.yaml`
- Windows: `%APPDATA%\pyscanbox\config.yaml`

**Option B: System-wide configuration (Multi-user systems)**
- Linux: `/etc/pyscanbox/config.yaml`
- Windows: `C:\ProgramData\pyscanbox\config.yaml`


## Project Status

This project is currently in **Phase 1: Core Backend Translation**.

See [MILESTONES.md](devel/MILESTONES.md) for detailed progress tracking.

## Documentation

- [Development Guide](devel/DEVELOPMENT_GUIDE.md) - Comprehensive guide for AI agents and developers
- [Milestones](devel/MILESTONES.md) - Detailed progress tracking and miscellaneous tasks
- [Hardware Setup](docs/hardware_setup.md) - Hardware configuration and connections
- [API Reference](docs/api_reference.md) - Complete API documentation

## Architecture

```
pyscanbox/
├── hardware/      # Hardware interface modules (Alazar, motors, controller)
├── acquisition/   # Data acquisition and processing
├── io/            # File I/O (.sbx and .mat formats)
├── utils/         # Utility functions
└── gui/           # PyQt GUI (Phase 3)
```

## Testing

Run tests with:
```bash
pytest
```

Run tests with coverage:
```bash
pytest --cov=pyscanbox --cov-report=html
```

## Contributing

Please follow the Google Python Style Guide and ensure all code includes proper docstrings.

## License

MIT License

## Authors

- Santiago Jaramillo (sjara@uoregon.edu) - Python implementation

## Acknowledgments

Based on the original MATLAB Scanbox system by Dario Ringach.
