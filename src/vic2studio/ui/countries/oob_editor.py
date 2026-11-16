"""Editor de órdenes de batalla (pestaña «Ejército» de la ficha nacional, wizard §14.2).

Un árbol con los ejércitos y flotas del país (ubicación y unidades: regimientos con tipo y provincia de origen,
barcos con tipo) y un formulario para añadir: ejército o flota con su ubicación («Elegir en el mapa»), y unidades
en el ejército elegido. Cada gesto es una transacción (``undo.oob_edit``); si el país no tenía OOB, el primer
cambio crea ``history/units/<TAG>_oob.txt`` y pone ``oob = "…"`` en su historia.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from ...core.domain import oob as core_oob
from ...i18n import N_, tr, translator
from ..pickers.province_picker import ANY, LAND, ProvincePicker
from ..widgets import make_icon, mark_data
from . import countries_facade

ROLE_POSITION = Qt.ItemDataRole.UserRole
ROLE_UNIT = Qt.ItemDataRole.UserRole + 1
KIND_LABELS = {"army": N_("countries.oob.army"), "navy": N_("countries.oob.navy"),
               "regiment": N_("countries.oob.regiment"), "ship": N_("countries.oob.ship")}


def unit_types(session, naval: bool) -> list[str]:
    from ...core.index.model import KIND_UNIT_TYPE

    index = getattr(session, "index", None)
    if index is None:
        return []
    wanted = "naval" if naval else "land"
    return sorted(s.name for s in index.symbols(KIND_UNIT_TYPE) if (s.attrs or {}).get("type") == wanted)


class OobEditor(QWidget):
    status_requested = Signal(str, object)

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.tag: str | None = None
        self.armies: list[core_oob.ArmyInfo] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.file_label = QLabel()
        self.file_label.setObjectName("oobFile")
        layout.addWidget(self.file_label)
        self.tree = mark_data(QTreeWidget())
        self.tree.setObjectName("oobTree")
        self.tree.setColumnCount(3)
        layout.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.remove_button = QPushButton()
        self.remove_button.setObjectName("oobRemove")
        self.remove_button.setIcon(make_icon("trash", "gold_light"))
        self.remove_button.clicked.connect(self.remove_selected)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        layout.addLayout(row)
        form = QFormLayout()
        self.army_kind = QComboBox()
        self.army_kind.setObjectName("oobArmyKind")
        self.army_kind.addItem("", "army")
        self.army_kind.addItem("", "navy")
        self.army_name = QLineEdit()
        self.army_name.setObjectName("oobArmyName")
        self.army_location = ProvincePicker(session, allow=ANY)
        self.army_location.setObjectName("oobArmyLocation")
        self.add_army_button = QPushButton()
        self.add_army_button.setObjectName("oobAddArmy")
        self.add_army_button.setIcon(make_icon("plus", "gold_light"))
        self.add_army_button.clicked.connect(self.add_army_from_form)
        self.labels = [QLabel() for _ in range(6)]
        form.addRow(self.labels[0], self.army_kind)
        form.addRow(self.labels[1], self.army_name)
        form.addRow(self.labels[2], self.army_location)
        form.addRow("", self.add_army_button)
        self.unit_name = QLineEdit()
        self.unit_name.setObjectName("oobUnitName")
        self.unit_type = QComboBox()
        self.unit_type.setObjectName("oobUnitType")
        self.unit_home = ProvincePicker(session, allow=LAND)
        self.unit_home.setObjectName("oobUnitHome")
        self.add_unit_button = QPushButton()
        self.add_unit_button.setObjectName("oobAddUnit")
        self.add_unit_button.setIcon(make_icon("plus", "gold_light"))
        self.add_unit_button.clicked.connect(self.add_unit_from_form)
        form.addRow(self.labels[3], self.unit_name)
        form.addRow(self.labels[4], self.unit_type)
        form.addRow(self.labels[5], self.unit_home)
        form.addRow("", self.add_unit_button)
        layout.addLayout(form)
        self.tree.currentItemChanged.connect(self._on_current)
        translator().languageChanged.connect(self._on_language)
        self.retranslate()

    def _on_language(self, code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.tree.setHeaderLabels([tr(N_("countries.oob.col.name")), tr(N_("countries.oob.col.type")),
                                   tr(N_("countries.oob.col.place"))])
        self.army_kind.setItemText(0, tr(KIND_LABELS["army"]))
        self.army_kind.setItemText(1, tr(KIND_LABELS["navy"]))
        for label, key in zip(self.labels, (N_("countries.oob.f.kind"), N_("countries.oob.f.name"),
                                            N_("countries.oob.f.location"), N_("countries.oob.f.unit_name"),
                                            N_("countries.oob.f.unit_type"), N_("countries.oob.f.home"))):
            label.setText(tr(key))
        self.add_army_button.setText(tr(N_("countries.oob.add_army")))
        self.add_unit_button.setText(tr(N_("countries.oob.add_unit")))
        self.remove_button.setText(tr(N_("countries.oob.remove")))
        self.reload()

    # --- datos ------------------------------------------------------------------------------------

    def _countries(self):
        return countries_facade(self.session)

    def _date(self):
        return getattr(self.session, "working_date", None)

    def rel(self):
        if self.tag is None:
            return None
        return core_oob.oob_rel_of(self._countries(), self.tag, self._date())

    def bind(self, tag: str | None) -> None:
        self.tag = tag
        self.reload()

    def reload(self, *args) -> None:
        self.tree.clear()
        self.armies = []
        rel = self.rel()
        if rel is None or self.session.project is None:
            self.file_label.setText("")
            return
        try:
            handle = self.session.project.ws.open(rel)
            self.armies = [] if handle.deleted else core_oob.read_oob(handle.model.document)
            exists = not handle.deleted
        except (FileNotFoundError, OSError):
            exists = False
        self.file_label.setText(tr(N_("countries.oob.file") if exists else N_("countries.oob.no_file"),
                                   file=str(rel)))
        for army in self.armies:
            item = QTreeWidgetItem([army.name, tr(KIND_LABELS[army.kind]), self._place(army.location)])
            item.setData(0, ROLE_POSITION, army.position)
            item.setData(0, ROLE_UNIT, None)
            for unit in army.units:
                child = QTreeWidgetItem([unit.name, unit.type, self._place(unit.home)])
                child.setData(0, ROLE_POSITION, army.position)
                child.setData(0, ROLE_UNIT, unit.position)
                item.addChild(child)
            self.tree.addTopLevelItem(item)
            item.setExpanded(True)
        self._on_current()

    def _place(self, pid) -> str:
        if pid is None:
            return ""
        name = self.session.map.province_name(pid) if hasattr(self.session, "map") else None
        return f"{pid} - {name}" if name else str(pid)

    def selected_army(self):
        item = self.tree.currentItem()
        if item is None:
            return None
        position = item.data(0, ROLE_POSITION)
        return next((a for a in self.armies if a.position == position), None)

    def _on_current(self, *args) -> None:
        army = self.selected_army()
        naval = army is not None and army.kind == "navy"
        current = self.unit_type.currentData()
        self.unit_type.clear()
        for name in unit_types(self.session, naval):
            self.unit_type.addItem(name, name)
        if current:
            index = self.unit_type.findData(current)
            if index >= 0:
                self.unit_type.setCurrentIndex(index)
        self.unit_home.setEnabled(not naval)
        self.add_unit_button.setEnabled(army is not None)

    # --- edición ----------------------------------------------------------------------------------

    def _edit(self, action) -> bool:
        if self.tag is None or self.session.project is None:
            return False
        countries = self._countries()
        try:
            with self.session.edit(core_oob.UNDO_OOB_EDIT, tag=self.tag):
                rel = core_oob.ensure_oob(self.session.project.ws, countries, self.tag, self._date())
                action(rel)
        except (core_oob.OobError, ValueError, KeyError) as exc:
            self.status_requested.emit(N_("countries.oob.failed"), {"error": str(exc)})
            return False
        self.reload()
        self.status_requested.emit(N_("countries.oob.done"), {"tag": self.tag})
        return True

    def add_army(self, kind: str, name: str, location: int) -> bool:
        return self._edit(lambda rel: core_oob.add_army(self.session.project.ws, rel, kind, name, location))

    def add_army_from_form(self) -> bool:
        name = self.army_name.text().strip()
        location = self.army_location.value()
        if not name or location is None:
            self.status_requested.emit(N_("countries.oob.incomplete"), {})
            return False
        return self.add_army(self.army_kind.currentData(), name, int(location))

    def add_unit(self, position: int, name: str, unit_type: str, home: int | None) -> bool:
        return self._edit(lambda rel: core_oob.add_unit(self.session.project.ws, rel, position, name, unit_type,
                                                        home))

    def add_unit_from_form(self) -> bool:
        army = self.selected_army()
        name = self.unit_name.text().strip()
        unit_type = self.unit_type.currentData()
        if army is None or not name or not unit_type:
            self.status_requested.emit(N_("countries.oob.incomplete"), {})
            return False
        home = self.unit_home.value() if army.kind == "army" else None
        if army.kind == "army" and home is None:
            home = army.location
        return self.add_unit(army.position, name, unit_type, home)

    def remove_selected(self) -> bool:
        item = self.tree.currentItem()
        if item is None:
            return False
        position, unit = item.data(0, ROLE_POSITION), item.data(0, ROLE_UNIT)
        return self._edit(lambda rel: core_oob.remove(self.session.project.ws, rel, position, unit))
