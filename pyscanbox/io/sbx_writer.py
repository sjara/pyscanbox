""".sbx file writer for raw PMT data.

This module handles writing raw uint16 PMT data to .sbx files.
The .sbx format is a headerless binary dump of reshaped uint16 arrays,
exactly matching MATLAB's fwrite output.

Reference:
    Original MATLAB implementation writes raw fwrite() binary data

Example:
    >>> import pyscanbox.io.sbx_writer
    >>> writer = pyscanbox.io.sbx_writer.SbxWriter('mydata')
    >>> writer.write_frame(frame_data)
    >>> writer.close()
"""

import os
import numpy as np
from typing import Optional


class SbxWriter:
    """Writer for .sbx binary files.

    Writes raw uint16 PMT data directly to disk in headerless binary format.
    This ensures backwards compatibility with existing MATLAB-based
    analysis pipelines like Suite2p.

    Attributes:
        filepath: Path to .sbx file (without extension)
        file_handle: Open file handle
        frames_written: Counter for frames written
    """

    def __init__(self, filepath: str):
        """Initialize .sbx writer.

        Args:
            filepath: Output path without extension (e.g., 'mydata').
                Will create 'mydata.sbx'.
        """
        self.filepath = filepath
        self.sbx_path = f"{filepath}.sbx"
        self.file_handle: Optional[object] = None
        self.frames_written = 0
        
        self._open_file()

    def _open_file(self) -> None:
        """Open .sbx file for writing.

        Creates output directory if needed and opens file in binary
        write mode.
        """
        # Create directory if needed
        output_dir = os.path.dirname(self.sbx_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        
        # Open file in binary write mode
        self.file_handle = open(self.sbx_path, 'wb')

    def write_frame(self, frame_data: np.ndarray) -> None:
        """Write one frame of data to .sbx file.

        Args:
            frame_data: Frame data as numpy array (uint16).
                Shape: (channels, lines, pixels) or (lines, pixels)

        Note:
            Data is written directly as raw bytes in C-order (row-major).
            This matches MATLAB's fwrite behavior.

        Raises:
            RuntimeError: If file is not open.
            ValueError: If data type is not uint16.
        """
        if self.file_handle is None:
            raise RuntimeError("File not open")
        
        if frame_data.dtype != np.uint16:
            raise ValueError(f"Data must be uint16, got {frame_data.dtype}")
        
        # Write raw bytes directly
        # Use tofile() for efficient binary write
        frame_data.tofile(self.file_handle)
        
        self.frames_written += 1

    def write_buffer(self, buffer: np.ndarray) -> None:
        """Write raw buffer data (alternative to write_frame).

        Args:
            buffer: Raw uint16 buffer to write
        """
        self.write_frame(buffer)

    def flush(self) -> None:
        """Flush write buffer to disk.

        Forces immediate write of buffered data to disk.
        """
        if self.file_handle is not None:
            self.file_handle.flush()
            os.fsync(self.file_handle.fileno())

    def close(self) -> None:
        """Close .sbx file.

        Flushes buffers and closes file handle.
        """
        if self.file_handle is not None:
            self.flush()
            self.file_handle.close()
            self.file_handle = None
        
        print(f"Wrote {self.frames_written} frames to {self.sbx_path}")

    def get_frames_written(self) -> int:
        """Get number of frames written.

        Returns:
            Number of frames written to file.
        """
        return self.frames_written

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


def write_sbx_file(filepath: str, data: np.ndarray) -> None:
    """Convenience function to write entire dataset to .sbx file.

    Args:
        filepath: Output path without extension
        data: Full dataset as numpy array (uint16).
            Shape: (frames, channels, lines, pixels) or (frames, lines, pixels)

    Example:
        >>> import numpy as np
        >>> data = np.zeros((1000, 2, 512, 796), dtype=np.uint16)
        >>> write_sbx_file('mydata', data)
    """
    with SbxWriter(filepath) as writer:
        if data.ndim == 4:
            # (frames, channels, lines, pixels)
            for frame in data:
                writer.write_frame(frame)
        elif data.ndim == 3:
            # (frames, lines, pixels)
            for frame in data:
                writer.write_frame(frame)
        else:
            raise ValueError(f"Data must be 3D or 4D, got shape {data.shape}")
