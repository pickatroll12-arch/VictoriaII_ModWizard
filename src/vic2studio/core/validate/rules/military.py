"""Familia «military» (parte de la iteración 3): ``peace_order`` de ``cb_types.txt`` (wizard §11, H17).

- ``cb_not_in_peace_order`` (aviso): un CB que no está en ``peace_order``.
- ``peace_order_unknown`` (aviso): un valor de ``peace_order`` que no es un CB
  (vanilla: ``annex``, heredado). Hace falta ya para el criterio 4 de la iteración 3.
"""

from __future__ import annotations

from ...clausewitz import Severity
from ...index import model as m
from ..registry import make_problem, rule

W = Severity.WARNING


@rule("cb_not_in_peace_order", W)
@rule("peace_order_unknown", W)
def peace_order(ctx):
    index = ctx.index
    problems = []
    order = [ref for ref in index.refs(m.KIND_CB) if ref.role == "peace_order"]
    if not order:
        return problems
    for ref in order:
        if not index.exists(m.KIND_CB, ref.name):
            problems.append(make_problem("peace_order_unknown", ref.rel, ref.line, ref.column,
                                         entity=(m.KIND_CB, ref.name), field=("peace_order",), cb=ref.name))
    listed = {ref.name for ref in order}
    for cb in index.symbols(m.KIND_CB):
        if cb.name not in listed:
            problems.append(make_problem("cb_not_in_peace_order", cb.rel, cb.line, entity=(m.KIND_CB, cb.name),
                                         cb=cb.name))
    return problems
