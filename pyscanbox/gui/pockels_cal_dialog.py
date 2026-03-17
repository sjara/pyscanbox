"""Pockels cell linearisation calibration dialog.

Provides a non-modal dialog for:

1. Entering (DAC level, laser power) measurement pairs collected manually
   using a power meter while stepping through Pockels levels from the main
   GUI window.
2. Fitting the sin² voltage-to-power model to those measurements.
3. Generating the 256-entry linearisation LUT and uploading it to the PSoC5.
4. Saving the calibration to ``pockels_cal.json`` alongside the active config.

Usage::

    dialog = PockelsCalibrationDialog(controller=ctrl, config_path=path)
    dialog.show()   # non-modal — main window remains interactive

The dialog auto-loads an existing ``pockels_cal.json`` when *config_path* is
provided.  Matplotlib is used for the curve preview; when it is unavailable a
text-only fallback is shown.
"""

import logging
import os

import numpy as np
import PyQt6.QtCore as QtCore
import PyQt6.QtWidgets as QtWidgets

from pyscanbox.calibration import pockels as pockels_cal


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


class PockelsCalibrationDialog(QtWidgets.QDialog):
    """Non-modal dialog for Pockels cell linearisation LUT calibration.

    Data entry
    ----------
    The user steps the Pockels level from the main GUI laser-power slider and
    records the power meter reading.  Each (DAC level, power) pair is entered
    manually in the measurement table.

    Workflow
    --------
    1. Set a Pockels DAC level (0–255) via the main window laser slider.
    2. Read the power meter and type the value in the *Power (mW)* column.
    3. Repeat for ~15–25 levels covering the range 0 to the sin² maximum
       (usually around DAC 150–200 for 920 nm).
    4. Click **Fit Curve** to compute parameters and preview the fit.
    5. Click **Upload LUT to Hardware** to linearise the PSoC5 response.
    6. Click **Save Calibration** to persist the result.

    Signals:
        lut_uploaded: Emitted after a successful LUT upload to hardware.
            Carries the 256-entry LUT list.
    """

    lut_uploaded = QtCore.pyqtSignal(list)

    def __init__(self, controller=None, config_path=None, cal_filename=None, value_getter=None, parent=None):
        """Initialise the dialog.

        Args:
            controller: :class:`~pyscanbox.gui.app_controller.AppController`
                instance used to upload the LUT to hardware.  When ``None``
                the *Upload* button is disabled (offline / design mode).
            config_path: Path to the active YAML config file.  When provided
                the dialog auto-loads the calibration file from the same
                directory and uses it as the default save location.
            cal_filename: Calibration filename override from config
                (``pockels.calibration_file``).  Defaults to
                ``pockels_cal.DEFAULT_CALIBRATION_FILE`` when ``None``.
            value_getter: Optional callable returning the current Pockels DAC
                level (0–255) as an ``int``.  When provided, "Add Row"
                pre-fills the DAC level column with the live slider value.
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self._controller = controller
        self._config_path = config_path
        self._cal_filename = cal_filename
        self._value_getter = value_getter

        # Most recently fitted calibration state.
        self._lut: list | None = None
        self._amplitude: float | None = None
        self._frequency: float | None = None
        self._max_voltage: float = pockels_cal.DEFAULT_MAX_VOLTAGE

        self.setWindowTitle('Pockels Cell Calibration')
        self.setMinimumSize(820, 520)

        self._init_ui()

        # Try to auto-load an existing calibration alongside the config.
        if self._config_path is not None:
            cal_path = pockels_cal.calibration_path(self._config_path, self._cal_filename)
            if os.path.exists(cal_path):
                self._apply_calibration(pockels_cal.load_calibration(cal_path), cal_path)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        """Build the dialog layout."""
        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setSpacing(12)

        main_layout.addWidget(self._build_left_panel(), stretch=1)
        main_layout.addWidget(self._build_right_panel(), stretch=1)

    def _build_left_panel(self) -> QtWidgets.QWidget:
        """Build the data-entry / controls panel (left side)."""
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setSpacing(8)

        # --- Measurement table ----------------------------------------
        table_label = QtWidgets.QLabel(
            'Measurements — step the laser-power slider on the main window\n'
            'and enter each (DAC level, power reading) pair below:'
        )
        table_label.setWordWrap(True)

        self._table = QtWidgets.QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(['DAC Level (0–255)', 'Power (mW)'])
        self._table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self._table.setMinimumHeight(200)
        self._table.setToolTip(
            'DAC level: the hardware Pockels value (0–255).\n'
            'The main-window laser slider (0–100 %) maps to 0–255 via\n'
            '  DAC = round(percent × 2.55).'
        )

        btn_row = QtWidgets.QHBoxLayout()
        self._add_row_btn = QtWidgets.QPushButton('Add Row')
        self._remove_row_btn = QtWidgets.QPushButton('Remove Row')
        self._clear_btn = QtWidgets.QPushButton('Clear All')
        btn_row.addWidget(self._add_row_btn)
        btn_row.addWidget(self._remove_row_btn)
        btn_row.addWidget(self._clear_btn)

        # --- Hardware parameter ----------------------------------------
        volt_group = QtWidgets.QGroupBox('Hardware parameter')
        volt_layout = QtWidgets.QHBoxLayout(volt_group)
        volt_layout.addWidget(QtWidgets.QLabel('PSoC5 max DAC voltage (V):'))
        self._max_voltage_spin = QtWidgets.QDoubleSpinBox()
        self._max_voltage_spin.setRange(0.5, 5.0)
        self._max_voltage_spin.setSingleStep(0.001)
        self._max_voltage_spin.setDecimals(3)
        self._max_voltage_spin.setValue(pockels_cal.DEFAULT_MAX_VOLTAGE)
        self._max_voltage_spin.setToolTip(
            'PSoC5 DAC full-scale voltage.  DAC value 255 maps to this\n'
            'voltage.  Default 2.040 V (from pockels_920nm.m).'
        )
        volt_layout.addWidget(self._max_voltage_spin)
        volt_layout.addStretch()

        # --- Fit button + result label ---------------------------------
        self._fit_btn = QtWidgets.QPushButton('Fit Curve')
        self._fit_btn.setToolTip('Fit P = A · sin(V · k)² to the measurements.')

        self._fit_result_label = QtWidgets.QLabel('Fit: not yet performed')
        self._fit_result_label.setWordWrap(True)
        self._fit_result_label.setMinimumHeight(80)
        self._fit_result_label.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self._fit_result_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft
        )

        # --- Action buttons -------------------------------------------
        self._upload_btn = QtWidgets.QPushButton('Upload LUT to Hardware')
        self._upload_btn.setEnabled(False)
        self._upload_btn.setToolTip(
            'Send the 256-entry linearisation LUT to the PSoC5.\n'
            'Requires a fitted calibration and an open hardware connection.'
        )
        self._save_btn = QtWidgets.QPushButton('Save Calibration…')
        self._save_btn.setEnabled(False)
        self._save_btn.setToolTip('Save LUT and fit parameters to pockels_cal.json.')
        self._load_btn = QtWidgets.QPushButton('Load Calibration…')
        self._load_btn.setToolTip('Load a previously saved pockels_cal.json file.')

        action_row = QtWidgets.QHBoxLayout()
        action_row.addWidget(self._save_btn)
        action_row.addWidget(self._load_btn)

        layout.addWidget(table_label)
        layout.addWidget(self._table)
        layout.addLayout(btn_row)
        layout.addWidget(volt_group)
        layout.addWidget(self._fit_btn)
        layout.addWidget(self._fit_result_label)
        layout.addStretch()
        layout.addWidget(self._upload_btn)
        layout.addLayout(action_row)

        # Connections
        self._add_row_btn.clicked.connect(self._on_add_row)
        self._remove_row_btn.clicked.connect(self._on_remove_row)
        self._clear_btn.clicked.connect(self._on_clear_table)
        self._fit_btn.clicked.connect(self._on_fit)
        self._upload_btn.clicked.connect(self._on_upload_lut)
        self._save_btn.clicked.connect(self._on_save)
        self._load_btn.clicked.connect(self._on_load)

        return panel

    def _build_right_panel(self) -> QtWidgets.QWidget:
        """Build the curve-preview panel (right side)."""
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)

        if _MATPLOTLIB_AVAILABLE:
            self._fig = mpl_figure.Figure(figsize=(4.5, 3.5))
            self._canvas = FigureCanvasQTAgg(self._fig)
            self._ax = self._fig.add_subplot(111)
            self._ax.set_xlabel('DAC Level (0–255)')
            self._ax.set_ylabel('Power (mW)')
            self._ax.set_title('Pockels Cell Power Response')
            self._fig.tight_layout()
            layout.addWidget(self._canvas)

            lut_label = QtWidgets.QLabel('LUT preview (DAC level → PSoC DAC value):')
            layout.addWidget(lut_label)
            self._lut_canvas = FigureCanvasQTAgg(
                mpl_figure.Figure(figsize=(4.5, 2.0))
            )
            self._lut_ax = self._lut_canvas.figure.add_subplot(111)
            self._lut_ax.set_xlabel('Power index (0–255)')
            self._lut_ax.set_ylabel('DAC value')
            self._lut_ax.set_title('Linearisation LUT')
            self._lut_canvas.figure.tight_layout()
            layout.addWidget(self._lut_canvas)
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
        """Append a blank measurement row to the table."""
        row = self._table.rowCount()
        self._table.insertRow(row)
        if self._value_getter is not None:
            try:
                dac_val = str(int(self._value_getter()))
            except Exception:  # pylint: disable=broad-except
                dac_val = '0'
        else:
            dac_val = '0'
        self._table.setItem(row, 0, QtWidgets.QTableWidgetItem(dac_val))
        self._table.setItem(row, 1, QtWidgets.QTableWidgetItem('0.0'))
        self._table.scrollToBottom()
        self._table.setCurrentCell(row, 1)

    def _on_remove_row(self) -> None:
        """Remove the selected row(s), or the last row if none is selected."""
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
        """Remove all rows and reset fit state."""
        self._table.setRowCount(0)
        self._lut = None
        self._amplitude = None
        self._frequency = None
        self._fit_result_label.setText('Fit: not yet performed')
        self._upload_btn.setEnabled(False)
        self._save_btn.setEnabled(False)
        if _MATPLOTLIB_AVAILABLE:
            self._ax.cla()
            self._ax.set_xlabel('DAC Level (0–255)')
            self._ax.set_ylabel('Power (mW)')
            self._ax.set_title('Pockels Cell Power Response')
            self._canvas.draw()
            self._lut_ax.cla()
            self._lut_ax.set_xlabel('Power index (0–255)')
            self._lut_ax.set_ylabel('DAC value')
            self._lut_ax.set_title('Linearisation LUT')
            self._lut_canvas.draw()

    def _read_table_data(self):
        """Parse (dac_levels, powers) from the table.

        Returns:
            Tuple ``(dac_levels, powers)`` as float arrays, or ``None`` on
            parse error or insufficient data.
        """
        n = self._table.rowCount()
        dac_levels = []
        powers = []
        for i in range(n):
            try:
                dac = int(self._table.item(i, 0).text().strip())
                pwr = float(self._table.item(i, 1).text().strip())
            except (ValueError, AttributeError):
                QtWidgets.QMessageBox.warning(
                    self, 'Invalid entry',
                    f'Row {i + 1}: could not parse values.\n'
                    'DAC level must be an integer (0–255); '
                    'power must be a number.',
                )
                return None
            if not (0 <= dac <= 255):
                QtWidgets.QMessageBox.warning(
                    self, 'Invalid entry',
                    f'Row {i + 1}: DAC level {dac} is outside 0–255.',
                )
                return None
            dac_levels.append(dac)
            powers.append(pwr)
        if len(dac_levels) < 4:
            QtWidgets.QMessageBox.warning(
                self, 'Not enough data',
                'At least 4 measurement points are needed to fit the curve.',
            )
            return None
        return np.asarray(dac_levels, dtype=float), np.asarray(powers, dtype=float)

    def _on_fit(self) -> None:
        """Fit sin² to table data and update plot and LUT."""
        data = self._read_table_data()
        if data is None:
            return
        dac_levels, powers = data
        max_voltage = self._max_voltage_spin.value()

        try:
            amplitude, frequency, r_sq = pockels_cal.fit_pockels_curve(
                dac_levels, powers, max_voltage=max_voltage,
            )
        except Exception as exc:  # pylint: disable=broad-except
            QtWidgets.QMessageBox.critical(
                self, 'Fit failed',
                f'Curve fitting failed:\n{exc}\n\n'
                'Check that the measurements cover the sin² maximum\n'
                'and that no duplicate DAC levels are present.',
            )
            return

        lut = pockels_cal.generate_lut(amplitude, frequency, max_voltage)

        self._amplitude = amplitude
        self._frequency = frequency
        self._max_voltage = max_voltage
        self._lut = lut

        v_at_max = np.pi / (2.0 * frequency)
        dac_at_max = v_at_max / max_voltage * 255.0
        self._fit_result_label.setText(
            f'Model: P = A · sin(V · k)²\n'
            f'  A (max power)   = {amplitude:.2f} mW\n'
            f'  k (frequency)   = {frequency:.4f} rad/V\n'
            f'  First maximum   = {v_at_max:.3f} V  (DAC ≈ {dac_at_max:.0f})\n'
            f'  R²              = {r_sq:.6f}'
        )

        has_hw = self._controller is not None and getattr(
            self._controller, 'is_open', False
        )
        self._upload_btn.setEnabled(has_hw)
        self._save_btn.setEnabled(True)

        if _MATPLOTLIB_AVAILABLE:
            self._update_fit_plot(dac_levels, powers, amplitude, frequency, max_voltage)
            self._update_lut_plot(lut)

    def _update_fit_plot(
        self,
        dac_levels: np.ndarray,
        powers: np.ndarray,
        amplitude: float,
        frequency: float,
        max_voltage: float,
    ) -> None:
        """Redraw the power-response plot with measurements and fit curve."""
        self._ax.cla()
        self._ax.scatter(
            dac_levels, powers,
            color='steelblue', zorder=5, label='Measured',
        )
        x_fit = np.linspace(0, 255, 512)
        v_fit = x_fit / 255.0 * max_voltage
        y_fit = amplitude * np.sin(v_fit * frequency) ** 2
        self._ax.plot(x_fit, y_fit, color='tomato', linewidth=1.5, label='Fit')
        self._ax.set_xlabel('DAC Level (0–255)')
        self._ax.set_ylabel('Power (mW)')
        self._ax.set_title('Pockels Cell Power Response')
        self._ax.legend(fontsize=8)
        self._fig.tight_layout()
        self._canvas.draw()

    def _update_lut_plot(self, lut: list) -> None:
        """Redraw the LUT preview (power index → DAC value)."""
        self._lut_ax.cla()
        self._lut_ax.plot(
            range(pockels_cal.LUT_SIZE), lut,
            color='mediumseagreen', linewidth=1.5,
        )
        self._lut_ax.set_xlabel('Power index (0–255)')
        self._lut_ax.set_ylabel('DAC value')
        self._lut_ax.set_title('Linearisation LUT')
        self._lut_canvas.figure.tight_layout()
        self._lut_canvas.draw()

    def _on_upload_lut(self) -> None:
        """Upload the fitted LUT to the PSoC5 via AppController."""
        if self._lut is None:
            return
        if self._controller is None:
            QtWidgets.QMessageBox.warning(
                self, 'No hardware connection',
                'Hardware is not connected.',
            )
            return
        try:
            self._controller.upload_pockels_lut(self._lut)
        except Exception as exc:  # pylint: disable=broad-except
            QtWidgets.QMessageBox.critical(
                self, 'Upload failed',
                f'Failed to upload LUT to hardware:\n{exc}',
            )
            return
        self.lut_uploaded.emit(self._lut)
        QtWidgets.QMessageBox.information(
            self, 'Upload complete',
            f'{pockels_cal.LUT_SIZE}-entry linearisation LUT uploaded '
            'to PSoC5 successfully.',
        )

    def _on_save(self) -> None:
        """Show save dialog and write pockels_cal.json."""
        if self._lut is None:
            return
        if self._config_path is not None:
            default_path = pockels_cal.calibration_path(self._config_path, self._cal_filename)
        else:
            default_path = self._cal_filename or pockels_cal.DEFAULT_CALIBRATION_FILE
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Save Pockels Calibration', default_path,
            'JSON files (*.json);;All files (*)',
        )
        if not path:
            return
        note, ok = QtWidgets.QInputDialog.getText(
            self, 'Calibration note',
            'Optional note (e.g. laser wavelength, objective):',
            text='',
        )
        if not ok:
            note = ''
        try:
            pockels_cal.save_calibration(
                path, self._lut,
                self._amplitude, self._frequency,
                max_voltage=self._max_voltage,
                note=note,
            )
        except OSError as exc:
            QtWidgets.QMessageBox.critical(
                self, 'Save failed',
                f'Could not write calibration file:\n{exc}',
            )
            return
        QtWidgets.QMessageBox.information(
            self, 'Saved', f'Calibration saved to:\n{path}',
        )

    def _on_load(self) -> None:
        """Show open dialog and load a pockels_cal.json file."""
        default_dir = ''
        if self._config_path is not None:
            default_dir = os.path.dirname(os.path.abspath(self._config_path))
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Load Pockels Calibration', default_dir,
            'JSON files (*.json);;All files (*)',
        )
        if not path:
            return
        cal = pockels_cal.load_calibration(path)
        if cal is None:
            QtWidgets.QMessageBox.critical(
                self, 'Load failed',
                f'Could not load a valid calibration from:\n{path}',
            )
            return
        self._apply_calibration(cal, path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_calibration(self, cal: dict | None, path: str) -> None:
        """Apply a loaded calibration dict to the dialog state.

        Args:
            cal: Dict returned by :func:`~pockels_cal.load_calibration`, or
                ``None`` (no-op).
            path: Source file path (used for status label).
        """
        if cal is None:
            return
        self._lut = cal['lut']
        self._amplitude = cal.get('amplitude')
        self._frequency = cal.get('frequency')
        self._max_voltage = cal.get('max_voltage', pockels_cal.DEFAULT_MAX_VOLTAGE)
        self._max_voltage_spin.setValue(self._max_voltage)

        date = cal.get('date', 'unknown date')
        note = cal.get('note', '')

        if self._amplitude is not None and self._frequency is not None:
            v_at_max = np.pi / (2.0 * self._frequency)
            dac_at_max = v_at_max / self._max_voltage * 255.0
            info = (
                f'Loaded from: {os.path.basename(path)}  ({date})\n'
                f'  A (max power)   = {self._amplitude:.2f} mW\n'
                f'  k (frequency)   = {self._frequency:.4f} rad/V\n'
                f'  First maximum   = {v_at_max:.3f} V  (DAC ≈ {dac_at_max:.0f})'
            )
            if note:
                info += f'\n  Note: {note}'
        else:
            info = (
                f'LUT loaded from {os.path.basename(path)} ({date})\n'
                'No fit parameters stored — add measurements and re-fit\n'
                'to update the curve.'
            )
        self._fit_result_label.setText(info)

        has_hw = self._controller is not None and getattr(
            self._controller, 'is_open', False
        )
        self._upload_btn.setEnabled(has_hw)
        self._save_btn.setEnabled(True)

        if _MATPLOTLIB_AVAILABLE and self._frequency is not None:
            x_fit = np.linspace(0, 255, 512)
            v_fit = x_fit / 255.0 * self._max_voltage
            y_fit = self._amplitude * np.sin(v_fit * self._frequency) ** 2
            self._ax.cla()
            self._ax.plot(x_fit, y_fit, color='tomato', linewidth=1.5, label='Fit')
            self._ax.set_xlabel('DAC Level (0–255)')
            self._ax.set_ylabel('Power (mW)')
            self._ax.set_title(f'Pockels Calibration  ({date})')
            self._ax.legend(fontsize=8)
            self._fig.tight_layout()
            self._canvas.draw()
            self._update_lut_plot(self._lut)
