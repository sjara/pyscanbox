#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Convert a Scanbox .mat metadata file to JSON or YAML.

Handles both file formats produced by pyscanbox:

* **Original Scanbox format** – the .mat file contains a top-level
  ``info`` MATLAB struct that is automatically flattened.
* **pyscanbox flat format** – the .mat file stores individual top-level
  keys directly.

Usage::

    python scripts/mat_to_json.py /path/to/recording
    python scripts/mat_to_json.py /path/to/recording.mat
    python scripts/mat_to_json.py /path/to/recording --format yaml
    python scripts/mat_to_json.py /path/to/recording --out /out/dir/meta.json

Positional arguments:
    input   Path to the .mat file, or base path without extension
            (e.g. ``/data/mouse001_20260325_000``).

Examples::

    # Convert to JSON (default):
    python scripts/mat_to_json.py /data/mouse001_20260325_000

    # Convert to YAML (more human-readable):
    python scripts/mat_to_json.py /data/mouse001_20260325_000 --format yaml

    # Specify output path explicitly:
    python scripts/mat_to_json.py /data/mouse001_20260325_000 \\
        --out /out/metadata.json
"""

import argparse
import os
import sys

# Allow running the script from the repo root without installing the package.
_REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pyscanbox.io.meta_exporter


def main():
    """Entry point for the mat_to_json conversion script."""
    parser = argparse.ArgumentParser(
        description='Convert a Scanbox .mat metadata file to JSON or YAML.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        'input',
        metavar='INPUT',
        help='Path to the .mat file, or base path without extension '
             '(e.g. /data/mouse001_20260325_000).',
    )
    parser.add_argument(
        '--format', '-f',
        metavar='FMT',
        choices=['json', 'yaml'],
        default='json',
        help="Output format: 'json' (default) or 'yaml'.",
    )
    parser.add_argument(
        '--out', '-o',
        metavar='PATH',
        default=None,
        help='Output file path.  Defaults to <input>.json or <input>.yaml '
             'next to the .mat file.',
    )
    parser.add_argument(
        '--indent',
        metavar='N',
        type=int,
        default=2,
        help='JSON indentation level (default: 2).  Ignored for YAML.',
    )
    args = parser.parse_args()

    # Resolve input path (strip .mat if provided, re-add internally).
    input_path = args.input
    if input_path.endswith('.mat'):
        base_path = input_path[:-4]
    else:
        base_path = input_path

    # Determine output path.
    out_path = args.out
    if out_path is None:
        out_path = f'{base_path}.{args.format}'

    print(f'Loading : {base_path}.mat')
    try:
        meta = pyscanbox.io.meta_exporter.load_mat_as_dict(base_path)
    except FileNotFoundError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)

    detected_format = meta.get('_format', 'unknown')
    print(f'Format  : {detected_format}')
    print(f'Fields  : {len([k for k in meta if not k.startswith("_")])}')
    print(f'Writing : {out_path}')

    if args.format == 'json':
        pyscanbox.io.meta_exporter.save_as_json(meta, out_path,
                                                indent=args.indent)
    else:
        pyscanbox.io.meta_exporter.save_as_yaml(meta, out_path)

    print('Done.')


if __name__ == '__main__':
    main()
