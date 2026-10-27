"""Panel acoplable «Historial»: los pasos que se pueden deshacer, el más reciente arriba (wizard §6.3, §13.2).

Cada paso es una transacción con nombre (``UndoStep.label`` es una clave del
catálogo con su formato: «Editar «name» del descriptor»). Doble clic en un paso
deshace hasta dejarlo como el último hecho. El historial no se guarda en disco.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr, translator
from .. import theme
from ..widgets import make_icon


def step_text(label: str, fmt: dict) -> str:
    return tr(label, **fmt)


class HistoryDock(QDockWidget):
    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("historyDock")
        self.session = session
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        body = QWidget()
        body.setProperty("surface", "parchment")
        body.setAutoFillBackground(True)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)
        self.hint = QLabel()
        self.hint.setProperty("role", "caption")
        self.hint.setFont(theme.font("caption"))
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.list = QListWidget()
        self.list.setObjectName("historyList")
        self.list.itemActivated.connect(self._on_activated)
        layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        self.undo_button = QPushButton()
        self.undo_button.setObjectName("historyUndo")
        self.undo_button.setIcon(make_icon("undo", "gold_light"))
        self.undo_button.clicked.connect(session.undo)
        self.redo_button = QPushButton()
        self.redo_button.setObjectName("historyRedo")
        self.redo_button.setIcon(make_icon("redo", "gold_light"))
        self.redo_button.clicked.connect(session.redo)
        buttons.addWidget(self.undo_button)
        buttons.addWidget(self.redo_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.setWidget(body)
        # Métodos y no lambdas: Qt corta la conexión cuando el panel se destruye (la sesión puede vivir más).
        session.undoChanged.connect(self.refresh)
        session.projectOpened.connect(self._on_project_opened)
        session.projectClosed.connect(self.refresh)
        translator().languageChanged.connect(self._on_language_changed)
        self.retranslate()

    def _on_project_opened(self, project) -> None:
        self.refresh()

    def _on_language_changed(self, code: str) -> None:
        self.retranslate()

    def refresh(self) -> None:
        self.list.clear()
        for label, fmt in self.session.history():
            item = QListWidgetItem(make_icon("history", "ink_soft", "cream"), step_text(label, fmt))
            item.setData(Qt.ItemDataRole.UserRole, (label, dict(fmt)))
            self.list.addItem(item)
        self.undo_button.setEnabled(self.session.can_undo())
        self.redo_button.setEnabled(self.session.can_redo())
        self.hint.setText(tr("history.hint") if self.list.count() else tr("history.empty"))

    def _on_activated(self, item: QListWidgetItem) -> None:
        # Deshace los pasos posteriores al elegido: queda él como el último hecho.
        for _ in range(self.list.row(item)):
            if self.session.undo() is None:
                break

    def retranslate(self) -> None:
        self.setWindowTitle(tr("history.title"))
        self.undo_button.setText(tr("shell.undo"))
        self.redo_button.setText(tr("shell.redo"))
        self.refresh()
