"""Eventos (``events/*.txt``): ``country_event`` y ``province_event`` (wizard §14.7, capacidad 7).

Vanilla: 82 archivos y 1 064 eventos (882 de país y 182 de provincia), cp1252, sin errores de sintaxis; ids de
100 a 111 011 928 sin repetir. Claves de un evento, por número de eventos que las llevan: ``id``, ``title`` y
``desc`` (1 064), ``trigger`` (1 002), ``mean_time_to_happen`` (989), ``picture`` (863), ``fire_only_once``
(225), ``news`` con sus tres ``news_desc_*`` (151), ``is_triggered_only`` (88), ``major`` (25), ``election``
con ``issue_group`` (22), ``immediate`` (3), ``news_title`` (3) y ``allow_multiple_instances`` (2); 1 655
``option`` (de 1 a 5 por evento; 589 eventos tienen una y 398 dos). Las imágenes son
``gfx/pictures/events/<picture>.tga`` de 521×203 (286 archivos; 5 eventos nombran una que no existe).

Decisiones del esquema:

- **Un esquema, dos vistas.** Los dos tipos comparten archivos, ids y el símbolo ``event`` del índice. El
  tipo es la clave de la entrada (``Record.entity_key``), no un campo: las vistas ``country`` y ``province``
  filtran por ella dentro de la misma sección (Eventos › Eventos), y el ámbito inicial de todo su guion sale
  de ``EVENT_SCOPE``.
- **Lo nuevo** va al final de ``events/<P>_events.txt`` (o del archivo que elija «Nuevo evento»), con el
  primer id libre del rango del proyecto (``IdRule.INT_RANGE("event")``, ``core/script/idalloc.py``).
- **Textos.** Las claves viven en los campos ``title``, ``desc`` y ``option.name`` (``LocSpec.field``): en
  vanilla, 253 títulos, 272 descripciones y 352 nombres de opción reutilizan la clave de otro evento. Al
  crear se proponen ``EVTNAME<id>``, ``EVTDESC<id>``, ``EVTOPTA<id>`` y ``EVTOPTB<id>`` en
  ``00_<P>_events.csv``. Un título en prosa (2 eventos de vanilla) se respeta.
- **Plantilla segura.** Un evento nuevo nace con ``is_triggered_only = yes``: sin condiciones, un evento con
  MTTH se dispararía para todos los países en cuanto se cargue el mod.

El esquema queda declarado pero sin registrar (``SCHEMAS`` vacío) hasta que ``TypedEntries``,
``Record.script`` y sus textos tengan lógica: registrarlo es lo que hace aparecer la sección.
"""

from __future__ import annotations

from ..schema import (
    REST,
    Bool,
    EntitySchema,
    Field,
    Group,
    IdRule,
    IdSpec,
    Int,
    LocKey,
    LocSpec,
    Picture,
    Ref,
    Scope,
    ScopeByEntry,
    Script,
    ScriptKind,
    Section,
    TypedEntries,
    View,
    When,
)
from ..script.mtth import AI_CHANCE_KEY
from .mtth import mtth_group, weight_group

COUNTRY_EVENT = "country_event"
PROVINCE_EVENT = "province_event"
EVENT_KEYS = (COUNTRY_EVENT, PROVINCE_EVENT)
# ``Entities.create("event", id, {TYPE_FIELD: PROVINCE_EVENT, …})`` elige el tipo (``TypedEntries.type_field``).
TYPE_FIELD = "type"

# Todo el guion de un evento empieza en el país o en la provincia que lo recibe.
EVENT_SCOPE = ScopeByEntry(((PROVINCE_EVENT, Scope.PROVINCE),), default=Scope.COUNTRY)

NEW_FILE = "events/{prefix}_events.txt"
LOC_AREA = "events"
PICTURE_FOLDER = "events"                    # gfx/pictures/events/<picture>.tga, 521×203
PICTURE_SIZE = (521, 203)

_WITH_NEWS = When("news", True)


def _entity_key(record) -> str:
    return (record.entity_key or "").lower()


def _template(ident: str, index) -> dict:
    return {
        TYPE_FIELD: COUNTRY_EVENT,
        "title": f"EVTNAME{ident}",
        "desc": f"EVTDESC{ident}",
        "is_triggered_only": True,
        "option": [{"name": f"EVTOPTA{ident}"}, {"name": f"EVTOPTB{ident}"}],
    }


EVENT = EntitySchema(
    kind="event",
    layout=TypedEntries("events/*.txt", EVENT_KEYS, "id", NEW_FILE, type_field=TYPE_FIELD),
    ident=IdSpec.FIELD("id"),
    ident_rule=IdRule.INT_RANGE("event"),
    provides="event",
    # Los mismos atributos que ya da el extractor de ``events/*.txt`` (``core/index/extractors/script.py``).
    symbol_attrs=lambda rec: {
        "type": _entity_key(rec), "title": rec.get("title", None), "desc": rec.get("desc", None),
        "picture": rec.get("picture", None), "triggered_only": rec.get("is_triggered_only", False) is True,
        "options": [option.get("name", None) for option in rec.groups("option")]},
    fields=(
        Section("general", (
            Field("id", Int(1), required=True),
            Field("title", LocKey("EVTNAME{id}"), required=True),
            Field("desc", LocKey("EVTDESC{id}"), required=True),
            Field("picture", Picture(PICTURE_FOLDER)),
            Field("is_triggered_only", Bool()),
            Field("fire_only_once", Bool()),
            Field("major", Bool(), advanced=True),
            Field("allow_multiple_instances", Bool(), advanced=True),
            Field("election", Bool(), advanced=True),
            Field("issue_group", Ref("issue_group"), advanced=True, visible_if=When("election", True)),
        )),
        Section("news", (
            Field("news", Bool()),
            Field("news_title", LocKey(), visible_if=_WITH_NEWS),
            Field("news_desc_long", LocKey(), visible_if=_WITH_NEWS),
            Field("news_desc_medium", LocKey(), visible_if=_WITH_NEWS),
            Field("news_desc_short", LocKey(), visible_if=_WITH_NEWS),
        ), collapsed=True),
        Section("conditions", (Script("trigger", ScriptKind.TRIGGER, EVENT_SCOPE),)),
        Section("mtth", (mtth_group(EVENT_SCOPE),)),
        Section("immediate", (Script("immediate", ScriptKind.EFFECT, EVENT_SCOPE),), collapsed=True),
        Section("options", (
            Group("option", repeat=True, required=True, widget="cards", fields=(
                Field("name", LocKey("EVTOPT{letter}{id}")),
                weight_group(AI_CHANCE_KEY, EVENT_SCOPE),
                Script(REST, ScriptKind.EFFECT, EVENT_SCOPE),
            )),
        )),
    ),
    views=(
        View("country", lambda rec: _entity_key(rec) == COUNTRY_EVENT, "events"),
        View("province", lambda rec: _entity_key(rec) == PROVINCE_EVENT, "events"),
    ),
    loc=(
        LocSpec("EVTNAME{id}", LOC_AREA, field=("title",)),
        LocSpec("EVTDESC{id}", LOC_AREA, field=("desc",)),
        LocSpec("EVTOPT{letter}{id}", LOC_AREA, field=("option", "name")),
    ),
    template=_template,
    hall="events", section="events", order=1, icon="events", preview="event",
)

# La cadena A lo registra (``SCHEMAS = (EVENT,)``) cuando el esquema ya funciona de punta a punta.
SCHEMAS = ()
