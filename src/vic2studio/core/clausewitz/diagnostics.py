"""Diagnósticos del parser Clausewitz, con mensajes en español e inglés.

Las posiciones son 1-based y se cuentan en caracteres. ``\\r\\n``, ``\\n`` y un
``\\r`` suelto cuentan como salto de línea, igual que en los editores de texto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


SEVERITY_LABELS = {
    "es": {Severity.ERROR: "error", Severity.WARNING: "aviso", Severity.INFO: "info"},
    "en": {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "info"},
}

# Plantillas para str.format; la variante "_anonymous" se usa cuando args["key"] es None.
MESSAGES = {
    "es": {
        "unclosed_block": "El bloque '{key}' abierto en la línea {open_line} no se cierra (falta '}}')",
        "unclosed_block_anonymous": "El bloque abierto en la línea {open_line} no se cierra (falta '}}')",
        "unexpected_close_brace": "Llave de cierre '}}' sobrante: no hay ningún bloque abierto",
        "missing_value": "Falta el valor de '{key}' después de '{op}'",
        "missing_key": "El operador '{op}' no tiene clave",
        "unterminated_string": "Cadena sin cerrar: falta la comilla de cierre",
        "invalid_key": "Un bloque no puede usarse como clave (delante de '{op}')",
        "unexpected_operator": "Operador '{op}' inesperado: se esperaba el valor de '{key}'",
        "invalid_character": "Carácter no válido '{char}'",
        "multiline_string": "La cadena continúa hasta la línea {end_line}; ¿falta una comilla de cierre?",
        "control_character": (
            "El archivo contiene {count} carácter(es) de control invisible(s); el primero es U+{codepoint}"
        ),
        "non_game_encoding": (
            "El archivo está en {encoding}; Victoria II lo lee como Windows-1252 "
            "y mostrará mal los caracteres no ASCII"
        ),
        "suspicious_close_brace": (
            "Esta '}}' cierra '{key}' (línea {open_line}) pero tiene menos sangría que esa línea: "
            "puede que falte una '}}' antes"
        ),
        "suspicious_close_brace_anonymous": (
            "Esta '}}' cierra el bloque de la línea {open_line} pero tiene menos sangría que esa línea: "
            "puede que falte una '}}' antes"
        ),
        "invisible_character": (
            "La palabra '{word}' contiene un carácter invisible (U+{codepoint}): "
            "no coincidirá con la palabra que aparenta"
        ),
    },
    "en": {
        "unclosed_block": "Block '{key}' opened on line {open_line} is never closed (missing '}}')",
        "unclosed_block_anonymous": "Block opened on line {open_line} is never closed (missing '}}')",
        "unexpected_close_brace": "Stray closing brace '}}': there is no open block",
        "missing_value": "Missing value for '{key}' after '{op}'",
        "missing_key": "Operator '{op}' has no key",
        "unterminated_string": "Unterminated string: missing closing quote",
        "invalid_key": "A block cannot be used as a key (before '{op}')",
        "unexpected_operator": "Unexpected operator '{op}': expected the value of '{key}'",
        "invalid_character": "Invalid character '{char}'",
        "multiline_string": "The string continues up to line {end_line}; is a closing quote missing?",
        "control_character": "The file contains {count} invisible control character(s); the first one is U+{codepoint}",
        "non_game_encoding": (
            "The file is encoded as {encoding}; Victoria II reads it as Windows-1252 "
            "and will garble non-ASCII characters"
        ),
        "suspicious_close_brace": (
            "This '}}' closes '{key}' (line {open_line}) but is less indented than that line: "
            "a '}}' may be missing before it"
        ),
        "suspicious_close_brace_anonymous": (
            "This '}}' closes the block from line {open_line} but is less indented than that line: "
            "a '}}' may be missing before it"
        ),
        "invisible_character": (
            "The word '{word}' contains an invisible character (U+{codepoint}): "
            "it will not match the word it looks like"
        ),
    },
}

# Errores de la API de edición y de from_json (``EditError``). Con el parámetro "where"
# (ruta del elemento JSON o archivo) el mensaje empieza por "where: ".
EDIT_MESSAGES = {
    "es": {
        "date_part_type": "El año, el mes y el día de una fecha deben ser enteros, no {type}",
        "date_month_range": "Mes fuera de rango: {month}",
        "date_day_range": "Día fuera de rango para el mes {month}: {day}",
        "not_a_date": "'{text}' no es una fecha año.mes.día",
        "not_an_integer": "'{text}' no es un entero",
        "not_a_number": "'{text}' no es un número",
        "not_a_bool": "'{text}' no es yes/no",
        "not_finite": "{value} no es un número finito: Clausewitz no puede escribirlo",
        "text_type": "El texto debe ser una cadena, no {type}",
        "quote_in_string": "Un texto no puede contener comillas dobles: Clausewitz no tiene secuencias de escape",
        "needs_quotes": "'{text}' no puede escribirse sin comillas: tiene espacios, símbolos o caracteres invisibles",
        "line_break": "'{text}' contiene un salto de línea: el juego espera una sola línea",
        "control_character": "'{text}' contiene un carácter de control invisible (U+{codepoint})",
        "invisible_character": "La clave '{text}' contiene un carácter invisible (U+{codepoint})",
        "empty_key": "La clave no puede estar vacía",
        "unencodable_character": "'{char}' (U+{codepoint}) no se puede guardar en {encoding}",
        "invalid_key_type": "Una clave debe ser texto, un entero o una fecha, no {type}",
        "unsupported_value": "Tipo de valor no admitido: {type}",
        "dict_none_key": "Las claves de un dict no pueden ser None",
        "pair_shape": "Cada par debe ser (clave, valor) o (clave, operador, valor), no {value}",
        "invalid_operator": "Operador no válido '{op}'; se admiten {allowed}",
        "entry_without_value": "Una entrada necesita un valor",
        "loose_value_operator": "Un valor suelto no tiene operador: asigna antes una clave",
        "not_an_entry": "Se esperaba una entrada (Entry), no {type}",
        "entry_not_in_block": "La entrada no pertenece a este bloque",
        "cycle": "Un bloque no puede contenerse a sí mismo",
        "not_a_node": "No es un nodo Clausewitz: {type}",
        "not_a_document": "Se esperaba un Document o un ParseResult, no {type}",
        "invalid_path_item": "Elemento de ruta no válido: {item}",
        "source_mismatch": (
            "El texto generado no se vuelve a leer igual que el documento editado (primera diferencia en "
            "'{entry}', línea {line} del texto generado); no se ha escrito el archivo"
        ),
        "json_expected_block": "se esperaba un bloque {{'type': 'block', 'entries': [...]}}",
        "json_expected_list": "se esperaba una lista",
        "json_expected_object": "se esperaba un objeto",
        "json_expected_scalar": "se esperaba un escalar {{'type': 'scalar', ...}}",
        "json_missing_type": "falta 'type' ('block' o 'scalar')",
        "json_unknown_type": "'type' debe ser 'block' o 'scalar', no {type}",
        "json_scalar_fields": "'text' debe ser una cadena y 'quoted' un booleano",
        "json_key_op": "'key' y 'op' deben ser ambos null o ambos no nulos",
        "json_expected_strings": "se esperaba una lista de cadenas",
        "json_expected_string": "se esperaba una cadena",
    },
    "en": {
        "date_part_type": "The year, month and day of a date must be integers, not {type}",
        "date_month_range": "Month out of range: {month}",
        "date_day_range": "Day out of range for month {month}: {day}",
        "not_a_date": "'{text}' is not a year.month.day date",
        "not_an_integer": "'{text}' is not an integer",
        "not_a_number": "'{text}' is not a number",
        "not_a_bool": "'{text}' is not yes/no",
        "not_finite": "{value} is not a finite number: Clausewitz cannot write it",
        "text_type": "The text must be a string, not {type}",
        "quote_in_string": "A text cannot contain double quotes: Clausewitz has no escape sequences",
        "needs_quotes": "'{text}' cannot be written without quotes: it has spaces, symbols or invisible characters",
        "line_break": "'{text}' contains a line break: the game expects a single line",
        "control_character": "'{text}' contains an invisible control character (U+{codepoint})",
        "invisible_character": "The key '{text}' contains an invisible character (U+{codepoint})",
        "empty_key": "The key cannot be empty",
        "unencodable_character": "'{char}' (U+{codepoint}) cannot be saved as {encoding}",
        "invalid_key_type": "A key must be text, an integer or a date, not {type}",
        "unsupported_value": "Unsupported value type: {type}",
        "dict_none_key": "Dict keys cannot be None",
        "pair_shape": "Each pair must be (key, value) or (key, operator, value), not {value}",
        "invalid_operator": "Invalid operator '{op}'; allowed: {allowed}",
        "entry_without_value": "An entry needs a value",
        "loose_value_operator": "A loose value has no operator: assign a key first",
        "not_an_entry": "Expected an entry (Entry), not {type}",
        "entry_not_in_block": "The entry does not belong to this block",
        "cycle": "A block cannot contain itself",
        "not_a_node": "Not a Clausewitz node: {type}",
        "not_a_document": "Expected a Document or a ParseResult, not {type}",
        "invalid_path_item": "Invalid path item: {item}",
        "source_mismatch": (
            "The generated text does not read back as the edited document (first difference at "
            "'{entry}', line {line} of the generated text); the file was not written"
        ),
        "json_expected_block": "expected a block {{'type': 'block', 'entries': [...]}}",
        "json_expected_list": "expected a list",
        "json_expected_object": "expected an object",
        "json_expected_scalar": "expected a scalar {{'type': 'scalar', ...}}",
        "json_missing_type": "missing 'type' ('block' or 'scalar')",
        "json_unknown_type": "'type' must be 'block' or 'scalar', not {type}",
        "json_scalar_fields": "'text' must be a string and 'quoted' a boolean",
        "json_key_op": "'key' and 'op' must be both null or both non-null",
        "json_expected_strings": "expected a list of strings",
        "json_expected_string": "expected a string",
    },
}

DEFAULT_LANG = "en"
_SHOWN_LIMIT = 60  # caracteres de un argumento de texto en un mensaje


class _MissingArgs(dict):
    def __missing__(self, name):
        return "?"


def _escaped(text: str) -> str:
    """Texto apto para un mensaje de una línea: saltos de línea y caracteres invisibles escapados."""
    if text.isprintable():
        return text
    return "".join(char if char.isprintable() else repr(char)[1:-1] for char in text)


def _shown(value):
    """Argumento de texto de un mensaje: escapado (ver ``_escaped``) y recortado."""
    if not isinstance(value, str):
        return value
    value = _escaped(value)
    if len(value) > _SHOWN_LIMIT:
        value = value[: _SHOWN_LIMIT - 1] + "…"
    return value


def _render(table: dict, code: str, args: dict) -> str | None:
    template = None
    if "key" in args and args["key"] is None:
        template = table.get(code + "_anonymous")
    if template is None:
        template = table.get(code)
    if template is None:
        return None
    return template.format_map(_MissingArgs({name: _shown(value) for name, value in args.items()}))


@dataclass
class Diagnostic:
    code: str
    severity: Severity
    line: int
    column: int
    offset: int
    args: dict = field(default_factory=dict)
    # Posiciones (línea, columna) relacionadas, p. ej. el final del archivo para un bloque sin cerrar.
    related: list = field(default_factory=list)

    def message(self, lang: str = DEFAULT_LANG) -> str:
        """Mensaje en una línea; los textos de ``args`` se muestran escapados y recortados."""
        text = _render(MESSAGES.get(lang, MESSAGES[DEFAULT_LANG]), self.code, self.args)
        if text is None:
            return f"{self.code} {self.args}" if self.args else self.code
        return text

    def format(self, path=None, lang: str = DEFAULT_LANG) -> str:
        """``archivo:línea:columna: severidad: mensaje`` (sin archivo si ``path`` es None)."""
        labels = SEVERITY_LABELS.get(lang, SEVERITY_LABELS[DEFAULT_LANG])
        location = f"{self.line}:{self.column}"
        if path is not None:
            location = f"{path}:{location}"
        return f"{location}: {labels[self.severity]}: {self.message(lang)}"

    def __str__(self) -> str:
        return self.format()


class EditError(ValueError):
    """Error de la API de edición o de ``from_json``, con código y mensaje en español o inglés.

    ``code`` identifica el error (ver ``EDIT_MESSAGES``) y ``params`` lleva sus datos;
    ``message(lang)`` da el texto en español o inglés para la interfaz y ``str()``, en
    español (como los demás errores del núcleo).
    """

    def __init__(self, code: str, params: dict | None = None):
        self.code = code
        self.params = dict(params or {})
        super().__init__(self.message("es"))

    def message(self, lang: str = DEFAULT_LANG) -> str:
        """Mensaje en una línea; "where" (archivo o ruta JSON) va entero, porque lo que localiza está al final."""
        params = dict(self.params)
        where = params.pop("where", None)
        text = _render(EDIT_MESSAGES.get(lang, EDIT_MESSAGES[DEFAULT_LANG]), self.code, params)
        if text is None:
            text = f"{self.code} {params}" if params else self.code
        return text if where is None else f"{_escaped(str(where))}: {text}"

    def __str__(self) -> str:
        return self.message("es")


class EditTypeError(EditError, TypeError):
    """``EditError`` por un tipo de dato no admitido (también es ``TypeError``)."""
