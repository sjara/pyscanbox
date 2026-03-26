#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Convert a pyscanbox/Scanbox .sbx recording to TIFF.

Writes one multi-page TIFF file per PMT channel.  Frames are written
incrementally so that large recordings (many GB) can be exported without
loading the entire dataset into RAM.

Output files are named ``<basename>_ch0.tif``, ``_ch1.tif``, etc., or
a single file when ``--channel`` is specified together with ``--out``.

Usage::

    python scripts/sbx_to_tiff.py /path/to/recording
    python scripts/sbx_to_tiff.py /path/to/recording --channel 0
    python scripts/sbx_to_tiff.py /path/to/recording --out /out/dir/myfile.tif
    python scripts/sbx_to_tiff.py /path/to/recording --bigtiff
    python scripts/sbx_to_tiff.py /path/to/recording --raw

Positional arguments:
    input   Base path of the recording, without extension (e.g.
            ``/data/mouse001_20260325_000``).  Both the .sbx and .mat
            files must be present at this path.

Examples::

    # Export both channels (default):
    python scripts/sbx_to_tiff.py /data/mouse001_20260325_000

    # Export only PMT channel 1:
    python scripts/sbx_to_tiff.py /data/mouse001_20260325_000 --channel 1

    # Write raw (wire-format) values instead of signal convention:
    python scripts/sbx_to_tiff.py /data/mouse001_20260325_000 --raw
"""

import argparse
import os
import sys

# Allow running the script from the repo root without installing the package.
_REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pyscanbox.io.sbx_reader
import pyscanbox.io.tiff_exporter


def main():
    """Entry point for the sbx_to_tiff conversion script."""
    parser = argparse.ArgumentParser(
        description='Convert a .sbx recording to one or more TIFF files.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        'input',
        metavar='INPUT',
        help='Base path of the .sbx recording, without extension '
             '(e.g. /data/mouse001_20260325_000).',
    )
    parser.add_argument(
        '--channel', '-c',
        metavar='N',
        type=int,
        default=None,
        help='Export only this PMT channel (0-based).  '
             'Default: export all channels.',
    )
    parser.add_argument(
        '--out', '-o',
        metavar='PATH',
        default=None,
        help='Output file path (used only when --channel is set).  '
             'Defaults to <input>_chN.tif next to the input file.',
    )
    parser.add_argument(
        '--bigtiff',
        action='store_true',
        default=False,
        help='Force BigTIFF format.  Auto-selected for files > 4 GB.',
    )
    parser.add_argument(
        '--raw',
        action='store_true',
        default=False,
        help='Write raw wire-format values (high = dark) instead of the '
             'default signal convention (high = bright) used by Suite2p.',
    )
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        default=False,
        help='Suppress progress output.',
    )
    args = parser.parse_args()

    invert = not args.raw
    progress = not args.quiet

    print(f'Opening: {args.input}.sbx')
    try:
        with pyscanbox.io.sbx_reader.ScanboxOriginalReader(args.input) as reader:
            print(f'  Frames   : {reader.num_frames}')
            print(f'  Channels : {reader.num_channels}')
            print(f'  Size     : {reader.lines_per_frame} × {reader.pixels_per_line} px')

            if args.channel is not None:
                # Single channel export.
                out_path = args.out
                if out_path is None:
                    out_path = f'{args.input}_ch{args.channel}.tif'
                print(f'Writing channel {args.channel} → {out_path}')
                pyscanbox.io.tiff_exporter.save_channel_as_tiff(
                    reader, out_path,
                    channel=args.channel,
                    invert=invert,
                    bigtiff=args.bigtiff or None,
                    progress=progress,
                )
                print('Done.')
            else:
                # All channels.
                base = args.out if args.out else args.input
                paths = pyscanbox.io.tiff_exporter.save_all_channels_as_tiff(
                    reader, base,
                    invert=invert,
                    bigtiff=args.bigtiff or None,
                    progress=progress,
                )
                print(f'Done. Written: {", ".join(paths)}')

    except FileNotFoundError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
    except IndexError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
    except ImportError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
