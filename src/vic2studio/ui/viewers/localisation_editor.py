"""Tabla de un CSV de localización (solo lectura en esta iteración) con buscador y lint.

``load_localisation`` lee el archivo en un hilo y precalcula todo lo que muestran
la tabla y el lint (tipo de cada fila, texto en minúsculas donde busca el filtro,
filas del lint y peor gravedad por fila): poner en pantalla un archivo enorme solo
asigna listas en el hilo de la interfaz. ``LocalisationFilterProxy`` guarda la
lista de filas visibles, calculada de una vez en Python, de modo que filtrar las
15 000 filas de ``text.csv`` cuesta milisegundos (y medio millón, decenas).

El buscador filtra ``SEARCH_DELAY_MS`` después de la última tecla
(``queue_query``); ``select_line`` aplica antes la búsqueda pendiente para que
no oculte después la fila que acaba de seleccionar.
"""

from __future__ import annotations

import os
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QAbstractProxyModel, QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...core.cancel import CancelCheck, raise_if_cancelled
from ...core.csvloc import DISPLAYED_LANGUAGES, END_MARKER_COLUMN, LANGUAGE_COLUMNS, LANGUAGE_COUNT, \
    LocalisationFile, RowKind, read_csv_file
from ...i18n import N_, tr
from .. import theme
from ..widgets import IconWidget, StatusBadge, mark_data
from .common import ERROR, INFO, SEVERITY_RANK, WARNING, core_language, file_stamp, format_number, severity_icon
from .common import OS_ERROR_KEYS, describe_os_error  # noqa: F401 - antes vivían aquí: se reexportan
from .diagnostics import COL_LINE, COL_MESSAGE, COL_SEVERITY, DiagnosticRow, DiagnosticsModel, DiagnosticsView

# Columnas de idioma en el orden de la tabla: las que muestra el juego vanilla primero.
LANGUAGE_ORDER = (1, 5, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13)
KEY, LANG, MARKER, EXTRAS = "key", "lang", "marker", "extras"
COLUMNS = ((KEY, 0), *((LANG, c) for c in LANGUAGE_ORDER), (MARKER, END_MARKER_COLUMN), (EXTRAS, END_MARKER_COLUMN + 1))
BASIC_COLUMNS = 5  # clave, English, Español, Français, Deutsch
# Endónimos: el nombre de cada idioma en sí mismo no se traduce.
ENDONYMS = {
    1: "English", 2: "Français", 3: "Deutsch", 4: "Polski", 5: "Español", 6: "Italiano", 7: "Svenska",
    8: "Čeština", 9: "Magyar", 10: "Nederlands", 11: "Português", 12: "Русский", 13: "Suomi",
}
SEVERITY_FILTERS = (
    ("all", N_("loc.diag_filter.all"), None),
    ("error", N_("loc.diag_filter.errors"), frozenset({ERROR})),
    ("warning", N_("loc.diag_filter.warnings"), frozenset({WARNING})),
    ("info", N_("loc.diag_filter.infos"), frozenset({INFO})),
)
SEARCH_DELAY_MS = 150  # espera tras la última tecla del buscador antes de filtrar
CANCEL_EVERY = 0x1000  # filas o diagnósticos entre dos consultas de cancelación


def language_header(column: int) -> str:
    """``Español (Spanish)``: endónimo y, si difiere, el nombre de la columna en el CSV."""
    endonym, csv_name = ENDONYMS[column], LANGUAGE_COLUMNS[column - 1]
    return endonym if endonym == csv_name else f"{endonym} ({csv_name})"


@dataclass
class LocalisationLoad:
    """Un CSV leído y todo lo que el editor muestra de él, calculado en el hilo de la tarea."""

    path: Path
    file: LocalisationFile
    stamp: tuple[int, int] | None  # ``file_stamp`` antes de leerlo: si cambia, hay que releerlo
    kinds: list[RowKind]
    haystack: list[str]
    data_rows: int
    row_diagnostics: dict[int, list]  # fila -> sus diagnósticos
    row_severity: dict[int, str]      # fila -> peor gravedad
    diagnostic_rows: list[DiagnosticRow]
    file_diagnostics: list[DiagnosticRow]  # los de todo el archivo (sin línea), como la codificación
    counts: dict[str, int]            # diagnósticos por gravedad


