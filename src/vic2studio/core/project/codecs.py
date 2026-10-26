"""Códecs de documento: bytes ⇄ modelo vivo, sin pérdidas (wizard §6.1, I3).

``render`` está comprobado: verifica por relectura y codifica, y lanza antes de
tocar el disco (``SourceMismatchError``, ``UnencodableTextError``). ``snapshot``
da los bytes con que se deshace, se pasa a los hilos de fondo y se indexa: para
los códecs de texto coincide con ``render`` sin verificar, y ``load(snapshot(m))``
reproduce ``m`` exactamente (la ida y vuelta byte a byte lo garantiza, D3).

En la iteración 2 hay CLAUSEWITZ, LOCALISATION y BINARY (solo lectura). TABLE,
LUA, BMP e IMAGE llegan con su iteración y se registran con ``register_codec``.
"""

from __future__ import annotations

from typing import Protocol

from ..vfs.model import DocKind
from ..vfs.paths import VPath


class DocCodec(Protocol):
    kind: DocKind
    writable: bool

    def load(self, data: bytes, rel: VPath) -> tuple[object, list]:
        """Modelo y diagnósticos. Nunca falla por sintaxis: los errores van en la lista."""
        ...

    def render(self, model: object) -> bytes:
        """Bytes que se escribirán; lanza si no se pueden escribir sin pérdidas."""
        ...

    def snapshot(self, model: object) -> bytes:
        ...

    def empty(self, rel: VPath) -> object:
        """Modelo de un documento nuevo (cp1252 y CRLF, NEW_FILE_*)."""
        ...


class ClausewitzCodec:
    """``ParseResult`` de ``clausewitz.parse``; ``render`` es ``serializer.render_checked``."""

    kind = DocKind.CLAUSEWITZ
    writable = True

    def load(self, data: bytes, rel: VPath) -> tuple[object, list]:
        raise NotImplementedError

    def render(self, model: object) -> bytes:
        raise NotImplementedError

    def snapshot(self, model: object) -> bytes:
        raise NotImplementedError

    def empty(self, rel: VPath) -> object:
        raise NotImplementedError


class LocalisationCodec:
    """``LocalisationFile`` de ``csvloc.parse_csv``; ``render`` es ``csvloc.render_csv_checked``."""

    kind = DocKind.LOCALISATION
    writable = True

    def load(self, data: bytes, rel: VPath) -> tuple[object, list]:
        raise NotImplementedError

    def render(self, model: object) -> bytes:
        raise NotImplementedError

    def snapshot(self, model: object) -> bytes:
        raise NotImplementedError

    def empty(self, rel: VPath) -> object:
        raise NotImplementedError


class BinaryCodec:
    """Bytes tal cual; ``writable=False`` hasta que su tipo tenga códec propio."""

    kind = DocKind.BINARY
    writable = False

    def load(self, data: bytes, rel: VPath) -> tuple[object, list]:
        raise NotImplementedError

    def render(self, model: object) -> bytes:
        raise NotImplementedError

    def snapshot(self, model: object) -> bytes:
        raise NotImplementedError

    def empty(self, rel: VPath) -> object:
        raise NotImplementedError


def register_codec(codec: DocCodec) -> None:
    raise NotImplementedError


def codec_for(kind: DocKind) -> DocCodec:
    raise NotImplementedError


def kind_for(rel: VPath) -> DocKind:
    """Tipo de documento de una ruta: la regla de carga (``vfs.rules.rule_for``) o, si no, la extensión."""
    raise NotImplementedError
