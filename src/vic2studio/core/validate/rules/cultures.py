"""Familia «cultures»: el mismo id de cultura dos veces (wizard §14.13, H18).

- ``culture_name_duplicate`` (error): una cultura definida más de una vez en
  ``common/cultures.txt``, en dos grupos o dos veces en el mismo. Las culturas son
  los bloques hijos de cada grupo y se nombran solo por su id (los POPs, las
  historias y ``primary_culture`` no dicen el grupo), así que el id tiene que ser
  único en todo el archivo. Vanilla: 226 culturas en 34 grupos, ninguna repetida.
  Con cuál se queda el juego es [verificar en juego]. Sin arreglo de un clic: cuál
  sobra lo decide el modder.

Sale del índice: cada definición de más da un problema en su línea.
"""

from __future__ import annotations

from ...clausewitz import Severity
from ...index import model as m
from ..registry import make_problem, rule


@rule("culture_name_duplicate", Severity.ERROR)
def culture_names(ctx):
    index = ctx.index
    problems = []
    for name in index.names(m.KIND_CULTURE):
        definitions = index.effective(m.KIND_CULTURE, name)
        first = definitions[0]
        for other in definitions[1:]:
            problems.append(make_problem(
                "culture_name_duplicate", other.rel, other.line, entity=(m.KIND_CULTURE, name), culture=name,
                group=str(other.attrs.get("group", "")), first_group=str(first.attrs.get("group", "")),
                first_line=first.line))
    return problems
