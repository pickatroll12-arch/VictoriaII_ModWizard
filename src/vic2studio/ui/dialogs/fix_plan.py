"""Plan de un arreglo (SimpleFix, wizard §11.1, §13.9): qué archivos cambia, cómo y con qué diff, antes de aplicarlo.

Muestra el problema, la etiqueta del arreglo y su ``ChangePlan`` (archivo · acción ·
diff, con el diff coloreado como en «Cambios pendientes»). Nunca se aplica nada sin
aceptar. Un arreglo ``safe=False`` (borra o sustituye) pide además una confirmación
explícita: «Aplicar» no se habilita hasta marcar la casilla, y se recuerda que lo
borrado va a la papelera del proyecto. Aplicar lo hace quien abre el diálogo.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.validate.model import ACTION_COPY_FROM_GAME, ACTION_CREATE, ACTION_MODIFY, ACTION_TRASH
from ...i18n import N_, tr
from .. import theme
from ..shell.pending_changes import DiffHighlighter, lines_text, shown_diff
from ..viewers.common import core_language
from ..widgets import StatusBadge, make_icon, mark_data

ACTION_KEYS = {
    ACTION_CREATE: N_("pending.action.create"), ACTION_MODIFY: N_("pending.action.modify"),
    ACTION_COPY_FROM_GAME: N_("pending.action.copy"), ACTION_TRASH: N_("pending.action.trash"),
}
ACTION_ICONS = {
    ACTION_CREATE: ("file", "success"), ACTION_MODIFY: ("file_text", "ink_soft"),
    ACTION_COPY_FROM_GAME: ("copy", "warning"), ACTION_TRASH: ("error", "danger"),
}
SIZE = (820, 560)


class FixPlanDialog(QDialog):
    """``spec`` es el ``FixSpec``; ``plan`` su ``ChangePlan``. Aceptado = el usuario confirma el arreglo."""

    def __init__(self, spec, problem, plan, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("fixPlanDialog")
        self.spec = spec
        self.problem = problem
        self.plan = plan
        self.setMinimumSize(600, 420)
        self.resize(*SIZE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        self.title = mark_data(QLabel())
        self.title.setObjectName("fixPlanTitle")
        self.title.setProperty("role", "title")
        self.title.setFont(theme.font("title", 16))
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.problem_badge = StatusBadge()
        self.problem_badge.setObjectName("fixPlanProblem")
        mark_data(self.problem_badge.label)   # el mensaje viene del núcleo, ya traducido
        layout.addWidget(self.problem_badge)
        self.intro = QLabel()
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)
        self.warning = StatusBadge()
        self.warning.setObjectName("fixPlanWarning")
        layout.addWidget(self.warning)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.tree = QTreeWidget()
        self.tree.setObjectName("fixPlanFiles")
        self.tree.setColumnCount(3)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(self._show_diff)
        self.splitter.addWidget(self.tree)
        self.diff = QPlainTextEdit()
        self.diff.setObjectName("fixPlanDiff")
        self.diff.setReadOnly(True)
        self.diff.setFont(theme.font("mono"))
        self.diff.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        mark_data(self.diff)
        self.highlighter = DiffHighlighter(self.diff.document())
        self.splitter.addWidget(self.diff)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        layout.addWidget(self.splitter, 1)
        for change in plan.changes:
            item = QTreeWidgetItem()
            item.setData(0, Qt.ItemDataRole.UserRole, change)
            icon, color = ACTION_ICONS.get(change.action, ("file", "ink_soft"))
            item.setIcon(1, make_icon(icon, color, "cream"))
            self.tree.addTopLevelItem(item)
        self.confirm = QCheckBox()
        self.confirm.setObjectName("fixPlanConfirm")
        self.confirm.toggled.connect(self._update_buttons)
        layout.addWidget(self.confirm)
        self.buttons = QDialogButtonBox()
        self.apply_button = QPushButton()
        self.apply_button.setObjectName("fixPlanApply")
        self.apply_button.setProperty("accent", True)
        self.apply_button.setDefault(True)
        self.cancel_button = QPushButton()
        self.cancel_button.setObjectName("fixPlanCancel")
        self.buttons.addButton(self.apply_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        # Después de meterlos en el diálogo: sin padre, setVisible(True) los mostraría como ventanas sueltas.
        self.warning.setVisible(not spec.safe)
        self.confirm.setVisible(not spec.safe)
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self.retranslate()

    def _update_buttons(self, *args) -> None:
        self.apply_button.setEnabled(bool(self.plan.changes) and (self.spec.safe or self.confirm.isChecked()))

    def _show_diff(self, current, previous=None) -> None:
        change = None if current is None else current.data(0, Qt.ItemDataRole.UserRole)
        if change is None:
            self.diff.setPlainText("")
        elif change.action == ACTION_TRASH:
            self.diff.setPlainText(tr("fixplan.trash_note", file=str(change.rel)))
        else:
            self.diff.setPlainText(shown_diff(change.diff))   # el recorte del núcleo, en el idioma de la interfaz

    def retranslate(self) -> None:
        lang = core_language()
        label = self.spec.label(self.problem, lang)
        self.setWindowTitle(tr("fixplan.window_title"))
        self.title.setText(label)
        level = {"error": "error", "warning": "warning"}.get(self.problem.severity.value, "neutral")
        self.problem_badge.set_status(level, self.problem.message(lang))
        count = len(self.plan.changes)
        if count:
            self.intro.setText(tr("fixplan.intro_one" if count == 1 else "fixplan.intro", count=count))
        else:
            self.intro.setText(tr("fixplan.nothing"))
        self.warning.set_status("warning", tr("fixplan.unsafe"))
        self.confirm.setText(tr("fixplan.confirm"))
        self.tree.setHeaderLabels([tr("pending.col.file"), tr("pending.col.action"), tr("pending.col.lines")])
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            change = item.data(0, Qt.ItemDataRole.UserRole)
            item.setText(0, str(change.rel))
            item.setText(1, tr(ACTION_KEYS.get(change.action, "pending.action.modify")))
            # Las del cambio entero (PlannedChange.lines): el diff viene recortado a 400 líneas.
            item.setText(2, "" if change.action == ACTION_TRASH else lines_text(change.diff, change.lines))
        self.apply_button.setText(tr("fixplan.apply"))
        self.cancel_button.setText(tr("fixplan.cancel"))
        self._update_buttons()
