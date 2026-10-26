"""Tabla de diagnósticos común (visor Clausewitz, lint de CSV y validación del mod).

El modelo guarda los diagnósticos originales y pide el mensaje en el idioma
actual al pintarlo (``message(lang)``), así que un cambio de idioma solo invalida
la caché de mensajes. El filtro por gravedad y texto vive en el propio modelo:
recalcular una lista en Python es mucho más rápido que filtrar fila a fila.

La vista es una tabla y no un árbol: QTreeView pedía al modelo (en Python) cada
fila al maquetar, y con decenas de miles de diagnósticos paraba la interfaz. Las
columnas se ajustan al idioma, a las filas y al ancho disponible sin barra horizontal.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyledItemDelegate, QTableView, QWidget

from ...i18n import N_, tr
from .. import theme
from .common import SEVERITY_COLOR, SEVERITY_RANK, core_language, severity_icon, severity_label, severity_name

COL_SEVERITY, COL_FILE, COL_LINE, COL_MESSAGE = "severity", "file", "line", "message"
HEADER_KEYS = {
    COL_SEVERITY: N_("diag.col.severity"), COL_FILE: N_("diag.col.file"),
    COL_LINE: N_("diag.col.line"), COL_MESSAGE: N_("diag.col.message"),
}
ROW_ROLE = Qt.ItemDataRole.UserRole + 1
HEADER_PADDING = 22  # relleno y borde de una sección de la cabecera (hoja de estilo)
CELL_PADDING = 14    # márgenes del texto de una celda
FILE_WIDTH = 180     # ancho de la columna Archivo cuando sobra sitio
FILE_MIN_WIDTH = 56   # ni aunque falte sitio (entonces sí aparece la barra horizontal); con el panel de
                      # validación al mínimo (323 px) deja al mensaje sus 100 px sin barra
FILE_SHARE = 1 / 3    # Archivo no pasa de esta parte de lo que dejan Gravedad y Línea: el resto es del mensaje
MESSAGE_MIN_WIDTH = 120  # Archivo cede ancho antes de dejar el mensaje en menos


def column_width(view: QAbstractItemView, title: str, sample: str, font: QFont | None = None, extra: int = 0) -> int:
    """Ancho de columna en el que caben la cabecera ``title`` (en negrita, como la pinta la
    hoja de estilo) y una celda con ``sample`` (más ``extra`` píxeles, p. ej. de un icono)."""
    bold = QFont(view.font())
    bold.setWeight(QFont.Weight.DemiBold)
    header = QFontMetrics(bold).horizontalAdvance(title) + HEADER_PADDING
    cell = QFontMetrics(font or view.font()).horizontalAdvance(sample) + CELL_PADDING + extra
    return max(header, cell)


@dataclass(frozen=True)
class DiagnosticRow:
    """Un diagnóstico para mostrar; ``source`` es cualquier objeto con ``message(lang)``."""

    severity: str
    line: int | None
    column: int | None
    source: object
    code: str = ""
    path: Path | None = None
    relative: str = ""

    @classmethod
    def of(cls, diagnostic, path: Path | None = None, relative: str = "") -> DiagnosticRow:
        return cls(severity_name(diagnostic.severity), diagnostic.line, diagnostic.column, diagnostic,
                   getattr(diagnostic, "code", ""), path, relative)

    def message(self, lang: str) -> str:
        return self.source.message(lang)

    def location(self) -> str:
        return _location(self.line, self.column)


def _location(line: int | None, column: int | None) -> str:
    if line is None:
        return ""
    return f"{line}:{column}" if column else str(line)


class DiagnosticsModel(QAbstractTableModel):
    def __init__(self, columns: tuple[str, ...] = (COL_SEVERITY, COL_LINE, COL_MESSAGE), parent=None):
        super().__init__(parent)
        self.columns = columns
        self._all: list[DiagnosticRow] = []
        self._rows: list[DiagnosticRow] = []
        self._widest_location = ""
        self._severities: frozenset[str] | None = None
        self._needle = ""
        self._messages: dict[int, str] = {}
        self._lang = core_language()
        self._mono = theme.font("mono")

    # --- datos ---------------------------------------------------------------------------

    def set_rows(self, rows: list[DiagnosticRow]) -> None:
        self.beginResetModel()
        self._all = list(rows)
        # Tantas cifras como la línea y la columna más largas: con la fuente monoespaciada, lo más ancho.
        self._widest_location = _location(max((r.line for r in self._all if r.line is not None), default=None),
                                          max((r.column or 0 for r in self._all), default=0))
        self._messages.clear()
        self._rows = self._filtered()
        self.endResetModel()

    def set_filter(self, severities: frozenset[str] | None = None, text: str = "") -> None:
        """Muestra solo esas gravedades (``None`` = todas) y filas cuyo mensaje o archivo contenga ``text``."""
        needle = text.strip().casefold()
        if severities == self._severities and needle == self._needle:
            return
        self.beginResetModel()
        self._severities, self._needle = severities, needle
        self._rows = self._filtered()
        self.endResetModel()

    def _filtered(self) -> list[DiagnosticRow]:
        rows = self._all
        if self._severities is not None:
            rows = [r for r in rows if r.severity in self._severities]
        if self._needle:
            needle = self._needle
            rows = [r for r in rows if needle in self._message(r).casefold() or needle in r.relative.casefold()]
        return rows

    def all_rows(self) -> list[DiagnosticRow]:
        return list(self._all)

    def widest_location(self) -> str:
        """Una «línea:columna» tan ancha como la más ancha de todas las filas (filtradas o no)."""
        return self._widest_location

    def visible_rows(self) -> list[DiagnosticRow]:
        return list(self._rows)

    def row_at(self, index: QModelIndex) -> DiagnosticRow | None:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        return self._rows[index.row()]

    def counts(self) -> dict[str, int]:
        counts = {"error": 0, "warning": 0, "info": 0}
        for row in self._all:
            counts[row.severity] = counts.get(row.severity, 0) + 1
        return counts

    def retranslate(self) -> None:
        self._lang = core_language()
        self._messages.clear()
        if self._needle:
            self.beginResetModel()
            self._rows = self._filtered()
            self.endResetModel()
        elif self._rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, len(self.columns) - 1))
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self.columns) - 1)

    def _message(self, row: DiagnosticRow) -> str:
        key = id(row)
        message = self._messages.get(key)
        if message is None:
            message = self._messages[key] = row.message(self._lang)
        return message

    # --- QAbstractTableModel -------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        # También como ayuda emergente: con el panel al mínimo, la cabecera de Archivo se recorta.
        roles = (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole)
        if orientation == Qt.Orientation.Horizontal and role in roles and 0 <= section < len(self.columns):
            return tr(HEADER_KEYS[self.columns[section]])
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        row = self.row_at(index)
        if row is None:
            return None
        column = self.columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            if column == COL_SEVERITY:
                return severity_label(row.severity)
            if column == COL_FILE:
                return row.relative
            if column == COL_LINE:
                return row.location()
            return self._message(row)
        if role == Qt.ItemDataRole.ToolTipRole:
            if column == COL_MESSAGE:
                return self._message(row)
            if column == COL_FILE:
                return row.relative
            return None
        if role == Qt.ItemDataRole.DecorationRole and column == COL_SEVERITY:
            return severity_icon(row.severity)
        if role == Qt.ItemDataRole.ForegroundRole and column == COL_SEVERITY:
            return theme.color(SEVERITY_COLOR[row.severity])
        if role == Qt.ItemDataRole.FontRole and column in (COL_LINE, COL_FILE):
            return self._mono
        if role == Qt.ItemDataRole.TextAlignmentRole and column == COL_LINE:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == ROW_ROLE:
            return row
        return None


class _ElideDelegate(QStyledItemDelegate):
    """Las rutas se recortan por la izquierda (se ve el nombre del archivo); los mensajes, por el final."""

    def __init__(self, left: set[int], parent=None):
        super().__init__(parent)
        self._left = left

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        option.textElideMode = (Qt.TextElideMode.ElideLeft if index.column() in self._left
                                else Qt.TextElideMode.ElideRight)


class DiagnosticsView(QTableView):
    """Lista plana con cabeceras; ``diagnostic_activated`` con doble clic o Intro.

    Gravedad y Línea miden lo que su cabecera traducida y su contenido; Archivo cede
    ancho cuando falta, para que el mensaje (la última columna, que se queda con lo que
    sobra) se siga leyendo sin barra horizontal; su ayuda emergente lo muestra entero.
    Tab pasa al control siguiente, no a la celda siguiente.
    """

    diagnostic_activated = Signal(object)  # DiagnosticRow

    def __init__(self, model: DiagnosticsModel, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "diagnostics")  # hoja de estilo: relleno y fila bajo el ratón
        self.setModel(model)
        self.setTabKeyNavigation(False)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setCornerButtonEnabled(False)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setIconSize(QSize(16, 16))
        self.setItemDelegate(_ElideDelegate({i for i, c in enumerate(model.columns) if c == COL_FILE}, self))
        rows = self.verticalHeader()
        rows.setVisible(False)
        rows.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        rows.setDefaultSectionSize(max(self.fontMetrics().height(), 16) + 8)
        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionsMovable(False)
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.installEventFilter(self)  # su ancho es el de la zona visible: ver ``_fit_file``
        self._fitted: dict[int, int] = {}
        model.headerDataChanged.connect(self._fit_columns)
        model.modelReset.connect(self._fit_columns)
        self._fit_columns()
        self.activated.connect(self._on_activated)

    def diagnostics_model(self) -> DiagnosticsModel:
        return self.model()

    def _fit_columns(self, *args) -> None:
        """Ajusta Gravedad y Línea a su cabecera y a su contenido, y después Archivo.

        Solo las cambia si cambia lo que miden (el idioma o las filas): filtrar no deshace un ajuste a mano.
        """
        model = self.diagnostics_model()
        widths = {}
        for section, column in enumerate(model.columns):
            title = tr(HEADER_KEYS[column])
            if column == COL_SEVERITY:
                widest = max((severity_label(s) for s in SEVERITY_RANK), key=self.fontMetrics().horizontalAdvance)
                widths[section] = column_width(self, title, widest, extra=self.iconSize().width() + 6)
            elif column == COL_LINE:
                widths[section] = column_width(self, title, model.widest_location(), theme.font("mono"))
        if widths == self._fitted:
            return
        self._fitted = widths
        header = self.horizontalHeader()
        for section, width in widths.items():
            header.resizeSection(section, width)
        self._fit_file()

    def _fit_file(self) -> None:
        """Archivo mide ``FILE_WIDTH`` si no pasa de ``FILE_SHARE`` del ancho que dejan Gravedad y Línea;
        si no, esa parte (y nunca menos de ``FILE_MIN_WIDTH``). El mensaje se queda con el resto: en una
        tabla estrecha es lo que más hay que leer, y la ruta se recorta por la izquierda."""
        columns = self.diagnostics_model().columns
        if COL_FILE not in columns:
            return
        header = self.horizontalHeader()
        section = columns.index(COL_FILE)
        others = sum(header.sectionSize(i) for i in range(len(columns) - 1) if i != section)
        free = header.width() - others
        width = min(FILE_WIDTH, round(free * FILE_SHARE), free - MESSAGE_MIN_WIDTH)
        header.resizeSection(section, max(FILE_MIN_WIDTH, width))

    def eventFilter(self, watched, event) -> bool:
        # La cabecera cambia de ancho con la vista y cuando aparece o desaparece la barra vertical.
        if watched is self.horizontalHeader() and event.type() == QEvent.Type.Resize:
            self._fit_file()
        return super().eventFilter(watched, event)

    def _on_activated(self, index: QModelIndex) -> None:
        row = self.diagnostics_model().row_at(index)
        if row is not None:
            self.diagnostic_activated.emit(row)
