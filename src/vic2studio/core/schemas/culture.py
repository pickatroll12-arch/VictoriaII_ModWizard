"""Culturas y grupos de culturas (``common/cultures.txt``, §14.13). Vanilla: 34 grupos y 226 culturas (H18).

``<grupo> = { leader = european unit = EuropeanGC union = GER is_overseas = no <cultura> = { color = { r g b }
first_names = { … } last_names = { … } radicalism = n primary = TAG } }``. Las culturas son los bloques del
grupo que no son campos (``Children``): el grupo es un registro de nivel 0 y la cultura, de nivel 1 del mismo
``GroupedIn``. Una cultura nueva va al final de su grupo; los nombres se editan en su sitio (``ListOf``).
"""

from __future__ import annotations

from ..schema import (
    Bool,
    Children,
    Color,
    EntitySchema,
    Enum,
    Field,
    GroupedIn,
    Int,
    ListOf,
    LocSpec,
    Ref,
    Section,
    Text,
    issue,
    validator,
)

_LEADERS = ("european", "southamerican", "russian", "arab", "asian", "indian", "nativeamerican", "african",
            "polar_bear")


@validator("culture_name_not_cp1252", "warning")
def names_fit_cp1252(rec, ctx):
    """Un nombre con caracteres fuera de cp1252 sale roto en el juego (§14.13)."""
    for key in ("first_names", "last_names"):
        names = rec.get(key, None)
        if not isinstance(names, list):
            continue
        for name in names:
            try:
                str(name).encode("cp1252")
            except UnicodeEncodeError:
                yield issue("culture_name_not_cp1252", rec, field=(key,), name=str(name))
                break


CULTURE = EntitySchema(
    kind="culture",
    layout=GroupedIn("common/cultures.txt", level=1),
    provides="culture",
    symbol_attrs=lambda rec: {"color": rec.get("color", None)},
    fields=(
        Section("general", (
            Field("color", Color(), required=True),
            Field("radicalism", Int(0, 100)),
            Field("primary", Ref("tag")),
        )),
        Section("names", (
            Field("first_names", ListOf(Text(quoted=False)), required=True, ui="names"),
            Field("last_names", ListOf(Text(quoted=False)), required=True, ui="names"),
        )),
    ),
    loc=(LocSpec("{id}", "cultures"),),
    validators=(names_fit_cp1252,),
    template=lambda ident, idx: {"color": (128, 128, 128), "first_names": ["Name"], "last_names": ["Surname"]},
    hall="nations", section="cultures", order=2, icon="culture",
)

CULTURE_GROUP = EntitySchema(
    kind="culture_group",
    layout=GroupedIn("common/cultures.txt", level=0),
    provides="culture_group",
    fields=(
        Section("group", (
            Field("leader", Enum(*_LEADERS), required=True),
            Field("unit", Ref("graphical_culture")),
            Field("union", Ref("tag")),
            Field("is_overseas", Bool()),
        )),
        Children(CULTURE),
    ),
    loc=(LocSpec("{id}", "cultures"),),
    template=lambda ident, idx: {"leader": "european"},
)

SCHEMAS = (CULTURE_GROUP, CULTURE)
