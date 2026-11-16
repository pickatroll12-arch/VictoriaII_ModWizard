"""MTTH, ``ai_chance`` y ``ai_will_do``: los grupos de campos que comparten eventos y decisiones (wizard §12.3).

No son entidades (no tienen archivo ni lista propios): son ``Group`` que los esquemas ``event`` y
``decision`` meten en sus campos. Los tres tienen la misma forma, una base y modificadores
``modifier = { factor = F <condiciones> }`` cuyas condiciones son un ``Script(REST, TRIGGER)``: el resto del
bloque tras ``factor``. El cálculo del tiempo efectivo y el modelo de la interfaz están en
``core/script/mtth.py``.

Vanilla (989 MTTH, 72 ``ai_chance`` y 42 ``ai_will_do``): la base del MTTH siempre es ``months``, entero;
``days`` y ``years`` no aparecen, así que van como avanzados.
"""

from __future__ import annotations

from ..schema import REST, Field, Float, Group, Int, Scope, ScopeByEntry, Script, ScriptKind
from ..script.mtth import AI_CHANCE_KEY, AI_WILL_DO_KEY, FACTOR_KEY, MODIFIER_KEY, MTTH_KEY


def modifier_group(scope: Scope | ScopeByEntry = Scope.COUNTRY) -> Group:
    """``modifier = { factor = F <condiciones> }``, repetible. Las condiciones se evalúan en ``scope``."""
    return Group(MODIFIER_KEY, repeat=True, widget="cards", fields=(
        Field(FACTOR_KEY, Float(), required=True),
        Script(REST, ScriptKind.TRIGGER, scope),
    ))


def mtth_group(scope: Scope | ScopeByEntry = Scope.COUNTRY) -> Group:
    """``mean_time_to_happen = { months = N modifier = { … } … }``."""
    return Group(MTTH_KEY, fields=(
        Field("months", Int(0)),
        Field("days", Int(0), advanced=True),
        Field("years", Int(0), advanced=True),
        modifier_group(scope),
    ))


def weight_group(key: str, scope: Scope | ScopeByEntry = Scope.COUNTRY) -> Group:
    """``ai_chance`` o ``ai_will_do``: ``<key> = { factor = F modifier = { … } … }``."""
    if key not in (AI_CHANCE_KEY, AI_WILL_DO_KEY):
        raise ValueError(f"grupo de pesos desconocido: {key!r}")
    return Group(key, fields=(
        Field(FACTOR_KEY, Float(0), required=True),
        modifier_group(scope),
    ))


# Sin entidades propias: el registro no añade nada por este módulo.
SCHEMAS = ()
