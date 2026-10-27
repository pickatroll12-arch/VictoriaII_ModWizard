"""Proyecto › Validación: el informe del validador con línea base, arreglos y explicador (wizard §11, §11.1, §13.9).

- **Tabla**: gravedad, mensaje, entidad, archivo y línea de cada ``Problem`` del último
  informe de la sesión. Los heredados del juego base (I11) se ocultan; el conmutador
  «Mostrar heredados del juego base (n)» los enseña, en cursiva.
- **[Arreglar ▾]**: el SimpleFix del problema seleccionado (con su plan de cambios y
  confirmación; los que borran o sustituyen, con confirmación explícita); los demás
  arreglos, en el desplegable (``problems_dock.FixFlow``).
- **[¿Por qué?]**: el panel del explicador (``ExplainerPanel``): las capas en el orden
  en que las carga el juego, con su línea real y su veredicto, la frase de lo que verá
  el jugador y sus arreglos.
- **Doble clic**: abre el archivo en esa línea en Archivos (``open_requested``).
- «Validar mod» (F7) lanza ``Session.validate`` (en segundo plano, cancelable).

No escribe nada: arreglar es una transacción de la sesión, deshacible con Ctrl+Z.
"""

from __future__ import annotations

import html
from collections import Counter

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ....core.clausewitz import Severity
from ....i18n import N_, tr
from ... import theme
from ...pages.base import BasePage
from ...shell.problems_dock import (
    FULL_COLUMNS,
    SEVERITY_FILTERS,
    FixButton,
    FixFlow,
    ProblemsModel,
    problems_table,
)
from ...viewers.common import ElidedLabel, core_language, format_number, format_seconds
from ...widgets import EmptyState, ParchmentCard, make_icon, mark_data, show_in_stack

FILTER_DELAY_MS = 200
VERDICT_COLORS = {"wins": "success", "loses": "ink_muted", "hidden": "warning", "not_loaded": "warning",
                  "missing": "danger"}


