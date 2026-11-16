"""Cámara alta (``upper_house = { <ideología> = n }``, wizard §14.2): una casilla por ideología y la suma, que
debe ser 100 (``upper_house_sum``). «Repartir» completa la última ideología con lo que falte."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...i18n import N_, tr
from ..pickers.fields import _Picker
from ..widgets import mark_data


class UpperHouseField(_Picker):
    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.form = QFormLayout()
        outer.addLayout(self.form)
        row = QHBoxLayout()
        self.sum_label = QLabel()
        self.sum_label.setObjectName("upperHouseSum")
        row.addWidget(self.sum_label, 1)
        self.fill_button = QPushButton()
        self.fill_button.setObjectName("upperHouseFill")
        self.fill_button.clicked.connect(self.fill)
        row.addWidget(self.fill_button)
        outer.addLayout(row)
        self.spins: dict[str, QDoubleSpinBox] = {}
        self.reload()

    def ideologies(self) -> list[str]:
        index = getattr(self.session, "index", None)
        if index is None:
            return []
        from ...core.index.model import KIND_IDEOLOGY

        return sorted(index.names(KIND_IDEOLOGY))

    def reload(self) -> None:
        current = self.value()
        while self.form.rowCount():
            self.form.removeRow(0)
        self.spins.clear()
        for ideology in self.ideologies():
            spin = QDoubleSpinBox()
            spin.setObjectName(f"upper_{ideology}")
            spin.setRange(0, 100)
            spin.setDecimals(1)
            spin.valueChanged.connect(self._changed)
            index = getattr(self.session, "index", None)
            symbol = index.get("ideology", ideology) if index is not None else None
            try:
                label = self.session.display(symbol) if symbol is not None else ideology
            except Exception:  # noqa: BLE001
                label = ideology
            self.form.addRow(mark_data(QLabel(label)), spin)       # nombre de la ideología: dato
            self.spins[ideology] = spin
        self.set_value(current)
        self.retranslate()

    def retranslate(self) -> None:
        self.fill_button.setText(tr(N_("countries.upper.fill")))
        self._show_sum()

    def total(self) -> float:
        return round(sum(spin.value() for spin in self.spins.values()), 3)

    def _show_sum(self) -> None:
        total = self.total()
        self.sum_label.setText(tr(N_("countries.upper.sum"), total=f"{total:g}"))
        self.sum_label.setProperty("invalid", abs(total - 100) > 0.001)
        self.sum_label.style().unpolish(self.sum_label)
        self.sum_label.style().polish(self.sum_label)

    def _changed(self, *args) -> None:
        self._show_sum()
        self.value_committed.emit(self.value())

    def value(self) -> dict[str, float]:
        return {name: spin.value() for name, spin in self.spins.items() if spin.value()}

    def set_value(self, value) -> None:
        value = dict(value or {})
        for name, spin in self.spins.items():
            with QSignalBlocker(spin):
                spin.setValue(float(value.get(name, 0) or 0))
        self._show_sum()

    def fill(self) -> None:
        """Pone en la última ideología con valor (o en la primera) lo que falta para 100."""
        if not self.spins:
            return
        names = [n for n, s in self.spins.items() if s.value()] or list(self.spins)
        target = names[-1]
        rest = 100 - (self.total() - self.spins[target].value())
        self.spins[target].setValue(max(0.0, rest))
