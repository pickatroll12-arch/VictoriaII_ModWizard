"""Historia fechada (wizard §10.6). Contrato: ni ``government`` ni ``unit`` la necesitan.

Lectura en la fecha D: primero las entradas sin fecha en orden de archivo;
después los bloques con fecha ≤ D, por fecha (dos bloques con la misma fecha
cuentan en orden de archivo). Escritura en la fecha D: si D es la fecha de
inicio (o None), se escribe la entrada sin fecha; si no, el destino es el
último bloque fechado existente con fecha en el intervalo (bookmark anterior,
D]; si no hay ninguno, se crea ``D = { }`` en su posición cronológica. Modo
LOG (guerras): cada bloque fechado es un suceso con su propio subformulario.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..clausewitz.nodes import Block, ClausewitzDate, Entry
    from .record import Record


@dataclass(frozen=True)
class Effective:
    """Valor vigente de una clave en una fecha: ``entry`` es la entrada dueña y ``date`` su
    bloque fechado (None = sin fecha)."""

    value: object
    entry: Entry | None
    date: ClausewitzDate | None


class HistoryView:
    """Vista de un registro en una fecha de trabajo, con ``bookmarks`` para los intervalos."""

    def __init__(self, record: Record, date: ClausewitzDate | None,
                 bookmarks: Sequence[ClausewitzDate]) -> None:
        self.record = record
        self.date = date
        self.bookmarks = bookmarks

    def get(self, key: str) -> Effective:
        """Valor vigente de ``key`` en la fecha."""
        raise NotImplementedError

    def get_set(self, key: str) -> list[Effective]:
        """Valores acumulativos (``add_core``/``remove_core``) en orden."""
        raise NotImplementedError

    def set(self, key: str, value: object) -> Entry:
        """Escribe ``key`` en el bloque que corresponde a la fecha (§10.6)."""
        raise NotImplementedError

    def add(self, key: str, value: object) -> Entry:
        """Añade un valor acumulativo: tras el inicio escribe ``add_<key>`` en el bloque vigente."""
        raise NotImplementedError

    def remove(self, key: str, value: object) -> None:
        """Quita un valor acumulativo: tras el inicio escribe ``remove_<key>``; en el inicio,
        borra el ``add_<key>``."""
        raise NotImplementedError

    def dated_blocks(self) -> list[tuple[ClausewitzDate, Block]]:
        """Bloques fechados del registro, por fecha (orden de archivo en empates)."""
        raise NotImplementedError
