"""Historias de provincia (``history/provinces/<carpeta>/<id> - <Nombre>.txt``, wizard §16.3, §22). Contrato de
la iteración 5.

Un archivo por provincia y el id es el entero inicial de su nombre (``KeyedFiles``, decisión 1 del informe
``docs/handoff/informes/it5_contrato.md``): el registro es el documento entero. Vanilla: 2 705 archivos para
2 703 ids (1396 y 1397 están dos veces) en 25 carpetas; 782 archivos tienen bloques fechados y 137, dos bloques
con la misma fecha. Los valores son historia fechada de estado (``HistorySpec("state")``): se leen y se escriben
con ``Record.at(fecha)`` (``core/schema/history.py``) y los núcleos se acumulan con ``add_core``/``remove_core``.

El esquema declara las claves para la referencia, la validación y la ficha de la provincia; la edición de
conjunto (pintar dueño, mover de región, POPs) va por ``core.domain.province.Provinces``. Nace con
``editable=False``: la cadena A lo pone a True cuando ``KeyedFiles`` y ``HistoryView`` tengan lógica. Su página
es la sección «Mundo» de la sala Mapa (``SectionSpec.hosts``), no un ``EntityEditorPage`` generado.
"""

from __future__ import annotations

from ..schema import (
    Bool,
    EntitySchema,
    Field,
    Group,
    HistorySpec,
    IdRule,
    IdSpec,
    Int,
    KeyedFiles,
    LocSpec,
    Ref,
    Section,
    SetOps,
)

FOLDER = "history/provinces"
DEFAULT_SUBFOLDER = "studio"


def region_folder(ctx, ident: str) -> str | None:
    """Subcarpeta de ``history/provinces`` donde nace la historia de la provincia ``ident``.

    Es la carpeta que más historias tiene de las provincias de **su región** (``map/region.txt``); con empate, la
    primera por orden alfabético sin mayúsculas, escrita como está en disco. None si la provincia no tiene región
    o ninguna de sus vecinas de región tiene historia: ``KeyedFiles`` usa entonces ``default_subfolder``
    (``"studio"``). En vanilla, 516 de los 549 estados tienen todas sus historias en una sola carpeta, 32 en dos
    y 1 en tres. Solo lee el índice de ``ctx`` (``pop``/``region``/``province_history``): no abre documentos.
    """
    from collections import Counter

    from ..index.model import KIND_PROVINCE_HISTORY, KIND_REGION

    index = getattr(ctx, "index", None)
    if index is None or not str(ident).isdigit():
        return None
    pid = int(ident)
    region = next((symbol for symbol in index.symbols(KIND_REGION)
                   if pid in ((symbol.attrs or {}).get("provinces") or ())), None)
    if region is None:
        return None
    folders: Counter = Counter()
    for other in (region.attrs or {}).get("provinces") or ():
        symbol = index.get(KIND_PROVINCE_HISTORY, str(other))
        if symbol is None:
            continue
        parts = symbol.rel.parts
        if len(parts) >= 4:            # history/provinces/<carpeta>/<archivo>
            folders[parts[2]] += 1
    if not folders:
        return None
    best = max(folders.values())
    return sorted((name for name, count in folders.items() if count == best), key=str.lower)[0]


def province_name(ctx, ident: str) -> str | None:
    """Nombre para el archivo nuevo de la provincia ``ident``: el texto de ``PROV<id>`` en la primera columna de
    la localización efectiva (con lo sin guardar); None si no hay texto. ``KeyedFiles`` lo pasa por
    ``ascii_name``."""
    loc = getattr(ctx, "loc", None)
    if loc is None:
        return None
    key = f"PROV{ident}"
    try:
        text = loc.text(key, "en")
    except (AttributeError, TypeError):
        entry = getattr(loc, "entry", lambda _key: None)(key)
        text = None if entry is None else (entry.get("en") if hasattr(entry, "get") else None)
    return text.strip() or None if isinstance(text, str) else None


PROVINCE_HISTORY = EntitySchema(
    kind="province_history",
    layout=KeyedFiles(FOLDER, default_subfolder=DEFAULT_SUBFOLDER, subfolder_of=region_folder,
                      name_of=province_name),
    ident=IdSpec.FILE("{id} - {name}.txt"),
    ident_rule=IdRule.INT_RANGE("province"),
    provides="province_history",
    history=HistorySpec("state"),
    fields=(
        Section("ownership", (
            Field("owner", Ref("tag")),
            Field("controller", Ref("tag")),
            Field("add_core", Ref("tag"), repeat=True, accumulate=SetOps("add_core", "remove_core"), ui="chips"),
        )),
        Section("resources", (
            Field("trade_goods", Ref("goods")),
            Field("life_rating", Int(0, 100)),
            Field("terrain", Ref("terrain"), advanced=True),
        )),
        Section("buildings", (
            Field("railroad", Int(0, 6)),
            Field("fort", Int(0, 6)),
            Field("naval_base", Int(0, 6)),
        )),
        Section("status", (
            Field("colonial", Int(0, 2)),
            Field("colony", Int(0, 2), advanced=True),
            Field("is_slave", Bool()),
        )),
        Section("extras", (
            Group("state_building", (
                Field("level", Int(1)),
                Field("building", Ref("building")),
                Field("upgrade", Bool()),
            ), repeat=True, id_field="building", widget="table"),
            Group("party_loyalty", (
                Field("ideology", Ref("ideology")),
                Field("loyalty_value", Int(0, 100)),
            ), repeat=True, id_field="ideology", widget="table"),
        ), collapsed=True),
    ),
    loc=(LocSpec("PROV{id}", "provinces"),),
    hall="map", section="world", order=1, icon="map",
    editable=True,
)

SCHEMAS = (PROVINCE_HISTORY,)
