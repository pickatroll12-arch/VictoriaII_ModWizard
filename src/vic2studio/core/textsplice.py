"""Recomposición del texto de un editor sin reescribir las líneas que no se tocaron (I3).

``QPlainTextEdit`` trabaja siempre con ``\\n``. Al guardar no se puede volver a
escribir todo el archivo con el salto predominante: un archivo con saltos
mezclados cambiaría en líneas que nadie editó. ``splice_text`` compara la vista
vieja y la nueva línea a línea y copia de ``original`` solo los tramos iguales,
con su salto exacto; los tramos nuevos usan el salto pedido.
"""

from __future__ import annotations

import difflib
import re

# Una línea con su salto, sin usar ``str.splitlines`` (también parte por \x0c, \x1c, \x85 y U+2028).
_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$")


def normalize_newlines(text: str) -> str:
    """``\\r\\n`` y ``\\r`` sueltos pasan a ``\\n``."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _lines_with_endings(text: str) -> list[tuple[str, str]]:
    """[(contenido, salto)] de ``text``; el último salto puede ser ``""``."""
    lines = []
    for line in _LINE.findall(text):
        if line.endswith("\r\n"):
            lines.append((line[:-2], "\r\n"))
        elif line.endswith(("\r", "\n")):
            lines.append((line[:-1], line[-1]))
        else:
            lines.append((line, ""))
    return lines


def splice_text(original: str, old_view: str, new_view: str, newline: str) -> str:
    """Texto final sin tocar los caracteres de las líneas que no cambiaron.

    Las líneas iguales conservan el contenido y el salto exacto de ``original``;
    las nuevas o cambiadas llevan ``newline``. La última línea solo lleva salto si
    la vista nueva lo lleva. Precondición: ``normalize_newlines(original) == old_view``.
    """
    if normalize_newlines(original) != old_view:
        raise ValueError("old_view no es la vista normalizada de original")

    original_lines = _lines_with_endings(original)
    old_lines = old_view.split("\n")
    # La vista de un archivo que acaba en salto (o está vacío) tiene una línea vacía más.
    if len(original_lines) < len(old_lines):
        original_lines.extend([("", "")] * (len(old_lines) - len(original_lines)))

    new_lines = new_view.split("\n")
    last_new = len(new_lines) - 1
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    parts: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                content, ending = original_lines[i1 + offset]
                new_index = j1 + offset
                parts.append(content)
                parts.append("" if new_index == last_new else (ending or newline))
        elif tag in ("replace", "insert"):
            for new_index in range(j1, j2):
                parts.append(new_lines[new_index])
                parts.append("" if new_index == last_new else newline)
    return "".join(parts)


__all__ = ["normalize_newlines", "splice_text"]
