"""Localización (CSV): barra de herramientas, tabla del CSV abierto y diagnósticos de lint.

El CSV se lee en segundo plano (``load_localisation``) y se muestra en un
``LocalisationEditor`` de solo lectura en esta iteración (la edición llega en la
iteración 2). Mientras se lee otro, sigue a la vista el anterior; si no se puede
abrir, el motivo traducido queda en la página (``error_badge``) hasta el
siguiente intento. Puntos de extensión:

* ``open_file(ruta, line=None)``: abre un CSV (diálogo, lista del mod o explorador
  de «Proyecto y Archivos») y, si se indica, selecciona la fila de esa línea. Si
  ya está abierto y no ha cambiado en disco, reutiliza la lectura; si cambió, lo relee.
* ``reload_if_changed()``: relee el CSV abierto si cambió en disco (también al volver a la página).
* ``open_requested(Path)``: se emite al pedir un CSV.
* ``search_changed(str)``: texto del buscador (habilitado cuando hay un CSV abierto).
* ``set_central_widget(widget)``: instala otro editor; ``None`` vuelve al estado vacío.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import QDir, QSize, Qt, Signal
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

from ...core.csvloc import is_localisation_csv
from ...i18n import N_, tr
from .. import theme
from ..tasks import TaskRunner
from ..viewers import LocalisationEditor
from ..viewers.common import ElidedLabel, describe_os_error, file_stamp, format_number, format_seconds
from ..viewers.localisation_editor import LocalisationFailure, try_load_localisation
from ..widgets import EmptyState, ParchmentCard, StatusBadge, make_icon, mark_data, rich, show_in_stack
from .base import BasePage

LOCALISATION_DIR = "localisation"


class LocalisationPage(BasePage):
    key = "localisation"
    title_key = N_("nav.localisation")
    subtitle_key = N_("page.localisation.subtitle")
    icon_name = "localisation"

    open_requested = Signal(object)  # Path
    search_changed = Signal(str)

    def build(self) -> None:
        self._mod_path: Path | None = None
        self._current_file: Path | None = None  # el que se ve en el editor
        self._loading: Path | None = None       # el que se está leyendo
        self._failure: tuple[Path, BaseException] | None = None
        self._central: QWidget | None = None
        self._pending_line: int | None = None
        self._open_started = 0.0
        self._mod_files: list[Path] = []

        self._runner = TaskRunner(self)
        self._runner.finished.connect(self._on_loaded)
        self._runner.failed.connect(self._on_failed)

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
        # Se rellena al abrirse, volviendo a leer la carpeta: así siempre la refleja.
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
        # Ocupa el hueco restante y recorta con «…»: un nombre largo no desborda la barra a 1100 px.
        self.file_label = ElidedLabel(mode=Qt.TextElideMode.ElideRight)
        self.file_label.setObjectName("csvFileLabel")
        self.file_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.file_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.file_label.setProperty("role", "caption")
        self.file_label.setFont(theme.font("caption"))
        self.toolbar.addWidget(self.file_label)
        self.loading_bar = QProgressBar()
        self.loading_bar.setObjectName("csvLoading")
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setFixedWidth(110)
        self.loading_bar.setMaximumHeight(12)
        self.loading_bar_action = self.toolbar.addWidget(self.loading_bar)
        self.loading_bar_action.setVisible(False)
        self.body.addWidget(self.toolbar)
        self.error_badge = StatusBadge()
        self.error_badge.setObjectName("csvOpenError")
        self.error_badge.setVisible(False)
        self.body.addWidget(self.error_badge)

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
        self.refresh_mod_files()

    def refresh_mod_files(self) -> None:
        """Vuelve a listar los CSV de ``localisation/`` del mod: la carpeta cambia también fuera de la aplicación."""
        folder = self._mod_path / LOCALISATION_DIR if self._mod_path else None
        try:
            # iterdir y no glob("*.csv"): en Linux glob distingue mayúsculas, y el juego (Windows) carga «.CSV».
            files = sorted((p for p in folder.iterdir() if is_localisation_csv(p) and p.is_file()),
                           key=lambda p: p.name.lower()) if folder and folder.is_dir() else []
        except OSError:
            files = []
        if files != self._mod_files or self.files_list.count() != len(files):
            self._mod_files = files
            current = self.files_list.currentItem()
            selected = current.data(Qt.ItemDataRole.UserRole) if current else None
            self.files_list.clear()
            icon = make_icon("file_table", "success", "cream")
            for file in files:
                item = QListWidgetItem(icon, file.name)
                item.setData(Qt.ItemDataRole.UserRole, os.fspath(file))
                item.setToolTip(os.fspath(file))
                self.files_list.addItem(item)
                if item.data(Qt.ItemDataRole.UserRole) == selected:
                    self.files_list.setCurrentItem(item)
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
        """Lee el CSV en segundo plano y lo muestra; ``line`` selecciona esa fila al terminar.

        Si ya se muestra y no ha cambiado en disco se reutiliza la lectura; si cambió
        (o ya no se puede leer), se vuelve a leer.
        """
        path = Path(path)
        self._pending_line = line
        self._set_failure(None)
        self.open_requested.emit(path)
        if self._runner.is_busy() and self._loading == path:
            return  # la lectura en curso aplicará la línea
        load = self.editor.current_load()
        if load is not None and load.path == path and load.stamp == file_stamp(path):
            self._stop_loading()
            self.set_central_widget(self.editor)
            self._apply_pending_line()
            return
        self._loading = path
        self._open_started = time.perf_counter()
        self.loading_bar_action.setVisible(True)
        self._retranslate_file_label()
        self.request_status("status.csv_loading", name=path.name)
        self._runner.start(lambda ctx: try_load_localisation(path, ctx.cancelled))

    def reload_if_changed(self) -> bool:
        """Vuelve a leer el CSV abierto si cambió en disco (conservando la fila seleccionada); ``True`` si lo hace."""
        load = self.editor.current_load()
        if load is None or self._runner.is_busy() or self._central is not self.editor \
                or load.stamp == file_stamp(load.path):
            return False
        self.open_file(load.path, line=self.editor.selected_line())
        return True

    def close_file(self) -> None:
        closed = self._current_file or self._loading
        self._stop_loading()
        self._pending_line = None
        self._current_file = None
        self.editor.set_load(None)
        self.set_central_widget(None)
        self._retranslate_file_label()
        self.refresh_mod_files()
        if closed is not None:
            self.request_status("status.csv_closed", name=closed.name)

    # --- interno -------------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_mod_files()
        self.reload_if_changed()

    def _stop_loading(self) -> None:
        self._runner.cancel()
        self._loading = None
        self.loading_bar_action.setVisible(False)
        self._retranslate_file_label()

    def _on_loaded(self, load) -> None:
        if isinstance(load, LocalisationFailure):
            self._show_failure(load.path, load.error)
            return
        self._loading = None
        self._current_file = load.path
        self.loading_bar_action.setVisible(False)
        self.editor.set_load(load)
        self.editor.set_query(self.search_edit.text())
        self.set_central_widget(self.editor)
        self._retranslate_file_label()
        seconds = time.perf_counter() - self._open_started
        # Invocables: la barra de estado los vuelve a formatear si cambia el idioma.
        self.request_status("status.csv_loaded", name=load.path.name, rows=lambda: format_number(load.data_rows),
                            seconds=lambda: format_seconds(seconds))
        self._apply_pending_line()

    def _on_failed(self, failure) -> None:
        self._show_failure(self._loading, failure.exception)

    def _show_failure(self, path: Path, error: BaseException) -> None:
        """Deja a la vista lo que se mostraba y explica en la página por qué no se pudo abrir ``path``."""
        self._loading = None
        self._pending_line = None
        self.loading_bar_action.setVisible(False)
        self._retranslate_file_label()
        self._set_failure((path, error))
        self.refresh_mod_files()  # quizá se borró: que la lista no lo siga ofreciendo
        self.request_status("status.csv_failed", name=path.name, error=lambda: describe_os_error(error)[0])

    def _set_failure(self, failure: tuple[Path, BaseException] | None) -> None:
        self._failure = failure
        self.error_badge.setVisible(failure is not None)
        self._retranslate_failure()

    def _apply_pending_line(self) -> None:
        line, self._pending_line = self._pending_line, None
        if line is not None:
            self.editor.select_line(line)

    def _on_search_text(self, text: str) -> None:
        self.search_changed.emit(text)
        self.editor.queue_query(text)

    def _on_query_reset(self) -> None:
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self.search_changed.emit("")

    def _fill_mod_files_menu(self) -> None:
        self.refresh_mod_files()
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
        # Durante una lectura el editor aún muestra el archivo anterior: la etiqueta nombra los dos.
        shown = tr("localisation.current_file", name=self._current_file.name) if self._current_file else None
        if self._loading is not None:
            loading = tr("status.csv_loading", name=self._loading.name)
            text = f"{loading} · {shown}" if shown else loading
        else:
            text = shown or tr("localisation.no_file")
        self.file_label.setText(text)
        self.file_label.setToolTip(text)

    def _retranslate_failure(self) -> None:
        if self._failure is None:
            return
        path, error = self._failure
        reason, detail = describe_os_error(error)
        self.error_badge.set_status("error", tr("status.csv_failed", name=path.name, error=reason))
        self.error_badge.setToolTip(tr("file_error.detail", path=os.fspath(path), detail=detail))

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
        self._retranslate_failure()
        self.empty.set_texts(tr("localisation.empty_title"), tr("localisation.empty_text"))
        self.empty_open.setText(tr("localisation.open"))
        self.empty_open.setToolTip(tr("localisation.open_tooltip"))
        self.format_label.setText(rich(tr("localisation.format")))
        self.roadmap_label.setText(tr("localisation.roadmap"))
        self._retranslate_files()
        self.editor.retranslate()
