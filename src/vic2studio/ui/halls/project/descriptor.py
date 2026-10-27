"""Sección «Descriptor .mod» (wizard §14.1): formulario sobre ``DescriptorSpec`` que edita el ``.mod`` del proyecto.

El descriptor es un documento más del ``Workspace`` (``vfs.DESCRIPTOR_REL``): cada
campo que se confirma (al salir de él o al marcar una carpeta) es una transacción
con nombre (``Session.edit``) que lleva el formulario al CST vivo con
``modfile.apply_descriptor``, así que conserva comentarios y claves desconocidas, se
deshace con Ctrl+Z y se escribe con Guardar (Ctrl+S). Si el mod aún no tiene
descriptor, el primero se crea con ``render_descriptor`` (cp1252 y CRLF).

A la derecha, los problemas de ``descriptor_problems`` (que se recalculan con cada
cambio, también sin confirmar) y el texto tal como quedará el archivo. La carpeta
se propone con ``sanitize_folder`` y el selector de ``replace_path`` explica el
efecto de cada carpeta marcada (cuántos archivos del juego base dejarán de cargarse).
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ....core.clausewitz import Severity, to_source
from ....core.modcheck import GAME_FOLDERS
from ....core.modfile import (
    FIELD_NEWLINE,
    FIELD_QUOTE,
    DescriptorFieldError,
    DescriptorSpec,
    apply_descriptor,
    descriptor_from_result,
    descriptor_problems,
    render_descriptor,
    sanitize_folder,
    taken_folders,
)
from ....core.vfs import DESCRIPTOR_REL
from ....i18n import N_, language, tr
from ... import theme
from ...pages.base import BasePage
from ...widgets import EmptyState, ParchmentCard, StatusBadge, make_icon, mark_data, rich, show_in_stack
from ...widgets.flow import FlowLayout

SEVERITY_LEVELS = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "neutral"}
# Subcarpetas de primer nivel que también se ofrecen para replace_path (las que los mods suelen sustituir).
SPLIT_FOLDERS = ("history", "gfx", "map", "interface")
FIELD_CODES = (FIELD_QUOTE, FIELD_NEWLINE)


def candidate_folders(game_root: Path | None) -> list[str]:
    """Carpetas del juego que tiene sentido sustituir: las que lee el juego y las subcarpetas de ``SPLIT_FOLDERS``."""
    found: list[str] = []
    if game_root is None or not game_root.is_dir():
        return found
    try:
        top = sorted((e.name for e in os.scandir(game_root) if e.is_dir()), key=str.casefold)
    except OSError:
        return found
    for name in top:
        if name.casefold() not in GAME_FOLDERS:
            continue
        found.append(name)
        if name.casefold() in SPLIT_FOLDERS:
            try:
                subs = sorted((e.name for e in os.scandir(game_root / name) if e.is_dir()), key=str.casefold)
            except OSError:
                subs = []
            found.extend(f"{name}/{sub}" for sub in subs)
    return found


def count_files(folder: Path) -> int:
    total = 0
    for _, _, names in os.walk(folder):
        total += len(names)
    return total


def _lines(text: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in text.splitlines() if line.strip())


class DescriptorPage(BasePage):
    key = "descriptor"
    title_key = N_("section.project.descriptor")
    subtitle_key = N_("descriptor.subtitle")
    icon_name = "file_mod"

    navigate_requested = Signal(str)
    new_mod_requested = Signal()

    def __init__(self, session, parent: QWidget | None = None):
        self.session = session
        self._spec: DescriptorSpec | None = None   # lo que hay en el documento (o lo que se creará)
        self._exists = False                        # el proyecto ya tiene descriptor (en disco o en memoria)
        self._candidates: list[str] = []
        self._candidates_game: Path | None = None
        self._counts: dict[str, int] = {}
        self._filling = False
        self._read_only = True
        self._read_only_reason: str | None = None
        self._empty_reason: tuple[str, dict] = (N_("descriptor.empty_text"), {})
        super().__init__(parent)
        # Métodos y no lambdas: Qt corta la conexión cuando la página se destruye (la sesión puede vivir más).
        session.projectOpened.connect(self._on_project_opened)
        session.projectClosed.connect(self.reload)
        session.projectOpenFailed.connect(self._on_open_failed)
        session.documentsChanged.connect(self._on_documents_changed)

    def _on_project_opened(self, project) -> None:
        self.reload()

    def _on_open_failed(self, key: str, fmt) -> None:
        self._set_empty((key, dict(fmt or {})))

    # --- construcción ----------------------------------------------------------------------------

    def build(self) -> None:
        self.new_button = QPushButton()
        self.new_button.setObjectName("descriptorNewMod")
        self.new_button.setIcon(make_icon("save", "gold_light"))
        self.new_button.clicked.connect(self.new_mod_requested.emit)
        self.header.trailing.addWidget(self.new_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.stack = QStackedWidget()
        self.empty = EmptyState("file_mod")
        self.home_button = QPushButton()
        self.home_button.setProperty("accent", True)
        self.home_button.setIcon(make_icon("home", "gold_pale"))
        self.home_button.clicked.connect(lambda: self.navigate_requested.emit("project:home"))
        self.empty.add_action(self.home_button)
        self.stack.addWidget(self.empty)

        self.view = QSplitter(Qt.Orientation.Horizontal)
        self.view.setChildrenCollapsible(False)
        left = QScrollArea()
        left.setWidgetResizable(True)
        left.setFrameShape(QFrame.Shape.NoFrame)
        left.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left.viewport().setAutoFillBackground(False)
        form_column = QWidget()
        form_column.setAutoFillBackground(False)
        column = QVBoxLayout(form_column)
        column.setContentsMargins(0, 0, 6, 0)
        column.setSpacing(12)
        column.addWidget(self._build_form())
        column.addWidget(self._build_replace())
        column.addStretch(1)
        left.setWidget(form_column)
        self.view.addWidget(left)
        right = QWidget()
        right_column = QVBoxLayout(right)
        right_column.setContentsMargins(6, 0, 0, 0)
        right_column.setSpacing(12)
        right_column.addWidget(self._build_problems())
        right_column.addWidget(self._build_preview(), 1)
        self.view.addWidget(right)
        self.view.setStretchFactor(0, 3)
        self.view.setStretchFactor(1, 2)
        self.stack.addWidget(self.view)
        self.body.addWidget(self.stack, 1)
        show_in_stack(self.stack, self.empty)

    def _heading(self, layout: QVBoxLayout) -> QLabel:
        label = QLabel()
        label.setProperty("role", "heading")
        label.setFont(theme.font("heading", 12))
        layout.addWidget(label)
        return label

    @staticmethod
    def _help() -> QLabel:
        label = QLabel()
        label.setProperty("role", "caption")
        label.setFont(theme.font("caption"))
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        return label

    @staticmethod
    def _with_help(field, help_label: QLabel) -> QWidget:
        """El campo con su explicación debajo, en una sola fila del formulario (QFormLayout calcula mal el alto
        de un rótulo que se parte en líneas si va en una fila propia)."""
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        if isinstance(field, QWidget):
            column.addWidget(field)
        else:
            column.addLayout(field)
        column.addWidget(help_label)
        return box

    def _build_form(self) -> QWidget:
        card = ParchmentCard(padding=16)
        layout = QVBoxLayout(card)
        layout.setSpacing(8)
        self.form_heading = self._heading(layout)
        self.read_only_badge = StatusBadge()
        self.read_only_badge.setVisible(False)
        layout.addWidget(self.read_only_badge)
        missing_row = QHBoxLayout()
        self.missing_badge = StatusBadge()
        missing_row.addWidget(self.missing_badge, 1)
        self.create_button = QPushButton()
        self.create_button.setObjectName("descriptorCreate")
        self.create_button.setProperty("accent", True)
        self.create_button.setIcon(make_icon("file_mod", "gold_pale"))
        self.create_button.clicked.connect(lambda: self._commit("all", force=True))
        missing_row.addWidget(self.create_button, 0, Qt.AlignmentFlag.AlignTop)
        self.missing_box = QWidget()
        self.missing_box.setLayout(missing_row)
        missing_row.setContentsMargins(0, 0, 0, 0)
        self.missing_box.setVisible(False)
        layout.addWidget(self.missing_box)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form = form

        self.name_label = QLabel()
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("descriptorName")
        self.name_edit.editingFinished.connect(lambda: self._commit("name"))
        self.name_edit.textEdited.connect(self._on_typing)
        form.addRow(self.name_label, self.name_edit)

        self.folder_label = QLabel()
        folder_row = QHBoxLayout()
        folder_row.setSpacing(4)
        prefix = mark_data(QLabel("mod/"))
        prefix.setFont(theme.font("mono"))
        folder_row.addWidget(prefix)
        self.folder_edit = QLineEdit()
        self.folder_edit.setObjectName("descriptorFolder")
        self.folder_edit.editingFinished.connect(lambda: self._commit("path"))
        self.folder_edit.textEdited.connect(self._on_typing)
        folder_row.addWidget(self.folder_edit, 1)
        self.suggest_button = QToolButton()
        self.suggest_button.setObjectName("descriptorSuggest")
        self.suggest_button.setIcon(make_icon("gear", "gold_light"))
        self.suggest_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.suggest_menu = QMenu(self.suggest_button)
        self.suggest_menu.aboutToShow.connect(self._fill_suggestions)
        self.suggest_button.setMenu(self.suggest_menu)
        folder_row.addWidget(self.suggest_button)
        self.folder_help = self._help()
        form.addRow(self.folder_label, self._with_help(folder_row, self.folder_help))

        self.user_dir_label = QLabel()
        user_row = QHBoxLayout()
        user_row.setSpacing(4)
        self.user_dir_edit = QLineEdit()
        self.user_dir_edit.setObjectName("descriptorUserDir")
        self.user_dir_edit.editingFinished.connect(lambda: self._commit("user_dir"))
        self.user_dir_edit.textEdited.connect(self._on_typing)
        user_row.addWidget(self.user_dir_edit, 1)
        self.same_button = QPushButton()
        self.same_button.setObjectName("descriptorSameUserDir")
        self.same_button.clicked.connect(self._use_folder_as_user_dir)
        user_row.addWidget(self.same_button)
        self.user_dir_help = self._help()
        form.addRow(self.user_dir_label, self._with_help(user_row, self.user_dir_help))

        self.dependencies_label = QLabel()
        self.dependencies_edit = QPlainTextEdit()
        self.dependencies_edit.setObjectName("descriptorDependencies")
        self.dependencies_edit.setTabChangesFocus(True)
        self.dependencies_edit.setFixedHeight(64)
        self.dependencies_edit.textChanged.connect(self._on_typing)
        self.dependencies_edit.installEventFilter(self)
        self.dependencies_help = self._help()
        form.addRow(self.dependencies_label, self._with_help(self.dependencies_edit, self.dependencies_help))
        for label in (self.name_label, self.folder_label, self.user_dir_label, self.dependencies_label):
            label.setProperty("role", "field")
        layout.addLayout(form)
        return card

    def _build_replace(self) -> QWidget:
        card = ParchmentCard(padding=16)
        layout = QVBoxLayout(card)
        layout.setSpacing(8)
        self.replace_heading = self._heading(layout)
        self.replace_help = self._help()
        layout.addWidget(self.replace_help)
        self.replace_list = QWidget()
        self.replace_list.setObjectName("descriptorReplaceList")
        self.replace_flow = FlowLayout(self.replace_list, spacing=10)
        self.replace_checks: list[QCheckBox] = []
        layout.addWidget(self.replace_list)
        self.replace_effect = self._help()
        self.replace_effect.setObjectName("descriptorReplaceEffect")
        layout.addWidget(self.replace_effect)
        return card

    def _build_problems(self) -> QWidget:
        card = ParchmentCard(padding=14)
        layout = QVBoxLayout(card)
        layout.setSpacing(6)
        self.problems_heading = self._heading(layout)
        self.problems_box = QVBoxLayout()
        self.problems_box.setSpacing(4)
        layout.addLayout(self.problems_box)
        self.problem_badges: list[StatusBadge] = []
        self.issues: list = []
        return card

    def _build_preview(self) -> QWidget:
        card = ParchmentCard(padding=14)
        layout = QVBoxLayout(card)
        layout.setSpacing(6)
        self.preview_heading = self._heading(layout)
        self.file_label = mark_data(QLabel())
        self.file_label.setProperty("role", "caption")
        self.file_label.setFont(theme.font("caption"))
        self.file_label.setWordWrap(True)
        layout.addWidget(self.file_label)
        self.preview = QPlainTextEdit()
        self.preview.setObjectName("descriptorPreview")
        self.preview.setReadOnly(True)
        self.preview.setFont(theme.font("mono"))
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.preview.setMinimumHeight(90)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        mark_data(self.preview)
        layout.addWidget(self.preview, 1)
        self.save_note = self._help()
        layout.addWidget(self.save_note)
        return card

    # --- datos -----------------------------------------------------------------------------------

    def _project(self):
        return self.session.project

    def _handle(self):
        project = self._project()
        if project is None:
            return None
        try:
            return project.ws.open(DESCRIPTOR_REL)
        except FileNotFoundError:
            return None

    def reload(self) -> None:
        """Vuelve a leer el formulario del documento del descriptor (al abrir, deshacer o recargar)."""
        project = self._project()
        if project is None:
            self._set_empty((N_("descriptor.empty_text"), {}))
            return
        handle = self._handle()
        self._exists = handle is not None and not handle.deleted
        if self._exists:
            fields = descriptor_from_result(project.vfs.descriptor_path or Path(), handle.model)
            self._spec = DescriptorSpec.from_descriptor(fields)
        else:
            folder = project.mod_root.name
            self._spec = DescriptorSpec(folder, folder, folder)
        if not self._candidates or self._candidates_game != project.game_root:
            self._candidates = candidate_folders(project.game_root)
            self._candidates_game = project.game_root
            self._counts = {}
        read_only = bool(project.read_only) or (handle is not None and handle.read_only_reason is not None)
        for widget in (self.name_edit, self.folder_edit, self.user_dir_edit, self.dependencies_edit,
                       self.same_button, self.suggest_button):
            widget.setEnabled(not read_only)
        self._read_only = read_only
        self._read_only_reason = None if handle is None else handle.read_only_reason
        self._fill(self._spec)
        show_in_stack(self.stack, self.view)
        self.retranslate()

    def _set_empty(self, reason: tuple[str, dict]) -> None:
        self._empty_reason = reason
        self._spec = None
        self._read_only = True
        show_in_stack(self.stack, self.empty)
        self.retranslate()

    def _fill(self, spec: DescriptorSpec) -> None:
        self._filling = True
        try:
            for edit, value in ((self.name_edit, spec.name), (self.folder_edit, spec.folder),
                                (self.user_dir_edit, spec.user_dir)):
                if edit.text() != value:
                    edit.setText(value)
            dependencies = "\n".join(spec.dependencies)
            if self.dependencies_edit.toPlainText() != dependencies:
                self.dependencies_edit.setPlainText(dependencies)
            checked = {p.casefold(): p for p in spec.replace_paths}
            names = list(self._candidates)
            known = {n.casefold() for n in names}
            names += [p for p in spec.replace_paths if p.casefold() not in known]
            if [c.property("folder") for c in self.replace_checks] != names:
                for check in self.replace_checks:
                    self.replace_flow.removeWidget(check)
                    check.deleteLater()
                self.replace_checks = []
                for name in names:
                    check = mark_data(QCheckBox(name))  # el nombre de la carpeta no se traduce
                    check.setProperty("folder", name)
                    check.toggled.connect(self._on_replace_changed)
                    self.replace_flow.addWidget(check)
                    self.replace_checks.append(check)
            for check in self.replace_checks:
                name = check.property("folder")
                check.setProperty("value", checked.get(name.casefold(), name))
                check.setChecked(name.casefold() in checked)
                check.setEnabled(not self._read_only)
        finally:
            self._filling = False

    def form_spec(self) -> DescriptorSpec:
        """Lo que dice ahora el formulario (confirmado o no)."""
        replace = tuple(check.property("value") for check in self.replace_checks if check.isChecked())
        return DescriptorSpec(self.name_edit.text().strip(), self.folder_edit.text().strip(),
                              self.user_dir_edit.text().strip(), replace,
                              _lines(self.dependencies_edit.toPlainText()))

    def problems(self, spec: DescriptorSpec | None = None) -> list:
        project = self._project()
        if project is None:
            return []
        return descriptor_problems(spec or self.form_spec(), project.game_root,
                                   descriptor_file=project.vfs.descriptor_path, mod_root=project.mod_root)

    # --- edición ---------------------------------------------------------------------------------

    def _commit(self, field: str, *, force: bool = False) -> bool:
        """Lleva el formulario al documento en una transacción; False si no había cambios o no se puede.

        Un mod sin descriptor solo lo recibe cuando algo cambia o se pide (``force``, «Crear el descriptor»).
        """
        if self._filling or self._spec is None or self._project() is None or self._read_only:
            return False
        spec = self.form_spec()
        if spec == self._spec and (self._exists or not force):
            return False
        if any(issue.code in FIELD_CODES for issue in self.problems(spec)):
            self._refresh_feedback()  # un valor que no se puede escribir no llega al documento
            return False
        try:
            with self.session.edit(N_("descriptor.undo_edit"), merge_key=f"descriptor.{field}", field=field):
                ws = self._project().ws
                handle = ws.open(DESCRIPTOR_REL, create=True)
                if not self._exists:
                    ws.replace_text(handle, render_descriptor(spec))
                else:
                    ws.touch(handle)
                    apply_descriptor(handle.model.document, spec)
        except DescriptorFieldError:
            self._refresh_feedback()
            return False
        self.reload()
        self.request_status("descriptor.status_edited", field=field)
        return True

    def commit(self, *, force: bool = False) -> bool:
        """Confirma todo el formulario de una vez (lo que hacen los campos al perder el foco)."""
        return self._commit("all", force=force)

    def _on_typing(self, *args) -> None:
        if not self._filling:
            self._refresh_feedback()

    def _on_replace_changed(self, checked: bool) -> None:
        if not self._filling:
            self._commit("replace_path")

    def eventFilter(self, watched, event) -> bool:
        if watched is self.dependencies_edit and event.type() == QEvent.Type.FocusOut:
            self._commit("dependencies")
        return super().eventFilter(watched, event)

    def _use_folder_as_user_dir(self) -> None:
        self.user_dir_edit.setText(self.folder_edit.text().strip())
        self._commit("user_dir")

    def _fill_suggestions(self) -> None:
        self.suggest_menu.clear()
        project = self._project()
        options: list[str] = []
        if project is not None:
            options.append(project.mod_root.name)
        taken = taken_folders(project.game_root if project is not None else None)
        if project is not None:
            taken = taken - {project.mod_root.name.casefold()}
        for option in sanitize_folder(self.name_edit.text(), taken=taken):
            if all(option.casefold() != o.casefold() for o in options):
                options.append(option)
        for option in options:
            action = QAction(option, self.suggest_menu)
            action.triggered.connect(lambda checked=False, value=option: self._use_folder(value))
            self.suggest_menu.addAction(action)

    def _use_folder(self, folder: str) -> None:
        self.folder_edit.setText(folder)
        self._commit("path")

    def _on_documents_changed(self, rels) -> None:
        if any(str(rel) == str(DESCRIPTOR_REL) for rel in rels) and self._project() is not None:
            self.reload()

    # --- textos ----------------------------------------------------------------------------------

    def _refresh_feedback(self) -> None:
        if self._spec is None:
            return
        spec = self.form_spec()
        self.issues = self.problems(spec)
        while len(self.problem_badges) < max(len(self.issues), 1):
            badge = StatusBadge()
            mark_data(badge.label)  # el texto viene del núcleo (modcheck.MESSAGES), ya traducido
            self.problems_box.addWidget(badge)
            self.problem_badges.append(badge)
        lang = language()
        if not self.issues:
            self.problem_badges[0].set_status("ok", tr("descriptor.no_problems"))
            self.problem_badges[0].label.setProperty("i18nData", False)
        for badge, issue in zip(self.problem_badges, self.issues):
            badge.set_status(SEVERITY_LEVELS[issue.severity], issue.message(lang))
            badge.label.setProperty("i18nData", True)
        for index, badge in enumerate(self.problem_badges):
            badge.setVisible(index < max(len(self.issues), 1))
        self._retranslate_preview(spec)
        self._retranslate_effect(spec)
        project = self._project()
        actual = project.mod_root.name if project is not None else ""
        self.folder_help.setText(rich(tr("descriptor.folder_help", folder=actual), 9))

    def _retranslate_preview(self, spec: DescriptorSpec) -> None:
        project = self._project()
        handle = self._handle() if self._exists else None
        if handle is not None:
            text = to_source(handle.model.document)
        else:
            try:
                text = render_descriptor(spec).decode("cp1252")
            except (DescriptorFieldError, UnicodeError, ValueError):
                text = ""
        if self.preview.toPlainText() != text:
            self.preview.setPlainText(text)
        target = project.vfs.descriptor_path if project is not None else None
        name = os.fspath(target) if target is not None else ""
        self.file_label.setText(name)
        dirty = handle is not None and handle.dirty
        key = N_("descriptor.preview_new") if handle is None else (
            N_("descriptor.preview_dirty") if dirty else N_("descriptor.preview_saved"))
        self.save_note.setText(rich(tr(key), 9))

    def _retranslate_effect(self, spec: DescriptorSpec) -> None:
        project = self._project()
        lines = []
        for folder in spec.replace_paths:
            if project is None or project.game_root is None:
                break
            if folder not in self._counts:
                path = project.game_root / folder
                self._counts[folder] = count_files(path) if path.is_dir() else 0
            count = self._counts[folder]
            key = N_("descriptor.replace_effect_one") if count == 1 else N_("descriptor.replace_effect")
            lines.append("• " + tr(key, count=count, folder=folder))
        if not lines:
            lines = [tr("descriptor.replace_effect_none")]
        self.replace_effect.setText(rich("\n".join(lines), 9))

    def retranslate(self) -> None:
        super().retranslate()
        self.new_button.setText(tr("descriptor.new_mod"))
        self.new_button.setToolTip(tr("descriptor.new_mod_tooltip"))
        key, fmt = self._empty_reason
        self.empty.set_texts(tr("descriptor.empty_title"), tr(key, **fmt))
        self.home_button.setText(tr("descriptor.go_home"))
        self.form_heading.setText(tr("descriptor.form_title"))
        self.name_label.setText(tr("descriptor.name"))
        self.name_edit.setToolTip(tr("descriptor.name_tooltip"))
        self.folder_label.setText(tr("descriptor.folder"))
        self.folder_edit.setToolTip(tr("descriptor.folder_tooltip"))
        self.suggest_button.setToolTip(tr("descriptor.suggest_tooltip"))
        self.user_dir_label.setText(tr("descriptor.user_dir"))
        self.user_dir_help.setText(rich(tr("descriptor.user_dir_help"), 9))
        self.same_button.setText(tr("descriptor.same_as_folder"))
        self.same_button.setToolTip(tr("descriptor.same_as_folder_tooltip"))
        self.dependencies_label.setText(tr("descriptor.dependencies"))
        self.dependencies_help.setText(rich(tr("descriptor.dependencies_help"), 9))
        self.replace_heading.setText(tr("descriptor.replace_title"))
        self.replace_help.setText(rich(tr("descriptor.replace_help"), 9))
        self.problems_heading.setText(tr("descriptor.problems_title"))
        self.preview_heading.setText(tr("descriptor.preview_title"))
        project = self._project()
        if project is not None and self._spec is not None and self._read_only:
            key = N_("descriptor.read_only_syntax") if self._read_only_reason == "parse_errors" \
                else N_("descriptor.read_only")
            self.read_only_badge.set_status("warning", tr(key))
            self.read_only_badge.setVisible(True)
        else:
            self.read_only_badge.setVisible(False)
        missing = project is not None and self._spec is not None and not self._exists
        self.missing_box.setVisible(missing)
        target = project.vfs.descriptor_path if project is not None else None
        self.missing_badge.set_status("neutral", tr("descriptor.missing", file=target.name if target else ""))
        self.create_button.setText(tr("descriptor.create"))
        self.create_button.setEnabled(missing and not self._read_only)
        self._refresh_feedback()

    def sizeHint(self) -> QSize:
        return QSize(900, 600)
