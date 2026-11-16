"""MTTH, ``ai_chance`` y ``ai_will_do``: una base y modificadores con factor y condiciones (wizard §12.3).

``mean_time_to_happen = { months = 6 modifier = { factor = 0.75 <condiciones> } … }``: el tiempo medio hasta
que el evento se dispara es la base por el producto de los factores de los modificadores cuyas condiciones
se cumplen. ``ai_chance`` (dentro de un ``option``) y ``ai_will_do`` (en una decisión) tienen la misma forma
con ``factor`` como base. El esquema de los tres está en ``core/schemas/mtth.py``; aquí vive el cálculo y el
modelo que pinta ``MtthEditor``.

Hechos de vanilla: 989 eventos con ``mean_time_to_happen``, todos con ``months`` entero (ninguno usa
``days`` ni ``years``, que el juego también admite) y 3 193 modificadores; ``factor`` va primero en 3 189 y
lleva decimales en 3 074; 3 136 tienen una sola condición. 72 ``ai_chance`` (23 modificadores) y 42
``ai_will_do`` (20). Un solo evento sin ``is_triggered_only`` carece de MTTH.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..clausewitz.nodes import Entry
    from ..schema.record import Record
    from .tree import ScriptTree

UNITS = ("months", "days", "years")           # claves de la base de un MTTH, en el orden del formulario
MONTHS_PER_YEAR = 12
DAYS_PER_MONTH = 30                           # convención del Studio al mostrar días como meses

MTTH_KEY = "mean_time_to_happen"
AI_CHANCE_KEY = "ai_chance"
AI_WILL_DO_KEY = "ai_will_do"
MODIFIER_KEY = "modifier"
FACTOR_KEY = "factor"


@dataclass(frozen=True)
class WeightModifier:
    """Un ``modifier = { factor = F <condiciones> }``. ``conditions`` es el árbol del resto del bloque
    (``Script(REST, TRIGGER)``) y ``entry`` su entrada en el CST («ver en el código»)."""

    factor: float
    conditions: ScriptTree | None = None
    entry: Entry | None = None


@dataclass(frozen=True)
class WeightModel:
    """Lo que edita ``MtthEditor``. ``unit``: ``"months"``, ``"days"`` o ``"years"`` en un MTTH y
    ``"factor"`` en ``ai_chance``/``ai_will_do``. ``base`` es None si el bloque no la trae."""

    key: str                                   # MTTH_KEY, AI_CHANCE_KEY o AI_WILL_DO_KEY
    unit: str
    base: float | None
    modifiers: tuple[WeightModifier, ...] = ()


def to_months(value: float, unit: str) -> float:
    """``value`` en meses (``days`` / 30, ``years`` × 12). ``ValueError`` con otra unidad."""
    if unit == "months":
        return float(value)
    if unit == "days":
        return float(value) / DAYS_PER_MONTH
    if unit == "years":
        return float(value) * MONTHS_PER_YEAR
    raise ValueError(f"unidad desconocida: {unit!r}")


def effective(base_months: float, factors: Sequence[float], satisfied: Sequence[bool]) -> float:
    """Tiempo efectivo: ``base_months`` por el producto de los ``factors`` cuyo ``satisfied`` es True
    (6 × 0,75 × 0,95 = 4,275 meses). Las dos secuencias miden lo mismo (``ValueError`` si no). Vale igual
    para el peso de ``ai_chance`` y ``ai_will_do`` con el factor base."""
    if len(factors) != len(satisfied):
        raise ValueError("factores y condiciones cumplidas deben medir lo mismo")
    result = float(base_months)
    for factor, ok in zip(factors, satisfied):
        if ok:
            result *= float(factor)
    return result


def read_weights(record: Record, key: str = MTTH_KEY) -> WeightModel | None:
    """El modelo del bloque ``key`` del registro (o de una vista de grupo: el ``option`` para
    ``ai_chance``); None si no lo tiene. No escribe nada (I4)."""
    raise NotImplementedError


def format_duration(months: float, lang: str) -> str:
    """El tiempo efectivo para mostrar: «4,3 meses», «1 año y 2 meses», «12 días» (un decimal y la coma o
    el punto del idioma). Textos ``script.mtth.*``."""
    from ..texts import text

    def number(value: float) -> str:
        shown = f"{value:.1f}".rstrip("0").rstrip(".") if value != int(value) else str(int(value))
        return shown.replace(".", ",") if lang == "es" else shown

    months = max(0.0, float(months))
    if months < 1:
        days = round(months * DAYS_PER_MONTH)
        return text("script.mtth.days_one" if days == 1 else "script.mtth.days", lang, n=days)
    if months >= MONTHS_PER_YEAR:
        years, rest = divmod(round(months), MONTHS_PER_YEAR)
        year_text = text("script.mtth.years_one" if years == 1 else "script.mtth.years", lang, n=years)
        if not rest:
            return year_text
        month_text = text("script.mtth.months_one" if rest == 1 else "script.mtth.months", lang, n=rest)
        return text("script.mtth.years_and_months", lang, years=year_text, months=month_text)
    rounded = round(months, 1)
    key = "script.mtth.months_one" if rounded == 1 else "script.mtth.months"
    return text(key, lang, n=number(rounded))
