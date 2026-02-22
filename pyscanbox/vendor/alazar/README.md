# AlazarTech SDK Development Files

## Purpose

This directory holds vendored copies of AlazarTech SDK files for development purposes only.

## Setup

To develop without installing the full AlazarTech SDK:

1. Copy `atsapi.py` from the AlazarTech SDK to this directory
2. The application will automatically use it when the SDK is not system-installed

```bash
# Copy atsapi.py to this directory
cp /path/to/AlazarSDK/atsapi.py pyscanbox/vendor/alazar/
```

## Production vs Development

**Production (Windows with SDK):**
- System-installed `atsapi.py` is used (from SDK installation)
- Vendored copy is ignored

**Development (without SDK):**
- Falls back to vendored `atsapi.py` in this directory
- Allows development without full SDK installation

**Emulation (Linux):**
- Uses `pyscanbox.emulator.mock_alazar`
- No atsapi.py needed

## Import Priority

The import logic in `pyscanbox/hardware/alazar.py`:

1. If emulation mode: use `mock_alazar`
2. Try system-installed `atsapi` (production)
3. Fall back to `pyscanbox.vendor.alazar.atsapi` (development)
4. Raise `ImportError` if none available

## License Note

`atsapi.py` is proprietary AlazarTech SDK code and should not be committed to version control or distributed. It is excluded via `.gitignore`.
