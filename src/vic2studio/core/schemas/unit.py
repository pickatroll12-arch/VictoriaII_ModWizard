"""Unidades terrestres y navales (``units/<id>.txt``, un bloque ``<id> = { … }`` por archivo).

Vanilla trae 21 unidades: 11 con ``type = land`` y 10 con ``type = naval`` (H18); las 21 pasan
sin ``unknown_field`` ni ``bad_type``. Los campos comunes están en «general» y los propios de
cada tipo, en la variante por ``type`` (§10.3), con una vista por sección («land» y «naval»).
Los costes (``build_cost``, ``supply_cost``) son bloques de bienes (``DynamicKeys`` sobre el
índice de bienes). Lo nuevo va a ``units/<id>.txt`` en el mod. Las vistas dan las secciones Guerra › Unidades terrestres
(``war:land``) y Unidades navales (``war:naval``); el compañero ``ActivateUnit`` dice qué la activa y avisa si
nada lo hace, y ``UnitNamesSlot`` ofrece su lista de nombres en los países al crear una naval.

Los campos de la variante activa salen solo de la clave ``type`` leída del bloque; una unidad
sin ``type`` no muestra campos de variante (nunca ocurre en vanilla).
"""

from __future__ import annotations

from ..schema import (
    ActivateUnit,
    Bool,
    DynamicKeys,
    EntitySchema,
    Enum,
    Field,
    Float,
    Group,
    Int,
    LocSpec,
    OnePerFile,
    Section,
    UnitNamesSlot,
    Variant,
    View,
    Word,
)

_UNIT_TYPES = ("infantry", "cavalry", "support", "special", "big_ship", "light_ship", "transport")

_COMMON = Section("general", (
    Field("icon", Int(0)),
    Field("type", Enum("land", "naval")),
    Field("sprite", Word()),
    Field("active", Bool()),
    Field("unit_type", Enum(*_UNIT_TYPES)),
    Field("floating_flag", Bool()),
    Field("priority", Int(0)),
    Field("max_strength", Int(0)),
    Field("default_organisation", Int(0)),
    Field("maximum_speed", Float()),
    Field("weighted_value", Float()),
    Field("build_time", Int(0)),
    Group("build_cost", (), dynamic=DynamicKeys("build_cost", "goods", Float(), widget="grid")),
    Field("supply_consumption", Float()),
    Group("supply_cost", (), dynamic=DynamicKeys("supply_cost", "goods", Float(), widget="grid")),
))

_LAND = Section("land", (
    Field("sprite_override", Word()),
    Field("sprite_mount", Word()),
    Field("sprite_mount_attach_node", Word()),
    Field("primary_culture", Bool()),
    Field("reconnaissance", Int(0)),
    Field("attack", Float()),
    Field("defence", Int(0)),
    Field("discipline", Float()),
    Field("support", Float()),
    Field("maneuver", Int(0)),
    Field("siege", Int(0)),
))

_NAVAL = Section("naval", (
    Field("naval_icon", Int(0)),
    Field("sail", Bool()),
    Field("capital", Bool()),
    Field("colonial_points", Int()),
    Field("can_build_overseas", Bool()),
    Field("min_port_level", Int()),
    Field("limit_per_port", Int()),
    Field("supply_consumption_score", Int()),
    Field("hull", Int()),
    Field("gun_power", Int()),
    Field("fire_range", Float()),
    Field("evasion", Float()),
    Field("torpedo_attack", Int()),
    Field("transport", Bool()),
    Field("move_sound", Word()),
    Field("select_sound", Word()),
))

UNIT = EntitySchema(
    kind="unit",
    layout=OnePerFile("units", r"^(?P<id>[a-z0-9_]+)\.txt$", "{id}.txt"),
    provides="unit_type",
    symbol_attrs=lambda rec: {"type": rec.get("type", None)},
    fields=(_COMMON,),
    variants=Variant("type", {"land": (_LAND,), "naval": (_NAVAL,)}),
    views=(
        View("land", lambda rec: rec.get("type") == "land", "land"),
        View("naval", lambda rec: rec.get("type") == "naval", "naval"),
    ),
    loc=(LocSpec("{id}", "units"), LocSpec("{id}_short", "units")),
    companions=(ActivateUnit(), UnitNamesSlot()),
    template=lambda ident, idx: {"type": "land", "unit_type": "infantry", "active": True, "priority": 1,
                                 "max_strength": 3, "default_organisation": 30, "maximum_speed": 4.0,
                                 "build_time": 90, "attack": 2.0, "defence": 2},
    hall="war", section="units", order=5, icon="helmet",
)

SCHEMAS = (UNIT,)
