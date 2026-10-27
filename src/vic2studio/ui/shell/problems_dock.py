"""Panel acoplable «Problemas» (wizard §13.2, §13.9) y las piezas que comparte con Proyecto › Validación.

- ``ProblemsModel``: la tabla de ``Problem`` del último informe de la sesión, con
  gravedad, mensaje, entidad, archivo y línea; los heredados del juego base (I11) se
  ocultan salvo que se pidan y, si se muestran, van en cursiva.
- ``FixFlow``: [Arreglar] (el SimpleFix, o el arreglo elegido en el desplegable): pide
  el plan a la sesión, lo enseña en ``FixPlanDialog`` (confirmación explícita si el
  arreglo borra o sustituye) y, si se acepta, lo aplica con ``Session.apply_fix`` (una
  transacción deshacible; la sesión vuelve a validar).
- ``ProblemsDock``: lo compacto: recuentos, «heredados (n)», la lista y los mismos
  [Arreglar] y [¿Por qué?]; doble clic abre el archivo en esa línea
  (``open_requested``) y [¿Por qué?] lleva a Proyecto › Validación con el explicador
  abierto (``explain_requested``).

Los mensajes vienen del núcleo (``Problem.message(lang)``) y se piden en el idioma
actual al pintar: cambiar de idioma no recalcula nada.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDockWidget,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.clausewitz import Severity
from ...core.index.model import fold
from ...i18n import N_, tr, translator
from .. import theme
from ..viewers.common import SEVERITY_COLOR, core_language, format_number, severity_icon, severity_label
from ..widgets import make_icon, mark_data
from .command_palette import kind_label

COL_SEVERITY, COL_MESSAGE, COL_ENTITY, COL_FILE, COL_LINE = "severity", "message", "entity", "file", "line"
HEADER_KEYS = {
    COL_SEVERITY: N_("checks.col.severity"), COL_MESSAGE: N_("checks.col.message"),
    COL_ENTITY: N_("checks.col.entity"), COL_FILE: N_("checks.col.file"), COL_LINE: N_("checks.col.line"),
}
FULL_COLUMNS = (COL_SEVERITY, COL_MESSAGE, COL_ENTITY, COL_FILE, COL_LINE)
COMPACT_COLUMNS = (COL_SEVERITY, COL_MESSAGE, COL_FILE)
PROBLEM_ROLE = Qt.ItemDataRole.UserRole + 2
SEVERITY_FILTERS = (
    ("all", N_("checks.filter.all"), None),
    ("error", N_("checks.filter.errors"), frozenset({Severity.ERROR})),
    ("problems", N_("checks.filter.problems"), frozenset({Severity.ERROR, Severity.WARNING})),
    ("warning", N_("checks.filter.warnings"), frozenset({Severity.WARNING})),
    ("info", N_("checks.filter.infos"), frozenset({Severity.INFO})),
)


def severity_key(problem) -> str:
    return problem.severity.value


def location_text(problem) -> str:
    if problem.rel is None:
        return ""
    return f"{problem.rel}:{problem.line}" if problem.line else str(problem.rel)


class ProblemsModel(QAbstractTableModel):
    """Problemas del último informe de ``session`` (``refresh``), filtrados por gravedad, texto y heredados."""

    def __init__(self, session, columns: tuple[str, ...] = FULL_COLUMNS, parent=None):
        super().__init__(parent)
        self.session = session
        self.columns = columns
        self._all: list = []
        self._rows: list = []
        self._inherited = False
        self._severities = None
        self._needle = ""
        self._messages: dict[int, str] = {}
        self._entities: dict[int, str] = {}
        self._lang = core_language()
        self._mono = theme.font("mono")
        self._italic = QFont(theme.font("body"))
        self._italic.setItalic(True)

    def refresh(self) -> None:
        report = self.session.report
        self.beginResetModel()
        self._all = [] if report is None else list(report.problems)
        self._messages.clear()
        self._entities.clear()
        self._rows = self._filtered()
        self.endResetModel()

    def set_filter(self, *, inherited: bool | None = None, severities=..., text: str | None = None) -> None:
        if inherited is not None:
            self._inherited = inherited
        if severities is not ...:
            self._severities = severities
        if text is not None:
            self._needle = fold(text.strip())
        self.beginResetModel()
        self._rows = self._filtered()
        self.endResetModel()

    def show_inherited(self) -> bool:
        return self._inherited

    def _filtered(self) -> list:
        rows = [p for p in self._all if self._inherited or not p.inherited]
        if self._severities is not None:
            rows = [p for p in rows if p.severity in self._severities]
        if self._needle:
            needle = self._needle
            rows = [p for p in rows if needle in fold(self.message(p)) or needle in fold(location_text(p))
                    or needle in fold(self.entity(p))]
        return rows

    def problems(self) -> list:
        return list(self._rows)

    def all_problems(self) -> list:
        return list(self._all)

    def problem_at(self, index: QModelIndex):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        return self._rows[index.row()]

    def row_of(self, problem) -> int | None:
        return next((row for row, other in enumerate(self._rows) if other == problem), None)

    def counts(self, *, inherited: bool = False) -> dict[str, int]:
        counts = {"error": 0, "warning": 0, "info": 0}
        for problem in self._all:
            if inherited or not problem.inherited:
                counts[severity_key(problem)] += 1
        return counts

    def inherited_count(self) -> int:
        return sum(1 for problem in self._all if problem.inherited)

    def message(self, problem) -> str:
        key = id(problem)
        text = self._messages.get(key)
        if text is None:
            try:
                text = problem.message(self._lang)
            except Exception:  # noqa: BLE001 - un mensaje roto no debe romper la tabla
                text = problem.code
            self._messages[key] = text
        return text

    def entity(self, problem) -> str:
        if problem.entity is None:
            return ""
        key = id(problem)
        text = self._entities.get(key)
        if text is None:
            kind, name = problem.entity
            text = name
            index = self.session.index
            if index is not None:
                try:
                    symbol = index.get(kind, name)
                    text = self.session.display(symbol) if symbol is not None else name
                except Exception:  # noqa: BLE001
                    text = name
            self._entities[key] = text
        return text

    def retranslate(self) -> None:
        self._lang = core_language()
        self._messages.clear()
        self._entities.clear()
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self.columns) - 1)
        if self._rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, len(self.columns) - 1))

    # --- QAbstractTableModel -----------------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.columns) and role in (
                Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return tr(HEADER_KEYS[self.columns[section]])
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        problem = self.problem_at(index)
        if problem is None:
            return None
        column = self.columns[index.column()]
        severity = severity_key(problem)
        if role == Qt.ItemDataRole.DisplayRole:
            if column == COL_SEVERITY:
                return severity_label(severity)
            if column == COL_MESSAGE:
                return self.message(problem)
            if column == COL_ENTITY:
                return self.entity(problem)
            if column == COL_FILE:
                if self.columns is COMPACT_COLUMNS:
                    return location_text(problem)
                return "" if problem.rel is None else str(problem.rel)
            return "" if problem.line is None else str(problem.line)
        if role == Qt.ItemDataRole.ToolTipRole:
            parts = [self.message(problem)]
            if problem.inherited:
                parts.append(tr("checks.inherited_tooltip"))
            if problem.entity is not None:
                parts.append(tr("checks.entity_tooltip", entity=self.entity(problem), kind=kind_label(problem.entity[0])))
            location = location_text(problem)
            if location:
                parts.append(location)
            return "\n".join(parts)
        if role == Qt.ItemDataRole.DecorationRole and column == COL_SEVERITY:
            return severity_icon(severity)
        if role == Qt.ItemDataRole.ForegroundRole:
            if problem.inherited:
                return theme.color("ink_muted")
            if column == COL_SEVERITY:
                return theme.color(SEVERITY_COLOR[severity])
            return None
        if role == Qt.ItemDataRole.FontRole:
            if problem.inherited:
                return self._italic
            return self._mono if column in (COL_FILE, COL_LINE) else None
        if role == Qt.ItemDataRole.TextAlignmentRole and column == COL_LINE:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == PROBLEM_ROLE:
            return problem
        return None


def problems_table(model: ProblemsModel) -> QTableView:
    view = QTableView()
    view.setProperty("role", "diagnostics")
    view.setModel(model)
    view.setTabKeyNavigation(False)
    view.setShowGrid(False)
    view.setWordWrap(False)
    view.setCornerButtonEnabled(False)
    view.setAlternatingRowColors(True)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setIconSize(QSize(16, 16))
    rows = view.verticalHeader()
    rows.setVisible(False)
    rows.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    rows.setDefaultSectionSize(max(view.fontMetrics().height(), 16) + 8)
    header = view.horizontalHeader()
    header.setHighlightSections(False)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setStretchLastSection(False)
    widths = {COL_SEVERITY: 96, COL_ENTITY: 150, COL_FILE: 230, COL_LINE: 56}
    for section, column in enumerate(model.columns):
        if column == COL_MESSAGE:
            header.setSectionResizeMode(section, QHeaderView.ResizeMode.Stretch)
        else:
            header.resizeSection(section, widths[column])
    mark_data(view)
    return view


class FixFlow(QObject):
    """[Arreglar] de un problema: plan → ``FixPlanDialog`` → ``Session.apply_fix``.

    ``exec_dialog(dialog)`` ejecuta el diálogo (la ventana lo sustituye, y las pruebas); ``request_status(clave, **fmt)``
    pone el resultado en la barra de estado.
    """

    applied = Signal(str, object)    # (clave del arreglo, problema)

    def __init__(self, session, parent_widget: QWidget, exec_dialog, request_status):
        super().__init__(parent_widget)
        self.session = session
        self.parent_widget = parent_widget
        self.exec_dialog = exec_dialog
        self.request_status = request_status

    def fixes(self, problem) -> list:
        if problem is None or self.session.project is None:
            return []
        try:
            return self.session.fixes_for(problem)
        except Exception:  # noqa: BLE001 - sin arreglos (el núcleo aún no los tiene)
            return []

    def run(self, problem, key: str | None = None) -> bool:
        """Enseña el plan del arreglo ``key`` (el SimpleFix si es None) y lo aplica si se acepta."""
        from ..dialogs.fix_plan import FixPlanDialog

        if self.session.is_read_only():
            self.request_status("status.read_only")
            return False
        specs = self.fixes(problem)
        spec = next((s for s in specs if key is None or s.key == key), None)
        if spec is None:
            self.request_status("checks.status_no_fix")
            return False
        lang = core_language()
        try:
            plan = self.session.plan_fix(spec.key, problem)
        except Exception as exc:  # noqa: BLE001 - el motivo se muestra
            self.request_status("checks.status_fix_failed", fix=spec.label(problem, lang), error=str(exc))
            return False
        dialog = FixPlanDialog(spec, problem, plan, self.parent_widget)
        if self.exec_dialog(dialog) != QDialog.DialogCode.Accepted:
            self.request_status("checks.status_fix_cancelled")
            return False
        try:
            self.session.apply_fix(spec.key, problem)
        except Exception as exc:  # noqa: BLE001
            self.request_status("checks.status_fix_failed", fix=spec.label(problem, lang), error=str(exc))
            return False
        self.request_status("checks.status_fix_applied", fix=lambda s=spec, p=problem: s.label(p, core_language()))
        self.applied.emit(spec.key, problem)
        return True


class FixButton(QToolButton):
    """[Arreglar ▾]: un clic aplica el SimpleFix (con su plan); el desplegable ofrece los demás arreglos."""

    def __init__(self, flow: FixFlow, parent: QWidget | None = None):
        super().__init__(parent)
        self.flow = flow
        self.problem = None
        self.setObjectName("fixButton")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIcon(make_icon("wrench", "gold_light"))
        self.setProperty("accent", True)
        self.menu_ = QMenu(self)
        self.setMenu(self.menu_)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.clicked.connect(lambda: self.flow.run(self.problem))
        self.menu_.aboutToShow.connect(self._fill_menu)
        self.set_problem(None)

    def set_problem(self, problem) -> None:
        self.problem = problem
        specs = self.flow.fixes(problem)
        self.setEnabled(bool(specs) and not self.flow.session.is_read_only())
        self.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup if len(specs) > 1
                          else QToolButton.ToolButtonPopupMode.DelayedPopup)
        self.retranslate()

    def _fill_menu(self) -> None:
        self.menu_.clear()
        lang = core_language()
        for spec in self.flow.fixes(self.problem):
            action = self.menu_.addAction(spec.label(self.problem, lang))
            action.setObjectName(f"fix_{spec.key}")
            action.triggered.connect(lambda checked=False, k=spec.key: self.flow.run(self.problem, k))

    def retranslate(self) -> None:
        specs = self.flow.fixes(self.problem)
        self.setText(tr("checks.fix"))
        if specs:
            self.setToolTip(tr("checks.fix_tooltip", fix=specs[0].label(self.problem, core_language())))
        else:
            self.setToolTip(tr("checks.fix_none_tooltip"))


class ProblemsDock(QDockWidget):
    """Lo compacto de la validación. ``open_requested(problema)`` y ``explain_requested(problema)`` los atiende la
    ventana; ``validate_requested`` también (F7)."""

    open_requested = Signal(object)
    explain_requested = Signal(object)
    validate_requested = Signal()

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("problemsDock")
        self.session = session
        self.exec_dialog = lambda dialog: dialog.exec()   # la ventana lo sustituye (y las pruebas)
        self.status_requested = None                      # función (clave, fmt) de la ventana
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        body = QWidget()
        body.setProperty("surface", "parchment")
        body.setAutoFillBackground(True)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.summary = QLabel()
        self.summary.setObjectName("problemsSummary")
        self.summary.setFont(theme.font("body_bold"))
        top.addWidget(self.summary, 1)
        self.inherited_check = QCheckBox()
        self.inherited_check.setObjectName("problemsInherited")
        self.inherited_check.toggled.connect(lambda on: self.model.set_filter(inherited=on))
        top.addWidget(self.inherited_check)
        self.validate_button = QPushButton()
        self.validate_button.setObjectName("problemsValidate")
        self.validate_button.setIcon(make_icon("validate", "gold_light"))
        self.validate_button.clicked.connect(self.validate_requested)
        top.addWidget(self.validate_button)
        layout.addLayout(top)
        self.model = ProblemsModel(session, COMPACT_COLUMNS, self)
        self.view = problems_table(self.model)
        self.view.setObjectName("problemsList")
        self.view.activated.connect(lambda index: self._open(self.model.problem_at(index)))
        self.view.selectionModel().currentRowChanged.connect(self._on_current_changed)
        layout.addWidget(self.view, 1)
        buttons = QHBoxLayout()
        self.flow = FixFlow(session, self, lambda dialog: self.exec_dialog(dialog), self.request_status)
        self.fix_button = FixButton(self.flow)
        buttons.addWidget(self.fix_button)
        self.why_button = QPushButton()
        self.why_button.setObjectName("problemsWhy")
        self.why_button.setIcon(make_icon("question", "gold_light"))
        self.why_button.clicked.connect(lambda: self._explain(self.current_problem()))
        buttons.addWidget(self.why_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.setWidget(body)
        # Métodos y no lambdas: Qt corta la conexión cuando el panel se destruye (la sesión puede vivir más).
        session.problemsChanged.connect(self.refresh)
        session.validationStateChanged.connect(self._retranslate_summary)
        session.projectOpened.connect(self._on_project_changed)
        session.projectClosed.connect(self._on_project_changed)
        self.model.modelReset.connect(self._retranslate_summary)
        translator().languageChanged.connect(self._on_language_changed)
        self.refresh()
        self.retranslate()

    def current_problem(self):
        return self.model.problem_at(self.view.currentIndex())

    def refresh(self) -> None:
        current = self.current_problem()
        self.model.refresh()
        row = self.model.row_of(current) if current is not None else None
        if row is not None:
            self.view.setCurrentIndex(self.model.index(row, 0))
        self._on_current_changed()
        self._retranslate_summary()

    def _on_project_changed(self, *args) -> None:
        self.refresh()

    def _on_current_changed(self, *args) -> None:
        problem = self.current_problem()
        self.fix_button.set_problem(problem)
        self.why_button.setEnabled(problem is not None and self.session.validation_context is not None)

    def _open(self, problem) -> None:
        if problem is not None:
            self.open_requested.emit(problem)

    def _explain(self, problem) -> None:
        if problem is not None:
            self.explain_requested.emit(problem)

    def request_status(self, key: str, **fmt) -> None:
        if self.status_requested is not None:
            self.status_requested(key, fmt)

    def _on_language_changed(self, code: str) -> None:
        self.retranslate()

    def _retranslate_summary(self, *args) -> None:
        session = self.session
        state = session.validation_state()
        if session.project is None:
            text = tr("checks.dock_no_project")
        elif state in ("busy", "waiting"):
            text = tr("checks.dock_running")
        elif state == "failed":
            text = tr("checks.dock_failed")
        elif session.report is None:
            text = tr("checks.dock_not_validated")
        else:
            counts = self.model.counts()
            text = tr("checks.dock_counts", errors=format_number(counts["error"]),
                      warnings=format_number(counts["warning"]), infos=format_number(counts["info"]))
        self.summary.setText(text)
        self.inherited_check.setText(tr("checks.show_inherited", count=format_number(self.model.inherited_count())))
        self.validate_button.setEnabled(session.project is not None and not session.is_validating())

    def retranslate(self) -> None:
        self.setWindowTitle(tr("checks.dock_title"))
        self.inherited_check.setToolTip(tr("checks.show_inherited_tooltip"))
        self.validate_button.setText(tr("checks.validate"))
        self.validate_button.setToolTip(tr("checks.validate_tooltip"))
        self.why_button.setText(tr("checks.why"))
        self.why_button.setToolTip(tr("checks.why_tooltip"))
        self.view.setToolTip(tr("checks.hint"))
        self.model.retranslate()
        self.fix_button.retranslate()
        self._retranslate_summary()
