"""Panel «Validar mod»: recorre el mod en segundo plano y lista todos sus diagnósticos.

La validación (``core.modcheck.check_mod``) corre en un hilo con progreso y se
puede cancelar. Doble clic (o Intro) en una fila emite ``issue_activated`` para
abrir el archivo en esa línea.
"""

from __future__ import annotations

import html
import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.modcheck import ModCheckReport, check_mod
from ...i18n import N_, tr
from .. import theme
from ..tasks import TaskRunner
from ..widgets import EmptyState, make_icon, mark_data, show_in_stack
from .common import ERROR, INFO, WARNING, format_number, format_seconds
from .diagnostics import COL_FILE, COL_LINE, COL_MESSAGE, COL_SEVERITY, DiagnosticRow, DiagnosticsModel, \
    DiagnosticsView

SEVERITY_FILTERS = (
    ("all", N_("validation.filter.all"), None),
    ("error", N_("validation.filter.errors"), frozenset({ERROR})),
    ("problems", N_("validation.filter.problems"), frozenset({ERROR, WARNING})),
    ("warning", N_("validation.filter.warnings"), frozenset({WARNING})),
    ("info", N_("validation.filter.infos"), frozenset({INFO})),
)
FILTER_DELAY_MS = 200


def issue_rows(report: ModCheckReport) -> list[DiagnosticRow]:
    return [DiagnosticRow(issue.severity.value, issue.line, issue.column, issue, issue.code, issue.path,
                          issue.relative) for issue in report.issues]


