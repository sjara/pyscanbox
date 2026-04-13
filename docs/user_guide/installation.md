# Installation

## Installation on Windows (if the hardware is available)
The target deployment environment for actual microscope hardware is Windows, as
this is currently required for the  hardware drivers. This installation assumes
you already have Scanbox working on your computer and that drivers for the
Alazar card and other devices are already installed.

1. Install [git](https://git-scm.com/downloads) (if not already installed).
2. If Scanbox already runs in your computer, you likely already have Python
   installed via [Anaconda](https://www.anaconda.com/download). If not, install
   [Miniforge](https://docs.conda.io/en/latest/miniconda.html) (a lightweight
   version of Anaconda).
3. In an Anaconda Power Shell, create the environment with a specific Python version:
   ```bash
   conda create -n pyscanbox python=3.12 
   ```
4. Activate the environment:
   ```bash
   conda activate pyscanbox
   ```
5. Clone the repository:
   ```bash
   git clone https://github.com/sjara/pyscanbox.git
   ```
6. Navigate to the `pyscanbox` directory:
   ```bash
   cd pyscanbox
   ```
7. Install `pyscanbox`:
   ```bash
   pip install .
   ```
8. Create a folder for your configuration file:
   ```bash
   mkdir C:\ProgramData\pyscanbox
   ```
9. Create your configuration file, by copying the template from the repository
   root and placing it in the appropriate location:
   ```bash
   copy config_template.yaml C:\ProgramData\pyscanbox\config.yaml
   ```
10. Edit the configuration file you created (`config.yaml`) to match your
    hardware setup (COM ports, scan parameters, etc.).
11. Run the application (for details, see [Running pyscanbox](running.md)):
    ```bash
    pyscanbox
    ```

## Installation for Emulation mode
The emulation mode works on Linux or Windows. This mode can be used for
development or if the physical hardware is not available. The installation steps
are the same as above, the only difference is you run the application (see
[Running pyscanbox](running.md) for more details):
   ```bash
   pyscanbox --emulation
   ```
## Installation for Development
For development of `pyscanbox`, it is useful to have additional packages installed.

1. Install Python if necessary.
2. Create and activate the virtual environment `pyscanbox_dev`:
   ```bash
   conda create -n pyscanbox_dev python=3.12
   conda activate pyscanbox_dev
   ```
3. Clone the repository:
   ```bash
   git clone https://github.com/sjara/pyscanbox.git
   ```
4. Navigate to the `pyscanbox` directory:
   ```bash
   cd pyscanbox
   ```
5. Install `pyscanbox` in editable mode with development dependencies:
   ```bash
   pip install -e .[dev]
   ```
6. Create your configuration file by copying the template from the repository
   root and placing it in the appropriate location:
   ```bash
   # Linux/Mac
   mkdir -p ~/.config/pyscanbox
   cp config_template.yaml ~/.config/pyscanbox/config.yaml

   # Windows
   mkdir C:\Users\<username>\AppData\Roaming\pyscanbox
   copy config_template.yaml C:\Users\<username>\AppData\Roaming\pyscanbox\config.yaml
   ```
   Note that on Windows, the config folder can be either in the user's %APPDATA% folder:  `C:\Users\<username>\AppData\Roaming\`, or in `C:\ProgramData\`
   (for system-wide use).
7. Then edit `config.yaml` to match your hardware setup (COM ports, scan parameters, etc.).
8. Run the application in emulation mode first (for details, see [Running pyscanbox](running.md)):
   ```bash
   pyscanbox --emulation
   ```


---

Back to [Table of Contents](index.md).


