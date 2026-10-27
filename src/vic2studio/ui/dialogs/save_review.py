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
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
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
PROBLEMS_MAX_HEIGHT = 180   # con muchos problemas, se desplazan: la lista de cambios y los botones siguen a la vista


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
        self.problems_area = QScrollArea()
        self.problems_area.setObjectName("reviewProblems")
        self.problems_area.setFrameShape(QFrame.Shape.NoFrame)
        self.problems_area.setWidgetResizable(True)
        self.problems_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.problems_area.viewport().setAutoFillBackground(False)
        problems_box = QWidget()
        problems_box.setAutoFillBackground(False)
        problems_column = QVBoxLayout(problems_box)
        problems_column.setContentsMargins(0, 0, 0, 0)
        problems_column.setSpacing(layout.spacing())
        for _ in self.problems:
            badge = StatusBadge()
            mark_data(badge.label)  # el texto viene del núcleo, ya traducido
            problems_column.addWidget(badge)
            self.problem_badges.append(badge)
        self.problems_area.setWidget(problems_box)
        layout.addWidget(self.problems_area)
        # Después de meterla en el diálogo: sin padre, setVisible(True) la mostraría como ventana suelta.
        self.problems_area.setVisible(bool(self.problems))
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
        # «Resolver» solo entra en la caja si hay conflictos: hasta Qt 6.6, QDialogButtonBox vuelve a mostrar sus
        # botones cada vez que los recoloca (hoja de estilo, idioma) y un setVisible(False) no duraría.
        if any(p.code == SAVE_CONFLICT for p in self.problems):
            self.buttons.addButton(self.resolve_button, QDialogButtonBox.ButtonRole.ActionRole)
        else:
            self.resolve_button.setParent(self)
            self.resolve_button.hide()
        self.buttons.addButton(self.save_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        self.save_button.setEnabled(not blocking)
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
        self._fit_problems()
        self.save_button.setText(tr("review.save"))
        self.resolve_button.setText(tr("review.resolve"))
        self.cancel_button.setText(tr("review.cancel"))
        self.panel.retranslate()

    def _fit_problems(self) -> None:
        """Alto de la lista de problemas: el de su contenido al ancho actual, como mucho ``PROBLEMS_MAX_HEIGHT``."""
        if not self.problem_badges:
            return
        column = self.problems_area.widget().layout()
        width = self.problems_area.width()
        height = column.totalHeightForWidth(width) if column.hasHeightForWidth() else column.sizeHint().height()
        self.problems_area.setFixedHeight(min(height, PROBLEMS_MAX_HEIGHT))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_problems()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_problems()
        self.panel.tree.setFocus(Qt.FocusReason.OtherFocusReason)
