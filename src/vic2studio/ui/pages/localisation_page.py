"""Localización (CSV): barra de herramientas, tabla del CSV abierto y diagnósticos de lint.

El CSV se lee en segundo plano (``load_localisation``) y se muestra en un
``LocalisationEditor`` de solo lectura en esta iteración (la edición llega en la
iteración 2). Puntos de extensión:

* ``open_file(ruta, line=None)``: abre un CSV (diálogo, lista del mod o explorador
  de «Proyecto y Archivos») y, si se indica, selecciona la fila de esa línea.
* ``open_requested(Path)``: se emite al pedir un CSV.
* ``search_changed(str)``: texto del buscador (habilitado cuando hay un CSV abierto).
* ``set_central_widget(widget)``: instala otro editor; ``None`` vuelve al estado vacío.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import QDir, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...i18n import N_, tr, translator
from .. import theme
from ..tasks import TaskRunner
from ..viewers import LocalisationEditor
from ..viewers.localisation_editor import LocalisationFailure, try_load_localisation
from ..widgets import EmptyState, ParchmentCard, make_icon, mark_data, rich, show_in_stack
from .base import BasePage

LOCALISATION_DIR = "localisation"
SEARCH_DELAY_MS = 150


class LocalisationPage(BasePage):
    key = "localisation"
    title_key = N_("nav.localisation")
    subtitle_key = N_("page.localisation.subtitle")
    icon_name = "localisation"

    open_requested = Signal(object)  # Path
    search_changed = Signal(str)
    file_loaded = Signal(object)  # LocalisationLoad

    def build(self) -> None:
        self._mod_path: Path | None = None
        self._current_file: Path | None = None
        self._central: QWidget | None = None
        self._pending_line: int | None = None
        self._open_started = 0.0
        self._mod_files: list[Path] = []
        self.last_open_seconds: float | None = None

        self._runner = TaskRunner(self)
        self._runner.finished.connect(self._on_loaded)
        self._runner.failed.connect(self._on_failed)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self._apply_search)

        self.toolbar = QToolBar()
        self.toolbar.setObjectName("localisationToolbar")
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QSize(18, 18))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.open_action = QAction(make_icon("folder_open", "gold_light"), "", self)
        self.open_action.setObjectName("openCsvAction")
        self.open_action.triggered.connect(self.browse_csv)
        self.toolbar.addAction(self.open_action)
        self.mod_files_button = QToolButton()
        self.mod_files_button.setObjectName("modCsvMenuButton")
        self.mod_files_button.setIcon(make_icon("file_table", "gold_light"))
        self.mod_files_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.mod_files_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.mod_files_menu = QMenu(self.mod_files_button)
        # Se rellena al abrirse: así siempre refleja la carpeta y no deja acciones con nombres de archivo.
        self.mod_files_menu.aboutToShow.connect(self._fill_mod_files_menu)
        self.mod_files_button.setMenu(self.mod_files_menu)
        self.toolbar.addWidget(self.mod_files_button)
        self.close_action = QAction(make_icon("error", "gold_light"), "", self)
        self.close_action.setObjectName("closeCsvAction")
        self.close_action.triggered.connect(self.close_file)
        self.close_action.setEnabled(False)
        self.toolbar.addAction(self.close_action)
        self.toolbar.addSeparator()
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("localisationSearch")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(300)
        self.search_edit.addAction(make_icon("search", "ink_muted"), QLineEdit.ActionPosition.LeadingPosition)
        self.search_edit.textChanged.connect(self._on_search_text)
        self.search_edit.setEnabled(False)
        self.toolbar.addWidget(self.search_edit)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)
        self.loading_bar = QProgressBar()
        self.loading_bar.setObjectName("csvLoading")
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setFixedWidth(110)
        self.loading_bar.setMaximumHeight(12)
        self.loading_bar_action = self.toolbar.addWidget(self.loading_bar)
        self.loading_bar_action.setVisible(False)
        self.file_label = QLabel()
        self.file_label.setProperty("role", "caption")
        self.file_label.setFont(theme.font("caption"))
        self.toolbar.addWidget(self.file_label)
        self.body.addWidget(self.toolbar)

        self.stack = QStackedWidget()
        self.empty_card = ParchmentCard(padding=16)
        card = QHBoxLayout(self.empty_card)
        card.setSpacing(20)
        self.empty = EmptyState("quill")
        self.empty_open = QPushButton()
        self.empty_open.setObjectName("emptyOpenCsv")
        self.empty_open.setProperty("accent", True)
        self.empty_open.setIcon(make_icon("folder_open", "gold_pale"))
        self.empty_open.clicked.connect(self.browse_csv)
        self.empty.add_action(self.empty_open)
        self.format_label = QLabel()
        self.format_label.setTextFormat(Qt.TextFormat.RichText)
        self.format_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.format_label.setWordWrap(True)
        self.format_label.setProperty("role", "caption")
        self.empty.extra.addWidget(self.format_label)
        self.roadmap_label = QLabel()
        self.roadmap_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.roadmap_label.setProperty("role", "heading")
        self.roadmap_label.setFont(theme.font("caption"))
        self.empty.extra.addWidget(self.roadmap_label)
        card.addWidget(self.empty, 3)

        self.files_group = QGroupBox()
        self.files_group.setObjectName("modCsvGroup")
        self.files_group.setFont(theme.font("heading"))
        self.files_group.setMinimumWidth(280)
        self.files_group.setMaximumWidth(420)
        files_inner = QWidget()
        files_inner.setFont(theme.font("body"))
        QVBoxLayout(self.files_group).addWidget(files_inner)
        side = QVBoxLayout(files_inner)
        side.setContentsMargins(0, 4, 0, 0)
        side.setSpacing(6)
        self.files_list = QListWidget()
        self.files_list.setObjectName("modCsvList")
        self.files_list.setAlternatingRowColors(True)
        self.files_list.setIconSize(QSize(18, 18))
        self.files_list.itemActivated.connect(self._on_item_activated)
        mark_data(self.files_list)
        side.addWidget(self.files_list, 1)
        self.files_hint = QLabel()
        self.files_hint.setProperty("role", "caption")
        self.files_hint.setFont(theme.font("caption"))
        self.files_hint.setWordWrap(True)
        side.addWidget(self.files_hint)
        self.files_empty = QWidget()
        self.files_empty.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        side.addWidget(self.files_empty)
        card.addWidget(self.files_group, 2)
        self.stack.addWidget(self.empty_card)

        self.editor = LocalisationEditor()
        self.editor.query_reset.connect(self._on_query_reset)
        self.stack.addWidget(self.editor)
        show_in_stack(self.stack, self.empty_card)
        self.body.addWidget(self.stack, 1)

    # --- API pública ---------------------------------------------------------------------

    def set_central_widget(self, widget: QWidget | None) -> None:
        """Instala el editor en el área central; el anterior se retira sin destruirlo."""
        if self._central is not None and self._central is not widget:
            if self._central is not self.editor:
                self.stack.removeWidget(self._central)
            self._central.hide()
            self._central = None
        if widget is not None:
            if self.stack.indexOf(widget) < 0:
                self.stack.addWidget(widget)
            self._central = widget
            show_in_stack(self.stack, widget)
        else:
            show_in_stack(self.stack, self.empty_card)
        self.search_edit.setEnabled(widget is not None)
        self.close_action.setEnabled(widget is not None)

    def central_widget(self) -> QWidget | None:
        return self._central

    def current_file(self) -> Path | None:
        return self._current_file

    def is_busy(self) -> bool:
        return self._runner.is_busy()

    def shutdown(self) -> None:
        self._runner.cancel()

    def set_mod_path(self, path: Path | None) -> None:
        self._mod_path = Path(path) if path else None
        self.files_list.clear()
        self.mod_files_menu.clear()
        folder = self._mod_path / LOCALISATION_DIR if self._mod_path else None
        files = sorted((p for p in folder.glob("*.csv") if p.is_file()), key=lambda p: p.name.lower()) \
            if folder and folder.is_dir() else []
        self._mod_files = files
        icon = make_icon("file_table", "success", "cream")
        for file in files:
            item = QListWidgetItem(icon, file.name)
            item.setData(Qt.ItemDataRole.UserRole, os.fspath(file))
            item.setToolTip(os.fspath(file))
            self.files_list.addItem(item)
        self.mod_files_button.setEnabled(bool(files))
        self.files_list.setVisible(bool(files))
        self.files_empty.setVisible(not files)
        self._retranslate_files()

    def browse_csv(self) -> None:
        start = self._mod_path / LOCALISATION_DIR if self._mod_path else None
        directory = os.fspath(start) if start and start.is_dir() else QDir.homePath()
        chosen, _ = QFileDialog.getOpenFileName(self, tr("localisation.dialog_title"), directory,
                                                tr("localisation.dialog_filter"))
        if chosen:
            self.open_file(Path(chosen))

    def open_file(self, path: str | os.PathLike, line: int | None = None) -> None:
        """Lee el CSV en segundo plano y lo muestra; ``line`` selecciona esa fila al terminar."""
        path = Path(path)
        self._current_file = path
        self._pending_line = line
        self._retranslate_file_label()
        self.open_requested.emit(path)
        load = self.editor.current_load()
        if load is not None and load.path == path and not self._runner.is_busy():
            self.set_central_widget(self.editor)
            self._apply_pending_line()
            return
        self._open_started = time.perf_counter()
        self.loading_bar_action.setVisible(True)
        self.request_status("status.csv_loading", name=path.name)
        self._runner.start(lambda ctx: try_load_localisation(path))

    def close_file(self) -> None:
        self._runner.cancel()
        self.loading_bar_action.setVisible(False)
        self._current_file = None
        self.editor.set_load(None)
        self.set_central_widget(None)
        self._retranslate_file_label()

    # --- interno -------------------------------------------------------------------------

    def _on_loaded(self, load) -> None:
        if isinstance(load, LocalisationFailure):
            self._show_failure(load.message)
            return
        self.editor.set_load(load)
        self.editor.set_query(self.search_edit.text())
        self.set_central_widget(self.editor)
        self.loading_bar_action.setVisible(False)
        seconds = self.last_open_seconds = time.perf_counter() - self._open_started
        self._retranslate_file_label()
        rows = self.editor.data_rows()
        # Invocables: la barra de estado los vuelve a formatear si cambia el idioma.
        self.request_status("status.csv_loaded", name=load.path.name,
                            rows=lambda: translator().locale().toString(rows),
                            seconds=lambda: translator().locale().toString(seconds, "f", 2))
        self._apply_pending_line()
        self.file_loaded.emit(load)

    def _on_failed(self, failure) -> None:
        self._show_failure(str(failure.exception))

    def _show_failure(self, message: str) -> None:
        self.loading_bar_action.setVisible(False)
        failed = self._current_file
        load = self.editor.current_load()
        self._current_file = load.path if load is not None and self._central is self.editor else None
        self._retranslate_file_label()
        self.request_status("status.csv_failed", name=failed.name if failed else "", error=message)

    def _apply_pending_line(self) -> None:
        line, self._pending_line = self._pending_line, None
        if line is not None:
            self.editor.select_line(line)

    def _on_search_text(self, text: str) -> None:
        self.search_changed.emit(text)
        self._search_timer.start()

    def _apply_search(self) -> None:
        self.editor.set_query(self.search_edit.text())

    def _on_query_reset(self) -> None:
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self.search_changed.emit("")

    def _fill_mod_files_menu(self) -> None:
        self.mod_files_menu.clear()
        icon = make_icon("file_table", "success", "cream")
        for file in self._mod_files:
            action = self.mod_files_menu.addAction(icon, file.name)
            action.setCheckable(True)
            action.setChecked(file == self._current_file)
            action.triggered.connect(lambda checked=False, f=file: self.open_file(f))

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        self.open_file(Path(item.data(Qt.ItemDataRole.UserRole)))

    def _retranslate_file_label(self) -> None:
        if self._current_file:
            self.file_label.setText(tr("localisation.current_file", name=self._current_file.name))
        else:
            self.file_label.setText(tr("localisation.no_file"))

    def _retranslate_files(self) -> None:
        count = self.files_list.count()
        self.files_group.setTitle(tr("localisation.mod_files", count=count))
        self.mod_files_button.setText(tr("localisation.mod_files_menu", count=count))
        self.mod_files_button.setToolTip(tr("localisation.mod_files_menu_tooltip"))
        if count:
            self.files_hint.setText(tr("localisation.mod_files_hint"))
        elif self._mod_path:
            self.files_hint.setText(tr("localisation.mod_files_none"))
        else:
            self.files_hint.setText(tr("localisation.mod_files_no_mod"))

    def retranslate(self) -> None:
        super().retranslate()
        self.open_action.setText(tr("localisation.open"))
        self.open_action.setToolTip(tr("localisation.open_tooltip"))
        self.close_action.setText(tr("localisation.close"))
        self.close_action.setToolTip(tr("localisation.close_tooltip"))
        self.search_edit.setPlaceholderText(tr("localisation.search_placeholder"))
        self.search_edit.setToolTip(tr("localisation.search_tooltip"))
        self.loading_bar.setToolTip(tr("localisation.loading"))
        self._retranslate_file_label()
        self.empty.set_texts(tr("localisation.empty_title"), tr("localisation.empty_text"))
        self.empty_open.setText(tr("localisation.open"))
        self.empty_open.setToolTip(tr("localisation.open_tooltip"))
        self.format_label.setText(rich(tr("localisation.format")))
        self.roadmap_label.setText(tr("localisation.roadmap"))
        self._retranslate_files()
        self.editor.retranslate()
