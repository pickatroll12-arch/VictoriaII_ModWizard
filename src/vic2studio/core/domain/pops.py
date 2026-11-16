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


def _folder_date(text: str) -> ClausewitzDate | None:
    try:
        return ClausewitzDate.parse(text)
    except ValueError:
        return None


class PopsIndex:
    """Qué archivo y qué bloque definen los POPs de cada provincia en cada fecha, con los repetidos."""

    def __init__(self, index) -> None:
        """``index``: el ``SymbolIndex`` (vivo o una copia). Lee los símbolos ``pop_block``."""
        self.index = index
        self._cache: tuple[int, dict] | None = None

    def _table(self) -> dict[ClausewitzDate, dict[int, list[PopBlockRef]]]:
        """``{carpeta: {provincia: bloques}}`` con los bloques efectivos (también los repetidos)."""
        generation = getattr(self.index, "generation", 0)
        if self._cache is not None and self._cache[0] == generation:
            return self._cache[1]
        from ..index.model import KIND_POP_BLOCK

        table: dict[ClausewitzDate, dict[int, list[PopBlockRef]]] = {}
        for name in self.index.names(KIND_POP_BLOCK):
            folder_text, _, province_text = name.partition(":")
            folder = _folder_date(folder_text)
            if folder is None or not province_text.isdigit():
                continue
            province = int(province_text)
            seen: dict[str, int] = {}
            for symbol in self.index.effective(KIND_POP_BLOCK, name):
                occurrence = symbol.attrs.get("occurrence") if symbol.attrs else None
                if occurrence is None:
                    occurrence = seen.get(symbol.rel.key, 0)
                seen[symbol.rel.key] = seen.get(symbol.rel.key, 0) + 1
                table.setdefault(folder, {}).setdefault(province, []).append(
                    PopBlockRef(folder, symbol.rel, province, int(occurrence), symbol.line))
        for provinces in table.values():
            for blocks in provinces.values():
                blocks.sort(key=lambda ref: (ref.rel.key, ref.occurrence))
        self._cache = (generation, table)
        return table

    def symbol(self, ref: PopBlockRef):
        """El símbolo ``pop_block`` del bloque (con ``size``, ``culture`` y ``religion``); None si no está."""
        from ..index.model import KIND_POP_BLOCK

        for symbol in self.index.effective(KIND_POP_BLOCK, f"{ref.folder}:{ref.province}"):
            if symbol.rel.key == ref.rel.key and symbol.line == ref.line:
                return symbol
        return None

    def folders(self) -> list[ClausewitzDate]:
        """Las carpetas de fecha con algún bloque, de menor a mayor. Una carpeta cuyo nombre no es una fecha no
        cuenta."""
        return sorted(self._table())

    def folder_for(self, date: ClausewitzDate) -> ClausewitzDate | None:
        """La última carpeta con fecha ≤ ``date``; None si no hay ninguna."""
        found = None
        for folder in self.folders():
            if folder <= date:
                found = folder
        return found

    def blocks(self, pid: int, date: ClausewitzDate, *, exact: bool = False) -> list[PopBlockRef]:
        """Los bloques de ``pid`` en la carpeta de ``date`` (``folder_for``; con ``exact``, solo si la carpeta
        es exactamente ``date``), por archivo (``rel.key``) y aparición. Vacía si no tiene."""
        folder = date if exact else self.folder_for(date)
        if folder is None:
            return []
        return list(self._table().get(folder, {}).get(int(pid), ()))

    def provinces(self, date: ClausewitzDate) -> list[int]:
        """Ids con algún bloque en la carpeta de ``date``, ordenados."""
        folder = self.folder_for(date)
        return [] if folder is None else sorted(self._table().get(folder, {}))

    def repeated(self, date: ClausewitzDate | None = None) -> list[tuple[PopBlockRef, ...]]:
        """Los grupos de bloques de una misma provincia y carpeta que son más de uno (en un archivo o en
        varios); con ``date``, solo los de su carpeta. Vanilla: uno, el de 2482."""
        table = self._table()
        folders = sorted(table) if date is None else [f for f in [self.folder_for(date)] if f is not None]
        found = []
        for folder in folders:
            for province in sorted(table.get(folder, {})):
                blocks = table[folder][province]
                if len(blocks) > 1:
                    found.append(tuple(blocks))
        return found

    def target_for_new(self, pid: int, date: ClausewitzDate, prefix: str) -> VPath:
        """Archivo donde crear el bloque de una provincia sin POPs:
        ``history/pops/<folder_for(date) o date>/00_<prefix>_pops.txt``."""
        folder = self.folder_for(date) or date
        return VPath.of(f"{POPS_FOLDER}/{folder}/{NEW_FILE.format(prefix=prefix)}")


