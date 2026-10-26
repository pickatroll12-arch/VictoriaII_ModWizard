"""Diagnósticos del módulo de localización y sus mensajes en español e inglés.

``Severity`` es propio de este módulo para no depender del orden de
construcción; tiene los mismos miembros que el de ``core.clausewitz`` y al
integrar puede sustituirse por un alias de aquel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .model import LANGUAGE_COLUMNS


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


MISSING_END_MARKER = "missing_end_marker"
TOO_FEW_COLUMNS = "too_few_columns"
DUPLICATE_KEY = "duplicate_key"
EMPTY_KEY = "empty_key"
KEY_WHITESPACE = "key_whitespace"
SEMICOLON_IN_QUOTES = "semicolon_in_quotes"
UNENCODABLE_CHARACTER = "unencodable_character"
NON_GAME_ENCODING = "non_game_encoding"
HEADER_ROW = "header_row"

SEVERITIES = {
    MISSING_END_MARKER: Severity.WARNING,
    TOO_FEW_COLUMNS: Severity.WARNING,
    DUPLICATE_KEY: Severity.WARNING,
    EMPTY_KEY: Severity.WARNING,
    KEY_WHITESPACE: Severity.WARNING,
    SEMICOLON_IN_QUOTES: Severity.WARNING,
    UNENCODABLE_CHARACTER: Severity.ERROR,
    NON_GAME_ENCODING: Severity.WARNING,
    HEADER_ROW: Severity.INFO,
}
CODES = tuple(SEVERITIES)

SEVERITY_LABELS = {
    "en": {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "info"},
    "es": {Severity.ERROR: "error", Severity.WARNING: "aviso", Severity.INFO: "info"},
}

_LANGUAGE_NAMES = {
    "en": LANGUAGE_COLUMNS,
    "es": ["inglés", "francés", "alemán", "polaco", "español", "italiano", "sueco",
           "checo", "húngaro", "neerlandés", "portugués", "ruso", "finés"],
}
_KEY_COLUMN = {"en": "key", "es": "clave"}
_OTHER_COLUMN = {"en": "column {0}", "es": "columna {0}"}

# Variantes: "<código>.<variante>"; ``CsvDiagnostic.message`` elige la variante.
MESSAGES = {
    "en": {
        MISSING_END_MARKER: "Row '{key}' has no end marker 'x' in column 14.",
        MISSING_END_MARKER + ".misplaced": (
            "Row '{key}' has the end marker 'x' in column {found_column} instead of 14: "
            "columns are missing, or a text contains an extra ';' that shifts the following ones."
        ),
        TOO_FEW_COLUMNS: "Row '{key}' has only {count} of the {expected} language columns.",
        DUPLICATE_KEY: (
            "Key '{key}' is already defined on line {first_line}; "
            "the game uses the first definition and ignores this one."
        ),
        EMPTY_KEY: "Row without a key: no text can refer to it.",
        KEY_WHITESPACE: "Key '{key}' has spaces at the start or the end; references to it will not match.",
        SEMICOLON_IN_QUOTES: (
            "The {column_name} text of row '{key}' has a ';' inside quotes. The game does not "
            "understand quotes: the ';' splits the text and shifts every following column."
        ),
        UNENCODABLE_CHARACTER: (
            "This line has {count} character(s) that cannot be saved in {encoding}; "
            "the first is '{char}' (U+{codepoint})."
        ),
        NON_GAME_ENCODING: (
            "The file is encoded as {encoding}, but Victoria II reads localisation as {expected}: "
            "accented letters will look garbled in the game."
        ),
        NON_GAME_ENCODING + ".bom": (
            "The file is encoded as {encoding} with a BOM, but Victoria II reads localisation as "
            "{expected}: the first key gets invisible bytes and accented letters will look garbled."
        ),
        HEADER_ROW: "Header row: the game loads it as an ordinary entry with key '{key}'. It is harmless.",
    },
    "es": {
        MISSING_END_MARKER: "La fila '{key}' no tiene el marcador de fin 'x' en la columna 14.",
        MISSING_END_MARKER + ".misplaced": (
            "La fila '{key}' tiene el marcador de fin 'x' en la columna {found_column} en vez de la 14: "
            "faltan columnas o algún texto tiene un ';' de más que desplaza las siguientes."
        ),
        TOO_FEW_COLUMNS: "La fila '{key}' solo tiene {count} de las {expected} columnas de idioma.",
        DUPLICATE_KEY: (
            "La clave '{key}' ya está definida en la línea {first_line}; "
            "el juego usa la primera definición e ignora esta."
        ),
        EMPTY_KEY: "Fila sin clave: ningún texto puede hacer referencia a ella.",
        KEY_WHITESPACE: "La clave '{key}' tiene espacios al principio o al final; las referencias a ella no coincidirán.",
        SEMICOLON_IN_QUOTES: (
            "El texto en {column_name} de la fila '{key}' tiene un ';' entre comillas. El juego no "
            "entiende las comillas: el ';' parte el texto y desplaza todas las columnas siguientes."
        ),
        UNENCODABLE_CHARACTER: (
            "Esta línea tiene {count} carácter(es) que no se pueden guardar en {encoding}; "
            "el primero es '{char}' (U+{codepoint})."
        ),
        NON_GAME_ENCODING: (
            "El archivo está codificado en {encoding}, pero Victoria II lee la localización en "
            "{expected}: las letras acentuadas se verán mal en el juego."
        ),
        NON_GAME_ENCODING + ".bom": (
            "El archivo está codificado en {encoding} con BOM, pero Victoria II lee la localización en "
            "{expected}: la primera clave recibe bytes invisibles y las letras acentuadas se verán mal."
        ),
        HEADER_ROW: "Fila de cabecera: el juego la carga como una entrada normal con la clave '{key}'. Es inofensiva.",
    },
}

DEFAULT_LANG = "en"


def column_name(index: int, lang: str = DEFAULT_LANG) -> str:
    """Nombre legible de la columna ``index`` (0 = clave) en el idioma de la interfaz."""
    lang = lang if lang in _LANGUAGE_NAMES else DEFAULT_LANG
    if index == 0:
        return _KEY_COLUMN[lang]
    if 1 <= index <= len(LANGUAGE_COLUMNS):
        return _LANGUAGE_NAMES[lang][index - 1]
    return _OTHER_COLUMN[lang].format(index)


@dataclass(frozen=True)
class CsvDiagnostic:
    """Un problema detectado. ``line`` y ``column`` son 1-based (``column`` en caracteres)."""

    code: str
    severity: Severity
    line: int | None = None
    column: int | None = None
    args: dict[str, Any] = field(default_factory=dict)
    path: str | None = None

    def __hash__(self) -> int:
        # ``args`` es un dict: el hash generado por dataclass fallaría.
        return hash((self.code, self.line, self.column, self.path))

    def _variant(self) -> str:
        if self.code == MISSING_END_MARKER and self.args.get("found_column"):
            return MISSING_END_MARKER + ".misplaced"
        if self.code == NON_GAME_ENCODING and self.args.get("bom"):
            return NON_GAME_ENCODING + ".bom"
        return self.code

    def message(self, lang: str = DEFAULT_LANG) -> str:
        table = MESSAGES.get(lang, MESSAGES[DEFAULT_LANG])
        template = table.get(self._variant()) or table.get(self.code)
        if template is None:
            return self.code
        values = dict(self.args)
        if "field" in values:
            values.setdefault("column_name", column_name(values["field"], lang))
        try:
            return template.format(**values)
        except (KeyError, IndexError, ValueError):
            return f"{template} {self.args}"

    def format(self, lang: str = DEFAULT_LANG) -> str:
        """``ruta:línea:columna: severidad: mensaje [código]`` para la CLI y los registros."""
        location = ":".join(str(part) for part in (self.path, self.line, self.column) if part is not None)
        label = SEVERITY_LABELS.get(lang, SEVERITY_LABELS[DEFAULT_LANG])[self.severity]
        prefix = f"{location}: " if location else ""
        return f"{prefix}{label}: {self.message(lang)} [{self.code}]"

    def __str__(self) -> str:
        return self.format()


def make(code: str, line: int | None = None, column: int | None = None,
         path: str | None = None, **args: Any) -> CsvDiagnostic:
    return CsvDiagnostic(code, SEVERITIES[code], line, column, args, path)
