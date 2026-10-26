"""Entorno común de las pruebas de interfaz.

Fuerza la plataforma ``offscreen``, aísla las preferencias en una carpeta
temporal (nunca toca la configuración real) y captura los avisos de Qt para
que las pruebas fallen si aparece alguno. ``dispose`` destruye de verdad las
ventanas de cada prueba: si siguieran vivas, se seguirían maquetando y
competirían por el GIL con las pruebas siguientes (y con sus latidos).
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vic2studio.compat import broken_binding_message, broken_qt_binding  # noqa: E402

# Con PySide6 6.12 en Python 3.10/3.11 la batería abortaría a mitad («none_dealloc»): mejor parar aquí y decir por qué.
_broken = broken_qt_binding()
if _broken is not None:
    raise RuntimeError(broken_binding_message(*_broken))

SETTINGS_DIR = tempfile.mkdtemp(prefix="vic2studio-tests-")
atexit.register(shutil.rmtree, SETTINGS_DIR, True)
os.environ["VIC2STUDIO_SETTINGS_DIR"] = SETTINGS_DIR

from PySide6.QtCore import QtMsgType, qInstallMessageHandler  # noqa: E402

_messages: list[str] = []
_REPORTED = {QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg}


def _handler(mode, context, message) -> None:
    if mode in _REPORTED:
        _messages.append(f"{mode.name}: {message}")


qInstallMessageHandler(_handler)


def application():
    """QApplication única del proceso, con el tema aplicado."""
    from vic2studio.app import create_application

    return create_application([])


def take_qt_messages() -> list[str]:
    messages = list(_messages)
    _messages.clear()
    return messages


def reset_settings() -> None:
    from vic2studio.settings import app_settings

    settings = app_settings()
    settings.clear()
    settings.sync()


def process_events(milliseconds: int = 0) -> None:
    from PySide6.QtCore import QCoreApplication, QDeadlineTimer, QEventLoop

    app = QCoreApplication.instance()
    if milliseconds <= 0:
        app.processEvents()
        return
    deadline = QDeadlineTimer(milliseconds)
    while not deadline.hasExpired():
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)


def delete_pending() -> None:
    """Borra ya lo pendiente de ``deleteLater``.

    Fuera de un bucle de eventos, ``processEvents`` no procesa los borrados diferidos
    (Qt solo los entrega al salir del bucle que los pidió, o si se piden expresamente).
    """
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def dispose(*widgets) -> list:
    """``deleteLater`` de ``widgets`` y su borrado inmediato; devuelve los que siguen vivos (ninguno)."""
    from shiboken6 import isValid

    for widget in widgets:
        if isValid(widget):
            widget.deleteLater()
    delete_pending()
    return [widget for widget in widgets if isValid(widget)]


def live_main_windows() -> list:
    """Ventanas principales que aún existen (cerradas o no)."""
    from PySide6.QtWidgets import QApplication

    from vic2studio.ui.main_window import MainWindow

    return [widget for widget in QApplication.topLevelWidgets() if isinstance(widget, MainWindow)]


def wait_until(predicate, timeout_ms: int = 5000) -> bool:
    from PySide6.QtCore import QCoreApplication, QDeadlineTimer, QEventLoop

    app = QCoreApplication.instance()
    deadline = QDeadlineTimer(timeout_ms)
    while not deadline.hasExpired():
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        if predicate():
            return True
    return predicate()
