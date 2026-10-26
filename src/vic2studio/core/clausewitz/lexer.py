"""Analizador léxico del formato Clausewitz.

Cada token guarda su *trivia* previa: espacios, saltos de línea, comentarios y,
en documentos con errores, el texto de los tokens que el parser descarta. La
concatenación de ``trivia + raw`` de todos los tokens (el último es ``EOF``, que
solo lleva la trivia final) reproduce el texto original exacto.

Reglas léxicas:

- espacio: cualquier carácter de control ASCII (``\\x00``-``\\x20``, ``\\x7f``) y U+FEFF;
- comentario: ``#`` hasta el final de la línea (fuera de comillas);
- cadena: ``"..."`` sin secuencias de escape, puede abarcar varias líneas; sin
  comilla de cierre llega hasta el final del texto (``OPEN_STRING``);
- operadores: ``=  <  >  <=  >=  !=  ==``;
- palabra: cualquier secuencia sin espacios ni ``{ } = < > ! # "`` (fechas,
  negativos, rutas, letras acentuadas...);
- un ``!`` que no forma ``!=`` es un carácter no válido (``INVALID``).
"""

from __future__ import annotations

import re

WORD, STRING, OPEN_STRING, LBRACE, RBRACE, OP, INVALID, EOF = range(8)
KIND_NAMES = ("word", "string", "open_string", "lbrace", "rbrace", "op", "invalid", "eof")

_WS = "\\x00-\\x20\\x7f\\ufeff"
_TRIVIA = "(?:[" + _WS + "]+|#[^\\n]*)*"
_WORD = "[^" + _WS + '{}=<>!#"]+'

# Grupos: 1 trivia, 2 palabra, 3 cadena, 4 llave, 5 operador, 6 "!" suelto.
# Todo carácter puede empezar trivia o un token, así que nunca hay coincidencias
# vacías salvo la final, que produce el token EOF.
_TOKEN_RE = re.compile(
    "(" + _TRIVIA + ")"
    "(?:(" + _WORD + ')|("[^"]*"?)|([{}])|([<>!=]=|[<>=])|(!))?'
)
_GROUP_KIND = (None, EOF, WORD, STRING, LBRACE, OP, INVALID)

BARE_WORD_RE = re.compile(_WORD)
CLEAN_TRIVIA_RE = re.compile(_TRIVIA)
_COMMENT_SCAN_RE = re.compile('"[^"]*"?|(#[^\\n]*)')


class Token:
    """Token con su trivia previa. ``raw is None`` indica texto a regenerar tras una edición."""

    __slots__ = ("kind", "raw", "trivia", "offset", "line", "column")

    def __init__(self, kind: int, raw: str | None, trivia: str, offset: int = -1, line: int = 0, column: int = 0):
        self.kind = kind
        self.raw = raw
        self.trivia = trivia
        self.offset = offset
        self.line = line
        self.column = column

    def detached(self) -> Token:
        """Copia que conserva trivia y posición pero cuyo texto se regenerará."""
        return Token(self.kind, None, self.trivia, self.offset, self.line, self.column)

    def __repr__(self) -> str:
        return f"Token({KIND_NAMES[self.kind]}, {self.raw!r}, trivia={self.trivia!r}, {self.line}:{self.column})"


def tokenize(text: str) -> list[Token]:
    """Divide ``text`` en tokens; el último es siempre ``EOF``."""
    tokens: list[Token] = []
    append = tokens.append
    line = 1
    line_start = 0
    for match in _TOKEN_RE.finditer(text):
        trivia = match.group(1)
        start = match.end(1)
        if "\n" in trivia:
            line += trivia.count("\n")
            line_start = start - len(trivia) + trivia.rfind("\n") + 1
        group = match.lastindex
        if group == 1:
            append(Token(EOF, "", trivia, start, line, start - line_start + 1))
            break
        raw = match.group(group)
        kind = _GROUP_KIND[group]
        if kind == STRING:
            if len(raw) < 2 or raw[-1] != '"':
                kind = OPEN_STRING
            append(Token(kind, raw, trivia, start, line, start - line_start + 1))
            if "\n" in raw:
                line += raw.count("\n")
                line_start = start + raw.rfind("\n") + 1
            continue
        if kind == LBRACE and raw == "}":
            kind = RBRACE
        append(Token(kind, raw, trivia, start, line, start - line_start + 1))
    return tokens


def is_clean_trivia(trivia: str) -> bool:
    """True si la trivia solo tiene espacios y comentarios (ningún token descartado)."""
    return CLEAN_TRIVIA_RE.fullmatch(trivia) is not None


def trivia_comments(trivia: str) -> list[str]:
    """Comentarios (``# ...``) de una trivia, ignorando el texto descartado que contenga."""
    if "#" not in trivia:
        return []
    return [m.group(1).rstrip() for m in _COMMENT_SCAN_RE.finditer(trivia) if m.group(1)]


def newline_split(trivia: str, *, last: bool = False) -> tuple[str, str] | None:
    """Divide justo antes del primer (o último) salto de línea; None si no hay ninguno."""
    index = trivia.rfind("\n") if last else trivia.find("\n")
    if index < 0:
        return None
    if index and trivia[index - 1] == "\r":
        index -= 1
    return trivia[:index], trivia[index:]


def last_line_indent(trivia: str) -> str | None:
    """Sangría del token si empieza su línea (solo espacios/tabs tras el último salto); si no, None."""
    index = trivia.rfind("\n")
    if index < 0:
        return None
    tail = trivia[index + 1:]
    return tail if not tail.strip(" \t") else None
