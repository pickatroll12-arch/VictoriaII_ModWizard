"""``defines.lua`` sin pérdidas: leer y cambiar ``CLAVE = valor,`` conservando todo lo demás (wizard §4.1, H20).

El juego solo lee asignaciones simples dentro de tablas (``defines = { start_date =
'1836.1.1', … }``). Este editor no interpreta Lua: localiza cada ``clave = valor``
con su posición, y ``set`` sustituye solo el texto del valor, así que comentarios
(``--``), espacios, comillas (``'``/``"``), saltos de línea y codificación quedan
igual (I3). ``to_bytes(from_bytes(b)) == b`` para cualquier entrada.

Se trabaja sobre los bytes: los tokens (nombres, números, cadenas, ``=``, ``{``,
``}``, ``,``) son ASCII, así que se buscan en el texto leído como latin-1, que
es biyectivo; el valor se decodifica con la codificación detectada del archivo
(``encoding.decode_bytes``) y ``set`` codifica el nuevo con esa misma.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .encoding import GAME_ENCODING, UTF8, UTF8_BOM, decode_bytes, encode_text

# Un token: comentario de bloque, comentario de línea, cadena, nombre, número o signo.
_TOKEN_RE = re.compile(
    r"""--\[(?P<level>=*)\[.*?\](?P=level)\]   # comentario de bloque --[[ … ]]
      | --[^\r\n]*                             # comentario de línea
      | (?P<string>'(?:\\.|[^'\\\r\n])*'?|"(?:\\.|[^"\\\r\n])*"?)
      | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
      | (?P<number>-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
      | (?P<sign>[={},;])
      | (?P<space>\s+)
      | (?P<other>.)
    """,
    re.VERBOSE | re.DOTALL,
)
_LINE_BREAK_RE = re.compile(r"\r\n?|\n")


@dataclass(frozen=True)
class LuaValue:
    key: str
    raw: str                    # el valor tal cual (``'1836.1.1'``, ``0.25``, ``yes``)
    line: int                   # desde 1
    table: str | None           # tabla que lo contiene (``country``, ``economy``…) o None en la raíz

    @property
    def text(self) -> str:
        """``raw`` sin comillas si las lleva."""
        raw = self.raw
        if len(raw) >= 2 and raw[0] in "'\"" and raw[-1] == raw[0]:
            return raw[1:-1]
        return raw


@dataclass(frozen=True)
class _Slot:
    value: LuaValue
    start: int                  # posición en bytes del valor
    end: int


class LuaDefines:
    """Las asignaciones de un ``defines.lua`` y sus posiciones; ``set`` reescribe solo el valor."""

    def __init__(self, data: bytes = b"") -> None:
        self._data = bytes(data)
        self._encoding = decode_bytes(self._data).encoding if self._data else GAME_ENCODING
        self._slots = self._scan()

    @classmethod
    def from_bytes(cls, data: bytes) -> LuaDefines:
        return cls(data)

    def to_bytes(self) -> bytes:
        return self._data

    @property
    def encoding(self) -> str:
        return self._encoding

    def values(self) -> list[LuaValue]:
        return [slot.value for slot in self._slots]

    def _find(self, key: str, table: str | None) -> _Slot | None:
        wanted = key.casefold()
        for slot in self._slots:
            value = slot.value
            if value.key.casefold() == wanted and (table is None or (value.table or "").casefold() == table.casefold()):
                return slot
        return None

    def get(self, key: str, *, table: str | None = None) -> LuaValue | None:
        """Primera asignación de ``key`` (en ``table`` si se da); sin distinguir mayúsculas."""
        slot = self._find(key, table)
        return None if slot is None else slot.value

    def set(self, key: str, raw: str, *, table: str | None = None) -> None:
        """Cambia el valor de ``key`` por ``raw`` (con sus comillas si las quiere); ``KeyError`` si no existe.

        ``raw`` no puede tener saltos de línea (``ValueError``); si no cabe en la codificación del archivo
        lanza ``encoding.UnencodableTextError`` sin cambiar nada.
        """
        slot = self._find(key, table)
        if slot is None:
            raise KeyError(key)
        if "\r" in raw or "\n" in raw:
            raise ValueError("un valor de defines.lua no puede tener saltos de línea")
        new = encode_text(raw, UTF8 if self._encoding == UTF8_BOM else self._encoding)   # el BOM va solo al principio
        self._data = self._data[:slot.start] + new + self._data[slot.end:]
        self._slots = self._scan()

    # --- análisis --------------------------------------------------------------------------------

    def _decode(self, chunk: bytes) -> str:
        encoding = UTF8 if self._encoding == UTF8_BOM else self._encoding
        try:
            return decode_bytes(chunk, encoding).text
        except (UnicodeDecodeError, LookupError):
            return chunk.decode("latin-1")

    def _scan(self) -> list[_Slot]:
        text = self._data.decode("latin-1")
        slots: list[_Slot] = []
        tables: list[str | None] = []      # pila de tablas abiertas (None: tabla sin nombre)
        pending: str | None = None         # nombre seguido de «=» que espera su valor
        last_name: str | None = None
        expect_value = False
        line = 1
        for match in _TOKEN_RE.finditer(text):
            kind = match.lastgroup
            token = match.group()
            start_line = line
            line += len(_LINE_BREAK_RE.findall(token))
            if kind in (None, "level", "space"):      # comentario (sin grupo con nombre, o el de bloque) o espacio
                continue
            if kind == "name":
                if expect_value and pending is not None:
                    slots.append(self._slot(pending, match, start_line, tables))
                    pending, expect_value, last_name = None, False, None
                    continue
                last_name = token
                pending, expect_value = None, False
                continue
            if kind in ("string", "number"):
                if expect_value and pending is not None:
                    slots.append(self._slot(pending, match, start_line, tables))
                pending, expect_value, last_name = None, False, None
                continue
            if kind == "sign":
                if token == "=":
                    pending, expect_value = last_name, last_name is not None
                    last_name = None
                elif token == "{":
                    tables.append(pending if expect_value else None)
                    pending, expect_value, last_name = None, False, None
                elif token == "}":
                    if tables:
                        tables.pop()
                    pending, expect_value, last_name = None, False, None
                else:
                    pending, expect_value, last_name = None, False, None
                continue
            pending, expect_value, last_name = None, False, None
        return slots

    def _slot(self, key: str, match: re.Match, line: int, tables: list[str | None]) -> _Slot:
        start, end = match.span()
        table = next((name for name in reversed(tables) if name is not None), None)
        raw = self._decode(self._data[start:end])
        return _Slot(LuaValue(key, raw, line, table), start, end)
