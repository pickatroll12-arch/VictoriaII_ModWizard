"""Lectura, escritura y conversión a JSON de archivos de localización CSV."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from ..cancel import CancelCheck, raise_if_cancelled
from ..encoding import BOM, BOM_ENCODINGS, GAME_ENCODING, UTF8, detect_newline, encode_text, normalize_encoding, \
    split_bom, split_extra_boms
from ..fileio import FileStamp, atomic_write_bytes, read_text
from .model import COMMENT_PREFIX, DEFAULT_NEWLINE, SEPARATOR, LocalisationFile, LocRow, RowKind

_NEWLINES = ("\r\n", "\n")


def parse_csv(text: str, *, filename: str | os.PathLike | None = None,
              encoding: str | None = None, cancelled: CancelCheck = None) -> LocalisationFile:
    """Convierte el texto de un CSV en un ``LocalisationFile`` sin perder nada.

    Un U+FEFF inicial que la codificación deja en el texto (el BOM de ``utf-8``,
    ``utf-16-le`` o ``utf-16-be``; sin ``encoding``, el de UTF-8) se quita y se
    recuerda en ella (``encoding.split_bom``: ``utf-8-sig``...); los U+FEFF que
    siguen, un BOM repetido, van a ``extra_boms`` y no a la primera clave. Las
    filas se separan solo en LF (con o sin CR delante); un CR suelto es
    contenido. Sin saltos de línea en el texto se asume CRLF (el de vanilla). Si
    ``cancelled()`` devuelve True lanza ``core.cancel.Cancelled``.
    """
    encoding = encoding or (UTF8 if text.startswith(BOM) else GAME_ENCODING)
    text, encoding = split_bom(text, encoding)
    text, extra_boms = split_extra_boms(text, encoding)
    newline = detect_newline(text, lone_cr=False) if "\n" in text else DEFAULT_NEWLINE
    pieces = text.split("\n")
    trailing_newline = pieces[-1] == ""
    if trailing_newline:
        pieces.pop()
    last = len(pieces) - 1
    data, comment, blank = RowKind.DATA, RowKind.COMMENT, RowKind.BLANK
    rows = []
    for index, piece in enumerate(pieces):
        if not index & 0xFFF:
            raise_if_cancelled(cancelled)
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
                            trailing_newline=trailing_newline, path=filename, extra_boms=extra_boms)
    file.diagnostics = file.lint(cancelled=cancelled)
    return file


def read_csv_file(path: str | os.PathLike, *, encoding: str | None = None,
                  cancelled: CancelCheck = None) -> LocalisationFile:
    """Lee un CSV detectando la codificación (ver ``core.encoding.decode_bytes``) y guarda su huella."""
    raise_if_cancelled(cancelled)
    decoded = read_text(path, encoding)
    file = parse_csv(decoded.text, filename=path, encoding=decoded.encoding, cancelled=cancelled)
    file.stamp = decoded.stamp
    return file


def to_source(file: LocalisationFile) -> str:
    """Texto completo del archivo; sin ediciones coincide byte a byte con el original al codificarlo."""
    return file.to_source()


def _same_file(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def write_csv_file(path: str | os.PathLike, file: LocalisationFile, *,
                   encoding: str | None = None, backup: bool = True, force: bool = False) -> Path | None:
    """Codifica y escribe de forma atómica; devuelve la ruta de la copia ``.bak`` si se hizo.

    Lanza, antes de tocar el disco, ``UnencodableTextError`` si algún carácter
    no cabe en la codificación (por defecto la del archivo) y
    ``core.fileio.FileChangedError`` si se guarda sobre el archivo leído y este
    ha cambiado fuera de la aplicación desde que se leyó o guardó (``force``
    sobrescribe de todos modos). Los BOM repetidos (``extra_boms``) solo se
    conservan al guardar en la misma codificación, si es de las que llevan BOM.
    """
    path = Path(path)
    target = normalize_encoding(encoding or file.encoding)
    text = file.to_source()
    extra_boms = file.extra_boms
    if extra_boms and (target != normalize_encoding(file.encoding) or target not in BOM_ENCODINGS):
        text, extra_boms = text[extra_boms:], 0
    data = encode_text(text, target)
    expected = None
    if not force and file.stamp is not None and file.path is not None and _same_file(path, file.path):
        expected = file.stamp
    backup_path = atomic_write_bytes(path, data, backup=backup, expected=expected)
    file.path = path
    file.encoding = target
    file.extra_boms = extra_boms
    file.stamp = FileStamp.of(data)
    file.mark_saved()
    file.diagnostics = file.lint()
    return backup_path


def to_json(file: LocalisationFile) -> dict[str, Any]:
    """Representación JSON. Una fila lleva ``newline`` solo si su salto difiere del del archivo, y el
    archivo ``extra_boms`` solo si tiene BOM repetidos."""
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
    obj: dict[str, Any] = {
        "encoding": file.encoding,
        "newline": file.newline,
        "trailing_newline": file.trailing_newline,
    }
    if file.extra_boms:
        obj["extra_boms"] = file.extra_boms
    obj["rows"] = rows
    return obj


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
        encoding = normalize_encoding(encoding)
    except LookupError:
        raise ValueError(f"JSON de localización no válido: codificación de texto desconocida {encoding!r}") from None
    newline = obj.get("newline", DEFAULT_NEWLINE)
    _expect(newline in _NEWLINES, "newline debe ser '\\r\\n' o '\\n'")
    trailing = obj.get("trailing_newline", True)
    _expect(isinstance(trailing, bool), "trailing_newline debe ser booleano")
    extra_boms = obj.get("extra_boms", 0)
    _expect(type(extra_boms) is int and extra_boms >= 0, "extra_boms debe ser un entero no negativo")
    _expect(not extra_boms or encoding in BOM_ENCODINGS, f"extra_boms exige una codificación con BOM, no {encoding}")
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
        # Con un salto LF, un "\r" final se fundiría con él al volver a leer el archivo
        # (con CRLF no: "x\r\r\n" se lee como "x\r" más CRLF).
        terminated = number < len(items) or trailing
        effective = row_newline or newline
        _expect(not (terminated and effective == "\n" and row.to_line().endswith("\r")),
                f"{where}: termina en '\\r' y su salto es LF")
        rows.append(row)
    file = LocalisationFile(rows, encoding=encoding, newline=newline, trailing_newline=trailing,
                            extra_boms=extra_boms)
    file.diagnostics = file.lint()
    return file
