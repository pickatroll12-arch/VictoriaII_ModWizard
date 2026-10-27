"""Diferencias legibles para «Cambios pendientes» y el diálogo de revisión (wizard §6.5, P1).

Las líneas se parten solo en ``\\r\\n``, ``\\r`` y ``\\n`` (``str.splitlines`` partiría
también en ``\\x0c``, ``\\x1c``…, que no son saltos para el juego).
"""

from __future__ import annotations

import difflib
import re

from ..encoding import decode_bytes
from ..vfs.paths import VPath

MAX_DIFF_LINES = 400   # más allá se resume («y 1 234 líneas más»)
_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$")


def _lines(data: bytes | None, encoding: str | None) -> list[str]:
    if not data:
        return []
    text = decode_bytes(data, encoding).text
    return [line.rstrip("\r\n") for line in _LINE_RE.findall(text)]


def is_binary(data: bytes | None) -> bool:
    """Heurística de «Cambios pendientes»: hay un NUL en los primeros 8 KB (UTF-16 incluido)."""
    return bool(data) and b"\0" in data[:8192]


def binary_summary(rel: VPath, before: int | None, after: int | None) -> str:
    """La línea que resume un binario que cambia: tamaños en bytes (``None``: no existe)."""
    size = lambda length: "-" if length is None else str(length)  # noqa: E731
    return f"Binary files a/{rel} and b/{rel} differ ({size(before)} -> {size(after)} bytes)"


def unified_diff(rel: VPath, before: bytes | None, after: bytes | None, *, encoding: str = "cp1252",
                 context: int = 3) -> str:
    """``difflib.unified_diff`` de los dos textos (``a/<rel>``, ``b/<rel>``). Binarios: una línea de resumen."""
    if is_binary(before) or is_binary(after):
        if before == after:
            return ""
        return binary_summary(rel, None if before is None else len(before), None if after is None else len(after))
    lines = list(difflib.unified_diff(_lines(before, encoding), _lines(after, encoding), f"a/{rel}", f"b/{rel}",
                                      n=context, lineterm=""))
    if len(lines) > MAX_DIFF_LINES:
        rest = len(lines) - MAX_DIFF_LINES
        lines = lines[:MAX_DIFF_LINES] + [f"... (+{rest} lines)"]
    return "\n".join(lines)


def changed_lines(before: bytes | None, after: bytes | None, *, encoding: str = "cp1252") -> tuple[int, int]:
    """(líneas añadidas, líneas quitadas): el «diff de 1 línea» de los criterios de aceptación."""
    old, new = _lines(before, encoding), _lines(after, encoding)
    added = removed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, removed
