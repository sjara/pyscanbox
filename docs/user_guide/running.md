# Getting Started & Emulation

## Starting the Software
To launch the `pyscanbox` application, first activate the environment:

```bash
conda activate pyscanbox
```

then execute the main entry point from your terminal.

```bash
pyscanbox
```

Alternatively, you can provide a specific YAML configuration file:
```bash
pyscanbox --config path/to/my_config.yaml
```

If you encounter errors or need more verbose logging for troubleshooting hardware connections, run with the `--verbose` flag:
```bash
pyscanbox --verbose
```

## Emulation Mode
If you are running the software on a development machine without physical access to the microscope hardware (like an AlazarTech digitizer, Trinamic motors, or the Scanbox controller), you can launch the software in **Emulation Mode**.

```bash
pyscanbox --emulation
```

This mode uses software mocks for the serial connections and digitizer. 
- Focus and Grab acquisitions will function as normal and save output data without requiring physical hardware, the software will generate mock data.
- Emulation is useful for developing new UI capabilities, testing offline, and getting familiar with the controls prior to a real imaging session.

---

Back to [Table of Contents](index.md).

