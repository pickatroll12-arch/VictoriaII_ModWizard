"""«Exportar a zip» (wizard §22, iteración 10): el mod en un zip limpio, listo para compartir.

El diálogo enseña qué entra y qué se queda fuera (``core.export.plan_zip``), y por qué. Exportar exige tres cosas,
y cada una que falta sale como aviso con su remedio:

- que no haya cambios sin guardar (el zip se hace con lo que hay en disco);
- un informe de validación al día (el botón «Validar» lo pide aquí mismo);
- ningún error propio del mod (los heredados del juego no cuentan, como en Proyecto › Validación).

El plan y la escritura van en segundo plano y se pueden cancelar; cancelar deja el zip anterior como estaba.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from ...core import export as zexport
from ...core.clausewitz import Severity
from ...i18n import N_, tr
from .. import theme
from ..tasks import POOL_PREVIEW, TaskRunner
from ..viewers.common import format_number, format_size
from ..widgets import StatusBadge, make_icon

REASON_KEYS = {
    zexport.SKIP_STUDIO: N_("export.skip.studio"), zexport.SKIP_BACKUP: N_("export.skip.backup"),
    zexport.SKIP_TEMP: N_("export.skip.temp"), zexport.SKIP_SYSTEM: N_("export.skip.system"),
    zexport.SKIP_VCS: N_("export.skip.vcs"), zexport.SKIP_LINK: N_("export.skip.link"),
    zexport.SKIP_IDENTICAL: N_("export.skip.identical"),
}
DEST_KEYS = {zexport.DEST_NOT_ZIP: N_("export.dest.not_zip"), zexport.DEST_INSIDE_MOD: N_("export.dest.inside_mod"),
             zexport.DEST_INSIDE_GAME: N_("export.dest.inside_game")}

_last_folder: str | None = None   # la carpeta del último zip, mientras dure la aplicación


class ExportZipDialog(QDialog):
    """``result`` es el ``ZipResult`` de la última exportación, o None."""

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("exportZipDialog")
        self.session = session
        self.plan: zexport.ZipPlan | None = None
        self.result: zexport.ZipResult | None = None
        self._error: str | None = None
        self._writing = False
        self.setMinimumSize(560, 420)
        self.resize(700, 500)
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

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.dest_label = QLabel()
        row = QHBoxLayout()
        self.dest_edit = QLineEdit()
        self.dest_edit.setObjectName("exportZipDest")
        self.dest_edit.textChanged.connect(lambda _t: self.refresh())
        self.dest_label.setBuddy(self.dest_edit)
        self.browse_button = QPushButton()
        self.browse_button.setObjectName("exportZipBrowse")
        self.browse_button.setIcon(make_icon("folder_open", "gold_pale"))
        self.browse_button.clicked.connect(self.browse)
        row.addWidget(self.dest_edit, 1)
        row.addWidget(self.browse_button)
        form.addRow(self.dest_label, row)
        layout.addLayout(form)
        self.prune_check = QCheckBox()
        self.prune_check.setObjectName("exportZipPrune")
        self.prune_check.toggled.connect(lambda _on: self.replan())
        layout.addWidget(self.prune_check)

        self.summary = QLabel()
        self.summary.setObjectName("exportZipSummary")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.skipped = QLabel()
        self.skipped.setObjectName("exportZipSkipped")
        self.skipped.setWordWrap(True)
        self.skipped.setProperty("role", "caption")
        layout.addWidget(self.skipped)
        self.badges = QVBoxLayout()
        self.badges.setSpacing(4)
        layout.addLayout(self.badges)
        self._badges: list[StatusBadge] = []
        layout.addStretch(1)

        self.buttons = QDialogButtonBox()
        self.validate_button = QPushButton()
        self.validate_button.setObjectName("exportZipValidate")
        self.validate_button.setIcon(make_icon("validate", "gold_pale"))
        self.validate_button.clicked.connect(self._validate)
        self.export_button = QPushButton()
        self.export_button.setObjectName("exportZipExport")
        self.export_button.setProperty("accent", True)
        self.export_button.setDefault(True)
        self.export_button.clicked.connect(self.export)
        self.close_button = QPushButton()
        self.close_button.setObjectName("exportZipClose")
        self.close_button.clicked.connect(self._close_or_cancel)
        self.buttons.addButton(self.validate_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.buttons.addButton(self.export_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(self.close_button, QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(self.buttons)

        self._plan_runner = TaskRunner(self, pool=POOL_PREVIEW)
        self._plan_runner.finished.connect(self._on_planned)
        self._plan_runner.failed.connect(lambda f: self._fail(str(f)))
        self._write_runner = TaskRunner(self, pool=POOL_PREVIEW)
        self._write_runner.finished.connect(self._on_written)
        self._write_runner.failed.connect(self._on_write_failed)
        for signal in (session.problemsChanged, session.validationStateChanged, session.dirtyChanged):
            signal.connect(self._on_session_changed)

        project = session.project
        if project is not None:
            name = zexport.default_zip_name(zexport.ZipPlan(project.mod_root, project.mod_root.name))
            folder = _last_folder or QDir.homePath()
            self.dest_edit.setText(str(Path(folder) / name))
        self.retranslate()
        self.replan()

    # --- plan --------------------------------------------------------------------------------------

    def replan(self) -> None:
        project = self.session.project
        self.plan = None
        if project is None:
            self.refresh()
            return
        descriptor = getattr(getattr(project, "descriptor", None), "file", None)
        prune = self.prune_check.isChecked()
        # Las replace_path del descriptor de ahora, no las leídas al abrir (``project.descriptor``): tras añadir
        # una a mano (o con «Exportar al mod») y guardar, la poda daba por idéntica la copia del mod de un archivo
        # que el descriptor del zip oculta en el juego, y el mod compartido se quedaba sin él. Exportar exige
        # guardar antes, así que el descriptor vivo es el del disco que va en el zip.
        current = getattr(project, "current_replace_paths", None)
        replaced = current() if current is not None else getattr(getattr(project, "descriptor", None),
                                                                  "replace_paths", ())
        mod_root, game_root = project.mod_root, project.game_root
        self._plan_runner.start(lambda ctx: zexport.plan_zip(
            mod_root, descriptor=descriptor, game_root=game_root, replace_paths=replaced, prune_identical=prune,
            cancelled=ctx.cancelled))
        self.refresh()

    def _on_planned(self, plan) -> None:
        self.plan = plan
        self.refresh()

    # --- estado ------------------------------------------------------------------------------------

    def blocking_errors(self) -> int:
        return sum(1 for p in self.session.problems() if p.severity is Severity.ERROR)

    def destination_problem(self) -> str | None:
        text = self.dest_edit.text().strip()
        project = self.session.project
        if not text or project is None:
            return zexport.DEST_NOT_ZIP
        return zexport.check_destination(text, mod_root=project.mod_root, game_root=project.game_root)

    def problems(self) -> list[tuple[str, str]]:
        """(nivel, texto) de lo que impide exportar ahora, en el orden en que conviene resolverlo."""
        session = self.session
        out: list[tuple[str, str]] = []
        if session.project is None:
            return [("error", tr("export.no_project"))]
        dirty = session.dirty_count()
        if dirty:
            out.append(("error", tr("export.unsaved", count=format_number(dirty))))
        if session.is_validating():
            out.append(("neutral", tr("export.validating")))
        elif session.report is None or session.report_stale():
            out.append(("warning", tr("export.validate_first")))
        else:
            errors = self.blocking_errors()
            if errors:
                out.append(("error", tr("export.errors", count=format_number(errors))))
        code = self.destination_problem()
        if code is not None and self.dest_edit.text().strip():
            out.append(("error", tr(DEST_KEYS[code])))
        return out

    def can_export(self) -> bool:
        return (self.plan is not None and not self._writing and not self.problems()
                and self.destination_problem() is None)

    def refresh(self) -> None:
        for badge in self._badges:
            self.badges.removeWidget(badge)
            badge.setParent(None)   # fuera ya: deleteLater espera al bucle de eventos
            badge.deleteLater()
        self._badges = []
        rows = self.problems()
        if self._error:
            rows.append(("error", self._error))
        if self.result is not None and not self._writing:
            r = self.result
            rows.append(("ok", tr("export.done", path=str(r.path), files=format_number(r.files),
                                  size=format_size(r.bytes_out))))
        if self._writing:
            rows.append(("neutral", tr("export.writing")))
        for level, text in rows:
            badge = StatusBadge()
            badge.set_status(level, text)
            self.badges.addWidget(badge)
            self._badges.append(badge)
        if self.plan is None:
            self.summary.setText(tr("export.planning") if self.session.project is not None else "")
            self.skipped.setText("")
        else:
            plan = self.plan
            self.summary.setText(tr("export.summary", files=format_number(len(plan.members)),
                                    size=format_size(plan.total_bytes)))
            counts = plan.counts()
            parts = [tr(REASON_KEYS[r], count=format_number(counts[r])) for r in zexport.SKIP_REASONS if r in counts]
            self.skipped.setText(tr("export.skipped", list="; ".join(parts)) if parts else tr("export.skipped_none"))
        stale = self.session.project is not None and (self.session.report is None or self.session.report_stale())
        self.validate_button.setVisible(stale)
        self.validate_button.setEnabled(not self.session.is_validating())
        self.export_button.setEnabled(self.can_export())
        self.dest_edit.setEnabled(not self._writing)
        self.browse_button.setEnabled(not self._writing)
        self.prune_check.setEnabled(not self._writing)
        self.close_button.setText(tr("export.cancel_writing") if self._writing else tr("export.close"))

    def _on_session_changed(self, *args) -> None:
        if not self._writing:
            self.refresh()

    # --- acciones ----------------------------------------------------------------------------------

    def browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("export.browse_title"), self.dest_edit.text(), "*.zip")
        if path:
            if not path.lower().endswith(".zip"):
                path += ".zip"
            self.dest_edit.setText(path)

    def _validate(self) -> None:
        self.session.validate()
        self.refresh()

    def export(self) -> bool:
        global _last_folder
        if not self.can_export():
            return False
        plan, project = self.plan, self.session.project
        dest = Path(self.dest_edit.text().strip())
        errors = self.blocking_errors()
        game_root = project.game_root
        self._writing = True
        self._error = None
        self.result = None
        _last_folder = str(dest.parent)
        self._write_runner.start(lambda ctx: zexport.write_zip_export(plan, dest, game_root=game_root,
                                                                      errors=errors, cancelled=ctx.cancelled))
        self.refresh()
        return True

    def _on_written(self, result) -> None:
        self._writing = False
        self.result = result
        self.refresh()

    def _on_write_failed(self, failure) -> None:
        self._writing = False
        exc = getattr(failure, "exception", None)
        if isinstance(exc, InterruptedError):
            self._error = tr("export.cancelled")
        else:
            self._error = tr("export.failed", error=str(failure))
        self.refresh()

    def _fail(self, error: str) -> None:
        self._error = tr("export.failed", error=error)
        self.refresh()

    def _close_or_cancel(self) -> None:
        if self._writing:
            self._write_runner.cancel()
            self._writing = False
            self._error = tr("export.cancelled")
            self.refresh()
            return
        self.reject()

    def reject(self) -> None:
        self._plan_runner.cancel()
        if self._writing:
            self._write_runner.cancel()
            self._writing = False
        super().reject()

    def retranslate(self) -> None:
        self.setWindowTitle(tr("export.window_title"))
        self.title.setText(tr("export.title"))
        self.intro.setText(tr("export.intro"))
        self.dest_label.setText(tr("export.dest"))
        self.browse_button.setText(tr("export.browse"))
        self.prune_check.setText(tr("export.prune"))
        self.prune_check.setToolTip(tr("export.prune_tooltip"))
        self.validate_button.setText(tr("export.validate"))
        self.export_button.setText(tr("export.export"))
        self.refresh()


__all__ = ["ExportZipDialog"]
