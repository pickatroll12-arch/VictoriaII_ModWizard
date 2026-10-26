"""Codificaciones de los archivos de Victoria II.

El motor Clausewitz de Victoria II lee los archivos de texto (.txt, .csv, .mod)
en Windows-1252 y no entiende UTF-8. Este módulo detecta la codificación de un
archivo existente y garantiza un ida y vuelta sin pérdidas: decodificar y volver
a codificar un archivo sin cambios produce exactamente los mismos bytes.

cp1252 deja cinco bytes sin definir (0x81, 0x8D, 0x8F, 0x90, 0x9D). En vez de
fallar, se decodifican al punto de código Unicode de mismo valor (como latin-1)
y se vuelven a codificar al byte original.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass

GAME_ENCODING = "cp1252"
UTF8 = "utf-8"
UTF8_BOM = "utf-8-sig"

_CP1252_UNDEFINED = frozenset((0x81, 0x8D, 0x8F, 0x90, 0x9D))
_ERROR_HANDLER = "vic2-cp1252-passthrough"


def _passthrough(error: UnicodeError):
    if isinstance(error, UnicodeDecodeError):
        chunk = error.object[error.start:error.end]
        if all(b in _CP1252_UNDEFINED for b in chunk):
            return "".join(chr(b) for b in chunk), error.end
    elif isinstance(error, UnicodeEncodeError):
        chunk = error.object[error.start:error.end]
        if all(ord(c) in _CP1252_UNDEFINED for c in chunk):
            return bytes(ord(c) for c in chunk), error.end
    raise error


codecs.register_error(_ERROR_HANDLER, _passthrough)


class UnencodableTextError(ValueError):
    """El texto contiene caracteres que la codificación de destino no admite."""

    def __init__(self, encoding: str, problems: list[tuple[int, int, int, str]]):
        self.encoding = encoding
        # (índice, línea 1-based, columna 1-based, carácter)
        self.problems = problems
        index, line, column, char = problems[0]
        super().__init__(
            f"{len(problems)} carácter(es) no representable(s) en {encoding}; "
            f"el primero es {char!r} (U+{ord(char):04X}) en la línea {line}, columna {column}"
        )


@dataclass(frozen=True)
class DecodedText:
    text: str
    encoding: str


def _normalize(encoding: str) -> str:
    return codecs.lookup(encoding).name


def decode_bytes(data: bytes, encoding: str | None = None) -> DecodedText:
    """Decodifica bytes de un archivo del juego.

    Sin ``encoding`` explícita: BOM UTF-8 -> ``utf-8-sig``; si no es ASCII y es
    UTF-8 válido -> ``utf-8``; en cualquier otro caso -> ``cp1252`` sin pérdidas.
    """
    if encoding is not None:
        name = _normalize(encoding)
        if name == GAME_ENCODING:
            return DecodedText(data.decode(GAME_ENCODING, _ERROR_HANDLER), GAME_ENCODING)
        return DecodedText(data.decode(name), name)
    if data.startswith(codecs.BOM_UTF8):
        return DecodedText(data.decode(UTF8_BOM), UTF8_BOM)
    if not data.isascii():
        try:
            return DecodedText(data.decode(UTF8), UTF8)
        except UnicodeDecodeError:
            pass
    return DecodedText(data.decode(GAME_ENCODING, _ERROR_HANDLER), GAME_ENCODING)


def find_unencodable(text: str, encoding: str = GAME_ENCODING) -> list[tuple[int, int, int, str]]:
    """Devuelve (índice, línea, columna, carácter) de cada carácter no codificable."""
    name = _normalize(encoding)
    problems = []
    line, line_start = 1, 0
    for index, char in enumerate(text):
        if char == "\n":
            line, line_start = line + 1, index + 1
            continue
        if char.isascii():
            continue
        try:
            if name == GAME_ENCODING:
                char.encode(GAME_ENCODING, _ERROR_HANDLER)
            else:
                char.encode(name)
        except UnicodeEncodeError:
            problems.append((index, line, index - line_start + 1, char))
    return problems


def encode_text(text: str, encoding: str = GAME_ENCODING) -> bytes:
    """Codifica texto; lanza ``UnencodableTextError`` con posiciones si no es posible."""
    name = _normalize(encoding)
    try:
        if name == GAME_ENCODING:
            return text.encode(GAME_ENCODING, _ERROR_HANDLER)
        return text.encode(name)
    except UnicodeEncodeError:
        raise UnencodableTextError(name, find_unencodable(text, name)) from None


def detect_newline(text: str) -> str:
    """Estilo de salto de línea predominante: ``"\\r\\n"`` o ``"\\n"``."""
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"
