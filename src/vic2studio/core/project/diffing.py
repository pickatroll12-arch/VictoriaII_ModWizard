"""Diferencias legibles para «Cambios pendientes» y el diálogo de revisión (wizard §6.5, P1)."""

from __future__ import annotations

from ..vfs.paths import VPath

MAX_DIFF_LINES = 400   # más allá se resume («y 1 234 líneas más»)


def unified_diff(rel: VPath, before: bytes | None, after: bytes | None, *, encoding: str = "cp1252",
                 context: int = 3) -> str:
    """``difflib.unified_diff`` de los dos textos (``a/<rel>``, ``b/<rel>``). Binarios: una línea de resumen."""
    raise NotImplementedError


def changed_lines(before: bytes | None, after: bytes | None, *, encoding: str = "cp1252") -> tuple[int, int]:
    """(líneas añadidas, líneas quitadas): el «diff de 1 línea» de los criterios de aceptación."""
    raise NotImplementedError
