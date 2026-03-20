"""Scanner gain calibration dialog.

Provides a non-modal dialog for editing and uploading the per-zoom-level
scanner gain tables that control the scan amplitude of both the resonant
(X-axis) and galvo (Y-axis) mirrors.

Parameters controlled
---------------------
dv_galvo
    Galvo mirror voltage step per scan line.  Hardware maximum is 64;
    the standard value for all rigs is 64 (``sbconfig.dv_galvo``).
gain_galvo (13-element)
    Y-axis (galvo) gain for each zoom level.  Logspaced 1.0–8.0 across
    the 13 discrete zoom positions (``sbconfig.gain_galvo``).
gain_resonant_mult
    Aspect-ratio corrector: ``gain_resonant = gain_resonant_mult × gain_galvo``.
    Calibrate with ``sbxspatialcalibration.m`` or by imaging a grid pattern
    (``sbconfig.gain_resonant_mult``).
gain_resonant (13-element, derived)
    X-axis (resonant) gain for each zoom level.  Can be overridden per-zoom
    without changing the multiplier if needed.

Usage::

    dialog = ScannerGainsDialog(controller=ctrl)
    dialog.show()   # non-modal — main window remains interactive

Reference:
    MATLAB: ``core/scanbox.m`` lines 253–262 (gain_override block),
    ``sb/sb_update_gains.m``, ``sb/sb_galvo_dv.m``, ``sb/sb_set_mag_x_i.m``,
    ``sb/sb_set_mag_y_i.m``.
"""

import logging

import PyQt6.QtCore as QtCore
import PyQt6.QtWidgets as QtWidgets

from pyscanbox.hardware import controller as hw_controller


logger = logging.getLogger(__name__)

# Number of zoom levels (matches len(ScanboxController.MAG_LABELS)).
_NUM_ZOOM_LEVELS = 13

# Table column indices.
_COL_INDEX = 0
_COL_LABEL = 1
_COL_GALVO = 2
_COL_RESONANT = 3


