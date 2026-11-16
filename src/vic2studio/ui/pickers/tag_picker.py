"""Selectores de TAG (wizard §14.2, §14.8): uno (``TagPicker``) o varios en orden (``SymbolListPicker``).

``TagPicker`` es un ``SymbolPicker`` de los TAG registrados (con su nombre localizado). ``SymbolListPicker`` es una
lista ordenada de símbolos de cualquier tipo (TAG de un bando, culturas aceptadas): el primero de la lista es el
líder del bando en las guerras. API común de los selectores: ``value()``/``values()``, ``set_value``/
``set_values``, la señal ``value_committed`` y ``retranslate()``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QToolButton, QVBoxLayout, QWidget

from ...i18n import N_, tr
from ..widgets import make_icon, mark_data
from .fields import SymbolPicker, _Picker

ROLE_NAME = Qt.ItemDataRole.UserRole


class TagPicker(SymbolPicker):
    """Un TAG registrado (``SymbolPicker`` del tipo ``tag``)."""

    def __init__(self, session, *, allow_new: bool = False, parent: QWidget | None = None):
        super().__init__(session, "tag", allow_new=allow_new, parent=parent)
        self.combo.setObjectName("tagPicker")

    def value(self) -> str | None:
        value = super().value()
        return value.upper() if isinstance(value, str) else value


class SymbolListPicker(_Picker):
    """Lista ordenada de símbolos de ``kind``: un selector, «Añadir», «Quitar» y «Subir»."""

    def __init__(self, session, kind: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.kind = kind
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.picker = TagPicker(session) if kind == "tag" else SymbolPicker(session, kind)
        row.addWidget(self.picker, 1)
        self.add_button = QToolButton()
        self.add_button.setObjectName("listPickerAdd")
        self.add_button.setIcon(make_icon("plus", "gold_light"))
        self.add_button.clicked.connect(self.add_current)
        row.addWidget(self.add_button)
        self.remove_button = QToolButton()
        self.remove_button.setObjectName("listPickerRemove")
        self.remove_button.setIcon(make_icon("minus", "gold_light"))
        self.remove_button.clicked.connect(self.remove_selected)
        row.addWidget(self.remove_button)
        self.up_button = QToolButton()
        self.up_button.setObjectName("listPickerUp")
        self.up_button.setArrowType(Qt.ArrowType.UpArrow)
        self.up_button.clicked.connect(self.move_up)
        row.addWidget(self.up_button)
        outer.addLayout(row)
        self.list = mark_data(QListWidget())
        self.list.setObjectName("listPickerItems")
        self.list.setMaximumHeight(110)
        outer.addWidget(self.list)
        self.retranslate()

    def retranslate(self) -> None:
        self.add_button.setToolTip(tr(N_("pickers.list.add")))
        self.remove_button.setToolTip(tr(N_("pickers.list.remove")))
        self.up_button.setToolTip(tr(N_("pickers.list.up")))

    def reload(self) -> None:
        self.picker.reload()

    def values(self) -> list[str]:
        return [self.list.item(i).data(ROLE_NAME) for i in range(self.list.count())]

    def value(self) -> list[str]:
        return self.values()

    def _label(self, name: str) -> str:
        return self.picker._label(name) if name else name

    def set_values(self, names) -> None:
        self.list.clear()
        for name in names or ():
            self._append(name)

    set_value = set_values

    def _append(self, name: str) -> None:
        item = QListWidgetItem(self._label(name))
        item.setData(ROLE_NAME, name)
        self.list.addItem(item)

    def add(self, name: str) -> bool:
        if not name or name in self.values():
            return False
        self._append(name)
        self.value_committed.emit(self.values())
        return True

    def add_current(self) -> bool:
        value = self.picker.value()
        if value is None or not self.picker.is_valid():
            return False
        added = self.add(value)
        self.picker.set_value(None)
        return added

    def remove_selected(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)
            self.value_committed.emit(self.values())

    def move_up(self) -> None:
        row = self.list.currentRow()
        if row > 0:
            item = self.list.takeItem(row)
            self.list.insertItem(row - 1, item)
            self.list.setCurrentRow(row - 1)
            self.value_committed.emit(self.values())
