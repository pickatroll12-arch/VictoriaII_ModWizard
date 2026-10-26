"""Visor de scripts Clausewitz: estructura, código fuente, diagnósticos y JSON.

El análisis (``load_clausewitz``) corre en un hilo: parsea, reconstruye el texto
exacto con ``to_source`` y aplana el árbol en un índice en preorden. La interfaz
crea los elementos del árbol solo al expandir cada rama, así que abrir un
archivo con decenas de miles de entradas no la bloquea. El JSON se genera
también en segundo plano y solo cuando se abre su pestaña.
"""

from __future__ import annotations

import bisect
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.clausewitz import Block, Entry, ParseResult, Scalar, parse_file, to_json, to_source
from ...core.modcheck import CLAUSEWITZ_SUFFIXES
from ...i18n import N_, tr
from ...settings import app_settings
from .. import theme
from ..tasks import TaskRunner
from ..widgets import EmptyState, make_icon, mark_data, rich, show_in_stack
from .code_view import CodeView, display_text, string_continuations
from .common import SEVERITY_RANK, ViewerHeader, format_number, format_size, severity_icon, severity_name, \
    summary_status
from .diagnostics import DiagnosticRow, DiagnosticsModel, DiagnosticsView

__all__ = [
    "CLAUSEWITZ_SUFFIXES", "ClausewitzLoad", "ClausewitzViewer", "StructureIndex", "build_index",
    "json_text", "load_clausewitz",
]

TAB_STRUCTURE, TAB_SOURCE, TAB_DIAGNOSTICS, TAB_JSON = "structure", "source", "diagnostics", "json"
TABS = (TAB_STRUCTURE, TAB_SOURCE, TAB_DIAGNOSTICS, TAB_JSON)
SETTINGS_TAB = "viewer/clausewitz_tab"
AUTO_EXPAND_LIMIT = 400        # entradas: por debajo, el árbol se abre entero al cargar
EXPAND_ALL_LIMIT = 20_000      # entradas: por encima, «expandir todo» abre solo el primer nivel
JSON_DISPLAY_LIMIT = 2_000_000  # caracteres de JSON que se muestran como mucho
INLINE_LIST_LIMIT = 60          # una lista de escalares más corta se muestra en línea
LOADING_DELAY_MS = 150
SEARCH_DELAY_MS = 150
NODE_ROLE = Qt.ItemDataRole.UserRole + 7
ENCODING_NAMES = {"cp1252": "Windows-1252", "utf-8": "UTF-8", "utf-8-sig": "UTF-8 BOM"}


# --- análisis en segundo plano (sin Qt) ----------------------------------------------------

def _scalar_display(scalar: Scalar) -> str:
    return f'"{scalar.text}"' if scalar.quoted else scalar.text


@dataclass
class StructureIndex:
    """Árbol aplanado en preorden; ``children[i]`` es ``None`` si la entrada ``i`` es escalar."""

    entries: list[Entry] = field(default_factory=list)
    parents: list[int] = field(default_factory=list)
    children: list[list[int] | None] = field(default_factory=list)
    roots: list[int] = field(default_factory=list)
    lines: list[int] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    haystack: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.entries)

    def chain(self, node: int) -> list[int]:
        """Índices desde la raíz hasta ``node`` (incluido)."""
        chain = []
        while node >= 0:
            chain.append(node)
            node = self.parents[node]
        chain.reverse()
        return chain

    def key_path(self, node: int) -> tuple[str, ...]:
        return tuple(self.keys[i] for i in self.chain(node))

    def node_at_line(self, line: int | None) -> int | None:
        """Última entrada (la más profunda) que empieza en ``line`` o antes."""
        if line is None or not self.lines:
            return None
        position = bisect.bisect_right(self.lines, line) - 1
        return position if position >= 0 else None


