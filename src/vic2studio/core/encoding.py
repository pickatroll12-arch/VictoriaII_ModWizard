"""Codificaciones de los archivos de Victoria II.

El motor Clausewitz de Victoria II lee los archivos de texto (.txt, .csv, .mod)
en Windows-1252 y no entiende UTF-8 ni, en absoluto, UTF-16. Este módulo
detecta la codificación de un archivo existente y garantiza un ida y vuelta sin
pérdidas: decodificar y volver a codificar un archivo sin cambios produce
exactamente los mismos bytes.

cp1252 deja cinco bytes sin definir (0x81, 0x8D, 0x8F, 0x90, 0x9D). En vez de
fallar, se decodifican al punto de código Unicode de mismo valor (como latin-1)
y se vuelven a codificar al byte original.

Codificaciones que puede devolver la detección:

* ``cp1252``: la del juego y la de todo lo que no encaja en las demás. También
  un archivo con BOM UTF-8 cuyo resto no es UTF-8 (un UTF-8 reconvertido a ANSI
  sin quitar el BOM): el juego ve entonces ``STRAY_BOM`` pegado a la primera
  clave (``has_stray_bom``).
* ``utf-8`` (sin BOM) y ``utf-8-sig`` (con BOM; el BOM no queda en el texto).
* ``utf-16`` (BOM FF FE, el «Unicode» del Bloc de notas y de PowerShell 5) y
  ``utf-16-be-bom`` (BOM FE FF, un codec que registra este módulo): como en
  ``utf-8-sig``, el BOM no queda en el texto y se vuelve a escribir delante, cada
  uno en su orden de bytes. ``utf-16-le``/``utf-16-be``: UTF-16 sin BOM,
  reconocido por los NUL alternos. El juego no puede leer ninguna de ellas
  (``GAME_UNREADABLE``).

Con una codificación explícita se usa ese codec tal cual: ``utf-8``,
``utf-16-le`` y ``utf-16-be`` dejan un BOM en el texto como U+FEFF
(``split_bom`` lo pasa a la codificación), y las que lo quitan no dicen si lo
había ni en qué orden de bytes (``match_bom`` lo mira en los bytes). Un BOM
repetido queda en el texto como U+FEFF tras el primero (``split_extra_boms``
los separa).
"""

from __future__ import annotations

import codecs
import sys
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fileio import FileStamp

GAME_ENCODING = "cp1252"
UTF8 = "utf-8"
UTF8_BOM = "utf-8-sig"
UTF16 = "utf-16"
UTF16_LE = "utf-16-le"
UTF16_BE = "utf-16-be"
UTF16_BE_BOM = "utf-16-be-bom"
# El juego lee bytes sueltos: con estas los textos le llegan llenos de NUL.
GAME_UNREADABLE = frozenset({UTF16, UTF16_LE, UTF16_BE, UTF16_BE_BOM})
BOM = "\ufeff"
# Lo que ve el juego (y lo que queda en el texto) cuando un BOM UTF-8 precede a texto cp1252.
STRAY_BOM = codecs.BOM_UTF8.decode("latin-1")
# Codecs que dejan el BOM en el texto como U+FEFF -> el que lo quita al leer y lo vuelve a escribir.
_WITH_BOM = {UTF8: UTF8_BOM, UTF16_LE: UTF16, UTF16_BE: UTF16_BE_BOM}
# Codificaciones que quitan su BOM al leer y lo vuelven a escribir delante.
BOM_ENCODINGS = frozenset(_WITH_BOM.values())
# Nombres para mostrar (visor, diagnósticos del parser, lint del CSV): con el orden de bytes y el BOM explícitos.
DISPLAY_NAMES = {
    GAME_ENCODING: "Windows-1252", UTF8: "UTF-8", UTF8_BOM: "UTF-8 BOM", UTF16: "UTF-16 LE BOM",
    UTF16_BE_BOM: "UTF-16 BE BOM", UTF16_LE: "UTF-16 LE", UTF16_BE: "UTF-16 BE",
}

_CP1252_UNDEFINED = frozenset((0x81, 0x8D, 0x8F, 0x90, 0x9D))
_ERROR_HANDLER = "vic2-cp1252-passthrough"
_COLLECT_HANDLER = "vic2-collect-unencodable"
_COLLECT_TLS = threading.local()
# Bytes que se miran para reconocer UTF-16 sin BOM, y proporción de NUL exigida en
# los bytes altos (los textos del juego son latinos: casi todos los caracteres < U+0100).
_UTF16_SAMPLE = 4096
_UTF16_MIN_NUL = 0.75
_UTF16_MAX_NUL_LOW = 0.1


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


