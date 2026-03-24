# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Logging utilities for pyscanbox.

Provides structured logging for hardware events, acquisition progress,
and error reporting.

Example:
    >>> import pyscanbox.utils.logging
    >>> logger = pyscanbox.utils.logging.get_logger('acquisition')
    >>> logger.info('Starting acquisition')
"""

import logging
import sys
from typing import Optional


def setup_logging(level: int = logging.INFO,
                 log_file: Optional[str] = None) -> None:
    """Setup logging configuration for pyscanbox.

    Args:
        level: Logging level (e.g., logging.INFO, logging.DEBUG)
        log_file: Optional path to log file. If None, logs only to console.
    """
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Setup root logger
    root_logger = logging.getLogger('pyscanbox')
    root_logger.setLevel(level)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler if specified
    if log_file is not None:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Get logger for specific module.

    Args:
        name: Logger name (typically module name)

    Returns:
        Logger instance.

    Example:
        >>> logger = get_logger('hardware.alazar')
        >>> logger.info('Configuring Alazar board')
    """
    return logging.getLogger(f'pyscanbox.{name}')


class ProgressReporter:
    """Simple progress reporter for acquisition.

    Attributes:
        total: Total number of items to process
        current: Current progress count
        last_percent: Last reported percentage
        report_interval: Report every N percent
    """

    def __init__(self, total: int, report_interval: int = 10):
        """Initialize progress reporter.

        Args:
            total: Total number of items to process
            report_interval: Report progress every N percent (1-100)
        """
        self.total = total
        self.current = 0
        self.last_percent = 0
        self.report_interval = report_interval
        self.logger = get_logger('progress')

    def update(self, count: int = 1) -> None:
        """Update progress by count items.

        Args:
            count: Number of items completed
        """
        self.current += count
        percent = int((self.current / self.total) * 100)
        
        if percent >= self.last_percent + self.report_interval:
            self.logger.info(f"Progress: {self.current}/{self.total} ({percent}%)")
            self.last_percent = percent

    def finish(self) -> None:
        """Mark progress as complete."""
        self.logger.info(f"Complete: {self.current}/{self.total} (100%)")


def log_hardware_event(component: str, event: str, details: Optional[str] = None) -> None:
    """Log hardware-related event.

    Args:
        component: Hardware component name (e.g., 'alazar', 'controller')
        event: Event description (e.g., 'opened', 'configured')
        details: Optional additional details
    """
    logger = get_logger(f'hardware.{component}')
    
    if details:
        logger.info(f"{event}: {details}")
    else:
        logger.info(event)


def log_acquisition_stats(frames: int, duration: float, data_size_mb: float) -> None:
    """Log acquisition statistics.

    Args:
        frames: Number of frames acquired
        duration: Acquisition duration in seconds
        data_size_mb: Total data size in megabytes
    """
    logger = get_logger('acquisition')
    
    fps = frames / duration if duration > 0 else 0
    mbps = data_size_mb / duration if duration > 0 else 0
    
    logger.info(f"Acquisition complete:")
    logger.info(f"  Frames: {frames}")
    logger.info(f"  Duration: {duration:.2f} s")
    logger.info(f"  Frame rate: {fps:.2f} fps")
    logger.info(f"  Data size: {data_size_mb:.2f} MB")
    logger.info(f"  Throughput: {mbps:.2f} MB/s")
