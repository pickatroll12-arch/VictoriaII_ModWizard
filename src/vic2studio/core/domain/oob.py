"""Órdenes de batalla (``history/units/<TAG>_oob.txt``, wizard §14.2 «Ejército»). Iteración 6.

``read_oob`` lee los ejércitos y flotas de un documento sin cambiar nada; ``add_army``, ``add_unit`` y ``remove``
lo editan sin pérdidas (el resto del archivo queda byte a byte) dentro de la transacción de quien llama. Un
ejército o flota se identifica por su posición entre las entradas de primer nivel del archivo, y una unidad por la
suya dentro del ejército (dos regimientos pueden llamarse igual).

``oob_rel_of`` dice qué archivo usa un país: el que nombra su historia (``oob = "PRU_oob.txt"``) o, si no nombra
ninguno, ``history/units/<TAG>_oob.txt``; ``ensure_oob`` crea el archivo y la línea de la historia si faltan.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..clausewitz.nodes import Block, Scalar
from ..vfs.paths import VPath

UNDO_OOB_EDIT = "undo.oob_edit"
FOLDER = "history/units"


@dataclass(frozen=True)
class UnitInfo:
    kind: str                   # regiment | ship
    name: str
    type: str
    home: int | None
    position: int


@dataclass(frozen=True)
class ArmyInfo:
    kind: str                   # army | navy
    name: str
    location: int | None
    position: int
    units: tuple[UnitInfo, ...] = field(default_factory=tuple)


class OobError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def _int(text: str | None) -> int | None:
    return int(text) if text and text.strip().isdigit() else None


def read_oob(document: Block) -> list[ArmyInfo]:
    found = []
    for position, entry in enumerate(document.entries):
        if entry.key is None or not isinstance(entry.value, Block):
            continue
        kind = entry.key.text.lower()
        if kind not in ("army", "navy"):
            continue
        units = []
        for unit_position, child in enumerate(entry.value.entries):
            if child.key is None or not isinstance(child.value, Block):
                continue
            unit_kind = child.key.text.lower()
            if unit_kind in ("regiment", "ship"):
                units.append(UnitInfo(unit_kind, child.value.get_text("name") or "", child.value.get_text("type") or "",
                                      _int(child.value.get_text("home")), unit_position))
        found.append(ArmyInfo(kind, entry.value.get_text("name") or "", _int(entry.value.get_text("location")),
                              position, tuple(units)))
    return found


def oob_rel_of(countries, tag: str, date=None) -> VPath:
    value = countries.get(tag, "oob", date) if countries is not None else None
    name = str(value).strip().strip('"') if value else f"{tag.upper()}_oob.txt"
    return VPath.of(f"{FOLDER}/{name}")


def ensure_oob(ws, countries, tag: str, date=None) -> VPath:
    """El archivo de OOB de ``tag`` (lo crea vacío si no existe) y ``oob = "…"`` en su historia si falta."""
    rel = oob_rel_of(countries, tag, date)
    if not countries.get(tag, "oob", date):
        countries.set(tag, "oob", rel.name, None)
    handle = ws.open(rel, create=True)
    ws.touch(handle)
    return rel


def _army(document: Block, position: int):
    entries = list(document.entries)
    if not 0 <= position < len(entries):
        raise OobError("missing", str(position))
    entry = entries[position]
    if entry.key is None or entry.key.text.lower() not in ("army", "navy") or not isinstance(entry.value, Block):
        raise OobError("missing", str(position))
    return entry


def add_army(ws, rel: VPath, kind: str, name: str, location: int) -> int:
    """Añade un ejército (``kind="army"``) o una flota (``"navy"``) al final; devuelve su posición."""
    if kind not in ("army", "navy"):
        raise OobError("kind", kind)
    handle = ws.open(rel, create=True)
    ws.touch(handle)
    block = Block()
    block.append("name", Scalar(name, True))
    block.append("location", Scalar(str(int(location))))
    document = handle.model.document
    document.append(kind, block)
    return len(document.entries) - 1


def add_unit(ws, rel: VPath, position: int, name: str, unit_type: str, home: int | None = None) -> None:
    handle = ws.open(rel)
    ws.touch(handle)
    army = _army(handle.model.document, position)
    naval = army.key.text.lower() == "navy"
    block = Block()
    block.append("name", Scalar(name, True))
    block.append("type", Scalar(unit_type))
    if not naval and home is not None:
        block.append("home", Scalar(str(int(home))))
    army.value.append("ship" if naval else "regiment", block)


def remove(ws, rel: VPath, position: int, unit_position: int | None = None) -> None:
    """Quita el ejército o la flota de ``position`` o, con ``unit_position``, solo esa unidad."""
    handle = ws.open(rel)
    ws.touch(handle)
    army = _army(handle.model.document, position)
    if unit_position is None:
        handle.model.document.remove_entry(army)
        return
    entries = list(army.value.entries)
    if not 0 <= unit_position < len(entries):
        raise OobError("missing", str(unit_position))
    army.value.remove_entry(entries[unit_position])


def set_location(ws, rel: VPath, position: int, location: int) -> None:
    handle = ws.open(rel)
    ws.touch(handle)
    army = _army(handle.model.document, position)
    army.value.set("location", Scalar(str(int(location))))
