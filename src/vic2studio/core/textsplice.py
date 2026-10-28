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

    Solo compara el tramo entre el prefijo y el sufijo comunes, y nunca deja un
    ``\\r`` suelto seguido de una línea vacía con ``\\n``: se leerían como un solo salto y se perdería una línea.
    """
    if normalize_newlines(original) != old_view:
        raise ValueError("old_view no es la vista normalizada de original")
    original_lines = _lines_with_endings(original)
    old_lines = old_view.split("\n")
    new_lines = new_view.split("\n")
    # La vista de un archivo que acaba en salto (o está vacío) tiene una línea vacía más.
    if len(original_lines) < len(old_lines):
        original_lines.extend([("", "")] * (len(old_lines) - len(original_lines)))
    # Prefijo y sufijo comunes fuera de SequenceMatcher: con muchas líneas repetidas («}») es casi cuadrático.
    limit = min(len(old_lines), len(new_lines))
    head = 0
    while head < limit and old_lines[head] == new_lines[head]:
        head += 1
    tail = 0
    while tail < limit - head and old_lines[-1 - tail] == new_lines[-1 - tail]:
        tail += 1
    pairs = [(k, k) for k in range(head)]          # (línea de old o None si es nueva, línea de new)
    matcher = difflib.SequenceMatcher(None, old_lines[head:len(old_lines) - tail],
                                      new_lines[head:len(new_lines) - tail], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            pairs.extend((head + i1 + k, head + j1 + k) for k in range(i2 - i1))
        elif tag in ("replace", "insert"):
            pairs.extend((None, head + j) for j in range(j1, j2))
    pairs.extend((len(old_lines) - tail + k, len(new_lines) - tail + k) for k in range(tail))
    last_new = len(new_lines) - 1
    parts: list[str] = []
    after_cr = False
    for old_index, new_index in pairs:
        content, ending = original_lines[old_index] if old_index is not None else (new_lines[new_index], newline)
        ending = "" if new_index == last_new else (ending or newline)
        if after_cr and not content and ending == "\n":
            ending = "\r\n"   # «\r» + «\n» se leería como un solo salto
        parts.append(content)
        parts.append(ending)
        if content or ending:
            after_cr = ending == "\r"
    return "".join(parts)


__all__ = ["normalize_newlines", "splice_text"]
