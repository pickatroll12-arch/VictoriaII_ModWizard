"""Catálogos de solo lectura: tecnologías, invenciones, ideologías, reformas, bienes y edificios (§22).

Solo se indexan y se listan (``editable=False``): alimentan los selectores y las claves dinámicas de otros
esquemas, y docgen los documenta. No tienen sección propia ni se crean, duplican o borran desde el Studio
(``Entities`` lanza ``ReadOnlySchemaError``). Sus claves se conservan sin avisar (``unknown="keep"``).
"""

from __future__ import annotations

from ..schema import EntitySchema, Field, GroupedIn, Int, LocSpec, NestedIn, Section, SingleFile, Word

TECHNOLOGY = EntitySchema(
    kind="technology",
    layout=NestedIn("technologies/*.txt", "", "technologies/new.txt"),
    provides="technology",
    fields=(Section("general", (Field("area", Word()), Field("year", Int(0)))),),
    loc=(LocSpec("{id}", "technologies"),),
    unknown="keep", editable=False, icon="gear",
)

INVENTION = EntitySchema(
    kind="invention",
    layout=NestedIn("inventions/*.txt", "", "inventions/new.txt"),
    provides="invention",
    fields=(),
    loc=(LocSpec("{id}", "technologies"),),
    unknown="keep", editable=False, icon="gear",
)

IDEOLOGY = EntitySchema(
    kind="ideology",
    layout=GroupedIn("common/ideologies.txt", level=1),
    provides="ideology",
    fields=(),
    loc=(LocSpec("{id}", "politics"),),
    unknown="keep", editable=False, icon="crown",
)

ISSUE_GROUP = EntitySchema(
    kind="issue_group",
    layout=GroupedIn("common/issues.txt", level=1),
    provides="issue_group",
    fields=(),
    loc=(LocSpec("{id}", "politics"),),
    unknown="keep", editable=False, icon="scroll_seal",
)

GOODS = EntitySchema(
    kind="goods",
    layout=GroupedIn("common/goods.txt", level=1),
    provides="goods",
    fields=(),
    loc=(LocSpec("{id}", "goods"),),
    unknown="keep", editable=False, icon="gear",
)

BUILDING = EntitySchema(
    kind="building",
    layout=SingleFile("common/buildings.txt"),
    provides="building",
    fields=(Section("general", (Field("max_level", Int(0)),)),),
    loc=(LocSpec("{id}", "buildings"),),
    unknown="keep", editable=False, icon="gear",
)

SCHEMAS = (TECHNOLOGY, INVENTION, IDEOLOGY, ISSUE_GROUP, GOODS, BUILDING)