def _collect_unencodable(error: UnicodeError):
    if not isinstance(error, UnicodeEncodeError):
        raise error
    text = error.object
    indices, is_cp1252 = _COLLECT_TLS.state
    if is_cp1252:
        for index in range(error.start, error.end):
            if ord(text[index]) not in _CP1252_UNDEFINED:
                indices.append(index)
    else:
        indices.extend(range(error.start, error.end))
    return b"", error.end


codecs.register_error(_ERROR_HANDLER, _passthrough)
codecs.register_error(_COLLECT_HANDLER, _collect_unencodable)


# --- codec ``utf-16-be-bom``: UTF-16 big-endian con BOM, como ``utf-8-sig`` -----------------
# Al leer quita el BOM si lo hay (sin él, lee big-endian); al escribir lo pone delante.

def _be_bom_encode(text: str, errors: str = "strict") -> tuple[bytes, int]:
    return codecs.BOM_UTF16_BE + codecs.utf_16_be_encode(text, errors)[0], len(text)


def _be_bom_decode(data, errors: str = "strict", final: bool = True) -> tuple[str, int]:
    skip = 2 if bytes(data[:2]) == codecs.BOM_UTF16_BE else 0
    text, consumed = codecs.utf_16_be_decode(data[skip:], errors, final)
    return text, consumed + skip


class _BeBomIncrementalEncoder(codecs.IncrementalEncoder):
    def __init__(self, errors: str = "strict"):
        super().__init__(errors)
        self.first = 1

    def encode(self, text: str, final: bool = False) -> bytes:
        if self.first:
            self.first = 0
            return _be_bom_encode(text, self.errors)[0]
        return codecs.utf_16_be_encode(text, self.errors)[0]

    def reset(self) -> None:
        self.first = 1

    def getstate(self) -> int:
        return self.first

    def setstate(self, state: int) -> None:
        self.first = state


class _BeBomIncrementalDecoder(codecs.BufferedIncrementalDecoder):
    def __init__(self, errors: str = "strict"):
        super().__init__(errors)
        self.first = 1

    def _buffer_decode(self, data, errors: str, final: bool) -> tuple[str, int]:
        if not self.first:
            return codecs.utf_16_be_decode(data, errors, final)
        if len(data) < 2 and not final:
            return "", 0  # aún no se sabe si empieza por el BOM
        self.first = 0
        return _be_bom_decode(data, errors, final)

    def reset(self) -> None:
        super().reset()
        self.first = 1

    def getstate(self) -> tuple[bytes, int]:
        return self.buffer, self.first

    def setstate(self, state: tuple[bytes, int]) -> None:
        self.buffer, self.first = state


class _BeBomStreamWriter(codecs.StreamWriter):
    def encode(self, text: str, errors: str = "strict") -> tuple[bytes, int]:
        self.encode = codecs.utf_16_be_encode  # el BOM, solo en la primera escritura
        return _be_bom_encode(text, errors)

    def reset(self) -> None:
        super().reset()
        self.__dict__.pop("encode", None)


class _BeBomStreamReader(codecs.StreamReader):
    def decode(self, data, errors: str = "strict") -> tuple[str, int]:
        if len(data) < 2:
            return "", 0
        self.decode = codecs.utf_16_be_decode
        return _be_bom_decode(data, errors, False)

    def reset(self) -> None:
        super().reset()
        self.__dict__.pop("decode", None)


_BE_BOM_CODEC = codecs.CodecInfo(
    _be_bom_encode, _be_bom_decode, _BeBomStreamReader, _BeBomStreamWriter,
    _BeBomIncrementalEncoder, _BeBomIncrementalDecoder, name=UTF16_BE_BOM,
)
# ``codecs.lookup`` pasa el nombre en minúsculas y con "_" en lugar de "-" y espacios.
codecs.register(lambda name: _BE_BOM_CODEC if name == UTF16_BE_BOM.replace("-", "_") else None)


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
    # Huella de los bytes leídos (``fileio.read_text``); ``None`` si no vienen de un archivo.
    stamp: FileStamp | None = None


def normalize_encoding(encoding: str) -> str:
    """Nombre canónico de ``encoding``; ``LookupError`` si no existe o no es de texto (base64, rot13...)."""
    info = codecs.lookup(encoding)
    if not getattr(info, "_is_text_encoding", True):
        raise LookupError(f"{encoding!r} no es una codificación de texto")
    return info.name


