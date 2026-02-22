"""Threading and async utilities for pyscanbox.

Provides utilities for managing background threads and async operations
for hardware polling and real-time processing.

Example:
    >>> import pyscanbox.utils.threading
    >>> worker = pyscanbox.utils.threading.BackgroundWorker(my_function)
    >>> worker.start()
    >>> worker.stop()
"""

import threading
import queue
import time
from typing import Callable, Optional, Any


class BackgroundWorker:
    """Background worker thread for continuous tasks.

    Runs a function repeatedly in a background thread until stopped.
    Useful for hardware polling and monitoring.

    Attributes:
        func: Function to run in background
        interval: Sleep interval between calls (seconds)
        thread: Worker thread
        stop_event: Event to signal stop
    """

    def __init__(self, func: Callable, interval: float = 0.1):
        """Initialize background worker.

        Args:
            func: Function to call repeatedly. Should take no arguments.
            interval: Time to sleep between calls (seconds)
        """
        self.func = func
        self.interval = interval
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

    def start(self) -> None:
        """Start background worker thread."""
        if self.thread is not None and self.thread.is_alive():
            return
        
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop background worker thread.

        Args:
            timeout: Maximum time to wait for thread to stop (seconds)
        """
        if self.thread is None:
            return
        
        self.stop_event.set()
        self.thread.join(timeout=timeout)

    def is_running(self) -> bool:
        """Check if worker is running.

        Returns:
            True if worker thread is active.
        """
        return self.thread is not None and self.thread.is_alive()

    def _worker_loop(self) -> None:
        """Worker loop (runs in background thread)."""
        while not self.stop_event.is_set():
            try:
                self.func()
            except Exception as e:
                print(f"Error in background worker: {e}")
            
            time.sleep(self.interval)


class ThreadSafeCounter:
    """Thread-safe counter for tracking progress.

    Attributes:
        value: Current counter value
        lock: Thread lock
    """

    def __init__(self, initial_value: int = 0):
        """Initialize counter.

        Args:
            initial_value: Starting value for counter
        """
        self.value = initial_value
        self.lock = threading.Lock()

    def increment(self, amount: int = 1) -> int:
        """Increment counter and return new value.

        Args:
            amount: Amount to increment by

        Returns:
            New counter value.
        """
        with self.lock:
            self.value += amount
            return self.value

    def get(self) -> int:
        """Get current counter value.

        Returns:
            Current value.
        """
        with self.lock:
            return self.value

    def reset(self) -> None:
        """Reset counter to zero."""
        with self.lock:
            self.value = 0


class RateLimiter:
    """Rate limiter for throttling operations.

    Ensures operations don't exceed a specified rate.

    Attributes:
        rate: Maximum operations per second
        last_time: Timestamp of last operation
        lock: Thread lock
    """

    def __init__(self, rate: float):
        """Initialize rate limiter.

        Args:
            rate: Maximum operations per second
        """
        self.rate = rate
        self.min_interval = 1.0 / rate
        self.last_time = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        """Wait if necessary to maintain rate limit.

        Blocks until enough time has passed since last operation.
        """
        with self.lock:
            now = time.time()
            elapsed = now - self.last_time
            
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            
            self.last_time = time.time()


class TimeoutLock:
    """Lock with timeout support.

    Wrapper around threading.Lock that raises exception on timeout.
    """

    def __init__(self):
        """Initialize timeout lock."""
        self.lock = threading.Lock()

    def acquire(self, timeout: Optional[float] = None) -> bool:
        """Acquire lock with optional timeout.

        Args:
            timeout: Maximum time to wait (seconds). None = wait forever.

        Returns:
            True if lock acquired, False if timeout.

        Raises:
            TimeoutError: If timeout specified and exceeded.
        """
        acquired = self.lock.acquire(timeout=timeout)
        
        if not acquired and timeout is not None:
            raise TimeoutError("Lock acquisition timeout")
        
        return acquired

    def release(self) -> None:
        """Release lock."""
        self.lock.release()

    def __enter__(self):
        """Context manager entry."""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()
