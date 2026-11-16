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

from bisect import bisect_right
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..clausewitz.diagnostics import EditError
from ..clausewitz.nodes import Block, ClausewitzDate, Entry, Scalar
from .fields import MISSING

if TYPE_CHECKING:
    from collections.abc import Sequence

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
    return min(bookmarks) if bookmarks else None


def previous_bookmark(date: ClausewitzDate, bookmarks: Sequence[ClausewitzDate]) -> ClausewitzDate | None:
    """El mayor bookmark estrictamente anterior a ``date``; None si no hay."""
    earlier = [mark for mark in bookmarks if mark < date]
    return max(earlier) if earlier else None


def read_order(dates: Sequence[ClausewitzDate], date: ClausewitzDate | None) -> list[int]:
    """Índices de los bloques fechados que cuentan en ``date`` (fecha ≤ ``date``), en orden de lectura: por
    fecha y, a igualdad, por posición. ``dates`` son las fechas de los bloques en orden de archivo. Con
    ``date`` None, ninguno. La comparten ``HistoryView`` y ``ProvinceFacts.build``."""
    if date is None:
        return []
    return sorted((index for index, when in enumerate(dates) if when <= date), key=lambda index: (dates[index], index))


def write_target(dates: Sequence[ClausewitzDate], date: ClausewitzDate,
                 bookmarks: Sequence[ClausewitzDate]) -> int | None:
    """Índice del bloque fechado donde se escribe en ``date`` (ver el módulo): el de mayor fecha del intervalo
    (bookmark anterior, ``date``], el último del archivo a igualdad; None si hay que crear uno."""
    floor = previous_bookmark(date, bookmarks)
    best = None
    for index, when in enumerate(dates):
        if when > date or (floor is not None and when <= floor):
            continue
        if best is None or when >= dates[best]:
            best = index
    return best


def _date_of(entry: Entry) -> ClausewitzDate | None:
    if entry.key is None or not isinstance(entry.value, Block) or not entry.key.is_date():
        return None
    try:
        return entry.key.as_date()
    except ValueError:
        return None


