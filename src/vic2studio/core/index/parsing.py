"""Apoyo de los extractores: analizar cada archivo una sola vez y leer valores del árbol (wizard §7).

``document(data)`` analiza los bytes de un archivo Clausewitz con la misma
detección de codificación que el resto del Studio (``project.codecs.parse_bytes``)
y recuerda el último resultado por hilo: los varios extractores de un mismo
archivo reciben el mismo objeto ``bytes`` (``builder.extract_bytes``) y comparten
el árbol. ``parse_count`` cuenta los análisis de verdad (pruebas).

Los extractores reciben bytes (I12): el árbol que se crea aquí es suyo y se tira
al terminar; nunca es el CST vivo del ``Workspace``.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator

from ..clausewitz.nodes import Block, Document, Entry, Scalar

_local = threading.local()
_lock = threading.Lock()
_parses = 0

INT_RE = re.compile(r"-?\d+")
NUMBER_RE = re.compile(r"-?(?:\d+\.?\d*|\.\d+)")
DATE_RE = re.compile(r"(-?\d+)\.(\d+)\.(\d+)")


def document(data: bytes) -> Document:
    """Árbol de ``data`` (analizado una vez por objeto ``bytes`` y por hilo)."""
    global _parses
    memo = getattr(_local, "memo", None)
    if memo is not None and memo[0] is data:
        return memo[1]
    from ..project.codecs import parse_bytes

    doc = parse_bytes(bytes(data)).document
    _local.memo = (data, doc)
    with _lock:
        _parses += 1
    return doc


def forget() -> None:
    """Suelta el árbol recordado (al terminar con un archivo, para no retener memoria)."""
    _local.memo = None


def parse_count() -> int:
    """Análisis hechos en este proceso (para comprobar que cada archivo se analiza una sola vez)."""
    return _parses


# --- lectura del árbol ---------------------------------------------------------------------------------


def text_of(value) -> str | None:
    """Texto de un escalar; None si es un bloque."""
    return value.text if value.__class__ is Scalar else None


def key_of(entry: Entry) -> str | None:
    key = entry.key
    return None if key is None else key.text


def blocks(block: Block) -> Iterator[tuple[str, Block, Entry]]:
    """``(clave, bloque, entrada)`` de cada asignación ``clave = { … }`` directa de ``block``."""
    for entry in block.entries:
        key = entry.key
        if key is not None and entry.value.__class__ is not Scalar:
            yield key.text, entry.value, entry


def scalars(block: Block) -> Iterator[tuple[str, str, Entry]]:
    """``(clave, texto, entrada)`` de cada asignación ``clave = valor`` directa de ``block``."""
    for entry in block.entries:
        key = entry.key
        if key is not None and entry.value.__class__ is Scalar:
            yield key.text, entry.value.text, entry


def loose_values(block: Block) -> list[str]:
    """Textos de los valores sueltos de ``block`` (``{ 1 2 3 }``)."""
    return [e.value.text for e in block.entries if e.key is None and e.value.__class__ is Scalar]


def get_text(block: Block, key: str, *, ignore_case: bool = False) -> str | None:
    return block.get_text(key, None, ignore_case=ignore_case)


def as_int(text: str | None) -> int | None:
    if text is None or INT_RE.fullmatch(text) is None:
        return None
    return int(text)


def leading_int(text: str | None) -> int | None:
    """Entero inicial al estilo ``atoi`` (``"223."`` → 223, H4); None si no empieza por un número."""
    if text is None:
        return None
    match = re.match(r"\s*(-?\d+)", text)
    return int(match.group(1)) if match else None


def as_number(text: str | None) -> float | None:
    if text is None or NUMBER_RE.fullmatch(text) is None:
        return None
    return float(text)


def is_date(text: str | None) -> bool:
    if text is None:
        return False
    match = DATE_RE.fullmatch(text)
    return match is not None


def walk(block: Block) -> Iterator[tuple[Entry, int]]:
    """Todas las entradas bajo ``block`` en preorden, con su profundidad (1 = hijas directas). Sin recursión."""
    stack: list[tuple[Iterator[Entry], int]] = [(iter(block.entries), 1)]
    while stack:
        items, depth = stack[-1]
        for entry in items:
            yield entry, depth
            if entry.value.__class__ is not Scalar:
                stack.append((iter(entry.value.entries), depth + 1))
                break
        else:
            stack.pop()
