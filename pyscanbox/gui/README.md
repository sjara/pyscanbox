# pyscanbox GUI Module

This module provides the PyQt6-based graphical user interface for the pyscanbox two-photon microscope control system.

## Overview

The GUI follows a two-panel layout as specified in `GUI_SPECIFICATION.md`:

- **Left Panel**: Primary hardware and acquisition controls
- **Right Panel**: Image display and secondary controls

## Architecture

### Main Components

- **`main_window.py`**: Contains the `MainWindow` class (QMainWindow)
  - Menu bar (File, Hardware, View, Help)
  - Status bar
  - Main splitter layout

- **`panels.py`**: Contains the major panel layouts
  - `LeftControlPanel`: Primary controls panel
  - `RightDisplayPanel`: Image display and secondary controls

- **`widgets.py`**: Contains individual control groups
  - `LaserControlGroup`: Laser power, shutter, wavelength
  - `ScannerControlGroup`: Scanner parameters
  - `PositionDisplayGroup`: Position coordinates
  - `AcquisitionControlGroup`: Acquisition buttons and status
  - `FileStorageGroup`: File path and metadata
  - `ImageDisplayWidget`: Main image display (QGraphicsView)
  - `CameraPathGroup`: Camera controls
  - `PMTControlGroup`: PMT gain controls
  - `ImageDisplayControlGroup`: Display settings
  - `OptotuneGroup`: ETL control

## Usage

### Launching the GUI

```python
import sys
from PyQt6.QtWidgets import QApplication
from pyscanbox.gui import MainWindow

app = QApplication(sys.argv)
window = MainWindow()
window.show()
sys.exit(app.exec())
```

Or use the provided example:

```bash
python examples/gui_example.py
```

### With Configuration

```python
from pyscanbox.config import AppConfig
from pyscanbox.gui import MainWindow

config = AppConfig.from_yaml("path/to/config.yaml")
window = MainWindow(config=config)
```

## Current Status

**Phase 3.1 (GUI Framework): ✅ Complete**

All UI components have been implemented according to the specification:
- ✅ Main window with menu system
- ✅ Two-panel splitter layout
- ✅ All left panel control groups
- ✅ Image display area
- ✅ All secondary control groups

**Next Steps (Phase 3.2-3.4):**
- [ ] Connect GUI controls to hardware backend classes
- [ ] Integrate real-time image display with acquisition pipeline
- [ ] Add live update callbacks
- [ ] Implement motor control integration
- [ ] Add keyboard shortcuts for common operations
- [ ] Implement data playback/review mode

## Layout Structure

```
MainWindow
├── MenuBar (File, Hardware, View, Help)
├── CentralWidget
│   └── HorizontalSplitter
│       ├── LeftControlPanel (300-500px width)
│       │   ├── LaserControlGroup
│       │   ├── ScannerControlGroup
│       │   ├── PositionDisplayGroup
│       │   ├── AcquisitionControlGroup
│       │   └── FileStorageGroup
│       └── RightDisplayPanel (remaining width)
│           └── VerticalSplitter
│               ├── ImageDisplayWidget (main area)
│               └── SecondaryControlsPanel
│                   ├── CameraPathGroup
│                   ├── PMTControlGroup
│                   ├── ImageDisplayControlGroup
│                   └── OptotuneGroup
└── StatusBar
```

## Design Principles

1. **Import Style**: Following project guidelines, we import modules, not individual classes:
   ```python
   import PyQt6.QtWidgets as QtWidgets
   # Use: QtWidgets.QPushButton() instead of QPushButton()
   ```

2. **Separation of Concerns**:
   - `main_window.py`: Application-level concerns (menu, status)
   - `panels.py`: High-level layout and panel organization
   - `widgets.py`: Individual control groups and widgets

3. **Docstrings**: All classes and methods use Google-style docstrings

4. **Flexibility**: Layout uses splitters for user-adjustable panel sizes

## Integration Notes

The GUI is currently functional at the UI level. Backend integration will connect:

- Laser controls → `ScanboxController` (Pockels cell, shutter, mirror)
- Scanner controls → `Scanner` acquisition parameters
- Position display → `TrinamicMotor` position feedback
- Acquisition buttons → `Scanner` start/stop methods
- File storage → `SbxWriter` and `MatWriter`
- Image display → Real-time frame data from acquisition pipeline

## Testing

To test GUI layout without hardware:

```bash
# Test imports
python -c "from pyscanbox.gui import MainWindow; print('GUI imports OK')"

# Launch GUI (requires display server)
python examples/gui_example.py
```

Note: Running GUI applications requires an X server or display environment. On Linux, ensure `DISPLAY` environment variable is set.

## Dependencies

- PyQt6 >= 6.0.0 (specified in requirements.txt)
- All other pyscanbox dependencies

## References

- `devel/GUI_SPECIFICATION.md`: Detailed layout specification
- `devel/DEVELOPMENT_GUIDE.md`: Project coding standards
- `devel/MILESTONES.md`: Development progress tracking
