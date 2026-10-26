"""Visor de scripts Clausewitz: estructura, código fuente, diagnósticos y JSON.

El análisis (``load_clausewitz``) corre en un hilo: parsea, reconstruye el texto
exacto con ``to_source``, aplana el árbol en un índice en preorden, asigna cada
diagnóstico a su línea y a su entrada y prepara el documento del código fuente.
La interfaz no crea nada por entrada: la Estructura es un modelo sobre el índice
(``StructureModel``) del que la vista solo pide las filas que maqueta y pinta, y
el código se cuelga ya preparado al mostrar su pestaña. El JSON se genera también
en segundo plano, al abrir su pestaña y solo hasta lo que se muestra.

Volver a abrir un archivo que cambió en disco (o ``reload_if_changed``) lo
analiza de nuevo; si no cambió, se reutiliza el análisis. Uno que no se pudo leer
se reintenta siempre (un permiso arreglado no cambia la fecha ni el tamaño).
"""

from __future__ import annotations

import bisect
import os
from array import array
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Callable, Iterator

from PySide6.QtCore import QAbstractItemModel, QEvent, QModelIndex, QObject, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QKeySequence, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QStackedWidget,
    QStyledItemDelegate,
    QTabWidget,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ...core.cancel import CancelCheck, raise_if_cancelled
from ...core.clausewitz import Block, ParseResult, Scalar, iter_json, parse_file, to_json, to_source
from ...core.encoding import GAME_UNREADABLE
from ...core.modcheck import CLAUSEWITZ_SUFFIXES
from ...i18n import N_, tr
from ...settings import app_settings
from .. import theme
from ..tasks import TaskRunner, release_in_background
from ..widgets import EmptyState, make_icon, rich, show_in_stack
from .code_view import CodeView, TextView, display_text, string_continuations
from .common import LOADING_DELAY_MS, SEVERITY_RANK, ViewerHeader, describe_os_error, file_stamp, format_number, \
    format_size, severity_icon, severity_name, summary_status
from .diagnostics import DiagnosticRow, DiagnosticsModel, DiagnosticsView, column_width

__all__ = [
    "CLAUSEWITZ_SUFFIXES", "ClausewitzLoad", "ClausewitzViewer", "StructureIndex", "StructureModel", "build_index",
    "dismantle_load", "file_stamp", "json_chunks", "json_preview", "load_clausewitz",
]

TAB_STRUCTURE, TAB_SOURCE, TAB_DIAGNOSTICS, TAB_JSON = "structure", "source", "diagnostics", "json"
TABS = (TAB_STRUCTURE, TAB_SOURCE, TAB_DIAGNOSTICS, TAB_JSON)
SETTINGS_TAB = "viewer/clausewitz_tab"
AUTO_EXPAND_LIMIT = 400        # entradas: por debajo, el árbol se abre entero al cargar
# Cada maquetación completa del árbol pregunta a Python por cada fila visible (raíces entregadas y
# ramas abiertas); con una tarea en marcha, cada pregunta espera además su turno del GIL.
EXPAND_ALL_LIMIT = 5_000       # filas visibles como mucho tras «expandir todo»
ROOT_BATCH = 1_000             # raíces del primer lote; cada lote siguiente dobla las ya entregadas
JSON_DISPLAY_LIMIT = 2_000_000  # caracteres de JSON que se muestran como mucho
INLINE_LIST_LIMIT = 60          # una lista de escalares más corta se muestra en línea
SEARCH_DELAY_MS = 150
LINE_SAMPLE = "0000000"         # números de línea que caben en la columna Línea
RELEASE_CHUNK = 4096            # elementos que se sueltan de una vez al desmontar un análisis viejo
ENCODING_NAMES = {
    "cp1252": "Windows-1252", "utf-8": "UTF-8", "utf-8-sig": "UTF-8 BOM", "utf-16": "UTF-16 LE BOM",
    "utf-16-be-bom": "UTF-16 BE BOM", "utf-16-le": "UTF-16 LE", "utf-16-be": "UTF-16 BE",
}

_UNBOUNDED = (1 << 63) - 1      # fin de un bloque sin cerrar: llega hasta el final del archivo


# --- análisis en segundo plano (no toca widgets) -------------------------------------------

def _position(line: int, column: int) -> int:
    """(línea, columna) como un entero que se ordena igual."""
    return (line << 32) | column


def _scalar_display(scalar: Scalar) -> str:
    return f'"{scalar.text}"' if scalar.quoted else scalar.text