class ScannerGainsDialog(QtWidgets.QDialog):
    """Non-modal dialog for scanner gain table editing and upload.

    The dialog shows the 13 per-zoom-level gain values for both scanner
    axes and allows the user to:

    * Edit galvo (Y) and resonant (X) gains per zoom level.
    * Set the global resonant multiplier and recompute all X gains.
    * Send the complete table to the PSoC5 controller immediately.

    When no controller is connected the *Send to Hardware* button is
    disabled (read/offline mode).

    Signals:
        gains_sent: Emitted after a successful hardware upload.  Carries
            a dict with keys ``gain_galvo`` (list), ``gain_resonant`` (list),
            and ``dv_galvo`` (int).
    """

    gains_sent = QtCore.pyqtSignal(dict)

    def __init__(
        self,
        controller=None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        """Initialise the dialog.

        Args:
            controller: :class:`~pyscanbox.gui.app_controller.AppController`
                instance.  When provided and ``is_open`` is True, the *Send
                to Hardware* button is enabled.  When ``None`` the dialog
                runs in offline / display-only mode.
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self._controller = controller

        self.setWindowTitle('Scanner Gain Calibration')
        self.setMinimumSize(560, 540)

        self._init_ui()
        self._populate_defaults()
        self._update_send_button_state()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        """Build the dialog layout."""
        outer = QtWidgets.QVBoxLayout(self)
        outer.setSpacing(10)

        outer.addWidget(self._build_params_group())
        outer.addWidget(self._build_table_group())
        outer.addWidget(self._build_button_row())
        outer.addWidget(self._build_status_bar())

    def _build_params_group(self) -> QtWidgets.QGroupBox:
        """Build the global-parameter spinboxes (dv_galvo, multiplier)."""
        group = QtWidgets.QGroupBox('Global Parameters')
        layout = QtWidgets.QFormLayout(group)
        layout.setHorizontalSpacing(12)

        # dv_galvo
        self._dv_spin = QtWidgets.QSpinBox()
        self._dv_spin.setRange(0, hw_controller.ScanboxController.DV_GALVO_MAX)
        self._dv_spin.setValue(hw_controller.ScanboxController.DV_GALVO_MAX)
        self._dv_spin.setToolTip(
            'Galvo mirror voltage step per scan line.\n'
            'Hardware maximum is 64.  Keep at 64 unless advised otherwise.\n'
            'Reference: sbconfig.dv_galvo'
        )
        layout.addRow('dv_galvo (0–64):', self._dv_spin)

        # gain_resonant_mult
        self._mult_spin = QtWidgets.QDoubleSpinBox()
        self._mult_spin.setRange(0.1, 10.0)
        self._mult_spin.setSingleStep(0.01)
        self._mult_spin.setDecimals(3)
        self._mult_spin.setValue(
            hw_controller.ScanboxController.GAIN_RESONANT_MULT_DEFAULT
        )
        self._mult_spin.setToolTip(
            'Resonant / galvo aspect-ratio corrector.\n'
            'gain_resonant[i] = gain_resonant_mult × gain_galvo[i]\n'
            'Increase to stretch the image horizontally.\n'
            'Calibrate by imaging a square grid and adjusting until pixels\n'
            'are square.  Reference: sbconfig.gain_resonant_mult = 1.42'
        )
        layout.addRow('gain_resonant_mult:', self._mult_spin)

        recompute_btn = QtWidgets.QPushButton('Recompute X Gains from Multiplier')
        recompute_btn.setToolTip(
            'Recalculates all Resonant (X) gains as:\n'
            '  X gain[i] = gain_resonant_mult × Galvo gain[i]'
        )
        recompute_btn.clicked.connect(self._on_recompute_x_gains)
        layout.addRow('', recompute_btn)

        return group

    def _build_table_group(self) -> QtWidgets.QGroupBox:
        """Build the per-zoom-level gain table."""
        group = QtWidgets.QGroupBox(
            'Per-Zoom Gain Table  (Resonant = X-axis mirror;  Galvo = Y-axis mirror)'
        )
        layout = QtWidgets.QVBoxLayout(group)

        self._table = QtWidgets.QTableWidget(_NUM_ZOOM_LEVELS, 4)
        self._table.setHorizontalHeaderLabels(
            ['Index', 'Zoom', 'Galvo Gain (Y)', 'Resonant Gain (X)']
        )
        # Stretch the two editable columns; keep index and label narrow.
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(
            _COL_INDEX, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        hdr.setSectionResizeMode(
            _COL_LABEL, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        hdr.setSectionResizeMode(
            _COL_GALVO, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        hdr.setSectionResizeMode(
            _COL_RESONANT, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self._table.setToolTip(
            'Galvo Gain (Y): controls the vertical scan amplitude.\n'
            'Resonant Gain (X): controls the horizontal scan amplitude.\n'
            'Higher gain → wider FOV at that zoom level.\n'
            'Only one decimal digit of precision is sent to the PSoC5\n'
            '(wire encoding: xh = floor(x), xl = floor((x-xh)×10)).'
        )

        # Populate index + label columns (read-only); leave gain cells empty
        # until _populate_defaults() fills them.
        for i in range(_NUM_ZOOM_LEVELS):
            idx_item = QtWidgets.QTableWidgetItem(str(i))
            idx_item.setFlags(
                idx_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable
            )
            self._table.setItem(i, _COL_INDEX, idx_item)

            label_item = QtWidgets.QTableWidgetItem(
                hw_controller.ScanboxController.MAG_LABELS[i]
            )
            label_item.setFlags(
                label_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable
            )
            self._table.setItem(i, _COL_LABEL, label_item)

        layout.addWidget(self._table)
        return group

    def _build_button_row(self) -> QtWidgets.QWidget:
        """Build the action button row."""
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        self._reset_btn = QtWidgets.QPushButton('Reset to Defaults')
        self._reset_btn.setToolTip(
            'Restore gain_galvo to the logspaced defaults (1.0–8.0)\n'
            'and recompute X gains using the current multiplier.'
        )
        self._reset_btn.clicked.connect(self._on_reset_defaults)

        self._send_btn = QtWidgets.QPushButton('Send to Hardware')
        self._send_btn.setToolTip(
            'Upload dv_galvo and all 13 X/Y gain values to the PSoC5\n'
            'controller immediately.  Connection must be open.'
        )
        self._send_btn.clicked.connect(self._on_send_to_hardware)

        close_btn = QtWidgets.QPushButton('Close')
        close_btn.clicked.connect(self.close)

        layout.addWidget(self._reset_btn)
        layout.addStretch()
        layout.addWidget(self._send_btn)
        layout.addWidget(close_btn)
        return row

    def _build_status_bar(self) -> QtWidgets.QLabel:
        """Build the status label shown below the buttons."""
        self._status_label = QtWidgets.QLabel('')
        self._status_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        return self._status_label

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def _populate_defaults(self) -> None:
        """Fill the table with controller default gain values."""
        defaults = hw_controller.ScanboxController.GAIN_GALVO_DEFAULT
        mult = hw_controller.ScanboxController.GAIN_RESONANT_MULT_DEFAULT
        for i, gy in enumerate(defaults):
            gx = mult * gy
            self._table.setItem(
                i, _COL_GALVO, QtWidgets.QTableWidgetItem(f'{gy:.3f}')
            )
            self._table.setItem(
                i, _COL_RESONANT, QtWidgets.QTableWidgetItem(f'{gx:.3f}')
            )

    def _read_table_gains(self):
        """Parse galvo and resonant gain values from the table.

        Returns:
            Tuple ``(gain_galvo, gain_resonant)`` — each a 13-element list
            of floats — or ``None`` if any cell fails to parse.
        """
        gain_galvo = []
        gain_resonant = []
        for i in range(_NUM_ZOOM_LEVELS):
            galvo_item = self._table.item(i, _COL_GALVO)
            res_item = self._table.item(i, _COL_RESONANT)
            try:
                gy = float(galvo_item.text().strip())
                gx = float(res_item.text().strip())
            except (ValueError, AttributeError):
                QtWidgets.QMessageBox.warning(
                    self,
                    'Invalid value',
                    f'Row {i} (zoom={i}): could not parse gain value.\n'
                    'Gains must be non-negative numbers.',
                )
                return None
            if gy < 0 or gx < 0:
                QtWidgets.QMessageBox.warning(
                    self,
                    'Invalid value',
                    f'Row {i}: gain values must be non-negative.',
                )
                return None
            gain_galvo.append(gy)
            gain_resonant.append(gx)
        return gain_galvo, gain_resonant

    def _update_send_button_state(self) -> None:
        """Enable Send to Hardware only when a controller is connected."""
        connected = (
            self._controller is not None
            and getattr(self._controller, 'is_open', False)
        )
        self._send_btn.setEnabled(connected)
        if not connected:
            self._send_btn.setToolTip(
                'Hardware not connected.  Open a connection via the\n'
                'Hardware menu before sending gains.'
            )

    # ------------------------------------------------------------------
    # Slot implementations
    # ------------------------------------------------------------------

    def _on_reset_defaults(self) -> None:
        """Restore table to logspaced defaults and recompute X gains."""
        self._populate_defaults()
        self._mult_spin.setValue(
            hw_controller.ScanboxController.GAIN_RESONANT_MULT_DEFAULT
        )
        self._dv_spin.setValue(hw_controller.ScanboxController.DV_GALVO_MAX)
        self._status_label.setText('Values reset to defaults.')

    def _on_recompute_x_gains(self) -> None:
        """Recompute all Resonant (X) gains from current Y gains × multiplier."""
        mult = self._mult_spin.value()
        for i in range(_NUM_ZOOM_LEVELS):
            galvo_item = self._table.item(i, _COL_GALVO)
            if galvo_item is None:
                continue
            try:
                gy = float(galvo_item.text().strip())
            except ValueError:
                continue
            gx = mult * gy
            self._table.setItem(
                i, _COL_RESONANT, QtWidgets.QTableWidgetItem(f'{gx:.3f}')
            )
        self._status_label.setText(
            f'X gains recomputed (multiplier = {mult:.3f}).'
        )

    def _on_send_to_hardware(self) -> None:
        """Validate table values and upload gain tables to the PSoC5."""
        self._update_send_button_state()
        if not self._send_btn.isEnabled():
            return

        result = self._read_table_gains()
        if result is None:
            return
        gain_galvo, gain_resonant = result
        dv_galvo = self._dv_spin.value()

        try:
            # Use the hardware controller directly so that per-zoom resonant
            # overrides entered in the table are sent verbatim, rather than
            # being recomputed from a single multiplier.
            self._controller._hw_controller.update_scanner_gains(
                gain_galvo=gain_galvo,
                gain_resonant=gain_resonant,
                dv_galvo=dv_galvo,
            )
        except RuntimeError as exc:
            QtWidgets.QMessageBox.critical(
                self, 'Send Failed', f'Could not send gains to hardware:\n{exc}'
            )
            self._status_label.setText(f'Error: {exc}')
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception('Scanner gains upload failed: %s', exc)
            QtWidgets.QMessageBox.critical(
                self, 'Send Failed', f'Unexpected error:\n{exc}'
            )
            self._status_label.setText(f'Error: {exc}')
            return

        self._status_label.setText(
            'Gains sent to hardware successfully.'
        )
        self.gains_sent.emit({
            'gain_galvo': gain_galvo,
            'gain_resonant': gain_resonant,
            'dv_galvo': dv_galvo,
        })
        logger.info(
            'Scanner gains uploaded: dv=%d, mult=%.3f, galvo=%s',
            dv_galvo,
            self._mult_spin.value(),
            gain_galvo,
        )
