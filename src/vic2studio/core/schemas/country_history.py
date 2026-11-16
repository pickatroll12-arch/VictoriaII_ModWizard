"""Historia de país (``history/countries/<TAG> - <Nombre>.txt``, wizard §14.2, H13, H19). Iteración 6.

Un archivo por TAG (los tres primeros caracteres del nombre, ``vfs.rules.tag_key``): el registro es el documento
entero. Es historia fechada de estado (``HistorySpec("state")``): la ficha nacional lee y escribe en la fecha de
trabajo con ``Record.at(fecha)``. Las tecnologías (``<tecnología> = 1``), las invenciones (``<invención> = yes``)
y las reformas (``<grupo> = <opción>``) son claves dinámicas.
"""

from __future__ import annotations

from ..schema import (
    Bool,
    Date,
    DynamicKeys,
    EntitySchema,
    Field,
    Float,
    HistorySpec,
    IdRule,
    IdSpec,
    Int,
    KeyedFiles,
    Ref,
    Section,
    Text,
    Word,
)
from ..vfs.rules import tag_key

COUNTRY_HISTORY = EntitySchema(
    kind="country_history",
    layout=KeyedFiles("history/countries", key=tag_key),
    ident=IdSpec.FILE("{id} - {name}.txt"),
    ident_rule=IdRule.TAG,
    provides="country_history",
    history=HistorySpec("state"),
    fields=(
        Section("identity", (
            Field("capital", Ref("province"), ui="map_pick"),
            Field("primary_culture", Ref("culture")),
            Field("culture", Ref("culture"), repeat=True, ui="chips"),
            Field("religion", Ref("religion")),
            Field("civilized", Bool()),
        )),
        Section("politics", (
            Field("government", Ref("government")),
            Field("ruling_party", Word()),
            Field("last_election", Date()),
            Field("plurality", Float(0, 100)),
            Field("prestige", Float()),
            Field("nationalvalue", Ref("national_value")),
            DynamicKeys("upper_house", "ideology", Float(0, 100), widget="sliders"),
        )),
        Section("society", (
            Field("literacy", Float(0, 1)),
            Field("non_state_culture_literacy", Float(0, 1)),
            Field("consciousness", Float(0, 10), advanced=True),
            Field("nonstate_consciousness", Float(0, 10), advanced=True),
            Field("schools", Ref("tech_school")),
        )),
        Section("army", (Field("oob", Text()),)),
        Section("technology", (
            DynamicKeys("technology", "technology", Int(0, 1), widget="checklist", group_by="folder"),
        ), collapsed=True),
    ),
    unknown="keep",
    hall="nations", section="countries", order=1, icon="countries",
    editable=True,
)

SCHEMAS = (COUNTRY_HISTORY,)
