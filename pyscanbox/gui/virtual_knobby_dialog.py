# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Santiago Jaramillo

"""Virtual Knobby dialog for pyscanbox.

Provides a floating Qt dialog that emulates the hardware Knobby controller
(rotary-encoder-based device, knobby2_3.ino firmware).  The user can nudge
each motor axis (X, Y, Z, A) by one step at a time using +/- buttons, with
a velocity mode selector that scales the step size to match the firmware's
coarse / fine / superfine modes.

The dialog also offers memory slots A/B/C (store and recall) and zero
buttons to reset the Knobby origin — identical to the touchscreen buttons
on the physical device.

Signals:
    move_requested(motor_id: int, delta_steps: int):
        Emitted when the user presses a +/- button.  ``motor_id`` is 0-3
        (Z/Y/X/A) and ``delta_steps`` is the signed step count to apply.
    zero_requested(axes: str):
        Emitted when the user clicks a zero button.  ``axes`` is ``'xyz'``
        or ``'xyza'``.

References:
    Firmware: Scanbox/scanknob/knobby2_3/knobby2_3/knobby2_3.ino
    Protocol: docs/hardware_protocols/knobby.md
"""

import logging

import PyQt6.QtCore as QtCore
import PyQt6.QtWidgets as QtWidgets
import PyQt6.QtGui as QtGui

from pyscanbox.hardware import knobby as hw_knobby

logger = logging.getLogger(__name__)

# Velocity-mode step sizes in physical units (μm for Z/Y/X, degrees for A).
# Index order: vel [coarse, fine, superfine], then motor [Z, Y, X, A].
_VEL_STEP_UNITS = [
    [10.0, 10.0, 10.0, 10.0],   # Coarse:    10 μm / 10 deg
    [1.0,  1.0,  1.0,  1.0],    # Fine:       1 μm /  1 deg
    [0.1,  0.1,  0.1,  0.1],    # Superfine:  0.1 μm / 0.1 deg
]

# Labels for the three velocity modes.
_VEL_LABELS = ['Coarse', 'Fine', 'Superfine']

# Human-readable labels for the four axes (displayed in the dialog).
# Note: motor_id order is Z=0, Y=1, X=2, A=3 (matches firmware).
_AXIS_LABELS = ['Z', 'Y', 'X', 'A']
_AXIS_UNITS = hw_knobby.AXIS_UNITS  # ['um', 'um', 'um', 'deg']



