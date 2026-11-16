"""Familia «units»: modelos de las unidades y nivel de puerto de las navales (wizard §14.4, §14.12).

- ``sprite_missing`` (aviso): el modelo de una unidad no es ningún actor de
  ``interface/*.gfx``. Medido en vanilla (21 unidades, 285 actores ``EMFXActorType``,
  22 culturas gráficas):
  - ``sprite`` se busca como ``<cultura gráfica><sprite>``. Ninguna unidad tiene
    actor en todas las culturas salvo Infantry y Cavalry (22 de 22): Tank tiene 20;
    Artillery, Engineer y Guard, 3; Irregular, 2; Plane, 1; y los 10 barcos solo
    ``Generic``. Por eso basta con que **una** cultura tenga el actor; qué enseña el
    juego en las demás es [verificar en juego].
  - con ``sprite_override`` (cuirassier, dragoon y hussar, los tres ``Cavalry``) el
    ``sprite`` propio no tiene actor en ninguna cultura y el del override, en las
    22: se comprueba el override y no el ``sprite``.
  - ``sprite_mount`` (4 unidades, ``GenericMount``) nombra el actor entero: existe
    ``GenericMount`` y ningún ``<cultura>GenericMount``. Como también se lee
    ``Generic`` + ``Mount``, se admiten las dos formas en todos los campos.
  - ``sprite_mount_attach_node`` es un nodo del modelo, no un actor: no se mira.
  Los nombres coinciden en vanilla con sus mayúsculas; aquí se comparan sin
  distinguirlas (lo que haga el juego es [verificar en juego]) para no dar falsos
  positivos. Sin ningún actor en la vista (un juego sin ``objectTypes``) no hay con
  qué comparar y la regla calla.
- ``unit_port_level_too_high`` (error): ``min_port_level`` mayor que el ``max_level``
  del edificio de tipo ``naval_base`` (6 en vanilla, donde las navales piden de 0
  a 5): ningún puerto llega a ese nivel y la unidad no se puede construir. Arreglo:
  bajarlo al máximo.

Las unidades salen del índice; sus campos, del archivo analizado (``ctx.parse``, con
lo sin guardar), para dar la línea exacta.
"""

from __future__ import annotations

from ...clausewitz import Severity
from ...clausewitz.nodes import Scalar
from ...index import model as m
from ...index.parsing import as_int
from ..registry import make_problem, rule

E, W = Severity.ERROR, Severity.WARNING
NAVAL_BASE = "naval_base"


def unit_block(document, name: str):
    """El bloque ``<name> = { … }`` de primer nivel de un archivo de ``units/``; None si no está."""
    for entry in document.entries:
        if entry.key is not None and entry.key.text == name and entry.value.__class__ is not Scalar:
            return entry.value
    return None


def unit_blocks(ctx):
    """``(símbolo, bloque)`` de cada unidad de la vista efectiva."""
    for unit in ctx.index.symbols(m.KIND_UNIT_TYPE):
        parsed = ctx.parse(unit.rel)
        block = None if parsed is None else unit_block(parsed.document, unit.name)
        if block is not None:
            yield unit, block


def model_fields(block) -> list:
    """Las entradas del bloque que nombran un actor: el modelo (``sprite_override`` si lo hay; si no, ``sprite``)
    y la montura."""
    found = [block.find("sprite_override") or block.find("sprite"), block.find("sprite_mount")]
    return [entry for entry in found if entry is not None and entry.value.__class__ is Scalar
            and entry.value.text.strip()]


def actor_lookup(index):
    """Función ``sprite → bool``: si algún actor se llama así o ``<cultura gráfica><sprite>``; None si la vista no
    tiene ningún actor."""
    actors = {name.casefold() for name in index.names(m.ACTOR_KIND)}
    if not actors:
        return None
    cultures = [name.casefold() for name in index.names(m.KIND_GRAPHICAL_CULTURE)]

    def has_actor(sprite: str) -> bool:
        wanted = sprite.casefold()
        return wanted in actors or any(culture + wanted in actors for culture in cultures)

    return has_actor


@rule("sprite_missing", W)
def unit_sprites(ctx):
    has_actor = actor_lookup(ctx.index)
    if has_actor is None:
        return []
    problems = []
    for unit, block in unit_blocks(ctx):
        for entry in model_fields(block):
            sprite = entry.value.text
            if not has_actor(sprite):
                problems.append(make_problem("sprite_missing", unit.rel, entry.line, entry.column,
                                             entity=(m.KIND_UNIT_TYPE, unit.name), field=(entry.key.text,),
                                             unit=unit.name, sprite=sprite, attr=entry.key.text))
    return problems


def port_cap(index) -> tuple[str, int] | None:
    """``(edificio, max_level)`` del puerto que más niveles admite: los edificios de tipo ``naval_base`` (o, sin
    ``type``, el que se llama así); None si no hay ninguno con ``max_level``."""
    best = None
    for building in index.symbols(m.KIND_BUILDING):
        level = building.attrs.get("max_level")
        if (building.attrs.get("type") or building.name).lower() != NAVAL_BASE or not isinstance(level, int):
            continue
        if best is None or level > best[1]:
            best = (building.name, level)
    return best


@rule("unit_port_level_too_high", E, fixes=("lower_min_port_level",))
def port_levels(ctx):
    cap = port_cap(ctx.index)
    if cap is None:
        return []
    building, highest = cap
    problems = []
    for unit, block in unit_blocks(ctx):
        entry = block.find("min_port_level")
        level = as_int(entry.value.text) if entry is not None and entry.value.__class__ is Scalar else None
        if level is not None and level > highest:
            problems.append(make_problem("unit_port_level_too_high", unit.rel, entry.line, entry.column,
                                         entity=(m.KIND_UNIT_TYPE, unit.name), field=("min_port_level",),
                                         unit=unit.name, level=level, max=highest, building=building))
    return problems
