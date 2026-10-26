"""Modelo en memoria de un archivo de localización CSV de Victoria II.

Cada línea del archivo es una ``LocRow``. Las filas de datos guardan la clave y
los campos crudos tal cual (``line.split(";")``), de modo que unirlos con ";"
reproduce exactamente la línea original. Solo al editar una fila con ``set``
se normaliza su estructura a ``clave;13 idiomas;x;extras``.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Iterator, Mapping, Union

from ..encoding import GAME_ENCODING

SEPARATOR = ";"
COMMENT_PREFIX = "#"
END_MARKER = "x"
DEFAULT_NEWLINE = "\r\n"

# Columna i+1 de cada línea (la columna 0 es la clave).
LANGUAGE_COLUMNS = [
    "English", "French", "German", "Polish", "Spanish", "Italian", "Swedish",
    "Czech", "Hungarian", "Dutch", "Portuguese", "Russian", "Finnish",
]
LANGUAGE_CODES = {
    "en": 1, "fr": 2, "de": 3, "pl": 4, "es": 5, "it": 6, "sv": 7,
    "cs": 8, "hu": 9, "nl": 10, "pt": 11, "ru": 12, "fi": 13,
}
# El juego vanilla solo ofrece estos cuatro idiomas; el resto de columnas existe
# por herencia del formato y el juego no las muestra.
DISPLAYED_LANGUAGES = ("English", "French", "German", "Spanish")
LANGUAGE_COUNT = len(LANGUAGE_COLUMNS)
END_MARKER_COLUMN = LANGUAGE_COUNT + 1

_LANGUAGE_BY_NAME = {name.lower(): index for index, name in enumerate(LANGUAGE_COLUMNS, 1)}

Lang = Union[str, int]


class RowKind(Enum):
    DATA = "data"
    COMMENT = "comment"
    BLANK = "blank"


class InvalidFieldError(ValueError):
    """Un texto o clave no se puede representar en una línea del CSV."""


def column_index(lang: Lang) -> int:
    """Columna de ``lang``: código ("es"), nombre ("Spanish") o índice de columna (int)."""
    if isinstance(lang, bool):
        raise TypeError("idioma no válido: bool")
    if isinstance(lang, int):
        if lang < 0:
            raise ValueError(f"índice de columna negativo: {lang}")
        return lang
    if isinstance(lang, str):
        lowered = lang.strip().lower()
        index = LANGUAGE_CODES.get(lowered) or _LANGUAGE_BY_NAME.get(lowered)
        if index is not None:
            return index
        raise ValueError(f"idioma desconocido: {lang!r}")
    raise TypeError(f"idioma no válido: {lang!r}")


def language_column(lang: Lang) -> int:
    """Como ``column_index`` pero exige una columna de idioma (1..13)."""
    index = column_index(lang)
    if not 1 <= index <= LANGUAGE_COUNT:
        raise ValueError(f"la columna {index} no es de idioma (1..{LANGUAGE_COUNT})")
    return index


def is_end_marker(field: str) -> bool:
    # El corpus vanilla también usa "X", "x " y "x" seguido de tabuladores.
    return field.strip().lower() == END_MARKER


def marker_index(fields: list[str]) -> int | None:
    """Posición en ``fields`` del marcador de fin, o ``None``.

    Prioriza la columna 14; si no, toma la última "x" tras la que solo quedan
    campos vacíos (filas con columnas de menos o de más).
    """
    if len(fields) >= LANGUAGE_COUNT + 1 and is_end_marker(fields[LANGUAGE_COUNT]):
        return LANGUAGE_COUNT
    for index in range(len(fields) - 1, -1, -1):
        field = fields[index]
        if is_end_marker(field):
            return index
        if field.strip():
            return None
    return None


def normalized_fields(fields: list[str]) -> list[str]:
    """Campos reorganizados como 13 idiomas + marcador + extras, sin perder texto.

    Los idiomas conservan su posición. Si había texto entre la columna 14 y una
    "x" desplazada, ese texto pasa detrás del marcador en vez de perderse.
    """
    marker = marker_index(fields)
    if marker is None:
        languages = fields[:LANGUAGE_COUNT]
        extras = fields[LANGUAGE_COUNT:]
        if extras and not extras[0].strip():
            extras = extras[1:]
        end = END_MARKER
    else:
        languages = fields[:min(marker, LANGUAGE_COUNT)]
        overflow = fields[LANGUAGE_COUNT:marker]
        end = fields[marker]
        extras = fields[marker + 1:]
        if any(f.strip() for f in overflow):
            extras = overflow + extras
    languages = languages + [""] * (LANGUAGE_COUNT - len(languages))
    return languages + [end] + extras


def check_text(text: str) -> None:
    """Lanza ``InvalidFieldError`` si ``text`` no cabe en un campo del CSV."""
    if not isinstance(text, str):
        raise TypeError(f"el texto debe ser str, no {type(text).__name__}")
    for char in (SEPARATOR, "\n", "\r"):
        if char in text:
            raise InvalidFieldError(
                f"el texto no puede contener {char!r}: el juego no admite escapes en el CSV"
                + (" (usa la secuencia \\n para saltos de línea)" if char != SEPARATOR else "")
            )


def check_key(key: str) -> None:
    check_text(key)
    if not key or key != key.strip():
        raise InvalidFieldError(f"clave vacía o con espacios en los extremos: {key!r}")
    if key.startswith(COMMENT_PREFIX):
        raise InvalidFieldError(f"una clave no puede empezar por {COMMENT_PREFIX!r}: {key!r}")


class LocRow:
    """Una línea del archivo.

    En filas de datos ``fields`` son todas las columnas tras la clave, incluida
    la "x" y los campos extra. En comentarios y líneas vacías ``key`` es "",
    ``fields`` está vacío y ``raw`` es el contenido de la línea. ``line`` es la
    línea (1-based) en el archivo leído, o ``None`` en filas nuevas. ``newline``
    solo se usa si el salto de esta línea difiere del del archivo.
    """

    __slots__ = ("kind", "key", "fields", "line", "raw", "modified", "newline")

    def __init__(self, kind: RowKind, key: str = "", fields: list[str] | None = None, *,
                 line: int | None = None, raw: str | None = None, modified: bool = False,
                 newline: str | None = None):
        self.kind = kind
        self.key = key
        self.fields = fields if fields is not None else []
        self.line = line
        self.raw = raw
        self.modified = modified
        self.newline = newline

    @classmethod
    def comment(cls, text: str) -> LocRow:
        return cls(RowKind.COMMENT, raw=text, modified=True)

    @classmethod
    def blank(cls, text: str = "") -> LocRow:
        return cls(RowKind.BLANK, raw=text, modified=True)

    @property
    def has_end_marker(self) -> bool:
        return len(self.fields) > LANGUAGE_COUNT and is_end_marker(self.fields[LANGUAGE_COUNT])

    @property
    def texts(self) -> list[str]:
        """Las 13 columnas de idioma por posición (vacías si faltan)."""
        texts = self.fields[:LANGUAGE_COUNT]
        return texts + [""] * (LANGUAGE_COUNT - len(texts))

    def get(self, lang: Lang) -> str:
        index = column_index(lang)
        if self.kind is not RowKind.DATA:
            return ""
        if index == 0:
            return self.key
        return self.fields[index - 1] if index <= len(self.fields) else ""

    def set(self, lang: Lang, text: str) -> None:
        """Cambia una columna de idioma y normaliza la fila (ver ``normalized_fields``)."""
        if self.kind is not RowKind.DATA:
            raise ValueError("solo se pueden editar filas de datos")
        index = language_column(lang)
        check_text(text)
        fields = normalized_fields(self.fields)
        fields[index - 1] = text
        if fields != self.fields:
            self.fields = fields
            self.modified = True

    def to_line(self) -> str:
        """Texto de la línea sin el salto."""
        if self.kind is RowKind.DATA:
            if not self.fields:
                return self.key
            return SEPARATOR.join([self.key, *self.fields])
        return self.raw or ""

    def __repr__(self) -> str:
        if self.kind is RowKind.DATA:
            return f"LocRow(line={self.line}, key={self.key!r}, fields={len(self.fields)})"
        return f"LocRow({self.kind.value}, line={self.line}, raw={self.raw!r})"


class LocalisationFile:
    """Archivo de localización completo, editable y serializable sin pérdidas."""

    def __init__(self, rows: list[LocRow] | None = None, *, encoding: str = GAME_ENCODING,
                 newline: str = DEFAULT_NEWLINE, trailing_newline: bool = True,
                 path: str | os.PathLike | None = None):
        self.rows: list[LocRow] = rows if rows is not None else []
        self.encoding = encoding
        self.newline = newline
        self.trailing_newline = trailing_newline
        self.path = Path(path) if path is not None else None
        self.diagnostics: list = []
        self._structure_changed = False
        self._index: dict[str, LocRow] | None = None
        self._index_size = -1

    # --- consulta -------------------------------------------------------

    def _key_index(self) -> dict[str, LocRow]:
        # Se reconstruye si cambia el número de filas; las ediciones a través
        # de los métodos de esta clase lo invalidan explícitamente.
        if self._index is None or self._index_size != len(self.rows):
            index: dict[str, LocRow] = {}
            for row in self.rows:
                if row.kind is RowKind.DATA and row.key not in index:
                    index[row.key] = row
            self._index, self._index_size = index, len(self.rows)
        return self._index

    def invalidate_index(self) -> None:
        self._index = None

    def data_rows(self) -> Iterator[LocRow]:
        return (row for row in self.rows if row.kind is RowKind.DATA)

    def keys(self) -> list[str]:
        """Claves en orden de primera aparición, sin repetir."""
        return list(self._key_index())

    def get_row(self, key: str) -> LocRow | None:
        """Primera fila con esa clave (la que usa el juego)."""
        return self._key_index().get(key)

    def get(self, key: str, lang: Lang) -> str | None:
        """Texto de ``key`` en ``lang``; ``None`` si la clave no existe."""
        row = self.get_row(key)
        return None if row is None else row.get(lang)

    def __contains__(self, key: object) -> bool:
        return key in self._key_index()

    def __len__(self) -> int:
        return len(self.rows)

    @property
    def modified(self) -> bool:
        return self._structure_changed or any(row.modified for row in self.rows)

    # --- edición --------------------------------------------------------

    def set(self, key: str, lang: Lang, text: str) -> LocRow:
        """Cambia un texto; si la clave no existe crea la fila al final."""
        row = self.get_row(key)
        if row is None:
            return self.add_row(key, {lang: text})
        row.set(lang, text)
        return row

    def add_row(self, key: str, texts: Mapping[Lang, str] | None = None, *,
                index: int | None = None, allow_duplicate: bool = False) -> LocRow:
        """Crea ``key;<13 idiomas>;x``. ``texts`` admite códigos, nombres o columnas."""
        check_key(key)
        if not allow_duplicate and key in self._key_index():
            raise KeyError(f"la clave {key!r} ya existe en el archivo")
        fields = [""] * LANGUAGE_COUNT + [END_MARKER]
        for lang, text in (texts or {}).items():
            check_text(text)
            fields[language_column(lang) - 1] = text
        row = LocRow(RowKind.DATA, key, fields, modified=True)
        if index is None:
            self.rows.append(row)
        else:
            self.rows.insert(index, row)
        self._structure_changed = True
        self._index = None
        return row

    def remove_row(self, key: str) -> int:
        """Elimina todas las filas con esa clave y devuelve cuántas había."""
        kept = [row for row in self.rows if not (row.kind is RowKind.DATA and row.key == key)]
        removed = len(self.rows) - len(kept)
        if removed:
            self.rows[:] = kept
            self._structure_changed = True
            self._index = None
        return removed

    def mark_saved(self) -> None:
        """Toma el estado actual como el guardado en disco (líneas renumeradas)."""
        for number, row in enumerate(self.rows, 1):
            row.line = number
            row.raw = row.to_line()
            row.modified = False
        self._structure_changed = False

    # --- serialización y validación -------------------------------------

    def to_source(self) -> str:
        parts = []
        for row in self.rows:
            parts.append(row.to_line())
            parts.append(row.newline if row.newline is not None else self.newline)
        if parts and not self.trailing_newline:
            parts.pop()
        return "".join(parts)

    def lint(self, encoding: str = GAME_ENCODING) -> list:
        """Diagnósticos del estado actual; las líneas son posiciones actuales (1-based)."""
        from .lint import lint_file

        return lint_file(self, encoding)

    def __repr__(self) -> str:
        return f"LocalisationFile(path={self.path!s}, rows={len(self.rows)}, encoding={self.encoding})"
