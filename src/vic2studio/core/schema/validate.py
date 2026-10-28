"""Validación propia del motor de esquemas (wizard §10, §10.10).

Los validadores de un esquema se registran con ``@validator(código,
gravedad)`` y reciben ``(record, ctx)``; producen problemas con ``issue``, que
usa el mismo ``Problem`` de ``core/validate/model.py`` (los textos van en
``core/schemas/texts/<kind>.<es|en>.json`` con la regla de REGLAS.md §4:
``issue.<código>``, ``explain.title.<código>`` y ``explain.outcome.<código>``
en ES y EN). ``CheckContext`` une lo que un validador necesita sin tocar disco
por su cuenta (I4).

La fase 1 entrega el registro de validadores y ``issue``; el recorrido de
campos de un ``Record`` llega en la fase 2.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..clausewitz.diagnostics import Severity
from ..validate.model import Problem
if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..locsync import LocSync
    from ..project.workspace import Workspace
    from .record import Record

_SEVERITIES = {"error": Severity.ERROR, "warning": Severity.WARNING, "info": Severity.INFO}

# código -> gravedad declarada por @validator
VALIDATORS: dict[str, Severity] = {}

RecordValidator = Callable[["Record", "CheckContext"], "Iterable[Problem]"]


def validator(code: str, severity: str = "error"):
    """Decorador: registra ``fn`` como validador que produce ``code`` con esa gravedad
    (``"error"``, ``"warning"`` o ``"info"``). Un código no puede registrarse dos veces."""

    if severity not in _SEVERITIES:
        raise ValueError(f"gravedad desconocida: {severity!r} (error, warning o info)")

    def register(fn: Callable) -> Callable:
        if code in VALIDATORS:
            raise ValueError(f"código de validador repetido: {code}")
        VALIDATORS[code] = _SEVERITIES[severity]
        return fn

    return register


def issue(code: str, rec: Record, *, field: tuple[str, ...] = (), **args) -> Problem:
    """``Problem`` de ``code`` sobre ``rec``: rel, línea y entidad salen del registro; la
    gravedad, del ``@validator`` que lo registró (``error`` si el código es desconocido).

    ``field`` es la ruta del campo dentro de la entidad (``("duration",)``). Los ``args`` son
    los del mensaje ``issue.<código>``.
    """
    severity = VALIDATORS.get(code, Severity.ERROR)
    rel = rec.handle.rel
    line = column = None
    if field:
        node = rec.node(field[0])
        if node is not None:
            line, column = node.line, node.column
    elif rec.block.line is not None:
        line, column = rec.block.line, rec.block.column
    entity = (rec.ref.kind, rec.ref.ident)
    return Problem(code, severity, rel, line, column, entity, field, args)


@dataclass(frozen=True)
class CheckContext:
    """Contexto inmutable de lectura para tipos, campos, compañeros y validadores: el
    ``Workspace`` (solo lectura), el índice, la localización y las reglas del juego. Leer a
    través de él no escribe nada (I4)."""

    ws: Workspace
    index: object
    loc: LocSync
    rules: object = None
    languages: tuple[str, ...] = ("es", "en")
