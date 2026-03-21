# Streaming and Plugins Specification

**Status:** 🔴 Planning Phase (Advanced Feature)  
**Implementation Target:** Phase 4  
**Last Updated:** February 23, 2026

---

## Overview

The streaming and plugin system enables real-time access to acquisition data for online analysis, feedback control, and custom processing pipelines. This supports advanced workflows like closed-loop experiments, real-time segmentation, and distributed processing.

---

## Motivation

### Use Cases

1. **Online Analysis:** Real-time cell detection, activity monitoring
2. **Closed-Loop Experiments:** Feedback control based on neural activity
3. **Distributed Processing:** Offload processing to separate machines
4. **Live Visualization:** External displays with custom rendering
5. **Data Reduction:** Store only processed/compressed data
6. **Quality Control:** Real-time monitoring of acquisition quality

### Requirements

- **Low Latency:** <50 ms from acquisition to consumer
- **High Throughput:** Keep up with 500 MB/s data stream
- **Multiple Consumers:** Support concurrent readers
- **Flexible Processing:** Plugin architecture for custom algorithms

---

## Architecture Overview

```
┌─────────────────┐
│ AlazarDigitizer │
│  (500 MB/s)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Reshape +      │
│  Buffer Queue   │
└────────┬────────┘
         │
         ├────────────────────────────┐
         │                            │
         ▼                            ▼
┌─────────────────┐         ┌─────────────────┐
│  File Writer    │         │  Streaming      │
│  (.sbx/.mat)    │         │  Interface      │
└─────────────────┘         └────────┬────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
                    ▼                ▼                ▼
            ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
            │  Plugin 1   │  │  Plugin 2   │  │  External   │
            │ (rolling)   │  │ (twopmts)   │  │  Consumer   │
            └─────────────┘  └─────────────┘  └─────────────┘
```

---

## Streaming Methods

### Option 1: Memory-Mapped Files (mmap)

**Advantages:**
- Zero-copy access within same machine
- Very low latency (<1 ms)
- Simple implementation
- No network overhead

**Disadvantages:**
- Same machine only
- File system overhead
- Requires synchronized access

**Implementation:**
```python
import mmap
import numpy as np

class MemoryMappedStreamer:
    """Stream frames via memory-mapped circular buffer."""
    
    def __init__(self, buffer_size_frames: int, frame_shape: tuple):
        self.buffer_size = buffer_size_frames
        self.frame_shape = frame_shape
        self.pixel_count = np.prod(frame_shape)
        
        # Create memory-mapped file
        self.mmap_file = tempfile.NamedTemporaryFile()
        self.mmap_file.write(b'\x00' * (buffer_size_frames * self.pixel_count * 2))
        self.mmap_file.flush()
        
        self.mmap = mmap.mmap(self.mmap_file.fileno(), 0)
        self.write_index = 0
        
    def write_frame(self, frame: np.ndarray):
        """Write frame to circular buffer."""
        offset = (self.write_index % self.buffer_size) * self.pixel_count * 2
        self.mmap[offset:offset + frame.nbytes] = frame.tobytes()
        self.write_index += 1
        
    def get_mmap_filename(self) -> str:
        return self.mmap_file.name
```

**Consumer Side:**
```python
def consume_frames(mmap_filename: str, frame_shape: tuple):
    """Read frames from memory-mapped buffer."""
    with open(mmap_filename, 'r+b') as f:
        mm = mmap.mmap(f.fileno(), 0)
        
        read_index = 0
        while True:
            offset = (read_index % buffer_size) * pixel_count * 2
            frame_bytes = mm[offset:offset + pixel_count * 2]
            frame = np.frombuffer(frame_bytes, dtype=np.uint16).reshape(frame_shape)
            
            # Process frame
            process_frame(frame)
            
            read_index += 1
```

### Option 2: TCP Sockets

**Advantages:**
- Works across network
- Standard protocol
- Many language bindings
- Flexible topology

**Disadvantages:**
- Network latency (~1-10 ms LAN)
- Requires serialization
- More complex error handling

**Implementation:**
```python
import socket
import pickle

class TCPStreamer:
    """Stream frames over TCP socket."""
    
    def __init__(self, host: str = 'localhost', port: int = 30000):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind((host, port))
        self.socket.listen(5)
        self.clients = []
        
    def accept_connection(self):
        """Accept new client connection."""
        client, addr = self.socket.accept()
        self.clients.append(client)
        
    def broadcast_frame(self, frame: np.ndarray):
        """Send frame to all connected clients."""
        # Serialize frame (consider msgpack or custom binary format)
        data = pickle.dumps(frame)
        size = len(data)
        
        for client in self.clients:
            try:
                # Send size header then data
                client.sendall(size.to_bytes(4, 'little'))
                client.sendall(data)
            except:
                self.clients.remove(client)
```

