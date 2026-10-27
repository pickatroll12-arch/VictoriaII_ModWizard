"""Diálogos del proyecto: revisión antes de guardar, conflicto externo, recuperación y «Nuevo mod» (wizard §4.1)."""

from .conflict import KEEP, RELOAD, ConflictDialog
from .new_mod import NewModDialog
from .recovery import DISCARD, RESTORE, RecoveryDialog
from .save_review import SaveReviewDialog, needs_review, review_reasons

__all__ = [
    "DISCARD", "KEEP", "RELOAD", "RESTORE", "ConflictDialog", "NewModDialog", "RecoveryDialog", "SaveReviewDialog",
    "needs_review", "review_reasons",
]
