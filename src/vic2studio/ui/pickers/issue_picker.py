"""Reformas de un país (wizard §14.2, paso 5 del asistente y pestaña «Política» de la ficha).

Un desplegable por grupo de reformas políticas y sociales; con ``set_civilized(False)``, también las económicas y
militares (las de los países no civilizados). ``value()`` da ``{grupo: opción}`` de los grupos con opción elegida.
"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QWidget

from ...i18n import N_, tr
from .fields import _Picker

POLITICAL = ("political_reforms", "social_reforms")
UNCIVILIZED = ("economic_reforms", "military_reforms")


class IssuePicker(_Picker):
    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.civilized = True
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.combos: dict[str, QComboBox] = {}
        self.labels: dict[str, QLabel] = {}
        self.reload()

    def _groups(self) -> list[tuple[str, str, list[str]]]:
        from ...core.index.model import KIND_ISSUE_GROUP

        index = getattr(self.session, "index", None)
        if index is None:
            return []
        categories = POLITICAL + (() if self.civilized else UNCIVILIZED)
        found = []
        for symbol in index.symbols(KIND_ISSUE_GROUP):
            attrs = symbol.attrs or {}
            if attrs.get("category") in categories:
                found.append((attrs.get("category"), symbol.name, list(attrs.get("options") or ())))
        order = {category: n for n, category in enumerate(categories)}
        return sorted(found, key=lambda item: (order.get(item[0], 9), item[1]))

    def _display(self, kind: str, name: str) -> str:
        index = getattr(self.session, "index", None)
        try:
            symbol = index.get(kind, name) if index is not None else None
            return self.session.display(symbol) if symbol is not None else name
        except Exception:  # noqa: BLE001
            return name

    def reload(self) -> None:
        current = self.value()
        while self.form.rowCount():
            self.form.removeRow(0)
        self.combos.clear()
        self.labels.clear()
        for _category, group, options in self._groups():
            combo = QComboBox()
            combo.setObjectName(f"issue_{group}")
            combo.addItem("", None)
            for option in options:
                combo.addItem(self._display("issue_option", option), option)
            combo.activated.connect(lambda _i: self.value_committed.emit(self.value()))
            label = QLabel(self._display("issue_group", group))
            self.form.addRow(label, combo)
            self.combos[group] = combo
            self.labels[group] = label
        self.set_value(current)
        self.retranslate()

    def retranslate(self) -> None:
        for combo in self.combos.values():
            combo.setItemText(0, tr(N_("pickers.issue.keep")))

    def set_civilized(self, civilized: bool) -> None:
        if civilized != self.civilized:
            self.civilized = civilized
            self.reload()

    def value(self) -> dict[str, str]:
        return {group: combo.currentData() for group, combo in self.combos.items() if combo.currentData()}

    def set_value(self, value) -> None:
        value = dict(value or {})
        for group, combo in self.combos.items():
            with QSignalBlocker(combo):
                index = combo.findData(value.get(group)) if value.get(group) else 0
                combo.setCurrentIndex(max(index, 0))