class ExplainerPanel(ParchmentCard):
    """El explicador de conflicto de un problema: título, capas (archivo:línea · extracto · veredicto), frase final
    y sus arreglos (un botón por arreglo, que lanza ``fix_requested``)."""

    fix_requested = Signal(str)       # clave del arreglo
    closed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(padding=12, parent=parent)
        self.setObjectName("explainerPanel")
        self.problem = None
        self.explanation = None
        self.fix_specs: list = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        head = QHBoxLayout()
        self.heading = QLabel()
        self.heading.setObjectName("explainerHeading")
        self.heading.setProperty("role", "heading")
        self.heading.setFont(theme.font("heading", 11))
        head.addWidget(self.heading, 1)
        self.close_button = QToolButton()
        self.close_button.setObjectName("explainerClose")
        self.close_button.setIcon(make_icon("error", "cream", "cream", "gold_pale"))  # sobre el botón de madera
        self.close_button.setIconSize(QSize(16, 16))
        self.close_button.clicked.connect(self.closed)
        head.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(head)
        self.title = mark_data(QLabel())
        self.title.setObjectName("explainerTitle")
        self.title.setFont(theme.font("body_bold"))
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        self.steps_box = QWidget()
        self.steps_box.setAutoFillBackground(False)
        self.steps_layout = QVBoxLayout(self.steps_box)
        self.steps_layout.setContentsMargins(0, 0, 0, 0)
        self.steps_layout.setSpacing(6)
        scroll.setWidget(self.steps_box)
        layout.addWidget(scroll, 1)
        self.outcome = mark_data(QLabel())
        self.outcome.setObjectName("explainerOutcome")
        self.outcome.setWordWrap(True)
        self.outcome.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.outcome)
        self.fixes_row = QHBoxLayout()
        self.fixes_row.setSpacing(6)
        layout.addLayout(self.fixes_row)
        self.step_rows: list[tuple[QLabel, QLabel, QLabel]] = []
        self.fix_buttons: list[QPushButton] = []
        self.retranslate()

    def show_explanation(self, problem, explanation, fix_specs: list) -> None:
        self.problem = problem
        self.explanation = explanation
        self.fix_specs = [spec for spec in fix_specs if explanation is None or spec.key in explanation.fixes
                          or not explanation.fixes]
        while self.steps_layout.count():
            item = self.steps_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.step_rows = []
        for step in (explanation.steps if explanation is not None else ()):
            row = QWidget()
            row.setObjectName("explainerStep")
            grid = QVBoxLayout(row)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(1)
            top = QHBoxLayout()
            top.setSpacing(10)
            layer = mark_data(QLabel())
            layer.setFont(theme.font("body_bold"))
            top.addWidget(layer)
            where = mark_data(ElidedLabel())   # la ruta se recorta por el medio; la línea no se pierde
            where.setFont(theme.font("mono", 8.5))
            where.setProperty("role", "caption")
            top.addWidget(where, 1)
            verdict = mark_data(QLabel())
            verdict.setFont(theme.font("body_bold"))
            top.addWidget(verdict)
            grid.addLayout(top)
            excerpt = mark_data(QLabel())
            excerpt.setFont(theme.font("mono", 8.5))
            excerpt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(excerpt)
            self.steps_layout.addWidget(row)
            self.step_rows.append((layer, where, verdict, excerpt, step))
        self.steps_layout.addStretch(1)
        while self.fixes_row.count():
            item = self.fixes_row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.fix_buttons = []
        for spec in self.fix_specs:
            button = QPushButton()
            button.setObjectName(f"explainerFix_{spec.key}")
            button.setIcon(make_icon("wrench", "gold_light"))
            button.clicked.connect(lambda checked=False, k=spec.key: self.fix_requested.emit(k))
            self.fixes_row.addWidget(button)
            self.fix_buttons.append(button)
        self.fixes_row.addStretch(1)
        self.retranslate()

    def step_texts(self) -> list[tuple[str, str, str, str]]:
        """(capa, archivo:línea, veredicto, extracto) de cada paso tal como se muestran (para las pruebas)."""
        return [(layer.text(), where.text(), verdict.text(), excerpt.text())
                for layer, where, verdict, excerpt, _ in self.step_rows]

    def retranslate(self) -> None:
        lang = core_language()
        self.heading.setText(tr("checks.explain_heading"))
        self.close_button.setToolTip(tr("checks.explain_close"))
        explanation = self.explanation
        if explanation is None:
            self.title.setText(tr("checks.explain_none"))
            self.outcome.setText("")
        else:
            self.title.setText(explanation.title(lang))
            self.outcome.setText(f'<span style="color:{theme.PALETTE["velvet_text"]};">'
                                 f'{html.escape(explanation.outcome(lang))}</span>')
        for layer, where, verdict, excerpt, step in self.step_rows:
            layer.setText(step.layer_text(lang))
            location = "" if step.rel is None else (f"{step.rel}:{step.line}" if step.line else str(step.rel))
            where.set_text(location, "" if step.rel is None else str(step.rel))
            where.setToolTip(location)
            verdict.setText(step.verdict_text(lang))
            color = VERDICT_COLORS.get(step.verdict, "ink_soft")
            verdict.setStyleSheet(f"color: {theme.PALETTE[color]};")
            excerpt.setText(step.excerpt or tr("checks.explain_no_line"))
            excerpt.setVisible(True)
        for button, spec in zip(self.fix_buttons, self.fix_specs):
            button.setText(spec.label(self.problem, lang))


