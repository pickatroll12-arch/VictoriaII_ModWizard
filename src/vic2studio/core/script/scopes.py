"""Tipos de guion, ámbitos y cambios de ámbito (wizard §12.1, §12.2).

Un bloque de guion es de **condiciones** (``trigger``, ``potential``, ``allow``, ``limit``, el resto de un
``modifier``) o de **efectos** (``immediate``, el resto de un ``option``, ``effect``). Cada clave se evalúa
en un **ámbito**: el país, la provincia, el estado o el POP sobre el que actúa. Algunas claves cambian el
ámbito de lo que contienen (``capital_scope``, ``any_owned_province``, ``owner``, ``FRA = { }``,
``369 = { }``): lo declara ``ScriptKeyDef.scope_change``.

Hechos de vanilla (eventos y decisiones, medidos con el censo de la iteración 7): 16 777 usos de claves en
condiciones y 9 369 en efectos; 7 niveles de anidación como máximo; el único operador es ``=``. Las claves
de bloque que cambian de ámbito más usadas son ``owner`` (742 usos), ``any_pop`` (717), ``random_state``
(255), ``capital_scope`` (190) y ``state_scope`` (127); 89 bloques llevan un TAG por clave y 119 un id de
provincia. ``THIS`` y ``FROM`` dependen de quién llama: su ámbito es ``Scope.ANY`` y no se comprueba.

Módulo hoja: no importa ``core.schema`` (que lo importa a él para el tipo ``Script``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum


class ScriptKind(str, Enum):
    """Qué contiene un bloque de guion. Los valores son los que ya usan los esquemas
    (``Script("can_use", "condition")``): al ser ``str``, ``ScriptKind.TRIGGER == "condition"``."""

    TRIGGER = "condition"
    EFFECT = "effect"

    def __str__(self) -> str:                # igual en Python 3.10 y 3.11+ (format() cambió en 3.11)
        return self.value


class Scope(str, Enum):
    """Ámbito en el que se evalúa una clave. ``ANY``: vale en cualquiera, o no se puede saber
    (``THIS``, ``FROM``) y no se comprueba."""

    ANY = "any"
    COUNTRY = "country"
    PROVINCE = "province"
    STATE = "state"
    POP = "pop"

    def __str__(self) -> str:
        return self.value


# Grafía con la que se escriben los grupos lógicos nuevos. Al leer no se distinguen mayúsculas: en vanilla
# hay 1 154 ``NOT`` y 272 ``not``, 267 ``OR`` y 261 ``or``, 9 ``AND`` y 178 ``and``; lo leído se conserva.
LOGIC_KEYS = ("AND", "OR", "NOT")


@dataclass(frozen=True)
class ScopeByEntry:
    """Ámbito inicial de un campo ``Script`` según la clave de la entrada dueña de la entidad.

    Los eventos comparten esquema y archivos, pero ``province_event`` se evalúa en la provincia y
    ``country_event`` en el país: ``ScopeByEntry((("province_event", Scope.PROVINCE),))``. La clave se
    compara sin distinguir mayúsculas.
    """

    cases: tuple[tuple[str, Scope], ...]
    default: Scope = Scope.COUNTRY

    def resolve(self, entry_key: str | None) -> Scope:
        """El ámbito para una entidad cuya entrada dueña tiene la clave ``entry_key``."""
        lowered = (entry_key or "").lower()
        for key, scope in self.cases:
            if key.lower() == lowered:
                return Scope(scope)
        return self.default


def accepts(allowed: Iterable[Scope], scope: Scope) -> bool:
    """True si una clave declarada para los ámbitos ``allowed`` vale en ``scope``.

    ``Scope.ANY`` en cualquiera de los dos lados acepta siempre: una clave general vale en todos los
    ámbitos, y dentro de ``THIS``/``FROM`` no se comprueba nada.
    """
    allowed = frozenset(allowed)
    return scope is Scope.ANY or Scope.ANY in allowed or scope in allowed


def scope_label(scope: Scope, lang: str) -> str:
    """Nombre legible del ámbito («país», «provincia»…): texto ``script.scope.<ámbito>``."""
    from ..texts import text

    return text(f"script.scope.{Scope(scope).value}", lang)
