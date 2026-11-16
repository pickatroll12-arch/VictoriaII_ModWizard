"""Familia «military» (parte de la iteración 3): ``peace_order`` de ``cb_types.txt`` (wizard §11, H17).

- ``cb_not_in_peace_order`` (aviso): un CB que no está en ``peace_order``.
- ``peace_order_unknown`` (aviso): un valor de ``peace_order`` que no es un CB
  (vanilla: ``annex``, heredado). Hace falta ya para el criterio 4 de la iteración 3.
"""

from __future__ import annotations

from ...clausewitz import Severity
from ...index import model as m
from ..registry import make_problem, rule

W = Severity.WARNING


@rule("cb_not_in_peace_order", W)
@rule("peace_order_unknown", W)
def peace_order(ctx):
    index = ctx.index
    problems = []
    order = [ref for ref in index.refs(m.KIND_CB) if ref.role == "peace_order"]
    if not order:
        return problems
    for ref in order:
        if not index.exists(m.KIND_CB, ref.name):
            problems.append(make_problem("peace_order_unknown", ref.rel, ref.line, ref.column,
                                         entity=(m.KIND_CB, ref.name), field=("peace_order",), cb=ref.name))
    listed = {ref.name for ref in order}
    for cb in index.symbols(m.KIND_CB):
        if cb.name not in listed:
            problems.append(make_problem("cb_not_in_peace_order", cb.rel, cb.line, entity=(m.KIND_CB, cb.name),
                                         cb=cb.name))
    return problems


# --- iteración 6: órdenes de batalla (history/units) -----------------------------------------------------------

E = Severity.ERROR
OOB_FOLDER = "history/units"


def oob_rels(ctx) -> list:
    """Los OOB de la vista, también los de las subcarpetas por fecha (``history/units/1861/…``)."""
    from ...vfs.paths import VPath

    found = {rel.key: rel for rel in ctx.rels(OOB_FOLDER, "*.txt")}
    for entry in ctx.snapshot.list(OOB_FOLDER, "*.txt", recursive=True):
        found.setdefault(entry.rel.key, entry.rel)
    return [VPath.of(found[key]) for key in sorted(found)]


def _units(ctx):
    """``(rel, entrada del ejército o la flota, tipo «army»/«navy», bloques de sus unidades)`` de cada OOB."""
    from ...clausewitz.nodes import Block

    for rel in oob_rels(ctx):
        parsed = ctx.parse(rel)
        if parsed is None:
            continue
        for entry in parsed.document.entries:
            if entry.key is None or not isinstance(entry.value, Block):
                continue
            kind = entry.key.text.lower()
            if kind not in ("army", "navy"):
                continue
            units = [child for child in entry.value.entries if child.key is not None
                     and child.key.text.lower() in ("regiment", "ship") and isinstance(child.value, Block)]
            yield rel, entry, kind, units


@rule("army_location_sea", E)
@rule("navy_location_inland", W)
@rule("regiment_type_mismatch", E)
def oob_units(ctx):
    """``army_location_sea``: un ejército en una provincia de mar (vanilla: ninguno). ``navy_location_inland``: una
    flota en una provincia de tierra que no toca el mar (las 116 flotas de vanilla están en puertos de tierra
    costeros; hace falta el ráster de provincias, y sin él no se comprueba). ``regiment_type_mismatch``: un
    ``regiment`` cuyo tipo es naval o un ``ship`` cuyo tipo es de tierra (vanilla: ninguno)."""
    index = ctx.index
    sea = set(index.names(m.KIND_SEA_PROVINCE)) | {str(p) for p in (getattr(ctx.rules, "sea", ()) or ())}
    types = {symbol.name: (symbol.attrs or {}).get("type") for symbol in index.symbols(m.KIND_UNIT_TYPE)}
    coastal = None
    problems = []
    for rel, entry, kind, units in _units(ctx):
        location = entry.value.get_text("location")
        name = entry.value.get_text("name") or ""
        place = entry.value.find("location")
        line = place.line if place is not None else entry.line
        if kind == "army" and location in sea:
            problems.append(make_problem("army_location_sea", rel, line, field=("location",), army=name,
                                         province=location))
        if kind == "navy" and location and location not in sea and location.isdigit():
            if coastal is None:
                from ...map.coherence import province_raster
                from ...map.geometry import coastal_provinces

                raster = province_raster(ctx)
                coastal = set() if raster is None else {str(p) for p in coastal_provinces(
                    raster, (int(p) for p in sea if str(p).isdigit()))}
                coastal_known = raster is not None
            if coastal_known and location not in coastal:
                problems.append(make_problem("navy_location_inland", rel, line, field=("location",), navy=name,
                                             province=location))
        wanted = "land" if kind == "army" else "naval"
        for unit in units:
            unit_type = unit.value.get_text("type")
            actual = types.get(unit_type) if unit_type else None
            if actual is not None and actual != wanted:
                problems.append(make_problem("regiment_type_mismatch", rel, unit.line, field=("type",),
                                             unit=unit.value.get_text("name") or "", type=unit_type,
                                             expected=wanted, actual=actual))
    return problems