@dataclass
class StructureIndex:
    """Árbol aplanado en preorden; ``children[i]`` es ``None`` si la entrada ``i`` es escalar.

    ``rows[i]`` es la posición de ``i`` entre sus hermanos. ``starts[i]`` y ``ends[i]``
    (ver ``_position``) delimitan la entrada: de su primer token a la ``}`` de su bloque
    (el final del archivo si no se cierra) o, si es escalar, al último carácter de su
    valor. Lo que queda entre entradas (comentarios, una ``}`` sobrante...) es del bloque
    que las contiene.
    """

    entries: list = field(default_factory=list)
    parents: list[int] = field(default_factory=list)
    children: list[list[int] | None] = field(default_factory=list)
    roots: list[int] = field(default_factory=list)
    rows: list[int] = field(default_factory=list)
    lines: list[int] = field(default_factory=list)
    columns: list[int] = field(default_factory=list)
    starts: array = field(default_factory=lambda: array("q"))
    ends: array = field(default_factory=lambda: array("q"))
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

    def node_at(self, line: int | None, column: int | None = None) -> int | None:
        """Entrada más profunda que contiene esa posición; sin ``column``, la primera que empieza en ``line``.

        Una ``}`` sobrante, o un error fuera de todo bloque, no pertenece a ninguna: ``None``.
        """
        if line is None or not self.starts:
            return None
        if column is None:
            first = bisect.bisect_left(self.starts, _position(line, 0))
            if first < len(self.starts) and self.lines[first] == line:
                return first
            column = 0
        target = _position(line, column)
        node = bisect.bisect_right(self.starts, target) - 1
        while node >= 0 and self.ends[node] < target:
            node = self.parents[node]
        return node if node >= 0 else None

    def expansion(self, limit: int, roots: int) -> tuple[list[int], int]:
        """``(ramas, raíces)`` de «expandir todo»: las ramas que abre, en orden de documento, sin
        pasar de ``limit`` filas visibles, y cuántas raíces tiene que tener la vista para mostrarlas.

        La vista ya tiene las ``roots`` primeras raíces; cada raíz más que haga falta
        entregar cuenta también como una fila. Se para en la primera rama que no cabe,
        así que lo abierto es siempre el principio. La primera rama se abre aunque no
        quepa, como al abrirla a mano: si no, un archivo con un único bloque enorme (las
        decisiones, por ejemplo) no se abriría nada.
        """
        children, parents, rows = self.children, self.parents, self.rows
        visible = roots
        opened = []
        # Preorden por las ramas: de cada lista de hermanos, solo las entradas con hijos.
        stack = [filter(children.__getitem__, self.roots)]
        while stack:
            for node in stack[-1]:
                fetch = max(0, rows[node] + 1 - roots) if parents[node] < 0 else 0
                cost = fetch + len(children[node])
                if opened and visible + cost > limit:
                    return opened, roots
                visible += cost
                roots += fetch
                opened.append(node)
                stack.append(filter(children.__getitem__, children[node]))
                break
            else:
                stack.pop()
        return opened, roots


def build_index(block: Block, cancelled: CancelCheck = None) -> StructureIndex:
    index = StructureIndex()
    entries, parents, children, ends = index.entries, index.parents, index.children, index.ends
    stack = [(-1, iter(enumerate(block.entries)))]
    while stack:
        parent, iterator = stack[-1]
        for position, entry in iterator:
            node = len(entries)
            if not node & 0xFFFF:
                raise_if_cancelled(cancelled)
            entries.append(entry)
            parents.append(parent)
            index.rows.append(position)
            (index.roots if parent < 0 else children[parent]).append(node)
            line, column = entry.line or 0, entry.column or 0
            start = _position(line, column)
            index.lines.append(line)
            index.columns.append(column)
            index.starts.append(start)
            key = entry.key.text if entry.key is not None else f"[{position}]"
            value = entry.value
            if isinstance(value, Scalar):
                shown = _scalar_display(value)
                children.append(None)
                # Un valor creado o cambiado por código no tiene posición propia: acaba donde empieza la entrada.
                end = entry.value_end
                ends.append(start if end is None else _position(*end))
            else:
                shown = ""
                if value.entries and all(e.key is None and isinstance(e.value, Scalar) for e in value.entries):
                    inline = " ".join(_scalar_display(e.value) for e in value.entries)
                    if len(inline) <= INLINE_LIST_LIMIT:
                        shown = "{ " + inline + " }"
                children.append([])
                close = value.close_position
                ends.append(_UNBOUNDED if close is None else _position(*close))
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
    stamp: tuple[int, int]  # ``file_stamp`` antes de leerlo
    rows: list[DiagnosticRow] = field(default_factory=list)
    markers: dict[int, str] = field(default_factory=dict)  # línea -> peor gravedad
    marks: dict[int, str] = field(default_factory=dict)    # entrada -> peor gravedad
    continuations: frozenset[int] = frozenset()
    document: QTextDocument | None = None  # código fuente ya preparado para ``CodeView``


def _diagnostic_views(result: ParseResult, path: Path, index: StructureIndex):
    """Filas de la tabla y la peor gravedad por línea (código) y por entrada (estructura)."""
    rows, markers, marks = [], {}, {}
    for diagnostic in result.diagnostics:
        severity = severity_name(diagnostic.severity)
        rows.append(DiagnosticRow.of(diagnostic, path))
        node = index.node_at(diagnostic.line, diagnostic.column)
        for target, key in ((markers, diagnostic.line), (marks, node)):
            if key is not None and SEVERITY_RANK[severity] < SEVERITY_RANK.get(target.get(key), 9):
                target[key] = severity
    return rows, markers, marks