### Option 3: ZeroMQ (Recommended)

**Advantages:**
- High performance (near-TCP speeds)
- Multiple messaging patterns (PUB-SUB, PUSH-PULL)
- Automatic reconnection
- Cross-platform, many bindings
- Built-in buffering

**Disadvantages:**
- External dependency (zmq library)
- Learning curve for new protocol

**Implementation:**
```python
import zmq
import numpy as np

class ZMQStreamer:
    """Stream frames using ZeroMQ PUB-SUB pattern."""
    
    def __init__(self, port: int = 30000):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind(f"tcp://*:{port}")
        
    def publish_frame(self, frame: np.ndarray, topic: str = 'frame'):
        """Publish frame to all subscribers."""
        # Send topic + metadata + data
        metadata = {
            'shape': frame.shape,
            'dtype': str(frame.dtype),
            'timestamp': time.time()
        }
        
        self.socket.send_string(topic, zmq.SNDMORE)
        self.socket.send_json(metadata, zmq.SNDMORE)
        self.socket.send(frame.tobytes(), copy=False)
```

**Consumer Side:**
```python
def consume_frames_zmq(host: str, port: int):
    """Subscribe to frame stream."""
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.connect(f"tcp://{host}:{port}")
    socket.subscribe('frame')
    
    while True:
        topic = socket.recv_string()
        metadata = socket.recv_json()
        frame_bytes = socket.recv(copy=False)
        
        # Reconstruct frame
        shape = tuple(metadata['shape'])
        dtype = metadata['dtype']
        frame = np.frombuffer(frame_bytes, dtype=dtype).reshape(shape)
        
        # Process
        process_frame(frame)
```

---

## Plugin System Architecture

### Plugin Interface

**Base Class:**
```python
from abc import ABC, abstractmethod

class AcquisitionPlugin(ABC):
    """Base class for acquisition plugins."""
    
    def __init__(self, config: dict):
        """Initialize plugin with configuration."""
        self.config = config
        
    @abstractmethod
    def on_frame(self, frame: np.ndarray, metadata: dict) -> None:
        """Called for each acquired frame.
        
        Args:
            frame: PMT data (height, width) uint16
            metadata: Frame metadata (timestamp, frame_number, etc.)
        """
        pass
        
    def on_start(self) -> None:
        """Called when acquisition starts."""
        pass
        
    def on_stop(self) -> None:
        """Called when acquisition stops."""
        pass
        
    def get_results(self) -> dict:
        """Return plugin results/statistics."""
        return {}
```

### Plugin Registration

```python
class PluginManager:
    """Manages acquisition plugins."""
    
    def __init__(self):
        self.plugins = []
        
    def register_plugin(self, plugin: AcquisitionPlugin):
        """Register a plugin."""
        self.plugins.append(plugin)
        
    def on_frame(self, frame: np.ndarray, metadata: dict):
        """Dispatch frame to all plugins."""
        for plugin in self.plugins:
            plugin.on_frame(frame, metadata)
```

### Integration with Scanner

```python
class Scanner:
    def __init__(self, config: dict):
        # ... existing init
        
        # Initialize streaming
        if config.get('streaming', {}).get('enabled', False):
            self.streamer = self._create_streamer(config['streaming'])
        else:
            self.streamer = None
            
        # Initialize plugins
        self.plugin_manager = PluginManager()
        for plugin_name in config.get('plugins', []):
            plugin = self._load_plugin(plugin_name, config)
            self.plugin_manager.register_plugin(plugin)
    
    def _acquisition_loop(self):
        """Main acquisition loop with streaming."""
        while self.is_running and self.frames_acquired < self.frames_to_acquire:
            # Read and reshape
            raw_buffer = self.alazar.read_buffer()
            pmt0, pmt1, sync = reshape.reshape_pmt_data(raw_buffer, ...)
            
            # Write to file
            self.sbx_writer.write_frame(pmt0, pmt1)
            
            # Stream frame
            if self.streamer:
                metadata = {
                    'frame_number': self.frames_acquired,
                    'timestamp': time.time() - self.start_time
                }
                self.streamer.publish_frame(pmt0, metadata)
                
            # Run plugins
            self.plugin_manager.on_frame(pmt0, metadata)
            
            self.frames_acquired += 1
```

---

## Example Plugins

### 1. Rolling Average Plugin

```python
class RollingAveragePlugin(AcquisitionPlugin):
    """Compute and display rolling average of frames."""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.window_size = config.get('window_size', 10)
        self.buffer = []
        
    def on_frame(self, frame: np.ndarray, metadata: dict):
        self.buffer.append(frame.copy())
        
        if len(self.buffer) > self.window_size:
            self.buffer.pop(0)
            
        # Compute average
        if len(self.buffer) == self.window_size:
            avg_frame = np.mean(self.buffer, axis=0)
            # Could publish to separate stream or display
            
    def get_results(self) -> dict:
        return {'frames_averaged': len(self.buffer)}
```

