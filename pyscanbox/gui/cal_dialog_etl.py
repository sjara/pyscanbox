# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""ETL (Electrically Tunable Lens) calibration dialog.

Provides a non-modal dialog for:

1. Entering (ETL current, depth) measurement pairs collected manually
   by positioning the ETL at known current values and measuring the
   resulting focal depth (e.g., with a calibrated stage or ruler).
2. Fitting a degree-2 polynomial to those measurements.
3. Saving the calibration to ``etl_cal.json`` alongside the active config.

Usage::

    dialog = EtlCalibrationDialog(config_path=path)
    dialog.show()   # non-modal — main window remains interactive

The dialog auto-loads an existing ``etl_cal.json`` when *config_path* is
provided.  Matplotlib is used for the curve preview; when it is unavailable a
text-only fallback is shown.
"""

import logging
import os

import numpy as np
import PyQt6.QtCore as QtCore
import PyQt6.QtWidgets as QtWidgets

from pyscanbox.calibration import etl as etl_calibration


logger = logging.getLogger(__name__)

try:
    import matplotlib
    import matplotlib.style
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    import matplotlib.figure as mpl_figure
    matplotlib.style.use('dark_background')
    _MATPLOTLIB_AVAILABLE = True
except ImportError:
    _MATPLOTLIB_AVAILABLE = False


class EtlCalibrationDialog(QtWidgets.QDialog):
    """Non-modal dialog for ETL polynomial calibration.

    Data entry
    ----------
    The user sets the ETL current on the main GUI slider, measures the
    resulting focal depth (e.g., by moving the stage to a reference plane),
    and enters each (ETL current, depth) pair in the measurement table.

    Workflow
    --------
    1. Set an ETL current value (0–1760) via the main window ETL slider.
    2. Measure the resulting focal depth in microns.
    3. Enter the pair in the table.
    4. Repeat for at least 3 values covering the desired ETL range.
    5. Click **Fit Curve** to compute the polynomial and preview the fit.
    6. Click **Save Calibration** to persist the result.

    Signals:
        calibration_saved: Emitted after a successful save.  Carries the
            3-element coefficient array ``[a, b, c]`` as an ``ndarray``.
    """

    calibration_saved = QtCore.pyqtSignal(object)

    def __init__(
        self,
        config_path: str | None = None,
        cal_filename: str | None = None,
        value_getter=None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        """Initialise the dialog.

        Args:
            config_path: Path to the active YAML config file.  When provided
                the dialog auto-loads the calibration file from the same
                directory and uses it as the default save location.
            cal_filename: Calibration filename override from config
                (``optotune.calibration_file``).  Defaults to
                ``etl_calibration.DEFAULT_CALIBRATION_FILE`` when ``None``.
            value_getter: Optional callable returning the current ETL current
                as an ``int``.  When provided, "Add Row" pre-fills the ETL
                current column with the live slider value.
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self._config_path = config_path
        self._cal_filename = cal_filename
        self._value_getter = value_getter

        # Most recently fitted calibration state.
        self._coeffs: np.ndarray | None = None

        self.setWindowTitle('ETL Calibration')
        self.setMinimumSize(780, 480)

        self._init_ui()

        # Auto-load an existing calibration alongside the config.
        if self._config_path is not None:
            cal_path = etl_calibration.calibration_path(
                self._config_path, self._cal_filename
            )
            if os.path.exists(cal_path):
                self._apply_calibration(
                    etl_calibration.load_calibration(cal_path), cal_path
                )

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.addWidget(self._build_left_panel(), stretch=1)
        main_layout.addWidget(self._build_right_panel(), stretch=1)

    def _build_left_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setSpacing(8)

        # --- Measurement table ----------------------------------------
        table_label = QtWidgets.QLabel(
            'Measurements — set the ETL current on the main window slider\n'
            'and enter each (ETL current, depth) pair below:'
        )
        table_label.setWordWrap(True)

        self._table = QtWidgets.QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(
            ['ETL Current (0–1760)', 'Depth (µm)']
        )
        self._table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self._table.setMinimumHeight(200)
        self._table.setToolTip(
            'ETL current: hardware units 0–1760.\n'
            'Depth: measured focal depth in microns (positive = deeper).'
        )

        btn_row = QtWidgets.QHBoxLayout()
        self._add_row_btn = QtWidgets.QPushButton('Add Row')
        self._remove_row_btn = QtWidgets.QPushButton('Remove Row')
        self._clear_btn = QtWidgets.QPushButton('Clear All')
        btn_row.addWidget(self._add_row_btn)
        btn_row.addWidget(self._remove_row_btn)
        btn_row.addWidget(self._clear_btn)

        # --- Fit button + result label ---------------------------------
        self._fit_btn = QtWidgets.QPushButton('Fit Curve')
        self._fit_btn.setToolTip(
            'Fit depth = a·I² + b·I + c to the measurements.'
        )

        self._fit_result_label = QtWidgets.QLabel('Fit: not yet performed')
        self._fit_result_label.setWordWrap(True)
        self._fit_result_label.setMinimumHeight(80)
        self._fit_result_label.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self._fit_result_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft
        )

        # --- Action buttons -------------------------------------------
        self._save_btn = QtWidgets.QPushButton('Save Calibration…')
        self._save_btn.setEnabled(False)
        self._save_btn.setToolTip('Save polynomial coefficients to etl_cal.json.')
        self._load_btn = QtWidgets.QPushButton('Load Calibration…')
        self._load_btn.setToolTip('Load a previously saved etl_cal.json file.')

        action_row = QtWidgets.QHBoxLayout()
        action_row.addWidget(self._save_btn)
        action_row.addWidget(self._load_btn)

        layout.addWidget(table_label)
        layout.addWidget(self._table)
        layout.addLayout(btn_row)
        layout.addWidget(self._fit_btn)
        layout.addWidget(self._fit_result_label)
        layout.addStretch()
        layout.addLayout(action_row)

        # Connections
        self._add_row_btn.clicked.connect(self._on_add_row)
        self._remove_row_btn.clicked.connect(self._on_remove_row)
        self._clear_btn.clicked.connect(self._on_clear_table)
        self._fit_btn.clicked.connect(self._on_fit)
        self._save_btn.clicked.connect(self._on_save)
        self._load_btn.clicked.connect(self._on_load)

        return panel

    def _build_right_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)

        if _MATPLOTLIB_AVAILABLE:
            self._fig = mpl_figure.Figure(figsize=(4.5, 4.5))
            self._canvas = FigureCanvasQTAgg(self._fig)
            self._ax = self._fig.add_subplot(111)
            self._ax.set_xlabel('ETL Current (0–1760)')
            self._ax.set_ylabel('Depth (µm)')
            self._ax.set_title('ETL Current → Depth')
            self._fig.tight_layout()
            layout.addWidget(self._canvas)
        else:
            hint = QtWidgets.QLabel(
                'Install matplotlib for a graphical preview:\n'
                '  pip install matplotlib'
            )
            hint.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(hint)

        return panel

    # ------------------------------------------------------------------
    # Slot implementations
    # ------------------------------------------------------------------

    def _on_add_row(self) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        if self._value_getter is not None:
            try:
                current_val = str(int(self._value_getter()))
            except Exception:  # pylint: disable=broad-except
                current_val = '0'
        else:
            current_val = '0'
        self._table.setItem(row, 0, QtWidgets.QTableWidgetItem(current_val))
        self._table.setItem(row, 1, QtWidgets.QTableWidgetItem('0'))
        self._table.scrollToBottom()
        self._table.setCurrentCell(row, 1)

    def _on_remove_row(self) -> None:
        selected = sorted(
            {idx.row() for idx in self._table.selectedIndexes()},
            reverse=True,
        )
        if selected:
            for row in selected:
                self._table.removeRow(row)
        elif self._table.rowCount() > 0:
            self._table.removeRow(self._table.rowCount() - 1)

    def _on_clear_table(self) -> None:
        self._table.setRowCount(0)
        self._coeffs = None
        self._fit_result_label.setText('Fit: not yet performed')
        self._save_btn.setEnabled(False)
        if _MATPLOTLIB_AVAILABLE:
            self._ax.cla()
            self._ax.set_xlabel('ETL Current (0–1760)')
            self._ax.set_ylabel('Depth (µm)')
            self._ax.set_title('ETL Current → Depth')
            self._canvas.draw()

    def _read_table_data(self):
        """Parse (etl_values, depths) from the table.

        Returns:
            Tuple ``(etl_values, depths)`` as float arrays, or ``None`` on
            parse error or insufficient data.
        """
        n = self._table.rowCount()
        etl_values = []
        depths = []
        for i in range(n):
            try:
                etl = float(self._table.item(i, 0).text().strip())
                depth = float(self._table.item(i, 1).text().strip())
            except (ValueError, AttributeError):
                QtWidgets.QMessageBox.warning(
                    self, 'Invalid entry',
                    f'Row {i + 1}: could not parse values.\n'
                    'ETL current and depth must both be numbers.',
                )
                return None
            if not (0 <= etl <= 1760):
                QtWidgets.QMessageBox.warning(
                    self, 'Invalid entry',
                    f'Row {i + 1}: ETL current {etl} is outside 0–1760.',
                )
                return None
            etl_values.append(etl)
            depths.append(depth)
        if len(etl_values) < 3:
            QtWidgets.QMessageBox.warning(
                self, 'Not enough data',
                'At least 3 measurement points are needed to fit the curve.',
            )
            return None
        return np.asarray(etl_values, dtype=float), np.asarray(depths, dtype=float)

    def _on_fit(self) -> None:
        data = self._read_table_data()
        if data is None:
            return
        etl_values, depths = data

        try:
            coeffs, r_sq = etl_calibration.fit_etl_curve(etl_values, depths)
        except Exception as exc:  # pylint: disable=broad-except
            QtWidgets.QMessageBox.critical(
                self, 'Fit failed',
                f'Polynomial fitting failed:\n{exc}',
            )
            return

        self._coeffs = coeffs
        self._fit_result_label.setText(
            f'Model: depth = a·I² + b·I + c\n'
            f'  a = {coeffs[0]:.6g}\n'
            f'  b = {coeffs[1]:.6g}\n'
            f'  c = {coeffs[2]:.6g}\n'
            f'  R² = {r_sq:.6f}'
        )
        self._save_btn.setEnabled(True)

        if _MATPLOTLIB_AVAILABLE:
            self._update_fit_plot(etl_values, depths, coeffs)

    def _update_fit_plot(
        self,
        etl_values: np.ndarray,
        depths: np.ndarray,
        coeffs: np.ndarray,
    ) -> None:
        self._ax.cla()
        self._ax.scatter(
            etl_values, depths,
            color='steelblue', zorder=5, label='Measured',
        )
        x_fit = np.linspace(etl_values.min(), etl_values.max(), 400)
        y_fit = np.polyval(coeffs, x_fit)
        self._ax.plot(x_fit, y_fit, color='tomato', linewidth=1.5, label='Fit')
        self._ax.set_xlabel('ETL Current (0–1760)')
        self._ax.set_ylabel('Depth (µm)')
        self._ax.set_title('ETL Current → Depth')
        self._ax.legend(fontsize=8)
        self._fig.tight_layout()
        self._canvas.draw()

    def _on_save(self) -> None:
        if self._coeffs is None:
            return
        if self._config_path is not None:
            default_path = etl_calibration.calibration_path(
                self._config_path, self._cal_filename
            )
        else:
            default_path = (
                self._cal_filename or etl_calibration.DEFAULT_CALIBRATION_FILE
            )
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Save ETL Calibration', default_path,
            'JSON files (*.json);;All files (*)',
        )
        if not path:
            return
        note, ok = QtWidgets.QInputDialog.getText(
            self, 'Calibration note',
            'Optional note (e.g. objective, sample type):',
            text='',
        )
        if not ok:
            note = ''
        try:
            etl_calibration.save_calibration(path, self._coeffs, note=note)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(
                self, 'Save failed',
                f'Could not write calibration file:\n{exc}',
            )
            return
        QtWidgets.QMessageBox.information(
            self, 'Saved', f'Calibration saved to:\n{path}',
        )
        self.calibration_saved.emit(self._coeffs.copy())

    def _on_load(self) -> None:
        default_dir = ''
        if self._config_path is not None:
            default_dir = os.path.dirname(os.path.abspath(self._config_path))
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Load ETL Calibration', default_dir,
            'JSON files (*.json);;All files (*)',
        )
        if not path:
            return
        coeffs = etl_calibration.load_calibration(path)
        if coeffs is None:
            QtWidgets.QMessageBox.critical(
                self, 'Load failed',
                f'Could not load a valid calibration from:\n{path}',
            )
            return
        self._apply_calibration(coeffs, path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_calibration(
        self, coeffs: np.ndarray | None, path: str
    ) -> None:
        """Apply loaded coefficients to the dialog state.

        Args:
            coeffs: 3-element ndarray ``[a, b, c]``, or ``None`` (no-op).
            path: Source file path (used for status label).
        """
        if coeffs is None:
            return
        self._coeffs = coeffs
        self._fit_result_label.setText(
            f'Loaded from: {os.path.basename(path)}\n'
            f'  a = {coeffs[0]:.6g}\n'
            f'  b = {coeffs[1]:.6g}\n'
            f'  c = {coeffs[2]:.6g}'
        )
        self._save_btn.setEnabled(True)

        if _MATPLOTLIB_AVAILABLE:
            i_fit = np.linspace(0, 1760, 400)
            d_fit = np.polyval(coeffs, i_fit)
            self._ax.cla()
            self._ax.plot(i_fit, d_fit, color='tomato', linewidth=1.5, label='Fit')
            self._ax.set_xlabel('ETL Current (0–1760)')
            self._ax.set_ylabel('Depth (µm)')
            self._ax.set_title(f'ETL Calibration  ({os.path.basename(path)})')
            self._ax.legend(fontsize=8)
            self._fig.tight_layout()
            self._canvas.draw()
