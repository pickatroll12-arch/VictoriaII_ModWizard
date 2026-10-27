"""``Validator``: ejecuta las reglas sobre un contexto y marca los heredados (wizard §11, I10, I11).

Validar nunca bloquea guardar (I10) ni escribe nada (I4). Una regla que lanza no
aborta la validación: su fallo sale como un ``Problem`` ``check_failed`` y se
registra en el log. Lanza ``core.cancel.Cancelled``.
"""

from __future__ import annotations

from collections.abc import Callable, Collection

from ..cancel import CancelCheck
from ..vfs.paths import VPath
from .context import ValidationContext
from .model import ValidationReport


class Validator:
    def __init__(self, ctx: ValidationContext, *, baseline: frozenset[tuple] | None = None) -> None:
        """``baseline``: huellas de ``compute_baseline`` (None = sin línea base todavía: nada se marca heredado y
        el informe lleva ``baseline_ready=False``)."""
        raise NotImplementedError

    def validate(self, *, codes: Collection[str] | None = None, files: Collection[VPath] | None = None,
                 progress: Callable[[int, int], None] | None = None,
                 cancelled: CancelCheck = None) -> ValidationReport:
        """Todas las reglas (o solo ``codes``); ``files`` limita las de ``SCOPE_FILE`` a esos archivos.
        ``progress(reglas hechas, total)``."""
        raise NotImplementedError
