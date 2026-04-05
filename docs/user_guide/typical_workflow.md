# Typical Session Workflow

This document outlines the standard high-level flow for a typical two-photon imaging session using **pyscanbox**. It assumes you are already familiar with the [main interface](main_interface.md). Subsequent sections of this User Guide describe each of the panels in mode detail.

1. **Power on the laser**:
   Using the laser software (separate from *pyscanbox*), make sure the laser is powered on that it has reached the *pulsing* state.

2. **Start pyscanbox**:
   Start the software. Once the graphical interface is up, it should show messages indicating connections to Knobby, the motor controller, and the Scanbox controller box.

3. **Select Light Path**:
   In the left panel under **Light Path**, click on **Epi** to enable the epifluorescence/widefield camera path. 

4. **Find Region of Interest**:
   In *Epi* mode, use your camera software to find the region of interest by moving the 
   objective position using the Knobby hardware.
   
5. **Switch to Two-Photon Mode**:
   In the **Light Path** section, click on **2P** to switch the mirror to the two-photon imaging path.

6. **Start Scanning**:
   Press *Focus* in the **Acquisition Controls** panel. The software will show a live stream on the right display panel so you can navigate across the sample. At this point it will look all dark until you increase the PMT gain and Laser power. 
   
7. **Set PMT Gain and Laser Power Levels**:
   From the **PMT Control**, increase the gain of the PMT associated with the wavelength of your signal (e.g., PMT0 for green) and adjust the laser power by increasing the *Power (Pockels)* in the **Laser** panel. You can open the *Histogram* from the *View* menu to monitor the signal intensity.

8. **Adjust Focal Plane (Z)**:
   Adjust the Z position of the objective to fine-tune your focus. Once you reach the intended focus plane, click **Stop** (same button as *Focus*) to stop the scanning.

9. **Set the File Saving Path**:
   Under **File Storage**, ensure that the output *Directory* and *Subject* are set
   correctly.
   
10. **Set the Number of Frames**:
   Under **Scanner**, set the total number of frames to record.

11. **Record Data**:
   Press the **Grab** button. This will record the imaging data continuously into `.sbx` format in the specified directory until the frame limit is achieved. The software will also save the metadata in `.mat` format in the same directory. Acquisition will stop automatically, but you can also stop the recording by pressing **Abort**. 

12. **Review the Data**:
   You can review your acquired frames using the *File -> Open Data* playback capability. Once the data is loaded, you can navigate through the frames using the slider that appears at the bottom of the display panel.

13. **Close the Session**:
   You can close the session by selecting *File -> Exit*, or by simply closing the main window. This will also disconnect all hardware.

---

Back to [Table of Contents](index.md).
