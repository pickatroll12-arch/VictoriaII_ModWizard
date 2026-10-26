"""Lectura, escritura y conversión a JSON de archivos de localización CSV."""

from __future__ import annotations

import codecs
import os
from pathlib import Path
from typing import Any, Mapping

from ..encoding import GAME_ENCODING, UTF8, UTF8_BOM, detect_newline, encode_text
from ..fileio import atomic_write_bytes, read_text
from .model import COMMENT_PREFIX, DEFAULT_NEWLINE, SEPARATOR, LocalisationFile, LocRow, RowKind

_BOM = "﻿"
_NEWLINES = ("\r\n", "\n")


def parse_csv(text: str, *, filename: str | os.PathLike | None = None,
              encoding: str | None = None) -> LocalisationFile:
    """Convierte el texto de un CSV en un ``LocalisationFile`` sin perder nada.

    Un BOM inicial se quita del texto y se recuerda como codificación
    ``utf-8-sig``. Sin saltos de línea en el texto se asume CRLF (el de vanilla).
    """
    if text.startswith(_BOM) and (encoding is None or codecs.lookup(encoding).name in (UTF8, UTF8_BOM)):
        text, encoding = text[1:], UTF8_BOM
    encoding = codecs.lookup(encoding).name if encoding else GAME_ENCODING
    newline = detect_newline(text) if "\n" in text else DEFAULT_NEWLINE
    pieces = text.split("\n")
    trailing_newline = pieces[-1] == ""
    if trailing_newline:
        pieces.pop()
    last = len(pieces) - 1
    data, comment, blank = RowKind.DATA, RowKind.COMMENT, RowKind.BLANK
    rows = []
    for index, piece in enumerate(pieces):
        terminated = index < last or trailing_newline
        if terminated and piece.endswith("\r"):
            line, eol = piece[:-1], "\r\n"
        else:
            line, eol = piece, "\n"
        override = eol if terminated and eol != newline else None
        if not line or line.isspace():
            row = LocRow(blank, line=index + 1, raw=line, newline=override)
        elif line[0] == COMMENT_PREFIX:
            row = LocRow(comment, line=index + 1, raw=line, newline=override)
        else:
            parts = line.split(SEPARATOR)
            row = LocRow(data, parts[0], parts[1:], line=index + 1, raw=line, newline=override)
        rows.append(row)
    file = LocalisationFile(rows, encoding=encoding, newline=newline,
                            trailing_newline=trailing_newline, path=filename)
    file.diagnostics = file.lint()
    return file


def read_csv_file(path: str | os.PathLike, *, encoding: str | None = None) -> LocalisationFile:
    """Lee un CSV detectando la codificación (ver ``core.encoding.decode_bytes``)."""
    decoded = read_text(path, encoding)
    return parse_csv(decoded.text, filename=path, encoding=decoded.encoding)


def to_source(file: LocalisationFile) -> str:
    """Texto completo del archivo; sin ediciones coincide byte a byte con el original al codificarlo."""
    return file.to_source()


def write_csv_file(path: str | os.PathLike, file: LocalisationFile, *,
                   encoding: str | None = None, backup: bool = True) -> Path | None:
    """Codifica y escribe de forma atómica; devuelve la ruta de la copia ``.bak`` si se hizo.

    Lanza ``UnencodableTextError`` antes de tocar el disco si algún carácter no
    cabe en la codificación (por defecto la del archivo).
    """
    target = codecs.lookup(encoding or file.encoding).name
    data = encode_text(file.to_source(), target)
    backup_path = atomic_write_bytes(path, data, backup=backup)
    file.path = Path(path)
    file.encoding = target
    file.mark_saved()
    file.diagnostics = file.lint()
    return backup_path


