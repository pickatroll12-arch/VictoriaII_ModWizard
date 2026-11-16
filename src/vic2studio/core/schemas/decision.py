"""Decisiones (``decisions/*.txt``, dentro de ``political_decisions = { … }``; wizard §14.5, capacidad 5).

Vanilla: 29 archivos y 151 decisiones, todas en un único contenedor ``political_decisions`` por archivo, sin
errores de sintaxis y sin ids repetidos (150 en minúsculas). Claves, por número de decisiones: ``potential``,
``allow`` y ``effect`` (151), ``ai_will_do`` (42), ``alert`` (8, siempre ``no``), ``news`` con sus tres
``news_desc_*`` (7) y ``picture`` (1). La imagen es ``gfx/pictures/decisions/<picture o id>.dds`` de 95×95,
sin comprimir y de 32 bits (149 archivos; 4 decisiones no tienen la suya, heredado). Textos: ``<id>_title`` y
``<id>_desc``.

Decisiones del esquema:

- **Lo nuevo** va al final del contenedor de ``decisions/<P>_decisions.txt``, que se crea con su
  ``political_decisions = { }`` si no existe. El usuario reparte las suyas por tema (4 archivos propios): el
  diálogo «Nueva decisión» deja elegir un archivo del mod que ya exista (``Entities.create(target_rel=…)``).
  Los textos van a ``00_<P>_decisions.csv``, que es justo el archivo que ya usa el mod del usuario.
- **Requisitos y efecto son obligatorios**: las 151 de vanilla llevan los tres bloques, aunque estén vacíos.
- **Archivos rotos.** 2 de los 4 archivos del usuario no cierran ``political_decisions``: se abren en modo
  texto y el arreglo «Añadir } al final» habilita el formulario (``core/script/textonly.py``).

Declarado sin registrar (``SCHEMAS`` vacío) hasta que crear en un ``NestedIn`` y ``Record.script`` tengan
lógica: registrarlo es lo que hace aparecer la sección.
"""

from __future__ import annotations

from ..schema import (
    Bool,
    EntitySchema,
    Field,
    LocKey,
    LocSpec,
    NestedIn,
    Picture,
    Scope,
    Script,
    ScriptKind,
    Section,
    When,
)
from ..script.mtth import AI_WILL_DO_KEY
from .mtth import weight_group

CONTAINER = "political_decisions"
NEW_FILE = "decisions/{prefix}_decisions.txt"
LOC_AREA = "decisions"
PICTURE_FOLDER = "decisions"                 # gfx/pictures/decisions/<picture o id>.dds, 95×95
PICTURE_SIZE = (95, 95)

_WITH_NEWS = When("news", True)

DECISION = EntitySchema(
    kind="decision",
    layout=NestedIn("decisions/*.txt", CONTAINER, NEW_FILE),
    provides="decision",
    # Los mismos atributos que ya da el extractor de ``decisions/*.txt``.
    symbol_attrs=lambda rec: {"category": CONTAINER, "picture": rec.get("picture", None)},
    fields=(
        Section("general", (
            Field("picture", Picture(PICTURE_FOLDER)),               # si falta, vale el id (H21)
            Field("alert", Bool(), default=True, advanced=True),
            Field("news", Bool(), advanced=True),
            Field("news_desc_long", LocKey(), advanced=True, visible_if=_WITH_NEWS),
            Field("news_desc_medium", LocKey(), advanced=True, visible_if=_WITH_NEWS),
            Field("news_desc_short", LocKey(), advanced=True, visible_if=_WITH_NEWS),
        )),
        Section("requirements", (
            Script("potential", ScriptKind.TRIGGER, Scope.COUNTRY, required=True),
            Script("allow", ScriptKind.TRIGGER, Scope.COUNTRY, required=True),
        )),
        Section("effect", (Script("effect", ScriptKind.EFFECT, Scope.COUNTRY, required=True),)),
        Section("ai", (weight_group(AI_WILL_DO_KEY, Scope.COUNTRY),), collapsed=True),
    ),
    loc=(LocSpec("{id}_title", LOC_AREA), LocSpec("{id}_desc", LOC_AREA)),
    template=lambda ident, index: {"potential": {}, "allow": {}, "effect": {}},
    hall="events", section="decisions", order=2, icon="quill", preview="decision",
)

# La cadena A lo registra (``SCHEMAS = (DECISION,)``) cuando el esquema ya funciona de punta a punta.
SCHEMAS = ()
