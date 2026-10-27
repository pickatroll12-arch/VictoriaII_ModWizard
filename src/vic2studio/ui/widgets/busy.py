"""Trabajo síncrono largo en el hilo de la interfaz: cursor de espera y la barra de estado pintada antes de empezar.

Algunas operaciones no pueden salir del hilo de la interfaz porque tocan el ``Workspace``
(I12): planificar y aplicar un arreglo, guardar. Con VSM duran segundos («Mover a la
papelera las copias idénticas», 8 462 archivos). ``busy(widget)`` pone el cursor de
espera mientras dura el bloque y repinta en el acto la barra de estado de la ventana de
``widget``: el mensaje que se acaba de pedir («Aplicando el arreglo…») se ve aunque el
bucle de eventos no vuelva a correr hasta el final. No procesa eventos (eso permitiría
pulsar otra cosa a mitad de la operación).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMainWindow, QWidget


@contextmanager
def busy(widget: QWidget | None) -> Iterator[None]:
    """Cursor de espera durante el bloque y la barra de estado de la ventana de ``widget`` repintada al empezar."""
    QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        window = widget.window() if widget is not None else None
        if isinstance(window, QMainWindow) and window.isVisible():
            window.statusBar().repaint()
        yield
    finally:
        QGuiApplication.restoreOverrideCursor()


def is_busy_cursor() -> bool:
    """True si hay un cursor de espera puesto (para las pruebas)."""
    cursor = QGuiApplication.overrideCursor()
    return cursor is not None and cursor.shape() == Qt.CursorShape.WaitCursor


__all__ = ["busy", "is_busy_cursor"]