class HistoryView:
    """Vista de un registro en una fecha de trabajo, con ``bookmarks`` para los intervalos."""

    def __init__(self, record: Record, date: ClausewitzDate | None,
                 bookmarks: Sequence[ClausewitzDate]) -> None:
        self.record = record
        self.date = date
        self.bookmarks = tuple(sorted(bookmarks))

    # --- estructura -------------------------------------------------------------------------------

    def _dated(self) -> list[tuple[ClausewitzDate, Entry]]:
        """``(fecha, entrada)`` de los bloques fechados en orden de archivo."""
        found = []
        for entry in self.record.block.entries:
            when = _date_of(entry)
            if when is not None:
                found.append((when, entry))
        return found

    def at_start(self) -> bool:
        """True si ``date`` es la fecha de inicio, anterior a ella o None (se escribe sin fecha)."""
        start = start_date(self.bookmarks)
        return self.date is None or start is None or self.date <= start

    def dated_blocks(self) -> list[tuple[ClausewitzDate, Block]]:
        """Bloques fechados del registro, por fecha (orden de archivo en empates)."""
        dated = self._dated()
        order = sorted(range(len(dated)), key=lambda index: (dated[index][0], index))
        return [(dated[index][0], dated[index][1].value) for index in order]

    def _layers(self) -> list[tuple[ClausewitzDate | None, Block]]:
        """Los bloques que cuentan en la fecha, en orden de lectura: la raíz (sin fecha) y los fechados ≤ D."""
        dated = self._dated()
        layers: list[tuple[ClausewitzDate | None, Block]] = [(None, self.record.block)]
        for index in read_order([when for when, _ in dated], self.date):
            layers.append((dated[index][0], dated[index][1].value))
        return layers

    # --- lectura ----------------------------------------------------------------------------------

    def _read(self, key: str, entry: Entry) -> object:
        field = self.record._field_of(key)
        value = entry.value
        if field is None:
            return value.text if isinstance(value, Scalar) else value
        try:
            return field.type.read(value)
        except (ValueError, EditError):
            return value.text if isinstance(value, Scalar) else value

    def _matches(self, entry: Entry, key: str) -> bool:
        return entry.key is not None and entry.key.text.lower() == key.lower() and _date_of(entry) is None

    def get(self, key: str) -> Effective:
        """Valor vigente de ``key`` en la fecha, leído con el tipo de su campo;
        ``Effective(MISSING, None, None)`` si ninguna entrada lo pone."""
        found = Effective(MISSING, None, None)
        for when, block in self._layers():
            for entry in block.entries:
                if self._matches(entry, key):
                    found = Effective(self._read(key, entry), entry, when)
        return found

    def _ops(self, key: str) -> tuple[str, str]:
        field = self.record._field_of(key)
        accumulate = getattr(field, "accumulate", None) if field is not None else None
        if accumulate is not None and hasattr(accumulate, "add"):
            return accumulate.add, accumulate.remove
        if key.startswith("add_"):
            return key, "remove_" + key[4:]
        return key, f"remove_{key}"

    def get_set(self, key: str) -> list[Effective]:
        """Valores acumulativos (``add_core``/``remove_core``) vigentes, en el orden en que entraron; ``key``
        es la clave del campo (``"add_core"``)."""
        add, remove = self._ops(key)
        current: dict[str, Effective] = {}
        for when, block in self._layers():
            for entry in block.entries:
                if entry.key is None or not isinstance(entry.value, Scalar):
                    continue
                lowered = entry.key.text.lower()
                text = entry.value.text
                if lowered == add.lower():
                    current.pop(text.upper(), None)
                    current[text.upper()] = Effective(self._read(key, entry), entry, when)
                elif lowered == remove.lower():
                    current.pop(text.upper(), None)
        return list(current.values())

    # --- escritura --------------------------------------------------------------------------------

    def target_block(self, *, create: bool = False) -> Block | None:
        """El bloque donde escribiría ``set`` en esta fecha: la raíz del registro en el inicio; si no, el
        bloque fechado destino. Con ``create`` lo crea si falta (exige transacción); sin él, None."""
        if self.at_start():
            return self.record.block
        dated = self._dated()
        index = write_target([when for when, _ in dated], self.date, self.bookmarks)
        if index is not None:
            return dated[index][1].value
        if not create:
            return None
        self.record._touch()
        dated = self._dated()     # tras ``touch`` el bloque puede ser otro (copia revivida)
        block = self.record.block
        position = len(block.entries)
        after = [entry for when, entry in dated if when <= self.date]
        before = [entry for when, entry in dated if when > self.date]
        if before:
            position = block.entries.index(before[0])
        elif after:
            position = block.entries.index(after[-1]) + 1
        return block.insert(position, str(self.date), Block()).value

    def _written(self, key: str, value: object, old) -> object:
        field = self.record._field_of(key)
        if field is None:
            raise KeyError(f"el esquema {self.record.schema.kind} no declara el campo {key!r}")
        return field.type.write(value, old)

    def _place(self, block: Block, key: str, written) -> Entry:
        """Inserta ``key`` en ``block``: en la raíz, según el orden del esquema y nunca tras un bloque fechado;
        dentro de un bloque fechado, al final."""
        if block is self.record.block:
            from .placement import SchemaOrder, first_dated_index, insertion_index

            fields, _, _ = self.record._index_schema()
            index = insertion_index(block, key=key, order=SchemaOrder(tuple(fields)),
                                    first_dated=first_dated_index(block))
            return block.insert(index, key, written)
        return block.append(key, written)

    def set(self, key: str, value: object) -> Entry | None:
        """Escribe ``key`` en el destino que corresponde a la fecha (ver el módulo) y devuelve la entrada.
        ``None`` o ``MISSING`` quitan la clave del destino (devuelve None). Si ya valía eso, no cambia nada."""
        removing = value is None or value is MISSING
        current = self.get(key)
        if not removing:
            self._written(key, value, None)      # valida antes de ensuciar nada
            if current.entry is not None and current.value == value:
                return current.entry
        if self.at_start() and current.entry is not None and current.date is not None and not removing:
            # El valor vigente en el inicio lo pone un bloque fechado ≤ D: se cambia esa entrada.
            self.record._touch()
            current = self.get(key)
            current.entry.value = self._written(key, value, current.entry.value)
            return current.entry
        target = self.target_block(create=False)
        if removing:
            if target is None:
                return None
            entries = [entry for entry in target.entries if self._matches(entry, key)]
            if not entries:
                return None
            self.record._touch()
            target = self.target_block(create=False)
            for entry in [entry for entry in target.entries if self._matches(entry, key)]:
                target.remove_entry(entry)
            return None
        self.record._touch()
        target = self.target_block(create=True)
        entries = [entry for entry in target.entries if self._matches(entry, key)]
        if entries:
            entries[-1].value = self._written(key, value, entries[-1].value)
            return entries[-1]
        return self._place(target, key, self._written(key, value, None))

    def add(self, key: str, value: object) -> Entry | None:
        """Añade un valor acumulativo; None si ya estaba vigente (no cambia nada)."""
        add, remove = self._ops(key)
        text = str(value)
        if any(str(item.value).upper() == text.upper() for item in self.get_set(key)):
            return None
        self.record._touch()
        target = self.target_block(create=True)
        for entry in list(target.entries):
            if entry.key is not None and entry.key.text.lower() == remove.lower() and isinstance(entry.value, Scalar) \
                    and entry.value.text.upper() == text.upper():
                target.remove_entry(entry)
                if any(str(item.value).upper() == text.upper() for item in self.get_set(key)):
                    return None
        written = self._written(key, value, None)
        siblings = [entry for entry in target.entries if entry.key is not None and entry.key.text.lower() == add.lower()]
        if siblings:
            return target.insert_after(siblings[-1], add, written)
        return self._place(target, add, written)

    def remove(self, key: str, value: object) -> None:
        """Quita un valor acumulativo (no hace nada si no estaba vigente)."""
        add, remove = self._ops(key)
        text = str(value).upper()
        if not any(str(item.value).upper() == text for item in self.get_set(key)):
            return
        self.record._touch()
        if self.at_start():
            for entry in [entry for entry in self.record.block.entries if entry.key is not None
                          and entry.key.text.lower() == add.lower() and isinstance(entry.value, Scalar)
                          and entry.value.text.upper() == text]:
                self.record.block.remove_entry(entry)
            return
        target = self.target_block(create=True)
        for entry in [entry for entry in target.entries if entry.key is not None
                      and entry.key.text.lower() == add.lower() and isinstance(entry.value, Scalar)
                      and entry.value.text.upper() == text]:
            target.remove_entry(entry)
        if any(str(item.value).upper() == text for item in self.get_set(key)):
            target.append(remove, Scalar(str(value)))