def _pop_entries(block) -> list:
    from ..clausewitz.nodes import Block

    return [entry for entry in block.entries if entry.key is not None and isinstance(entry.value, Block)]


def _text(block, key: str) -> str | None:
    value = block.get(key)
    return value.text if value is not None and hasattr(value, "text") else None


def _number(text: str | None, kind=int):
    if text is None:
        return None
    try:
        return kind(float(text)) if kind is int else kind(text)
    except ValueError:
        return None


class ProvincePops:
    """Lectura y edición de los POPs de un bloque sobre ``Entities`` (hilo de la interfaz)."""

    def __init__(self, entities: Entities, pops_index: PopsIndex | None = None) -> None:
        self.entities = entities
        self.pops_index = pops_index if pops_index is not None else PopsIndex(entities.index)

    def _record(self, ref: PopBlockRef):
        from ..schema.record import RecordRef

        return self.entities.open(RecordRef("pops", ref.ident, ref.rel))

    def read(self, ref: PopBlockRef) -> list[Pop]:
        """Los POPs del bloque en orden de archivo. ``KeyError`` si el bloque ya no está. No escribe."""
        record = self._record(ref)
        pops = []
        for position, entry in enumerate(_pop_entries(record.block)):
            block = entry.value
            pops.append(Pop(position, entry.key.text, _text(block, "culture") or "", _text(block, "religion") or "",
                            _number(_text(block, "size")) or 0, _number(_text(block, "militancy"), float),
                            _text(block, "rebel_type")))
        return pops

    def total(self, pid: int, date: ClausewitzDate) -> int:
        """Suma de ``size`` de todos los bloques de ``pid`` en la carpeta de ``date`` (repetidos incluidos)."""
        total = 0
        for ref in self.pops_index.blocks(pid, date):
            try:
                total += sum(pop.size for pop in self.read(ref))
            except (KeyError, FileNotFoundError):
                continue
        return total

    def majority(self, pid: int, date: ClausewitzDate) -> tuple[str | None, str | None]:
        """Cultura y religión del POP mayor de ``pid`` en la fecha (el primero a igualdad)."""
        best = None
        for ref in self.pops_index.blocks(pid, date):
            try:
                pops = self.read(ref)
            except (KeyError, FileNotFoundError):
                continue
            for pop in pops:
                if best is None or pop.size > best.size:
                    best = pop
        return (None, None) if best is None else (best.culture or None, best.religion or None)

    def _entry(self, ref: PopBlockRef, index: int):
        record = self._record(ref)
        entries = _pop_entries(record.block)
        if not 0 <= index < len(entries):
            raise IndexError(index)
        return record, entries[index]

    def set(self, ref: PopBlockRef, index: int, *, type: str | None = None, culture: str | None = None,
            religion: str | None = None, size: int | None = None, militancy: object = MISSING,
            rebel_type: object = MISSING) -> None:
        """Cambia los datos indicados del POP ``index`` (None = no tocar; ``militancy`` y ``rebel_type`` admiten
        None para quitar la clave). Cambiar el tipo cambia solo la clave del POP."""
        if size is not None and int(size) < 1:
            raise ValueError("size")
        record, entry = self._entry(ref, index)
        block = entry.value
        changes = []
        if type is not None and entry.key.text != type:
            changes.append(lambda: setattr(entry, "key", type))
        for key, value in (("culture", culture), ("religion", religion)):
            if value is not None and _text(block, key) != value:
                changes.append(lambda key=key, value=value: block.set(key, value))
        if size is not None and _number(_text(block, "size")) != int(size):
            changes.append(lambda: block.set("size", int(size)))
        if militancy is not MISSING:
            current = _number(_text(block, "militancy"), float)
            if militancy is None and block.has("militancy"):
                changes.append(lambda: block.remove("militancy"))
            elif militancy is not None and current != float(militancy):
                changes.append(lambda: block.set("militancy", float(militancy)))
        if rebel_type is not MISSING:
            if rebel_type is None and block.has("rebel_type"):
                changes.append(lambda: block.remove("rebel_type"))
            elif rebel_type is not None and _text(block, "rebel_type") != rebel_type:
                changes.append(lambda: block.set("rebel_type", rebel_type))
        if not changes:
            return
        record._touch()
        for change in changes:
            change()

    def add(self, ref: PopBlockRef, pop: Pop) -> int:
        """Añade un POP al final del bloque y devuelve su posición (``pop.index`` se ignora)."""
        from ..clausewitz.nodes import Block

        if pop.size < 1:
            raise ValueError("size")
        record = self._record(ref)
        values = [("culture", pop.culture), ("religion", pop.religion), ("size", int(pop.size))]
        if pop.militancy is not None:
            values.append(("militancy", float(pop.militancy)))
        if pop.rebel_type:
            values.append(("rebel_type", pop.rebel_type))
        record._touch()
        record.block.append(pop.type, Block.from_pairs(values))
        return len(_pop_entries(record.block)) - 1

    def remove(self, ref: PopBlockRef, index: int) -> None:
        record, entry = self._entry(ref, index)
        record._touch()
        record.block.remove_entry(entry)

    def create_block(self, pid: int, date: ClausewitzDate) -> PopBlockRef:
        """Bloque vacío para una provincia sin POPs en la carpeta de ``date``, en ``target_for_new`` (crea el
        archivo si hace falta). ``ValueError`` si ya tiene alguno."""
        if self.pops_index.blocks(pid, date):
            raise ValueError(f"la provincia {pid} ya tiene POPs")
        from ..schema.record import RecordRef

        folder = self.pops_index.folder_for(date) or date
        prefix = getattr(self.entities.loc, "prefix", None) or "studio"
        rel = self.pops_index.target_for_new(pid, date, prefix)
        ws = self.entities.ws
        handle = ws.open(rel, create=True)
        ws.touch(handle)
        from ..clausewitz.nodes import Block

        handle.model.document.append(str(int(pid)), Block())
        occurrence = 0
        ref = PopBlockRef(folder, rel, int(pid), occurrence)
        self.entities.open(RecordRef("pops", ref.ident, rel))      # comprueba que se lee
        return ref

    def copy_from(self, target: PopBlockRef, source: PopBlockRef) -> None:
        """«Copiar POPs de la provincia…»: sustituye los POPs de ``target`` por una copia de los de
        ``source`` (con su formato)."""
        origin = self._record(source)
        copies = [entry.clone() for entry in _pop_entries(origin.block)]
        record = self._record(target)
        record._touch()
        for entry in _pop_entries(record.block):
            record.block.remove_entry(entry)
        for entry in copies:
            record.block.insert_entry(len(record.block.entries), entry)

    def scale(self, ref: PopBlockRef, factor: float) -> None:
        """«Escalar ×»: multiplica cada ``size`` por ``factor`` y redondea al entero más cercano (mínimo 1).
        ``ValueError`` si ``factor`` ≤ 0."""
        if factor <= 0:
            raise ValueError("factor")
        record = self._record(ref)
        targets = []
        for entry in _pop_entries(record.block):
            size = _number(_text(entry.value, "size"))
            if size is None:
                continue
            new = max(1, int(round(size * factor)))
            if new != size:
                targets.append((entry.value, new))
        if not targets:
            return
        record._touch()
        for block, new in targets:
            block.set("size", new)