class ValidationPanel(QWidget):
    issue_activated = Signal(object)  # DiagnosticRow (path, line, column)
    validation_finished = Signal(object)  # ModCheckReport
    run_requested = Signal()
    busy_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("validationPanel")
        self._report: ModCheckReport | None = None
        self._progress: tuple[int, int, str] = (0, 0, "")
        self._failure: str | None = None
        self._runner = TaskRunner(self)
        self._runner.progress.connect(self._on_progress)
        self._runner.finished.connect(self._on_finished)
        self._runner.failed.connect(self._on_failed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self.empty = EmptyState("validate")
        self.run_button = QPushButton()
        self.run_button.setObjectName("runValidation")
        self.run_button.setProperty("accent", True)
        self.run_button.setIcon(make_icon("validate", "gold_pale"))
        self.run_button.clicked.connect(self.run_requested)
        self.empty.add_action(self.run_button)
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
        self.progress_bar.setObjectName("validationProgress")
        self.progress_bar.setTextVisible(True)
        running.addWidget(self.progress_bar)
        self.current_file = mark_data(QLabel())
        self.current_file.setProperty("role", "caption")
        self.current_file.setFont(theme.font("mono", 8.5))
        self.current_file.setAlignment(Qt.AlignmentFlag.AlignCenter)
        running.addWidget(self.current_file)
        self.cancel_button = QPushButton()
        self.cancel_button.setObjectName("cancelValidation")
        self.cancel_button.setIcon(make_icon("error", "cream"))
        self.cancel_button.clicked.connect(self.cancel)
        running.addWidget(self.cancel_button, 0, Qt.AlignmentFlag.AlignHCenter)
        running.addStretch(2)
        self.stack.addWidget(self.running)

        self.results = QWidget()
        results = QVBoxLayout(self.results)
        results.setContentsMargins(4, 6, 4, 4)
        results.setSpacing(6)
        self.summary = QLabel()
        self.summary.setObjectName("validationSummary")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        results.addWidget(self.summary)
        filters = QHBoxLayout()
        filters.setSpacing(6)
        self.severity_combo = QComboBox()
        self.severity_combo.setObjectName("validationSeverity")
        for data, _, _ in SEVERITY_FILTERS:
            self.severity_combo.addItem("", data)
        self.severity_combo.currentIndexChanged.connect(self._apply_filter)
        filters.addWidget(self.severity_combo)
        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("validationFilter")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.addAction(make_icon("search", "ink_muted"), QLineEdit.ActionPosition.LeadingPosition)
        self.filter_edit.textChanged.connect(lambda _: self._filter_timer.start())
        filters.addWidget(self.filter_edit, 1)
        results.addLayout(filters)
        self.results_stack = QStackedWidget()
        self.model = DiagnosticsModel((COL_SEVERITY, COL_FILE, COL_LINE, COL_MESSAGE), self)
        self.view = DiagnosticsView(self.model)
        self.view.setObjectName("validationView")
        self.view.setIconSize(QSize(16, 16))
        self.view.diagnostic_activated.connect(self.issue_activated)
        self.results_stack.addWidget(self.view)
        self.clean = EmptyState("check")
        self.results_stack.addWidget(self.clean)
        results.addWidget(self.results_stack, 1)
        self.hint = QLabel()
        self.hint.setProperty("role", "caption")
        self.hint.setWordWrap(True)
        results.addWidget(self.hint)
        self.stack.addWidget(self.results)

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(FILTER_DELAY_MS)
        self._filter_timer.timeout.connect(self._apply_filter)
        show_in_stack(self.stack, self.empty)
        self.retranslate()

    # --- API -----------------------------------------------------------------------------

    def start(self, root: str | os.PathLike, extra_files=()) -> None:
        root = Path(root)
        extra = [Path(p) for p in extra_files]
        self._report = None
        self._failure = None
        self._progress = (0, 0, "")
        self.progress_bar.setRange(0, 0)
        show_in_stack(self.stack, self.running)
        self.retranslate()
        self.busy_changed.emit(True)

        def run(ctx):
            def progress(done: int, total: int, relative: str) -> None:
                ctx.report((done, total, relative), force=done == total)
            return check_mod(root, extra_files=extra, progress=progress, cancelled=ctx.cancelled)

        self._runner.start(run)

    def cancel(self) -> None:
        if self._runner.is_busy():
            self._runner.cancel()
            self._report = None
            show_in_stack(self.stack, self.empty)
            self.retranslate()
            self.busy_changed.emit(False)

    def clear(self) -> None:
        busy = self._runner.is_busy()
        self._runner.cancel()
        self._report = None
        self._failure = None
        self.model.set_rows([])
        show_in_stack(self.stack, self.empty)
        self.retranslate()
        if busy:
            self.busy_changed.emit(False)

    def is_busy(self) -> bool:
        return self._runner.is_busy()

    def report(self) -> ModCheckReport | None:
        return self._report

    def set_run_enabled(self, enabled: bool) -> None:
        self.run_button.setEnabled(enabled)

    def set_compact(self, compact: bool) -> None:
        """Sin resumen ni ayuda (el resumen sigue en la ayuda emergente de la tabla)."""
        self.hint.setVisible(not compact)
        self.summary.setVisible(not compact)

    # --- interno -------------------------------------------------------------------------

    def _on_progress(self, value: tuple[int, int, str]) -> None:
        self._progress = value
        done, total, relative = value
        if self.progress_bar.maximum() != total:
            self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        self.current_file.setText(relative)
        self._retranslate_running()

    def _on_finished(self, report: ModCheckReport) -> None:
        self._report = report
        self.model.set_rows(issue_rows(report))
        self._apply_filter()
        show_in_stack(self.results_stack, self.view if report.issues else self.clean)
        show_in_stack(self.stack, self.results)
        self.retranslate()
        self.busy_changed.emit(False)
        self.validation_finished.emit(report)

    def _on_failed(self, failure) -> None:
        self._failure = str(failure)
        show_in_stack(self.stack, self.empty)
        self.retranslate()
        self.busy_changed.emit(False)

    def _apply_filter(self, *args) -> None:
        self._filter_timer.stop()
        severities = SEVERITY_FILTERS[max(0, self.severity_combo.currentIndex())][2]
        self.model.set_filter(severities, self.filter_edit.text())
        self._retranslate_summary()

    def _retranslate_running(self) -> None:
        done, total, _ = self._progress
        self.running_title.setText(tr("validation.running"))
        self.progress_bar.setFormat(tr("validation.progress", done=format_number(done), total=format_number(total))
                                    if total else "")

    def _retranslate_summary(self) -> None:
        report = self._report
        if report is None:
            self.summary.setText("")
            return
        counts = self.model.counts()
        text = tr("validation.summary", files=format_number(report.files), seconds=format_seconds(report.elapsed),
                  errors=format_number(counts[ERROR]), warnings=format_number(counts[WARNING]),
                  infos=format_number(counts[INFO]))
        shown = len(self.model.visible_rows())
        if shown != len(self.model.all_rows()):
            text += " " + tr("validation.shown", shown=format_number(shown))
        color = theme.PALETTE["danger" if counts[ERROR] else "warning" if counts[WARNING] else "success"]
        self.summary.setText(f'<span style="color:{color}; font-weight:600;">{html.escape(text)}</span>')
        self.view.setToolTip(f"{text}\n{tr('validation.hint')}")

    def retranslate(self) -> None:
        self.run_button.setText(tr("validation.run"))
        self.run_button.setToolTip(tr("validation.run_tooltip"))
        if self._failure:
            self.empty.set_texts(tr("validation.failed_title"), tr("validation.failed_text", error=self._failure))
        else:
            self.empty.set_texts(tr("validation.empty_title"), tr("validation.empty_text"))
        self.cancel_button.setText(tr("validation.cancel"))
        self.cancel_button.setToolTip(tr("validation.cancel_tooltip"))
        self._retranslate_running()
        for i, (_, key, _) in enumerate(SEVERITY_FILTERS):
            self.severity_combo.setItemText(i, tr(key))
        self.severity_combo.setToolTip(tr("validation.filter_tooltip"))
        self.filter_edit.setPlaceholderText(tr("validation.filter_placeholder"))
        self.filter_edit.setToolTip(tr("validation.filter_text_tooltip"))
        files = format_number(self._report.files) if self._report else "0"
        self.clean.set_texts(tr("validation.clean_title"), tr("validation.clean_text", files=files))
        self.hint.setText(tr("validation.hint"))
        self.view.setToolTip(tr("validation.hint"))  # el resumen se añade al terminar
        self.model.retranslate()
        self._retranslate_summary()
