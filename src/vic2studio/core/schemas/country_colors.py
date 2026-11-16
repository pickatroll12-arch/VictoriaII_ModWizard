"""Colores de uniforme (``common/country_colors.txt``, wizard §14.2). Iteración 6.

``<TAG> = { color1 = { r g b } color2 = { … } color3 = { … } }``. Son opcionales: en vanilla los tienen 147 de
271 TAG (``country_colors_missing`` es solo informativo).
"""

from __future__ import annotations

from ..schema import Color, EntitySchema, Field, IdRule, Section, SingleFile

COUNTRY_COLORS = EntitySchema(
    kind="country_colors",
    layout=SingleFile("common/country_colors.txt"),
    ident_rule=IdRule.TAG,
    provides="country_colors",
    fields=(Section("uniform", (Field("color1", Color()), Field("color2", Color()), Field("color3", Color()))),),
    unknown="keep",
    hall="nations", section="countries", order=1, icon="countries",
    editable=True,
)

SCHEMAS = (COUNTRY_COLORS,)
