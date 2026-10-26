"""Combinaciones de Python y PySide6 que se sabe que no funcionan.

PySide6 6.12.0 suelta referencias de más a ``None``, ``True`` y ``False`` (una por
tarea de ``QThreadPool`` y alguna al emitir señales con argumentos ``object``).
Desde Python 3.12 esos objetos son inmortales y no pasa nada; con 3.10 y 3.11 el
proceso aborta tarde o temprano («Fatal Python error: none_dealloc»). Con la
6.11.3 el recuento queda bien. ``pyproject.toml`` ya impide instalar esa
combinación; esto avisa a quien la tenga instalada de antes.

No importa Qt: solo lee ``PySide6.__version_info__``, que no carga QtCore.
"""

from __future__ import annotations

import os
import sys

# Primera versión de PySide6 con el fallo; no se conoce ninguna posterior que lo corrija.
BROKEN_PYSIDE_FROM = (6, 12)
# Desde esta versión de Python, None, True y False son inmortales.
IMMORTAL_SINGLETONS_FROM = (3, 12)
# Para quien quiera probar una PySide6 posterior que quizá ya lo corrija.
OVERRIDE_ENV = "VIC2STUDIO_ALLOW_BROKEN_PYSIDE"


def pyside_version() -> tuple[int, ...]:
    """Versión de PySide6 instalada (sin cargar QtCore)."""
    import PySide6

    return tuple(int(part) for part in PySide6.__version_info__[:3])


def is_broken_combination(python: tuple[int, ...], pyside: tuple[int, ...]) -> bool:
    """True si esa versión de Python con esa de PySide6 acaba abortando."""
    return tuple(python[:2]) < IMMORTAL_SINGLETONS_FROM and tuple(pyside[:2]) >= BROKEN_PYSIDE_FROM


def broken_qt_binding() -> tuple[str, str] | None:
    """``(python, pyside)`` como texto si la combinación instalada está rota; si no, None.

    ``VIC2STUDIO_ALLOW_BROKEN_PYSIDE=1`` desactiva la comprobación.
    """
    if os.environ.get(OVERRIDE_ENV, "").strip() not in ("", "0"):
        return None
    python = tuple(sys.version_info[:3])
    pyside = pyside_version()
    if not is_broken_combination(python, pyside):
        return None
    return ".".join(map(str, python)), ".".join(map(str, pyside))


def broken_binding_message(python: str, pyside: str) -> str:
    """Mensaje para la terminal y las pruebas, en los dos idiomas (no hay traductor sin Qt)."""
    return (
        f"PySide6 {pyside} no funciona con Python {python}: el proceso acaba abortando "
        f"(«Fatal Python error: none_dealloc»). Instala PySide6 6.11 "
        f'(pip install "PySide6>=6.5,<6.12") o usa Python 3.12 o superior.\n'
        f"PySide6 {pyside} does not work with Python {python}: the process eventually aborts "
        f"(\"Fatal Python error: none_dealloc\"). Install PySide6 6.11 "
        f'(pip install "PySide6>=6.5,<6.12") or use Python 3.12 or newer.\n'
        f"({OVERRIDE_ENV}=1 skips this check.)"
    )
