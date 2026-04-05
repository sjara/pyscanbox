# Focus Stacking (Z-Stacks)

The software provides native support for automated Z-stacks using an **Electrically Tunable Lens (ETL)** (*Optotune*) device without needing to physically translate the sample or objective stages.

## Usage
1. Use the **ETL current** slider to adjust the focal depth manually to the desired top focus plane.
2. Press the **Set** button in the **Top** row to store this value.
3. Use the **ETL current** slider to move to the desired bottom focus plane. 
4. Press the **Set** button in the **Bottom** row to store this value.
5. Configure the total number of `Planes` desired.
6. Configure the number of `Frames/plane` to acquire.
7. Check **Enable volumetric** box to enable volumetric imaging mode.
8. When you press **Focus** or **Grab** in the **Acquisition Control** section of the left panel, the system will sequentially collect `Frames/plane` at each plane, and step the ETL to the next plane. Once all planes are collected, the system will return to the first plane and repeat the process.

## Limitations

The ETL focus-stacking feature is limited by the PSoC5 controller's onboard memory. The key constraint is:

**`Planes × Frames/Plane ≤ 255`**

The hardware maintains a lookup table of 255 entries maximum. Each entry holds for one frame, so to acquire multiple frames at each plane, the same focal position must be repeated in the table.

### Examples:
- **1 Frame/Plane**: Up to 255 unique planes
- **10 Frames/Plane**: Up to 25 planes 
- **50 Frames/Plane**: Up to 5 planes

The GUI automatically enforces this limit by clamping the maximum "Planes" spinbox value when you adjust "Frames/plane".

---

Back to [Table of Contents](index.md).
