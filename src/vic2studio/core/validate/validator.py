"""``Validator``: ejecuta las reglas sobre un contexto y marca los heredados (wizard §11, I10, I11).

Validar nunca bloquea guardar (I10) ni escribe nada (I4). Una regla que lanza no
aborta la validación: su fallo sale como un ``Problem`` ``check_failed`` y se
registra en el log. Lanza ``core.cancel.Cancelled``.

Cada función de regla se ejecuta una sola vez aunque declare varios códigos
(decoradores apilados); con ``codes`` solo corren las que declaran alguno de ellos
y solo se devuelven esos códigos.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Collection
from dataclasses import replace

from ..cancel import CancelCheck, Cancelled, raise_if_cancelled
from ..clausewitz import Severity
from ..vfs.paths import VPath
from .context import ValidationContext
from .model import SEVERITY_ORDER, Problem, ValidationReport
from .registry import SCOPE_FILE, RuleSpec, discover_rules

_log = logging.getLogger(__name__)

CHECK_FAILED = "check_failed"


def _sort_key(problem: Problem) -> tuple:
    return (SEVERITY_ORDER[problem.severity], problem.rel.key if problem.rel is not None else "",
            problem.line or 0, problem.column or 0, problem.code)


def rule_groups(codes: Collection[str] | None = None) -> list[tuple[Callable, list[RuleSpec]]]:
    """Las funciones de regla con sus códigos, en orden estable (familia, código); con ``codes``, solo las que
    declaran alguno."""
    groups: dict[int, tuple[Callable, list[RuleSpec]]] = {}
    for spec in sorted(discover_rules().values(), key=lambda s: (s.family, s.code)):
        groups.setdefault(id(spec.fn), (spec.fn, []))[1].append(spec)
    selected = list(groups.values())
    if codes is not None:
        wanted = set(codes)
        selected = [group for group in selected if any(spec.code in wanted for spec in group[1])]
    return selected


class Validator:
    def __init__(self, ctx: ValidationContext, *, baseline: frozenset[tuple] | None = None) -> None:
        """``baseline``: huellas de ``compute_baseline`` (None = sin línea base todavía: nada se marca heredado y
        el informe lleva ``baseline_ready=False``)."""
        self.ctx = ctx
        self.baseline = baseline

    def validate(self, *, codes: Collection[str] | None = None, files: Collection[VPath] | None = None,
                 progress: Callable[[int, int], None] | None = None,
                 cancelled: CancelCheck = None) -> ValidationReport:
        """Todas las reglas (o solo ``codes``); ``files`` limita las de ``SCOPE_FILE`` a esos archivos.
        ``progress(reglas hechas, total)``."""
        start = time.perf_counter()
        ctx = self.ctx
        cancelled = cancelled if cancelled is not None else ctx.cancelled
        previous_cancel = ctx.cancelled
        ctx.cancelled = cancelled
        wanted = None if codes is None else set(codes)
        groups = rule_groups(wanted)
        problems: list[Problem] = []
        previous_files = ctx.files
        try:
            for done, (fn, specs) in enumerate(groups):
                raise_if_cancelled(cancelled)
                file_scope = all(spec.scope == SCOPE_FILE for spec in specs)
                ctx.files = None if files is None or not file_scope else {VPath.of(f).key for f in files}
                try:
                    found = list(fn(ctx) or ())
                except Cancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 - una regla rota no tumba la validación (docstring)
                    _log.exception("la regla %s.%s falló", specs[0].family, fn.__name__)
                    found = [_check_failed(specs[0], exc)]
                if wanted is not None:
                    found = [p for p in found if p.code in wanted or p.code == CHECK_FAILED]
                problems.extend(found)
                if progress is not None:
                    progress(done + 1, len(groups))
        finally:
            ctx.files = previous_files
            ctx.cancelled = previous_cancel
        baseline = self.baseline
        if baseline is not None:
            problems = [replace(p, inherited=True) if p.fingerprint() in baseline else p for p in problems]
        problems.sort(key=_sort_key)
        return ValidationReport(tuple(problems), ctx.read_count, time.perf_counter() - start, False,
                                baseline is not None)

    def validate_record(self, rec) -> list[Problem]:
        """Validación en vivo de un registro (iteración 4, con los esquemas): aún no hay validadores por esquema."""
        return []


def _check_failed(spec: RuleSpec, exc: BaseException) -> Problem:
    from types import MappingProxyType

    from .registry import RULES

    severity = RULES[CHECK_FAILED].severity if CHECK_FAILED in RULES else Severity.ERROR
    return Problem(CHECK_FAILED, severity, None, args=MappingProxyType({
        "rule": f"{spec.family}.{spec.fn.__name__}", "error": f"{type(exc).__name__}: {exc}"}))
