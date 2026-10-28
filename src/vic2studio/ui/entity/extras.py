"""Controles especiales del editor de entidades (wizard §13.5, §14.10, §14.11).

- ``RebelMatrix``: la matriz de rebeldes de un gobierno (14 tablas de ``rebel_types.txt`` en vanilla): una fila
  por tipo de rebelde con el gobierno de destino. Sale como pestaña en los esquemas con ``MappingTable``.
- ``EndDatePanel``: el editor mínimo de ``end_date`` de ``defines.lua`` (Guerra › Fechas de inicio). Cambia solo
  ese token (``core.schemas.bookmark.set_define_date``) y avisa si una fecha de inicio queda fuera.

Cada cambio es una transacción con ``Session.edit`` (I5).
"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.schema import MappingTable
from ...core.schema.companions import EditContext
from ...i18n import N_, tr, translator
from ..pickers import DateEdit
from ..widgets import mark_data


def mapping_table(schema) -> MappingTable | None:
    return next((c for c in schema.companions if isinstance(c, MappingTable)), None)


class RebelMatrix(QWidget):
    """Tipo de rebelde × gobierno de destino del gobierno enlazado (``bind(ref)``)."""

    status_requested = Signal(str, object)

    def __init__(self, session, companion: MappingTable, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.companion = companion
        self.ref = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.intro = QLabel()
        self.intro.setWordWrap(True)
        outer.addWidget(self.intro)
        self.table = mark_data(QTableWidget(0, 2))
        self.table.setObjectName("rebelMatrix")
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        outer.addWidget(self.table, 1)
        translator().languageChanged.connect(self._on_language_changed)
        self.retranslate()

    def _on_language_changed(self, code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.intro.setText(tr("entity.rebels.intro"))
        self.table.setHorizontalHeaderLabels([tr("entity.rebels.rebel"), tr("entity.rebels.target")])

    def _ctx(self):
        entities = self.session.entities
        return EditContext(entities.ws, entities.index, entities.loc)

    def bind(self, ref) -> None:
        self.ref = ref
        self.table.setRowCount(0)
        if ref is None or self.session.entities is None:
            return
        try:
            rows = self.companion.rows(self._ctx(), ref.ident)
        except (FileNotFoundError, OSError):
            rows = []
        governments = [summary.ref.ident for summary in self.session.entities.list(ref.kind)]
        read_only = self.session.is_read_only()
        for owner, target in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            item = QTableWidgetItem(owner)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item)
            combo = mark_data(QComboBox())
            combo.setObjectName(f"rebel_{owner}")
            combo.addItem("—", None)
            for name in governments:
                combo.addItem(name, name)
            with QSignalBlocker(combo):
                combo.setCurrentIndex(max(combo.findData(target), 0))
            combo.setEnabled(not read_only)
            combo.activated.connect(lambda _index, o=owner, c=combo: self._commit(o, c.currentData()))
            self.table.setCellWidget(row, 1, combo)

    def missing(self) -> list[str]:
        """Tipos de rebelde sin destino para el gobierno enlazado."""
        result = []
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 1)
            if combo is not None and combo.currentData() is None:
                result.append(self.table.item(row, 0).text())
        return result

    def _commit(self, owner: str, target: str | None) -> None:
        if self.ref is None or target is None:
            return
        with self.session.edit(N_("entity.rebels.undo"), merge_key=f"rebels.{self.ref.ident}.{owner}",
                               ident=self.ref.ident, rebel=owner):
            self.companion.set_target(self._ctx(), self.ref.ident, owner, target)
        self.status_requested.emit(N_("entity.rebels.done"), {"rebel": owner, "target": target})


class EndDatePanel(QWidget):
    """``end_date`` de ``defines.lua``: la fecha y «Aplicar»; dice qué fechas de inicio caen fuera."""

    status_requested = Signal(str, object)

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.label = QLabel()
        row.addWidget(self.label)
        self.date = DateEdit()
        self.date.setObjectName("endDate")
        self.date.value_committed.connect(self._apply)
        row.addWidget(self.date, 1)
        self.warning = QLabel()
        self.warning.setObjectName("endDateWarning")
        self.warning.setProperty("role", "caption")
        self.warning.setWordWrap(True)
        row.addWidget(self.warning, 2)
        self.extend_button = QPushButton()
        self.extend_button.setObjectName("endDateExtend")
        self.extend_button.clicked.connect(self.extend_to_bookmarks)
        row.addWidget(self.extend_button)
        translator().languageChanged.connect(self._on_language_changed)
        self.retranslate()

    def _on_language_changed(self, code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.label.setText(tr("entity.end_date"))
        self.extend_button.setText(tr("entity.end_date_extend"))
        self.refresh()

    def _ws(self):
        project = self.session.project
        return None if project is None else project.ws

    def end_date(self):
        from ...core.schemas.bookmark import define_date, read_defines

        ws = self._ws()
        return None if ws is None else define_date(read_defines(ws), "end_date")

    def late_bookmarks(self) -> list:
        """``(nombre, fecha)`` de las fechas de inicio posteriores a ``end_date``."""
        end = self.end_date()
        entities = self.session.entities
        if end is None or entities is None:
            return []
        late = []
        for summary in entities.list("bookmark"):
            date = entities.open(summary.ref).get("date", None)
            if date is not None and not isinstance(date, str) and date > end:
                late.append((summary.ref.ident, date))
        return late

    def refresh(self) -> None:
        end = self.end_date()
        self.date.set_value(end)
        self.date.setEnabled(end is not None and not self.session.is_read_only())
        late = self.late_bookmarks()
        self.warning.setText(tr("entity.end_date_late", names=", ".join(name for name, _ in late)) if late else "")
        self.extend_button.setVisible(bool(late))

    def _apply(self, date) -> bool:
        from ...core.schemas.bookmark import set_define_date

        if date is None or self._ws() is None or self.session.is_read_only():
            return False
        try:
            with self.session.edit(N_("entity.end_date_undo"), merge_key="defines.end_date", date=str(date)):
                set_define_date(self._ws(), "end_date", date)
        except (KeyError, ValueError, FileNotFoundError):
            self.status_requested.emit(N_("entity.end_date_failed"), {})
            return False
        self.refresh()
        self.status_requested.emit(N_("entity.end_date_done"), {"date": str(date)})
        return True

    def extend_to_bookmarks(self) -> bool:
        """Amplía ``end_date`` a la última fecha de inicio (el arreglo de §14.10)."""
        late = self.late_bookmarks()
        if not late:
            return False
        return self._apply(max(date for _, date in late))