def build_index(block: Block) -> StructureIndex:
    index = StructureIndex()
    stack = [(-1, iter(enumerate(block.entries)))]
    while stack:
        parent, iterator = stack[-1]
        for position, entry in iterator:
            node = len(index.entries)
            index.entries.append(entry)
            index.parents.append(parent)
            (index.roots if parent < 0 else index.children[parent]).append(node)
            index.lines.append(entry.line or 0)
            key = entry.key.text if entry.key is not None else f"[{position}]"
            value = entry.value
            if isinstance(value, Scalar):
                shown = _scalar_display(value)
                index.children.append(None)
            else:
                shown = ""
                if value.entries and all(e.key is None and isinstance(e.value, Scalar) for e in value.entries):
                    inline = " ".join(_scalar_display(e.value) for e in value.entries)
                    if len(inline) <= INLINE_LIST_LIMIT:
                        shown = "{ " + inline + " }"
                index.children.append([])
            index.keys.append(key)
            index.values.append(shown)
            index.haystack.append(f"{key}\x00{shown}".casefold())
            if not isinstance(value, Scalar):
                stack.append((node, iter(enumerate(value.entries))))
                break
        else:
            stack.pop()
    return index


@dataclass
class ClausewitzLoad:
    path: Path
    result: ParseResult
    text: str
    size: int
    lines: int
    index: StructureIndex
    elapsed: float
    continuations: frozenset[int] = frozenset()


def load_clausewitz(path: str | os.PathLike) -> ClausewitzLoad:
    """Parsea ``path`` y prepara todo lo que la interfaz necesita (se ejecuta en un hilo)."""
    start = time.perf_counter()
    path = Path(path)
    result = parse_file(path)
    text = display_text(to_source(result.document))
    lines = text.count("\n") + (0 if not text or text.endswith("\n") else 1)
    index = build_index(result.document)
    return ClausewitzLoad(path, result, text, path.stat().st_size, lines, index, time.perf_counter() - start,
                          string_continuations(text))


@dataclass
class ClausewitzFailure:
    """El archivo no se pudo leer (el contenido nunca hace fallar al parser)."""

    path: Path
    message: str


def try_load_clausewitz(path: str | os.PathLike) -> ClausewitzLoad | ClausewitzFailure:
    try:
        return load_clausewitz(path)
    except OSError as exc:
        return ClausewitzFailure(Path(path), exc.strerror or str(exc))


def json_text(document: Block) -> str:
    return json.dumps(to_json(document), ensure_ascii=False, indent=2)


# --- widget --------------------------------------------------------------------------------

class _SearchKeys(QObject):
    """Mayús+Intro en el buscador va a la coincidencia anterior."""

    def __init__(self, viewer: ClausewitzViewer):
        super().__init__(viewer)
        self.viewer = viewer

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.viewer.previous_match()
            else:
                self.viewer.next_match()
            return True
        return False


