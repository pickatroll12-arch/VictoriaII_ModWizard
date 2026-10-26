"""Tabla de un CSV de localización (solo lectura en esta iteración) con buscador y lint.

``load_localisation`` lee el archivo en un hilo y precalcula, por fila, el texto
en minúsculas donde busca el filtro. ``LocalisationFilterProxy`` decide qué filas
se ven con una máscara calculada de una vez en Python, de modo que filtrar las
15 000 filas de ``text.csv`` cuesta milisegundos.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
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

from ...core.csvloc import DISPLAYED_LANGUAGES, END_MARKER_COLUMN, LANGUAGE_COLUMNS, LANGUAGE_COUNT, \
    LocalisationFile, RowKind, read_csv_file
from ...i18n import N_, tr
from .. import theme
from ..widgets import IconWidget, mark_data
from .common import ERROR, INFO, SEVERITY_RANK, WARNING, core_language, format_number, severity_icon, \
    severity_name
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


def language_header(column: int) -> str:
    """``Español (Spanish)``: endónimo y, si difiere, el nombre de la columna en el CSV."""
    endonym, csv_name = ENDONYMS[column], LANGUAGE_COLUMNS[column - 1]
    return endonym if endonym == csv_name else f"{endonym} ({csv_name})"


@dataclass
class LocalisationLoad:
    path: Path
    file: LocalisationFile
    haystack: list[str]
    row_diagnostics: dict[int, list] = field(default_factory=dict)
    size: int = 0
    elapsed: float = 0.0


def load_localisation(path: str | os.PathLike) -> LocalisationLoad:
    """Lee y valida un CSV y prepara el índice de búsqueda (se ejecuta en un hilo)."""
    start = time.perf_counter()
    path = Path(path)
    file = read_csv_file(path)
    haystack = []
    for row in file.rows:
        if row.kind is RowKind.DATA:
            haystack.append("\x00".join((row.key, *row.fields[:LANGUAGE_COUNT])).casefold())
        else:
            haystack.append((row.raw or "").casefold())
    by_row: dict[int, list] = {}
    for diagnostic in file.diagnostics:
        # Recién leído, la fila i está en la línea i + 1 (ver LocalisationFile.lint).
        if diagnostic.line is not None:
            by_row.setdefault(diagnostic.line - 1, []).append(diagnostic)
    return LocalisationLoad(path, file, haystack, by_row, path.stat().st_size, time.perf_counter() - start)


@dataclass
class LocalisationFailure:
    path: Path
    message: str


def try_load_localisation(path: str | os.PathLike) -> LocalisationLoad | LocalisationFailure:
    try:
        return load_localisation(path)
    except OSError as exc:
        return LocalisationFailure(Path(path), exc.strerror or str(exc))


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
        self.kinds = [row.kind for row in self.rows]
        self.haystack = load.haystack if load else []
        self._severity = {}
        if load:
            for row, diagnostics in load.row_diagnostics.items():
                self._severity[row] = min((severity_name(d.severity) for d in diagnostics), key=SEVERITY_RANK.get)
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
            if kind == LANG:
                name = LANGUAGE_COLUMNS[column - 1]
                return tr("loc.col.lang_tooltip_shown" if name in DISPLAYED_LANGUAGES else "loc.col.lang_tooltip_hidden",
                          column=column + 1, name=name)
            return tr("loc.col.marker_tooltip") if kind == MARKER else (
                tr("loc.col.extras_tooltip") if kind == EXTRAS else tr("loc.col.key_tooltip"))
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


def _refilter(proxy: QSortFilterProxyModel, apply) -> None:
    """Cambia el filtro con la API de Qt 6.10+ si existe (``invalidateRowsFilter`` está obsoleta)."""
    if hasattr(proxy, "endFilterChange"):
        proxy.beginFilterChange()
        apply()
        proxy.endFilterChange(QSortFilterProxyModel.Direction.Rows)
    else:
        apply()
        proxy.invalidateRowsFilter()


class LocalisationFilterProxy(QSortFilterProxyModel):
    """Filtra por texto (clave o cualquier idioma) y oculta comentarios/líneas vacías si se pide."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Los datos no cambian (solo lectura): volver a filtrar en cada dataChanged sería trabajo perdido.
        self.setDynamicSortFilter(False)
        self._mask: list[bool] | None = None
        self._query = ""
        self._show_comments = False

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

    def compute_mask(self, kinds: list[RowKind], haystack: list[str]) -> list[bool] | None:
        query, data = self._query, RowKind.DATA
        if query:
            if self._show_comments:
                return [query in text for text in haystack]
            return [kind is data and query in text for kind, text in zip(kinds, haystack)]
        if self._show_comments:
            return None
        return [kind is data for kind in kinds]

    def prepare_reset(self, kinds: list[RowKind], haystack: list[str]) -> None:
        """Deja lista la máscara de los datos que van a entrar: el reinicio del modelo filtra una sola vez."""
        self._mask = self.compute_mask(kinds, haystack)

    def refresh(self) -> None:
        model: LocalisationModel = self.sourceModel()
        mask = self.compute_mask(model.kinds, model.haystack)
        _refilter(self, lambda: setattr(self, "_mask", mask))

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        mask = self._mask
        return mask is None or (source_row < len(mask) and mask[source_row])


