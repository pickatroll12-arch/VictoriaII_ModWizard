"""Buscador universal Ctrl+K (wizard §13.4): símbolos del índice y secciones de la ventana.

``CommandPalette`` es un panel superpuesto dentro de la ventana principal (no una
ventana aparte: sale en las capturas y no depende del gestor de ventanas). Busca con
``Session.search`` (``SymbolIndex.search`` con la localización efectiva: «549»,
«Berlín», «berlin», «PRU», «north_german») y, además, entre los títulos de las salas
y secciones. Cada resultado muestra el icono y el nombre de su tipo, el nombre para
mostrar (``Session.display``: «Prusia (PRU)»), el id, el archivo y la línea, y su
origen (juego base o mod). Intro abre el archivo en esa línea (``symbol_activated``;
desde la iteración 4, el editor de la entidad); Mayús+Intro, el código
(``code_requested``); una sección, la sección (``section_activated``). Esc cierra.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.index import model as kinds
from ...core.index.model import fold
from ...core.vfs import LayerKind
from ...i18n import N_, tr, translator
from .. import theme
from ..widgets import make_icon, mark_data

SEARCH_DELAY_MS = 120
LIMIT = 40
WIDTH = 760
ITEM_ROLE = Qt.ItemDataRole.UserRole + 3
KIND_SYMBOL, KIND_SECTION = "symbol", "section"

KIND_LABELS = {
    kinds.KIND_TAG: N_("kind.tag"), kinds.KIND_PARTY: N_("kind.party"), kinds.KIND_GOVERNMENT: N_("kind.government"),
    kinds.KIND_IDEOLOGY: N_("kind.ideology"), kinds.KIND_ISSUE_GROUP: N_("kind.issue_group"),
    kinds.KIND_ISSUE_OPTION: N_("kind.issue_option"), kinds.KIND_NATIONAL_VALUE: N_("kind.national_value"),
    kinds.KIND_PROVINCE: N_("kind.province"), kinds.KIND_SEA_PROVINCE: N_("kind.sea_province"),
    kinds.KIND_PROVINCE_HISTORY: N_("kind.province_history"), kinds.KIND_REGION: N_("kind.region"),
    kinds.KIND_SEA_REGION: N_("kind.sea_region"), kinds.KIND_CONTINENT: N_("kind.continent"),
    kinds.KIND_CLIMATE: N_("kind.climate"), kinds.KIND_TERRAIN: N_("kind.terrain"),
    kinds.KIND_CULTURE: N_("kind.culture"), kinds.KIND_CULTURE_GROUP: N_("kind.culture_group"),
    kinds.KIND_RELIGION: N_("kind.religion"), kinds.KIND_RELIGION_GROUP: N_("kind.religion_group"),
    kinds.KIND_POP_TYPE: N_("kind.pop_type"), kinds.KIND_GOODS: N_("kind.goods"),
    kinds.KIND_BUILDING: N_("kind.building"), kinds.KIND_TECHNOLOGY: N_("kind.technology"),
    kinds.KIND_INVENTION: N_("kind.invention"), kinds.KIND_TECH_SCHOOL: N_("kind.tech_school"),
    kinds.KIND_UNIT_TYPE: N_("kind.unit_type"), kinds.KIND_GRAPHICAL_CULTURE: N_("kind.graphical_culture"),
    kinds.KIND_REBEL_TYPE: N_("kind.rebel_type"), kinds.KIND_TRAIT: N_("kind.trait"),
    kinds.KIND_MODIFIER: N_("kind.modifier"), kinds.KIND_CB: N_("kind.cb"), kinds.KIND_BOOKMARK: N_("kind.bookmark"),
    kinds.KIND_WAR: N_("kind.war"), kinds.KIND_COUNTRY_HISTORY: N_("kind.country_history"),
    kinds.KIND_EVENT: N_("kind.event"), kinds.KIND_DECISION: N_("kind.decision"),
    kinds.KIND_SPRITE: N_("kind.sprite"), kinds.KIND_GUI_WINDOW: N_("kind.gui_window"),
    kinds.KIND_IMAGE: N_("kind.image"), kinds.KIND_LOC_KEY: N_("kind.loc_key"),
    kinds.KIND_COUNTRY_FLAG: N_("kind.country_flag"), kinds.KIND_GLOBAL_FLAG: N_("kind.global_flag"),
    kinds.KIND_PROVINCE_FLAG: N_("kind.province_flag"),
}
KIND_ICONS = {
    kinds.KIND_TAG: "flag", kinds.KIND_COUNTRY_HISTORY: "countries", kinds.KIND_PARTY: "countries",
    kinds.KIND_GOVERNMENT: "crown", kinds.KIND_IDEOLOGY: "crown", kinds.KIND_ISSUE_GROUP: "crown",
    kinds.KIND_ISSUE_OPTION: "crown", kinds.KIND_NATIONAL_VALUE: "crown",
    kinds.KIND_PROVINCE: "map", kinds.KIND_SEA_PROVINCE: "anchor", kinds.KIND_PROVINCE_HISTORY: "map",
    kinds.KIND_REGION: "layers", kinds.KIND_SEA_REGION: "layers", kinds.KIND_CONTINENT: "layers",
    kinds.KIND_CLIMATE: "climate", kinds.KIND_TERRAIN: "climate",
    kinds.KIND_CULTURE: "culture", kinds.KIND_CULTURE_GROUP: "culture", kinds.KIND_RELIGION: "culture",
    kinds.KIND_RELIGION_GROUP: "culture", kinds.KIND_POP_TYPE: "culture",
    kinds.KIND_UNIT_TYPE: "helmet", kinds.KIND_CB: "swords", kinds.KIND_WAR: "swords",
    kinds.KIND_BOOKMARK: "calendar", kinds.KIND_EVENT: "events", kinds.KIND_DECISION: "scroll_seal",
    kinds.KIND_SPRITE: "window", kinds.KIND_GUI_WINDOW: "window", kinds.KIND_IMAGE: "file_image",
    kinds.KIND_LOC_KEY: "localisation",
}
LAYER_KEYS = {LayerKind.GAME: N_("palette.layer.game"), LayerKind.DEPENDENCY: N_("palette.layer.dependency"),
              LayerKind.MOD: N_("palette.layer.mod")}


def kind_label(kind: str) -> str:
    key = KIND_LABELS.get(kind)
    return tr(key) if key is not None else kind


class PaletteResult:
    """Un resultado: un símbolo del índice o una sección de la ventana («sala:sección»)."""

    __slots__ = ("kind", "symbol", "target", "title")

    def __init__(self, kind: str, *, symbol=None, target: str = "", title: str = ""):
        self.kind = kind
        self.symbol = symbol
        self.target = target
        self.title = title


class CommandPalette(QFrame):
    """``sections()`` da ``(«sala:sección», título traducido)`` de cada sección de la ventana."""

    symbol_activated = Signal(object)    # Symbol
    code_requested = Signal(object)      # Symbol (Mayús+Intro)
    section_activated = Signal(str)      # «sala:sección»
    closed = Signal()

    def __init__(self, session, sections: Callable[[], list[tuple[str, str]]], parent: QWidget):
        super().__init__(parent)
        self.setObjectName("commandPalette")
        self.session = session
        self.sections = sections
        self.setProperty("surface", "parchment")
        self.setAutoFillBackground(True)
        self.setFrameShape(QFrame.Shape.Box)
        self.setLineWidth(2)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName("paletteTitle")
        self.title.setProperty("role", "heading")
        self.title.setFont(theme.font("heading", 11))
        layout.addWidget(self.title)
        self.edit = QLineEdit()
        self.edit.setObjectName("paletteSearch")
        self.edit.setClearButtonEnabled(True)
        self.edit.addAction(make_icon("search", "ink_muted"), QLineEdit.ActionPosition.LeadingPosition)
        self.edit.textChanged.connect(lambda _: self._timer.start())
        self.edit.installEventFilter(self)
        layout.addWidget(self.edit)
        self.list = QListWidget()
        self.list.setObjectName("paletteResults")
        self.list.setIconSize(QSize(18, 18))
        self.list.setUniformItemSizes(True)
        self.list.itemActivated.connect(self._on_item_activated)
        self.list.installEventFilter(self)
        mark_data(self.list)
        layout.addWidget(self.list, 1)
        self.state = QLabel()
        self.state.setObjectName("paletteState")
        self.state.setProperty("role", "caption")
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.hint = QLabel()
        self.hint.setObjectName("paletteHint")
        self.hint.setProperty("role", "caption")
        self.hint.setFont(theme.font("caption"))
        layout.addWidget(self.hint)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SEARCH_DELAY_MS)
        self._timer.timeout.connect(self.search)
        self._results: list[PaletteResult] = []
        self.hide()
        app = QApplication.instance()
        app.focusChanged.connect(self._on_focus_changed)
        translator().languageChanged.connect(self._on_language_changed)
        session.symbolsChanged.connect(self._on_symbols_changed)
        self.retranslate()

    # --- API -----------------------------------------------------------------------------------------

    def open(self, text: str = "") -> None:
        """Muestra la paleta arriba en el centro de la ventana, con ``text`` buscado y el foco en el buscador."""
        self.place()
        self.show()
        self.raise_()
        self.edit.setText(text)
        self.edit.selectAll()
        self.edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search()

    def close_palette(self) -> None:
        if self.isVisible():
            self.hide()
            self.closed.emit()

    def results(self) -> list[PaletteResult]:
        return list(self._results)

    def result_texts(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    def search(self) -> None:
        """Busca ya (sin esperar a la pausa de teclas) y rellena la lista."""
        self._timer.stop()
        text = self.edit.text().strip()
        results: list[PaletteResult] = []
        if text:
            try:
                symbols = self.session.search(text, limit=LIMIT)
            except Exception:  # noqa: BLE001 - un índice a medias no debe romper la paleta
                symbols = []
            results.extend(PaletteResult(KIND_SYMBOL, symbol=symbol) for symbol in symbols)
            needle = fold(text)
            results.extend(PaletteResult(KIND_SECTION, target=target, title=title)
                           for target, title in self.sections() if needle in fold(title))
        self._results = results
        self.list.clear()
        for result in results:
            self.list.addItem(self._item(result))
        if self.list.count():
            self.list.setCurrentRow(0)
        self._retranslate_state()

    def activate(self, row: int | None = None, *, code: bool = False) -> bool:
        """Abre el resultado ``row`` (el seleccionado si es None); False si no hay ninguno."""
        row = self.list.currentRow() if row is None else row
        if not 0 <= row < len(self._results):
            return False
        result = self._results[row]
        self.close_palette()
        if result.kind == KIND_SECTION:
            self.section_activated.emit(result.target)
        elif code:
            self.code_requested.emit(result.symbol)
        else:
            self.symbol_activated.emit(result.symbol)
        return True

    # --- interno -------------------------------------------------------------------------------------

    def _item(self, result: PaletteResult) -> QListWidgetItem:
        if result.kind == KIND_SECTION:
            item = QListWidgetItem(make_icon("chevron_down", "ink_soft", "cream"),
                                   tr("palette.section", title=result.title))
            item.setToolTip(tr("palette.section_tooltip", title=result.title))
        else:
            symbol = result.symbol
            try:
                shown = self.session.display(symbol)
            except Exception:  # noqa: BLE001
                shown = symbol.name
            where = f"{symbol.rel}:{symbol.line}" if symbol.line else str(symbol.rel)
            layer = tr(LAYER_KEYS.get(symbol.layer, "palette.layer.game"))
            item = QListWidgetItem(make_icon(KIND_ICONS.get(symbol.kind, "info"), "ink_soft", "cream"),
                                   tr("palette.result", name=shown, kind=kind_label(symbol.kind), id=symbol.name,
                                      file=where, layer=layer))
            item.setToolTip(tr("palette.result_tooltip", name=shown, kind=kind_label(symbol.kind), file=where))
        item.setData(ITEM_ROLE, result)
        return item

    def place(self) -> None:
        parent = self.parentWidget()
        width = max(360, min(WIDTH, parent.width() - 80))
        height = max(260, min(460, parent.height() - 140))
        self.setGeometry((parent.width() - width) // 2, 70, width, height)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        self.activate(self.list.row(item))

    def _on_symbols_changed(self, kinds_changed) -> None:
        if self.isVisible() and self.edit.text().strip():
            self._timer.start()

    def _on_focus_changed(self, old, new) -> None:
        if self.isVisible() and new is not None and not self.isAncestorOf(new) and new is not self:
            self.close_palette()

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.KeyPress and watched in (self.edit, self.list):
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.close_palette()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._timer.isActive():
                    self.search()
                shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                self.activate(code=shift)
                return True
            if watched is self.edit and key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                if self.list.count():
                    step = 1 if key == Qt.Key.Key_Down else -1
                    self.list.setCurrentRow(max(0, min(self.list.count() - 1, self.list.currentRow() + step)))
                return True
        return super().eventFilter(watched, event)

    def _on_language_changed(self, code: str) -> None:
        self.retranslate()

    def _retranslate_state(self) -> None:
        session = self.session
        text = self.edit.text().strip()
        if session.project is None:
            self.state.setText(tr("palette.no_project"))
        elif session.index is None:
            state = session.index_state()
            self.state.setText(tr("palette.indexing") if state == "busy" else tr("palette.no_index"))
        elif not text:
            self.state.setText(tr("palette.empty"))
        elif not self._results:
            self.state.setText(tr("palette.nothing", text=text))
        else:
            self.state.setText(tr("palette.count_one" if len(self._results) == 1 else "palette.count",
                                  count=len(self._results)))

    def retranslate(self) -> None:
        self.title.setText(tr("palette.title"))
        self.edit.setPlaceholderText(tr("palette.placeholder"))
        self.hint.setText(tr("palette.hint"))
        if self.isVisible():
            self.search()
        else:
            self._retranslate_state()
