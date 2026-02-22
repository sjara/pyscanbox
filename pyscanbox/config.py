"""Configuration management for pyscanbox.

This module handles loading and managing configuration settings for the
Scanbox system, including COM ports, acquisition parameters, and hardware
settings.

Configuration files are searched in the following order:
1. User config: ~/.config/pyscanbox/config.yaml (Linux/Mac) or
                %APPDATA%/pyscanbox/config.yaml (Windows)
2. System config: /etc/pyscanbox/config.yaml (Linux) or
                  C:/ProgramData/pyscanbox/config.yaml (Windows)

Example:
    >>> import pyscanbox.config
    >>> # Search standard locations
    >>> config = pyscanbox.config.load_config()
    >>> # Or specify path explicitly
    >>> config = pyscanbox.config.load_config('my_config.yaml')
    >>> print(config['alazar']['sample_rate'])
"""

import os
import sys
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

    def __init__(self, config_dict: Dict[str, Any]):
        """Initialize configuration.

        Args:
            config_dict: Dictionary containing configuration parameters.
                Use load_config() to create from a YAML file.
        """
        self.emulation = config_dict.get('emulation', {'enabled': False, 'verbose': False})
        self.alazar = config_dict.get('alazar', {})
        self.controller = config_dict.get('controller', {})
        self.motor = config_dict.get('motor', {})
        self.acquisition = config_dict.get('acquisition', {})
        self.io = config_dict.get('io', {})

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



def find_config() -> str:
    """Find configuration file in standard locations.
    
    Searches for config.yaml in the following order:
    1. User config directory:
       - Linux/Mac: ~/.config/pyscanbox/config.yaml
       - Windows: %APPDATA%/pyscanbox/config.yaml
    2. System config directory:
       - Linux: /etc/pyscanbox/config.yaml
       - Windows: C:/ProgramData/pyscanbox/config.yaml
    
    Returns:
        Path to first configuration file found.
        
    Raises:
        FileNotFoundError: If no configuration file is found in any location.
        
    Example:
        >>> # Automatically find config in standard locations
        >>> config_path = find_config()
        >>> config = load_config(config_path)
    """
    search_paths = []
    
    # User config directory
    if sys.platform == 'win32':
        # Windows: %APPDATA%/pyscanbox/config.yaml
        appdata = os.environ.get('APPDATA')
        if appdata:
            search_paths.append(os.path.join(appdata, 'pyscanbox', 'config.yaml'))
    else:
        # Linux/Mac: ~/.config/pyscanbox/config.yaml
        home = os.path.expanduser('~')
        search_paths.append(os.path.join(home, '.config', 'pyscanbox', 'config.yaml'))
    
    # System config directory
    if sys.platform == 'win32':
        # Windows: C:/ProgramData/pyscanbox/config.yaml
        search_paths.append(r'C:\ProgramData\pyscanbox\config.yaml')
    else:
        # Linux: /etc/pyscanbox/config.yaml
        search_paths.append('/etc/pyscanbox/config.yaml')
    
    # Search for first existing config file
    for path in search_paths:
        if os.path.exists(path):
            return path
    
    # No config found
    raise FileNotFoundError(
        f"No configuration file found. Searched locations:\n" +
        "\n".join(f"  - {path}" for path in search_paths) +
        "\n\nCreate a config file in one of these locations or specify path explicitly."
    )


def load_config(filepath: Optional[str] = None) -> ScanboxConfig:
    """Load configuration from YAML file.

    Args:
        filepath: Path to YAML configuration file. If None, searches standard
            locations (user config dir, then system config dir).

    Returns:
        ScanboxConfig object with loaded configuration.

    Raises:
        FileNotFoundError: If configuration file does not exist.
        yaml.YAMLError: If configuration file is not valid YAML.
        
    Example:
        >>> # Search standard locations automatically
        >>> config = load_config()
        >>> # Or specify path explicitly
        >>> config = load_config('/path/to/my_config.yaml')
    """
    if filepath is None:
        filepath = find_config()
    
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
