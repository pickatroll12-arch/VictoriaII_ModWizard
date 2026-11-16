"""Familia «history» (iteración 6): guerras de inicio (wizard §14.8).

- ``wargoal_actor_not_in_war`` (error): el ``actor`` o el ``receiver`` de un ``war_goal`` no está en la guerra
  (ni como atacante ni como defensor).
- ``wargoal_state_required`` (aviso): el CB del objetivo pide un estado (``po_demand_state`` o
  ``po_transfer_provinces``) y el objetivo no lleva ``state_province_id``.
- ``war_dates_order`` (error): un TAG sale de la guerra antes de entrar (o el mismo día) o sale sin haber entrado.
- ``war_inactive_at_bookmarks`` (aviso): la guerra no está activa en ninguna fecha de inicio (termina antes de la
  primera o empieza después de ``end_date``). Vanilla: la de independencia americana (heredado).

Un CB que no existe es ``cb_unknown`` y un TAG sin registrar es ``tag_not_registered`` (las dos ya miraban las
guerras): no se repiten aquí con otro código.
"""

from __future__ import annotations

from ...clausewitz import Severity
from ...domain.war import WARS_FOLDER, _date_key, read_war
from ...index import model as m
from ..registry import make_problem, rule

E, W = Severity.ERROR, Severity.WARNING
STATE_POS = frozenset({"po_demand_state", "po_transfer_provinces"})


def _wars(ctx):
    for rel in ctx.rels(WARS_FOLDER, "*.txt"):
        parsed = ctx.parse(rel)
        if parsed is not None:
            yield rel, read_war(parsed.document, rel.name.rsplit(".", 1)[0])


@rule("wargoal_actor_not_in_war", E)
@rule("wargoal_state_required", W)
def war_goals(ctx):
    index = ctx.index
    problems = []
    for rel, war in _wars(ctx):
        inside = war.participants()
        for goal in war.goals:
            for role in ("actor", "receiver"):
                tag = getattr(goal, role)
                if tag and tag.upper() not in inside:
                    problems.append(make_problem("wargoal_actor_not_in_war", rel, goal.line, field=(role,),
                                                 entity=(m.KIND_TAG, tag.upper()), war=war.name, tag=tag, role=role))
            cb = index.get(m.KIND_CB, goal.casus_belli) if goal.casus_belli else None
            options = set((cb.attrs or {}).get("po") or ()) if cb is not None else set()
            if options & STATE_POS and "po_annex" not in options and goal.state_province_id is None:
                problems.append(make_problem("wargoal_state_required", rel, goal.line, field=("state_province_id",),
                                             war=war.name, cb=goal.casus_belli))
    return problems


@rule("war_dates_order", E)
@rule("war_inactive_at_bookmarks", W)
def war_dates(ctx):
    rules = ctx.rules
    bookmarks = [str(d) for d in (getattr(rules, "bookmarks", ()) or ())] or [str(ctx.start_date)]
    end_date = str(getattr(rules, "end_date", "") or "")
    problems = []
    for rel, war in _wars(ctx):
        joined: dict[str, str] = {}
        for event in sorted(war.events, key=lambda e: _date_key(e.date)):
            tag = event.tag.upper()
            if event.action.startswith("add_"):
                joined.setdefault(tag, event.date)
            elif tag not in joined or _date_key(event.date) <= _date_key(joined[tag]):
                problems.append(make_problem("war_dates_order", rel, event.line, entity=(m.KIND_TAG, tag),
                                             war=war.name, tag=tag, date=event.date,
                                             start=joined.get(tag, "—")))
        start = war.start
        if start is None:
            continue
        active = any(war.active_at(date) for date in bookmarks)
        late = bool(end_date) and _date_key(start) > _date_key(end_date)
        if not active or late:
            problems.append(make_problem("war_inactive_at_bookmarks", rel, None, war=war.name, start=start,
                                         end=war.end or "—", dates=", ".join(bookmarks)))
    return problems