def load_clausewitz(path: str | os.PathLike, make_document: Callable[..., QTextDocument] | None = None,
                    cancelled: CancelCheck = None) -> ClausewitzLoad:
    """Parsea ``path`` y prepara todo lo que la interfaz necesita (se ejecuta en un hilo).

    ``make_document`` (``TextView.document_factory``) prepara además el documento del código.
    """
    path = Path(path)
    stat = path.stat()  # antes de leer: si el archivo cambia mientras, la próxima apertura lo relee
    result = parse_file(path, cancelled=cancelled)
    text = display_text(to_source(result.document))
    raise_if_cancelled(cancelled)
    lines = text.count("\n") + (0 if not text or text.endswith("\n") else 1)
    index = build_index(result.document, cancelled)
    rows, markers, marks = _diagnostic_views(result, path, index)
    continuations = string_continuations(text)
    document = make_document(text, cancelled) if make_document is not None else None
    return ClausewitzLoad(path, result, text, stat.st_size, lines, index, (stat.st_mtime_ns, stat.st_size), rows,
                          markers, marks, continuations, document)


@dataclass
class ClausewitzFailure:
    """El archivo no se pudo leer (el contenido nunca hace fallar al parser).

    Lleva la excepción y no su texto: ``describe_os_error`` la explica en el idioma de cada momento.
    """

    path: Path
    error: OSError
    stamp: tuple[int, int] | None = None  # ``file_stamp`` antes de intentarlo


def _drain(items) -> Iterator[None]:
    """Vacía la lista o el diccionario ``items`` de ``RELEASE_CHUNK`` en ``RELEASE_CHUNK`` elementos, por pasos."""
    if isinstance(items, list):
        while items:
            del items[-RELEASE_CHUNK:]
            yield
    elif isinstance(items, dict):
        while items:
            for _ in range(min(len(items), RELEASE_CHUNK)):
                items.popitem()
            yield


def dismantle_load(load: ClausewitzLoad) -> Iterator[None]:
    """Desmonta por pasos un análisis que ya no usa nadie (``release_in_background`` los recorre).

    Soltar la raíz del árbol del parser liberaría millones de nodos en una sola cascada. Pero
    ``index.entries`` retiene cada entrada: sin la raíz, vaciarla en preorden suelta en cada paso
    unas pocas entradas, con sus tokens y sus bloques, mientras sus hijos siguen retenidos por la
    lista hasta su propio paso. El resto del índice y las filas de diagnósticos son listas planas.
    Su ``document`` (de Qt) ya no puede estar: o lo tiene la vista o se soltó en el hilo de la interfaz.
    """
    index = load.index
    load.result = None  # la raíz y la lista de diagnósticos (sus filas aún los retienen)
    yield
    index.entries.reverse()  # se vacía desde el final: así sale primero el principio del preorden
    for item in fields(index):
        yield from _drain(getattr(index, item.name))
    for items in (load.rows, load.markers, load.marks):
        yield from _drain(items)


def try_load_clausewitz(path: str | os.PathLike, make_document: Callable[..., QTextDocument] | None = None,
                        cancelled: CancelCheck = None) -> ClausewitzLoad | ClausewitzFailure:
    stamp = file_stamp(path)
    try:
        return load_clausewitz(path, make_document, cancelled)
    except OSError as exc:
        return ClausewitzFailure(Path(path), exc, stamp)


class _LazyEntries(list):
    """Entradas de primer nivel que ``iter_json`` recorre como una lista y ``to_json`` convierte al llegar a ellas."""

    __slots__ = ("entries",)

    def __init__(self, entries: list):
        super().__init__()
        self.entries = entries

    def __bool__(self) -> bool:
        return bool(self.entries)

    def __iter__(self):
        return map(to_json, self.entries)


def json_chunks(document: Block) -> Iterator[str]:
    """``json.dumps(to_json(document), ensure_ascii=False, indent=2)`` por trozos.

    Sin recursión, y cada entrada de primer nivel se convierte solo al llegar a ella.
    """
    root = to_json(Block())
    root["entries"] = _LazyEntries(document.entries)
    return iter_json(root)


def json_preview(document: Block, limit: int = JSON_DISPLAY_LIMIT, cancelled: CancelCheck = None) -> tuple[str, bool]:
    """``(texto, recortado)``: el JSON de ``document`` si cabe en ``limit`` caracteres; si no, su
    principio hasta el último salto de línea que cabe."""
    parts, size = [], 0
    for count, chunk in enumerate(json_chunks(document)):
        if not count & 0xFFF:
            raise_if_cancelled(cancelled)
        parts.append(chunk)
        size += len(chunk)
        if size > limit:
            text = "".join(parts)[:limit]
            cut = text.rfind("\n")
            return (text[:cut] if cut > 0 else text), True
    return "".join(parts), False


def _prepare_json(document: Block, make_document: Callable[..., QTextDocument], cancelled: CancelCheck):
    """(documento para la vista JSON, bytes UTF-8 mostrados, recortado)."""
    text, truncated = json_preview(document, JSON_DISPLAY_LIMIT, cancelled)
    return make_document(text, cancelled), len(text.encode("utf-8")), truncated


# --- modelo de la estructura ---------------------------------------------------------------

