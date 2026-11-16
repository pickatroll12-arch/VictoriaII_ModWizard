"""Pantalla 12 del taller (wizard §18.2 y §18.11): problemas con [Arreglar] y [¿Por qué?], auditoría (§18.9) y
plan de cambios (archivo · acción · clase · tamaño) antes de exportar.

El panel solo enseña y recoge decisiones: el asistente calcula los problemas, el plan y la auditoría, y aplica
los arreglos. Exportar queda bloqueado mientras haya errores o confirmaciones sin marcar.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ...core.clausewitz import Severity
from ...i18n import N_, tr
from ..widgets import make_icon

ACTION_LABELS = {"G": N_("forge.plan.action.generate"), "M": N_("forge.plan.action.modify"),
                 "T": N_("forge.plan.action.trash"), "E": N_("forge.plan.action.empty")}
PLAN_COLUMNS = (N_("forge.plan.col.file"), N_("forge.plan.col.action"), N_("forge.plan.col.class"),
                N_("forge.plan.col.size"))
AUDIT_COLUMNS = (N_("forge.audit.col.folder"), N_("forge.audit.col.role"), N_("forge.audit.col.files"),
                 N_("forge.audit.col.cites"), N_("forge.audit.col.examples"), N_("forge.audit.col.action"))
ROLE_LABELS = {"mod_files": N_("forge.audit.role.mod_files"), "oob": N_("forge.audit.role.oob"),
               "province_id": N_("forge.audit.role.province_id"), "continent": N_("forge.audit.role.continent")}
AUDIT_ACTIONS = {"trash": N_("forge.audit.action.trash"), "empty": N_("forge.audit.action.empty"),
                 "view": N_("forge.audit.action.view"), "ignore": N_("forge.audit.action.ignore")}
# Arreglos que el asistente aplica desde aquí (los de la importación se eligen en su pantalla; el resto, en 9b).
AVAILABLE_FIXES = frozenset({"share_existing_tags", "reduce_target", "discard_edit"})
SEVERITY_ICONS = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "info"}
ROLE_ISSUE = Qt.ItemDataRole.UserRole


def human_size(n: int) -> str:
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f} MiB"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.0f} KiB"
    return f"{n} B"


class ReviewPanel(QWidget):
    renderRequested = Signal()
    fixRequested = Signal(object, str)          # (ForgeIssue, arreglo)
    exportRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.issues: list = []
        self.plan: list = []
        self.groups: list = []
        self._confirm_boxes: dict[str, QCheckBox] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.render_button = QPushButton()
        self.render_button.setObjectName("forgeRenderFinal")
        self.render_button.setIcon(make_icon("refresh", "gold_light"))
        self.render_button.clicked.connect(self.renderRequested)
        top.addWidget(self.render_button)
        self.state_label = QLabel()
        self.state_label.setObjectName("forgeReviewState")
        self.state_label.setWordWrap(True)
        top.addWidget(self.state_label, 1)
        layout.addLayout(top)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("forgeReviewTabs")
        # Problemas
        prob = QWidget()
        pl = QVBoxLayout(prob)
        self.tree = QTreeWidget()
        self.tree.setObjectName("forgeIssues")
        self.tree.setHeaderHidden(True)
        self.tree.setHeaderLabels([""])   # oculta, pero sin el «1» que Qt pone por defecto
        self.tree.setRootIsDecorated(False)
        self.tree.itemSelectionChanged.connect(self._on_selected)
        pl.addWidget(self.tree, 2)
        row = QHBoxLayout()
        self.fix_button = QPushButton()
        self.fix_button.setObjectName("forgeFix")
        self.fix_button.clicked.connect(self._fix)
        self.why_button = QPushButton()
        self.why_button.setObjectName("forgeWhy")
        self.why_button.clicked.connect(self._why)
        row.addWidget(self.fix_button)
        row.addWidget(self.why_button)
        row.addStretch(1)
        pl.addLayout(row)
        self.why_title = QLabel()
        self.why_title.setObjectName("forgeWhyTitle")
        self.why_title.setWordWrap(True)
        self.why_text = QLabel()
        self.why_text.setObjectName("forgeWhyText")
        self.why_text.setWordWrap(True)
        pl.addWidget(self.why_title)
        pl.addWidget(self.why_text)
        self.confirm_box = QVBoxLayout()
        pl.addLayout(self.confirm_box)
        self.tabs.addTab(prob, "")
        # Auditoría
        self.audit = QTableWidget(0, len(AUDIT_COLUMNS))
        self.audit.setObjectName("forgeAudit")
        self._table(self.audit)
        self.tabs.addTab(self.audit, "")
        # Plan
        plan = QWidget()
        planl = QVBoxLayout(plan)
        self.plan_table = QTableWidget(0, len(PLAN_COLUMNS))
        self.plan_table.setObjectName("forgePlan")
        self._table(self.plan_table)
        planl.addWidget(self.plan_table, 1)
        self.plan_summary = QLabel()
        self.plan_summary.setObjectName("forgePlanSummary")
        planl.addWidget(self.plan_summary)
        self.tabs.addTab(plan, "")
        layout.addWidget(self.tabs, 1)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.export_button = QPushButton()
        self.export_button.setObjectName("forgeExport")
        self.export_button.setIcon(make_icon("check", "gold_light"))
        self.export_button.clicked.connect(self.exportRequested)
        bottom.addWidget(self.export_button)
        layout.addLayout(bottom)
        self._update_buttons()

    @staticmethod
    def _table(table: QTableWidget) -> None:
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)

    def retranslate(self) -> None:
        self.render_button.setText(tr("forge.review.render"))
        self.fix_button.setText(tr("forge.review.fix"))
        self.why_button.setText(tr("forge.review.why"))
        self.export_button.setText(tr("forge.review.export"))
        self.tabs.setTabText(0, tr("forge.review.tab.problems", count=len(self.issues)))
        self.tabs.setTabText(1, tr("forge.review.tab.audit", count=sum(g.count for g in self.groups)))
        self.tabs.setTabText(2, tr("forge.review.tab.plan", count=len(self.plan)))
        self.audit.setHorizontalHeaderLabels([tr(k) for k in AUDIT_COLUMNS])
        self.plan_table.setHorizontalHeaderLabels([tr(k) for k in PLAN_COLUMNS])
        self.set_issues(self.issues)
        self.set_audit(self.groups)
        self.set_plan(self.plan)

    # --- datos --------------------------------------------------------------------------------------------

    def set_state(self, text: str) -> None:
        self.state_label.setText(text)

    def set_issues(self, issues: list) -> None:
        self.issues = list(issues)
        self.tree.clear()
        for issue in self.issues:
            item = QTreeWidgetItem([issue.message(_lang())])
            item.setIcon(0, make_icon(SEVERITY_ICONS.get(issue.severity, "info")))
            item.setData(0, ROLE_ISSUE, issue)
            item.setToolTip(0, issue.code)
            self.tree.addTopLevelItem(item)
        keep = {k: b.isChecked() for k, b in self._confirm_boxes.items()}
        for box in self._confirm_boxes.values():
            self.confirm_box.removeWidget(box)
            box.deleteLater()
        self._confirm_boxes.clear()
        for issue in self.issues:
            if issue.needs_confirmation and issue.code not in self._confirm_boxes:
                box = QCheckBox(tr("forge.review.confirm", problem=issue.message(_lang())))
                box.setObjectName(f"forgeConfirm_{issue.code}")
                box.setChecked(keep.get(issue.code, False))
                box.toggled.connect(lambda _on: self._update_buttons())
                self.confirm_box.addWidget(box)
                self._confirm_boxes[issue.code] = box
        self.tabs.setTabText(0, tr("forge.review.tab.problems", count=len(self.issues)))
        self.why_title.clear()
        self.why_text.clear()
        self._update_buttons()

    def set_audit(self, groups: list) -> None:
        self.groups = list(groups)
        self.audit.setRowCount(len(self.groups))
        for r, g in enumerate(self.groups):
            vals = (g.folder, tr(ROLE_LABELS.get(g.role, "forge.audit.role.province_id")), str(len(g.files)),
                    str(g.count), ", ".join(str(e) for e in g.examples[:4]),
                    " · ".join(tr(AUDIT_ACTIONS[a]) for a in g.actions if a in AUDIT_ACTIONS))
            for c, v in enumerate(vals):
                self.audit.setItem(r, c, QTableWidgetItem(v))
        self.tabs.setTabText(1, tr("forge.review.tab.audit", count=sum(g.count for g in self.groups)))

    def set_plan(self, plan: list) -> None:
        self.plan = list(plan)
        self.plan_table.setRowCount(len(self.plan))
        for r, f in enumerate(self.plan):
            vals = (f.rel, tr(ACTION_LABELS.get(f.action, "forge.plan.action.generate")), f.cls, human_size(f.size))
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.plan_table.setItem(r, c, item)
        counts = {a: sum(1 for f in self.plan if f.action == a) for a in ACTION_LABELS}
        total = sum(f.size for f in self.plan)
        self.plan_summary.setText(tr("forge.plan.summary", generate=counts["G"], modify=counts["M"],
                                     trash=counts["T"], empty=counts["E"], size=human_size(total)) if self.plan
                                  else tr("forge.plan.empty"))
        self.tabs.setTabText(2, tr("forge.review.tab.plan", count=len(self.plan)))
        self._update_buttons()

    # --- acciones -----------------------------------------------------------------------------------------

    def selected_issue(self):
        items = self.tree.selectedItems()
        return items[0].data(0, ROLE_ISSUE) if items else None

    def _on_selected(self) -> None:
        issue = self.selected_issue()
        fix = issue.fixes[0] if issue is not None and issue.fixes else None
        self.fix_button.setEnabled(fix in AVAILABLE_FIXES)
        self.why_button.setEnabled(issue is not None)
        self.fix_button.setToolTip(tr("forge.review.fix_named", fix=tr(f"fix.mapforge.{fix}")) if fix else "")

    def _fix(self) -> None:
        issue = self.selected_issue()
        if issue is not None and issue.fixes and issue.fixes[0] in AVAILABLE_FIXES:
            self.fixRequested.emit(issue, issue.fixes[0])

    def _why(self) -> None:
        issue = self.selected_issue()
        if issue is None:
            return
        title, outcome = issue.explanation(_lang())
        self.why_title.setText(f"<b>{title}</b>")
        if issue.fixes:
            fix = tr(f"fix.mapforge.{issue.fixes[0]}")
            here = issue.fixes[0] in AVAILABLE_FIXES
            outcome += "\n" + (tr("forge.review.fix_here", fix=fix) if here else tr("forge.review.fix_later", fix=fix))
        self.why_text.setText(outcome)

    def blocking(self) -> list:
        """Lo que impide exportar: errores sin arreglar y confirmaciones sin marcar."""
        out = [i for i in self.issues if i.severity is Severity.ERROR and not i.needs_confirmation]
        out += [i for i in self.issues if i.needs_confirmation and not self._confirm_boxes.get(i.code, QCheckBox()).
                isChecked()]
        return out

    def _update_buttons(self) -> None:
        self.export_button.setEnabled(bool(self.plan) and not self.blocking())
        self._on_selected()


def _lang() -> str:
    from ...i18n import language

    return language()


__all__ = ["ReviewPanel", "human_size"]