class VirtualKnobbyDialog(QtWidgets.QDialog):
    """Floating dialog that emulates the hardware Knobby position controller.

    Provides +/- buttons for each axis, a velocity-mode selector, memory
    store/recall slots, and zero buttons.  Position readouts are updated via
    :meth:`update_positions`.

    Signals:
        move_requested: Emitted with ``(motor_id, delta_steps)`` when a +/-
            button is clicked.
        zero_requested: Emitted with ``'xyz'`` or ``'xyza'``.
    """

    move_requested = QtCore.pyqtSignal(int, int)   # motor_id, delta_steps
    zero_requested = QtCore.pyqtSignal(str)         # 'xyz' or 'xyza'

    def __init__(self, parent=None):
        """Initialise the virtual Knobby dialog.

        Args:
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle('Virtual Knobby')
        self.setWindowFlags(
            self.windowFlags() | QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        # Do not destroy on close; just hide so it can be re-shown.
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)

        # Current velocity mode: 0=coarse, 1=fine, 2=superfine.
        self._vel = 0

        self._pos_labels = {}   # motor_id -> QLabel (Knobby relative pos)

        self._init_ui()

    def _init_ui(self):
        """Build the dialog layout."""
        outer = QtWidgets.QVBoxLayout(self)
        outer.setSpacing(6)

        # ── Velocity mode ───────────────────────────────────────────────
        vel_group = QtWidgets.QGroupBox('Velocity')
        vel_layout = QtWidgets.QHBoxLayout(vel_group)
        self._vel_buttons = []
        for idx, label in enumerate(_VEL_LABELS):
            btn = QtWidgets.QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(idx == 0)
            btn.clicked.connect(lambda checked, i=idx: self._on_vel_clicked(i))
            vel_layout.addWidget(btn)
            self._vel_buttons.append(btn)
        outer.addWidget(vel_group)

        # ── Axis controls ───────────────────────────────────────────────
        axes_group = QtWidgets.QGroupBox('Position')
        axes_layout = QtWidgets.QGridLayout(axes_group)
        axes_layout.setSpacing(4)

        # Header row.
        for col, header in enumerate(['Axis', 'Position', '−', '+']):
            lbl = QtWidgets.QLabel(f'<b>{header}</b>')
            lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            axes_layout.addWidget(lbl, 0, col)

        # One row per axis. motor_id order: Z=0, Y=1, X=2, A=3.
        for row, motor_id in enumerate(range(4)):
            axis_name = _AXIS_LABELS[motor_id]
            units = _AXIS_UNITS[motor_id]

            axis_label = QtWidgets.QLabel(f'<b>{axis_name}</b>')
            axis_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            axes_layout.addWidget(axis_label, row + 1, 0)

            pos_label = QtWidgets.QLabel('0.00')
            pos_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            pos_label.setMinimumWidth(90)
            pos_label.setToolTip(f'Knobby relative position ({units})')
            axes_layout.addWidget(pos_label, row + 1, 1)
            self._pos_labels[motor_id] = pos_label

            minus_btn = QtWidgets.QPushButton('−')
            minus_btn.setFixedWidth(32)
            minus_btn.clicked.connect(
                lambda checked, mid=motor_id: self._on_move(mid, -1)
            )
            axes_layout.addWidget(minus_btn, row + 1, 2)

            plus_btn = QtWidgets.QPushButton('+')
            plus_btn.setFixedWidth(32)
            plus_btn.clicked.connect(
                lambda checked, mid=motor_id: self._on_move(mid, +1)
            )
            axes_layout.addWidget(plus_btn, row + 1, 3)

        outer.addWidget(axes_group)


        # ── Zero buttons ─────────────────────────────────────────────────
        zero_layout = QtWidgets.QHBoxLayout()
        zero_xyz_btn = QtWidgets.QPushButton('Zero XYZ')
        zero_xyz_btn.setToolTip('Reset X, Y, Z origin to current position')
        zero_xyz_btn.clicked.connect(lambda: self.zero_requested.emit('xyz'))
        zero_layout.addWidget(zero_xyz_btn)

        zero_xyza_btn = QtWidgets.QPushButton('Zero XYZA')
        zero_xyza_btn.setToolTip('Reset X, Y, Z, A origin to current position')
        zero_xyza_btn.clicked.connect(lambda: self.zero_requested.emit('xyza'))
        zero_layout.addWidget(zero_xyza_btn)
        outer.addLayout(zero_layout)

        self.setLayout(outer)
        self.adjustSize()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_vel_clicked(self, vel_idx: int) -> None:
        """Update velocity mode and toggle button states.

        Args:
            vel_idx: New velocity index (0=coarse, 1=fine, 2=superfine).
        """
        self._vel = vel_idx
        for i, btn in enumerate(self._vel_buttons):
            btn.setChecked(i == vel_idx)
        logger.debug('VirtualKnobby: velocity mode = %s', _VEL_LABELS[vel_idx])

    def _on_move(self, motor_id: int, direction: int) -> None:
        """Compute delta_steps and emit move_requested.

        Converts the physical-unit step size for the current velocity mode
        into motor steps using hw_knobby.units_to_steps, then emits
        move_requested.  A minimum of ±1 step is enforced so that very small
        physical step sizes still produce a detectable movement.

        Args:
            motor_id: Motor index 0-3 (Z/Y/X/A).
            direction: +1 or -1.
        """
        step_units = _VEL_STEP_UNITS[self._vel][motor_id]
        delta_steps = hw_knobby.units_to_steps(motor_id, direction * step_units)
        if delta_steps == 0:
            delta_steps = direction
        logger.debug(
            'VirtualKnobby: motor=%d direction=%+d vel=%d step=%.1f→%d steps',
            motor_id, direction, self._vel, step_units, delta_steps,
        )
        self.move_requested.emit(motor_id, delta_steps)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_positions(self, positions: dict) -> None:
        """Refresh the position readouts.

        Args:
            positions: Dict as emitted by AppController.position_updated.
                Keys ``'Z'``, ``'Y'``, ``'X'``, ``'A'`` are the Knobby
                relative positions in physical units.
        """
        for motor_id in range(4):
            name = hw_knobby.AXIS_NAMES[motor_id]
            val = positions.get(name, 0.0)
            units = _AXIS_UNITS[motor_id]
            self._pos_labels[motor_id].setText(f'{val:.2f} {units}')
