# pyscanbox: PyQt6 GUI Specification

## 1. Overview and Main Layout
The main application window (`QMainWindow`) is divided into a narrow left panel and a wider right panel. This should be implemented using a `QSplitter` (horizontal orientation) to allow the user to adjust the width of the control panel relative to the image display.

## 2. Left Panel (Primary Controls)
This is a semi-fixed-width vertical panel. Use a `QVBoxLayout` containing a series of `QGroupBox` widgets stacked vertically. 

### 2.1 Laser
Use a vertical layout (`QVBoxLayout`) for a simple control panel.
* **Wavelength:** `QLabel` ("Wavelength:") + `QSpinBox` for the wavelength value (680-1100 nm).
* **Power Slider:** A horizontal `QSlider` with label "Power (Pockels)" to control laser power.
* **Power Label:** Display current power percentage below the slider.

### 2.2 Scanner
Use a form layout (`QFormLayout`) or grid layout (`QGridLayout`) for clean label-to-input alignment.
* **Total frames:** `QSpinBox`.
* **Lines/frame:** `QSpinBox`.
* **Magnification:** `QComboBox` populated with ["1.0", "2.0", "3.0", "4.0"].
* **Frame rate:** `QLabel` or read-only `QLineEdit` (if derived), or `QDoubleSpinBox` (if set by user).
* **Scan mode:** `QComboBox` with options "Unidirectional" and "Bidirectional".
* **Bidirectional alignment:** `QSpinBox` with range -100 to 100.

### 2.3 Position
Use a grid layout (`QGridLayout`) to display the coordinates cleanly.
* **Objective angle:** `QLabel` + read-only `QLineEdit` or `QLabel` for the value.
* **World coords:** `QLabel` ("World:") + three read-only `QLineEdit` boxes (x, y, z).
* **Rotated coords:** `QLabel` ("Rotated:") + three read-only `QLineEdit` boxes (x, y, z).

### 2.4 Acquisition Control
Use a vertical layout (`QVBoxLayout`) containing three horizontal sub-layouts (`QHBoxLayout`).
* **Top Row:** `QPushButton` ("Focus") and `QPushButton` ("Grab").
* **Middle Row:** `QLabel` (Frames collected) and `QLabel` (Time recorded). These should update dynamically during acquisition.
* **Bottom Row:** `QPushButton` ("Snapshot") and `QPushButton` ("Load").

### 2.5 File Storage
Use a grid layout (`QGridLayout`).
* **Directory Selection:** `QPushButton` ("Directory") + `QLineEdit` (read-only, showing the path to the output directory).
* **Metadata Fields:** Three `QLabel` + `QLineEdit` pairs for:
  * Subject
  * Date
  * Session ID
* **Channel Selection:** `QLabel` ("Save Channels:") + `QComboBox` populated with ["PMT0", "PMT1", "Both"].

## 3. Right Panel (Display & Secondary Controls)
The wider right panel is subdivided vertically into a top image display area and a bottom control area. Use a `QSplitter` (vertical orientation) or a `QVBoxLayout` with stretch factors to ensure the image display takes up the majority of the vertical space.

### 3.1 Top Panel: Main Image Display
* This area is dedicated to real-time image visualization.
* **Widget Type:** Use `pyqtgraph.ImageView` or a custom `QGraphicsView` for high-performance image rendering.

### 3.2 Bottom Panel: Secondary Controls
This area contains additional hardware and display controls. Arrange these four sections using a horizontal layout (`QHBoxLayout`) so they sit side-by-side as `QGroupBox` widgets beneath the main image.

#### 3.2.1 Camera Path
Use a vertical layout (`QVBoxLayout`).
* **Enable:** `QCheckBox` ("Enable").
* **Exposure:** `QLabel` ("Exposure") + `QSlider` (Horizontal).
* **Properties:** `QPushButton` ("Camera Properties").

#### 3.2.2 PMT Control
Use a form layout (`QFormLayout`) or vertical layout (`QVBoxLayout`).
* **PMT0 Gain:** `QLabel` ("PMT0") + `QSlider` (Horizontal).
* **PMT1 Gain:** `QLabel` ("PMT1") + `QSlider` (Horizontal).

#### 3.2.3 Image Display
Use a form layout (`QFormLayout`) or vertical layout (`QVBoxLayout`).
* **Channel Display:** `QComboBox` populated with ["PMT0", "PMT1", "PMT0/PMT1"].
* **Display Gain:** `QLabel` ("Gain") + `QSlider` (Horizontal) or `QDoubleSpinBox`.

#### 3.2.4 Optotune / Volumetric
Use a horizontal layout (`QHBoxLayout`).
* **ETL Control:** A single `QSlider` (Vertical) for the electrotunable lens value. 
* *(Note: Leave space in this layout or use a flexible grid to accommodate additional volumetric parameters that will be defined later).*


## IMPROVEMENTS

Here is a list of GUI issues we found during development to address at a later point:

- [ ] placeholder for issue
