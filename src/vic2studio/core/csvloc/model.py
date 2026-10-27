"""Modelo en memoria de un archivo de localización CSV de Victoria II.

Cada línea del archivo es una ``LocRow``. Las filas de datos guardan la clave y
los campos crudos tal cual (``line.split(";")``), de modo que unirlos con ";"
reproduce exactamente la línea original. Solo al editar una fila con ``set``
se normaliza su estructura a ``clave;13 idiomas;x;extras``.

Los errores de edición (``InvalidFieldError``) llevan ``code`` y ``params`` para
mostrarlos traducidos con ``message(lang)``; ``str()`` da el texto en español.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Union

from ..encoding import BOM, GAME_ENCODING

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
# Columna del último idioma que muestra el juego (Spanish): una fila con al menos
# tantos campos de idioma se ve entera en el juego aunque le falten columnas.
LAST_DISPLAYED_COLUMN = max(_LANGUAGE_BY_NAME[name.lower()] for name in DISPLAYED_LANGUAGES)

Lang = Union[str, int]

LOCALISATION_FOLDER = "localisation"
CSV_SUFFIX = ".csv"

# Códigos de ``InvalidFieldError`` (mensajes en ``diagnostics.EDIT_MESSAGES``).
SEPARATOR_IN_TEXT = "separator_in_text"
NEWLINE_IN_TEXT = "newline_in_text"
EMPTY_KEY = "empty_key"
KEY_WHITESPACE = "key_whitespace"
COMMENT_KEY = "comment_key"
DUPLICATE_KEY = "duplicate_key"
UNKNOWN_LANGUAGE = "unknown_language"
INVALID_COLUMN = "invalid_column"
NOT_A_LANGUAGE_COLUMN = "not_a_language_column"
NOT_A_DATA_ROW = "not_a_data_row"
INVALID_COMMENT = "invalid_comment"
INVALID_BLANK = "invalid_blank"


class RowKind(Enum):
    DATA = "data"
    COMMENT = "comment"
    BLANK = "blank"


class InvalidFieldError(ValueError):
    """Un texto, clave, columna o fila que no se puede representar o editar en el CSV.

    ``code`` identifica el problema y ``params`` sus datos (``args`` es el de
    cualquier excepción); ``message(lang)`` da el texto en español o inglés.
    """

    def __init__(self, code: str, **params: Any):
        self.code = code
        self.params = params
        super().__init__(self.message("es"))

    def message(self, lang: str = "en") -> str:
        from .diagnostics import edit_message

        return edit_message(self.code, lang, self.params)

    def __str__(self) -> str:
        return self.message("es")


class DuplicateKeyError(InvalidFieldError, KeyError):
    """La clave ya existe en el archivo (es también un ``KeyError``)."""

    def __init__(self, key: str):
        super().__init__(DUPLICATE_KEY, key=key)

    def __reduce__(self):
        return (type(self), (self.params["key"],))


def column_index(lang: Lang) -> int:
    """Columna de ``lang``: código ("es"), nombre ("Spanish") o índice de columna (int)."""
    if isinstance(lang, bool):
        raise TypeError("idioma no válido: bool")
    if isinstance(lang, int):
        if lang < 0:
            raise InvalidFieldError(INVALID_COLUMN, column=lang)
        return lang
    if isinstance(lang, str):
        lowered = lang.strip().lower()
        index = LANGUAGE_CODES.get(lowered) or _LANGUAGE_BY_NAME.get(lowered)
        if index is not None:
            return index
        raise InvalidFieldError(UNKNOWN_LANGUAGE, lang=lang)
    raise TypeError(f"idioma no válido: {lang!r}")


def language_column(lang: Lang) -> int:
    """Como ``column_index`` pero exige una columna de idioma (1..13)."""
    index = column_index(lang)
    if not 1 <= index <= LANGUAGE_COUNT:
        raise InvalidFieldError(NOT_A_LANGUAGE_COLUMN, column=index, last=LANGUAGE_COUNT)
    return index


def is_localisation_csv(path: str | os.PathLike) -> bool:
    """True si el juego cargaría ``path`` como localización: un ``.csv`` directamente en una carpeta
    ``localisation`` (sin distinguir mayúsculas). ``map/definition.csv`` y ``map/adjacencies.csv`` no lo son."""
    path = Path(path)
    return path.suffix.lower() == CSV_SUFFIX and path.parent.name.casefold() == LOCALISATION_FOLDER


def is_end_marker(field: str) -> bool:
    # El corpus vanilla también usa "X", "x " y "x" seguido de tabuladores.
    return field.strip().lower() == END_MARKER


def marker_index(fields: list[str]) -> int | None:
    """Posición en ``fields`` del marcador de fin, o ``None``.

    Prioriza la columna 14; si no, toma la última "x" tras la que solo quedan
    campos vacíos (filas con columnas de menos o de más). Antes de la columna
    14 solo cuenta una "x" minúscula detrás de los idiomas que muestra el juego
    (columnas 6 a 13, como en ``darkness_3_01.csv``): una "X" en English o en
    Spanish es texto (un numeral romano), no el marcador.
    """
    if len(fields) > LANGUAGE_COUNT and is_end_marker(fields[LANGUAGE_COUNT]):
        return LANGUAGE_COUNT
    for index in range(len(fields) - 1, -1, -1):
        field = fields[index]
        if not field.strip():
            continue
        if index > LANGUAGE_COUNT:
            return index if is_end_marker(field) else None
        if index >= LAST_DISPLAYED_COLUMN and field.strip() == END_MARKER:  # campo i = columna i + 1
            return index
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


def _check_line_text(text: str) -> None:
    if not isinstance(text, str):
        raise TypeError(f"el texto debe ser str, no {type(text).__name__}")
    if "\n" in text or "\r" in text:
        raise InvalidFieldError(NEWLINE_IN_TEXT)


def check_text(text: str) -> None:
    """Lanza ``InvalidFieldError`` si ``text`` no cabe en un campo del CSV."""
    _check_line_text(text)
    if SEPARATOR in text:
        raise InvalidFieldError(SEPARATOR_IN_TEXT)


def check_key(key: str) -> None:
    check_text(key)
    if not key:
        raise InvalidFieldError(EMPTY_KEY)
    if key != key.strip():
        raise InvalidFieldError(KEY_WHITESPACE, key=key)
    if key.startswith(COMMENT_PREFIX):
        raise InvalidFieldError(COMMENT_KEY, key=key)


def check_comment(text: str) -> None:
    """Un comentario es una sola línea que empieza por "#" (puede llevar ";")."""
    _check_line_text(text)
    if not text.startswith(COMMENT_PREFIX):
        raise InvalidFieldError(INVALID_COMMENT, text=text)


def check_blank(text: str) -> None:
    """Una línea vacía solo admite espacios y tabuladores."""
    _check_line_text(text)
    if text.strip():
        raise InvalidFieldError(INVALID_BLANK, text=text)


class LocRow:
    """Una línea del archivo.

    En filas de datos ``fields`` son todas las columnas tras la clave, incluida
    la "x" y los campos extra. En comentarios y líneas vacías ``key`` es "",
    ``fields`` está vacío y ``raw`` es el contenido de la línea. ``line`` es la
    línea (1-based) en el archivo leído, o ``None`` en filas nuevas. ``newline``
    solo se usa si el salto de esta línea difiere del del archivo.

    Para cambiar la clave de una fila de un archivo usa
    ``LocalisationFile.rename_key``: asignar ``key`` directamente deja obsoleto
    el índice de claves del archivo.
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
        """Comentario nuevo; ``text`` empieza por "#" (ver ``check_comment``)."""
        check_comment(text)
        return cls(RowKind.COMMENT, raw=text, modified=True)

    @classmethod
    def blank(cls, text: str = "") -> LocRow:
        """Línea vacía nueva; ``text`` solo puede tener espacios (ver ``check_blank``)."""
        check_blank(text)
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
            raise InvalidFieldError(NOT_A_DATA_ROW)
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


