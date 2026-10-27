"""Conflicto con un cambio externo (wizard §6.5): el archivo cambió fuera del Studio desde que se leyó.

Tres salidas: «Conservar mis cambios» (``Workspace.accept_external``: el próximo
guardado sobrescribe el cambio externo, con su ``.bak``), «Recargar del disco»
(``Workspace.reload``: se pierden los cambios en memoria de ese archivo) y
«Comparar», que muestra aquí mismo el diff entre el disco y la memoria
(``Workspace.external_diff``). ``choice`` dice qué se eligió (``KEEP``, ``RELOAD``
o None si se cerró sin decidir); el diálogo no toca el proyecto: lo hace quien lo
abre, a través de ``Session``.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from .. import theme
from ..shell.pending_changes import DiffHighlighter
from ..widgets import mark_data

KEEP = "keep"
RELOAD = "reload"


class ConflictDialog(QDialog):
    def __init__(self, name: str, diff: Callable[[], str], *, dirty: bool = True, deleted: bool = False,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("conflictDialog")
        self.name = name
        self.dirty = dirty
        self.deleted = deleted
        self._diff = diff
        self.choice: str | None = None
        self.setMinimumSize(560, 360)  # explícito: el layout no lo cambia con la ventana ya creada
        self.resize(760, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        self.title = QLabel()
        self.title.setProperty("role", "title")
        self.title.setFont(theme.font("title", 16))
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.text = QLabel()
        self.text.setWordWrap(True)
        layout.addWidget(self.text)
        self.diff_view = QPlainTextEdit()
        self.diff_view.setObjectName("conflictDiff")
        self.diff_view.setReadOnly(True)
        self.diff_view.setFont(theme.font("mono"))
        self.diff_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.diff_view.setVisible(False)
        mark_data(self.diff_view)
        self.highlighter = DiffHighlighter(self.diff_view.document())
        layout.addWidget(self.diff_view, 1)
        layout.addStretch(0)
        self.buttons = QDialogButtonBox()
        self.keep_button = QPushButton()
        self.keep_button.setObjectName("conflictKeep")
        self.keep_button.setProperty("accent", True)
        self.reload_button = QPushButton()
        self.reload_button.setObjectName("conflictReload")
        self.compare_button = QPushButton()
        self.compare_button.setObjectName("conflictCompare")
        self.cancel_button = QPushButton()
        self.cancel_button.setObjectName("conflictCancel")
        self.buttons.addButton(self.compare_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.buttons.addButton(self.reload_button, QDialogButtonBox.ButtonRole.DestructiveRole)
        self.buttons.addButton(self.keep_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        self.keep_button.clicked.connect(lambda: self._choose(KEEP))
        self.reload_button.clicked.connect(lambda: self._choose(RELOAD))
        self.compare_button.clicked.connect(self.compare)
        self.cancel_button.clicked.connect(self.reject)
        self.reload_button.setEnabled(not deleted)
        self.compare_button.setEnabled(not deleted)
        layout.addWidget(self.buttons)
        self.retranslate()

    def _choose(self, choice: str) -> None:
        self.choice = choice
        self.accept()

    def compare(self) -> None:
        self.diff_view.setPlainText(self._diff() or tr("conflict.no_difference"))
        self.diff_view.setVisible(True)

    def retranslate(self) -> None:
        self.setWindowTitle(tr("conflict.window_title"))
        self.title.setText(tr("conflict.title", name=self.name))
        if self.deleted:
            self.text.setText(tr("conflict.text_deleted", name=self.name))
        else:
            self.text.setText(tr("conflict.text" if self.dirty else "conflict.text_clean", name=self.name))
        self.keep_button.setText(tr("conflict.keep"))
        self.keep_button.setToolTip(tr("conflict.keep_tooltip"))
        self.reload_button.setText(tr("conflict.reload"))
        self.reload_button.setToolTip(tr("conflict.reload_tooltip"))
        self.compare_button.setText(tr("conflict.compare"))
        self.compare_button.setToolTip(tr("conflict.compare_tooltip"))
        self.cancel_button.setText(tr("conflict.cancel"))
