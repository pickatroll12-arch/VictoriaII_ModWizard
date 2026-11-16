"""Buscador del catálogo: lo que se puede añadir a un grupo, por categorías (wizard §14.7).

Una caja de búsqueda (por etiqueta ES/EN y por clave cruda, sin acentos), la lista de categorías
(``catalog.categories``) y los resultados (``catalog.suggestions``), cada uno con su etiqueta y su clave. Al
elegir una familia (un TAG, una provincia, una tecnología…) pide la clave concreta con
``catalog.family_keys``. Lo que se teclea y no está catalogado se puede añadir como clave cruda.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...i18n import N_, tr, translator
from ..widgets import mark_data

_DEF = Qt.ItemDataRole.UserRole
_ALL = "__all__"
CATEGORY_KEYS = {
    "country": N_("script_ui.category.country"), "province": N_("script_ui.category.province"),
    "time": N_("script_ui.category.time"), "technology": N_("script_ui.category.technology"),
    "politics": N_("script_ui.category.politics"), "economy": N_("script_ui.category.economy"),
    "diplomacy": N_("script_ui.category.diplomacy"), "population": N_("script_ui.category.population"),
    "flags": N_("script_ui.category.flags"), "military": N_("script_ui.category.military"),
    "events": N_("script_ui.category.events"), "logic": N_("script_ui.category.logic"),
    "scope": N_("script_ui.category.scope"), "other": N_("script_ui.category.other"),
}
FAMILY_LIMIT = 400                               # claves de familia que se listan a la vez (se filtra al teclear)


def _lang() -> str:
    from .trigger_builder import phrase_language

    return phrase_language()


def definition_label(definition, lang: str) -> str:
    return definition.label.get(lang) or definition.label.get("en") or definition.name


class CatalogPicker(QWidget):
    """Buscador de claves del catálogo para un tipo de guion y un ámbito."""

    picked = Signal(object, str)                 # (ScriptKeyDef, clave concreta: el nombre, o la de la familia)
    raw_requested = Signal(str)                  # clave tecleada que el catálogo no conoce
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("catalogPicker")
        self._catalog = None
        self._kind = None
        self._scope = None
        self._roles = None
        self._category: str | None = None
        self._family = None
        self._results: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.search = mark_data(QLineEdit())
        self.search.setObjectName("catalogSearch")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_text)
        self.search.returnPressed.connect(self._accept_current)
        outer.addWidget(self.search)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)

        # Página 1: categorías y resultados.
        browse = QWidget()
        row = QHBoxLayout(browse)
        row.setContentsMargins(0, 0, 0, 0)
        self.categories = mark_data(QListWidget())
        self.categories.setObjectName("catalogCategories")
        self.categories.setMaximumWidth(190)
        self.categories.currentItemChanged.connect(self._on_category)
        self.list = mark_data(QListWidget())
        self.list.setObjectName("catalogResults")
        self.list.itemActivated.connect(lambda item: self.pick(item.data(_DEF)))
        self.list.currentItemChanged.connect(self._on_result)
        right = QVBoxLayout()
        right.addWidget(self.list, 1)
        self.help = mark_data(QLabel())
        self.help.setObjectName("catalogHelp")
        self.help.setWordWrap(True)
        right.addWidget(self.help)
        self.raw_button = QPushButton()
        self.raw_button.setObjectName("catalogRaw")
        self.raw_button.clicked.connect(self._request_raw)
        right.addWidget(self.raw_button)
        row.addWidget(self.categories)
        row.addLayout(right, 1)
        self.stack.addWidget(browse)

        # Página 2: la clave concreta de una familia.
        family = QWidget()
        column = QVBoxLayout(family)
        column.setContentsMargins(0, 0, 0, 0)
        self.family_title = mark_data(QLabel())
        self.family_title.setObjectName("catalogFamilyTitle")
        column.addWidget(self.family_title)
        self.family_list = mark_data(QListWidget())
        self.family_list.setObjectName("catalogFamilyKeys")
        self.family_list.itemActivated.connect(lambda item: self.pick(self._family, item.text()))
        column.addWidget(self.family_list, 1)
        self.family_edit = mark_data(QLineEdit())
        self.family_edit.setObjectName("catalogFamilyKey")
        self.family_edit.returnPressed.connect(lambda: self.pick(self._family, self.family_edit.text().strip()))
        column.addWidget(self.family_edit)
        buttons = QHBoxLayout()
        self.back_button = QPushButton()
        self.back_button.setObjectName("catalogBack")
        self.back_button.clicked.connect(self._back)
        self.family_ok = QPushButton()
        self.family_ok.setObjectName("catalogFamilyOk")
        self.family_ok.clicked.connect(self._accept_family)
        buttons.addWidget(self.back_button)
        buttons.addStretch(1)
        buttons.addWidget(self.family_ok)
        column.addLayout(buttons)
        self.stack.addWidget(family)
        translator().languageChanged.connect(self._on_language)
        self.retranslate()

    # --- contexto ---------------------------------------------------------------------------------

    def set_context(self, catalog, kind, scope, *, roles=None) -> None:
        """Qué se ofrece: las sugerencias de ``catalog`` para ``kind`` y ``scope``; ``roles`` limita los
        papeles (``Role.SCOPE`` e ``ITERATOR`` en «+ Ámbito»)."""
        self._catalog, self._kind, self._scope = catalog, kind, scope
        self._roles = None if roles is None else tuple(roles)
        self._category = None
        self._back()
        self._fill_categories()
        self._fill_results()

    def set_filter(self, text: str) -> None:
        """Texto de búsqueda (lo mismo que teclear en la caja)."""
        if self.search.text() != text:
            self.search.setText(text)
        else:
            self._fill_results()

    def set_category(self, category: str | None) -> None:
        """Filtra por una categoría de ``CATEGORIES`` (None: todas)."""
        self._category = category
        wanted = _ALL if category is None else category
        for row in range(self.categories.count()):
            if self.categories.item(row).data(_DEF) == wanted:
                self.categories.blockSignals(True)
                self.categories.setCurrentRow(row)
                self.categories.blockSignals(False)
                break
        self._fill_results()

    def results(self) -> list:
        """Las ``ScriptKeyDef`` que se ven ahora, en orden."""
        return list(self._results)

    def _suggestions(self, text: str = "") -> list:
        if self._catalog is None or self._kind is None:
            return []
        return self._catalog.suggestions(self._kind, self._scope, text, _lang(), roles=self._roles)

    def _fill_categories(self) -> None:
        self.categories.blockSignals(True)
        self.categories.clear()
        item = QListWidgetItem(tr(N_("script_ui.category.all")))
        item.setData(_DEF, _ALL)
        self.categories.addItem(item)
        present = []
        for definition in self._suggestions():
            if definition.category not in present:
                present.append(definition.category)
        from ...core.script.catalog import CATEGORIES

        for category in CATEGORIES:
            if category in present:
                item = QListWidgetItem(tr(CATEGORY_KEYS.get(category, N_("script_ui.category.other"))))
                item.setData(_DEF, category)
                self.categories.addItem(item)
        self.categories.setCurrentRow(0)
        self.categories.blockSignals(False)

    def _fill_results(self) -> None:
        lang = _lang()
        text = self.search.text().strip()
        found = self._suggestions(text)
        if self._category is not None:
            found = [d for d in found if d.category == self._category]
        self._results = found
        self.list.clear()
        for definition in found:
            label = definition_label(definition, lang)
            shown = f"{label}  ·  {definition.name}" + ("  …" if definition.family else "")
            item = QListWidgetItem(shown)
            item.setData(_DEF, definition)
            item.setToolTip(definition.help.get(lang) or definition.help.get("en", "") or definition.name)
            self.list.addItem(item)
        if found:
            self.list.setCurrentRow(0)
        raw = text.partition("=")[0].strip()
        known = bool(raw) and self._catalog is not None and any(d.name.lower() == raw.lower() for d in found)
        self.raw_button.setVisible(bool(raw) and not known and " " not in raw)
        self.raw_button.setText(tr(N_("script_ui.picker.raw"), key=text))

    def _on_text(self, _text: str) -> None:
        if self.stack.currentIndex() == 1:
            self._fill_family()
        else:
            self._fill_results()

    def _on_category(self, current, _previous=None) -> None:
        value = current.data(_DEF) if current is not None else _ALL
        self._category = None if value == _ALL else value
        self._fill_results()

    def _on_result(self, current, _previous=None) -> None:
        definition = current.data(_DEF) if current is not None else None
        lang = _lang()
        self.help.setText("" if definition is None else
                          (definition.help.get(lang) or definition.help.get("en", "") or ""))

    # --- elegir -----------------------------------------------------------------------------------

    def pick(self, definition, key: str | None = None) -> None:
        """Elige una definición (como un doble clic). En una familia sin ``key`` pasa a pedir la clave."""
        if definition is None:
            return
        if definition.family and not key:
            self._family = definition
            self.family_title.setText(tr(N_("script_ui.picker.family"),
                                         label=definition_label(definition, _lang())))
            self.family_edit.clear()
            self.stack.setCurrentIndex(1)
            self._fill_family()
            return
        if definition.family and not definition.matches(key):
            return
        self.picked.emit(definition, key or definition.name)

    def _fill_family(self) -> None:
        self.family_list.clear()
        if self._family is None or self._catalog is None:
            return
        for name in self._catalog.family_keys(self._family, self.search.text().strip(), limit=FAMILY_LIMIT):
            self.family_list.addItem(name)

    def _accept_family(self) -> None:
        item = self.family_list.currentItem()
        key = self.family_edit.text().strip() or (item.text() if item is not None else "")
        if key:
            self.pick(self._family, key)

    def _back(self) -> None:
        self._family = None
        self.stack.setCurrentIndex(0)

    def _accept_current(self) -> None:
        if self.stack.currentIndex() == 1:
            self._accept_family()
            return
        item = self.list.currentItem()
        if item is not None:
            self.pick(item.data(_DEF))
        elif self.raw_button.isVisible():
            self._request_raw()

    def _request_raw(self) -> None:
        text = self.search.text().strip()
        if text:
            self.raw_requested.emit(text)

    def _on_language(self, _code: str = "") -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.search.setPlaceholderText(tr(N_("script_ui.picker.search")))
        self.back_button.setText(tr(N_("script_ui.picker.back")))
        self.family_ok.setText(tr(N_("script_ui.picker.add")))
        self.family_edit.setPlaceholderText(tr(N_("script_ui.picker.family_key")))
        if self._catalog is not None:
            category = self._category
            self._fill_categories()
            self.set_category(category)
        else:
            self.raw_button.setText(tr(N_("script_ui.picker.raw"), key=""))
            self.raw_button.hide()


class CatalogPickerDialog(QDialog):
    """El buscador en una ventana («+ Condición», «+ Efecto», «+ Ámbito»)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("catalogPickerDialog")
        self.resize(640, 460)
        layout = QVBoxLayout(self)
        self.picker = CatalogPicker(self)
        layout.addWidget(self.picker, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.rejected.connect(self.reject)
        self.picker.cancelled.connect(self.reject)
        layout.addWidget(self.buttons)
        self.setWindowTitle(tr(N_("script_ui.picker.title")))
