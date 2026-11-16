"""Selectores de pueblo (wizard §14.2, paso 3 del asistente): cultura principal (``CulturePicker``), culturas
aceptadas (``CultureListPicker``) y religión (``ReligionPicker``), sobre los símbolos del índice."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from .fields import SymbolPicker
from .tag_picker import SymbolListPicker


class CulturePicker(SymbolPicker):
    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(session, "culture", parent=parent)
        self.combo.setObjectName("culturePicker")


class CultureListPicker(SymbolListPicker):
    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(session, "culture", parent=parent)


class ReligionPicker(SymbolPicker):
    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(session, "religion", parent=parent)
        self.combo.setObjectName("religionPicker")
