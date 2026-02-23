# Integration Tests

This directory contains integration tests that verify complete workflows across multiple components.

Unlike unit tests, these tests:
- Test multiple components working together
- May take longer to run
- Use emulation mode (no hardware required)
- Are **not** run automatically during CI

## Running Integration Tests

```bash
# Run all integration tests
python -m pytest tests/integration/ -v

# Run specific integration test
python tests/integration/test_alazar_integration.py
```

## Available Tests

### test_alazar_integration.py
Complete Alazar acquisition pipeline test with emulated hardware.

Tests:
- Basic acquisition workflow (open → configure → allocate → start → read → stop → close)
- Error condition handling
- Performance validation (83.5 MB/s demonstrated)

**When to run:**
- After changes to Alazar hardware integration
- Before hardware-in-the-loop testing
- To validate emulation system