def display_name(encoding: str) -> str:
    """Nombre legible de ``encoding`` (``utf-16-be-bom`` → ``UTF-16 BE BOM``, ``cp1252`` → ``Windows-1252``).

    Acepta alias (``windows-1252``, ``UTF-16-BE-BOM``); una codificación sin nombre propio sale en mayúsculas.
    """
    try:
        return DISPLAY_NAMES.get(normalize_encoding(encoding), encoding.upper())
    except LookupError:
        return encoding.upper()


def has_stray_bom(text: str, encoding: str) -> bool:
    """True si el texto, leído como cp1252, empieza por los bytes de un BOM UTF-8."""
    return encoding == GAME_ENCODING and text.startswith(STRAY_BOM)


def split_bom(text: str, encoding: str) -> tuple[str, str]:
    """(texto, codificación) sin el U+FEFF inicial que ``encoding`` deja en el texto al leer un BOM.

    ``utf-8`` pasa a ``utf-8-sig``, ``utf-16-le`` a ``utf-16`` y ``utf-16-be`` a
    ``utf-16-be-bom``, que lo vuelven a escribir: codificar el resultado da los
    mismos bytes. Con las demás no cambia nada (la codificación sale normalizada):
    tras ``utf-8-sig`` o ``utf-16`` un U+FEFF inicial es un BOM repetido
    (``split_extra_boms``).
    """
    name = normalize_encoding(encoding)
    if text.startswith(BOM) and name in _WITH_BOM:
        return text[1:], _WITH_BOM[name]
    return text, name


def match_bom(data: bytes, encoding: str) -> str:
    """Codificación de la familia de ``encoding`` que vuelve a escribir el BOM tal como está en ``data``.

    Las que quitan el BOM al leer no dejan rastro de él en el texto: ``utf-8-sig``
    sin BOM pasa a ``utf-8`` y ``utf-16-be-bom`` sin BOM, a ``utf-16-be``; ``utf-16``
    con BOM FE FF (big-endian) pasa a ``utf-16-be-bom`` y sin BOM, a la de esta
    máquina, que es la que usa el codec (``utf-16-le`` casi siempre). Las demás no
    cambian (la codificación sale normalizada): las que dejan el BOM en el texto
    las arregla ``split_bom``.
    """
    name = normalize_encoding(encoding)
    if name == UTF8_BOM and not data.startswith(codecs.BOM_UTF8):
        return UTF8
    if name == UTF16_BE_BOM and not data.startswith(codecs.BOM_UTF16_BE):
        return UTF16_BE
    if name == UTF16 and not data.startswith(codecs.BOM_UTF16_LE):
        if data.startswith(codecs.BOM_UTF16_BE):
            return UTF16_BE_BOM
        return UTF16_LE if sys.byteorder == "little" else UTF16_BE
    return name


def split_extra_boms(text: str, encoding: str) -> tuple[str, int]:
    """(texto, n) sin los ``n`` U+FEFF iniciales que deja un BOM repetido tras el de ``encoding``.

    Solo con las de ``BOM_ENCODINGS``, que los pueden volver a escribir:
    ``encode_text(BOM * n + texto, encoding)`` da los mismos bytes. Con las demás
    un U+FEFF inicial es contenido y ``n`` es 0.
    """
    if normalize_encoding(encoding) not in BOM_ENCODINGS:
        return text, 0
    body = text.lstrip(BOM)
    return body, len(text) - len(body)


def _decode(data: bytes, name: str, partial: bool) -> str:
    errors = _ERROR_HANDLER if name == GAME_ENCODING else "strict"
    if partial:
        return codecs.getincrementaldecoder(name)(errors).decode(data, final=False)
    return data.decode(name, errors)


def _utf16_without_bom(data: bytes, partial: bool) -> str | None:
    """Codificación UTF-16 de ``data`` sin BOM por la proporción de NUL alternos, o ``None``."""
    if len(data) < 4 or (len(data) % 2 and not partial):
        return None
    sample = data[:_UTF16_SAMPLE]
    pairs = len(sample) // 2
    even, odd = sample[0:pairs * 2:2].count(0), sample[1:pairs * 2:2].count(0)
    for name, high, low in ((UTF16_LE, odd, even), (UTF16_BE, even, odd)):
        if high >= pairs * _UTF16_MIN_NUL and low <= pairs * _UTF16_MAX_NUL_LOW:
            try:
                _decode(data, name, partial)
            except UnicodeDecodeError:
                return None
            return name
    return None


