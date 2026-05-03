# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Main application entry point for pyscanbox.

This module provides ``main()`` (the installed console-script entry point)
and ``run()`` (the Qt startup function, callable by other entry points such
as ``examples/gui_example.py``).

Invocation::

    # After installation — real hardware (default):
    pyscanbox

    # Emulation mode (development on Linux):
    pyscanbox --emulation

    # As a Python module (no installation required):
    python -m pyscanbox

    # Custom config file:
    pyscanbox --config path/to/config.yaml

    # Debug logging:
    pyscanbox --verbose
"""

import argparse
import logging
import os
import signal
import sys
import traceback

import pyscanbox
from pyscanbox import config as config_mod
# PyQt6, qdarktheme, and pyscanbox.gui are imported inside run() to keep
# --version and other non-GUI entry points fast.


def run(cfg, config_path, frame_data_callback=None):
    """Create the Qt application and main window, then start the event loop.

    Args:
        cfg: Loaded configuration object.
        config_path: Absolute path to the config file (passed to MainWindow).
        frame_data_callback: Optional callable connected to the
            ``frame_data_ready`` signal after window creation.  Intended for
            development tools (e.g. per-frame stats printing).
    """
    # pylint: disable=import-outside-toplevel
    import PyQt6.QtWidgets as QtWidgets
    import PyQt6.QtCore as QtCore
    import PyQt6.QtGui as QtGui
    import qdarktheme
    from pyscanbox import gui as gui_mod

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName('pyscanbox')
    app.setOrganizationName('pyscanbox')
    app.setApplicationVersion(pyscanbox.__version__)

    # Set application icon from the docs/assets directory.
    icon_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        'docs', 'assets', 'icon_blue.svg'
    )
    if os.path.exists(icon_path):
        app.setWindowIcon(QtGui.QIcon(icon_path))

    stylesheet = qdarktheme.load_stylesheet()
    stylesheet += """
        QSlider::add-page {
            background-color: rgba(25, 45, 80, 1.0);
        }
        QDockWidget::title {
            background-color: rgba(42, 43, 46, 1.0);
            padding-left: 6px;
        }
    """
    # background-color: palette(window);
    #3f4042
    app.setStyleSheet(stylesheet)

    # Allow Ctrl-C to terminate the application from the terminal.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    heartbeat = QtCore.QTimer()
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start(100)

    window = gui_mod.MainWindow(config=cfg, config_path=config_path)

    if frame_data_callback is not None:
        window._ctrl.frame_data_ready.connect(frame_data_callback)

    window.show()
    sys.exit(app.exec())


def main():
    """Launch the pyscanbox GUI application."""
    parser = argparse.ArgumentParser(
        description='Two-Photon Microscope Control Software'
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {pyscanbox.__version__}',
        help='Show version and exit',
    )
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help=(
            'Path to YAML configuration file '
            '(default: search standard locations, then bundled example)'
        ),
    )
    parser.add_argument(
        '--emulation',
        action='store_true',
        help='Enable hardware emulation (for development without hardware)',
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable DEBUG logging (shows hardware calls, slot activity, etc.)',
    )
    args = parser.parse_args()

    # Configure logging.
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s  %(levelname)-8s  %(name)s: %(message)s',
        datefmt='%H:%M:%S',
    )
    logging.getLogger('numba').setLevel(logging.WARNING)

    # Defer terminal handler setup until after config is loaded (see below).

    # Install an exception hook so exceptions in Qt slots are visible in full.
    def _qt_exception_hook(exc_type, exc_value, exc_tb):
        print('\n--- Unhandled exception in Qt slot ---', file=sys.stderr)
        traceback.print_exception(exc_type, exc_value, exc_tb)
        print('--------------------------------------\n', file=sys.stderr)

    sys.excepthook = _qt_exception_hook

    config_path = args.config
    try:
        cfg = config_mod.load_config(config_path)
        config_path = config_path or config_mod.find_config()
    except FileNotFoundError as exc:
        print(f'Error: {exc}')
        sys.exit(1)

    print(f'————  pyscanbox v{pyscanbox.__version__}  ————')

    # Add a StreamHandler on the pyscanbox logger at the level from config,
    # unless --verbose was passed (root logger already captures everything).
    if not args.verbose:
        terminal_level_name = cfg.terminal.get('log_level', 'INFO')
        terminal_level = getattr(logging, terminal_level_name.upper(), logging.INFO)
        _handler = logging.StreamHandler()
        _handler.setLevel(terminal_level)
        _handler.setFormatter(logging.Formatter(
            fmt='%(asctime)s  %(levelname)-8s  %(message)s',
            datefmt='%H:%M:%S',
        ))
        _psb_logger = logging.getLogger('pyscanbox')
        _psb_logger.setLevel(terminal_level)
        _psb_logger.addHandler(_handler)
        _psb_logger.propagate = False

    cfg.emulation['enabled'] = args.emulation
    if args.emulation:
        print('Emulation mode enabled.')
    else:
        print('⚠  Real hardware mode — ensure you are on the Windows rig.')

    print(f'Config:    {os.path.abspath(config_path)}')
    #print(f'Emulation: {args.emulation}')

    run(cfg, os.path.abspath(config_path))
