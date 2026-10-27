"""Familia «events»: ids de evento repetidos, fuera de rango o que no existen (wizard §11, H21, D15).

- ``event_id_duplicate`` (error): un id definido más de una vez en la vista
  efectiva (vanilla: 0). Un evento de vanilla copiado a otra ruta del mod lo da.
- ``event_id_invalid`` (error): un id fuera de ``EVENT_ID_RANGE`` (32 bits positivo).
- ``event_ref_missing`` (aviso): ``country_event = X`` o ``province_event = { id = X }``
  sin evento X (vanilla: 11108, heredado).
"""

from __future__ import annotations

from ...clausewitz import Severity
from ...index import model as m
from ...rules.ids import event_id_problem
from ..registry import make_problem, rule

E, W = Severity.ERROR, Severity.WARNING


@rule("event_id_duplicate", E)
@rule("event_id_invalid", E)
def event_ids(ctx):
    index = ctx.index
    problems = []
    for name in index.names(m.KIND_EVENT):
        definitions = index.effective(m.KIND_EVENT, name)
        entity = (m.KIND_EVENT, name)
        if event_id_problem(int(name)) is not None:
            first = definitions[0]
            problems.append(make_problem("event_id_invalid", first.rel, first.line, entity=entity, event=name))
        for other in definitions[1:]:
            problems.append(make_problem("event_id_duplicate", other.rel, other.line, entity=entity, event=name,
                                         other=str(definitions[0].rel)))
    return problems


@rule("event_ref_missing", W)
def event_refs(ctx):
    index = ctx.index
    return [make_problem("event_ref_missing", ref.rel, ref.line, ref.column, entity=(m.KIND_EVENT, ref.name),
                         field=(ref.role,), event=ref.name)
            for ref in index.refs(m.KIND_EVENT) if not index.exists(m.KIND_EVENT, ref.name)]
