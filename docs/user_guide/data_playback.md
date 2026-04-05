# Reviewing Acquired Data

Apart from live hardware acquisition, `pyscanbox` allows operators to open previously collected `.sbx` / `.mat` file pairs for data playback, enabling rapid reviewing of experimental footage without utilizing third party visualization programs. 

## Loading Files via the File Menu
Navigate to **File -> Open Data...** and target an `.sbx` binary container in your system utilizing the browser overlay. The accompanying `.mat` configuration matrix from your identical imaging run will naturally be paired in memory. This converts the display to playback mode.

## The Frame Selector 
When data is loaded successfully, the **Frame Selector Widget** will appear dynamically (it can also be toggled explicitly from the **View** menu). It acts as a timeline transport bar, allowing scrub mechanics:
- Drag the slider right and left through the frames axis.
- The displayed image dynamically updates its arrays directly indexing from the raw memory-mapped volume. 

## Interacting with Display Metrics
Because standard displays usually operate on 8-bit dynamic ceilings while Scanbox data operates heavily inside dense 16/14-bit arrays, features appearing dark due to scaling mismatches can be highlighted manually: 
1. Move the *Display Gains* (found under the Image Display Controls widget cluster) slider upwards, enforcing immediate luminance thresholds applied exclusively over the rendering path. It will NOT alter the core array data itself. 
2. Adjusting the viewing Channel will likewise filter data playback dynamically matching user specifications. 
