"""``LocSync``: editar la localización con la política del juego (wizard §8, D6).

Gana la primera clave cargada: los CSV se cargan por orden alfabético de nombre
(``csvloc.db.load_order_key``) y un CSV del mod sustituye al del juego con el mismo
nombre (la VFS ya lo resuelve). Al escribir un texto:

- **clave nueva** → fila en ``localisation/00_<P>_<área>.csv`` (``countries``,
  ``events``…); si ya hay un archivo del mod que sigue el patrón, se reutiliza;
- **clave cuyo ganador está en un archivo del mod** → se edita en su sitio
  (``LocRow.set``); en VSM, su copia de ``text.csv`` (diff de 1 línea);
- **clave cuyo ganador está en el juego** → fila en
  ``localisation/00_<P>_overrides.csv``, que carga antes que ``text.csv`` y gana.
  Nunca se copia el CSV del juego.

Formato de un archivo nuevo: imita a los del mod (cabecera ``key;English;…`` si
los del usuario la llevan, y su marcador ``x``); si no hay ninguno, el de vanilla
(clave, 13 idiomas y ``x``, cp1252 y CRLF). Un ``;`` o un salto de línea en un
texto se rechazan antes de escribir (``check_text``, ``InvalidFieldError``). Se
rellenan las columnas de ``languages``; ``copy_en_to`` copia el inglés a francés o
alemán. Todo son ediciones del ``Workspace`` dentro de la transacción de quien
llama: deshacibles con ella. Python puro, en el hilo del ``Workspace`` (I12).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .vfs.model import LayerKind
from .vfs.paths import VPath

AREA_OVERRIDES = "overrides"


@dataclass(frozen=True)
class LocEntry:
    """Una clave efectiva para la tabla de la sala Textos."""

    key: str
    texts: Mapping[str, str]            # idioma → texto efectivo («en», «fr», «de», «es»…)
    rel: VPath                          # archivo ganador
    line: int | None
    layer: LayerKind                    # capa del archivo ganador (MOD para un documento sin guardar)
    created_by_studio: bool             # está en un 00_<P>_<área>.csv del mod
    overrides_game: bool                # el juego también la define y el mod gana («sustituye a vanilla»)
    degraded: bool                      # difiere de la del juego solo por «?» en lugar de letras acentuadas (H15)


class LocSync:
    def __init__(self, ws, vfs, *, prefix: str, languages: Sequence[str] = ("en", "es"),
                 copy_en_to: Sequence[str] = ()) -> None:
        """``ws`` es el ``Workspace`` del proyecto y ``vfs`` su ``VirtualFS``."""
        raise NotImplementedError

    def text(self, key: str, lang: str = "es") -> str | None:
        """Texto efectivo (I7: con los cambios sin guardar)."""
        raise NotImplementedError

    def where(self, key: str) -> tuple[VPath, int] | None:
        """Archivo y línea ganadores."""
        raise NotImplementedError

    def entries(self) -> list[LocEntry]:
        """Todas las claves efectivas en orden de carga (para la tabla y sus filtros)."""
        raise NotImplementedError

    def target_file(self, area: str) -> VPath:
        """``localisation/00_<P>_<area>.csv`` (o el del mod que ya siga el patrón)."""
        raise NotImplementedError

    def set_text(self, key: str, lang: str, text: str, *, area: str = AREA_OVERRIDES) -> VPath:
        """Escribe ``text`` según la política; devuelve el archivo tocado. ``InvalidFieldError`` si no vale.
        Debe llamarse dentro de una transacción del ``Workspace``."""
        raise NotImplementedError

    def ensure(self, keys: Mapping[str, Mapping[str, str]], *, area: str) -> list[str]:
        """Crea las claves que falten (``clave → {idioma: texto}``); devuelve las creadas."""
        raise NotImplementedError

    def rename(self, old: str, new: str) -> None:
        """Renombra la clave en las filas del mod (nunca toca el juego)."""
        raise NotImplementedError

    def delete(self, key: str) -> None:
        """Quita las filas del mod; nunca borra del juego."""
        raise NotImplementedError

    def missing(self, keys: Iterable[str], langs: Sequence[str] = ("en", "es")) -> dict[str, list[str]]:
        """Clave → idiomas sin texto (o sin clave)."""
        raise NotImplementedError

    def orphans(self, index) -> list[str]:
        """Claves del mod que nada usa según el ``SymbolIndex`` (información)."""
        raise NotImplementedError

    def localisation_db(self):
        """``LocalisationDB`` efectiva: mod + juego + documentos sin guardar (modelos vivos del ``Workspace``)."""
        raise NotImplementedError