class ClausewitzViewer(QWidget):
    """Visor con pestañas; ``load(ruta, line=…, tab=…)`` y ``show_diagnostic(fila)``."""

    loaded = Signal(object)  # Path

    TAB_KEYS = {
        TAB_STRUCTURE: N_("viewer.tab.structure"), TAB_SOURCE: N_("viewer.tab.source"),
        TAB_DIAGNOSTICS: N_("viewer.tab.diagnostics"), TAB_JSON: N_("viewer.tab.json"),
    }
    TREE_HEADER_KEYS = (N_("viewer.col.key"), N_("viewer.col.op"), N_("viewer.col.value"), N_("viewer.col.line"))

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("clausewitzViewer")
        self._path: Path | None = None
        self._root: Path | None = None
        self._load: ClausewitzLoad | None = None
        self._error: str | None = None
        self._pending: tuple[int | None, int | None, str | None] | None = None
        self._items: dict[int, QTreeWidgetItem] = {}
        self._populated: set[int] = set()
        self._marks: dict[int, str] = {}
        self._matches: list[int] = []
        self._match_set: set[int] = set()
        self._match_pos = -1
        self._syncing = False
        self._json_for: ClausewitzLoad | None = None
        self._json_note: tuple[str, dict] | None = None
        self._mono = theme.font("mono")
        self._match_brush = QColor(201, 162, 74, 120)

        self._runner = TaskRunner(self)
        self._runner.finished.connect(self._on_loaded)
        self._runner.failed.connect(self._on_failed)
        self._json_runner = TaskRunner(self)
        self._json_runner.finished.connect(self._on_json_ready)
        self._json_runner.failed.connect(self._on_json_failed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.header = ViewerHeader("file_text")
        layout.addWidget(self.header)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.loading = QWidget()
        loading = QVBoxLayout(self.loading)
        loading.addStretch(1)
        self.loading_label = QLabel()
        self.loading_label.setProperty("role", "caption")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading.addWidget(self.loading_label)
        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setTextVisible(False)
        self.loading_bar.setMaximumWidth(260)
        loading.addWidget(self.loading_bar, 0, Qt.AlignmentFlag.AlignHCenter)
        loading.addStretch(2)
        self.stack.addWidget(self.loading)

        self.failure = EmptyState("error")
        self.stack.addWidget(self.failure)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("viewerTabs")
        self.tabs.setDocumentMode(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        self.stack.addWidget(self.tabs)
        self.tabs.addTab(self._build_structure(), "")
        self.tabs.addTab(self._build_source(), "")
        self.tabs.addTab(self._build_diagnostics(), "")
        self.tabs.addTab(self._build_json(), "")
        stored = app_settings().value(SETTINGS_TAB, TAB_STRUCTURE, str)
        self.tabs.setCurrentIndex(TABS.index(stored) if stored in TABS else 0)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._loading_timer = QTimer(self)
        self._loading_timer.setSingleShot(True)
        self._loading_timer.setInterval(LOADING_DELAY_MS)
        self._loading_timer.timeout.connect(lambda: show_in_stack(self.stack, self.loading))
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self._run_search)
        show_in_stack(self.stack, self.tabs)
        self.retranslate()

    # --- construcción --------------------------------------------------------------------

    def _tool_button(self, name: str, icon: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName(name)
        button.setIcon(make_icon(icon, "gold_light"))
        button.setIconSize(QSize(16, 16))
        button.setAutoRaise(False)
        return button

    def _build_structure(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(6, 8, 6, 6)
        column.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("structureSearch")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.addAction(make_icon("search", "ink_muted"), QLineEdit.ActionPosition.LeadingPosition)
        self.search_edit.textChanged.connect(lambda _: self._search_timer.start())
        self.search_edit.installEventFilter(_SearchKeys(self))
        row.addWidget(self.search_edit, 1)
        self.match_label = QLabel()
        self.match_label.setObjectName("structureMatches")
        self.match_label.setProperty("role", "caption")
        self.match_label.setMinimumWidth(64)
        self.match_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.match_label)
        self.previous_action = QAction(make_icon("chevron_up", "gold_light"), "", self)
        self.previous_action.setShortcut(QKeySequence("Shift+F3"))
        self.previous_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.previous_action.triggered.connect(self.previous_match)
        self.next_action = QAction(make_icon("chevron_down", "gold_light"), "", self)
        self.next_action.setShortcut(QKeySequence("F3"))
        self.next_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.next_action.triggered.connect(self.next_match)
        self.addAction(self.previous_action)
        self.addAction(self.next_action)
        self.previous_button = self._tool_button("previousMatch", "chevron_up")
        self.previous_button.setDefaultAction(self.previous_action)
        self.next_button = self._tool_button("nextMatch", "chevron_down")
        self.next_button.setDefaultAction(self.next_action)
        self.expand_button = self._tool_button("expandAll", "expand")
        self.expand_button.clicked.connect(self.expand_all)
        self.collapse_button = self._tool_button("collapseAll", "collapse")
        for button in (self.previous_button, self.next_button, self.expand_button, self.collapse_button):
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            row.addWidget(button)
        column.addLayout(row)

        self.tree = QTreeWidget()
        self.tree.setObjectName("structureTree")
        self.tree.setColumnCount(4)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setAnimated(False)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_tree_menu)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self.tree.currentItemChanged.connect(self._on_current_item_changed)
        self.collapse_button.clicked.connect(self.tree.collapseAll)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 230)
        header.resizeSection(1, 40)
        header.resizeSection(3, 58)
        column.addWidget(self.tree, 1)
        return page

    def _build_source(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(6, 8, 6, 6)
        column.setSpacing(4)
        self.code = CodeView()
        column.addWidget(self.code, 1)
        return page

    def _build_diagnostics(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(6, 8, 6, 6)
        column.setSpacing(6)
        self.diagnostics_hint = QLabel()
        self.diagnostics_hint.setProperty("role", "caption")
        self.diagnostics_hint.setWordWrap(True)
        column.addWidget(self.diagnostics_hint)
        self.diagnostics_stack = QStackedWidget()
        self.diagnostics_model = DiagnosticsModel(parent=self)
        self.diagnostics_view = DiagnosticsView(self.diagnostics_model)
        self.diagnostics_view.setObjectName("viewerDiagnostics")
        self.diagnostics_view.diagnostic_activated.connect(self.show_diagnostic)
        self.diagnostics_empty = EmptyState("check")
        self.diagnostics_stack.addWidget(self.diagnostics_view)
        self.diagnostics_stack.addWidget(self.diagnostics_empty)
        column.addWidget(self.diagnostics_stack, 1)
        return page

    def _build_json(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(6, 8, 6, 6)
        column.setSpacing(4)
        self.json_caption = QLabel()
        self.json_caption.setTextFormat(Qt.TextFormat.RichText)
        self.json_caption.setProperty("role", "caption")
        self.json_caption.setWordWrap(True)
        column.addWidget(self.json_caption)
        self.json_view = QPlainTextEdit()
        self.json_view.setObjectName("jsonView")
        mark_data(self.json_view)
        self.json_view.setReadOnly(True)
        self.json_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.json_view.setFont(theme.font("mono"))
        column.addWidget(self.json_view, 1)
        self.json_note = QLabel()
        self.json_note.setTextFormat(Qt.TextFormat.RichText)
        self.json_note.setProperty("role", "caption")
        self.json_note.setWordWrap(True)
        self.json_note.setVisible(False)
        column.addWidget(self.json_note)
        return page

    # --- API pública ---------------------------------------------------------------------

    def current_path(self) -> Path | None:
        return self._path

    def current_load(self) -> ClausewitzLoad | None:
        return self._load if self._load is not None and self._load.path == self._path else None

    def is_busy(self) -> bool:
        return self._runner.is_busy() or self._json_runner.is_busy()

    def load(self, path: str | os.PathLike, *, root: Path | None = None, line: int | None = None,
             column: int | None = None, tab: str | None = None) -> None:
        """Analiza ``path`` en segundo plano; ``line``/``tab`` se aplican al terminar."""
        path = Path(path)
        self._root = root
        if tab is not None and tab not in TABS:
            raise ValueError(f"pestaña desconocida: {tab!r}")
        self._pending = (line, column, tab) if (line is not None or tab is not None) else None
        if path == self._path and (self._runner.is_busy() or self.current_load() is not None):
            if not self._runner.is_busy():
                self._apply_pending()
            return
        self._path = path
        self._error = None
        self._json_runner.cancel()
        self.header.set_file(path, "")
        self.header.set_summary(None)
        self._retranslate_header()
        self._runner.start(lambda ctx: try_load_clausewitz(path))
        self._loading_timer.start()

    def clear(self) -> None:
        self._runner.cancel()
        self._json_runner.cancel()
        self._loading_timer.stop()
        self._path = self._load = self._json_for = None
        self._error = None
        self._reset_tree()
        self.code.clear_source()
        self.diagnostics_model.set_rows([])
        self.json_view.clear()
        self.header.set_file(None)
        self.header.set_summary(None)
        show_in_stack(self.stack, self.tabs)
        self.retranslate()

    def select_tab(self, tab: str) -> None:
        self.tabs.setCurrentIndex(TABS.index(tab))

    def current_tab(self) -> str:
        return TABS[self.tabs.currentIndex()]

    def set_compact(self, compact: bool) -> None:
        """Oculta las líneas de ayuda (pasan a ser ayudas emergentes) cuando falta altura."""
        self.diagnostics_hint.setVisible(not compact)
        self.json_caption.setVisible(not compact)

    def go_to_line(self, line: int, column: int | None = None) -> bool:
        """Salta a ``line`` en el código fuente y selecciona su nodo en la estructura."""
        load = self.current_load()
        if load is None:
            return False
        node = load.index.node_at_line(line)
        if node is not None:
            self.reveal_node(node)
        self.select_tab(TAB_SOURCE)
        return self.code.go_to_line(line, column)

    def show_diagnostic(self, row: DiagnosticRow) -> None:
        if row.line is not None:
            self.go_to_line(row.line, row.column)

    def reveal_node(self, node: int) -> QTreeWidgetItem:
        """Crea (si hace falta), expande hasta y selecciona el nodo ``node`` sin mover el código."""
        item = self._ensure_item(node)
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self._syncing = True
        try:
            self.tree.setCurrentItem(item)
        finally:
            self._syncing = False
        self.tree.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
        return item

    def node_of_item(self, item: QTreeWidgetItem | None) -> int | None:
        return None if item is None else item.data(0, NODE_ROLE)

    def item_for_node(self, node: int) -> QTreeWidgetItem | None:
        return self._items.get(node)

    def set_search(self, text: str) -> None:
        self.search_edit.setText(text)
        self._search_timer.stop()
        self._run_search()

    def matches(self) -> list[int]:
        return list(self._matches)

    def next_match(self) -> None:
        if self._search_timer.isActive():
            self._search_timer.stop()
            self._run_search()
            return
        if self._matches:
            self._go_to_match((self._match_pos + 1) % len(self._matches))

    def previous_match(self) -> None:
        if self._search_timer.isActive():
            self._search_timer.stop()
            self._run_search()
        if self._matches:
            self._go_to_match((self._match_pos - 1) % len(self._matches))

    def expand_all(self) -> None:
        """Expande todo; en archivos enormes solo el primer nivel, para no crear cientos de miles de filas."""
        load = self.current_load()
        if load is None:
            return
        index = load.index
        self.tree.setUpdatesEnabled(False)
        try:
            if len(index) > EXPAND_ALL_LIMIT:
                for node in index.roots:
                    self._populate(node)
                self.tree.expandToDepth(0)
                return
            for node, children in enumerate(index.children):
                if children:
                    self._populate(node)
            self.tree.expandAll()
        finally:
            self.tree.setUpdatesEnabled(True)

    # --- carga ---------------------------------------------------------------------------

    def _on_loaded(self, load: ClausewitzLoad | ClausewitzFailure) -> None:
        self._loading_timer.stop()
        if load.path != self._path:
            return
        if isinstance(load, ClausewitzFailure):
            self._show_failure(load.message)
            return
        self._load = load
        self._json_for = None
        result = load.result
        markers: dict[int, str] = {}
        rows = []
        marks: dict[int, str] = {}
        for diagnostic in result.diagnostics:
            severity = severity_name(diagnostic.severity)
            rows.append(DiagnosticRow.of(diagnostic, load.path))
            for target, key in ((markers, diagnostic.line), (marks, load.index.node_at_line(diagnostic.line))):
                if key is not None and SEVERITY_RANK[severity] < SEVERITY_RANK.get(target.get(key), 9):
                    target[key] = severity
        self._marks = marks
        self.code.set_source(load.text, markers, continuations=load.continuations)
        self.diagnostics_model.set_rows(rows)
        show_in_stack(self.diagnostics_stack, self.diagnostics_view if rows else self.diagnostics_empty)
        self._fill_tree(load)
        self.json_view.clear()
        self.json_note.setVisible(False)
        show_in_stack(self.stack, self.tabs)
        self.retranslate()
        self._apply_pending()
        if self.current_tab() == TAB_JSON:
            self._ensure_json()
        self.loaded.emit(load.path)

    def _on_failed(self, failure) -> None:
        self._loading_timer.stop()
        self._show_failure(str(failure.exception))

    def _show_failure(self, message: str) -> None:
        self._load = None
        self._error = message
        show_in_stack(self.stack, self.failure)
        self.retranslate()
        self.loaded.emit(self._path)

    def _apply_pending(self) -> None:
        pending, self._pending = self._pending, None
        if pending is None:
            return
        line, column, tab = pending
        if line is not None:
            self.go_to_line(line, column)
        if tab is not None:
            self.select_tab(tab)

    # --- árbol perezoso ------------------------------------------------------------------

    def _reset_tree(self) -> None:
        self.tree.clear()
        self._items.clear()
        self._populated.clear()
        self._matches, self._match_set, self._match_pos = [], set(), -1

    def _fill_tree(self, load: ClausewitzLoad) -> None:
        self.tree.setUpdatesEnabled(False)
        try:
            self._reset_tree()
            index = load.index
            self.tree.addTopLevelItems([self._make_item(node) for node in index.roots])
            if len(index) <= AUTO_EXPAND_LIMIT:
                self.expand_all()
        finally:
            self.tree.setUpdatesEnabled(True)
        if self.search_edit.text().strip():
            self._run_search(select=False)

    def _make_item(self, node: int) -> QTreeWidgetItem:
        index = self._load.index
        entry = index.entries[node]
        item = QTreeWidgetItem()
        item.setData(0, NODE_ROLE, node)
        item.setText(0, index.keys[node])
        item.setText(1, entry.op or "")
        item.setText(3, str(index.lines[node]) if index.lines[node] else "")
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
        item.setTextAlignment(3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for column in (0, 1, 2):
            item.setFont(column, self._mono)
        item.setForeground(0, theme.color("syntax_key" if entry.key is not None else "ink_muted"))
        item.setForeground(3, theme.color("ink_muted"))
        value = entry.value
        if isinstance(value, Scalar):
            item.setText(2, index.values[node])
            color = "syntax_string" if value.quoted else (
                "syntax_number" if value.is_number() or value.is_date() else
                "syntax_keyword" if value.text.lower() in ("yes", "no") else "ink")
            item.setForeground(2, theme.color(color))
        else:
            self._set_block_text(item, node)
            if index.children[node]:
                item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        severity = self._marks.get(node)
        if severity is not None:
            item.setIcon(0, severity_icon(severity))
        if node in self._match_set:
            self._paint_match(item, True)
        self._items[node] = item
        return item

    def _set_block_text(self, item: QTreeWidgetItem, node: int) -> None:
        index = self._load.index
        block = index.entries[node].value
        inline = index.values[node]
        if inline:
            text, color = inline, "ink"
        elif not block.entries:
            text, color = "{ }", "ink_muted"
        else:
            count = len(block.entries)
            text = tr("viewer.block_entries_one" if count == 1 else "viewer.block_entries", count=format_number(count))
            color = "ink_muted"
        if not block.is_closed:
            text = tr("viewer.block_unclosed", summary=text)
            color = "danger"
        item.setText(2, text)
        item.setForeground(2, theme.color(color))

    def _populate(self, node: int) -> None:
        if node in self._populated:
            return
        self._populated.add(node)
        children = self._load.index.children[node]
        if children:
            self._items[node].addChildren([self._make_item(child) for child in children])

    def _ensure_item(self, node: int) -> QTreeWidgetItem:
        for ancestor in self._load.index.chain(node)[:-1]:
            self._populate(ancestor)
        return self._items[node]

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        node = self.node_of_item(item)
        if node is not None and self._load is not None:
            self.tree.setUpdatesEnabled(False)
            try:
                self._populate(node)
            finally:
                self.tree.setUpdatesEnabled(True)

    def _on_current_item_changed(self, current: QTreeWidgetItem | None, previous) -> None:
        # Seleccionar un nodo lleva el cursor del código a su línea (sin cambiar de pestaña).
        node = self.node_of_item(current)
        if self._syncing or node is None or self._load is None:
            return
        line = self._load.index.lines[node]
        if line:
            self.code.go_to_line(line)

    def _show_tree_menu(self, pos: QPoint) -> None:
        item = self.tree.itemAt(pos)
        node = self.node_of_item(item)
        if node is None or self._load is None:
            return
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        line = self._load.index.lines[node]
        go = QAction(make_icon("file_code", "cream"), tr("viewer.menu.go_to_source"), menu)
        go.setEnabled(bool(line))
        go.triggered.connect(lambda: self.go_to_line(line))
        copy = QAction(make_icon("copy", "cream"), tr("viewer.menu.copy_path"), menu)
        path = " > ".join(self._load.index.key_path(node))
        copy.triggered.connect(lambda: QGuiApplication.clipboard().setText(path))
        menu.addAction(go)
        menu.addAction(copy)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # --- búsqueda ------------------------------------------------------------------------

    def _paint_match(self, item: QTreeWidgetItem, on: bool) -> None:
        for column in range(4):
            if on:
                item.setBackground(column, self._match_brush)
            else:
                item.setData(column, Qt.ItemDataRole.BackgroundRole, None)

    def _run_search(self, select: bool = True) -> None:
        for node in self._match_set:
            item = self._items.get(node)
            if item is not None:
                self._paint_match(item, False)
        needle = self.search_edit.text().strip().casefold()
        load = self.current_load()
        if not needle or load is None:
            self._matches, self._match_set, self._match_pos = [], set(), -1
        else:
            self._matches = [i for i, text in enumerate(load.index.haystack) if needle in text]
            self._match_set = set(self._matches)
            self._match_pos = -1
            for node in self._matches:
                item = self._items.get(node)
                if item is not None:
                    self._paint_match(item, True)
            if select and self._matches:
                self._go_to_match(0)
        self._retranslate_matches()

    def _go_to_match(self, position: int) -> None:
        self._match_pos = position
        self.reveal_node(self._matches[position])
        line = self._load.index.lines[self._matches[position]]
        if line:
            self.code.go_to_line(line)
        self._retranslate_matches()

    # --- JSON ----------------------------------------------------------------------------

    def _on_tab_changed(self, index: int) -> None:
        app_settings().setValue(SETTINGS_TAB, TABS[index])
        if TABS[index] == TAB_JSON:
            self._ensure_json()

    def _ensure_json(self) -> None:
        load = self.current_load()
        if load is None or self._json_for is load or self._json_runner.is_busy():
            return
        self._json_for = load
        self.json_view.clear()
        self.json_note.setVisible(False)
        document = load.result.document
        self._json_runner.start(lambda ctx: json_text(document))

    def _on_json_ready(self, text: str) -> None:
        if len(text) > JSON_DISPLAY_LIMIT:
            self._json_note = (N_("viewer.json_truncated"), {
                "shown": format_size(JSON_DISPLAY_LIMIT), "total": format_size(len(text.encode("utf-8")))})
            text = text[:JSON_DISPLAY_LIMIT]
        else:
            self._json_note = None
        self.json_view.setPlainText(text)
        self._retranslate_json_note()

    def _on_json_failed(self, failure) -> None:
        self._json_for = None
        self._json_note = (N_("viewer.json_failed"), {"error": str(failure)})
        self._retranslate_json_note()

    # --- textos --------------------------------------------------------------------------

    def _details(self) -> str:
        path = self._path
        if path is None:
            return ""
        shown = path.as_posix()
        if self._root is not None:
            try:
                shown = path.relative_to(self._root).as_posix()
            except ValueError:
                pass
        load = self.current_load()
        if load is None:
            return tr("viewer.details_loading", path=shown)
        encoding = load.result.encoding
        return tr("viewer.details", path=shown, encoding=ENCODING_NAMES.get(encoding, encoding),
                  lines=format_number(load.lines), size=format_size(load.size))

    def _retranslate_header(self) -> None:
        self.header.set_details(self._details())
        load = self.current_load()
        if load is None:
            self.header.set_summary(None)
            return
        counts = self.diagnostics_model.counts()
        self.header.set_summary(*summary_status(counts["error"], counts["warning"], counts["info"]))

    def _retranslate_matches(self) -> None:
        if not self.search_edit.text().strip() or self.current_load() is None:
            self.match_label.setText("")
        elif not self._matches:
            self.match_label.setText(tr("viewer.search_none"))
        else:
            self.match_label.setText(tr("viewer.search_count", current=format_number(self._match_pos + 1),
                                        total=format_number(len(self._matches))))

    def _retranslate_json_note(self) -> None:
        if self._json_note is None:
            self.json_note.setVisible(False)
            self.json_note.setText("")
        else:
            key, fmt = self._json_note
            self.json_note.setText(rich(tr(key, **fmt), 9))
            self.json_note.setVisible(True)

    def retranslate(self) -> None:
        counts = self.diagnostics_model.counts()
        total = sum(counts.values())
        for i, tab in enumerate(TABS):
            text = tr(self.TAB_KEYS[tab])
            if tab == TAB_DIAGNOSTICS and total:
                text = tr("viewer.tab.diagnostics_count", count=format_number(total))
            self.tabs.setTabText(i, text)
        worst = next((s for s in ("error", "warning") if counts[s]), None)
        load = self.current_load()
        icon = severity_icon(worst) if worst else make_icon("check", "success") if load is not None else QIcon()
        self.tabs.setTabIcon(TABS.index(TAB_DIAGNOSTICS), icon)
        self.tree.setHeaderLabels([tr(key) for key in self.TREE_HEADER_KEYS])
        self.search_edit.setPlaceholderText(tr("viewer.search_placeholder"))
        self.search_edit.setToolTip(tr("viewer.search_tooltip"))
        self.previous_action.setText(tr("viewer.previous_match"))
        self.previous_action.setToolTip(tr("viewer.previous_match_tooltip"))
        self.next_action.setText(tr("viewer.next_match"))
        self.next_action.setToolTip(tr("viewer.next_match_tooltip"))
        self.expand_button.setToolTip(tr("viewer.expand_all"))
        self.collapse_button.setToolTip(tr("viewer.collapse_all"))
        self.loading_label.setText(tr("viewer.loading"))
        self.failure.set_texts(tr("viewer.failed_title"), tr("viewer.failed_text", error=self._error or ""))
        self.diagnostics_hint.setText(tr("viewer.diagnostics_hint"))
        self.diagnostics_view.setToolTip(tr("viewer.diagnostics_hint"))
        self.diagnostics_empty.set_texts(tr("viewer.no_diagnostics_title"), tr("viewer.no_diagnostics_text"))
        self.diagnostics_model.retranslate()
        self.json_caption.setText(rich(tr("viewer.json_caption"), 9))
        self.json_view.setPlaceholderText(tr("viewer.json_pending"))
        self._retranslate_json_note()
        self._retranslate_matches()
        self._retranslate_header()
        if load is not None:
            for node, item in self._items.items():
                if load.index.children[node] is not None:
                    self._set_block_text(item, node)
