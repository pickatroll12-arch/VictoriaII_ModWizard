"""Parser Clausewitz tolerante a errores.

Gramática::

    documento := entrada*
    entrada   := escalar OP valor | escalar | bloque
    valor     := escalar | bloque
    bloque    := "{" entrada* "}"

Nunca lanza excepciones por el contenido del texto: siempre devuelve un
``Document`` y diagnósticos. Los tokens que no encajan se pliegan como trivia
del token siguiente, así que ``to_source(parse(t).document) == t`` para cualquier
``t``. El análisis es iterativo (pila explícita): el anidamiento no tiene límite.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..encoding import GAME_ENCODING, UTF8_BOM, detect_newline
from ..fileio import read_text
from .diagnostics import Diagnostic, Severity
from .lexer import INVALID, LBRACE, OP, OPEN_STRING, RBRACE, STRING, WORD, last_line_indent, tokenize
from .nodes import Block, Document, Entry, Scalar, first_token

_CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_NON_ASCII_RE = re.compile("[^\x00-\x7f]")
_INDENT_RE = re.compile(r"\n([ \t]+)[^ \t\r\n]")
_TAB_WIDTH = 4

ERROR = Severity.ERROR
WARNING = Severity.WARNING
INFO = Severity.INFO


@dataclass
class ParseResult:
    document: Document
    diagnostics: list = field(default_factory=list)
    encoding: str = GAME_ENCODING
    newline: str = "\n"
    path: Path | None = None

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


def _diag(code, severity, token, args=None, related=None) -> Diagnostic:
    return Diagnostic(code, severity, token.line, token.column, token.offset, args or {}, related or [])


def _fold(token, into) -> None:
    """Convierte ``token`` en trivia del token siguiente (sus bytes no se pierden)."""
    into.trivia = token.trivia + token.raw + into.trivia


def _key_name(scalar: Scalar | None):
    return None if scalar is None else scalar._text


def _build(tokens: list) -> tuple[Document, list, list]:
    doc = Document()
    diags = []
    stack = []
    current = doc
    entries = doc.entries
    cache = {}
    trusted = Scalar._trusted
    parsed_entry = Entry._parsed
    parsed_block = Block._parsed

    def scalar(token):
        # Los escalares son inmutables: un mismo texto comparte objeto dentro del documento.
        raw = token.raw
        kind = token.kind
        value = cache.get(raw)
        if value is None:
            if kind == WORD:
                value = trusted(raw, False)
            elif kind == STRING:
                value = trusted(raw[1:-1], True)
            else:
                value = trusted(raw[1:], True)
            cache[raw] = value
        if kind != WORD:
            if kind == OPEN_STRING:
                diags.append(_diag("unterminated_string", ERROR, token))
            elif "\n" in raw:
                end_line = token.line + raw.count("\n")
                diags.append(_diag("multiline_string", WARNING, token, {"end_line": end_line}))
        return value

    index = 0
    last_close = -1
    while True:
        token = tokens[index]
        kind = token.kind
        if kind <= OPEN_STRING:
            op = tokens[index + 1]
            if op.kind != OP:
                entries.append(parsed_entry(None, None, None, None, scalar(token), token))
                index += 1
                continue
            key = scalar(token)
            pos = index + 2
            value = tokens[pos]
            while value.kind == OP:
                diags.append(_diag("unexpected_operator", ERROR, value, {"op": value.raw, "key": key._text}))
                _fold(value, tokens[pos + 1])
                pos += 1
                value = tokens[pos]
            vkind = value.kind
            if vkind <= OPEN_STRING:
                entries.append(parsed_entry(key, token, op.raw, op, scalar(value), value))
                index = pos + 1
            elif vkind == LBRACE:
                block = parsed_block(value)
                entries.append(parsed_entry(key, token, op.raw, op, block, None))
                stack.append(current)
                current = block
                entries = block.entries
                index = pos + 1
            else:
                diags.append(_diag(
                    "missing_value", ERROR, token, {"key": key._text, "op": op.raw}, [(value.line, value.column)]
                ))
                _fold(token, op)
                _fold(op, value)
                index = pos
        elif kind == LBRACE:
            block = parsed_block(token)
            entries.append(parsed_entry(None, None, None, None, block, None))
            stack.append(current)
            current = block
            entries = block.entries
            index += 1
        elif kind == RBRACE:
            if stack:
                current._close = token
                current = stack.pop()
                entries = current.entries
                last_close = index
            else:
                diags.append(_diag("unexpected_close_brace", ERROR, token))
                _fold(token, tokens[index + 1])
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
            _fold(token, tokens[index + 1])
            index += 1
        elif kind == INVALID:
            diags.append(_diag("invalid_character", ERROR, token, {"char": token.raw}))
            _fold(token, tokens[index + 1])
            index += 1
        else:
            doc._eof = token
            break

    unclosed = []
    if stack:
        opened = stack[1:] + [current]
        for parent, block in zip(stack, opened):
            block._unclosed = True
            owner = parent.entries[-1]
            unclosed.append((owner, block))
            diags.append(_diag(
                "unclosed_block",
                ERROR,
                block._open,
                {"key": _key_name(owner._key), "open_line": block._open.line},
                [(doc._eof.line, doc._eof.column)],
            ))
    return doc, diags, unclosed


def _line_indent_width(text: str, offset: int) -> int:
    start = text.rfind("\n", 0, offset) + 1
    end = start
    while end < len(text) and text[end] in " \t":
        end += 1
    return len(text[start:end].expandtabs(_TAB_WIDTH))


def _suspicious_brace(text: str, outermost: Block) -> Diagnostic | None:
    """Pista para un bloque sin cerrar: la primera ``}`` con menos sangría que su apertura.

    Si falta la ``}`` de un bloque interior, la ``}`` siguiente cierra ese bloque y
    no el que su sangría sugiere; la primera llave así suele marcar el lugar del
    fallo. Basta recorrer el bloque sin cerrar más externo: contiene a los demás.
    """
    best = None
    stack = [outermost]
    while stack:
        block = stack.pop()
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


def _infer_indent_unit(text: str) -> str:
    match = _INDENT_RE.search(text)
    if match is None or match.group(1)[0] == "\t":
        return "\t"
    spaces = len(match.group(1)) - len(match.group(1).lstrip(" "))
    return " " * min(spaces, 8)


def _position(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    return line, offset - (text.rfind("\n", 0, offset) + 1) + 1


def parse(text: str, *, filename: str | os.PathLike | None = None) -> ParseResult:
    """Analiza texto Clausewitz. Nunca falla por el contenido; los problemas van en ``diagnostics``."""
    if not isinstance(text, str):
        raise TypeError(f"parse() espera str, no {type(text).__name__}")
    tokens = tokenize(text)
    doc, diags, unclosed = _build(tokens)
    if unclosed:
        hint = _suspicious_brace(text, unclosed[0][1])
        if hint is not None:
            diags.append(hint)
    control = _CONTROL_RE.findall(text)
    if control:
        offset = _CONTROL_RE.search(text).start()
        line, column = _position(text, offset)
        diags.append(Diagnostic(
            "control_character", WARNING, line, column, offset,
            {"count": len(control), "codepoint": f"{ord(control[0]):04X}"},
        ))
    newline = detect_newline(text)
    doc.newline = newline
    doc.encoding = GAME_ENCODING
    doc._indent_unit = _infer_indent_unit(text)
    diags.sort(key=lambda d: d.offset)
    path = None if filename is None else Path(filename)
    return ParseResult(doc, diags, GAME_ENCODING, newline, path)


def _encoding_warning(text: str, encoding: str) -> Diagnostic | None:
    if encoding == GAME_ENCODING:
        return None
    if encoding == UTF8_BOM:
        return Diagnostic("non_game_encoding", WARNING, 1, 1, 0, {"encoding": "UTF-8 (BOM)"})
    match = _NON_ASCII_RE.search(text)
    if match is None:
        return None
    line, column = _position(text, match.start())
    return Diagnostic("non_game_encoding", WARNING, line, column, match.start(), {"encoding": encoding.upper()})


def parse_file(path: str | os.PathLike, *, encoding: str | None = None) -> ParseResult:
    """Lee y analiza un archivo detectando su codificación (ver ``encoding.decode_bytes``)."""
    path = Path(path)
    decoded = read_text(path, encoding)
    result = parse(decoded.text, filename=path)
    result.encoding = decoded.encoding
    result.document.encoding = decoded.encoding
    warning = _encoding_warning(decoded.text, decoded.encoding)
    if warning is not None:
        result.diagnostics.insert(0, warning)
        result.diagnostics.sort(key=lambda d: d.offset)
    return result
