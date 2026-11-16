"""POPs por provincia y fecha: ``PopsIndex`` y su edición (wizard §14.3). Contrato de la iteración 5.

``history/pops/<fecha>/<Zona>.txt`` trae bloques ``<id> = { <tipo> = { culture religion size [militancy]
[rebel_type] } … }``. Hechos de vanilla (medidos): 2 carpetas (``1836.1.1`` y ``1861.4.14``, que **no** es la fecha
del segundo bookmark, ``1861.7.1``), 179 archivos en cada una, sin subcarpetas y todos con CRLF; 2 703 y 2 704
bloques para 2 703 provincias; ninguna provincia está en dos archivos de la misma fecha, y una sola tiene dos
bloques en el mismo archivo (2482, en ``1861.4.14/Australia.txt``). Dentro de un bloque el mismo tipo de POP se
repite a menudo (7 713 veces en 1836): un POP se identifica por su posición, no por su tipo.

De ahí el modelo:

- Un **bloque** es ``PopBlockRef``: carpeta de fecha, archivo, provincia y número de aparición en ese archivo. Su
  id de registro (esquema ``pops``) es ``"<fecha>:<provincia>"``, el nombre del símbolo ``pop_block`` del índice;
  la aparición n-ésima (n ≥ 2) añade ``#n``. Así los dos bloques de 2482 son dos registros y se edita el elegido.
- La carpeta que vale para una fecha de trabajo es la última con fecha ≤ ella (``folder_for``): con el bookmark
  de 1861.7.1 se usan los POPs de ``1861.4.14``. Qué carpeta usa el juego es [verificar en juego]; si no hay
  ninguna ≤ la fecha, no hay POPs (``bookmark_without_pops``).
- Los bloques repetidos se muestran todos y la población los **suma**; si el juego los suma o se queda con uno
  es [verificar en juego] (§23).
- Se edita el bloque en el archivo que lo define: al guardar se copia ese archivo de zona entero al mod, a la
  misma ruta (``UNION_BY_PATH``). Una provincia sin bloque en la carpeta recibe uno nuevo en
  ``history/pops/<carpeta>/00_<P>_pops.txt`` (``target_for_new``).

``PopsIndex`` es una vista del índice de símbolos (no abre archivos; se puede usar con una copia del índice en un
hilo de tarea). ``ProvincePops`` lee y edita sobre ``Entities``; sus ediciones van dentro de la transacción de
quien llama (I5) y cambian solo el POP tocado (I3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..clausewitz.nodes import ClausewitzDate
from ..schema.fields import MISSING
from ..vfs.paths import VPath

if TYPE_CHECKING:
    from ..schema.record import Entities

POPS_FOLDER = "history/pops"
NEW_FILE = "00_{prefix}_pops.txt"    # archivo del mod para los bloques de provincias sin POPs
OCCURRENCE_MARK = "#"
POP_FIELDS = ("culture", "religion", "size", "militancy", "rebel_type")


def pop_ident(folder: ClausewitzDate | str, province: int, occurrence: int = 0) -> str:
    """Id del registro de un bloque: ``"1836.1.1:549"``; la segunda aparición en su archivo, ``"…:549#2"``."""
    base = f"{folder}:{int(province)}"
    return base if occurrence <= 0 else f"{base}{OCCURRENCE_MARK}{occurrence + 1}"


def parse_pop_ident(ident: str) -> tuple[str, int, int]:
    """``(carpeta, provincia, aparición)`` de un id de ``pop_ident``; ``ValueError`` si no tiene esa forma."""
    folder, sep, rest = ident.partition(":")
    number, mark, nth = rest.partition(OCCURRENCE_MARK)
    if not sep or not folder or not number.isdigit() or (mark and not nth.isdigit()) or (mark and int(nth) < 2):
        raise ValueError(f"id de bloque de POP no válido: {ident!r}")
    return folder, int(number), int(nth) - 1 if mark else 0


@dataclass(frozen=True)
class PopBlockRef:
    """Un bloque ``<provincia> = { … }`` concreto. ``occurrence`` cuenta desde 0 dentro de ``rel``."""

    folder: ClausewitzDate
    rel: VPath
    province: int
    occurrence: int = 0
    line: int | None = None

    @property
    def ident(self) -> str:
        return pop_ident(self.folder, self.province, self.occurrence)


@dataclass(frozen=True)
class Pop:
    """Un POP de un bloque. ``index`` es su posición entre los POPs del bloque (desde 0)."""

    index: int
    type: str
    culture: str
    religion: str
    size: int
    militancy: float | None = None
    rebel_type: str | None = None


class PopsIndex:
    """Qué archivo y qué bloque definen los POPs de cada provincia en cada fecha, con los repetidos."""

    def __init__(self, index) -> None:
        """``index``: el ``SymbolIndex`` (vivo o una copia). Lee los símbolos ``pop_block``."""
        self.index = index

    def folders(self) -> list[ClausewitzDate]:
        """Las carpetas de fecha con algún bloque, de menor a mayor. Una carpeta cuyo nombre no es una fecha no
        cuenta."""
        raise NotImplementedError

    def folder_for(self, date: ClausewitzDate) -> ClausewitzDate | None:
        """La última carpeta con fecha ≤ ``date``; None si no hay ninguna."""
        raise NotImplementedError

    def blocks(self, pid: int, date: ClausewitzDate, *, exact: bool = False) -> list[PopBlockRef]:
        """Los bloques de ``pid`` en la carpeta de ``date`` (``folder_for``; con ``exact``, solo si la carpeta
        es exactamente ``date``), por archivo (``rel.key``) y aparición. Vacía si no tiene."""
        raise NotImplementedError

    def provinces(self, date: ClausewitzDate) -> list[int]:
        """Ids con algún bloque en la carpeta de ``date``, ordenados."""
        raise NotImplementedError

    def repeated(self, date: ClausewitzDate | None = None) -> list[tuple[PopBlockRef, ...]]:
        """Los grupos de bloques de una misma provincia y carpeta que son más de uno (en un archivo o en
        varios); con ``date``, solo los de su carpeta. Vanilla: uno, el de 2482."""
        raise NotImplementedError

    def target_for_new(self, pid: int, date: ClausewitzDate, prefix: str) -> VPath:
        """Archivo donde crear el bloque de una provincia sin POPs:
        ``history/pops/<folder_for(date) o date>/00_<prefix>_pops.txt``."""
        raise NotImplementedError


class ProvincePops:
    """Lectura y edición de los POPs de un bloque sobre ``Entities`` (hilo de la interfaz)."""

    def __init__(self, entities: Entities, pops_index: PopsIndex | None = None) -> None:
        self.entities = entities
        self.pops_index = pops_index if pops_index is not None else PopsIndex(entities.index)

    def read(self, ref: PopBlockRef) -> list[Pop]:
        """Los POPs del bloque en orden de archivo. ``KeyError`` si el bloque ya no está. No escribe."""
        raise NotImplementedError

    def total(self, pid: int, date: ClausewitzDate) -> int:
        """Suma de ``size`` de todos los bloques de ``pid`` en la carpeta de ``date`` (repetidos incluidos)."""
        raise NotImplementedError

    def set(self, ref: PopBlockRef, index: int, *, type: str | None = None, culture: str | None = None,
            religion: str | None = None, size: int | None = None, militancy: object = MISSING,
            rebel_type: object = MISSING) -> None:
        """Cambia los datos indicados del POP ``index`` (None = no tocar; ``militancy`` y ``rebel_type`` admiten
        None para quitar la clave). Cambiar el tipo cambia solo la clave del POP."""
        raise NotImplementedError

    def add(self, ref: PopBlockRef, pop: Pop) -> int:
        """Añade un POP al final del bloque y devuelve su posición (``pop.index`` se ignora)."""
        raise NotImplementedError

    def remove(self, ref: PopBlockRef, index: int) -> None:
        raise NotImplementedError

    def create_block(self, pid: int, date: ClausewitzDate) -> PopBlockRef:
        """Bloque vacío para una provincia sin POPs en la carpeta de ``date``, en ``target_for_new`` (crea el
        archivo si hace falta). ``ValueError`` si ya tiene alguno."""
        raise NotImplementedError

    def copy_from(self, target: PopBlockRef, source: PopBlockRef) -> None:
        """«Copiar POPs de la provincia…»: sustituye los POPs de ``target`` por una copia de los de
        ``source`` (con su formato)."""
        raise NotImplementedError

    def scale(self, ref: PopBlockRef, factor: float) -> None:
        """«Escalar ×»: multiplica cada ``size`` por ``factor`` y redondea al entero más cercano (mínimo 1).
        ``ValueError`` si ``factor`` ≤ 0."""
        raise NotImplementedError
