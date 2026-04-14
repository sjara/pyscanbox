# Hardware Controls (Left Panel)

The left side of the **pyscanbox** GUI houses the primary hardware and acquisition controls. 

## Light Path
- Use these buttons to switch the microscope between widefield epifluorescence (**Epi**) and two-photon scanning (**2P**) pathways. 

## Laser
- **Wavelength**: set this value if you want it to be saved in the metadata. Note that this value does not change the actual laser wavelength as the laser is not connected to the software.
- **Power slider**: Controls the laser power reaching the sample via the Pockels cell voltage. 

## PMT Control
- **PMT0 Gain**: slider to set the photomultiplier gain for channel 0 (green). Small buttons will set the gain to the specified level (which you can set in the config file).
- **PMT1 Gain**: slider to set the photomultiplier gain for channel 1 (red). Small buttons will set the gain to the specified level (which you can set in the config file).
- **Zero**: Resets the PMT gains to zero.

## Scanner
- **Total frames**: Number of frames to acquire in **Grab** mode. Zero means "infinite" (until stopped manually).
- **Lines/frame**: Number of horizontal lines per frame to collect. Determines how far the galvo scanner moves vertically, since the delta between lines is generally fixed.
- **Magnification**: Select predefined magnification. This changes the extent of the scanners, effectively zooming in and out of the sample.
- **Frame rate**: Estimated frame rate based on the current settings.
- **Scan mode**: Switch between unidirectional or bidirectional scanning. Bidirectional scanning doubles the effective frame rate, but requires alignment (see *Bidir alignment*).
- **Bidir alignment**: Sets the number of pixels to offset even vs odd lines during bidirectional scanning.

## Acquisition Control
- **Focus**: Start streaming data (endlessly) without saving to the disk.
- **Grab**: Start acquiring frames and save them to the disk, halting automatically when the limit set by *Total frames* is reached.

## File Storage
- **Directory**: Base directory for saving files.
- **Subject**: Subject identifier.
- **Date/suffix**: Automatically set date used for the output files. You can modify this or append a suffix for the output files. 
- **Session ID**: A 3-digit number that increments after each recording.
- **Save Channels**: Select which channel(s) to save. 

---

Back to [Table of Contents](index.md).

