"""Configuration management for pyscanbox.

This module handles loading and managing configuration settings for the
Scanbox system, including COM ports, acquisition parameters, and hardware
settings.

Example:
    >>> import pyscanbox.config
    >>> config = pyscanbox.config.load_config('my_config.yaml')
    >>> print(config['alazar']['sample_rate'])
"""

import os
import yaml
from typing import Dict, Any, Optional


class ScanboxConfig:
    """Configuration container for Scanbox system.

    Attributes:
        alazar: AlazarTech digitizer configuration
        controller: Main controller (Pockels, shutter, mirror) configuration
        motor: Trinamic motor configuration
        acquisition: Acquisition parameters
        io: File I/O settings
    """

    def __init__(self, config_dict: Optional[Dict[str, Any]] = None):
        """Initialize configuration.

        Args:
            config_dict: Dictionary containing configuration parameters.
                If None, loads default configuration.
        """
        if config_dict is None:
            config_dict = self._default_config()
        
        self.emulation = config_dict.get('emulation', {'enabled': False, 'verbose': False})
        self.alazar = config_dict.get('alazar', {})
        self.controller = config_dict.get('controller', {})
        self.motor = config_dict.get('motor', {})
        self.acquisition = config_dict.get('acquisition', {})
        self.io = config_dict.get('io', {})

    @staticmethod
    def _default_config() -> Dict[str, Any]:
        """Return default configuration dictionary.

        Returns:
            Dictionary with default configuration values.
        """
        return {
            'emulation': {
                'enabled': False,  # Enable hardware emulation for Linux/offline dev
                'verbose': False,  # Log emulation events
            },
            'alazar': {
                'sample_rate': 125_000_000,  # 125 MS/s
                'bits_per_sample': 14,
                'channels': 2,
                'buffer_count': 4,
                'samples_per_buffer': 2048,
            },
            'controller': {
                'com_port': 'COM3',
                'baud_rate': 1_000_000,
                'timeout': 1.0,
            },
            'motor': {
                'com_port': 'COM4',
                'baud_rate': 57600,
                'timeout': 1.0,
            },
            'acquisition': {
                'lines_per_frame': 512,
                'pixels_per_line': 796,
                'frames': 1000,
            },
            'io': {
                'output_directory': 'C:/scanbox_data',
                'file_prefix': 'scan',
            },
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary.

        Returns:
            Dictionary representation of configuration.
        """
        return {
            'alazar': self.alazar,
            'controller': self.controller,
            'motor': self.motor,
            'acquisition': self.acquisition,
            'io': self.io,
            'emulation': self.emulation,
        }



def load_config(filepath: str) -> ScanboxConfig:
    """Load configuration from YAML file.

    Args:
        filepath: Path to YAML configuration file.

    Returns:
        ScanboxConfig object with loaded configuration.

    Raises:
        FileNotFoundError: If configuration file does not exist.
        yaml.YAMLError: If configuration file is not valid YAML.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Configuration file not found: {filepath}")
    
    with open(filepath, 'r') as f:
        config_dict = yaml.safe_load(f)
    
    return ScanboxConfig(config_dict)


def save_config(config: ScanboxConfig, filepath: str) -> None:
    """Save configuration to YAML file.

    Args:
        config: ScanboxConfig object to save.
        filepath: Path to output YAML file.
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    with open(filepath, 'w') as f:
        yaml.dump(config.to_dict(), f, default_flow_style=False)


def get_default_config() -> ScanboxConfig:
    """Get default configuration.

    Returns:
        ScanboxConfig object with default values.
    """
    return ScanboxConfig()
