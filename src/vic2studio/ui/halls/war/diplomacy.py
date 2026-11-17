"""Sección «Diplomacia de inicio» de la sala Guerra (wizard §14.2 «Diplomacia», §14.12). Iteración 6.

La tabla de todas las relaciones de ``history/diplomacy`` (alianzas, vasallos, subestados, uniones y garantías),
con filtro por tipo y por TAG; las vigentes en la fecha de trabajo van marcadas. El formulario añade una
relación al final del archivo de su tipo y «Quitar» borra la elegida; los dos son un paso de deshacer y el resto
del archivo queda byte a byte (``core.domain.war.put_relation`` / ``drop_relation``).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QWidget,
)

from ....core.domain import war as core_war
from ....i18n import N_, tr
from ...countries import domain_context
from ...pages.base import BasePage
from ...pickers.tag_picker import TagPicker
from ...session import replace_paths_touch
from ...widgets import make_icon, mark_data
from .wars import war_error_text

TYPE_LABELS = {"alliance": N_("war.diplomacy.alliance"), "vassal": N_("war.diplomacy.vassal"),
               "substate": N_("war.diplomacy.substate"), "union": N_("war.diplomacy.union"),
               "guarantee": N_("war.diplomacy.guarantee")}
COLUMNS = (N_("war.diplomacy.col.type"), N_("war.diplomacy.col.first"), N_("war.diplomacy.col.second"),
           N_("war.diplomacy.col.start"), N_("war.diplomacy.col.end"), N_("war.diplomacy.col.file"))
ROLE_RELATION = Qt.ItemDataRole.UserRole


def _active(relation: core_war.Relation, date: str | None) -> bool:
    if date is None or not relation.start_date:
        return False
    start = core_war._date_key(relation.start_date)
    end = core_war._date_key(relation.end_date) if relation.end_date else (99999, 0, 0)
    return start <= core_war._date_key(date) < end


class DiplomacyPage(BasePage):
    key = "diplomacy"
    title_key = N_("section.war.diplomacy")
    subtitle_key = N_("war.diplomacy.subtitle")
    icon_name = "handshake"

    def __init__(self, session, parent: QWidget | None = None):
        self.session = session
        self.relations: list[core_war.Relation] = []
        super().__init__(parent)
        session.projectOpened.connect(self.reload)
        session.projectClosed.connect(self.reload)
        session.documentsChanged.connect(self._on_documents)
        session.replacePathsChanged.connect(self._on_replace_paths)
        session.workingDateChanged.connect(self.reload)
        self.reload()

    def build(self) -> None:
        filters = QHBoxLayout()
        self.type_filter = QComboBox()
        self.type_filter.setObjectName("diplomacyTypeFilter")
        self.type_filter.addItem("", None)
        for kind in core_war.RELATION_TYPES:
            self.type_filter.addItem("", kind)
        self.type_filter.currentIndexChanged.connect(lambda _i: self._fill())
        self.tag_filter = QLineEdit()
        self.tag_filter.setObjectName("diplomacyTagFilter")
        self.tag_filter.setMaxLength(3)
        self.tag_filter.textChanged.connect(lambda _t: self._fill())
        self.count_label = QLabel()
        self.count_label.setObjectName("diplomacyCount")
        filters.addWidget(self.type_filter)
        filters.addWidget(self.tag_filter)
        filters.addWidget(self.count_label, 1)
        self.body.addLayout(filters)
        self.table = mark_data(QTableWidget(0, len(COLUMNS)))
        self.table.setObjectName("diplomacyTable")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.body.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.remove_button = QPushButton()
        self.remove_button.setObjectName("diplomacyRemove")
        self.remove_button.setIcon(make_icon("trash", "gold_light"))
        self.remove_button.clicked.connect(self.remove_selected)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        self.body.addLayout(row)
        self.add_title = QLabel()
        self.body.addWidget(self.add_title)
        form = QFormLayout()
        self.form_labels = [QLabel() for _ in range(5)]
        self.kind_combo = QComboBox()
        self.kind_combo.setObjectName("diplomacyKind")
        for kind in core_war.RELATION_TYPES:
            self.kind_combo.addItem("", kind)
        self.first_picker = TagPicker(self.session)
        self.first_picker.setObjectName("diplomacyFirst")
        self.second_picker = TagPicker(self.session)
        self.second_picker.setObjectName("diplomacySecond")
        self.start_edit = QLineEdit()
        self.start_edit.setObjectName("diplomacyStart")
        self.end_edit = QLineEdit()
        self.end_edit.setObjectName("diplomacyEnd")
        for label, widget in zip(self.form_labels, (self.kind_combo, self.first_picker, self.second_picker,
                                                     self.start_edit, self.end_edit)):
            form.addRow(label, widget)
        self.body.addLayout(form)
        buttons = QHBoxLayout()
        self.add_button = QPushButton()
        self.add_button.setObjectName("diplomacyAdd")
        self.add_button.setIcon(make_icon("plus", "gold_light"))
        self.add_button.clicked.connect(self.add_from_form)
        self.status_label = QLabel()
        self.status_label.setObjectName("diplomacyStatus")
        self.status_label.setWordWrap(True)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.status_label, 1)
        self.body.addLayout(buttons)

    def retranslate(self) -> None:
        super().retranslate()
        self.type_filter.setItemText(0, tr(N_("war.diplomacy.all_types")))
        for index, kind in enumerate(core_war.RELATION_TYPES, start=1):
            self.type_filter.setItemText(index, tr(TYPE_LABELS[kind]))
        for index, kind in enumerate(core_war.RELATION_TYPES):
            self.kind_combo.setItemText(index, tr(TYPE_LABELS[kind]))
        self.tag_filter.setPlaceholderText(tr(N_("war.diplomacy.tag_filter")))
        self.table.setHorizontalHeaderLabels([tr(key) for key in COLUMNS])
        self.remove_button.setText(tr(N_("war.diplomacy.remove")))
        self.add_title.setText(tr(N_("war.diplomacy.add_title")))
        for label, key in zip(self.form_labels, (N_("war.diplomacy.col.type"), N_("war.diplomacy.col.first"),
                                                 N_("war.diplomacy.col.second"), N_("war.diplomacy.col.start"),
                                                 N_("war.diplomacy.col.end"))):
            label.setText(tr(key))
        self.end_edit.setPlaceholderText(tr(N_("war.diplomacy.end_optional")))
        self.add_button.setText(tr(N_("war.diplomacy.add")))
        self._fill()

    # --- datos ------------------------------------------------------------------------------------

    def _on_documents(self, rels) -> None:
        if any(str(rel).lower().startswith(core_war.DIPLOMACY_FOLDER + "/") for rel in rels or ()):
            self.reload()

    def _on_replace_paths(self, folders) -> None:
        """Otras ``replace_path``: las relaciones del juego dejan de contar, o vuelven, sin que se nombre ningún
        archivo de ``history/diplomacy``."""
        if replace_paths_touch(folders, core_war.DIPLOMACY_FOLDER):
            self.reload()

    def reload(self, *args) -> None:
        context = domain_context(self.session)
        self.relations = core_war.relations(context) if context is not None else []
        if context is not None and not self.start_edit.text():
            self.start_edit.setText(str(self.session.working_date))
        self.add_button.setEnabled(context is not None)
        self._fill()

    def visible(self) -> list[core_war.Relation]:
        kind = self.type_filter.currentData()
        tag = self.tag_filter.text().strip().upper()
        return [r for r in self.relations if (kind is None or r.type == kind)
                and (not tag or tag in (r.first.upper(), r.second.upper()))]

    def _fill(self) -> None:
        rows = self.visible()
        date = str(self.session.working_date) if self.session.project is not None else None
        self.table.setRowCount(len(rows))
        active = 0
        for index, relation in enumerate(rows):
            on = _active(relation, date)
            active += on
            values = (("● " if on else "○ ") + tr(TYPE_LABELS.get(relation.type, relation.type)), relation.first,
                      relation.second, relation.start_date or "", relation.end_date or "",
                      f"{relation.rel}:{relation.line}" if relation.line else str(relation.rel))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(ROLE_RELATION, relation)
                self.table.setItem(index, column, item)
        self.count_label.setText(tr(N_("war.diplomacy.count"), count=len(rows), active=active, date=date or "—"))

    def selected(self) -> core_war.Relation | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.data(ROLE_RELATION) if item is not None else None

    # --- edición ----------------------------------------------------------------------------------

    def add_relation(self, kind: str, first: str, second: str, start: str, end: str | None = None) -> bool:
        context = domain_context(self.session)
        if context is None:
            return False
        if not core_war.is_date(start):
            self.status_label.setText(tr(N_("war.error.no_date")))
            return False
        try:
            with self.session.edit(core_war.UNDO_RELATION_ADD, kind=kind, first=first, second=second):
                core_war.put_relation(context, kind, first, second, start, end or None)
        except core_war.WarError as exc:
            self.status_label.setText(war_error_text(exc))
            return False
        self.reload()
        self.status_label.setText(tr(N_("war.diplomacy.added"), first=first, second=second))
        return True

    def add_from_form(self) -> bool:
        first, second = self.first_picker.value(), self.second_picker.value()
        if not first or not second:
            self.status_label.setText(tr(N_("war.diplomacy.incomplete")))
            return False
        return self.add_relation(self.kind_combo.currentData(), first, second, self.start_edit.text().strip(),
                                 self.end_edit.text().strip() or None)

    def remove_selected(self) -> bool:
        relation = self.selected()
        context = domain_context(self.session)
        if relation is None or context is None:
            return False
        try:
            with self.session.edit(core_war.UNDO_RELATION_REMOVE, kind=relation.type, first=relation.first,
                                   second=relation.second):
                core_war.drop_relation(context, relation)
        except core_war.WarError as exc:
            self.status_label.setText(war_error_text(exc))
            self.reload()
            return False
        self.reload()
        self.status_label.setText(tr(N_("war.diplomacy.removed"), first=relation.first, second=relation.second))
        return True

    def focus_field(self, ref, field=()) -> bool:
        """Filtra por el archivo de ``ref`` (``diplomacy:<archivo>``) y elige su primera fila."""
        ident = str(getattr(ref, "ident", ref)).lower()
        self.type_filter.setCurrentIndex(0)
        self.tag_filter.clear()
        for row in range(self.table.rowCount()):
            relation = self.table.item(row, 0).data(ROLE_RELATION)
            if relation.rel is not None and relation.rel.name.lower().removesuffix(".txt") == ident:
                self.table.selectRow(row)
                return True
        return False
