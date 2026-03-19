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

import PyQt6.QtWidgets as QtWidgets
import PyQt6.QtCore as QtCore
import qdarktheme

import pyscanbox
from pyscanbox import config as config_mod
from pyscanbox import gui as gui_mod


def run(cfg, config_path, frame_data_callback=None):
    """Create the Qt application and main window, then start the event loop.

    Args:
        cfg: Loaded configuration object.
        config_path: Absolute path to the config file (passed to MainWindow).
        frame_data_callback: Optional callable connected to the
            ``frame_data_ready`` signal after window creation.  Intended for
            development tools (e.g. per-frame stats printing).
    """
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName('pyscanbox')
    app.setOrganizationName('pyscanbox')
    app.setApplicationVersion(pyscanbox.__version__)

    stylesheet = qdarktheme.load_stylesheet()
    stylesheet += """
        QSlider::add-page {
            background-color: rgba(25, 45, 80, 1.0);
        }
        QDockWidget::title {
            background-color: palette(window);
            padding-left: 6px;
        }
    """
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

    # Install an exception hook so exceptions in Qt slots are visible in full.
    def _qt_exception_hook(exc_type, exc_value, exc_tb):
        print('\n--- Unhandled exception in Qt slot ---', file=sys.stderr)
        traceback.print_exception(exc_type, exc_value, exc_tb)
        print('--------------------------------------\n', file=sys.stderr)

    sys.excepthook = _qt_exception_hook

    # Bundled fallback config (used when no user/system config is found).
    _pkg_dir = os.path.dirname(__file__)
    dev_fallback = os.path.join(
        _pkg_dir, '..', 'examples', 'config_examples', 'default_config.yaml'
    )

    config_path = args.config
    try:
        cfg = config_mod.load_config(config_path)
        config_path = config_path or config_mod.find_config()
    except FileNotFoundError:
        if config_path is not None:
            print(f'Error: config file not found: {config_path}')
            sys.exit(1)
        try:
            cfg = config_mod.load_config(dev_fallback)
            config_path = dev_fallback
            print('Note: no user config found, using bundled example config.')
        except FileNotFoundError as exc:
            print(f'Error: {exc}')
            sys.exit(1)

    cfg.emulation['enabled'] = args.emulation
    if args.emulation:
        print('Emulation mode enabled.')
    else:
        print('⚠  Real hardware mode — ensure you are on the Windows rig.')

    print(f'Config:    {os.path.abspath(config_path)}')
    print(f'Emulation: {args.emulation}')

    run(cfg, os.path.abspath(config_path))
