"""Diagnósticos del parser Clausewitz, con mensajes en español e inglés.

Las posiciones son 1-based y se cuentan en caracteres; solo ``\\n`` cuenta como
salto de línea (igual que ``encoding.find_unencodable``).
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
    },
}

DEFAULT_LANG = "en"


class _MissingArgs(dict):
    def __missing__(self, name):
        return "?"


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
        table = MESSAGES.get(lang, MESSAGES[DEFAULT_LANG])
        template = None
        if "key" in self.args and self.args["key"] is None:
            template = table.get(self.code + "_anonymous")
        if template is None:
            template = table.get(self.code)
        if template is None:
            return f"{self.code} {self.args}" if self.args else self.code
        return template.format_map(_MissingArgs(self.args))

    def format(self, path=None, lang: str = DEFAULT_LANG) -> str:
        """``archivo:línea:columna: severidad: mensaje`` (sin archivo si ``path`` es None)."""
        labels = SEVERITY_LABELS.get(lang, SEVERITY_LABELS[DEFAULT_LANG])
        location = f"{self.line}:{self.column}"
        if path is not None:
            location = f"{path}:{location}"
        return f"{location}: {labels[self.severity]}: {self.message(lang)}"

    def __str__(self) -> str:
        return self.format()
