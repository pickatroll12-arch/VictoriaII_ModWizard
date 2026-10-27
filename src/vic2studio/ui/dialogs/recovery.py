"""Recuperación al abrir un proyecto (wizard §6.5, I2, I8).

Explica lo que pasó y deja decidir:

* los guardados que se cortaron a medias y se completaron o se deshicieron al abrir
  (``Project.recovered``: ``RecoveryResult`` con lo restaurado y lo mandado a la
  papelera); solo informa, porque la recuperación ya se hizo;
* las sesiones de autoguardado de una ejecución que murió (``Project.orphan_sessions``):
  «Restaurar» las carga como cambios sin guardar (``Project.restore_session``, se
  deshace en un paso) y «Descartar» las borra.

``decisions`` reúne lo elegido (``{sesión: RESTORE | DISCARD}``); quien abre el diálogo
lo aplica con ``Session``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...i18n import N_, tr
from .. import theme
from ..widgets import StatusBadge, mark_data

RESTORE = "restore"
DISCARD = "discard"
OUTCOME_KEYS = {
    "rolled_back": N_("recovery.outcome_rolled_back"),
    "rolled_forward": N_("recovery.outcome_rolled_forward"),
    "cleaned": N_("recovery.outcome_cleaned"),
    "nothing": N_("recovery.outcome_nothing"),
}


class RecoveryDialog(QDialog):
    def __init__(self, orphan_sessions: list[str], recovered: list | tuple = (), parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("recoveryDialog")
        self.sessions = list(orphan_sessions)
        self.recovered = list(recovered)
        self.decisions: dict[str, str] = {}
        self.setMinimumSize(520, 300)  # explícito: el layout no lo cambia con la ventana ya creada
        self.resize(640, 380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        self.title = QLabel()
        self.title.setProperty("role", "title")
        self.title.setFont(theme.font("title", 16))
        layout.addWidget(self.title)
        self.recovered_badges: list[StatusBadge] = []
        for _ in self.recovered:
            badge = StatusBadge()
            layout.addWidget(badge)
            self.recovered_badges.append(badge)
        self.sessions_intro = QLabel()
        self.sessions_intro.setWordWrap(True)
        layout.addWidget(self.sessions_intro)
        # Después de meterla en el diálogo: sin padre, setVisible(True) la mostraría como ventana suelta.
        self.sessions_intro.setVisible(bool(self.sessions))
        self.rows: list[tuple[QLabel, QPushButton, QPushButton]] = []
        for session in self.sessions:
            row = QHBoxLayout()
            name = mark_data(QLabel(session))
            name.setFont(theme.font("mono"))
            row.addWidget(name, 1)
            restore = QPushButton()
            restore.setObjectName("recoveryRestore")
            restore.setProperty("accent", True)
            discard = QPushButton()
            discard.setObjectName("recoveryDiscard")
            restore.clicked.connect(lambda checked=False, s=session: self._decide(s, RESTORE))
            discard.clicked.connect(lambda checked=False, s=session: self._decide(s, DISCARD))
            row.addWidget(restore)
            row.addWidget(discard)
            layout.addLayout(row)
            self.rows.append((name, restore, discard))
        layout.addStretch(1)
        self.buttons = QDialogButtonBox()
        self.close_button = QPushButton()
        self.close_button.setObjectName("recoveryClose")
        self.buttons.addButton(self.close_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.accepted.connect(self.accept)
        layout.addWidget(self.buttons)
        self.retranslate()

    def _decide(self, session: str, decision: str) -> None:
        self.decisions[session] = decision
        self.retranslate()
        if all(s in self.decisions for s in self.sessions):
            self.accept()

    def retranslate(self) -> None:
        self.setWindowTitle(tr("recovery.window_title"))
        self.title.setText(tr("recovery.title"))
        for badge, result in zip(self.recovered_badges, self.recovered):
            files = ", ".join(str(rel) for rel in (*result.restored, *result.trashed)) or "—"
            badge.set_status("warning", tr(OUTCOME_KEYS.get(result.outcome, "recovery.outcome_nothing"),
                                           txid=result.txid, files=files))
        self.sessions_intro.setText(tr("recovery.sessions_intro", count=len(self.sessions)))
        for session, (name, restore, discard) in zip(self.sessions, self.rows):
            decided = self.decisions.get(session)
            restore.setText(tr("recovery.restore"))
            discard.setText(tr("recovery.discard"))
            restore.setEnabled(decided is None)
            discard.setEnabled(decided is None)
            name.setToolTip(tr("recovery.decided_restore") if decided == RESTORE else
                            tr("recovery.decided_discard") if decided == DISCARD else "")
        self.close_button.setText(tr("recovery.close"))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.accept()
            return
        super().keyPressEvent(event)