class StructureModel(QAbstractItemModel):
    """Estructura de solo lectura sobre un ``StructureIndex``: no crea nada por entrada.

    La vista pide solo las filas que maqueta y pinta, pero cada maquetación completa
    recorre todas las raíces entregadas llamando a Python. Por eso las raíces se
    entregan por lotes (``fetch_more_roots``), cada uno del doble que el anterior,
    cuando la vista llega al final; los hijos de una rama, enteros al expandirla. No
    se usa ``canFetchMore``: QTreeView pide otro lote en cada maquetación completa y
    acabaría entregándolas todas. Tampoco se reimplementa ``flags``: cada método en
    Python que la vista llama por fila encarece la maquetación. Los textos se
    traducen al pintarlos: un cambio de idioma solo pide repintar la vista.
    """

    COLUMNS = 4
    HEADER_KEYS = (N_("viewer.col.key"), N_("viewer.col.op"), N_("viewer.col.value"), N_("viewer.col.line"))

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._index = StructureIndex()
        self._marks: dict[int, str] = {}
        self._matches: frozenset[int] = frozenset()
        self._fetched = 0
        self._mono = theme.font("mono")

    def set_index(self, index: StructureIndex, marks: dict[int, str]) -> None:
        """Muestra ``index``; ``marks`` es la peor gravedad de los diagnósticos de cada entrada."""
        self.beginResetModel()
        self._index, self._marks, self._matches = index, marks, frozenset()
        self._fetched = min(len(index.roots), ROOT_BATCH)
        self.endResetModel()

    def set_matches(self, nodes) -> None:
        self._matches = frozenset(nodes)

    def is_match(self, index: QModelIndex) -> bool:
        return index.isValid() and index.internalId() in self._matches

    def node_of(self, index: QModelIndex) -> int | None:
        return index.internalId() if index.isValid() else None

    def index_of(self, node: int, column: int = 0) -> QModelIndex:
        """Índice de la entrada ``node``; entrega antes su raíz si aún no lo estaba."""
        if self._fetched < len(self._index.roots):
            root = self._index.rows[self._index.chain(node)[0]]
            if root >= self._fetched:
                self.fetch_roots(max(root + 1, 2 * self._fetched))
        return self.createIndex(self._index.rows[node], column, node)

    def has_more_roots(self) -> bool:
        return self._fetched < len(self._index.roots)

    def fetch_more_roots(self) -> None:
        self.fetch_roots(self._fetched + max(ROOT_BATCH, self._fetched))

    def fetch_roots(self, count: int) -> None:
        """Entrega a la vista las ``count`` primeras raíces, si aún no las tiene."""
        count = min(count, len(self._index.roots))
        if count > self._fetched:
            self.beginInsertRows(QModelIndex(), self._fetched, count - 1)
            self._fetched = count
            self.endInsertRows()

    # --- QAbstractItemModel --------------------------------------------------------------

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if row < 0 or not 0 <= column < self.COLUMNS:
            return QModelIndex()
        if parent.isValid():
            siblings = self._index.children[parent.internalId()] if parent.column() == 0 else None
            if not siblings or row >= len(siblings):
                return QModelIndex()
        elif row < self._fetched:
            siblings = self._index.roots
        else:
            return QModelIndex()
        return self.createIndex(row, column, siblings[row])

    def parent(self, child: QModelIndex | None = None):
        if child is None:
            return super().parent()  # QObject.parent()
        if not child.isValid():
            return QModelIndex()
        parent = self._index.parents[child.internalId()]
        return QModelIndex() if parent < 0 else self.createIndex(self._index.rows[parent], 0, parent)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if not parent.isValid():
            return self._fetched
        children = self._index.children[parent.internalId()] if parent.column() == 0 else None
        return len(children) if children else 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return self.COLUMNS

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:
        if not parent.isValid():
            return bool(self._index.roots)
        return parent.column() == 0 and bool(self._index.children[parent.internalId()])

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole \
                and 0 <= section < self.COLUMNS:
            return tr(self.HEADER_KEYS[section])
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node, column = index.internalId(), index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return self._text(node, column)
        if role == Qt.ItemDataRole.ForegroundRole:
            color = self._color(node, column)
            return theme.color(color) if color else None
        if role == Qt.ItemDataRole.FontRole:
            return self._mono if column < 3 else None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column == 1:
                return int(Qt.AlignmentFlag.AlignCenter)
            if column == 3:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return None
        if role == Qt.ItemDataRole.DecorationRole and column == 0:
            severity = self._marks.get(node)
            return severity_icon(severity) if severity is not None else None
        return None

    def _text(self, node: int, column: int) -> str:
        index = self._index
        if column == 0:
            return index.keys[node]
        if column == 1:
            return index.entries[node].op or ""
        if column == 3:
            return str(index.lines[node]) if index.lines[node] else ""
        value = index.entries[node].value
        text = index.values[node]
        if isinstance(value, Scalar):
            return text
        if not text:
            count = len(value.entries)
            text = "{ }" if not count else tr("viewer.block_entries_one" if count == 1 else "viewer.block_entries",
                                               count=format_number(count))
        return text if value.is_closed else tr("viewer.block_unclosed", summary=text)

    def _color(self, node: int, column: int) -> str | None:
        entry = self._index.entries[node]
        if column == 0:
            return "syntax_key" if entry.key is not None else "ink_muted"
        if column == 3:
            return "ink_muted"
        if column == 1:
            return None
        value = entry.value
        if isinstance(value, Scalar):
            return "syntax_string" if value.quoted else (
                "syntax_number" if value.is_number() or value.is_date() else
                "syntax_keyword" if value.text.lower() in ("yes", "no") else "ink")
        if not value.is_closed:
            return "danger"
        return "ink" if self._index.values[node] else "ink_muted"