class ValidationPage(BasePage):
    """Proyecto › Validación. ``open_requested(problema)`` lo atiende la ventana (abre el archivo en su línea)."""

    key = "project.validation"
    title_key = N_("section.project.validation")
    subtitle_key = N_("section.project.validation.intro")
    icon_name = "validate"

    open_requested = Signal(object)

    def __init__(self, session, parent: QWidget | None = None):
        self.session = session
        super().__init__(parent)
        session.problemsChanged.connect(self.refresh)
        session.validationStateChanged.connect(self._update_state)
        session.validationProgress.connect(self._on_progress)
        session.projectOpened.connect(self._on_project_changed)
        session.projectClosed.connect(self._on_project_changed)
        session.indexStateChanged.connect(self._update_state)
        self.refresh()

    # --- construcción --------------------------------------------------------------------------------

    def build(self) -> None:
        self.exec_dialog = lambda dialog: dialog.exec()   # la ventana lo sustituye (y las pruebas)
        self._progress = (0, 0)
        self._announced = False   # la barra de estado dice «Validando…» por esta página: al terminar se dice
        self.validate_button = QPushButton()
        self.validate_button.setObjectName("checksValidate")
        self.validate_button.setProperty("accent", True)
        self.validate_button.setIcon(make_icon("validate", "gold_pale"))
        self.validate_button.clicked.connect(self.validate)
        self.header.trailing.addWidget(self.validate_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.stack = QStackedWidget()
        self.empty = EmptyState("validate")
        self.empty_validate = QPushButton()
        self.empty_validate.setObjectName("checksEmptyValidate")
        self.empty_validate.setProperty("accent", True)
        self.empty_validate.setIcon(make_icon("validate", "gold_pale"))
        self.empty_validate.clicked.connect(self.validate)
        self.empty.add_action(self.empty_validate)
        self.stack.addWidget(self.empty)

        self.running = QWidget()
        running = QVBoxLayout(self.running)
        running.setContentsMargins(24, 12, 24, 12)
        running.addStretch(1)
        self.running_title = QLabel()
        self.running_title.setProperty("role", "empty-title")
        self.running_title.setFont(theme.font("heading", 13))
        self.running_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        running.addWidget(self.running_title)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("checksProgress")
        self.progress_bar.setRange(0, 0)
        running.addWidget(self.progress_bar)
        self.cancel_button = QPushButton()
        self.cancel_button.setObjectName("checksCancel")
        self.cancel_button.setIcon(make_icon("error", "cream"))
        self.cancel_button.clicked.connect(self.session.cancel_validation)
        running.addWidget(self.cancel_button, 0, Qt.AlignmentFlag.AlignHCenter)
        running.addStretch(2)
        self.stack.addWidget(self.running)

        self.results = QWidget()
        results = QVBoxLayout(self.results)
        results.setContentsMargins(0, 0, 0, 0)
        results.setSpacing(6)
        self.summary = QLabel()
        self.summary.setObjectName("checksSummary")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        results.addWidget(self.summary)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.severity_combo = QComboBox()
        self.severity_combo.setObjectName("checksSeverity")
        self.severity_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for data, _, _ in SEVERITY_FILTERS:
            self.severity_combo.addItem("", data)
        self.severity_combo.currentIndexChanged.connect(self._apply_filter)
        filters.addWidget(self.severity_combo)
        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("checksFilter")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.addAction(make_icon("search", "ink_muted"), QLineEdit.ActionPosition.LeadingPosition)
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(FILTER_DELAY_MS)
        self._filter_timer.timeout.connect(self._apply_filter)
        self.filter_edit.textChanged.connect(lambda _: self._filter_timer.start())
        filters.addWidget(self.filter_edit, 1)
        self.inherited_check = QCheckBox()
        self.inherited_check.setObjectName("checksInherited")
        self.inherited_check.toggled.connect(self._apply_filter)
        filters.addWidget(self.inherited_check)
        results.addLayout(filters)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        table_box = QWidget()
        table_layout = QVBoxLayout(table_box)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(6)
        self.table_stack = QStackedWidget()
        self.model = ProblemsModel(self.session, FULL_COLUMNS, self)
        self.view = problems_table(self.model)
        self.view.setObjectName("checksTable")
        self.view.activated.connect(self._on_activated)
        self.view.selectionModel().currentRowChanged.connect(self._on_current_changed)
        self.table_stack.addWidget(self.view)
        self.clean = EmptyState("check")
        self.table_stack.addWidget(self.clean)
        table_layout.addWidget(self.table_stack, 1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.flow = FixFlow(self.session, self, lambda dialog: self.exec_dialog(dialog), self.request_status)
        self.flow.applied.connect(self._on_fix_applied)
        self.fix_button = FixButton(self.flow)
        actions.addWidget(self.fix_button)
        self.why_button = QPushButton()
        self.why_button.setObjectName("checksWhy")
        self.why_button.setIcon(make_icon("question", "gold_light"))
        self.why_button.clicked.connect(lambda: self.show_explanation(self.current_problem()))
        actions.addWidget(self.why_button)
        self.hint = QLabel()
        self.hint.setProperty("role", "caption")
        self.hint.setFont(theme.font("caption"))
        self.hint.setWordWrap(True)
        actions.addWidget(self.hint, 1)
        table_layout.addLayout(actions)
        self.splitter.addWidget(table_box)
        self.explainer = ExplainerPanel()
        self.explainer.fix_requested.connect(lambda key: self.flow.run(self.explainer.problem, key))
        self.explainer.closed.connect(self.hide_explanation)
        self.splitter.addWidget(self.explainer)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        results.addWidget(self.splitter, 1)
        self.stack.addWidget(self.results)
        self.body.addWidget(self.stack, 1)
        # Ya dentro de la página: sin padre, setVisible(False) no basta y mostrarlo luego lo sacaría como ventana.
        self.explainer.setVisible(False)
        show_in_stack(self.stack, self.empty)

    # --- API -----------------------------------------------------------------------------------------

    def validate(self) -> bool:
        """«Validar mod» (F7): valida en segundo plano con el validador del núcleo."""
        if self.session.project is None:
            self.request_status("status.no_project")
            return False
        started = self.session.validate()
        if started:
            self.request_status("checks.status_started")
            self._announced = True
            self._announce_end()   # una validación que terminó ya (o falló) al pedirla
        return started

    def _announce_end(self) -> None:
        """Cambia el «Validando…» de la barra de estado por el resultado cuando termina la validación que pidió
        esta página (las de después de un arreglo no lo pisan: el estado dice qué se arregló)."""
        state = self.session.validation_state()
        if not self._announced or state in ("busy", "waiting"):
            return
        self._announced = False
        if state == "failed":
            self.request_status("checks.status_failed", error=self.session.validation_error() or "")
        elif state == "ready" and self.session.report is not None:
            # Del informe, no del modelo de la tabla: problemsChanged llega después de este cambio de estado.
            own = Counter(p.severity for p in self.session.problems())
            self.request_status("checks.status_done", errors=format_number(own[Severity.ERROR]),
                                warnings=format_number(own[Severity.WARNING]), infos=format_number(own[Severity.INFO]),
                                seconds=format_seconds(self.session.report.elapsed))

    def refresh(self) -> None:
        current = self.current_problem()
        explained = self.explainer.problem if self.explainer.isVisible() else None
        self.model.refresh()
        row = self.model.row_of(current) if current is not None else None
        if row is not None:
            self.view.setCurrentIndex(self.model.index(row, 0))
        elif self.model.rowCount():
            self.view.setCurrentIndex(self.model.index(0, 0))
        if explained is not None and self.model.row_of(explained) is None:
            self.hide_explanation()   # el problema ya no está (se arregló)
        self._on_current_changed()
        self._update_state()

    def current_problem(self):
        return self.model.problem_at(self.view.currentIndex())

    def select_problem(self, problem) -> bool:
        row = self.model.row_of(problem)
        if row is None and problem is not None and problem.inherited and not self.inherited_check.isChecked():
            self.inherited_check.setChecked(True)
            row = self.model.row_of(problem)
        if row is None:
            return False
        self.view.setCurrentIndex(self.model.index(row, 0))
        return True

    def show_explanation(self, problem=None) -> bool:
        """[¿Por qué?]: abre el explicador del problema (el seleccionado si no se da)."""
        problem = problem if problem is not None else self.current_problem()
        if problem is None:
            return False
        self.select_problem(problem)
        try:
            explanation = self.session.explain(problem)
        except Exception as exc:  # noqa: BLE001 - el explicador aún puede no existir
            self.request_status("checks.status_explain_failed", error=str(exc))
            return False
        if explanation is None:
            self.request_status("checks.status_explain_failed", error=tr("checks.explain_no_report"))
            return False
        self.explainer.show_explanation(problem, explanation, self.flow.fixes(problem))
        self.explainer.setVisible(True)
        return True

    def hide_explanation(self) -> None:
        self.explainer.setVisible(False)

    def is_busy(self) -> bool:
        return self._filter_timer.isActive()

    # --- interno -------------------------------------------------------------------------------------

    def _on_project_changed(self, *args) -> None:
        self.hide_explanation()
        self.refresh()

    def _on_activated(self, index) -> None:
        problem = self.model.problem_at(index)
        if problem is not None:
            self.open_requested.emit(problem)

    def _on_current_changed(self, *args) -> None:
        problem = self.current_problem()
        self.fix_button.set_problem(problem)
        self.why_button.setEnabled(problem is not None and self.session.validation_context is not None)

    def _on_fix_applied(self, key: str, problem) -> None:
        self.hide_explanation()

    def _on_progress(self, done: int, total: int) -> None:
        self._progress = (done, total)
        if self.progress_bar.maximum() != total:
            self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        self._retranslate_running()

    def _apply_filter(self, *args) -> None:
        self._filter_timer.stop()
        severities = SEVERITY_FILTERS[max(0, self.severity_combo.currentIndex())][2]
        self.model.set_filter(inherited=self.inherited_check.isChecked(), severities=severities,
                              text=self.filter_edit.text())
        if self.model.rowCount() and not self.view.currentIndex().isValid():
            self.view.setCurrentIndex(self.model.index(0, 0))
        self._on_current_changed()
        self._update_state()

    def _update_state(self, *args) -> None:
        session = self.session
        state = session.validation_state()
        has_project = session.project is not None
        self.validate_button.setEnabled(has_project and not session.is_validating())
        self.empty_validate.setEnabled(has_project and not session.is_validating())
        self.empty_validate.setVisible(has_project)
        # Los textos del estado vacío se ponen siempre, se vea o no: oculto también cambia de idioma.
        if not has_project:
            self.empty.set_texts(tr("checks.empty_no_project_title"), tr("checks.empty_no_project"))
        elif state == "failed":
            self.empty.set_texts(tr("checks.failed_title"), tr("checks.failed_text",
                                                               error=session.validation_error() or ""))
        else:
            self.empty.set_texts(tr("checks.empty_title"), tr("checks.empty_text"))
        if not has_project or state == "failed" or (session.report is None and state not in ("busy", "waiting")):
            show_in_stack(self.stack, self.empty)
        elif state in ("busy", "waiting"):
            if self.progress_bar.maximum() and state == "waiting":
                self.progress_bar.setRange(0, 0)
            show_in_stack(self.stack, self.running)
        else:
            show_in_stack(self.stack, self.results)
            show_in_stack(self.table_stack, self.view if self.model.rowCount() else self.clean)
        self._retranslate_running()
        self._retranslate_summary()
        self._announce_end()

    def _retranslate_running(self) -> None:
        done, total = self._progress
        waiting = self.session.validation_state() == "waiting"
        self.running_title.setText(tr("checks.waiting_index" if waiting else "checks.running"))
        self.progress_bar.setFormat(tr("checks.progress", done=format_number(done), total=format_number(total))
                                    if total and not waiting else "")

    def _retranslate_summary(self) -> None:
        report = self.session.report
        inherited = self.model.inherited_count()
        self.inherited_check.setText(tr("checks.show_inherited", count=format_number(inherited)))
        if report is None:
            self.summary.setText("")
            return
        counts = self.model.counts()
        text = tr("checks.summary", files=format_number(report.files), seconds=format_seconds(report.elapsed),
                  errors=format_number(counts["error"]), warnings=format_number(counts["warning"]),
                  infos=format_number(counts["info"]))
        if not report.baseline_ready:
            text += " " + tr("checks.no_baseline")
        elif inherited and not self.inherited_check.isChecked():
            text += " " + tr("checks.inherited_hidden", count=format_number(inherited))
        shown = self.model.rowCount()
        visible = sum(1 for p in self.model.all_problems() if self.inherited_check.isChecked() or not p.inherited)
        if shown != visible:
            text += " " + tr("checks.shown", shown=format_number(shown))
        color = theme.PALETTE["danger" if counts["error"] else "warning" if counts["warning"] else "success"]
        self.summary.setText(f'<span style="color:{color}; font-weight:600;">{html.escape(text)}</span>')
        self.clean.set_texts(tr("checks.clean_title"), tr("checks.clean_text", files=format_number(report.files)))

    def retranslate(self) -> None:
        super().retranslate()
        if not hasattr(self, "model"):
            return
        self.validate_button.setText(tr("checks.validate"))
        self.validate_button.setToolTip(tr("checks.validate_tooltip"))
        self.empty_validate.setText(tr("checks.validate"))
        self.empty_validate.setToolTip(tr("checks.validate_tooltip"))
        self.cancel_button.setText(tr("checks.cancel"))
        for position, (_, key, _) in enumerate(SEVERITY_FILTERS):
            self.severity_combo.setItemText(position, tr(key))
        self.severity_combo.setToolTip(tr("checks.filter_tooltip"))
        self.filter_edit.setPlaceholderText(tr("checks.filter_placeholder"))
        self.inherited_check.setToolTip(tr("checks.show_inherited_tooltip"))
        self.why_button.setText(tr("checks.why"))
        self.why_button.setToolTip(tr("checks.why_tooltip"))
        self.hint.setText(tr("checks.hint"))
        self.model.retranslate()
        self.fix_button.retranslate()
        self.explainer.retranslate()
        self._update_state()
