"""Historia fechada (wizard §10.6). Contrato: ni ``government`` ni ``unit`` la necesitan; la implementa la
iteración 5 con la historia de provincias.

Un archivo de historia tiene entradas **sin fecha** (el estado en la fecha de inicio) y **bloques fechados**
``1861.1.1 = { … }`` con lo que cambia ese día. Hechos de las 2 705 historias de provincia de vanilla (medidos):
1 923 no tienen bloques, 645 tienen uno, 132 dos y 5 tres; **137 tienen dos bloques con la misma fecha** (549
tiene dos ``1861.1.1``); ninguna tiene una entrada sin fecha detrás de un bloque fechado. Los bookmarks son
1836.1.1 y 1861.7.1.

**Lectura en la fecha D.** Primero las entradas sin fecha, en orden de archivo; después los bloques con fecha
≤ D, por fecha; dos bloques con la misma fecha cuentan en orden de archivo. El valor vigente de una clave es el
de la última entrada en ese orden. ``D = None`` lee solo lo que no tiene fecha.

**Fecha de inicio.** La menor de ``bookmarks``. Sin bookmarks, o con ``D`` None o ≤ la de inicio, se está «en el
inicio».

**Escritura en la fecha D.** Tras escribir, ``get`` devuelve lo escrito (si no, la edición no se vería):

- En el inicio: se escribe la entrada sin fecha (si ya existe, se cambia su valor; si no, se coloca según §10.7,
  nunca detrás del primer bloque fechado). Si el valor vigente lo pone un bloque fechado ≤ D, se cambia esa
  entrada del bloque.
- Después del inicio: el destino es, de los bloques con fecha en el intervalo **(bookmark anterior, D]**, el de
  mayor fecha y, a igualdad, el último del archivo (``write_target``). El bookmark anterior es el mayor
  estrictamente menor que D. Si no hay ninguno, se crea ``D = { }`` en su sitio cronológico: detrás del último
  bloque con fecha ≤ D y delante del primero con fecha mayor. Dentro del bloque, la clave se cambia si está y se
  añade si no. Así, editar 549 en 1861.7.1 escribe en su segundo ``1861.1.1`` y no crea otro bloque (criterio
  5): ningún bookmark cae entre el bloque y D, así que ninguna fecha de inicio ve un cambio que no pidió.

**Acumulativos** (``Field.accumulate``: ``add_core``/``remove_core``). ``get_set`` aplica las altas y bajas en
orden de lectura. ``add`` en el inicio añade ``add_core`` sin fecha; después, lo añade en el bloque destino (o
quita de él un ``remove_core`` del mismo valor). ``remove`` en el inicio borra los ``add_core`` sin fecha de ese
valor; después, borra el ``add_core`` del bloque destino si está y, si el valor sigue vigente, escribe
``remove_core``. Ninguna de las dos hace nada si el conjunto ya está como se pide.

**Modo LOG** (guerras, iteración 6): cada bloque fechado es un suceso con su propio subformulario.

Toda escritura llama antes a ``ws.touch`` a través del ``Record`` (exige la transacción de quien llama) y edita el
árbol sin regenerar bloques (I3).
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


def start_date(bookmarks: Sequence[ClausewitzDate]) -> ClausewitzDate | None:
    """La fecha de inicio: la menor de ``bookmarks``; None si no hay."""
    raise NotImplementedError


def previous_bookmark(date: ClausewitzDate, bookmarks: Sequence[ClausewitzDate]) -> ClausewitzDate | None:
    """El mayor bookmark estrictamente anterior a ``date``; None si no hay."""
    raise NotImplementedError


def read_order(dates: Sequence[ClausewitzDate], date: ClausewitzDate | None) -> list[int]:
    """Índices de los bloques fechados que cuentan en ``date`` (fecha ≤ ``date``), en orden de lectura: por
    fecha y, a igualdad, por posición. ``dates`` son las fechas de los bloques en orden de archivo. Con
    ``date`` None, ninguno. La comparten ``HistoryView`` y ``ProvinceFacts.build``."""
    raise NotImplementedError


def write_target(dates: Sequence[ClausewitzDate], date: ClausewitzDate,
                 bookmarks: Sequence[ClausewitzDate]) -> int | None:
    """Índice del bloque fechado donde se escribe en ``date`` (ver el módulo): el de mayor fecha del intervalo
    (bookmark anterior, ``date``], el último del archivo a igualdad; None si hay que crear uno."""
    raise NotImplementedError


class HistoryView:
    """Vista de un registro en una fecha de trabajo, con ``bookmarks`` para los intervalos."""

    def __init__(self, record: Record, date: ClausewitzDate | None,
                 bookmarks: Sequence[ClausewitzDate]) -> None:
        self.record = record
        self.date = date
        self.bookmarks = bookmarks

    def at_start(self) -> bool:
        """True si ``date`` es la fecha de inicio, anterior a ella o None (se escribe sin fecha)."""
        raise NotImplementedError

    def get(self, key: str) -> Effective:
        """Valor vigente de ``key`` en la fecha, leído con el tipo de su campo;
        ``Effective(MISSING, None, None)`` si ninguna entrada lo pone."""
        raise NotImplementedError

    def get_set(self, key: str) -> list[Effective]:
        """Valores acumulativos (``add_core``/``remove_core``) vigentes, en el orden en que entraron; ``key``
        es la clave del campo (``"add_core"``)."""
        raise NotImplementedError

    def set(self, key: str, value: object) -> Entry | None:
        """Escribe ``key`` en el destino que corresponde a la fecha (ver el módulo) y devuelve la entrada.
        ``None`` o ``MISSING`` quitan la clave del destino (devuelve None). Si ya valía eso, no cambia nada."""
        raise NotImplementedError

    def add(self, key: str, value: object) -> Entry | None:
        """Añade un valor acumulativo; None si ya estaba vigente (no cambia nada)."""
        raise NotImplementedError

    def remove(self, key: str, value: object) -> None:
        """Quita un valor acumulativo (no hace nada si no estaba vigente)."""
        raise NotImplementedError

    def dated_blocks(self) -> list[tuple[ClausewitzDate, Block]]:
        """Bloques fechados del registro, por fecha (orden de archivo en empates)."""
        raise NotImplementedError

    def target_block(self, *, create: bool = False) -> Block | None:
        """El bloque donde escribiría ``set`` en esta fecha: la raíz del registro en el inicio; si no, el
        bloque fechado destino. Con ``create`` lo crea si falta (exige transacción); sin él, None."""
        raise NotImplementedError
