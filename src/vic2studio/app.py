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


def refuse_broken_binding(python: str, pyside: str) -> int:
    """Explica que esta combinación de Python y PySide6 aborta, y devuelve el código de salida."""
    from PySide6.QtWidgets import QMessageBox

    from .compat import broken_binding_message
    from .i18n import tr

    print(broken_binding_message(python, pyside), file=sys.stderr)
    QMessageBox.critical(
        None,
        tr("compat.pyside_title"),
        tr("compat.pyside_text", python=python, pyside=pyside),
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    """Arranca la interfaz; ``argv`` son los argumentos sin el nombre del programa."""
    from .compat import broken_qt_binding

    app = create_application(sys.argv[1:] if argv is None else argv)
    # Antes de la ventana y de cualquier tarea: con esa combinación el proceso aborta al rato.
    broken = broken_qt_binding()
    if broken is not None:
        return refuse_broken_binding(*broken)

    from .ui.main_window import MainWindow
    from .ui.tasks import cancel_all, wait_for_tasks

    window = MainWindow()
    window.show()
    code = app.exec()
    # Ningún hilo debe seguir ejecutando Python mientras se cierra el intérprete; canceladas, las tareas paran pronto.
    cancel_all()
    wait_for_tasks()
    return code
