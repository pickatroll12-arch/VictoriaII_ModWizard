"""Sección «Países» de la sala Naciones (wizard §14.2). Iteración 6.

A la izquierda, los TAG registrados (con su color de mapa y su nombre) y un filtro; «Nuevo país…» abre el
asistente de 8 pasos. A la derecha, la ficha nacional del país elegido (``ui/countries/sheet.py``), en la fecha de
trabajo. La sección aloja los esquemas ``country``, ``country_history``, ``country_colors`` y ``oob``: un
problema o un resultado de Ctrl+K de cualquiera de ellos abre aquí la ficha del país (``focus_field``), y el
doble clic en una provincia del mapa abre la de su dueño.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from ....i18n import N_, tr
from ...countries import countries_facade, loc_text
from ...countries.sheet import NationalSheet
from ...pages.base import BasePage
from ...widgets import make_icon, mark_data

ROLE_TAG = Qt.ItemDataRole.UserRole


def _swatch(color) -> QIcon:
    pixmap = QPixmap(14, 14)
    pixmap.fill(QColor(*color[:3]) if color else QColor(0, 0, 0, 0))
    return QIcon(pixmap)


class CountriesPage(BasePage):
    entity_requested = Signal(str, str)     # una guerra de la pestaña Diplomacia: su página en la sala Guerra

    key = "countries"
    title_key = N_("section.nations.countries")
    subtitle_key = N_("countries.subtitle")
    icon_name = "countries"

    def __init__(self, session, parent: QWidget | None = None):
        self.session = session
        self.wizard = None
        self._pending: str | None = None      # TAG recién creado: se elige cuando el índice lo conozca
        super().__init__(parent)
        session.projectOpened.connect(self.reload)
        session.projectClosed.connect(self.reload)
        session.symbolsChanged.connect(self._on_symbols)
        session.indexStateChanged.connect(self.reload)
        self.reload()

    # --- construcción -----------------------------------------------------------------------------

    def build(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left.setMinimumWidth(220)
        layout = QVBoxLayout(left)
        layout.setContentsMargins(0, 0, 6, 0)
        self.new_button = QPushButton()
        self.new_button.setObjectName("countriesNew")
        self.new_button.setIcon(make_icon("plus", "gold_light"))
        self.new_button.clicked.connect(self.open_wizard)
        layout.addWidget(self.new_button)
        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("countriesFilter")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        layout.addWidget(self.filter_edit)
        self.list = mark_data(QListWidget())
        self.list.setObjectName("countriesList")
        self.list.currentItemChanged.connect(self._on_current)
        layout.addWidget(self.list, 1)
        self.count_label = QLabel()
        self.count_label.setObjectName("countriesCount")
        layout.addWidget(self.count_label)
        splitter.addWidget(left)
        self.sheet = NationalSheet(self.session)
        self.sheet.status_requested.connect(self.status_requested)
        self.sheet.openWar.connect(self._open_war)
        splitter.addWidget(self.sheet)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        self.body.addWidget(splitter, 1)

    def retranslate(self) -> None:
        super().retranslate()
        self.new_button.setText(tr(N_("countries.new")))
        self.filter_edit.setPlaceholderText(tr(N_("countries.filter")))
        self._update_count()

    # --- lista ------------------------------------------------------------------------------------

    def _on_symbols(self, kinds) -> None:
        if not kinds or "tag" in kinds or "country_history" in kinds:
            self.reload()

    def tags(self) -> list[str]:
        return [self.list.item(i).data(ROLE_TAG) for i in range(self.list.count())]

    def reload(self, *args) -> None:
        current = self.current_tag()
        self.list.blockSignals(True)
        self.list.clear()
        countries = countries_facade(self.session) if self.session.project is not None else None
        for tag in countries.tags() if countries is not None else ():
            name = loc_text(self.session, tag)
            item = QListWidgetItem(f"{tag} · {name}" if name else tag)
            item.setData(ROLE_TAG, tag)
            color = self.session.index.attrs("tag", tag, "color") if self.session.index is not None else None
            if not color:
                color = countries.file_value(tag, "color") if countries is not None else None
            item.setIcon(_swatch(tuple(color) if color else None))
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._apply_filter()
        if self._pending and self._pending in self.tags():
            self.select_tag(self._pending)
            self._pending = None
        elif current and current in self.tags():
            self.select_tag(current)
        elif self.list.count():
            self.select_tag(self.tags()[0])
        else:
            self.sheet.bind(None)
        self._update_count()

    def _apply_filter(self, *args) -> None:
        text = self.filter_edit.text().strip().lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(bool(text) and text not in item.text().lower())
        self._update_count()

    def _update_count(self) -> None:
        visible = sum(1 for i in range(self.list.count()) if not self.list.item(i).isHidden())
        self.count_label.setText(tr(N_("countries.count"), count=visible, total=self.list.count()))

    def current_tag(self) -> str | None:
        item = self.list.currentItem()
        return item.data(ROLE_TAG) if item is not None else None

    def select_tag(self, tag: str) -> bool:
        tag = (tag or "").upper()
        for i in range(self.list.count()):
            if self.list.item(i).data(ROLE_TAG) == tag:
                self.list.setCurrentRow(i)
                if self.sheet.tag != tag:
                    self.sheet.bind(tag)
                return True
        return False

    def _on_current(self, current, previous) -> None:
        self.sheet.bind(current.data(ROLE_TAG) if current is not None else None)

    # --- acciones ---------------------------------------------------------------------------------

    def new_country_wizard(self):
        """El asistente «Nuevo país» (sin abrirlo: las pruebas lo rellenan y llaman a ``create``)."""
        from ...countries.wizard import NewCountryWizard

        wizard = NewCountryWizard(self.session, self)
        wizard.created.connect(self._on_created)
        self.wizard = wizard
        return wizard

    def open_wizard(self) -> None:
        if self.session.project is None:
            self.status_requested.emit(N_("countries.no_project"), {})
            return
        self.new_country_wizard().open()

    def _on_created(self, tag: str) -> None:
        self._pending = tag.upper()
        self.reload()
        self.status_requested.emit(N_("countries.created"), {"tag": tag})

    def _open_war(self, rel) -> None:
        from ....core.vfs.paths import VPath

        name = VPath.of(str(rel)).name        # el dato de un QListWidgetItem vuelve como str
        self.entity_requested.emit("war", name[:-4] if name.lower().endswith(".txt") else name)

    def focus_field(self, ref, field=()) -> bool:
        """Abre la ficha del país de ``ref``: ``country_history:<TAG>``, ``oob:<TAG>_oob``, ``country:<archivo>``…"""
        kind = getattr(ref, "kind", "")
        ident = str(getattr(ref, "ident", ref))
        if kind == "country":
            countries = countries_facade(self.session)
            for tag in countries.tags() if countries is not None else ():
                path = "/" + (countries.country_file(tag) or "").lower()   # «countries/aland.txt», con o sin common/
                if path.endswith("/" + ident.lower()):
                    return self._focus(tag, "identity")
            return False
        if kind == "oob":
            return self._focus(ident.split("_", 1)[0], "army")
        tag = ident.split(" ", 1)[0].upper()
        return self._focus(tag, _tab_for(field))

    def _focus(self, tag: str, tab: str) -> bool:
        if not self.select_tag(tag):
            return False
        self.sheet.show_tab(tab)
        return True


def _tab_for(field) -> str:
    first = field[0] if field else ""
    if first in ("government", "ruling_party", "plurality", "prestige", "nationalvalue", "upper_house"):
        return "politics"
    if first in ("literacy", "non_state_culture_literacy", "consciousness", "nonstate_consciousness", "schools"):
        return "society"
    if first == "oob":
        return "army"
    return "identity"

