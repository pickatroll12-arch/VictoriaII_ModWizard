"""Familia «files»: archivos del mod idénticos al juego y rutas que Windows no admite (wizard §11, H15, §24.4).

Solo mira la capa del mod: en la línea base (sin el mod) no da nada.

- ``mod_shadow_identical`` (info): un archivo del mod idéntico byte a byte al que
  cargaría el juego sin él (el de la dependencia con más prioridad o, si no hay, el
  del juego): borrarlo no cambia lo que se carga. Una copia idéntica a la del juego
  con una dependencia en medio que trae otra versión sí hace falta. No cuenta en las
  carpetas ocultas por ``replace_path`` (decisión del usuario, wizard §24.4) ni con
  un documento sin guardar. Arreglo: mandar las copias idénticas a la papelera.
  Comparar es caro (942 MB en VSM): ``ValidationContext.identical`` recuerda el
  resultado entre validaciones.
- ``case_collision`` (error): dos archivos del mod que solo difieren en mayúsculas.
- ``windows_reserved_name`` (error): un componente de la ruta que Windows rechaza.
- ``path_too_long`` (aviso): la ruta absoluta pasa de ``MAX_PATH_WARNING``.
"""

from __future__ import annotations

from ...cancel import raise_if_cancelled
from ...clausewitz import Severity
from ...vfs.model import LayerKind, winner
from ...vfs.paths import DESCRIPTOR_REL, long_path_problem, windows_name_problems
from ..registry import SCOPE_FILE, make_problem, rule


def mod_entries(ctx):
    """Entradas de la capa del mod (todas, también las que no ganan), sin el descriptor."""
    for key, stack in sorted(ctx.snapshot.entries.items()):
        if key == DESCRIPTOR_REL.key:
            continue
        for entry in stack:
            if entry.layer.kind is LayerKind.MOD:
                yield key, stack, entry


def without_mod(stack, hidden: bool):
    """La entrada que cargaría el juego si el mod no tuviera ese archivo (None si ninguna)."""
    return winner([e for e in stack if e.layer.kind is not LayerKind.MOD], hidden)


def identical_copies(ctx) -> list:
    """``(entrada del mod, entrada que ganaría sin ella)`` de cada copia idéntica que se puede mandar a la papelera
    (la segunda es del juego o de una dependencia)."""
    found = []
    hidden = ctx.snapshot.hidden
    for key, stack, entry in mod_entries(ctx):
        raise_if_cancelled(ctx.cancelled)
        if ctx.unsaved(entry.rel) or key in hidden:
            continue
        below = without_mod(stack, key in hidden)
        if below is not None and ctx.identical(entry, below):
            found.append((entry, below))
    return found


@rule("mod_shadow_identical", Severity.INFO, scope=SCOPE_FILE, fixes=("trash_identical_copies",))
def shadow_identical(ctx):
    return [make_problem("mod_shadow_identical", entry.rel, file=entry.rel.name)
            for entry, _ in identical_copies(ctx) if ctx.wants(entry.rel)]


@rule("case_collision", Severity.ERROR, scope=SCOPE_FILE)
@rule("windows_reserved_name", Severity.ERROR, scope=SCOPE_FILE)
@rule("path_too_long", Severity.WARNING, scope=SCOPE_FILE)
def windows_paths(ctx):
    problems = []
    for key, stack, entry in mod_entries(ctx):
        if not ctx.wants(entry.rel):
            continue
        same_layer = [e for e in stack if e.layer.kind is LayerKind.MOD]
        if len(same_layer) > 1 and entry is same_layer[1]:
            problems.append(make_problem("case_collision", entry.rel, other=str(same_layer[0].rel)))
        for part in entry.rel.parts:
            if windows_name_problems(part):
                problems.append(make_problem("windows_reserved_name", entry.rel, folder=part))
                break
        if long_path_problem(entry.path) is not None:
            problems.append(make_problem("path_too_long", entry.rel, length=len(str(entry.path))))
    return problems
