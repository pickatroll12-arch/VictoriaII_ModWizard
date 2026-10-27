"""Familia «decisions»: decisiones repetidas y sin imagen (wizard §11, H21).

- ``decision_duplicate`` (error): el mismo nombre de decisión en dos sitios.
- ``decision_picture_missing`` (aviso): ni ``gfx/pictures/decisions/<picture>`` ni
  ``<id>`` (la imagen por defecto) existen con ``.dds`` o ``.tga`` (vanilla: 4,
  heredados).

Las decisiones que no cierran ``political_decisions`` son ``unclosed_block`` de la
familia «syntax», con el arreglo «Añadir ``}`` al final».
"""

from __future__ import annotations

from ...clausewitz import Severity
from ...index import model as m
from ..registry import make_problem, rule

E, W = Severity.ERROR, Severity.WARNING
PICTURE_FOLDER = "gfx/pictures/decisions"
PICTURE_SUFFIXES = (".dds", ".tga")


def picture_candidates(name: str) -> list[str]:
    base = name.strip().replace("\\", "/").lower()
    if base.endswith(PICTURE_SUFFIXES):
        base = base.rsplit(".", 1)[0]
    if "/" not in base:
        base = f"{PICTURE_FOLDER}/{base}"
    return [base + suffix for suffix in PICTURE_SUFFIXES]


@rule("decision_duplicate", E)
@rule("decision_picture_missing", W)
def decisions(ctx):
    index = ctx.index
    problems = []
    has_images = bool(index.names(m.KIND_IMAGE))
    for name in index.names(m.KIND_DECISION):
        definitions = index.effective(m.KIND_DECISION, name)
        entity = (m.KIND_DECISION, name)
        for other in definitions[1:]:
            problems.append(make_problem("decision_duplicate", other.rel, other.line, entity=entity, decision=name,
                                         other=str(definitions[0].rel)))
        decision = definitions[0]
        picture = decision.attrs.get("picture") or name
        if has_images and not any(index.exists(m.KIND_IMAGE, c) for c in picture_candidates(str(picture))):
            problems.append(make_problem("decision_picture_missing", decision.rel, decision.line, entity=entity,
                                         decision=name, picture=str(picture)))
    return problems