def to_json(file: LocalisationFile) -> dict[str, Any]:
    """Representación JSON. Una fila lleva ``newline`` solo si su salto difiere del del archivo."""
    rows = []
    for row in file.rows:
        if row.kind is RowKind.DATA:
            item: dict[str, Any] = {"kind": "data", "key": row.key, "fields": list(row.fields)}
        elif row.kind is RowKind.COMMENT:
            item = {"kind": "comment", "text": row.raw or ""}
        else:
            item = {"kind": "blank"}
            if row.raw:
                item["text"] = row.raw
        if row.newline is not None:
            item["newline"] = row.newline
        rows.append(item)
    return {
        "encoding": file.encoding,
        "newline": file.newline,
        "trailing_newline": file.trailing_newline,
        "rows": rows,
    }


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"JSON de localización no válido: {message}")


def _text(value: Any, what: str, *, allow_separator: bool = False) -> str:
    _expect(isinstance(value, str), f"{what} debe ser una cadena")
    _expect("\n" not in value, f"{what} contiene un salto de línea")
    _expect(allow_separator or SEPARATOR not in value, f"{what} contiene ';'")
    return value


def from_json(obj: Mapping[str, Any]) -> LocalisationFile:
    """Inversa de ``to_json``; lanza ``ValueError`` si la estructura no es válida."""
    _expect(isinstance(obj, Mapping), "se esperaba un objeto")
    encoding = obj.get("encoding", GAME_ENCODING)
    _expect(isinstance(encoding, str), "encoding debe ser una cadena")
    try:
        encoding = codecs.lookup(encoding).name
    except LookupError:
        raise ValueError(f"JSON de localización no válido: codificación desconocida {encoding!r}") from None
    newline = obj.get("newline", DEFAULT_NEWLINE)
    _expect(newline in _NEWLINES, "newline debe ser '\\r\\n' o '\\n'")
    trailing = obj.get("trailing_newline", True)
    _expect(isinstance(trailing, bool), "trailing_newline debe ser booleano")
    items = obj.get("rows", [])
    _expect(isinstance(items, list), "rows debe ser una lista")
    rows = []
    for number, item in enumerate(items, 1):
        where = f"fila {number}"
        _expect(isinstance(item, Mapping), f"{where} debe ser un objeto")
        kind = item.get("kind")
        row_newline = item.get("newline")
        _expect(row_newline is None or row_newline in _NEWLINES, f"{where}: newline no válido")
        if kind == "data":
            key = _text(item.get("key"), f"{where}: key")
            fields = item.get("fields", [])
            _expect(isinstance(fields, list), f"{where}: fields debe ser una lista")
            fields = [_text(f, f"{where}: campo") for f in fields]
            _expect(not key.startswith(COMMENT_PREFIX), f"{where}: la clave empieza por '#'")
            _expect(bool(fields) or bool(key.strip()), f"{where}: fila de datos vacía")
            row = LocRow(RowKind.DATA, key, fields)
        elif kind == "comment":
            text = _text(item.get("text"), f"{where}: text", allow_separator=True)
            _expect(text.startswith(COMMENT_PREFIX), f"{where}: un comentario debe empezar por '#'")
            row = LocRow(RowKind.COMMENT, raw=text)
        elif kind == "blank":
            text = _text(item.get("text", ""), f"{where}: text")
            _expect(not text.strip(), f"{where}: una línea vacía solo admite espacios")
            row = LocRow(RowKind.BLANK, raw=text)
        else:
            raise ValueError(f"JSON de localización no válido: {where}: tipo desconocido {kind!r}")
        row.line = number
        row.newline = row_newline
        if row.kind is RowKind.DATA:
            row.raw = row.to_line()
        # Un "\r" final se fundiría con el salto al volver a leer el archivo.
        terminated = number < len(items) or trailing
        _expect(not (terminated and row.to_line().endswith("\r")), f"{where}: termina en '\\r'")
        rows.append(row)
    file = LocalisationFile(rows, encoding=encoding, newline=newline, trailing_newline=trailing)
    file.diagnostics = file.lint()
    return file
