"""Validación propia del motor de esquemas (wizard §10, §10.10).

Los validadores de un esquema se registran con ``@validator(código,
gravedad)`` y reciben ``(record, ctx)``; producen problemas con ``issue``, que
usa el mismo ``Problem`` de ``core/validate/model.py``. Los textos van en
``core/schemas/texts/<kind>.<es|en>.json`` con la regla de REGLAS.md §4:
``issue.<código>``, ``explain.title.<código>`` y ``explain.outcome.<código>``
en ES y EN. ``CheckContext`` une lo que un validador necesita sin tocar disco
por su cuenta (I4).

Los códigos propios del motor (``unknown_field``, ``bad_type``,
``required_missing``) no tienen función registrada: su gravedad sale de
``SEVERITY_FALLBACK``, y ``duplicate_field`` ya existe en ``core/validate``
(aviso) y se reutiliza con sus textos.
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

# Gravedad de los códigos que el motor emite sin @validator (los textos de unknown_field,
# bad_type y required_missing son del motor; duplicate_field ya está en core/validate).
SEVERITY_FALLBACK = {
    "unknown_field": Severity.WARNING,      # «se conservan y avisan» (unknown = keep_warn, I6)
    "bad_type": Severity.ERROR,
    "required_missing": Severity.ERROR,
    "duplicate_field": Severity.WARNING,    # coincide con core/validate/rules/countries.py
    "unit_never_active": Severity.INFO,     # compañero ActivateUnit (§14.4)
}

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
        fn.validator_code = code   # docgen lo lista en «Comprobaciones propias»
        return fn

    return register


def severity_of(code: str) -> Severity:
    """Gravedad de un código del motor: la de su ``@validator`` o la de ``SEVERITY_FALLBACK``."""
    return VALIDATORS.get(code, SEVERITY_FALLBACK.get(code, Severity.ERROR))


def issue(code: str, rec: Record, *, field: tuple[str, ...] = (), **args) -> Problem:
    """``Problem`` de ``code`` sobre ``rec``: rel, línea y entidad salen del registro; la
    gravedad, del ``@validator`` que lo registró (o de ``SEVERITY_FALLBACK``).

    ``field`` es la ruta del campo dentro de la entidad (``("duration",)``). Los ``args`` son
    los del mensaje ``issue.<código>``.
    """
    rel = rec.handle.rel
    line = column = None
    if field:
        node = rec.node(field[0])
        if node is not None:
            line, column = node.line, node.column
    if line is None:
        # Sin el campo (falta, que es justo el problema): la línea del registro.
        owner = getattr(rec, "_entry", None)
        if owner is not None and owner.line is not None:
            line, column = owner.line, owner.column
        elif rec.block.line is not None:
            line, column = rec.block.line, rec.block.column
    entity = (rec.ref.kind, rec.ref.ident)
    return Problem(code, severity_of(code), rel, line, column, entity, tuple(field), args)


@dataclass(frozen=True)
class CheckContext:
    """Contexto inmutable de lectura para tipos, campos, compañeros y validadores: el
    ``Workspace`` (solo lectura), el índice, la localización y las reglas del juego. Leer a
    través de él no escribe nada (I4).

    En segundo plano (``schema_problems``) no hay ``Workspace`` (``ws`` None, I12): ``source`` es el
    ``ValidationContext`` inmutable, con los bytes efectivos de cada archivo."""

    ws: Workspace
    index: object
    loc: LocSync
    rules: object = None
    languages: tuple[str, ...] = ("es", "en")
    source: object = None


class _DetachedHandle:
    """Lo poco de un ``DocHandle`` que lee ``Record`` en segundo plano: la ruta y el modelo (de solo lectura)."""

    __slots__ = ("rel", "model", "origin", "deleted", "dirty", "kind")

    def __init__(self, rel, model) -> None:
        self.rel = rel
        self.model = model
        self.origin = None
        self.deleted = False
        self.dirty = False
        self.kind = None


def schema_problems(source, *, cancelled=None) -> list[Problem]:
    """Problemas de esquema de todos los registros editables (decisión 3 del informe de la iteración 4).

    ``source`` es un ``ValidationContext`` (instantánea inmutable con lo sin guardar): se puede llamar desde el
    hilo de la validación porque no toca el ``Workspace`` (I12) ni escribe nada (I4). Cada archivo se lee una vez
    con ``source.parse`` (en su caché). Los compañeros que necesitan el ``Workspace`` no dan nada aquí; sus
    códigos ya los da la validación global (``government_missing_in_rebel_map``, ``cb_not_in_peace_order``).

    Un problema en un archivo que no es del mod (el juego o una dependencia que el mod no sustituye) sale
    ``inherited`` (I11): no es del mod.
    """
    from dataclasses import replace as dc_replace

    from ..cancel import raise_if_cancelled
    from ..vfs.model import LayerKind
    from .record import Record, RecordRef
    from .registry import registry

    ctx = CheckContext(None, getattr(source, "index", None), None, source=source)
    found: list[Problem] = []
    for schema in registry.all_schemas():
        if not schema.editable:
            continue
        rels_of = getattr(schema.layout, "context_rels", None)
        if rels_of is None:
            continue
        for rel in rels_of(source):
            raise_if_cancelled(cancelled)
            parsed = source.parse(rel)
            if parsed is None:
                continue
            handle = _DetachedHandle(rel, parsed)
            # Lo sin guardar es del mod aunque venga del juego (se copiará al guardar).
            inherited = not source.unsaved(rel) and source.layer_of(rel) is not LayerKind.MOD
            for ident, block, entry in schema.layout.entries(parsed.document, rel):
                record = Record(schema, RecordRef(schema.kind, ident, rel), handle, block, None,
                                index=ctx.index, entry=entry)
                problems = record.issues(ctx)
                if inherited:
                    problems = [dc_replace(problem, inherited=True) for problem in problems]
                found.extend(problems)
    return found