class LocalisationEditor(QWidget):
    """Tabla + panel de diagnósticos. ``query_reset`` pide al buscador de la página que se vacíe."""

    query_reset = Signal()
    counts_changed = Signal(int, int)  # filas visibles, filas totales

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("localisationEditor")
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

        self.model = LocalisationModel(self)
        self.proxy = LocalisationFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.layoutChanged.connect(self._update_counts)
        self.proxy.rowsInserted.connect(self._update_counts)
        self.proxy.rowsRemoved.connect(self._update_counts)
        self.proxy.modelReset.connect(self._update_counts)
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
        self.proxy.refresh()
        self.retranslate()

    # --- API -----------------------------------------------------------------------------

    def current_load(self) -> LocalisationLoad | None:
        return self.model.load

    def set_load(self, load: LocalisationLoad | None) -> None:
        if load is not None:
            self.proxy.prepare_reset([row.kind for row in load.file.rows], load.haystack)
        self.model.set_load(load)
        rows = [DiagnosticRow.of(d) for d in (load.file.diagnostics if load else [])]
        self.diagnostics_model.set_rows(rows)
        self.table.scrollToTop()
        self._retranslate_diagnostics()
        self._update_counts()

    def set_query(self, text: str) -> None:
        self.proxy.set_query(text)

    def visible_rows(self) -> int:
        return self.proxy.rowCount()

    def total_rows(self) -> int:
        return self.model.rowCount()

    def data_rows(self) -> int:
        return sum(1 for kind in self.model.kinds if kind is RowKind.DATA)

    def select_line(self, line: int | None) -> bool:
        """Selecciona y centra la fila de la línea ``line``; vacía el filtro si la ocultaba."""
        if line is None:
            return False
        source = self.model.source_row_for_line(line)
        if source is None:
            return False
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
        current = self.diagnostics_model.row_at(self.diagnostics_view.currentIndex())
        if current is not None and current.line == line:
            return
        for position, row in enumerate(self.diagnostics_model.visible_rows()):
            if row.line == line:
                index = self.diagnostics_model.index(position, 0)
                self.diagnostics_view.setCurrentIndex(index)
                self.diagnostics_view.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtTop)
                return
        self.diagnostics_view.clearSelection()

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
        self.counts_changed.emit(self.visible_rows(), self.total_rows())

    def _retranslate_diagnostics(self) -> None:
        counts = self.diagnostics_model.counts()
        self.diagnostics_title.setText(tr("loc.diagnostics_title", count=format_number(sum(counts.values())),
                                          errors=format_number(counts["error"]),
                                          warnings=format_number(counts["warning"])))

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
