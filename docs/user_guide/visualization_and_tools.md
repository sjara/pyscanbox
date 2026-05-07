# Visualization and Tools (Right Panel)

The right panel is devoted predominantly to displaying the collected data and providing positioning contexts.

## Image Display Canvas
The central visual element of `pyscanbox` is the *Image Display Canvas*, where active streams, whether via **Focus**, **Grab**, or offline data playback are shown in real-time.
- *Zoom*: You can adjust the zoom with the mouse wheel. The bottom right corner of the image canvas displays the current zoom level.
- *Pan*: You can adjust the pan with the left mouse button and dragging.
- *Context menu*: Right click on the image to open the context menu. This will allow you to set different zoom levels and clear markers from the image.
- *Markers*: 
  - You can activate this mode by left clicking on the *[+]* icon in the top-right corner of the image canvas.
  - You can also temporarily activate this mode by holding the Shift key.
  - After activating, you can add a marker by left clicking on the image canvas. 
  - To disable this mode, click the *[+]* icon again (or press 'Esc').
  - To clear all markers, right click on the image canvas and select "Clear markers".

## Save Channels
This widget allows selecting what data streams are saved.
- *PMT*: Select which channel(s) to save — **PMT0**, **PMT1**, or **PMT0 & PMT1** (both). By default, the state of this combobox changes when changing the channel in the *Image Display* widget, but you can also set it independently.
- *TTL*: Toggle buttons to enable or disable recording of TTL input signals. The initial state is seeded from `interrupt_mask` in the config file.

## Objective Position
This widget displays the current position of the objective using information from the Knobby hardware.
- *Angle*: This value matches the angle displayed in Knobby.
- *Rotate to 0°*: When clicked, this button will physically rotate the objective to 0 degrees. This is a dangerous operation is your objective is close to the sample, so a warning will pop up for you to confirm the action.
- *Tip fixed* (experimental): When active, the system will attempt to keep the tip of the objective at the same position while rotating the objective. Because each motor runs at a different speed, the tip will not be perfectly fixed at the same position while rotating the objective.
- *Knobby (µm)*: Position of the objective in µm, as reported by Knobby (relative to the last time the position was zeroed). This position is always with respect to the horizontal plane, even when Knobby is in `Rotated` mode.
- *Abs (µm)*: Absolute position of the objective in µm, as reported by the motor controller.
- *Rotated (µm)*: Position of the objective in µm, relative to the objective axis, estimated from the angle and the Knobby position. Make sure you enable `Rotated` in Knobby for the Z-axis knob to move the objective in the direction of the objective axis.

## Image Display (settings)
The settings in this widget do not affect the saved data.
- *Channel*: Switch between visualizing the data from PMT0, or PMT1, or an overlay of PMT0 & PMT1, or a side-by-side view (PMT0 | PMT1).
- *Gain*: Slider to set the gain of the displayed image. Use the button `Reset` to set it back to 1.0x.
- *Rolling avg*: Enables averaging adjacent historical frames to reduce noise. It uses exponential averaging with the decay factor specified by tau. Useful for reducing noise in fast scans.

## Optotune/Volumetric
For details on how to use the Optotune/Volumetric controls, see the [Volumetric imaging/Z-stacks](volumetric_imaging.md).

---

Back to [Table of Contents](index.md).

