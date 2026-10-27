"""Códecs de documento: bytes ⇄ modelo vivo, sin pérdidas (wizard §6.1, I3).

``render`` está comprobado: verifica por relectura y codifica, y lanza antes de
tocar el disco (``SourceMismatchError``, ``UnencodableTextError``). ``snapshot``
da los bytes con que se deshace, se pasa a los hilos de fondo y se indexa: para
los códecs de texto coincide con ``render`` sin verificar, y ``load(snapshot(m))``
reproduce ``m`` exactamente (la ida y vuelta byte a byte lo garantiza, D3).

En la iteración 2 hay CLAUSEWITZ, LOCALISATION, JSON (``project.json``) y BINARY
(solo lectura). TABLE, LUA, BMP e IMAGE llegan con su iteración y se registran
con ``register_codec``; hasta entonces se abren con ``BinaryCodec``.
"""

from __future__ import annotations

import json
from typing import Protocol

from ..clausewitz import parser as _parser
from ..clausewitz.nodes import Document
from ..clausewitz.parser import ParseResult, parse
from ..clausewitz.serializer import render_checked
from ..csvloc.model import LocalisationFile
from ..csvloc.serialization import parse_csv, render_csv_checked
from ..encoding import GAME_ENCODING, decode_bytes, match_bom, split_bom, split_extra_boms
from ..fileio import FileStamp
from ..vfs.model import DocKind
from ..vfs.paths import VPath
from ..vfs.rules import rule_for

# Archivos nuevos del mod: como los de vanilla (H3).
NEW_FILE_ENCODING = GAME_ENCODING
NEW_FILE_NEWLINE = "\r\n"


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


def parse_bytes(data: bytes, *, filename=None) -> ParseResult:
    """``parser.parse_file`` sobre bytes ya leídos: misma detección de codificación, BOM y diagnósticos."""
    decoded = decode_bytes(data)
    text, name = split_bom(decoded.text, match_bom(data, decoded.encoding))
    text, extra_boms = split_extra_boms(text, name)
    result = parse(text, filename=filename)
    result.encoding = name
    result.document.extra_boms = extra_boms
    result.stamp = FileStamp.of(data)
    diagnostic = _parser._encoding_diagnostic(text, name)
    if diagnostic is not None:
        result.diagnostics.insert(0, diagnostic)
        result.diagnostics.sort(key=lambda d: d.offset)
    return result


class ClausewitzCodec:
    """``ParseResult`` de ``clausewitz.parse``; ``render`` es ``serializer.render_checked``."""

    kind = DocKind.CLAUSEWITZ
    writable = True

    def load(self, data: bytes, rel: VPath) -> tuple[object, list]:
        result = parse_bytes(data)
        return result, result.diagnostics

    def render(self, model: object, *, rel: VPath | None = None) -> bytes:
        return render_checked(model, path=rel)

    def snapshot(self, model: object) -> bytes:
        return render_checked(model, verify=False)

    def empty(self, rel: VPath) -> object:
        return ParseResult(Document(newline=NEW_FILE_NEWLINE, encoding=NEW_FILE_ENCODING))


class LocalisationCodec:
    """``LocalisationFile`` de ``csvloc.parse_csv``; ``render`` es ``csvloc.render_csv_checked``."""

    kind = DocKind.LOCALISATION
    writable = True

    def load(self, data: bytes, rel: VPath) -> tuple[object, list]:
        decoded = decode_bytes(data)
        file = parse_csv(decoded.text, encoding=decoded.encoding)
        file.stamp = FileStamp.of(data)
        return file, file.diagnostics

    def render(self, model: object, *, rel: VPath | None = None) -> bytes:
        return render_csv_checked(model)

    def snapshot(self, model: object) -> bytes:
        return render_csv_checked(model)

    def empty(self, rel: VPath) -> object:
        return LocalisationFile(encoding=NEW_FILE_ENCODING, newline=NEW_FILE_NEWLINE)


class JsonCodec:
    """Archivos JSON propios del Studio (``.vic2studio/project.json``): el modelo son los bytes UTF-8.

    ``render`` comprueba que sean un JSON válido antes de escribir.
    """

    kind = DocKind.JSON
    writable = True

    def load(self, data: bytes, rel: VPath) -> tuple[object, list]:
        return bytes(data), []

    def render(self, model: object, *, rel: VPath | None = None) -> bytes:
        data = bytes(model)
        json.loads(data.decode("utf-8"))
        return data

    def snapshot(self, model: object) -> bytes:
        return bytes(model)

    def empty(self, rel: VPath) -> object:
        return b"{}\n"


class BinaryCodec:
    """Bytes tal cual; ``writable=False`` hasta que su tipo tenga códec propio."""

    kind = DocKind.BINARY
    writable = False

    def load(self, data: bytes, rel: VPath) -> tuple[object, list]:
        return bytes(data), []

    def render(self, model: object, *, rel: VPath | None = None) -> bytes:
        return bytes(model)

    def snapshot(self, model: object) -> bytes:
        return bytes(model)

    def empty(self, rel: VPath) -> object:
        return b""


_BINARY = BinaryCodec()
_CODECS: dict[DocKind, DocCodec] = {}


def register_codec(codec: DocCodec) -> None:
    _CODECS[codec.kind] = codec


def codec_for(kind: DocKind) -> DocCodec:
    """Códec registrado para ``kind``; sin códec propio, ``BinaryCodec`` (solo lectura)."""
    return _CODECS.get(kind, _BINARY)


def kind_for(rel: VPath) -> DocKind:
    """Tipo de documento de una ruta: la regla de carga (``vfs.rules.rule_for``) o, si no, la extensión."""
    rel = VPath.of(rel)
    if rel.suffix == ".json" and rel.is_under(".vic2studio"):
        return DocKind.JSON
    return rule_for(rel).doc_kind


for _codec in (ClausewitzCodec(), LocalisationCodec(), JsonCodec(), _BINARY):
    register_codec(_codec)
