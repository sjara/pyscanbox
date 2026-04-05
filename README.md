# pyscanbox

**pyscanbox** is an application designed to control a [Neurolabware](https://neurolabware.com/) two-photon  microscope. It provides a Python-based alternative to the original MATLAB-based [Scanbox](https://www.scanbox.org/) software.

![pyscanbox GUI](docs/assets/gui_screenshot.png)

The software provides:
- A Qt-based graphical interface with real-time image display and data playback.
- PMT data acquisition via the AlazarTech digitizer (in unidirectional or bidirectional modes).
- Volumetric imaging via Optotune/ETL control for z-stacks.
- Control of the Trinamic motors via the Knobby hardware.
- Pockels cell control with linearization LUT calibration.
- TTL event timestamping (frame and line number).
- Real-time data streaming via a ZeroMQ plugin system (experimental).
- Data saving in `.sbx` and `.mat` formats for compatibility with existing analysis pipelines.
- An emulator to develop and test the software without real hardware.

Running **pyscanbox** with real hardware has only been tested on **Windows** (using the AlazarTech and Trinamic drivers). In emulation mode, however, the software runs on **Windows, macOS, or Linux** (in fact, the software was developed mostly on Ubuntu Linux). The emulation mode allows data playback on any of these platforms.

## User Guide
See the [User Guide](docs/user_guide/index.md) for how to install and use the software.

## Contributing
Contributions to the project are welcome. If you encounter an issue, or want to contribute code, please open an issue or submit a pull request.

## License
This software is open-source, licensed under the GNU General Public License v3.0 or later. See [LICENSE](LICENSE).

## Authors
Santiago Jaramillo (https://jaralab.uoregon.edu/)

## Acknowledgments
Several features of this software were inspired by the original MATLAB-based [Scanbox](https://www.scanbox.org/) system by Dario Ringach.<br>
The software relies on the [atsbindings](https://github.com/tweber225/atsbindings) library by Tim Weber for interacting with the AlazarTech board.
