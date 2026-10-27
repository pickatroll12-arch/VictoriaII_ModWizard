"""Delegados pequeños compartidos por las tablas."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStyledItemDelegate


class PathElideDelegate(QStyledItemDelegate):
    """Una columna de rutas se recorta por la izquierda: «…/AGC - Angoche.txt:1» conserva el nombre y la línea.

    Es lo que hace la lista de diagnósticos de los visores con su columna Archivo.
    """

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        option.textElideMode = Qt.TextElideMode.ElideLeft