def load_localisation(path: str | os.PathLike, cancelled: CancelCheck = None) -> LocalisationLoad:
    """Lee y valida un CSV y prepara la tabla y el lint (se ejecuta en un hilo).

    Si ``cancelled()`` devuelve True lanza ``core.cancel.Cancelled``.
    """
    path = Path(path)
    stamp = file_stamp(path)  # antes de leer: si el archivo cambia mientras, la próxima apertura lo relee
    file = read_csv_file(path, cancelled=cancelled)
    data = RowKind.DATA
    kinds, haystack = [], []
    for number, row in enumerate(file.rows):
        if not number & (CANCEL_EVERY - 1):
            raise_if_cancelled(cancelled)
        kinds.append(row.kind)
        if row.kind is data:
            haystack.append("\x00".join((row.key, *row.fields[:LANGUAGE_COUNT])).casefold())
        else:
            haystack.append((row.raw or "").casefold())
    by_row: dict[int, list] = {}
    worst: dict[int, str] = {}
    rows, whole_file = [], []
    counts = dict.fromkeys(SEVERITY_RANK, 0)
    for number, diagnostic in enumerate(file.diagnostics):
        if not number & (CANCEL_EVERY - 1):
            raise_if_cancelled(cancelled)
        row = DiagnosticRow.of(diagnostic)
        rows.append(row)
        counts[row.severity] += 1
        if diagnostic.line is None:
            whole_file.append(row)
            continue
        # Recién leído, la fila i está en la línea i + 1 (ver LocalisationFile.lint).
        index = diagnostic.line - 1
        by_row.setdefault(index, []).append(diagnostic)
        current = worst.get(index)
        if current is None or SEVERITY_RANK[row.severity] < SEVERITY_RANK[current]:
            worst[index] = row.severity
    return LocalisationLoad(path, file, stamp, kinds, haystack, kinds.count(data), by_row, worst, rows, whole_file,
                            counts)


@dataclass
class LocalisationFailure:
    """El archivo no se pudo leer (el contenido nunca hace fallar a ``read_csv_file``)."""

    path: Path
    error: OSError


def try_load_localisation(path: str | os.PathLike, cancelled: CancelCheck = None) \
        -> LocalisationLoad | LocalisationFailure:
    try:
        return load_localisation(path, cancelled)
    except OSError as exc:
        return LocalisationFailure(Path(path), exc)


