"""Sección «Cambios pendientes» (wizard §13.1, D13): lo que escribiría Guardar ahora, con su diff.

Siempre a mano: muestra el ``ChangeSet`` de ``Session.changeset`` (se recalcula al
cambiar los documentos, pero solo con la sección a la vista, porque renderiza
todos los documentos sin guardar) y permite guardar (``save_requested``: la
ventana decide si hace falta la revisión previa) o descartar los cambios de un
archivo (``Workspace.revert`` dentro de una transacción, así que se deshace).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton, QStackedWidget, QWidget

from ....core.clausewitz import SourceMismatchError
from ....core.encoding import UnencodableTextError
from ....i18n import N_, tr
from ...pages.base import BasePage
from ...shell.pending_changes import PendingChangesPanel, write_label
from ...widgets import EmptyState, StatusBadge, make_icon, show_in_stack


class PendingChangesPage(BasePage):
    key = "pending"
    title_key = N_("section.project.pending")
    subtitle_key = N_("pending.subtitle")
    icon_name = "scroll_seal"

    save_requested = Signal()

    def __init__(self, session, parent: QWidget | None = None):
        self.session = session
        self._stale = True
        self._error: str | None = None
        super().__init__(parent)
        # Métodos y no lambdas: Qt corta la conexión cuando la página se destruye (la sesión puede vivir más).
        for signal in (session.documentsChanged, session.dirtyChanged, session.projectOpened, session.saved):
            signal.connect(self._on_session_changed)
        session.projectClosed.connect(self.mark_stale)

    def _on_session_changed(self, *args) -> None:
        self.mark_stale()

    def build(self) -> None:
        self.revert_button = QPushButton()
        self.revert_button.setObjectName("pendingRevert")
        self.revert_button.setIcon(make_icon("refresh", "gold_light"))
        self.revert_button.clicked.connect(self.revert_selected)
        self.header.trailing.addWidget(self.revert_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.save_button = QPushButton()
        self.save_button.setObjectName("pendingSave")
        self.save_button.setProperty("accent", True)
        self.save_button.setIcon(make_icon("save", "gold_pale"))
        self.save_button.clicked.connect(self.save_requested.emit)
        self.header.trailing.addWidget(self.save_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.error_badge = StatusBadge()
        self.error_badge.setVisible(False)
        self.body.addWidget(self.error_badge)
        self.stack = QStackedWidget()
        self.empty = EmptyState("scroll_seal")
        self.stack.addWidget(self.empty)
        self.panel = PendingChangesPanel()
        self.panel.selection_changed.connect(lambda write: self._update_buttons())
        self.stack.addWidget(self.panel)
        self.body.addWidget(self.stack, 1)
        show_in_stack(self.stack, self.empty)

    def mark_stale(self) -> None:
        self._stale = True
        if self.isVisible():
            self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._stale:
            self.refresh()

    def refresh(self) -> None:
        self._stale = False
        self._error = None
        try:
            changeset = self.session.changeset()
        except (UnencodableTextError, SourceMismatchError) as exc:
            # Un documento que no se puede escribir sin pérdidas: Guardar lo dirá también, sin tocar el disco.
            changeset = None
            self._error = str(exc)
        if changeset is None or not changeset.writes:
            show_in_stack(self.stack, self.empty)
        else:
            self.panel.set_changeset(changeset)
            show_in_stack(self.stack, self.panel)
        self.retranslate()

    def revert_selected(self) -> bool:
        write = self.panel.current_write()
        if write is None or self.session.project is None:
            return False
        with self.session.edit(N_("pending.undo_revert"), name=write_label(write)):
            self.session.project.ws.revert(write.rel)
        self.request_status("pending.status_reverted", name=write_label(write))
        return True

    def _update_buttons(self) -> None:
        has_changes = self.stack.currentWidget() is self.panel
        self.save_button.setEnabled(has_changes and not self.session.is_read_only())
        write = self.panel.current_write() if has_changes else None
        self.revert_button.setEnabled(write is not None and write.action.value != "create")

    def retranslate(self) -> None:
        super().retranslate()
        self.save_button.setText(tr("pending.save"))
        self.save_button.setToolTip(tr("pending.save_tooltip"))
        self.revert_button.setText(tr("pending.revert"))
        self.revert_button.setToolTip(tr("pending.revert_tooltip"))
        if self.session.project is None:
            self.empty.set_texts(tr("pending.empty_title"), tr("pending.no_project"))
        else:
            self.empty.set_texts(tr("pending.empty_title"), tr("pending.empty_text"))
        self.error_badge.setVisible(self._error is not None)
        if self._error is not None:
            self.error_badge.set_status("error", tr("pending.render_error", error=self._error))
        self.panel.retranslate()
        self._update_buttons()
