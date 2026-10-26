"""Entorno común de las pruebas de interfaz.

Fuerza la plataforma ``offscreen``, aísla las preferencias en una carpeta
temporal (nunca toca la configuración real) y captura los avisos de Qt para
que las pruebas fallen si aparece alguno.
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


def wait_until(predicate, timeout_ms: int = 5000) -> bool:
    from PySide6.QtCore import QCoreApplication, QDeadlineTimer, QEventLoop

    app = QCoreApplication.instance()
    deadline = QDeadlineTimer(timeout_ms)
    while not deadline.hasExpired():
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        if predicate():
            return True
    return predicate()