class _MatchDelegate(QStyledItemDelegate):
    """Fondo dorado en las coincidencias de la búsqueda (la hoja de estilo ignora ``BackgroundRole``)."""

    def __init__(self, model: StructureModel, parent: QObject | None = None):
        super().__init__(parent)
        self._model = model
        self._brush = QColor(201, 162, 74, 120)

    def paint(self, painter, option, index) -> None:
        if self._model.is_match(index):
            painter.fillRect(option.rect, self._brush)
        super().paint(painter, option, index)


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

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("clausewitzViewer")
        self._path: Path | None = None
        self._root: Path | None = None
        self._load: ClausewitzLoad | None = None
        self._error: BaseException | None = None  # por qué no se pudo leer el archivo
        self._failed_stamp: tuple[int, int] | None = None  # ``file_stamp`` del intento fallido
        self._pending: tuple[int | None, int | None, str | None] | None = None
        self._matches: list[int] = []
        self._match_pos = -1
        self._syncing = False
        self._compact = False
        self._json_for: ClausewitzLoad | None = None
        self._json_note: Callable[[], str] | None = None
        self._json_failed = False

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
        # Si no caben, se recortan los textos antes de recurrir a las flechas de desplazamiento.
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
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
        self._loading_timer.timeout.connect(self._show_loading)
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

        self.structure_model = StructureModel(self)
        self.tree = QTreeView()
        self.tree.setObjectName("structureTree")
        self.tree.setModel(self.structure_model)
        self.tree.setItemDelegate(_MatchDelegate(self.structure_model, self.tree))
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setAnimated(False)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_tree_menu)
        self.tree.selectionModel().currentChanged.connect(self._on_current_changed)
        self.tree.verticalScrollBar().valueChanged.connect(self._on_tree_scrolled)
        self.collapse_button.clicked.connect(self.tree.collapseAll)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 230)
        header.resizeSection(1, 40)
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
        self.json_view = TextView()
        self.json_view.setObjectName("jsonView")
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
        """El análisis a la vista. Cuando el visor deja de mostrarlo lo vacía en segundo plano (``_release``):
        quien quiera conservar algo de él, que lo copie antes."""
        return self._load if self._load is not None and self._load.path == self._path else None

    def is_busy(self) -> bool:
        return self._runner.is_busy() or self._json_runner.is_busy()

    def failure_text(self) -> str:
        """Por qué no se pudo leer el archivo abierto, en el idioma actual (vacío si se leyó)."""
        error = self._error
        if error is None:
            return ""
        # Un OSError se explica por su tipo (su texto es el de la libc, en inglés); otro fallo es un error interno.
        return describe_os_error(error)[0] if isinstance(error, OSError) else f"{type(error).__name__}: {error}"

    def load(self, path: str | os.PathLike, *, root: Path | None = None, line: int | None = None,
             column: int | None = None, tab: str | None = None) -> None:
        """Analiza ``path`` en segundo plano; ``line``/``tab`` se aplican al terminar.

        Si ya está abierto y no ha cambiado en disco, reutiliza el análisis.
        """
        path = Path(path)
        if tab is not None and tab not in TABS:
            raise ValueError(f"pestaña desconocida: {tab!r}")
        pending = (line, column, tab) if (line is not None or tab is not None) else None
        self._root = root
        if path == self._path:
            if self._runner.is_busy():
                # La carga en curso aplicará lo pendiente; pedir el archivo sin línea no anula la de antes.
                self._pending = pending or self._pending
                self._retranslate_header()  # la raíz puede ser otra
                return
            load = self.current_load()
            if load is not None and load.stamp == file_stamp(path):
                self._pending = pending
                self._retranslate_header()
                self._apply_pending()
                if self.current_tab() == TAB_JSON:
                    self._ensure_json()  # ``cancel()`` pudo dejarlo a medias
                return
        if path != self._path:
            self._error = None  # reintentar un fallo lo deja a la vista hasta que haya respuesta (``_show_loading``)
        self._pending = pending
        self._path = path
        self._json_runner.cancel()
        self.header.set_file(path, self._details(), self._shown_path())
        self.header.set_summary(None)
        self._retranslate_header()
        make_document = self.code.document_factory()
        self._runner.start(lambda ctx: try_load_clausewitz(path, make_document, ctx.cancelled))
        self._loading_timer.start()

    def reload_if_changed(self) -> bool:
        """Vuelve a analizar el archivo abierto si cambió en disco desde que se leyó; ``True`` si lo hace.

        Si no se pudo leer (``OSError``) lo reintenta siempre: arreglar un permiso o soltar un bloqueo no
        cambia la fecha ni el tamaño, y fallar otra vez cuesta poco. Un error interno, solo si cambió.
        """
        if self._path is None or self._runner.is_busy():
            return False
        load = self.current_load()
        if load is not None:
            stamp = load.stamp
        elif self._error is not None:
            stamp = self._failed_stamp
        else:
            return False
        if not isinstance(self._error, OSError) and stamp == file_stamp(self._path):
            return False
        self.load(self._path, root=self._root)
        return True

    def cancel(self) -> None:
        """Deja de generar el JSON, que nadie verá hasta volver a su pestaña (entonces se rehace).

        Conserva el análisis y deja seguir uno en curso: si es un reanálisis del archivo cargado, al
        volver ya está al día (CP-7); si es el primero, quien deja de mostrar el visor usa ``clear()``.
        """
        if self._json_runner.is_busy():
            self._json_runner.cancel()
            self._json_for = None

    def clear(self) -> None:
        self._runner.cancel()
        self._json_runner.cancel()
        self._loading_timer.stop()
        self._forget_load()
        self._path = None
        self._error = None
        self._json_note = None
        self._json_failed = False
        self.json_view.set_document(None)
        self.header.set_file(None)
        self.header.set_summary(None)
        show_in_stack(self.stack, self.tabs)
        self.retranslate()

    def select_tab(self, tab: str) -> None:
        self.tabs.setCurrentIndex(TABS.index(tab))

    def current_tab(self) -> str:
        return TABS[self.tabs.currentIndex()]

    def set_compact(self, compact: bool) -> None:
        """Oculta las líneas de ayuda cuando falta altura; pasan a ser ayudas emergentes."""
        self._compact = compact
        self.diagnostics_hint.setVisible(not compact)
        self.json_caption.setVisible(not compact)
        self._retranslate_json()

    def current_node(self) -> int | None:
        """Entrada seleccionada en la estructura."""
        return self.structure_model.node_of(self.tree.currentIndex())

    def go_to_line(self, line: int, column: int | None = None) -> bool:
        """Salta a ``line`` en el código fuente y selecciona la entrada que contiene esa posición."""
        load = self.current_load()
        if load is None:
            return False
        self._select_node(load.index.node_at(line, column))
        self.select_tab(TAB_SOURCE)
        return self.code.go_to_line(line, column)

    def show_diagnostic(self, row: DiagnosticRow) -> None:
        if row.line is not None:
            self.go_to_line(row.line, row.column)

    def reveal_node(self, node: int) -> QModelIndex:
        """Expande hasta el nodo ``node``, lo selecciona y lo centra, sin mover el código."""
        model = self.structure_model
        for ancestor in self._load.index.chain(node)[:-1]:
            self.tree.expand(model.index_of(ancestor))
        index = model.index_of(node)
        self._syncing = True
        try:
            self.tree.setCurrentIndex(index)
        finally:
            self._syncing = False
        self.tree.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        return index

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
        """Expande el árbol desde el principio sin pasar de ``EXPAND_ALL_LIMIT`` filas visibles.

        En un archivo pequeño lo abre entero; en uno grande, su principio: la vista
        maqueta cada fila visible preguntando a Python, y decenas de miles la congelarían.
        """
        load = self.current_load()
        if load is None:
            return
        model = self.structure_model
        opened, roots = load.index.expansion(EXPAND_ALL_LIMIT, model.rowCount())
        model.fetch_roots(roots)
        self.tree.scheduleDelayedItemsLayout()  # así cada expand() solo se apunta y se maqueta una vez
        for node in opened:
            self.tree.expand(model.index_of(node))

    # --- carga ---------------------------------------------------------------------------

    def _show_loading(self) -> None:
        """Pasados ``LOADING_DELAY_MS`` sin respuesta: un reintento que tarda ya no es el fallo de antes."""
        self._error = None
        show_in_stack(self.stack, self.loading)
        self._retranslate_header()

    def _on_loaded(self, load: ClausewitzLoad | ClausewitzFailure) -> None:
        self._loading_timer.stop()
        if isinstance(load, ClausewitzFailure):
            self._show_failure(load.error, load.stamp)
            return
        self._error = None
        old, self._load = self._load, load
        self._json_for = None
        self._json_note = None
        self._json_failed = False
        self.code.set_source(load.text, load.markers, continuations=load.continuations, document=load.document)
        load.document = None  # ya es de la vista
        self.diagnostics_model.set_rows(load.rows)
        show_in_stack(self.diagnostics_stack, self.diagnostics_view if load.rows else self.diagnostics_empty)
        self._fill_tree(load)
        self.json_view.set_document(None)
        self._release(old)  # ya no lo muestra nada
        show_in_stack(self.stack, self.tabs)
        self.retranslate()
        self._apply_pending()
        if self.current_tab() == TAB_JSON:
            self._ensure_json()
        self.loaded.emit(load.path)

    def _on_failed(self, failure) -> None:
        self._loading_timer.stop()
        self._show_failure(failure.exception, file_stamp(self._path))

    def _show_failure(self, error: BaseException, stamp: tuple[int, int] | None) -> None:
        self._forget_load()
        self._error = error
        self._failed_stamp = stamp
        show_in_stack(self.stack, self.failure)
        self.retranslate()
        self.loaded.emit(self._path)

    def _forget_load(self) -> None:
        """Vacía las vistas y suelta en segundo plano el análisis que mostraban."""
        old, self._load, self._json_for = self._load, None, None
        self._matches, self._match_pos = [], -1
        self.structure_model.set_index(StructureIndex(), {})
        self.diagnostics_model.set_rows([])
        self.code.clear_source()
        self._release(old)

    @staticmethod
    def _release(load: ClausewitzLoad | None) -> None:
        """Suelta ``load``, que ya no muestra nada, en el hilo de una tarea (``dismantle_load``).

        Con un archivo de 20 MB, soltarlo aquí paraba la interfaz ~0,9 s.
        """
        if load is not None:
            load.document = None  # de Qt: si aún lo tenía, se destruye aquí, en su hilo
            release_in_background(load, dismantle_load)

    def _apply_pending(self) -> None:
        pending, self._pending = self._pending, None
        if pending is None:
            return
        line, column, tab = pending
        if line is not None:
            self.go_to_line(line, column)
        if tab is not None:
            self.select_tab(tab)

    # --- estructura ----------------------------------------------------------------------

    def _fill_tree(self, load: ClausewitzLoad) -> None:
        self._matches, self._match_pos = [], -1
        self.structure_model.set_index(load.index, load.marks)
        if len(load.index) <= AUTO_EXPAND_LIMIT:
            self.tree.expandAll()
        if self.search_edit.text().strip():
            self._run_search(select=False)

    def _on_tree_scrolled(self, value: int) -> None:
        bar = self.tree.verticalScrollBar()
        if value >= bar.maximum() - bar.pageStep() and self.structure_model.has_more_roots():
            self.structure_model.fetch_more_roots()

    def _select_node(self, node: int | None) -> None:
        if node is not None:
            self.reveal_node(node)
            return
        self._syncing = True
        try:
            self.tree.selectionModel().clear()
        finally:
            self._syncing = False

    def _show_in_source(self, node: int) -> None:
        index = self._load.index
        self.select_tab(TAB_SOURCE)
        self.code.go_to_line(index.lines[node], index.columns[node] or None)

    def _on_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        # Seleccionar un nodo lleva el cursor del código a su clave (sin cambiar de pestaña).
        node = self.structure_model.node_of(current)
        if self._syncing or node is None or self._load is None:
            return
        index = self._load.index
        if index.lines[node]:
            self.code.go_to_line(index.lines[node], index.columns[node] or None)

    def tree_menu(self, node: int) -> QMenu:
        """Menú contextual de la entrada ``node``: ir a su clave en el código y copiar su ruta."""
        index = self._load.index
        menu = QMenu(self)
        go = QAction(make_icon("file_code", "cream"), tr("viewer.menu.go_to_source"), menu)
        go.setEnabled(bool(index.lines[node]))
        go.triggered.connect(lambda: self._show_in_source(node))
        copy = QAction(make_icon("copy", "cream"), tr("viewer.menu.copy_path"), menu)
        path = " > ".join(index.key_path(node))
        copy.triggered.connect(lambda: QGuiApplication.clipboard().setText(path))
        menu.addAction(go)
        menu.addAction(copy)
        return menu

    def _show_tree_menu(self, pos: QPoint) -> None:
        node = self.structure_model.node_of(self.tree.indexAt(pos))
        if node is None or self._load is None:
            return
        menu = self.tree_menu(node)
        menu.exec(self.tree.viewport().mapToGlobal(pos))
        menu.deleteLater()

    # --- búsqueda ------------------------------------------------------------------------

    def _run_search(self, select: bool = True) -> None:
        needle = self.search_edit.text().strip().casefold()
        load = self.current_load()
        self._match_pos = -1
        if not needle or load is None:
            self._matches = []
        else:
            self._matches = [i for i, text in enumerate(load.index.haystack) if needle in text]
        self.structure_model.set_matches(self._matches)
        self.tree.viewport().update()
        if select and self._matches:
            self._go_to_match(0)
        self._retranslate_matches()

    def _go_to_match(self, position: int) -> None:
        self._match_pos = position
        node = self._matches[position]
        self.reveal_node(node)
        index = self._load.index
        if index.lines[node]:
            self.code.go_to_line(index.lines[node], index.columns[node] or None)
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
        self._json_note = None
        self._json_failed = False
        self.json_view.set_document(None)
        self._retranslate_json()
        document = load.result.document
        make_document = self.json_view.document_factory()
        self._json_runner.start(lambda ctx: _prepare_json(document, make_document, ctx.cancelled))

    def _on_json_ready(self, result) -> None:
        document, size, truncated = result
        self._json_note = (lambda: tr("viewer.json_truncated", shown=format_size(size))) if truncated else None
        self.json_view.set_document(document)
        self._retranslate_json()

    def _on_json_failed(self, failure) -> None:
        self._json_for = None
        self._json_failed = True
        self._json_note = lambda: tr("viewer.json_failed", error=str(failure))
        self._retranslate_json()

    # --- textos --------------------------------------------------------------------------

    def _shown_path(self) -> str:
        path = self._path
        if path is None:
            return ""
        if self._root is not None:
            try:
                return path.relative_to(self._root).as_posix()
            except ValueError:
                pass
        return path.as_posix()

    def _details(self) -> str:
        if self._path is None:
            return ""
        shown = self._shown_path()
        if self._error is not None:
            return tr("viewer.details_failed", path=shown)
        load = self.current_load()
        if load is None:
            return tr("viewer.details_loading", path=shown)
        encoding = load.result.encoding
        name = ENCODING_NAMES.get(encoding, encoding)
        if encoding in GAME_UNREADABLE:
            name = tr("viewer.encoding_unreadable", encoding=name)
        return tr("viewer.details_one" if load.lines == 1 else "viewer.details", path=shown, encoding=name,
                  lines=format_number(load.lines), size=format_size(load.size))

    def _retranslate_failure(self) -> None:
        self.failure.set_texts(tr("viewer.failed_title"), tr("viewer.failed_text", error=self.failure_text()))
        # La ruta completa y el detalle del sistema (en inglés), en la ayuda emergente.
        error, tooltip = self._error, ""
        if isinstance(error, OSError) and self._path is not None:
            tooltip = tr("file_error.detail", path=os.fspath(self._path), detail=describe_os_error(error)[1])
        self.failure.setToolTip(tooltip)

    def _retranslate_header(self) -> None:
        self.header.set_details(self._details(), self._shown_path())
        load = self.current_load()
        if load is None:
            self.header.set_summary(None)
            return
        if load.result.encoding in GAME_UNREADABLE:  # nada de lo demás importa si el juego no puede leerlo
            self.header.set_summary("error", tr("viewer.summary_unreadable"))
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

    def _retranslate_json(self) -> None:
        caption = rich(tr("viewer.json_caption"), 9)
        self.json_caption.setText(caption)
        self.json_view.setToolTip(caption if self._compact else "")
        self.tabs.setTabToolTip(TABS.index(TAB_JSON), caption if self._compact else "")
        self.json_view.setPlaceholderText("" if self._json_failed else tr("viewer.json_pending"))
        if self._json_note is None:
            self.json_note.setVisible(False)
            self.json_note.setText("")
        else:
            self.json_note.setText(rich(self._json_note(), 9))
            self.json_note.setVisible(True)

    def retranslate(self) -> None:
        counts = self.diagnostics_model.counts()
        total = sum(counts.values())
        for i, tab in enumerate(TABS):
            text = tr(self.TAB_KEYS[tab])
            if tab == TAB_DIAGNOSTICS and total:
                text = tr("viewer.tab.diagnostics_count", count=format_number(total))
            self.tabs.setTabText(i, text)
        load = self.current_load()
        # Un archivo que el juego no puede leer es un error aunque el parser no encuentre nada (como en la cabecera).
        unreadable = load is not None and load.result.encoding in GAME_UNREADABLE
        worst = "error" if unreadable else next((s for s in ("error", "warning") if counts[s]), None)
        icon = severity_icon(worst) if worst else make_icon("check", "success") if load is not None else QIcon()
        self.tabs.setTabIcon(TABS.index(TAB_DIAGNOSTICS), icon)
        # Los textos del árbol y de su cabecera se piden al pintarlos: basta con repintar. Con
        # headerDataChanged o dataChanged, QTreeView volvería a maquetar todas las filas visibles.
        self.tree.header().viewport().update()
        self.tree.viewport().update()
        self.tree.header().resizeSection(3, column_width(self.tree, tr("viewer.col.line"), LINE_SAMPLE))
        self.search_edit.setPlaceholderText(tr("viewer.search_placeholder"))
        self.search_edit.setToolTip(tr("viewer.search_tooltip"))
        self.previous_action.setText(tr("viewer.previous_match"))
        self.previous_action.setToolTip(tr("viewer.previous_match_tooltip"))
        self.next_action.setText(tr("viewer.next_match"))
        self.next_action.setToolTip(tr("viewer.next_match_tooltip"))
        self.expand_button.setToolTip(tr("viewer.expand_all"))
        self.collapse_button.setToolTip(tr("viewer.collapse_all"))
        self.loading_label.setText(tr("viewer.loading"))
        self._retranslate_failure()
        self.diagnostics_hint.setText(tr("viewer.diagnostics_hint"))
        self.diagnostics_view.setToolTip(tr("viewer.diagnostics_hint"))
        if unreadable:
            encoding = load.result.encoding
            self.diagnostics_empty.set_texts(tr("viewer.summary_unreadable"), tr(
                "viewer.unreadable_text", encoding=ENCODING_NAMES.get(encoding, encoding)))
        else:
            self.diagnostics_empty.set_texts(tr("viewer.no_diagnostics_title"), tr("viewer.no_diagnostics_text"))
        self.diagnostics_empty.medallion.set_icon("error" if unreadable else "check")
        self.diagnostics_model.retranslate()
        self._retranslate_json()
        self._retranslate_matches()
        self._retranslate_header()
