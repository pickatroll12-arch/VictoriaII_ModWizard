"""«Nuevo mod» (wizard §14.1): nombre, carpeta sugerida, ``user_dir`` y una plantilla opcional.

La carpeta se propone a partir del nombre con ``sanitize_folder`` (sin las que ya hay
en ``<juego>/mod``) mientras el usuario no la escriba él; ``user_dir`` sigue a la
carpeta salvo que se desmarque «Igual que la carpeta». Los problemas de
``descriptor_problems(..., creating=True)`` se ven al momento y los errores impiden
crear. «Crear» pide el mod a ``Session.create_mod`` (``create_mod_skeleton`` en segundo
plano, una sola transacción del diario): el diálogo espera la respuesta y se cierra
si el mod se creó (``created`` es su ``ModDescriptor``) o muestra el motivo si no.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QDir, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.clausewitz import Severity
from ...core.modfile import DescriptorSpec, descriptor_problems, render_descriptor, sanitize_folder, taken_folders
from ...core.vfs.guard import evaluate_game, inspect_folder
from ...i18n import language, tr
from .. import theme
from ..widgets import StatusBadge, mark_data, rich

LEVELS = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "neutral"}


class NewModDialog(QDialog):
    def __init__(self, session, game_root: Path | None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("newModDialog")
        self.session = session
        self.game_root = Path(game_root) if game_root else None
        self.created = None
        self._folder_typed = False
        self._error: str | None = None
        self._taken = taken_folders(self.game_root)
        self.setMinimumSize(560, 440)  # explícito: el layout no lo cambia con la ventana ya creada
        self.resize(680, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        self.title = QLabel()
        self.title.setProperty("role", "title")
        self.title.setFont(theme.font("title", 16))
        layout.addWidget(self.title)
        self.intro = QLabel()
        self.intro.setWordWrap(True)
        self.intro.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.intro)
        self.game_badge = StatusBadge()
        layout.addWidget(self.game_badge)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.name_label = QLabel()
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("newModName")
        self.name_edit.textChanged.connect(self._on_name_changed)
        form.addRow(self.name_label, self.name_edit)
        self.folder_label = QLabel()
        self.folder_combo = QComboBox()
        self.folder_combo.setObjectName("newModFolder")
        self.folder_combo.setEditable(True)
        self.folder_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.folder_combo.lineEdit().textEdited.connect(self._on_folder_typed)
        self.folder_combo.currentTextChanged.connect(lambda text: self._on_folder_changed())
        form.addRow(self.folder_label, self.folder_combo)
        self.user_dir_label = QLabel()
        user_row = QHBoxLayout()
        self.user_dir_edit = QLineEdit()
        self.user_dir_edit.setObjectName("newModUserDir")
        self.user_dir_edit.textChanged.connect(lambda text: self.refresh())
        user_row.addWidget(self.user_dir_edit, 1)
        self.same_check = QCheckBox()
        self.same_check.setObjectName("newModSameUserDir")
        self.same_check.setChecked(True)
        self.same_check.toggled.connect(self._on_same_toggled)
        self.user_dir_edit.setReadOnly(True)  # sigue a la carpeta mientras «Igual que la carpeta» esté marcado
        user_row.addWidget(self.same_check)
        form.addRow(self.user_dir_label, user_row)
        self.template_label = QLabel()
        template_row = QHBoxLayout()
        self.template_edit = QLineEdit()
        self.template_edit.setObjectName("newModTemplate")
        self.template_edit.setClearButtonEnabled(True)
        self.template_edit.textChanged.connect(lambda text: self.refresh())
        template_row.addWidget(self.template_edit, 1)
        self.template_button = QPushButton()
        self.template_button.setObjectName("newModTemplateBrowse")
        self.template_button.clicked.connect(self._browse_template)
        template_row.addWidget(self.template_button)
        form.addRow(self.template_label, template_row)
        layout.addLayout(form)
        self.preview_caption = QLabel()
        self.preview_caption.setProperty("role", "caption")
        self.preview_caption.setFont(theme.font("caption"))
        self.preview_caption.setWordWrap(True)
        layout.addWidget(self.preview_caption)
        self.preview = mark_data(QLabel())
        self.preview.setObjectName("newModPreview")
        self.preview.setFont(theme.font("mono"))
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.preview)
        self.problems_box = QVBoxLayout()
        self.problems_box.setSpacing(4)
        layout.addLayout(self.problems_box)
        self.problem_badges: list[StatusBadge] = []
        self.issues: list = []
        layout.addStretch(1)
        self.buttons = QDialogButtonBox()
        self.create_button = QPushButton()
        self.create_button.setObjectName("newModCreate")
        self.create_button.setProperty("accent", True)
        self.create_button.setDefault(True)
        self.cancel_button = QPushButton()
        self.cancel_button.setObjectName("newModCancel")
        self.buttons.addButton(self.create_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        self.create_button.clicked.connect(self.create)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.buttons)
        session.modCreated.connect(self._on_created)
        session.modCreateFailed.connect(self._on_failed)
        self.retranslate()

    # --- formulario ------------------------------------------------------------------------------

    def spec(self) -> DescriptorSpec:
        folder = self.folder_combo.currentText().strip()
        user_dir = folder if self.same_check.isChecked() else self.user_dir_edit.text().strip()
        return DescriptorSpec(self.name_edit.text().strip(), folder, user_dir)

    def template(self) -> Path | None:
        text = self.template_edit.text().strip()
        return Path(os.path.expanduser(text)) if text else None

    def suggestions(self) -> list[str]:
        return sanitize_folder(self.name_edit.text(), taken=self._taken)

    def _on_name_changed(self, text: str) -> None:
        if not self._folder_typed:
            options = self.suggestions()
            self.folder_combo.blockSignals(True)
            self.folder_combo.clear()
            self.folder_combo.addItems(options)
            self.folder_combo.setCurrentIndex(0 if options else -1)
            if not options:
                self.folder_combo.setEditText("")
            self.folder_combo.blockSignals(False)
            self._on_folder_changed()
        self.refresh()

    def _on_folder_typed(self, text: str) -> None:
        self._folder_typed = bool(text)

    def _on_folder_changed(self) -> None:
        if self.same_check.isChecked():
            self.user_dir_edit.setText(self.folder_combo.currentText().strip())
        self.refresh()

    def _on_same_toggled(self, same: bool) -> None:
        self.user_dir_edit.setReadOnly(same)
        if same:
            self.user_dir_edit.setText(self.folder_combo.currentText().strip())
        self.refresh()

    def _browse_template(self) -> None:
        start = os.fspath(self.game_root / "mod") if self.game_root and (self.game_root / "mod").is_dir() \
            else QDir.homePath()
        chosen = QFileDialog.getExistingDirectory(self, tr("newmod.template_dialog"), start)
        if chosen:
            self.template_edit.setText(chosen)

    def game_ok(self) -> bool:
        return self.game_root is not None and evaluate_game(inspect_folder(self.game_root))[0] in ("ok", "warning")

    def problems(self) -> list:
        return descriptor_problems(self.spec(), self.game_root, creating=True, template=self.template())

    def can_create(self) -> bool:
        spec = self.spec()
        template = self.template()
        return (self.game_ok() and bool(spec.name) and bool(spec.folder) and not self.session.is_creating()
                and (template is None or template.is_dir())
                and not any(i.severity is Severity.ERROR for i in self.issues))

    def refresh(self) -> None:
        self.issues = self.problems() if self.name_edit.text().strip() or self.folder_combo.currentText() else []
        while len(self.problem_badges) < len(self.issues) + 1:
            badge = StatusBadge()
            self.problems_box.addWidget(badge)
            self.problem_badges.append(badge)
        lang = language()
        for badge, issue in zip(self.problem_badges, self.issues):
            badge.set_status(LEVELS[issue.severity], issue.message(lang))
            badge.label.setProperty("i18nData", True)  # el texto viene del núcleo, ya traducido
        extra = self.problem_badges[len(self.issues)]
        extra.label.setProperty("i18nData", False)
        template = self.template()
        spec = self.spec()
        extra_visible = True
        if self._error is not None:
            extra.set_status("error", tr("newmod.failed", error=self._error))
        elif template is not None and not template.is_dir():
            extra.set_status("error", tr("newmod.template_missing", folder=os.fspath(template)))
        elif self.session.is_creating():
            extra.set_status("neutral", tr("newmod.creating"))
        elif spec.name and spec.folder and self.game_ok() \
                and not any(i.severity is Severity.ERROR for i in self.issues):
            extra.set_status("ok", tr("newmod.ready", folder=spec.folder))
        else:
            extra_visible = False
        for index, badge in enumerate(self.problem_badges):
            badge.setVisible(index < len(self.issues) or (index == len(self.issues) and extra_visible))
        try:
            self.preview.setText(render_descriptor(spec).decode("cp1252").rstrip("\r\n").replace("\r\n", "\n")
                                 if spec.folder else "")
        except ValueError:
            self.preview.setText("")
        self.create_button.setEnabled(self.can_create())

    # --- crear -----------------------------------------------------------------------------------

    def create(self) -> bool:
        if not self.can_create():
            return False
        self._error = None
        self.session.create_mod(self.game_root, self.spec(), self.template())
        for widget in (self.name_edit, self.folder_combo, self.user_dir_edit, self.same_check,
                       self.template_edit, self.template_button):
            widget.setEnabled(False)
        self.refresh()
        return True

    def _unlock(self) -> None:
        for widget in (self.name_edit, self.folder_combo, self.user_dir_edit, self.same_check,
                       self.template_edit, self.template_button):
            widget.setEnabled(True)

    def _on_created(self, descriptor) -> None:
        self.created = descriptor
        self._unlock()
        self.accept()

    def _on_failed(self, key: str, fmt) -> None:
        self._error = dict(fmt or {}).get("error", "")
        self._unlock()
        self.refresh()

    def retranslate(self) -> None:
        self.setWindowTitle(tr("newmod.window_title"))
        self.title.setText(tr("newmod.title"))
        folder = os.fspath(self.game_root / "mod") if self.game_root else "—"
        self.intro.setText(rich(tr("newmod.intro", folder=folder), 9.5))
        if self.game_ok():
            self.game_badge.setVisible(False)
        else:
            self.game_badge.setVisible(True)
            self.game_badge.set_status("error", tr("newmod.no_game"))
        self.name_label.setText(tr("newmod.name"))
        self.name_edit.setPlaceholderText(tr("newmod.name_placeholder"))
        self.folder_label.setText(tr("newmod.folder"))
        self.folder_combo.setToolTip(tr("newmod.folder_tooltip"))
        self.user_dir_label.setText(tr("newmod.user_dir"))
        self.user_dir_edit.setToolTip(tr("newmod.user_dir_tooltip"))
        self.same_check.setText(tr("newmod.same_as_folder"))
        self.template_label.setText(tr("newmod.template"))
        self.template_edit.setPlaceholderText(tr("newmod.template_placeholder"))
        self.template_button.setText(tr("project.paths.browse"))
        self.preview_caption.setText(tr("newmod.preview", folder=folder))
        self.create_button.setText(tr("newmod.create"))
        self.cancel_button.setText(tr("newmod.cancel"))
        self.refresh()
