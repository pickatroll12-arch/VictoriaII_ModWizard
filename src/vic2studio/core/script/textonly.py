"""Archivos con errores de sintaxis: modo texto con diagnóstico y arreglo (wizard D17, §14.5).

Un archivo Clausewitz con errores de sintaxis se abre de **solo texto**: el ``Workspace`` ya lo marca con
``DocHandle.read_only_reason == READ_ONLY_PARSE_ERRORS`` y ``ws.touch`` lanza ``ReadOnlyDocumentError``, así
que ningún formulario ni constructor puede editarlo (una edición estructural junto a un error de sintaxis se
relee distinta en un 10 % de los casos, CONTINUAR §6). Solo se puede sustituir su texto entero, que es lo que
hace el editor de texto (``ScriptEditor``) y el arreglo ``add_closing_brace``.

Lo que fija este módulo para los editores de entidades (criterio 4 de la iteración 7):

1. ``Entities.list`` **sí** lista los registros que el parser tolerante encuentra en un archivo roto, y
   ``Entities.open`` los abre para leer (vista previa, frases). Toda mutación sobre ellos lanza
   ``ReadOnlyDocumentError`` sin cambiar nada.
2. Al elegir un registro, la interfaz pregunta ``text_only_state(ws, rel)``. Si no es None, en lugar del
   formulario enseña el editor de texto del archivo en la línea del primer diagnóstico, con sus mensajes y
   un botón por cada arreglo de ``state.fixes``.
3. El botón aplica ``state.fixes[0]`` sobre ``state.problem`` con el mecanismo de arreglos de la
   iteración 3 (``Session.plan_fix``/``apply_fix`` → ``core.validate.fixes``): una transacción, un Ctrl+Z.
4. Tras el arreglo (o tras corregir a mano en el editor de texto), ``documentsChanged`` hace que la
   interfaz vuelva a preguntar: con ``None`` el formulario se habilita.

Hechos del corpus: los 111 archivos de eventos y decisiones de vanilla no tienen errores de sintaxis. De
los 4 archivos de decisiones del mod del usuario, 2 tienen exactamente un error, ``unclosed_block`` en 1:23
(la llave de ``political_decisions`` sin cerrar); el parser tolerante lee igualmente sus decisiones (1 y 3).
Uno de ellos trae además un ``suspicious_close_brace``, que es información y no bloquea.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..clausewitz.diagnostics import Diagnostic
    from ..project.workspace import Workspace
    from ..schema.record import Entities, RecordRef
    from ..validate.model import Problem
    from ..vfs.paths import VPath

FIX_ADD_CLOSING_BRACE = "add_closing_brace"   # clave de ``core.validate.fixes.FIXES`` («Añadir } al final»)
UNCLOSED_BLOCK = "unclosed_block"


@dataclass(frozen=True)
class TextOnlyState:
    """Por qué un archivo solo se puede editar como texto.

    ``reason``: ``READ_ONLY_PARSE_ERRORS`` o ``READ_ONLY_UNREADABLE`` (``core.project.model``).
    ``diagnostics``: los errores que lo bloquean, por línea, con su mensaje ES/EN (``Diagnostic.message``).
    ``problem``: el ``Problem`` del primer error, como lo daría la regla de sintaxis (con sus ``fixes``),
    para pasarlo a ``plan_fix``/``apply_fix``. ``fixes``: los arreglos que **habilitan el formulario** de
    una vez: ``("add_closing_brace",)`` solo cuando todos los errores son ``unclosed_block``; vacío si hay
    que corregir a mano.
    """

    rel: VPath
    reason: str
    diagnostics: tuple[Diagnostic, ...]
    problem: Problem | None = None
    fixes: tuple[str, ...] = ()

    @property
    def line(self) -> int | None:
        """Línea del primer diagnóstico (donde se coloca el editor de texto); None si no hay."""
        return self.diagnostics[0].line if self.diagnostics else None


def text_only_state(ws: Workspace, rel: VPath) -> TextOnlyState | None:
    """El estado de solo texto del documento efectivo de ``rel``; None si admite formulario (también si
    es de solo lectura por otro motivo: proyecto bloqueado, binario). Lee a través del ``Workspace`` (I7:
    lo que cuenta es lo que hay en memoria) y no escribe nada (I4). ``FileNotFoundError`` si no existe."""
    from dataclasses import replace
    from types import MappingProxyType

    from ..clausewitz.diagnostics import Severity
    from ..project.model import READ_ONLY_PARSE_ERRORS, READ_ONLY_UNREADABLE
    from ..validate.model import SOURCE_CLAUSEWITZ
    from ..validate.registry import RULES, make_problem

    handle = ws.peek(rel) or ws.open(rel)
    reason = handle.read_only_reason
    if reason not in (READ_ONLY_PARSE_ERRORS, READ_ONLY_UNREADABLE):
        return None
    diagnostics = tuple(sorted((d for d in (handle.diagnostics or ()) if d.severity is Severity.ERROR),
                               key=lambda d: (d.line, d.column)))
    problem = None
    if diagnostics:
        first = diagnostics[0]
        code = first.code if first.code in RULES else "check_failed"
        problem = make_problem(code, handle.rel, first.line, first.column)
        problem = replace(problem, args=MappingProxyType({**first.args, "source": SOURCE_CLAUSEWITZ}))
    fixes: tuple[str, ...] = ()
    if reason == READ_ONLY_PARSE_ERRORS and diagnostics and all(d.code == UNCLOSED_BLOCK for d in diagnostics):
        fixes = (FIX_ADD_CLOSING_BRACE,)
    return TextOnlyState(handle.rel, reason, diagnostics, problem, fixes)


def text_only_of(entities: Entities, ref: RecordRef) -> TextOnlyState | None:
    """Lo mismo para el archivo efectivo del registro ``ref``."""
    rel = ref.rel
    if rel is None:
        record = entities.open(ref)
        handle = getattr(record, "handle", None)
        rel = getattr(handle, "rel", None)
        if rel is None:
            return None
    return text_only_state(entities.ws, rel)
