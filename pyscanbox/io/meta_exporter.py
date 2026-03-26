# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Metadata export for Scanbox .mat files.

Converts Scanbox-compatible ``.mat`` metadata files to human-readable
formats (JSON, YAML) without requiring MATLAB.  Handles both the original
Scanbox nested-struct format and the pyscanbox flat-key format.

The conversion logic is shared with the reader classes in
:mod:`pyscanbox.io.sbx_reader` — all numpy-to-Python scalar/array
normalization happens here so that neither the readers nor the CLI
script need to duplicate it.

Example::

    >>> import pyscanbox.io.meta_exporter
    >>> meta = pyscanbox.io.meta_exporter.load_mat_as_dict('mydata.mat')
    >>> pyscanbox.io.meta_exporter.save_as_json(meta, 'mydata_meta.json')
    >>> pyscanbox.io.meta_exporter.save_as_yaml(meta, 'mydata_meta.yaml')
"""

import json
import os
import numpy as np
import scipy.io
import yaml


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _numpy_to_python(obj):
    """Recursively convert numpy scalars and arrays to plain Python types.

    This is necessary because ``json.dumps`` (and most YAML serializers)
    cannot serialize numpy dtypes by default.

    Args:
        obj: Any Python object, potentially containing numpy scalars,
            arrays, or nested containers.

    Returns:
        A JSON-serializable copy of ``obj``.
    """
    if isinstance(obj, np.ndarray):
        if obj.ndim == 0:
            return _numpy_to_python(obj.item())
        return [_numpy_to_python(v) for v in obj.tolist()]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.complexfloating,)):
        return complex(obj)
    if isinstance(obj, dict):
        return {k: _numpy_to_python(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_numpy_to_python(v) for v in obj]
    return obj


def _flatten_scanbox_info(info_obj):
    """Flatten a MATLAB-struct scipy object (the Scanbox 'info' struct).

    Args:
        info_obj: A ``scipy.io.matlab.mio5_params.MatlabObject`` or similar
            object with a ``_fieldnames`` attribute.

    Returns:
        Flat dictionary of field names to plain Python values.
    """
    flat = {}
    for field in info_obj._fieldnames:
        val = getattr(info_obj, field)
        # Recursively flatten nested structs.
        if hasattr(val, '_fieldnames'):
            flat[field] = _flatten_scanbox_info(val)
        else:
            flat[field] = _numpy_to_python(val)
    return flat


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_mat_as_dict(mat_path):
    """Load a Scanbox ``.mat`` file and return a JSON-serializable dict.

    Supports both formats:

    * **Original Scanbox** – contains a top-level ``info`` MATLAB struct.
      The struct is flattened so that e.g. ``info.sz`` becomes ``{'sz': …}``
      at the top level.
    * **pyscanbox flat** – contains individual top-level keys; these are
      returned as-is after numpy-to-Python conversion.

    Args:
        mat_path: Path to the ``.mat`` file (with or without extension).
            If the extension is missing, ``.mat`` is appended automatically.

    Returns:
        Dictionary with all metadata fields as plain Python types
        (``int``, ``float``, ``str``, ``list``).  A ``'_format'`` key is
        added to indicate which format was detected:
        ``'scanbox_original'`` or ``'pyscanbox_flat'``.

    Raises:
        FileNotFoundError: If the ``.mat`` file does not exist.
        KeyError: If neither ``info`` struct nor flat keys are found.

    Example::

        >>> import pyscanbox.io.meta_exporter
        >>> meta = pyscanbox.io.meta_exporter.load_mat_as_dict('mydata')
        >>> print(meta['sz'])
    """
    # Accept path with or without extension.
    if not mat_path.endswith('.mat'):
        mat_path = f'{mat_path}.mat'
    if not os.path.exists(mat_path):
        raise FileNotFoundError(f'.mat file not found: {mat_path}')

    raw = scipy.io.loadmat(mat_path, squeeze_me=True, struct_as_record=False)

    # --- Original Scanbox format: single nested 'info' struct ---
    has_info = 'info' in raw
    has_flat = any(k for k in raw if not k.startswith('__') and k != 'info')

    if has_info and not has_flat:
        info_obj = raw['info']
        result = _flatten_scanbox_info(info_obj)
        result['_format'] = 'scanbox_original'
        return result

    # --- pyscanbox flat format: individual top-level keys ---
    result = {}
    for key, val in raw.items():
        if key.startswith('__'):
            continue
        if hasattr(val, '_fieldnames'):
            result[key] = _flatten_scanbox_info(val)
        else:
            result[key] = _numpy_to_python(val)
    result['_format'] = 'pyscanbox_flat'
    return result


def save_as_json(meta_dict, output_path, indent=2):
    """Write a metadata dictionary to a JSON file.

    Args:
        meta_dict: Dictionary as returned by :func:`load_mat_as_dict`.
        output_path: Destination ``.json`` file path.
        indent: JSON indentation level (default ``2``).

    Raises:
        TypeError: If ``meta_dict`` contains values that are not
            JSON-serializable (should not happen after
            :func:`load_mat_as_dict`).

    Example::

        >>> import pyscanbox.io.meta_exporter
        >>> meta = pyscanbox.io.meta_exporter.load_mat_as_dict('mydata')
        >>> pyscanbox.io.meta_exporter.save_as_json(meta, 'mydata_meta.json')
    """
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as fh:
        json.dump(meta_dict, fh, indent=indent, ensure_ascii=False)


def save_as_yaml(meta_dict, output_path):
    """Write a metadata dictionary to a YAML file.

    Args:
        meta_dict: Dictionary as returned by :func:`load_mat_as_dict`.
        output_path: Destination ``.yaml`` file path.

    Example::

        >>> import pyscanbox.io.meta_exporter
        >>> meta = pyscanbox.io.meta_exporter.load_mat_as_dict('mydata')
        >>> pyscanbox.io.meta_exporter.save_as_yaml(meta, 'mydata_meta.yaml')
    """
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as fh:
        yaml.dump(meta_dict, fh, default_flow_style=False, allow_unicode=True,
                  sort_keys=True)
