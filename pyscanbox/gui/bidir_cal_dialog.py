"""Bidirectional scan calibration dialog.

Provides a non-modal dialog that guides the user through the bidirectional
pixel-shift calibration procedure and shows live progress as frames are
collected.

Usage::

    dialog = BidirCalibrationDialog(controller=ctrl, parent=main_window)
    dialog.show()   # non-modal: main window stays interactive

The dialog connects to :attr:`AppController.bidir_calibration_progress` and
:attr:`AppController.bidir_calibration_done` to receive updates; the caller
is responsible for wiring those signals before calling :meth:`update_progress`
and :meth:`update_done`.
"""

import logging

import PyQt6.QtCore as QtCore
import PyQt6.QtWidgets as QtWidgets

from pyscanbox.hardware import controller as hw_controller


logger = logging.getLogger(__name__)

# Displayed magnification labels (must match ScanboxController.MAG_LABELS).
_MAG_LABELS = hw_controller.ScanboxController.MAG_LABELS


class BidirCalibrationDialog(QtWidgets.QDialog):
    """Non-modal dialog for bidirectional pixel-shift calibration.

    Layout
    ------
    The dialog has three visual sections:

    1. **Instructions** — explains what the user must do before starting.
    2. **Progress** — progress bar and frame-count label, shown while
       calibration is running.
    3. **Result** — displays the measured bishift and which magnification
       was calibrated, shown after convergence.

    The **Start Calibration** button launches the measurement.  While it is
    running the button becomes a **Cancel** button.  After completion a
    **Close** button is shown.

    Args:
        controller: :class:`~pyscanbox.gui.app_controller.AppController`
            instance. Used to call ``start_bidir_calibration()`` and
            ``stop_bidir_calibration()``.  When ``None`` the Start button
            is disabled (offline / design mode).
        parent: Optional Qt parent widget.
    """

    def __init__(self, controller=None, parent=None):
        """Initialise the dialog.

        Args:
            controller: AppController instance, or ``None``.
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self._ctrl = controller
        self._running = False
        self.setWindowTitle('Bidirectional Scan Calibration')
        self.setWindowFlags(
            self.windowFlags() & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setMinimumWidth(420)
        self._init_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self):
        """Build the dialog layout."""
        outer = QtWidgets.QVBoxLayout()
        outer.setSpacing(12)
        outer.setContentsMargins(16, 16, 16, 16)

        # ---- Instructions section ----
        instructions_box = QtWidgets.QGroupBox('Instructions')
        instr_layout = QtWidgets.QVBoxLayout()
        instr_layout.setSpacing(4)

        steps = [
            '1. Switch the scan mode to <b>Bidirectional</b> in the Scanner '
            'Controls panel.',
            '2. Set the desired <b>magnification</b> in the Scanner Controls '
            'panel.',
            '3. Adjust the <b>Bidir Alignment</b> spinbox until forward and '
            'backward scan lines are aligned in the live image.',
            '4. Repeat steps 2–3 for each magnification you use.',
            '5. Click <b>Save Manual Calibration</b> to store all values.',
        ]
        for step in steps:
            lbl = QtWidgets.QLabel(step)
            lbl.setWordWrap(True)
            lbl.setTextFormat(QtCore.Qt.TextFormat.RichText)
            instr_layout.addWidget(lbl)

        note = QtWidgets.QLabel(
            '<i><b>Auto Calibrate</b> (experimental): '
            'start Focus on a sample with fine horizontal structure, then '
            'click <b>Auto Calibrate</b>.  The software collects ~25 live '
            'frames and estimates the pixel offset automatically.  '
            'Fine-tune the result with the Bidir Alignment spinbox and '
            'click <b>Save Manual Calibration</b> when satisfied.</i>'
        )
        note.setWordWrap(True)
        note.setTextFormat(QtCore.Qt.TextFormat.RichText)
        instr_layout.addWidget(note)
        instructions_box.setLayout(instr_layout)
        outer.addWidget(instructions_box)

        # ---- Progress section ----
        self._progress_box = QtWidgets.QGroupBox('Progress')
        progress_layout = QtWidgets.QVBoxLayout()
        progress_layout.setSpacing(6)

        self._progress_bar = QtWidgets.QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat('%v / %m frames')
        progress_layout.addWidget(self._progress_bar)

        self._status_label = QtWidgets.QLabel('Waiting to start…')
        self._status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        progress_layout.addWidget(self._status_label)

        self._progress_box.setLayout(progress_layout)
        outer.addWidget(self._progress_box)

        # ---- Result section ----
        self._result_box = QtWidgets.QGroupBox('Result')
        result_layout = QtWidgets.QFormLayout()
        result_layout.setSpacing(6)

        self._result_mag_label = QtWidgets.QLabel('—')
        result_layout.addRow('Magnification:', self._result_mag_label)

        self._result_shift_label = QtWidgets.QLabel('—')
        result_layout.addRow('Measured bishift (px):', self._result_shift_label)

        self._result_note = QtWidgets.QLabel(
            'Fine-tune the value with the Bidir Alignment spinbox in '
            'Scanner Controls, then click <b>Save Manual Calibration</b> '
            'to keep the result.'
        )
        self._result_note.setWordWrap(True)
        self._result_note.setTextFormat(QtCore.Qt.TextFormat.RichText)
        result_layout.addRow(self._result_note)

        self._result_box.setLayout(result_layout)
        self._result_box.setVisible(False)
        outer.addWidget(self._result_box)

        # ---- Button row ----
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()

        self._save_btn = QtWidgets.QPushButton('Save Manual Calibration')
        if self._ctrl is None:
            self._save_btn.setEnabled(False)
            self._save_btn.setToolTip('No hardware connected.')
        self._save_btn.clicked.connect(self._on_save_clicked)
        btn_row.addWidget(self._save_btn)

        self._start_btn = QtWidgets.QPushButton('Auto Calibrate')
        self._start_btn.setDefault(True)
        if self._ctrl is None:
            self._start_btn.setEnabled(False)
            self._start_btn.setToolTip('No hardware connected.')
        self._start_btn.clicked.connect(self._on_start_cancel_clicked)
        btn_row.addWidget(self._start_btn)

        self._close_btn = QtWidgets.QPushButton('Close')
        self._close_btn.clicked.connect(self.close)
        btn_row.addWidget(self._close_btn)

        outer.addLayout(btn_row)
        self.setLayout(outer)

    # ------------------------------------------------------------------
    # Public update API (called from MainWindow signal handlers)
    # ------------------------------------------------------------------

    def update_progress(self, done: int, needed: int) -> None:
        """Update the progress bar and status label.

        Should be called from the ``bidir_calibration_progress`` signal handler.

        Args:
            done: Frames collected so far.
            needed: Total frames needed.
        """
        self._progress_bar.setMaximum(needed)
        self._progress_bar.setValue(done)
        self._status_label.setText(f'Collecting frames… {done} / {needed}')

    def update_done(self, mag_index: int, shift: int) -> None:
        """Display the calibration result and reset the running state.

        Should be called from the ``bidir_calibration_done`` signal handler.

        Args:
            mag_index: Magnification index that was calibrated (0–12).
            shift: Measured pixel shift stored for that magnification.
        """
        self._running = False
        self._start_btn.setText('Auto Calibrate')
        self._start_btn.setEnabled(True)
        self._save_btn.setEnabled(self._ctrl is not None)
        self._status_label.setText('Calibration complete.')
        self._progress_bar.setValue(self._progress_bar.maximum())

        mag_label = (
            _MAG_LABELS[mag_index]
            if 0 <= mag_index < len(_MAG_LABELS)
            else str(mag_index)
        )
        self._result_mag_label.setText(f'{mag_label}  (index {mag_index})')
        self._result_shift_label.setText(f'{shift:+d}')
        self._result_box.setVisible(True)

    def notify_cancelled(self) -> None:
        """Reset the dialog to the idle state after an external cancellation."""
        self._running = False
        self._start_btn.setText('Auto Calibrate')
        self._start_btn.setEnabled(self._ctrl is not None)
        self._save_btn.setEnabled(self._ctrl is not None)
        self._status_label.setText('Cancelled.')
        self._progress_bar.setValue(0)

    # ------------------------------------------------------------------
    # Internal slots
    # ------------------------------------------------------------------

    def _on_start_cancel_clicked(self) -> None:
        """Handle Auto Calibrate / Cancel button press."""
        if self._running:
            self._cancel()
        else:
            self._start()

    def _on_save_clicked(self) -> None:
        """Save all current bishift values (manual calibration)."""
        if self._ctrl is None:
            return
        try:
            path = self._ctrl.save_manual_bidir_calibration()
        except RuntimeError as exc:
            QtWidgets.QMessageBox.warning(
                self, 'Save Failed', str(exc)
            )
            return
        QtWidgets.QMessageBox.information(
            self,
            'Calibration Saved',
            f'All bishift values saved to:\n{path}',
        )

    def _start(self) -> None:
        """Validate preconditions and start calibration."""
        if self._ctrl is None:
            return

        # Check hardware is open.
        if not self._ctrl.is_open:
            QtWidgets.QMessageBox.warning(
                self,
                'Hardware Not Connected',
                'Please connect the hardware before running calibration.',
            )
            return

        # Check bidirectional mode.
        unidirectional = self._ctrl.config.get(
            'acquisition', {}
        ).get('unidirectional', True)
        if unidirectional:
            QtWidgets.QMessageBox.information(
                self,
                'Bidirectional Mode Required',
                'Please switch to <b>Bidirectional</b> scan mode in the '
                'Scanner Controls panel before calibrating.',
            )
            return

        # Check that Focus is running so frames will arrive.
        # AppController.start_bidir_calibration() connects to frame_data_ready;
        # if Focus is not running no frames will arrive and the progress bar
        # will stay at zero.  Give the user a helpful warning.
        # We detect "running" heuristically: if the scanner thread exists and
        # is running (attribute exposed by ScannerThread / AppController).
        scanner_running = getattr(self._ctrl, '_scanner_thread', None)
        if scanner_running is None or not getattr(scanner_running, 'isRunning', lambda: False)():
            reply = QtWidgets.QMessageBox.question(
                self,
                'Focus Not Running',
                'Focus does not appear to be running.\n\n'
                'Calibration requires live frames — start Focus in the '
                'Acquisition Control panel first.\n\n'
                'Start calibration anyway?',
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return

        # Reset UI.
        self._result_box.setVisible(False)
        self._progress_bar.setValue(0)
        self._status_label.setText('Starting…')

        try:
            self._ctrl.start_bidir_calibration()
        except RuntimeError as exc:
            QtWidgets.QMessageBox.warning(
                self, 'Calibration Error', str(exc)
            )
            return

        self._running = True
        self._start_btn.setText('Cancel')
        self._save_btn.setEnabled(False)

        # Retrieve how many frames are expected and initialise progress bar.
        if self._ctrl._bidir_cal is not None:
            needed = self._ctrl._bidir_cal.frames_needed
            self._progress_bar.setMaximum(needed)
            self._status_label.setText(f'Collecting frames… 0 / {needed}')

    def _cancel(self) -> None:
        """Cancel an in-progress calibration."""
        if self._ctrl is not None:
            self._ctrl.stop_bidir_calibration()
        self.notify_cancelled()

    def closeEvent(self, event):
        """Cancel any running calibration before closing.

        Args:
            event: QCloseEvent from Qt.
        """
        if self._running:
            self._cancel()
        super().closeEvent(event)
