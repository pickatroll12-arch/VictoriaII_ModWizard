"""``SymbolIndex``: qué existe en la vista efectiva (juego + dependencias + mod + cambios sin guardar), wizard §7.

Se construye con ``builder.build_index`` a partir de ``FileFacts`` y se mantiene
con ``apply`` (incremental: un archivo cambiado sustituye sus hechos). Combina
según las reglas de carga (§5.2):

- ``WHOLE_FILE`` (``common/*.txt``, ``map/*``…): solo cuentan los hechos del
  archivo ganador de esa ruta; los de las capas que pierden se conservan para el
  explicador (``lookup`` los devuelve después del efectivo).
- ``UNION_BY_PATH`` y ``KEYED_UNION`` (eventos, decisiones, historias): cuentan
  todos los ganadores de cada ruta; dos definiciones del mismo nombre en rutas
  distintas son un duplicado (``lookup`` da más de una).
- ``LOCALISATION``: gana la primera clave por orden de carga de los archivos
  (``csvloc.db.load_order_key``), como ``LocalisationDB``.
- Un archivo del juego oculto por ``replace_path`` no aporta nada.

Python puro y de solo lectura para quien consulta; ``apply`` lo llama un solo
hilo (el de la interfaz). Las consultas no leen disco.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable

from ..vfs.paths import VPath
from .model import FileFacts, Symbol, SymbolRef


class SymbolIndex:
    """Índice consultable. ``generation`` sube con cada ``apply`` (las vistas lo comparan para refrescar)."""

    generation: int = 0

    def __init__(self, facts: Iterable[FileFacts] = (), *, snapshot=None) -> None:
        """``snapshot`` (``VfsSnapshot``) da el orden de capas y qué está oculto por ``replace_path``; sin él,
        todos los hechos cuentan como ganadores (pruebas con un índice en memoria)."""
        raise NotImplementedError

    # --- consultas ---------------------------------------------------------------------------------

    def kinds(self) -> list[str]:
        """Tipos con al menos una definición efectiva, ordenados."""
        raise NotImplementedError

    def names(self, kind: str) -> list[str]:
        """Nombres efectivos de ``kind``, en orden de definición (archivo y línea)."""
        raise NotImplementedError

    def count(self, kind: str) -> int:
        raise NotImplementedError

    def get(self, kind: str, name: str) -> Symbol | None:
        """Definición efectiva (la que usa el juego) o None."""
        raise NotImplementedError

    def lookup(self, kind: str, name: str) -> list[Symbol]:
        """Todas las definiciones, la efectiva primero; más de una = duplicado o capas que pierden."""
        raise NotImplementedError

    def exists(self, kind: str, name: str, *, ignore_case: bool = False) -> bool:
        raise NotImplementedError

    def attrs(self, kind: str, name: str, attr: str, default=None) -> object:
        raise NotImplementedError

    def symbols(self, kind: str) -> list[Symbol]:
        """Definiciones efectivas de ``kind`` (como ``names``, con todo)."""
        raise NotImplementedError

    def defs_in(self, rel: VPath) -> list[Symbol]:
        """Definiciones que aporta el archivo ganador de ``rel``."""
        raise NotImplementedError

    def refs_to(self, kind: str, name: str) -> list[SymbolRef]:
        """Usos de ``kind``/``name`` en la vista efectiva («dónde se usa»)."""
        raise NotImplementedError

    def refs_from(self, rel: VPath) -> list[SymbolRef]:
        raise NotImplementedError

    def refs(self, kind: str) -> list[SymbolRef]:
        """Todos los usos de ``kind`` (las reglas ``*_unknown`` los recorren)."""
        raise NotImplementedError

    def search(self, text: str, *, kinds: Collection[str] = (), loc=None, lang: str = "es",
               limit: int = 50) -> list[Symbol]:
        """Buscador universal (Ctrl+K): por id o nombre («549», «PRU», «north_german») y, con ``loc``
        (``LocalisationDB``), por nombre localizado sin mayúsculas ni acentos («Berlín», «berlin»). Primero
        las coincidencias exactas, luego las que empiezan por ``text`` y luego las que lo contienen."""
        raise NotImplementedError

    def display(self, kind: str, name: str, loc=None, lang: str = "es") -> str:
        """Nombre para mostrar: «Prusia (PRU)», «549 Berlín»; sin ``loc`` o sin texto, ``name``."""
        raise NotImplementedError

    # --- mantenimiento ------------------------------------------------------------------------------

    def apply(self, facts: Iterable[FileFacts], removed: Iterable[tuple[VPath, object]] = (), *,
              snapshot=None) -> None:
        """Sustituye los hechos de cada ``(rel, capa)`` de ``facts`` y quita los de ``removed`` (pares
        ``(rel, LayerKind)``). ``snapshot`` actualiza el orden de capas (un archivo nuevo del mod puede ganar
        ahora). Sube ``generation``."""
        raise NotImplementedError

    def facts(self) -> list[FileFacts]:
        """Todos los hechos que contiene (para la caché y las pruebas)."""
        raise NotImplementedError
