"""Registro de reglas de validación por descubrimiento (wizard §11, §20: sin listas centrales).

Cada familia es un módulo de ``core/validate/rules/`` cuyas funciones se registran
con ``@rule``. Una función puede declarar varios códigos apilando decoradores; el
validador la ejecuta una sola vez. Recibe el ``ValidationContext`` y devuelve los
``Problem`` que encuentre, creados con ``make_problem`` (que pone la gravedad y
los arreglos declarados). Una regla no lee disco por su cuenta: usa ``ctx``.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..clausewitz import Severity
from ..vfs.paths import VPath
from .model import Problem

if TYPE_CHECKING:
    from .context import ValidationContext

RuleFn = Callable[["ValidationContext"], Iterable[Problem]]

SCOPE_PROJECT = "project"   # necesita la vista entera (registros, mapa, ids)
SCOPE_FILE = "file"         # se puede repetir solo sobre los archivos cambiados (sintaxis, codificación)


@dataclass(frozen=True)
class RuleSpec:
    code: str
    severity: Severity
    scope: str
    fixes: tuple[str, ...]
    fn: RuleFn
    family: str                          # módulo de rules/ («countries», «localisation»…)


RULES: dict[str, RuleSpec] = {}


def rule(code: str, severity: Severity, *, scope: str = SCOPE_PROJECT,
         fixes: tuple[str, ...] = ()) -> Callable[[RuleFn], RuleFn]:
    """Decorador: ``fn`` puede producir problemas ``code`` con esa gravedad y esos arreglos."""

    def register(fn: RuleFn) -> RuleFn:
        if code in RULES:
            raise ValueError(f"código de validación repetido: {code}")
        RULES[code] = RuleSpec(code, severity, scope, tuple(fixes), fn, fn.__module__.rsplit(".", 1)[-1])
        return fn

    return register


def discover_rules() -> dict[str, RuleSpec]:
    """Importa ``core/validate/rules/*`` y devuelve el registro (por código)."""
    from . import rules as package

    for info in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{package.__name__}.{info.name}")
    return dict(RULES)


def make_problem(code: str, rel: VPath | None, line: int | None = None, column: int | None = None, *,
                 entity: tuple[str, str] | None = None, field: tuple[str, ...] = (), **args) -> Problem:
    """``Problem`` de un código registrado, con su gravedad y sus arreglos (``KeyError`` si no lo está)."""
    spec = RULES[code]
    return Problem(code, spec.severity, rel, line, column, entity, tuple(field), MappingProxyType(dict(args)),
                   False, spec.fixes)
