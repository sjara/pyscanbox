""".mat file writer for acquisition metadata.

This module handles writing acquisition metadata to .mat files for
backwards compatibility with MATLAB-based analysis pipelines.

Uses scipy.io.savemat to create MATLAB v7.3 compatible files.

Example:
    >>> import pyscanbox.io.mat_writer
    >>> metadata = {'frames': 1000, 'lines': 512, 'pixels': 796}
    >>> writer = pyscanbox.io.mat_writer.MatWriter('mydata')
    >>> writer.write(metadata)
"""

import os
import scipy.io
from typing import Dict, Any


class MatWriter:
    """Writer for .mat metadata files.

    Writes acquisition metadata in MATLAB format for backwards
    compatibility with existing analysis tools like Suite2p.

    Attributes:
        filepath: Path to .mat file (without extension)
    """

    def __init__(self, filepath: str):
        """Initialize .mat writer.

        Args:
            filepath: Output path without extension (e.g., 'mydata').
                Will create 'mydata.mat'.
        """
        self.filepath = filepath
        self.mat_path = f"{filepath}.mat"

    def write(self, metadata: Dict[str, Any]) -> None:
        """Write metadata dictionary to .mat file.

        Args:
            metadata: Dictionary containing acquisition metadata.
                Common keys:
                    - frames: Number of frames acquired
                    - lines_per_frame: Lines per frame
                    - pixels_per_line: Pixels per line
                    - sample_rate: Alazar sample rate
                    - channels: Number of PMT channels
                    - timestamp: Acquisition timestamp
                    - config: Full configuration dictionary

        Note:
            Uses scipy.io.savemat with oned_as='row' to match MATLAB
            array orientation conventions.
        """
        # Create directory if needed
        output_dir = os.path.dirname(self.mat_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        
        # Write metadata using scipy
        scipy.io.savemat(
            self.mat_path,
            metadata,
            oned_as='row',  # Save 1D arrays as row vectors (MATLAB convention)
            do_compression=True,
        )
        
        print(f"Wrote metadata to {self.mat_path}")

    def append(self, metadata: Dict[str, Any]) -> None:
        """Append metadata to existing .mat file.

        Loads existing .mat file, updates with new metadata, and
        writes back.

        Args:
            metadata: Dictionary with new/updated metadata fields.

        Note:
            If file doesn't exist, creates new file.
        """
        # Load existing data if file exists
        if os.path.exists(self.mat_path):
            existing = scipy.io.loadmat(self.mat_path)
            # Strip scipy internal keys (e.g. __header__, __version__, __globals__)
            existing = {k: v for k, v in existing.items() if not k.startswith('__')}
            # Update with new metadata
            existing.update(metadata)
            metadata = existing
        
        # Write combined metadata
        self.write(metadata)


def write_mat_file(filepath: str, metadata: Dict[str, Any]) -> None:
    """Convenience function to write metadata to .mat file.

    Args:
        filepath: Output path without extension
        metadata: Dictionary containing metadata

    Example:
        >>> metadata = {
        ...     'frames': 1000,
        ...     'lines_per_frame': 512,
        ...     'pixels_per_line': 796,
        ...     'sample_rate': 125000000,
        ... }
        >>> write_mat_file('mydata', metadata)
    """
    writer = MatWriter(filepath)
    writer.write(metadata)


def create_suite2p_metadata(config: Dict[str, Any], frames_acquired: int) -> Dict[str, Any]:
    """Create metadata dictionary compatible with Suite2p.

    Args:
        config: Configuration dictionary
        frames_acquired: Number of frames acquired

    Returns:
        Dictionary with metadata in Suite2p-compatible format.

    Note:
        Suite2p expects specific field names for automatic detection.
    """
    return {
        'nframes': frames_acquired,
        'nchannels': config['alazar']['channels'],
        'nplanes': 1,
        'nrois': 0,
        'scanmode': 1 if config.get('acquisition', {}).get('unidirectional', True) else 0,
        'ballmotion': [],
        'cam1': [],
        'cam2': [],
        'config': config,
        'sz': [
            config['acquisition']['lines_per_frame'],
            config['acquisition']['pixels_per_line'],
        ],
    }
