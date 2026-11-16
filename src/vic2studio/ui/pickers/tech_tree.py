"""Tecnologías de un país (wizard §14.2, paso 6 del asistente y pestaña «Tecnologías» de la ficha).

``TechChecklist`` enseña las tecnologías del índice agrupadas por carpeta (``army_tech``, ``commerce_tech``…) con
una casilla cada una. ``TechTreeDialog`` la envuelve con plantillas: «civilizado» (las de año ≤ al de inicio),
«no civilizado» (ninguna) y «como <país>» (las que conoce ese país en la fecha de inicio).
"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ...i18n import N_, tr, translator
from ..widgets import mark_data
from .tag_picker import TagPicker

ROLE_NAME = Qt.ItemDataRole.UserRole
TEMPLATE_CIVILIZED = "civilized"
TEMPLATE_UNCIVILIZED = "uncivilized"
TEMPLATE_LIKE = "like"
TEMPLATES = {TEMPLATE_CIVILIZED: N_("pickers.tech.template.civilized"),
             TEMPLATE_UNCIVILIZED: N_("pickers.tech.template.uncivilized"),
             TEMPLATE_LIKE: N_("pickers.tech.template.like")}


def technologies(index) -> dict[str, list[tuple[str, int | None]]]:
    """Carpeta → [(tecnología, año)], ordenadas por año y nombre."""
    from ...core.index.model import KIND_TECHNOLOGY

    groups: dict[str, list] = {}
    if index is None:
        return groups
    for symbol in index.symbols(KIND_TECHNOLOGY):
        attrs = symbol.attrs or {}
        groups.setdefault(attrs.get("folder") or "", []).append((symbol.name, attrs.get("year")))
    for items in groups.values():
        items.sort(key=lambda item: (item[1] if item[1] is not None else 0, item[0]))
    return dict(sorted(groups.items()))


def civilized_template(index, year: int) -> set[str]:
    return {name for items in technologies(index).values() for name, when in items
            if when is not None and when <= year}


class TechChecklist(QWidget):
    changed = Signal()

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tree = mark_data(QTreeWidget())
        self.tree.setObjectName("techTree")
        self.tree.setHeaderHidden(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree, 1)
        self.count_label = QLabel()
        self.count_label.setObjectName("techCount")
        layout.addWidget(self.count_label)
        self.reload()

    def reload(self) -> None:
        chosen = self.selected()
        with QSignalBlocker(self.tree):
            self.tree.clear()
            for folder, items in technologies(getattr(self.session, "index", None)).items():
                parent = QTreeWidgetItem([folder or "—"])
                parent.setFlags(parent.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                self.tree.addTopLevelItem(parent)
                for name, year in items:
                    child = QTreeWidgetItem([f"{self._label(name)}" + (f"  ({year})" if year else "")])
                    child.setData(0, ROLE_NAME, name)
                    child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    child.setCheckState(0, Qt.CheckState.Checked if name in chosen else Qt.CheckState.Unchecked)
                    parent.addChild(child)
                parent.setExpanded(True)
        self._count()

    def _label(self, name: str) -> str:
        index = getattr(self.session, "index", None)
        if index is None:
            return name
        from ...core.index.model import KIND_TECHNOLOGY

        symbol = index.get(KIND_TECHNOLOGY, name)
        try:
            return self.session.display(symbol) if symbol is not None else name
        except Exception:  # noqa: BLE001
            return name

    def _items(self):
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                yield parent.child(j)

    def selected(self) -> set[str]:
        return {item.data(0, ROLE_NAME) for item in self._items() if item.checkState(0) == Qt.CheckState.Checked}

    def set_selected(self, names) -> None:
        names = set(names or ())
        with QSignalBlocker(self.tree):
            for item in self._items():
                item.setCheckState(0, Qt.CheckState.Checked if item.data(0, ROLE_NAME) in names
                                   else Qt.CheckState.Unchecked)
        self._count()
        self.changed.emit()

    def _on_item_changed(self, *args) -> None:
        self._count()
        self.changed.emit()

    def _count(self) -> None:
        self.count_label.setText(tr(N_("pickers.tech.count"), n=len(self.selected())))


class TechTreeDialog(QDialog):
    """La lista de tecnologías con plantillas; ``selected()`` tras aceptar."""

    def __init__(self, session, selected=(), parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.setObjectName("techTreeDialog")
        self.resize(560, 620)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.template_combo = QComboBox()
        self.template_combo.setObjectName("techTemplate")
        for key in TEMPLATES:
            self.template_combo.addItem("", key)
        self.template_combo.currentIndexChanged.connect(self._on_template)
        row.addWidget(self.template_combo, 1)
        self.like_picker = TagPicker(session)
        self.like_picker.hide()
        row.addWidget(self.like_picker, 1)
        self.apply_button = QPushButton()
        self.apply_button.setObjectName("techTemplateApply")
        self.apply_button.clicked.connect(self.apply_template)
        row.addWidget(self.apply_button)
        layout.addLayout(row)
        self.checklist = TechChecklist(session)
        self.checklist.set_selected(selected)
        layout.addWidget(self.checklist, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        translator().languageChanged.connect(self._on_language)
        self.retranslate()

    def _on_language(self, code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.setWindowTitle(tr(N_("pickers.tech.title")))
        for i in range(self.template_combo.count()):
            self.template_combo.setItemText(i, tr(TEMPLATES[self.template_combo.itemData(i)]))
        self.apply_button.setText(tr(N_("pickers.tech.apply")))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr(N_("pickers.map.accept")))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr(N_("entity.cancel")))

    def _on_template(self, *args) -> None:
        self.like_picker.setVisible(self.template_combo.currentData() == TEMPLATE_LIKE)

    def template(self, key: str, tag: str | None = None) -> set[str]:
        index = getattr(self.session, "index", None)
        if key == TEMPLATE_UNCIVILIZED:
            return set()
        if key == TEMPLATE_LIKE:
            if not tag:
                return self.checklist.selected()
            from ...core.domain.nation import Countries

            entities = getattr(self.session, "entities", None)
            if entities is None:
                return set()
            rules = self.session.map.rules() if hasattr(self.session, "map") else None
            countries = Countries(entities, rules)
            date = rules.bookmarks[0] if rules is not None and rules.bookmarks else None
            return countries.technologies(tag, date)
        rules = self.session.map.rules() if hasattr(self.session, "map") else None
        year = rules.start_date.year if rules is not None else 1836
        return civilized_template(index, year)

    def apply_template(self) -> None:
        key = self.template_combo.currentData()
        self.checklist.set_selected(self.template(key, self.like_picker.value()))

    def selected(self) -> set[str]:
        return self.checklist.selected()
