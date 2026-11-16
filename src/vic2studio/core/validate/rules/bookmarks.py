"""Familia «bookmarks»: fechas de inicio sin población y cámara fuera del mapa (wizard §14.10, H10, H20).

- ``bookmark_without_pops`` (aviso): ninguna carpeta ``history/pops/<fecha>`` con una
  fecha igual o anterior a la del bookmark. Vanilla trae ``1836.1.1`` y ``1861.4.14``
  para sus bookmarks de 1836.1.1 y 1861.7.1: el segundo no tiene carpeta con su
  fecha exacta, así que el juego no exige que coincidan, pero qué carpeta usa es
  [verificar en juego] y el texto no afirma más que eso.
- ``bookmark_camera_outside_map`` (aviso): ``cameraX``/``cameraY`` fuera del tamaño del
  BMP de provincias (``GameRules.map_size``, que solo lee su cabecera; vanilla:
  5616×2160 y cámaras dentro). El borde cuenta como dentro. Arreglo: llevar la
  cámara al punto del mapa más cercano.

``bookmarks.txt`` es un solo archivo (``WHOLE_FILE``): se lee el ganador con
``ctx.parse`` (con lo sin guardar) para dar la línea de cada campo.
"""

from __future__ import annotations

from ...clausewitz import Severity
from ...clausewitz.nodes import ClausewitzDate, Scalar
from ...index import model as m
from ...index.parsing import as_number
from ...vfs.paths import VPath
from ..registry import make_problem, rule

W = Severity.WARNING
BOOKMARKS_REL = VPath.of("common/bookmarks.txt")
POPS_FOLDER = "history/pops"
CAMERA_KEYS = ("cameraX", "cameraY")


def _date(text) -> ClausewitzDate | None:
    try:
        return ClausewitzDate.parse(str(text).strip())
    except ValueError:
        return None


def bookmark_entries(document) -> list[tuple[str, object]]:
    """``(nombre, entrada)`` de cada ``bookmark = { … }``, con el nombre que le da el índice (``name``; sin él, la
    fecha o la línea: ``extractors/war.bookmarks``)."""
    found = []
    for entry in document.entries:
        if entry.key is None or entry.key.text.lower() != "bookmark" or entry.value.__class__ is Scalar:
            continue
        block = entry.value
        found.append((block.get_text("name") or block.get_text("date") or f"bookmark_{entry.line}", entry))
    return found


def effective_bookmarks(ctx) -> tuple[VPath, list[tuple[str, object]]]:
    """La ruta (con sus mayúsculas) y los bookmarks del ``bookmarks.txt`` efectivo."""
    parsed = ctx.parse(BOOKMARKS_REL)
    if parsed is None:
        return BOOKMARKS_REL, []
    entry = ctx.entry(BOOKMARKS_REL)
    return (entry.rel if entry is not None else BOOKMARKS_REL), bookmark_entries(parsed.document)


def pops_dates(ctx) -> list[ClausewitzDate]:
    """Fechas de las carpetas ``history/pops/<fecha>`` con algún archivo en la vista efectiva, ordenadas."""
    dates = set()
    for rel in ctx.rels(POPS_FOLDER, "*.txt"):
        date = _date(rel.parts[2]) if len(rel.parts) > 3 else None
        if date is not None:
            dates.add(date)
    return sorted(dates)


@rule("bookmark_without_pops", W)
def bookmark_pops(ctx):
    rel, bookmarks = effective_bookmarks(ctx)
    if not bookmarks:
        return []
    dates = pops_dates(ctx)
    problems = []
    for name, entry in bookmarks:
        found = entry.value.find("date")
        date = _date(found.value.text) if found is not None and found.value.__class__ is Scalar else None
        if date is None or any(folder <= date for folder in dates):
            continue
        problems.append(make_problem("bookmark_without_pops", rel, found.line, found.column,
                                     entity=(m.KIND_BOOKMARK, name), field=("date",), bookmark=name,
                                     date=str(date)))
    return problems


def camera_outside(block, size: tuple[int, int]) -> list[tuple[object, float, int]]:
    """``(entrada, valor, límite)`` de cada coordenada de la cámara que cae fuera de ``0…límite``."""
    found = []
    for key, limit in zip(CAMERA_KEYS, size):
        entry = block.find(key)
        value = as_number(entry.value.text) if entry is not None and entry.value.__class__ is Scalar else None
        if value is not None and not 0 <= value <= limit:
            found.append((entry, value, limit))
    return found


@rule("bookmark_camera_outside_map", W, fixes=("move_camera_into_map",))
def bookmark_cameras(ctx):
    width, height = getattr(ctx.rules, "map_size", (0, 0))
    if width <= 0 or height <= 0:
        return []
    rel, bookmarks = effective_bookmarks(ctx)
    problems = []
    for name, entry in bookmarks:
        outside = camera_outside(entry.value, (width, height))
        if not outside:
            continue
        first = outside[0][0]
        block = entry.value
        problems.append(make_problem(
            "bookmark_camera_outside_map", rel, first.line, first.column, entity=(m.KIND_BOOKMARK, name),
            field=(first.key.text,), bookmark=name, x=block.get_text("cameraX", ""), y=block.get_text("cameraY", ""),
            width=width, height=height))
    return problems