def decode_bytes(data: bytes, encoding: str | None = None, *, partial: bool = False) -> DecodedText:
    """Decodifica bytes de un archivo del juego; sin ``encoding``, la detecta (ver el docstring del módulo).

    Nunca falla al detectar. Con ``partial`` los bytes son solo el principio de un
    archivo (una vista previa): una secuencia multibyte cortada al final se
    descarta en vez de cambiar la detección, así que el texto no vuelve a dar
    exactamente esos bytes.
    """
    if encoding is not None:
        name = normalize_encoding(encoding)
        return DecodedText(_decode(data, name, partial), name)
    if data.startswith(codecs.BOM_UTF16_LE):
        try:
            return DecodedText(_decode(data[2:], UTF16_LE, partial), UTF16)
        except UnicodeDecodeError:
            pass
    elif data.startswith(codecs.BOM_UTF16_BE):
        try:
            return DecodedText(_decode(data[2:], UTF16_BE, partial), UTF16_BE_BOM)
        except UnicodeDecodeError:
            pass
    elif data.startswith(codecs.BOM_UTF8):
        try:
            return DecodedText(_decode(data, UTF8_BOM, partial), UTF8_BOM)
        except UnicodeDecodeError:
            pass  # BOM seguido de cp1252: el BOM queda en el texto como STRAY_BOM
    elif not data.isascii():
        try:
            text = _decode(data, UTF8, partial)
        except UnicodeDecodeError:
            pass
        else:
            # Si solo el final cortado no era ASCII, no hay pruebas de UTF-8 (puede ser un "é" cp1252).
            if not text.isascii():
                return DecodedText(text, UTF8)
    if 0 in data:
        utf16 = _utf16_without_bom(data, partial)
        if utf16 is not None:
            return DecodedText(_decode(data, utf16, partial), utf16)
    return DecodedText(_decode(data, GAME_ENCODING, partial), GAME_ENCODING)


def _encoder(name: str):
    if name == GAME_ENCODING:
        return lambda text: text.encode(GAME_ENCODING, _ERROR_HANDLER)
    if name == UTF16:
        # Siempre little-endian con BOM, como en Windows, sea cual sea el orden de esta máquina.
        return lambda text: codecs.BOM_UTF16_LE + text.encode(UTF16_LE)
    return lambda text: text.encode(name)


def line_breaks(text: str, start: int = 0, end: int | None = None) -> int:
    """Número de saltos de línea (``\\r\\n``, ``\\n`` o ``\\r`` suelto) en ``text[start:end]``."""
    stop = len(text) if end is None else end
    return text.count("\n", start, stop) + text.count("\r", start, stop) - text.count("\r\n", start, stop)


def count_lines(text: str) -> int:
    """Número de líneas de ``text`` contando ``\\r\\n``, ``\\n`` y ``\\r`` suelto (0 si está vacío)."""
    if not text:
        return 0
    return line_breaks(text) + (0 if text.endswith(("\n", "\r")) else 1)


def find_unencodable(text: str, encoding: str = GAME_ENCODING) -> list[tuple[int, int, int, str]]:
    """Devuelve (índice, línea, columna, carácter) de cada carácter no codificable."""
    name = normalize_encoding(encoding)
    indices: list[int] = []
    previous = getattr(_COLLECT_TLS, "state", None)
    _COLLECT_TLS.state = (indices, name == GAME_ENCODING)
    try:
        text.encode(name, _COLLECT_HANDLER)
    finally:
        _COLLECT_TLS.state = previous
    if not indices:
        return []
    problems: list[tuple[int, int, int, str]] = []
    line, prev_start = 1, 0
    for index in indices:
        lf = text.rfind("\n", prev_start, index)
        last_break = max(lf, text.rfind("\r", prev_start if lf < 0 else lf + 1, index))
        if last_break >= 0:
            start = last_break + 1
            line += line_breaks(text, prev_start, start)
            prev_start = start
        problems.append((index, line, index - prev_start + 1, text[index]))
    return problems


def encode_text(text: str, encoding: str = GAME_ENCODING) -> bytes:
    """Codifica texto; lanza ``UnencodableTextError`` con posiciones si no es posible."""
    name = normalize_encoding(encoding)
    try:
        return _encoder(name)(text)
    except UnicodeEncodeError:
        raise UnencodableTextError(name, find_unencodable(text, name)) from None


def detect_newline(text: str, *, lone_cr: bool = True) -> str:
    """Salto de línea predominante: ``"\\r\\n"``, ``"\\n"`` o ``"\\r"``; sin saltos, ``"\\n"``.

    Solo CR es el salto de algunos archivos vanilla (``map/region_sea.txt``). Con
    ``lone_cr=False`` un CR suelto no cuenta como salto (el CSV del juego solo
    parte las filas en LF) y el resultado es ``"\\r\\n"`` o ``"\\n"``.
    """
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    if lone_cr:
        cr = text.count("\r") - crlf
        if cr > crlf and cr > lf:
            return "\r"
    return "\r\n" if crlf > lf else "\n"
