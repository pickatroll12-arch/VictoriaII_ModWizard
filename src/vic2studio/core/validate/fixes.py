"""Arreglos de un clic (SimpleFix, wizard §11.1), con plan de cambios previo y confirmación.

Cada arreglo es un ``FixSpec`` registrado en ``FIXES`` con ``register_fix``.
``apply`` trabaja sobre el ``Project`` en el hilo de la interfaz, dentro de una
transacción con nombre (``undo.fix_<clave>``): deshacible en un paso, y no escribe
en disco hasta que el usuario guarda. ``plan`` calcula el mismo cambio sin
dejarlo aplicado (por ejemplo en una transacción que se revierte) y devuelve el
diff. Catálogo de la iteración 3: ``register_tag``, ``convert_to_cp1252``,
``add_closing_brace``, ``restore_vanilla_loc_rows`` y ``trash_identical_copies``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .model import ChangePlan, FixSpec, Problem

if TYPE_CHECKING:
    from ..project import Project

FIXES: dict[str, FixSpec] = {}


def register_fix(spec: FixSpec) -> FixSpec:
    if spec.key in FIXES:
        raise ValueError(f"arreglo repetido: {spec.key}")
    FIXES[spec.key] = spec
    return spec


def fixes_for(problem: Problem) -> list[FixSpec]:
    """Los arreglos de ``problem`` en su orden (el primero es el SimpleFix) que estén registrados."""
    raise NotImplementedError


def plan_fix(key: str, problem: Problem, project: Project) -> ChangePlan:
    """Vista previa sin cambiar nada (el proyecto queda exactamente igual, también su pila de deshacer)."""
    raise NotImplementedError


def apply_fix(key: str, problem: Problem, project: Project) -> None:
    """Aplica el arreglo en una transacción deshacible; ``KeyError`` si la clave no existe."""
    raise NotImplementedError