### 2. Dual-PMT Processing Plugin

```python
class TwoPMTsPlugin(AcquisitionPlugin):
    """Process data from two PMT channels."""
    
    def on_frame(self, frame: np.ndarray, metadata: dict):
        # Assume frame contains both PMTs stacked
        height = frame.shape[0] // 2
        pmt0 = frame[:height, :]
        pmt1 = frame[height:, :]
        
        # Compute ratio, correlation, etc.
        ratio = np.divide(pmt0, pmt1, where=pmt1>0)
        correlation = np.corrcoef(pmt0.flat, pmt1.flat)[0,1]
        
        # Store or stream results
```

### 3. Saturation Monitor Plugin

```python
class SaturationMonitorPlugin(AcquisitionPlugin):
    """Monitor PMT saturation levels."""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.threshold = config.get('saturation_threshold', 4000)
        self.saturation_counts = []
        
    def on_frame(self, frame: np.ndarray, metadata: dict):
        saturated_pixels = np.sum(frame > self.threshold)
        saturation_percent = 100 * saturated_pixels / frame.size
        
        self.saturation_counts.append(saturation_percent)
        
        # Could trigger warning if exceeds limit
        if saturation_percent > 1.0:
            print(f"Warning: {saturation_percent:.2f}% pixels saturated")
            
    def get_results(self) -> dict:
        return {
            'mean_saturation': np.mean(self.saturation_counts),
            'max_saturation': np.max(self.saturation_counts)
        }
```

---

## Configuration Schema

```yaml
streaming:
  enabled: false
  method: 'zmq'  # Options: 'mmap', 'tcp', 'zmq'
  host: 'localhost'
  port: 30000
  
  # Performance tuning
  buffer_size_frames: 100
  max_framerate_hz: 30  # Subsample if necessary
  
plugins:
  enabled: false
  plugins:
    - name: 'rolling'
      window_size: 10
    - name: 'twopmts'
      enabled: true
    - name: 'saturation_monitor'
      threshold: 4000
```

---

## Performance Considerations

### Bottlenecks

1. **Serialization:** Pickle is slow, use msgpack or raw bytes
2. **Network Bandwidth:** 500 MB/s may exceed network capacity
3. **Latency:** Each hop adds delay
4. **GIL:** Plugin processing can block acquisition if not careful

### Solutions

1. **Subsampling:** Stream every Nth frame
2. **Downsampling:** Reduce spatial resolution (bin pixels)
3. **Compression:** On-the-fly compression (e.g., blosc)
4. **Separate Thread:** Run streaming in background thread
5. **Shared Memory:** Use mmap for same-machine consumers

### Performance Targets

- **Latency:** <50 ms from acquisition to consumer
- **Throughput:** Support streaming at 30 fps minimum
- **Overhead:** <5% CPU impact on acquisition

---

## Testing Strategy

### Unit Tests
- Plugin interface contract
- Frame serialization/deserialization
- Configuration parsing

### Integration Tests
- Multiple plugins running simultaneously
- Streaming with mock data
- Plugin results verification

### Performance Tests
- Latency measurement
- Throughput benchmarks
- CPU overhead profiling

### HIL Tests (Phase 4)
- Streaming during real acquisition
- Multiple consumers
- Network streaming across machines
- Long-duration stability

---

## Security Considerations

### Network Streaming
- **Authentication:** Add connection authentication if needed
- **Encryption:** SSL/TLS for sensitive data
- **Access Control:** Bind to localhost unless network access required
- **Firewall:** Ensure proper port configuration

---

## References

- **MATLAB Config:** `Scanbox/core/scanbox_config.m`
  - `sbconfig.mmap = false`
  - `sbconfig.plugin = {'rolling','twopmts'}`
  - `sbconfig.stream_host = 'localhost'`
  - `sbconfig.stream_port = 30000`
- **ZeroMQ:** https://zeromq.org/
- **Python mmap:** https://docs.python.org/3/library/mmap.html

---

## Milestones

- **Phase 4:** Milestone 4.5 - Streaming infrastructure and plugin system
- Implementation priority after core features complete
- Advanced feature for specialized workflows

---

## Decision Criteria

**Implement if:**
- ✅ Need online analysis or feedback control
- ✅ Core features (Phases 1-3) complete and stable
- ✅ Time/resources available for advanced features

**Skip if:**
- ❌ Offline analysis sufficient for current experiments
- ❌ Core features not yet complete
- ❌ Limited development time/resources

**Recommended Approach:**
- Start with simple mmap implementation for same-machine use
- Upgrade to ZeroMQ if network streaming needed
- Add plugins incrementally based on user requirements
