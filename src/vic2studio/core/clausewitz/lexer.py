"""Analizador léxico del formato Clausewitz.

Cada token guarda su *trivia* previa: espacios, saltos de línea, comentarios y,
en documentos con errores, el texto de los tokens que el parser descarta. La
concatenación de ``trivia + raw`` de todos los tokens (el último es ``EOF``, que
solo lleva la trivia final) reproduce el texto original exacto.

Reglas léxicas:

- espacio: cualquier carácter de control ASCII (``\\x00``-``\\x20``, ``\\x7f``) y U+FEFF;
- salto de línea: ``\\r\\n``, ``\\n`` o un ``\\r`` suelto (como en los editores de texto);
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
from bisect import bisect_right

from ..cancel import CancelCheck, raise_if_cancelled

WORD, STRING, OPEN_STRING, LBRACE, RBRACE, OP, INVALID, EOF = range(8)
KIND_NAMES = ("word", "string", "open_string", "lbrace", "rbrace", "op", "invalid", "eof")

_WS = "\\x00-\\x20\\x7f\\ufeff"
_TRIVIA = "(?:[" + _WS + "]+|#[^\\r\\n]*)*"
_WORD = "[^" + _WS + '{}=<>!#"]+'

# Pares (trivia, token): palabra, cadena, llave, operador o "!" suelto. Todo carácter puede
# empezar trivia o un token, así que el token solo es vacío al final del texto analizado.
_TOKEN_RE = re.compile("(" + _TRIVIA + ")(" + _WORD + '|"[^"]*"?|[{}]|[<>!=]=|[<>=]|!|)')
_KINDS = {"{": LBRACE, "}": RBRACE, '"': STRING, "<": OP, ">": OP, "=": OP, "!": OP}

# Caracteres por tanda: la cancelación se consulta entre tandas. Con tandas mayores, las tuplas que
# devuelve findall de golpe hacen trabajar de más al recolector de basura (con 64 000 caracteres,
# Python 3.10 pasaba en él más del doble de tiempo).
_CHUNK = 1 << 13
CANCEL_EVERY = 1 << 14  # elementos (tokens, entradas...) entre dos consultas de cancelación en los recorridos

BARE_WORD_RE = re.compile(_WORD)
WORD_CHAR_RE = re.compile("[^" + _WS + '{}=<>!#"]')
CLEAN_TRIVIA_RE = re.compile(_TRIVIA)
LINE_BREAK_RE = re.compile("\\r\\n?|\\n")
# Caracteres de control que no son espacio habitual (tab, salto de línea): invisibles y sospechosos.
CONTROL_RE = re.compile("[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]")
# Caracteres que no se ven pero forman parte de una palabra: espacios no ASCII, de ancho
# cero, marcas de dirección y controles C1 (típicos al copiar de foros o wikis).
INVISIBLE_RE = re.compile("[\\x80-\\xa0\\xad\\u2000-\\u200f\\u2028-\\u202f\\u205f-\\u2064\\u3000]")
_COMMENT_SCAN_RE = re.compile('"[^"]*"?|(#[^\\r\\n]*)')


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


def tokenize(text: str, *, cancelled: CancelCheck = None) -> list[Token]:
    """Divide ``text`` en tokens; el último es siempre ``EOF``.

    Consulta ``cancelled()`` entre tandas de unos 8 000 caracteres y lanza ``core.cancel.Cancelled``.
    """
    tokens = _scan(text, cancelled)
    if "\r" in text and text.count("\r") != text.count("\r\n"):
        _relocate(tokens, text, cancelled)
    return tokens


def _scan(text: str, cancelled: CancelCheck) -> list[Token]:
    """Tokens con línea y columna contando solo ``\\n`` (basta si no hay ``\\r`` sueltos).

    El texto se analiza por tandas. Lo que puede seguir tras el corte de una tanda (la
    trivia del final, una palabra, un operador o una cadena sin cerrar) se vuelve a leer
    entero en la tanda siguiente, así que el resultado no depende de dónde se corte.
    """
    tokens: list[Token] = []
    append = tokens.append
    findall = _TOKEN_RE.findall
    kinds = _KINDS
    size = len(text)
    line = 1
    line_start = 0
    pos = 0  # inicio de la trivia del token siguiente
    width = _CHUNK
    while True:
        end = min(pos + width, size)
        begin = pos
        width = 0  # ancho de la tanda siguiente si hace falta uno concreto
        for trivia, raw in findall(text, pos, end):
            if not raw:
                if end < size:
                    break  # la trivia del final de la tanda se lee con la siguiente
                if "\n" in trivia:
                    line += trivia.count("\n")
                    line_start = pos + trivia.rfind("\n") + 1
                start = pos + len(trivia)
                append(Token(EOF, "", trivia, start, line, start - line_start + 1))
                return tokens
            start = pos + len(trivia)
            kind = kinds.get(raw[0], WORD)
            closed = kind != STRING or (len(raw) > 1 and raw[-1] == '"')
            if end < size and start + len(raw) == end and (kind == WORD or kind == OP or not closed):
                # El token llega al corte y podría seguir detrás: se lee entero en la tanda siguiente.
                if not closed:
                    quote = text.find('"', start + 1)
                    width = (size if quote < 0 else quote + 1) - pos
                break
            if not closed:
                kind = OPEN_STRING
            elif kind == OP and raw == "!":
                kind = INVALID
            if "\n" in trivia:
                line += trivia.count("\n")
                line_start = pos + trivia.rfind("\n") + 1
            append(Token(kind, raw, trivia, start, line, start - line_start + 1))
            pos = start + len(raw)
            if kind == STRING or kind == OPEN_STRING:
                if "\n" in raw:
                    line += raw.count("\n")
                    line_start = start + raw.rfind("\n") + 1
        if not width:
            width = 2 * (end - begin) if pos == begin else _CHUNK  # sin ningún token completo, se amplía
        raise_if_cancelled(cancelled)


def _relocate(tokens: list[Token], text: str, cancelled: CancelCheck) -> None:
    """Recalcula línea y columna contando también los ``\\r`` sueltos como salto de línea."""
    starts = [0]
    starts.extend(match.end() for match in LINE_BREAK_RE.finditer(text))
    for index, token in enumerate(tokens):
        line = bisect_right(starts, token.offset)
        token.line = line
        token.column = token.offset - starts[line - 1] + 1
        if not index % CANCEL_EVERY:
            raise_if_cancelled(cancelled)


def end_position(token: Token) -> tuple[int, int]:
    """Línea y columna (1-based) del último carácter de ``token``, con la regla de saltos de ``tokenize``.

    Una cadena puede abarcar varias líneas. Un salto de línea final (una cadena sin
    cerrar al final del archivo) cuenta en su línea, en la columna donde empieza.
    """
    raw = token.raw
    if "\n" not in raw and "\r" not in raw:
        return token.line, token.column + len(raw) - 1
    breaks = list(LINE_BREAK_RE.finditer(raw))
    last = breaks[-1]
    if last.end() < len(raw):
        return token.line + len(breaks), len(raw) - last.end()
    if len(breaks) == 1:
        return token.line, token.column + last.start()
    return token.line + len(breaks) - 1, last.start() - breaks[-2].end() + 1


def scalar_text(kind: int, raw: str) -> str:
    """Texto de un escalar leído (``WORD``, ``STRING`` u ``OPEN_STRING``), sin sus comillas."""
    return raw if kind == WORD else raw[1:-1] if kind == STRING else raw[1:]


def position(text: str, offset: int) -> tuple[int, int]:
    """Línea y columna (1-based) de ``offset``, con la misma regla de saltos que ``tokenize``."""
    start = line_start(text, offset)
    return len(LINE_BREAK_RE.findall(text, 0, start)) + 1, offset - start + 1


def line_start(text: str, offset: int) -> int:
    """Inicio de la línea de ``offset``: justo tras el último salto anterior (``\\n`` o ``\\r``)."""
    # El "\r" solo se busca en la propia línea: en un archivo LF, buscarlo hasta el principio costaría O(n).
    lf = text.rfind("\n", 0, offset)
    return max(lf, text.rfind("\r", lf + 1, offset)) + 1


def is_clean_trivia(trivia: str) -> bool:
    """True si la trivia solo tiene espacios y comentarios (ningún token descartado)."""
    # Sin anclar el final: la estrella codiciosa termina sin retroceder (fullmatch es exponencial).
    return CLEAN_TRIVIA_RE.match(trivia).end() == len(trivia)


def trivia_comments(trivia: str) -> list[str]:
    """Comentarios (``# ...``) de una trivia, ignorando el texto descartado que contenga."""
    if "#" not in trivia:
        return []
    return [m.group(1).rstrip() for m in _COMMENT_SCAN_RE.finditer(trivia) if m.group(1)]


def comment_start(text: str) -> int:
    """Posición del ``#`` del primer comentario (fuera de cadenas descartadas); -1 si no hay."""
    if "#" in text:
        for match in _COMMENT_SCAN_RE.finditer(text):
            if match.group(1):
                return match.start(1)
    return -1


def tail_comment(trivia: str) -> str | None:
    """Comentario al final de la línea del token anterior (antes del primer salto de la trivia)."""
    if "#" not in trivia:
        return None
    cut = first_break(trivia)
    head = trivia if cut < 0 else trivia[:cut]
    start = comment_start(head)
    return None if start < 0 else head[start:].rstrip()


def head_comments(trivia: str, at_start: bool = False) -> list[str]:
    """Comentarios de las líneas propias de la trivia, tras su primer salto de línea.

    Con ``at_start`` (la trivia empieza el archivo) cuenta también la primera línea.
    """
    if "#" not in trivia:
        return []
    if not at_start:
        cut = first_break(trivia)
        if cut < 0:
            return []
        trivia = trivia[cut:]
    return trivia_comments(trivia)


def first_break(text: str, start: int = 0) -> int:
    """Índice del primer salto de línea (``\\r`` o ``\\n``) desde ``start``; -1 si no hay."""
    lf = text.find("\n", start)
    cr = text.find("\r", start, None if lf < 0 else lf)
    return lf if cr < 0 else cr


def last_break_end(text: str) -> int:
    """Posición justo detrás del último salto de línea; 0 si no hay ninguno."""
    return line_start(text, len(text))


def newline_split(trivia: str, *, last: bool = False) -> tuple[str, str] | None:
    """Divide justo antes del primer (o último) salto de línea; None si no hay ninguno."""
    if last:
        index = last_break_end(trivia) - 1
        if index > 0 and trivia[index] == "\n" and trivia[index - 1] == "\r":
            index -= 1
    else:
        index = first_break(trivia)
    if index < 0:
        return None
    return trivia[:index], trivia[index:]


def last_line_indent(trivia: str) -> str | None:
    """Sangría del token si empieza su línea (solo espacios/tabs tras el último salto); si no, None."""
    index = last_break_end(trivia)
    if not index:
        return None
    tail = trivia[index:]
    return tail if not tail.strip(" \t") else None
