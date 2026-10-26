"""Punto de entrada de la aplicación de escritorio."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from . import APP_NAME, ORG_NAME, __version__


def create_application(argv: list[str] | None = None) -> QApplication:
    """Crea (o reutiliza) la ``QApplication`` con nombre, versión, tema e icono."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0] if sys.argv else APP_NAME, *(argv or [])])
    app.setOrganizationName(ORG_NAME)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)

    from .ui.main_window import app_icon
    from .ui.theme import apply_theme

    apply_theme(app)
    app.setWindowIcon(app_icon())
    return app


def main(argv: list[str] | None = None) -> int:
    """Arranca la interfaz; ``argv`` son los argumentos sin el nombre del programa."""
    app = create_application(sys.argv[1:] if argv is None else argv)

    from .ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()
