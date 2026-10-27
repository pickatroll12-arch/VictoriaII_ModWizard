"""Atajos comunes de los extractores (no registra ninguno): crear símbolos y referencias, normalizar rutas."""

from __future__ import annotations

from types import MappingProxyType

from ...vfs.model import LayerKind
from ...vfs.paths import VPath
from ..model import Symbol, SymbolRef

EMPTY = MappingProxyType({})


class Facts:
    """Acumula las definiciones y referencias de un archivo."""

    __slots__ = ("rel", "layer", "defs", "refs")

    def __init__(self, rel: VPath, layer: LayerKind) -> None:
        self.rel = rel
        self.layer = layer
        self.defs: list[Symbol] = []
        self.refs: list[SymbolRef] = []

    def define(self, kind: str, name: str, line: int | None, attrs: dict | None = None) -> Symbol:
        symbol = Symbol(kind, name, self.rel, line, self.layer, MappingProxyType(attrs) if attrs else EMPTY)
        self.defs.append(symbol)
        return symbol

    def ref(self, kind: str, name: str, entry_or_line, role: str, column: int | None = None) -> None:
        if isinstance(entry_or_line, int) or entry_or_line is None:
            line = entry_or_line
        else:
            line, column = entry_or_line.line, entry_or_line.column
        self.refs.append(SymbolRef(kind, name, self.rel, line, column, role))

    def result(self) -> tuple[tuple[Symbol, ...], tuple[SymbolRef, ...]]:
        return tuple(self.defs), tuple(self.refs)


def path_name(raw: str, prefix: str = "") -> str | None:
    """Ruta de un archivo nombrado en otro (``gfx\\\\x.dds``, ``/1861/PRU_oob.txt``) como nombre de símbolo:
    relativa, con «/» y en minúsculas; None si no es una ruta válida."""
    text = raw.strip().replace("\\", "/")
    if prefix:
        text = prefix.rstrip("/") + "/" + text.lstrip("/")
    try:
        return VPath.of(text).lower()
    except ValueError:
        return None
