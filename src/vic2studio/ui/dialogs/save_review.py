"""Revisión antes de guardar (wizard D13, §6.5): solo sale si el guardado copia archivos del juego base, manda
algo a la papelera o tiene conflictos o errores.

Explica el motivo arriba, lista lo que se escribirá (con el diff de cada archivo) y,
si los hay, los problemas que impiden guardar (``SaveProblem``: conflictos externos,
nombres que Windows no admite, caracteres que no caben en cp1252...). Con un
problema bloqueante no se puede guardar: el botón «Resolver conflictos…» lleva al
diálogo de conflicto (``resolve_requested``).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.project import ChangeSet, SaveProblem
from ...core.project.model import SAVE_CONFLICT
from ...i18n import N_, language, tr
from .. import theme
from ..shell.pending_changes import PendingChangesPanel
from ..widgets import StatusBadge, mark_data

SIZE = (860, 600)


REASON_CONFLICTS = N_("review.reason_conflicts")
REASON_ERRORS = N_("review.reason_errors")


def review_reasons(changeset: ChangeSet, problems: tuple[SaveProblem, ...] = ()) -> list[tuple[str, dict]]:
    """Por qué hay que revisar (claves del catálogo con formato), en el orden en que se explican."""
    reasons = []
    copies = changeset.copies_from_game
    if copies:
        reasons.append((N_("review.reason_copies_one") if copies == 1 else N_("review.reason_copies"),
                        {"count": copies}))
    if changeset.trashed:
        reasons.append((N_("review.reason_trash"), {"count": changeset.trashed}))
    if any(p.code == SAVE_CONFLICT for p in problems):
        reasons.append((REASON_CONFLICTS, {}))
    if any(p.code != SAVE_CONFLICT for p in problems):
        reasons.append((REASON_ERRORS, {}))
    return reasons


def needs_review(changeset: ChangeSet, problems: tuple[SaveProblem, ...] = ()) -> bool:
    """D13: copias del juego base, papelera, conflictos o errores."""
    return changeset.needs_review or bool(problems)


class SaveReviewDialog(QDialog):
    resolve_requested = Signal(object)   # list[SaveProblem] de conflictos

    def __init__(self, changeset: ChangeSet, problems: tuple[SaveProblem, ...] = (), parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("saveReviewDialog")
        self.changeset = changeset
        self.problems = tuple(problems)
        self.setMinimumSize(640, 440)  # explícito: el layout no lo cambia con la ventana ya creada
        self.resize(*SIZE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        self.title = QLabel()
        self.title.setProperty("role", "title")
        self.title.setFont(theme.font("title", 16))
        layout.addWidget(self.title)
        self.intro = QLabel()
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)
        self.reasons: list[StatusBadge] = []
        for _ in review_reasons(changeset, self.problems):
            badge = StatusBadge()
            layout.addWidget(badge)
            self.reasons.append(badge)
        self.problem_badges: list[StatusBadge] = []
        for _ in self.problems:
            badge = StatusBadge()
            mark_data(badge.label)  # el texto viene del núcleo, ya traducido
            layout.addWidget(badge)
            self.problem_badges.append(badge)
        self.panel = PendingChangesPanel()
        self.panel.set_changeset(changeset)
        layout.addWidget(self.panel, 1)
        self.buttons = QDialogButtonBox()
        self.save_button = QPushButton()
        self.save_button.setObjectName("reviewSave")
        self.save_button.setProperty("accent", True)
        self.save_button.setDefault(True)
        self.resolve_button = QPushButton()
        self.resolve_button.setObjectName("reviewResolve")
        self.cancel_button = QPushButton()
        self.cancel_button.setObjectName("reviewCancel")
        blocking = self.blocking
        self.buttons.addButton(self.resolve_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.buttons.addButton(self.save_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        self.save_button.setEnabled(not blocking)
        self.resolve_button.setVisible(any(p.code == SAVE_CONFLICT for p in self.problems))
        self.resolve_button.clicked.connect(self._on_resolve)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.retranslate()

    @property
    def blocking(self) -> bool:
        return any(p.blocking for p in self.problems)

    def _on_resolve(self) -> None:
        self.resolve_requested.emit([p for p in self.problems if p.code == SAVE_CONFLICT])
        self.reject()

    def retranslate(self) -> None:
        self.setWindowTitle(tr("review.window_title"))
        self.title.setText(tr("review.title"))
        self.intro.setText(tr("review.intro_blocked") if self.blocking else tr("review.intro"))
        for badge, (key, fmt) in zip(self.reasons, review_reasons(self.changeset, self.problems)):
            level = "error" if key in (REASON_CONFLICTS, REASON_ERRORS) else "warning"
            badge.set_status(level, tr(key, **fmt))
        lang = language()
        for badge, problem in zip(self.problem_badges, self.problems):
            badge.set_status("error" if problem.blocking else "warning", problem.message(lang))
        self.save_button.setText(tr("review.save"))
        self.resolve_button.setText(tr("review.resolve"))
        self.cancel_button.setText(tr("review.cancel"))
        self.panel.retranslate()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.panel.tree.setFocus(Qt.FocusReason.OtherFocusReason)
