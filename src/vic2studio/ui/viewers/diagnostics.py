"""Tabla de diagnósticos común (visor Clausewitz, lint de CSV y validación del mod).

El modelo guarda los diagnósticos originales y pide el mensaje en el idioma
actual al pintarlo (``message(lang)``), así que un cambio de idioma solo invalida
la caché de mensajes. El filtro por gravedad y texto vive en el propio modelo:
recalcular una lista en Python es mucho más rápido que filtrar fila a fila.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyledItemDelegate, QTreeView, QWidget

from ...i18n import N_, tr
from .. import theme
from .common import SEVERITY_COLOR, core_language, severity_icon, severity_label, severity_name

COL_SEVERITY, COL_FILE, COL_LINE, COL_MESSAGE = "severity", "file", "line", "message"
HEADER_KEYS = {
    COL_SEVERITY: N_("diag.col.severity"), COL_FILE: N_("diag.col.file"),
    COL_LINE: N_("diag.col.line"), COL_MESSAGE: N_("diag.col.message"),
}
ROW_ROLE = Qt.ItemDataRole.UserRole + 1


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
        if self.line is None:
            return ""
        return f"{self.line}:{self.column}" if self.column else str(self.line)


class DiagnosticsModel(QAbstractTableModel):
    def __init__(self, columns: tuple[str, ...] = (COL_SEVERITY, COL_LINE, COL_MESSAGE), parent=None):
        super().__init__(parent)
        self.columns = columns
        self._all: list[DiagnosticRow] = []
        self._rows: list[DiagnosticRow] = []
        self._severities: frozenset[str] | None = None
        self._needle = ""
        self._messages: dict[int, str] = {}
        self._lang = core_language()
        self._mono = theme.font("mono")

    # --- datos ---------------------------------------------------------------------------

    def set_rows(self, rows: list[DiagnosticRow]) -> None:
        self.beginResetModel()
        self._all = list(rows)
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
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole \
                and 0 <= section < len(self.columns):
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
    """Las rutas se recortan por el centro (se ve carpeta y archivo); los mensajes, por el final."""

    def __init__(self, middle: set[int], parent=None):
        super().__init__(parent)
        self._middle = middle

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        option.textElideMode = (Qt.TextElideMode.ElideMiddle if index.column() in self._middle
                                else Qt.TextElideMode.ElideRight)


class DiagnosticsView(QTreeView):
    """Lista plana con cabeceras; ``diagnostic_activated`` con doble clic o Intro."""

    diagnostic_activated = Signal(object)  # DiagnosticRow

    def __init__(self, model: DiagnosticsModel, parent: QWidget | None = None):
        super().__init__(parent)
        self.setModel(model)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.setItemsExpandable(False)
        self.setAllColumnsShowFocus(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setIconSize(QSize(16, 16))
        self.setItemDelegate(_ElideDelegate({i for i, c in enumerate(model.columns) if c == COL_FILE}, self))
        header = self.header()
        header.setStretchLastSection(True)
        header.setSectionsMovable(False)
        for section, column in enumerate(model.columns):
            if column == COL_SEVERITY:
                header.setSectionResizeMode(section, QHeaderView.ResizeMode.Interactive)
                header.resizeSection(section, 92)
            elif column == COL_LINE:
                header.setSectionResizeMode(section, QHeaderView.ResizeMode.Interactive)
                header.resizeSection(section, 58)
            elif column == COL_FILE:
                header.setSectionResizeMode(section, QHeaderView.ResizeMode.Interactive)
                header.resizeSection(section, 180)
        self.activated.connect(self._on_activated)

    def diagnostics_model(self) -> DiagnosticsModel:
        return self.model()

    def _on_activated(self, index: QModelIndex) -> None:
        row = self.diagnostics_model().row_at(index)
        if row is not None:
            self.diagnostic_activated.emit(row)