class LocalisationModel(QAbstractTableModel):
    """Modelo de solo lectura sobre ``LocalisationFile.rows`` (una fila por línea del archivo)."""

    HEADER_KEYS = {KEY: N_("loc.col.key"), MARKER: N_("loc.col.marker"), EXTRAS: N_("loc.col.extras")}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.load: LocalisationLoad | None = None
        self.rows: list = []
        self.kinds: list[RowKind] = []
        self.haystack: list[str] = []
        self._severity: dict[int, str] = {}
        self._mono = theme.font("mono")
        self._italic = theme.font("body")
        self._italic.setItalic(True)

    def set_load(self, load: LocalisationLoad | None) -> None:
        self.beginResetModel()
        self.load = load
        self.rows = load.file.rows if load else []
        self.kinds = load.kinds if load else []
        self.haystack = load.haystack if load else []
        self._severity = load.row_severity if load else {}
        self.endResetModel()

    def source_row_for_line(self, line: int) -> int | None:
        candidate = line - 1
        if 0 <= candidate < len(self.rows) and self.rows[candidate].line == line:
            return candidate
        return next((i for i, row in enumerate(self.rows) if row.line == line), None)

    def retranslate(self) -> None:
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(COLUMNS) - 1)
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(COLUMNS) - 1),
                                  [Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.DisplayRole])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Vertical:
            if role == Qt.ItemDataRole.DisplayRole and 0 <= section < len(self.rows):
                return str(self.rows[section].line or "")
            return None
        if not 0 <= section < len(COLUMNS):
            return None
        kind, column = COLUMNS[section]
        if role == Qt.ItemDataRole.DisplayRole:
            return language_header(column) if kind == LANG else tr(self.HEADER_KEYS[kind])
        if role == Qt.ItemDataRole.ToolTipRole:
            # Columnas numeradas desde 0 (la clave), como en los mensajes del lint (ver core.csvloc).
            if kind == LANG:
                name = LANGUAGE_COLUMNS[column - 1]
                return tr("loc.col.lang_tooltip_shown" if name in DISPLAYED_LANGUAGES else "loc.col.lang_tooltip_hidden",
                          column=column, name=name)
            if kind == EXTRAS:
                return tr("loc.col.extras_tooltip")
            return tr("loc.col.marker_tooltip" if kind == MARKER else "loc.col.key_tooltip", column=column)
        return None

    def _cell(self, row, kind: str, column: int) -> str:
        if row.kind is not RowKind.DATA:
            return (row.raw or "") if kind == KEY else ""
        if kind == KEY:
            return row.key
        fields = row.fields
        if kind == EXTRAS:
            return ";".join(fields[END_MARKER_COLUMN:]) if len(fields) > END_MARKER_COLUMN else ""
        return fields[column - 1] if column <= len(fields) else ""

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        number = index.row()
        row = self.rows[number]
        kind, column = COLUMNS[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return self._cell(row, kind, column)
        if role == Qt.ItemDataRole.ToolTipRole:
            parts = []
            text = self._cell(row, kind, column)
            if len(text) > 40:
                parts.append(text)
            diagnostics = self.load.row_diagnostics.get(number) if self.load else None
            if diagnostics and kind == KEY:
                lang = core_language()
                parts.extend(f"• {d.message(lang)}" for d in diagnostics)
            return "\n".join(parts) or None
        if role == Qt.ItemDataRole.DecorationRole and kind == KEY:
            severity = self._severity.get(number)
            return severity_icon(severity) if severity else None
        if role == Qt.ItemDataRole.FontRole:
            if row.kind is not RowKind.DATA:
                return self._italic
            return self._mono if kind in (KEY, MARKER, EXTRAS) else None
        if role == Qt.ItemDataRole.ForegroundRole:
            if row.kind is not RowKind.DATA:
                return theme.color("ink_muted")
            if kind == KEY:
                return theme.color("syntax_key")
            if kind in (MARKER, EXTRAS):
                return theme.color("ink_muted")
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole and kind == MARKER:
            return int(Qt.AlignmentFlag.AlignCenter)
        return None


class LocalisationFilterProxy(QAbstractProxyModel):
    """Filas visibles del modelo: por texto (clave o cualquier idioma) y, si se pide, sin comentarios ni líneas vacías.

    Guarda la lista ordenada de filas visibles, calculada de una vez en Python. Con
    ``QSortFilterProxyModel`` cada fila costaba una llamada a ``filterAcceptsRow`` en el
    hilo de la interfaz: 0,7 s al abrir o filtrar un archivo de medio millón de filas.
    Solo admite un modelo de origen (``LocalisationModel``, de solo lectura).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[int] = []
        self._query = ""
        self._show_comments = False

    def setSourceModel(self, model: LocalisationModel) -> None:
        self.beginResetModel()
        super().setSourceModel(model)
        model.modelAboutToBeReset.connect(self.beginResetModel)
        model.modelReset.connect(self._on_source_reset)
        model.dataChanged.connect(self._on_source_data_changed)
        model.headerDataChanged.connect(self._on_source_header_changed)
        self._on_source_reset()

    def query(self) -> str:
        return self._query

    def show_comments(self) -> bool:
        return self._show_comments

    def set_query(self, text: str) -> None:
        query = text.strip().casefold()
        if query != self._query:
            self._query = query
            self.refresh()

    def set_show_comments(self, show: bool) -> None:
        if show != self._show_comments:
            self._show_comments = show
            self.refresh()

    def visible_source_rows(self, kinds: list[RowKind], haystack: list[str]) -> list[int]:
        query, data = self._query, RowKind.DATA
        if query:
            if self._show_comments:
                return [i for i, text in enumerate(haystack) if query in text]
            return [i for i, (kind, text) in enumerate(zip(kinds, haystack)) if kind is data and query in text]
        if self._show_comments:
            return list(range(len(kinds)))
        return [i for i, kind in enumerate(kinds) if kind is data]

    def refresh(self) -> None:
        """Vuelve a filtrar conservando la selección y la fila actual de las vistas, si siguen visibles."""
        model: LocalisationModel = self.sourceModel()
        rows = self.visible_source_rows(model.kinds, model.haystack)
        self.layoutAboutToBeChanged.emit()
        before = self.persistentIndexList()
        sources = [self._rows[index.row()] for index in before]
        self._rows = rows
        self.changePersistentIndexList(before, [self._proxy_index(row, index.column())
                                                for row, index in zip(sources, before)])
        self.layoutChanged.emit()

    # --- QAbstractProxyModel -------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if parent.isValid() or not (0 <= row < len(self._rows) and 0 <= column < len(COLUMNS)):
            return QModelIndex()
        return self.createIndex(row, column)

    def parent(self, index: QModelIndex | None = None):
        # Sin argumento es QObject.parent(); en la tabla ninguna fila tiene padre.
        return super().parent() if index is None else QModelIndex()

    def mapToSource(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        return self.sourceModel().index(self._rows[index.row()], index.column())

    def mapFromSource(self, index: QModelIndex) -> QModelIndex:
        return self._proxy_index(index.row(), index.column()) if index.isValid() else QModelIndex()

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        # La implementación base traduce la columna a través de la fila 0: sin filas visibles no habría cabeceras.
        if orientation == Qt.Orientation.Vertical:
            if not 0 <= section < len(self._rows):
                return None
            section = self._rows[section]
        return self.sourceModel().headerData(section, orientation, role)

    # --- interno -------------------------------------------------------------------------

    def _proxy_index(self, source_row: int, column: int) -> QModelIndex:
        position = bisect_left(self._rows, source_row)
        if position < len(self._rows) and self._rows[position] == source_row:
            return self.createIndex(position, column)
        return QModelIndex()

    def _on_source_reset(self) -> None:
        model: LocalisationModel = self.sourceModel()
        self._rows = self.visible_source_rows(model.kinds, model.haystack)
        self.endResetModel()

    def _on_source_data_changed(self, top_left: QModelIndex, bottom_right: QModelIndex, roles=()) -> None:
        first = bisect_left(self._rows, top_left.row())
        last = bisect_right(self._rows, bottom_right.row()) - 1
        if first <= last:
            self.dataChanged.emit(self.index(first, top_left.column()), self.index(last, bottom_right.column()),
                                  list(roles))

    def _on_source_header_changed(self, orientation: Qt.Orientation, first: int, last: int) -> None:
        if orientation == Qt.Orientation.Horizontal:  # las columnas son las mismas
            self.headerDataChanged.emit(orientation, first, last)


class LocalisationEditor(QWidget):
    """Tabla + panel de diagnósticos. ``query_reset`` pide al buscador de la página que se vacíe.

    Los diagnósticos de todo el archivo (sin fila, como una codificación que el
    juego no lee) se muestran además encima de la tabla (``file_notice``).
    """

    query_reset = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("localisationEditor")
        self._pending_query: str | None = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self._apply_pending_query)
        self._counts = dict.fromkeys(SEVERITY_RANK, 0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.lock_icon = IconWidget("lock", 16, "ink_muted")
        bar.addWidget(self.lock_icon)
        self.read_only = QLabel()
        self.read_only.setObjectName("readOnlyNotice")
        self.read_only.setProperty("role", "caption")
        self.read_only.setFont(theme.font("caption"))
        bar.addWidget(self.read_only)
        bar.addStretch(1)
        self.comments_check = QCheckBox()
        self.comments_check.setObjectName("showComments")
        self.comments_check.toggled.connect(self._on_comments_toggled)
        bar.addWidget(self.comments_check)
        self.columns_check = QCheckBox()
        self.columns_check.setObjectName("showAllColumns")
        self.columns_check.toggled.connect(self._apply_columns)
        bar.addWidget(self.columns_check)
        self.count_label = QLabel()
        self.count_label.setObjectName("rowCount")
        self.count_label.setProperty("role", "heading")
        self.count_label.setFont(theme.font("body_bold", 9.5))
        bar.addWidget(self.count_label)
        layout.addLayout(bar)
        self.file_notice = StatusBadge()
        self.file_notice.setObjectName("fileNotice")
        self.file_notice.setVisible(False)
        layout.addWidget(self.file_notice)

        self.model = LocalisationModel(self)
        self.proxy = LocalisationFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.layoutChanged.connect(self._update_counts)  # filtrar
        self.proxy.modelReset.connect(self._update_counts)     # otro archivo
        self.table = QTableView()
        self.table.setObjectName("localisationTable")
        mark_data(self.table)
        self.table.setModel(self.proxy)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setCornerButtonEnabled(False)
        vertical = self.table.verticalHeader()
        vertical.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vertical.setDefaultSectionSize(self.fontMetrics().height() + 8)
        vertical.setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        horizontal = self.table.horizontalHeader()
        horizontal.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        horizontal.setStretchLastSection(True)
        horizontal.setHighlightSections(False)
        horizontal.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for section, (kind, _) in enumerate(COLUMNS):
            horizontal.resizeSection(section, 230 if kind == KEY else 60 if kind == MARKER else 250)

        self.diagnostics_panel = QWidget()
        panel = QVBoxLayout(self.diagnostics_panel)
        panel.setContentsMargins(0, 4, 0, 0)
        panel.setSpacing(4)
        head = QHBoxLayout()
        self.diagnostics_title = QLabel()
        self.diagnostics_title.setObjectName("lintTitle")
        self.diagnostics_title.setProperty("role", "heading")
        self.diagnostics_title.setFont(theme.font("heading", 10.5))
        head.addWidget(self.diagnostics_title)
        head.addStretch(1)
        self.severity_combo = QComboBox()
        self.severity_combo.setObjectName("lintSeverity")
        # El ancho sigue a los textos: con el valor por defecto se fija en el idioma del primer show.
        self.severity_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for data, _, _ in SEVERITY_FILTERS:
            self.severity_combo.addItem("", data)
        self.severity_combo.currentIndexChanged.connect(self._apply_severity)
        head.addWidget(self.severity_combo)
        panel.addLayout(head)
        self.diagnostics_model = DiagnosticsModel((COL_SEVERITY, COL_LINE, COL_MESSAGE), self)
        self.diagnostics_view = DiagnosticsView(self.diagnostics_model)
        self.diagnostics_view.setObjectName("lintView")
        self.diagnostics_view.diagnostic_activated.connect(lambda row: self.select_line(row.line))
        panel.addWidget(self.diagnostics_view, 1)
        self.table.selectionModel().currentRowChanged.connect(self._sync_diagnostics)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.table)
        self.splitter.addWidget(self.diagnostics_panel)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([430, 220])
        layout.addWidget(self.splitter, 1)
        self._apply_columns()
        self.retranslate()

    # --- API -----------------------------------------------------------------------------

    def current_load(self) -> LocalisationLoad | None:
        return self.model.load

    def set_load(self, load: LocalisationLoad | None) -> None:
        self.model.set_load(load)
        self.diagnostics_model.set_rows(load.diagnostic_rows if load else [])
        self._counts = load.counts if load else dict.fromkeys(SEVERITY_RANK, 0)
        self.table.scrollToTop()
        self._retranslate_diagnostics()
        self._update_counts()

    def set_query(self, text: str) -> None:
        """Filtra ya por ``text`` y descarta la búsqueda pendiente."""
        self._search_timer.stop()
        self._pending_query = None
        self.proxy.set_query(text)

    def queue_query(self, text: str) -> None:
        """Filtra por ``text`` cuando pasen ``SEARCH_DELAY_MS`` sin otra llamada (para teclear)."""
        self._pending_query = text
        self._search_timer.start()

    def visible_rows(self) -> int:
        return self.proxy.rowCount()

    def total_rows(self) -> int:
        return self.model.rowCount()

    def select_line(self, line: int | None) -> bool:
        """Selecciona y centra la fila de la línea ``line``; vacía el filtro si la ocultaba."""
        if line is None:
            return False
        source = self.model.source_row_for_line(line)
        if source is None:
            return False
        self._apply_pending_query()  # si no, filtraría después y ocultaría la fila seleccionada
        index = self.proxy.mapFromSource(self.model.index(source, 0))
        if not index.isValid():
            if self.model.kinds[source] is not RowKind.DATA:
                self.comments_check.setChecked(True)
            if self.proxy.query():
                self.proxy.set_query("")
                self.query_reset.emit()
            index = self.proxy.mapFromSource(self.model.index(source, 0))
            if not index.isValid():
                return False
        self.table.setCurrentIndex(index)
        self.table.selectRow(index.row())
        self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        return True

    def selected_line(self) -> int | None:
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        return self.model.rows[self.proxy.mapToSource(index).row()].line

    # --- interno -------------------------------------------------------------------------

    def _sync_diagnostics(self, current, previous) -> None:
        """Al cambiar de fila en la tabla, selecciona (sin activarlo) su primer diagnóstico."""
        line = self.selected_line()
        if line is None:
            return
        view = self.diagnostics_view
        current = self.diagnostics_model.row_at(view.currentIndex())
        if current is not None and current.line == line:
            return
        for position, row in enumerate(self.diagnostics_model.visible_rows()):
            if row.line == line:
                index = self.diagnostics_model.index(position, 0)
                view.setCurrentIndex(index)
                view.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtTop)
                return
        # También el índice actual: si quedara, volver a esta fila parecería no necesitar seleccionar nada.
        view.selectionModel().clear()

    def _apply_pending_query(self) -> None:
        if self._pending_query is not None:
            self.set_query(self._pending_query)

    def _on_comments_toggled(self, show: bool) -> None:
        self.proxy.set_show_comments(show)

    def _apply_columns(self, *args) -> None:
        show_all = self.columns_check.isChecked()
        for section in range(BASIC_COLUMNS, len(COLUMNS)):
            self.table.setColumnHidden(section, not show_all)

    def _apply_severity(self, index: int) -> None:
        self.diagnostics_model.set_filter(SEVERITY_FILTERS[max(0, index)][2])
        self._retranslate_diagnostics()

    def _update_counts(self, *args) -> None:
        self.count_label.setText(tr("loc.row_count", shown=format_number(self.visible_rows()),
                                    total=format_number(self.total_rows())))

    def _retranslate_diagnostics(self) -> None:
        counts = self._counts
        self.diagnostics_title.setText(tr("loc.diagnostics_title", count=format_number(sum(counts.values())),
                                          errors=format_number(counts[ERROR]),
                                          warnings=format_number(counts[WARNING]), infos=format_number(counts[INFO])))
        load = self.model.load
        problems = [row for row in load.file_diagnostics if row.severity != INFO] if load else []
        self.file_notice.setVisible(bool(problems))
        if problems:
            worst = min(problems, key=lambda row: SEVERITY_RANK[row.severity])
            self.file_notice.set_status(worst.severity, tr("loc.file_notice", message=worst.message(core_language())))

    def retranslate(self) -> None:
        self.read_only.setText(tr("loc.read_only"))
        self.read_only.setToolTip(tr("loc.read_only_tooltip"))
        self.lock_icon.setToolTip(tr("loc.read_only_tooltip"))
        self.comments_check.setText(tr("loc.show_comments"))
        self.comments_check.setToolTip(tr("loc.show_comments_tooltip"))
        self.columns_check.setText(tr("loc.show_all_columns"))
        self.columns_check.setToolTip(tr("loc.show_all_columns_tooltip"))
        self.severity_combo.setToolTip(tr("loc.diag_filter_tooltip"))
        for i, (_, key, _) in enumerate(SEVERITY_FILTERS):
            self.severity_combo.setItemText(i, tr(key))
        self.diagnostics_view.setToolTip(tr("loc.diagnostics_tooltip"))
        self.model.retranslate()
        self.diagnostics_model.retranslate()
        self._retranslate_diagnostics()
        self._update_counts()
