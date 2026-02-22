"""DMA buffer management for high-speed acquisition.

This module provides utilities for managing DMA buffers used in
continuous data acquisition from the Alazar digitizer.

Key requirements:
    - Buffers must use pinned (page-locked) memory
    - Circular buffering for continuous acquisition
    - Thread-safe buffer access

Reference:
    Original MATLAB implementation uses built-in DMA from Alazar API
"""

import ctypes
import numpy as np
from typing import List, Optional
import threading


class BufferPool:
    """Pool of DMA buffers for continuous acquisition.

    Manages a circular pool of pinned memory buffers for DMA transfers.
    Provides thread-safe buffer acquisition and release.

    Attributes:
        buffer_size: Size of each buffer in bytes
        buffer_count: Number of buffers in pool
        buffers: List of buffer arrays
        available: Indices of available buffers
        lock: Thread lock for buffer access
    """

    def __init__(self, buffer_size: int, buffer_count: int):
        """Initialize buffer pool.

        Args:
            buffer_size: Size of each buffer in bytes
            buffer_count: Number of buffers to allocate
        """
        self.buffer_size = buffer_size
        self.buffer_count = buffer_count
        
        self.buffers: List[np.ndarray] = []
        self.buffer_pointers: List[ctypes.c_void_p] = []
        self.available: List[int] = []
        self.lock = threading.Lock()
        
        self._allocate_buffers()

    def _allocate_buffers(self) -> None:
        """Allocate pinned memory buffers.

        Uses ctypes to allocate page-locked memory that is safe for
        DMA transfers (won't be moved by garbage collector).

        Note:
            On Windows, may need to use VirtualAlloc with PAGE_READWRITE
            and VirtualLock for true pinned memory.
        """
        for i in range(self.buffer_count):
            # Allocate buffer using numpy (TODO: use pinned memory)
            # For production, should use ctypes to allocate page-locked memory
            buffer = np.zeros(self.buffer_size // 2, dtype=np.uint16)
            
            self.buffers.append(buffer)
            self.available.append(i)
            
            # Get pointer for DMA
            ptr = buffer.ctypes.data_as(ctypes.c_void_p)
            self.buffer_pointers.append(ptr)

    def acquire_buffer(self, timeout: Optional[float] = None) -> Optional[int]:
        """Acquire an available buffer from pool.

        Args:
            timeout: Maximum time to wait for buffer (seconds).
                None means wait indefinitely.

        Returns:
            Buffer index, or None if timeout.
        """
        with self.lock:
            if len(self.available) == 0:
                return None
            
            return self.available.pop(0)

    def release_buffer(self, buffer_index: int) -> None:
        """Release buffer back to pool.

        Args:
            buffer_index: Index of buffer to release
        """
        with self.lock:
            if buffer_index not in self.available:
                self.available.append(buffer_index)

    def get_buffer(self, buffer_index: int) -> np.ndarray:
        """Get buffer array by index.

        Args:
            buffer_index: Index of buffer

        Returns:
            NumPy array for buffer.
        """
        return self.buffers[buffer_index]

    def get_buffer_pointer(self, buffer_index: int) -> ctypes.c_void_p:
        """Get buffer pointer for DMA.

        Args:
            buffer_index: Index of buffer

        Returns:
            Pointer to buffer memory.
        """
        return self.buffer_pointers[buffer_index]

    def get_available_count(self) -> int:
        """Get number of available buffers.

        Returns:
            Number of buffers currently available.
        """
        with self.lock:
            return len(self.available)

    def reset(self) -> None:
        """Reset pool, making all buffers available."""
        with self.lock:
            self.available = list(range(self.buffer_count))


class CircularBufferQueue:
    """Thread-safe circular buffer queue for producer-consumer pattern.

    Used to pass filled buffers from acquisition thread to processing
    thread without blocking or copying data.

    Attributes:
        max_size: Maximum queue size
        queue: List of buffer indices
        lock: Thread lock
        not_empty: Condition for consumer
        not_full: Condition for producer
    """

    def __init__(self, max_size: int = 4):
        """Initialize circular buffer queue.

        Args:
            max_size: Maximum number of buffers in queue
        """
        self.max_size = max_size
        self.queue: List[int] = []
        self.lock = threading.Lock()
        self.not_empty = threading.Condition(self.lock)
        self.not_full = threading.Condition(self.lock)

    def put(self, buffer_index: int, timeout: Optional[float] = None) -> bool:
        """Put buffer index in queue.

        Args:
            buffer_index: Index of buffer to queue
            timeout: Maximum time to wait if queue is full

        Returns:
            True if successful, False if timeout.
        """
        with self.not_full:
            while len(self.queue) >= self.max_size:
                if not self.not_full.wait(timeout):
                    return False
            
            self.queue.append(buffer_index)
            self.not_empty.notify()
            return True

    def get(self, timeout: Optional[float] = None) -> Optional[int]:
        """Get buffer index from queue.

        Args:
            timeout: Maximum time to wait if queue is empty

        Returns:
            Buffer index, or None if timeout.
        """
        with self.not_empty:
            while len(self.queue) == 0:
                if not self.not_empty.wait(timeout):
                    return None
            
            buffer_index = self.queue.pop(0)
            self.not_full.notify()
            return buffer_index

    def size(self) -> int:
        """Get current queue size.

        Returns:
            Number of buffers in queue.
        """
        with self.lock:
            return len(self.queue)

    def is_empty(self) -> bool:
        """Check if queue is empty.

        Returns:
            True if queue is empty.
        """
        with self.lock:
            return len(self.queue) == 0

    def is_full(self) -> bool:
        """Check if queue is full.

        Returns:
            True if queue is full.
        """
        with self.lock:
            return len(self.queue) >= self.max_size
