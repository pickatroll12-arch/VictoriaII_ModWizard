"""Parser Clausewitz tolerante a errores.

Gramática::

    documento := entrada*
    entrada   := escalar OP valor | escalar | bloque
    valor     := escalar | bloque
    bloque    := "{" entrada* "}"

Nunca lanza excepciones por el contenido del texto: siempre devuelve un
``Document`` y diagnósticos. Los tokens que no encajan se pliegan como trivia
del siguiente token que se queda en el árbol, así que ``to_source(parse(t).document) == t``
para cualquier ``t``. El análisis es iterativo (pila explícita): el anidamiento no tiene límite.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

from ..cancel import CancelCheck, raise_if_cancelled
from ..encoding import GAME_ENCODING, UTF8_BOM, detect_newline
from ..fileio import read_text
from .diagnostics import Diagnostic, Severity
from .lexer import (
    CANCEL_EVERY,
    CONTROL_RE,
    INVALID,
    INVISIBLE_RE,
    LBRACE,
    LINE_BREAK_RE,
    OP,
    OPEN_STRING,
    RBRACE,
    WORD,
    last_line_indent,
    line_start,
    position,
    scalar_text,
    tail_comment,
    tokenize,
)
from .nodes import Block, Document, Entry, Scalar, first_token

_NON_ASCII_RE = re.compile("[^\x00-\x7f]")
_INDENT_RE = re.compile(r"[\r\n]([ \t]*)[^ \t\r\n]")
_INDENT_SAMPLE = 8192  # caracteres del principio que bastan para deducir la unidad de sangría
_TAB_WIDTH = 4

ERROR = Severity.ERROR
WARNING = Severity.WARNING
INFO = Severity.INFO

# Extensiones de los archivos de script Clausewitz del juego (map/default.map también lo es).
CLAUSEWITZ_SUFFIXES = frozenset({".txt", ".mod", ".gfx", ".gui", ".sfx", ".asset", ".map"})


class ParseResult:
    """Documento analizado, sus diagnósticos y la ruta del archivo.

    ``encoding`` y ``newline`` son los del documento (una sola fuente de verdad):
    cambiarlos aquí o en ``document`` es lo mismo, y ``write_file`` usa esos valores.
    ``stamp`` es la huella de los bytes leídos por ``parse_file`` (para
    ``write_file(..., expected=result.stamp)``); None si no viene de un archivo.
    """

    __slots__ = ("document", "diagnostics", "path", "stamp")

    def __init__(self, document: Document, diagnostics: list | None = None, encoding: str | None = None,
                 newline: str | None = None, path: str | os.PathLike | None = None):
        self.document = document
        self.diagnostics = [] if diagnostics is None else diagnostics
        self.path = None if path is None else Path(path)
        self.stamp = None
        if encoding is not None:
            document.encoding = encoding
        if newline is not None:
            document.newline = newline

    @property
    def encoding(self) -> str:
        return self.document.encoding or GAME_ENCODING

    @encoding.setter
    def encoding(self, value: str) -> None:
        self.document.encoding = value

    @property
    def newline(self) -> str:
        return self.document.newline

    @newline.setter
    def newline(self, value: str) -> None:
        self.document.newline = value

    @property
    def ok(self) -> bool:
        """True si no hay diagnósticos de error (los avisos no cuentan)."""
        return not any(d.severity is ERROR for d in self.diagnostics)

    @property
    def errors(self) -> list:
        return [d for d in self.diagnostics if d.severity is ERROR]

    @property
    def warnings(self) -> list:
        return [d for d in self.diagnostics if d.severity is WARNING]

    def __repr__(self) -> str:
        return f"ParseResult({self.path}, {len(self.diagnostics)} diagnostics, encoding={self.encoding!r})"


def _diag(code, severity, token, args=None, related=None) -> Diagnostic:
    return Diagnostic(code, severity, token.line, token.column, token.offset, args or {}, related or [])


def _take_line_comment(entries: list, trivia: str) -> None:
    """Comentario al final de la línea de la última entrada (ver ``Entry.line_comment``): el de ``trivia``."""
    comment = tail_comment(trivia)
    if comment is not None:
        entries[-1]._line_comment = comment


def _keep(token, folded: list, entries: list) -> None:
    """``token`` se queda en el árbol: recibe en su trivia el texto descartado de delante, de una vez."""
    folded.append(token.trivia)
    token.trivia = "".join(folded)
    folded.clear()
    if entries and "#" in token.trivia:
        _take_line_comment(entries, token.trivia)


def _key_name(scalar: Scalar | None):
    return None if scalar is None else scalar._text


def _build(tokens: list, cancelled: CancelCheck = None) -> tuple[Document, list, list]:
    doc = Document()
    diags = []
    stack = []
    current = doc
    entries = doc.entries
    cache = {}
    trusted = Scalar._trusted
    parsed_entry = Entry._parsed
    parsed_block = Block._parsed
    checkpoint = CANCEL_EVERY
    # Tokens descartados (trivia y texto) que aún no tienen dueño: pasan de una vez a la trivia del siguiente
    # token que se queda (ver _keep). Plegarlos uno a uno en el siguiente copiaría todo lo acumulado en cada
    # paso: tiempo y memoria cuadráticos con muchos errores seguidos.
    folded = []

    def scalar(token):
        # Los escalares son inmutables: un mismo texto comparte objeto dentro del documento.
        raw = token.raw
        kind = token.kind
        value = cache.get(raw)
        if value is None:
            value = cache[raw] = trusted(scalar_text(kind, raw), kind != WORD)
        if kind != WORD:
            if kind == OPEN_STRING:
                diags.append(_diag("unterminated_string", ERROR, token))
            elif "\n" in raw or "\r" in raw:
                end_line = token.line + len(LINE_BREAK_RE.findall(raw))
                diags.append(_diag("multiline_string", WARNING, token, {"end_line": end_line}))
        return value

    index = 0
    last_close = -1
    while True:
        if index >= checkpoint:
            raise_if_cancelled(cancelled)
            checkpoint = index + CANCEL_EVERY
        token = tokens[index]
        kind = token.kind
        if entries and not folded and "#" in token.trivia:
            # Comentario de final de línea de la entrada anterior; tras texto descartado, lo busca _keep.
            _take_line_comment(entries, token.trivia)
        if kind <= OPEN_STRING:
            op = tokens[index + 1]
            if op.kind != OP:
                if folded:
                    _keep(token, folded, entries)
                entries.append(parsed_entry(None, None, None, None, scalar(token), token))
                index += 1
                continue
            key = scalar(token)
            pos = index + 2
            value = tokens[pos]
            while value.kind == OP:
                diags.append(_diag("unexpected_operator", ERROR, value, {"op": value.raw, "key": key._text}))
                pos += 1
                value = tokens[pos]
            vkind = value.kind
            if vkind == LBRACE or vkind <= OPEN_STRING and not (value.line > op.line and tokens[pos + 1].kind == OP):
                if folded:
                    _keep(token, folded, entries)
                if pos > index + 2:
                    # Los operadores sobrantes pasan a la trivia del valor.
                    value.trivia = "".join([t.trivia + t.raw for t in tokens[index + 2:pos]] + [value.trivia])
                if vkind == LBRACE:
                    block = parsed_block(value)
                    entries.append(parsed_entry(key, token, op.raw, op, block, None))
                    stack.append(current)
                    current = block
                    entries = block.entries
                else:
                    entries.append(parsed_entry(key, token, op.raw, op, scalar(value), value))
                index = pos + 1
            else:
                # Sin valor antes de "}" o del final, o "clave =" al final de una línea seguida de
                # "otra = ...": la palabra siguiente es la clave de la entrada siguiente, no el valor.
                diags.append(_diag(
                    "missing_value", ERROR, token, {"key": key._text, "op": op.raw}, [(value.line, value.column)]
                ))
                for discarded in tokens[index:pos]:
                    folded += (discarded.trivia, discarded.raw)
                index = pos
        elif kind == LBRACE:
            if folded:
                _keep(token, folded, entries)
            block = parsed_block(token)
            entries.append(parsed_entry(None, None, None, None, block, None))
            stack.append(current)
            current = block
            entries = block.entries
            index += 1
        elif kind == RBRACE:
            if stack:
                if folded:
                    _keep(token, folded, entries)
                current._close = token
                current._orig = entries[:]
                current = stack.pop()
                entries = current.entries
                last_close = index
            else:
                diags.append(_diag("unexpected_close_brace", ERROR, token))
                folded += (token.trivia, token.raw)
            index += 1
        elif kind == OP:
            previous = entries[-1] if entries else None
            if (
                last_close == index - 1
                and previous is not None
                and previous._key is None
                and previous._value.__class__ is not Scalar
            ):
                block = previous._value
                diags.append(_diag("invalid_key", ERROR, block._open, {"op": token.raw}, [(token.line, token.column)]))
            else:
                diags.append(_diag("missing_key", ERROR, token, {"op": token.raw}))
            folded += (token.trivia, token.raw)
            index += 1
        elif kind == INVALID:
            diags.append(_diag("invalid_character", ERROR, token, {"char": token.raw}))
            folded += (token.trivia, token.raw)
            index += 1
        else:
            if folded:
                _keep(token, folded, entries)
            doc._eof = token
            break

    unclosed = []
    if stack:
        opened = stack[1:] + [current]
        for parent, block in zip(stack, opened):
            block._unclosed = True
            block._orig = block.entries[:]
            owner = parent.entries[-1]
            unclosed.append((owner, block))
            diags.append(_diag(
                "unclosed_block",
                ERROR,
                block._open,
                {"key": _key_name(owner._key), "open_line": block._open.line},
                [(doc._eof.line, doc._eof.column)],
            ))
    doc._orig = doc.entries[:]
    return doc, diags, unclosed


def _line_indent_width(text: str, offset: int) -> int:
    start = line_start(text, offset)
    end = start
    while end < len(text) and text[end] in " \t":
        end += 1
    return len(text[start:end].expandtabs(_TAB_WIDTH))


def _suspicious_brace(text: str, outermost: Block, cancelled: CancelCheck = None) -> Diagnostic | None:
    """Pista para un bloque sin cerrar: la primera ``}`` con menos sangría que su apertura.

    Si falta la ``}`` de un bloque interior, la ``}`` siguiente cierra ese bloque y
    no el que su sangría sugiere; la primera llave así suele marcar el lugar del
    fallo. Basta recorrer el bloque sin cerrar más externo: contiene a los demás.
    """
    best = None
    stack = [outermost]
    visited = 0
    while stack:
        block = stack.pop()
        visited += len(block.entries) + 1
        if visited >= CANCEL_EVERY:
            raise_if_cancelled(cancelled)
            visited = 0
        for entry in block.entries:
            child = entry._value
            if child.__class__ is Scalar:
                continue
            stack.append(child)
            close = child._close
            if close is None or (best is not None and close.offset >= best[0].offset):
                continue
            indent = last_line_indent(close.trivia)
            if indent is None:
                continue
            if len(indent.expandtabs(_TAB_WIDTH)) < _line_indent_width(text, first_token(entry).offset):
                best = (close, entry, child)
    if best is None:
        return None
    close, entry, child = best
    return _diag(
        "suspicious_close_brace",
        INFO,
        close,
        {"key": _key_name(entry._key), "open_line": child._open.line},
        [(child._open.line, child._open.column)],
    )


def _invisible_characters(tokens: list, cancelled: CancelCheck = None) -> list:
    """Avisos de palabras sin comillas con caracteres invisibles (NBSP, espacio de ancho cero...)."""
    found = []
    for index, token in enumerate(tokens):
        if not index % CANCEL_EVERY:
            raise_if_cancelled(cancelled)
        if token.kind == WORD:
            match = INVISIBLE_RE.search(token.raw)
            if match is not None:
                start = match.start()
                found.append(Diagnostic(
                    "invisible_character", WARNING, token.line, token.column + start, token.offset + start,
                    {"word": token.raw, "codepoint": f"{ord(match.group()):04X}"},
                ))
    return found


def _infer_indent_unit(text: str) -> str:
    """Unidad de sangría predominante al principio del texto: tab si hay al menos tantas líneas
    sangradas con tab como con espacios; si no, el salto de espacios más frecuente entre líneas."""
    sample = text[:_INDENT_SAMPLE]
    # Contar en C basta para lo habitual (tabs) y evita recorrer las líneas.
    tabs, spaces = sample.count("\n\t"), sample.count("\n ")
    if not (tabs or spaces):  # quizá solo CR como salto de línea
        tabs, spaces = sample.count("\r\t"), sample.count("\r ")
    if tabs >= spaces:
        return "\t"
    previous = 0
    steps = Counter()
    for match in _INDENT_RE.finditer(sample):
        indent = match.group(1)
        width = len(indent.expandtabs(_TAB_WIDTH))
        if width > previous and indent[:1] != "\t":
            steps[width - previous] += 1
        previous = width
    if not steps:
        return "\t"
    return " " * min(steps.most_common(1)[0][0], 8)


def parse(text: str, *, filename: str | os.PathLike | None = None, cancelled: CancelCheck = None) -> ParseResult:
    """Analiza texto Clausewitz. Nunca falla por el contenido; los problemas van en ``diagnostics``.

    Si ``cancelled()`` devuelve True durante el análisis lanza ``core.cancel.Cancelled``.
    """
    if not isinstance(text, str):
        raise TypeError(f"parse() espera str, no {type(text).__name__}")
    raise_if_cancelled(cancelled)
    tokens = tokenize(text, cancelled=cancelled)
    doc, diags, unclosed = _build(tokens, cancelled)
    raise_if_cancelled(cancelled)
    if unclosed:
        hint = _suspicious_brace(text, unclosed[0][1], cancelled)
        if hint is not None:
            diags.append(hint)
    control = CONTROL_RE.findall(text)
    if control:
        offset = CONTROL_RE.search(text).start()
        line, column = position(text, offset)
        diags.append(Diagnostic(
            "control_character", WARNING, line, column, offset,
            {"count": len(control), "codepoint": f"{ord(control[0]):04X}"},
        ))
    if not text.isascii() and INVISIBLE_RE.search(text) is not None:
        diags.extend(_invisible_characters(tokens, cancelled))
    doc.newline = detect_newline(text)
    doc.encoding = GAME_ENCODING
    doc._indent_unit = _infer_indent_unit(text)
    diags.sort(key=lambda d: d.offset)
    return ParseResult(doc, diags, path=filename)


def _encoding_warning(text: str, encoding: str) -> Diagnostic | None:
    if encoding == GAME_ENCODING:
        return None
    if encoding == UTF8_BOM:
        return Diagnostic("non_game_encoding", WARNING, 1, 1, 0, {"encoding": "UTF-8 (BOM)"})
    match = _NON_ASCII_RE.search(text)
    if match is None:
        return None
    line, column = position(text, match.start())
    return Diagnostic("non_game_encoding", WARNING, line, column, match.start(), {"encoding": encoding.upper()})


def parse_file(path: str | os.PathLike, *, encoding: str | None = None,
               cancelled: CancelCheck = None) -> ParseResult:
    """Lee y analiza un archivo detectando su codificación (ver ``encoding.decode_bytes``)."""
    path = Path(path)
    decoded = read_text(path, encoding)
    result = parse(decoded.text, filename=path, cancelled=cancelled)
    result.encoding = decoded.encoding
    result.stamp = decoded.stamp
    warning = _encoding_warning(decoded.text, decoded.encoding)
    if warning is not None:
        result.diagnostics.insert(0, warning)
        result.diagnostics.sort(key=lambda d: d.offset)
    return result
