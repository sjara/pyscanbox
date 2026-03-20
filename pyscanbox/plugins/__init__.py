"""pyscanbox acquisition plugins.

Each plugin integrates an auxiliary hardware or behavioural device with the
imaging acquisition loop.  See the plugin system specification for details:
    devel/specifications/plugin_system.md

Available plugins:
    quadrature  — Arduino-based quadrature encoder (Strategy 2, per-frame poll)

Template plugins (starting points for new devices):
    template_ttl_device       — Strategy 1: TTL edge timestamping
    template_per_frame_device — Strategy 2: per-frame polling
    template_async_device     — Strategy 3: PC-clock alignment
"""
