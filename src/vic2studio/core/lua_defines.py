"""``defines.lua`` sin pérdidas: leer y cambiar ``CLAVE = valor,`` conservando todo lo demás (wizard §4.1, H20).

El juego solo lee asignaciones simples dentro de tablas (``defines = { start_date =
'1836.1.1', … }``). Este editor no interpreta Lua: localiza cada ``clave = valor``
con su posición, y ``set`` sustituye solo el texto del valor, así que comentarios
(``--``), espacios, comillas (``'``/``"``), saltos de línea y codificación quedan
igual (I3). ``to_bytes(from_bytes(b)) == b`` para cualquier entrada.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LuaValue:
    key: str
    raw: str                    # el valor tal cual (``'1836.1.1'``, ``0.25``, ``yes``)
    line: int                   # desde 1
    table: str | None           # tabla que lo contiene (``country``, ``economy``…) o None en la raíz

    @property
    def text(self) -> str:
        """``raw`` sin comillas si las lleva."""
        raise NotImplementedError


class LuaDefines:
    @classmethod
    def from_bytes(cls, data: bytes) -> LuaDefines:
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        raise NotImplementedError

    def values(self) -> list[LuaValue]:
        raise NotImplementedError

    def get(self, key: str, *, table: str | None = None) -> LuaValue | None:
        """Primera asignación de ``key`` (en ``table`` si se da); sin distinguir mayúsculas."""
        raise NotImplementedError

    def set(self, key: str, raw: str, *, table: str | None = None) -> None:
        """Cambia el valor de ``key`` por ``raw`` (con sus comillas si las quiere); ``KeyError`` si no existe."""
        raise NotImplementedError