def _new_data_row(key: str, texts: Mapping[Lang, str] | None) -> LocRow:
    check_key(key)
    fields = [""] * LANGUAGE_COUNT + [END_MARKER]
    for lang, text in (texts or {}).items():
        check_text(text)
        fields[language_column(lang) - 1] = text
    return LocRow(RowKind.DATA, key, fields, modified=True)


class LocalisationFile:
    """Archivo de localización completo, editable y serializable sin pérdidas.

    ``stamp`` es la huella del archivo en disco al leerlo o guardarlo
    (``core.fileio.FileStamp``): ``write_csv_file`` no sobrescribe un archivo
    que ha cambiado fuera de la aplicación desde entonces.

    ``extra_boms`` cuenta los BOM repetidos tras el de ``encoding``
    (``encoding.split_extra_boms``): no forman parte de la primera clave,
    ``to_source`` los pone delante y ``write_csv_file`` los descarta al guardar
    en otra codificación.
    """

    def __init__(self, rows: list[LocRow] | None = None, *, encoding: str = GAME_ENCODING,
                 newline: str = DEFAULT_NEWLINE, trailing_newline: bool = True,
                 path: str | os.PathLike | None = None, extra_boms: int = 0):
        self.rows: list[LocRow] = rows if rows is not None else []
        self.encoding = encoding
        self.extra_boms = extra_boms
        self.newline = newline
        self.trailing_newline = trailing_newline
        self.path = Path(path) if path is not None else None
        self.stamp = None
        self.diagnostics: list = []
        self._structure_changed = False
        self._index: dict[str, LocRow] | None = None
        self._index_size = -1

    # --- consulta -------------------------------------------------------

    def _key_index(self) -> dict[str, LocRow]:
        # Se reconstruye si cambia el número de filas; los métodos de edición de
        # esta clase lo mantienen al día o lo invalidan explícitamente.
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

    def _insert(self, rows: list[LocRow], index: int | None) -> None:
        keys = self._key_index()
        data = [row for row in rows if row.kind is RowKind.DATA]
        if index is None or index >= len(self.rows):
            # Al final (el caso de las altas masivas) el índice se mantiene sin reconstruirlo.
            self.rows.extend(rows)
            for row in data:
                keys.setdefault(row.key, row)
            self._index_size = len(self.rows)
        else:
            self.rows[index:index] = rows
            if data:
                # Una fila de datos en medio cambia el orden de primera aparición (``keys``)
                # y puede pasar a ser la primera de una clave repetida.
                self._index = None
            else:
                self._index_size = len(self.rows)
        self._structure_changed = True

    def add_row(self, key: str, texts: Mapping[Lang, str] | None = None, *,
                index: int | None = None, allow_duplicate: bool = False) -> LocRow:
        """Crea ``key;<13 idiomas>;x``. ``texts`` admite códigos, nombres o columnas.

        Lanza ``DuplicateKeyError`` (un ``KeyError``) si la clave ya existe, salvo
        con ``allow_duplicate``.
        """
        return self.add_rows([(key, texts)], index=index, allow_duplicate=allow_duplicate)[0]

    def add_rows(self, items: Iterable[tuple[str, Mapping[Lang, str] | None]], *,
                 index: int | None = None, allow_duplicate: bool = False) -> list[LocRow]:
        """Como ``add_row`` para varias claves de una vez: se validan todas antes de añadir ninguna."""
        rows = [_new_data_row(key, texts) for key, texts in items]
        if not allow_duplicate:
            keys, seen = self._key_index(), set()
            for row in rows:
                if row.key in keys or row.key in seen:
                    raise DuplicateKeyError(row.key)
                seen.add(row.key)
        self._insert(rows, index)
        return rows

    def add_comment(self, text: str, *, index: int | None = None) -> LocRow:
        """Añade un comentario (``text`` empieza por "#"), al final o en la posición ``index``."""
        row = LocRow.comment(text)
        self._insert([row], index)
        return row

    def add_blank(self, text: str = "", *, index: int | None = None) -> LocRow:
        """Añade una línea vacía, al final o en la posición ``index``."""
        row = LocRow.blank(text)
        self._insert([row], index)
        return row

    def rename_key(self, old: str, new: str, *, all: bool = False, allow_duplicate: bool = False) -> int:
        """Cambia la clave de la primera fila con ``old`` (de todas con ``all``) conservando sus textos.

        Devuelve cuántas filas cambió. Lanza ``DuplicateKeyError`` si ``new`` ya
        existe, salvo con ``allow_duplicate``.
        """
        check_key(new)
        first = self.get_row(old)
        if first is None or new == old:
            return 0
        if not allow_duplicate and new in self._key_index():
            raise DuplicateKeyError(new)
        targets = [row for row in self.rows if row.kind is RowKind.DATA and row.key == old] if all else [first]
        for row in targets:
            row.key = new
            row.modified = True
        self._index = None
        return len(targets)

    def remove_row(self, key: str) -> int:
        """Elimina todas las filas con esa clave y devuelve cuántas había."""
        return self.remove_rows([row for row in self.rows if row.kind is RowKind.DATA and row.key == key])

    def remove_rows(self, rows: Iterable[LocRow]) -> int:
        """Elimina esas filas (por identidad, p. ej. un solo duplicado) y devuelve cuántas quitó."""
        doomed = {id(row) for row in rows}
        kept = [row for row in self.rows if id(row) not in doomed]
        removed = len(self.rows) - len(kept)
        if removed:
            self.rows[:] = kept
            self._structure_changed = True
            self._index = None
        return removed

    def remove(self, row: LocRow) -> None:
        """Elimina una fila concreta; ``ValueError`` si no es de este archivo."""
        if not self.remove_rows([row]):
            raise ValueError(f"la fila {row!r} no es de este archivo")

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
        return BOM * self.extra_boms + "".join(parts)

    def lint(self, encoding: str = GAME_ENCODING, *, cancelled=None) -> list:
        """Diagnósticos del estado actual; las líneas son posiciones actuales (1-based).

        Con ``cancelled`` lanza ``core.cancel.Cancelled`` si pide parar.
        """
        from .lint import lint_file

        return lint_file(self, encoding, cancelled=cancelled)

    def __repr__(self) -> str:
        return f"LocalisationFile(path={self.path!s}, rows={len(self.rows)}, encoding={self.encoding})"
