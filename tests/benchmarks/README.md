# Performance Benchmarks

This directory contains performance benchmark scripts for measuring and validating system throughput.

Unlike unit tests, these benchmarks:
- Focus on performance metrics (MB/s, fps, latency)
- Take longer to run (statistical significance)
- Generate detailed performance reports
- Are **not** run automatically during CI

## Running Benchmarks

```bash
# Run reshape performance benchmark
python tests/benchmarks/benchmark_reshape.py
```

## Available Benchmarks

### benchmark_reshape.py
Comprehensive performance benchmark for the `reshape_pmt_data()` function.

Measures:
- Throughput (MB/s) for various frame sizes
- Per-frame processing time (ms)
- JIT compilation overhead
- Sustained acquisition performance

**Target:** 500 MB/s (125 MS/s × 2 bytes × 2 channels)  
**Achieved:** 4,500-5,400 MB/s (9-10× target)

**When to run:**
- After changes to reshape implementation
- When validating on new hardware
- To track performance trends over time
- Before major releases
