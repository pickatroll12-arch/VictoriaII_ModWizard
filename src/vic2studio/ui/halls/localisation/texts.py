"""Textos › Todos los textos y Pendientes de traducir: la localización efectiva, editable (wizard §8, I7).

La tabla muestra ``LocSync.entries()``: cada clave que vería el juego con sus textos
en inglés, español, francés y alemán, su archivo ganador y su origen. Editar una
celda es ``Session.edit`` + ``LocSync.set_text`` (una transacción con nombre,
deshacible con Ctrl+Z); la política de dónde se escribe es la de ``LocSync`` (en su
sitio si gana el mod; en ``00_<P>_overrides.csv`` si gana el juego; nunca se copia
``text.csv``). «Añadir clave» crea una con ``LocSync.ensure`` en el archivo del área.

Filtros: «creadas por el Studio», «sin traducir» (a algún idioma del proyecto, solo
las del mod), «sustituyen a vanilla» y «degradadas» (H15), más un buscador por clave
o texto sin mayúsculas ni acentos. «Pendientes de traducir» es la misma página con el
filtro «sin traducir» puesto.

La tabla se rellena cuando ``Session.textsReady`` dice que los CSV del disco ya están
leídos (en segundo plano), y se refresca con ``textsChanged`` (ediciones, deshacer,
recargas) conservando la fila seleccionada. Ningún widget lee ni escribe archivos.
"""

from __future__ import annotations

from bisect import bisect_left

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ....core.csvloc import InvalidFieldError
from ....core.encoding import UnencodableTextError
from ....core.index.model import fold
from ....core.locsync import LocEntry
from ....core.project import ReadOnlyDocumentError
from ....core.vfs import LayerKind
from ....i18n import N_, tr
from ... import theme
from ...pages.base import BasePage
from ...viewers.common import core_language, format_number
from ...widgets import EmptyState, make_icon, mark_data, show_in_stack
from ...widgets.delegates import PathElideDelegate

FILTER_ALL, FILTER_STUDIO, FILTER_UNTRANSLATED, FILTER_OVERRIDES, FILTER_DEGRADED = (
    "all", "studio", "untranslated", "overrides", "degraded")
FILTERS = (
    (FILTER_ALL, N_("texts.filter.all")),
    (FILTER_STUDIO, N_("texts.filter.studio")),
    (FILTER_UNTRANSLATED, N_("texts.filter.untranslated")),
    (FILTER_OVERRIDES, N_("texts.filter.overrides")),
    (FILTER_DEGRADED, N_("texts.filter.degraded")),
)
COL_KEY, COL_FILE, COL_ORIGIN = "key", "file", "origin"
# Idiomas editables, en el orden de la tabla: los dos del proyecto por defecto y después los que también ve el juego.
LANGUAGE_COLUMNS = ("en", "es", "fr", "de")
EXTRA_LANGUAGES = ("fr", "de")
COLUMNS = (COL_KEY, *LANGUAGE_COLUMNS, COL_FILE, COL_ORIGIN)
HEADER_KEYS = {COL_KEY: N_("texts.col.key"), COL_FILE: N_("texts.col.file"), COL_ORIGIN: N_("texts.col.origin")}
ENDONYMS = {"en": "English", "es": "Español", "fr": "Français", "de": "Deutsch"}
ORIGIN_KEYS = {
    "game": N_("texts.origin.game"), "dependency": N_("texts.origin.dependency"), "mod": N_("texts.origin.mod"),
    "override": N_("texts.origin.override"),
}
ORIGIN_TOOLTIPS = {
    "game": N_("texts.origin.game_tooltip"), "dependency": N_("texts.origin.dependency_tooltip"),
    "mod": N_("texts.origin.mod_tooltip"), "override": N_("texts.origin.override_tooltip"),
}
HEADER_TOOLTIPS = {COL_KEY: N_("texts.col.key_tooltip"), COL_FILE: N_("texts.col.file_tooltip"),
                   COL_ORIGIN: N_("texts.col.origin_tooltip")}
ORIGIN_COLORS = {"game": "ink_soft", "dependency": "ink_soft", "mod": "success", "override": "warning"}
SEARCH_DELAY_MS = 150
LABEL_EDIT = N_("undo.texts_edit")
LABEL_ADD = N_("undo.texts_add_key")
ENTRY_ROLE = Qt.ItemDataRole.UserRole + 1
COLUMN_WIDTHS = {COL_KEY: 220, COL_FILE: 210, COL_ORIGIN: 130}   # los idiomas se reparten el resto
MIN_COLUMN_WIDTH = 100                                          # con francés y alemán a 1100 px


def origin_of(entry: LocEntry) -> str:
    if entry.layer is LayerKind.GAME:
        return "game"
    if entry.layer is LayerKind.DEPENDENCY:
        return "dependency"
    return "override" if entry.overrides_game else "mod"


class LocEntriesModel(QAbstractTableModel):
    """Las ``LocEntry`` efectivas; editables las columnas de idioma (``edit_requested`` con clave, idioma y texto).

    ``set_entries`` refresca sin reiniciar el modelo si las claves son las mismas (una edición en su sitio).
    """

    edit_requested = Signal(str, str, str)    # (clave, idioma, texto): quien escucha decide y escribe

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: list[LocEntry] = []
        self.editable = True
        self.languages: tuple[str, ...] = ("en", "es")
        self.pending_check = None             # función LocEntry → idiomas sin traducir
        self.prefix = ""                      # prefijo del proyecto (00_<prefijo>_*.csv)
        self._mono = theme.font("mono")
        self._accepted: bool | None = None

    def set_entries(self, entries: list[LocEntry]) -> bool:
        """Sustituye las filas; True si cambió el conjunto de claves (se reinició el modelo)."""
        same = len(entries) == len(self.entries) and all(a.key == b.key for a, b in zip(entries, self.entries))
        if same:
            self.entries = entries
            if entries:
                self.dataChanged.emit(self.index(0, 0), self.index(len(entries) - 1, len(COLUMNS) - 1))
            return False
        self.beginResetModel()
        self.entries = entries
        self.endResetModel()
        return True

    def update_entry(self, entry: LocEntry) -> bool:
        """Refresca la fila de ``entry.key`` (tras una edición propia); False si no está."""
        for row, current in enumerate(self.entries):
            if current.key == entry.key:
                self.entries[row] = entry
                self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))
                return True
        return False

    def row_of(self, key: str) -> int | None:
        return next((row for row, entry in enumerate(self.entries) if entry.key == key), None)

    def retranslate(self) -> None:
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(COLUMNS) - 1)
        if self.entries:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.entries) - 1, len(COLUMNS) - 1))

    # --- QAbstractTableModel ---------------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal or not 0 <= section < len(COLUMNS):
            return None
        column = COLUMNS[section]
        if role == Qt.ItemDataRole.DisplayRole:
            return ENDONYMS[column] if column in ENDONYMS else tr(HEADER_KEYS[column])
        if role == Qt.ItemDataRole.ToolTipRole:
            if column in ENDONYMS:
                return tr("texts.col.lang_tooltip", language=ENDONYMS[column])
            return tr(HEADER_TOOLTIPS[column])
        return None

    def flags(self, index: QModelIndex):
        flags = super().flags(index)
        if index.isValid() and self.editable and COLUMNS[index.column()] in ENDONYMS:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.entries):
            return None
        entry = self.entries[index.row()]
        column = COLUMNS[index.column()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if column == COL_KEY:
                return entry.key
            if column in ENDONYMS:
                return entry.texts.get(column, "")
            if column == COL_FILE:
                return f"{entry.rel.name}:{entry.line}" if entry.line else entry.rel.name
            return tr(ORIGIN_KEYS[origin_of(entry)])
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(entry, column)
        if role == Qt.ItemDataRole.DecorationRole and column == COL_KEY:
            if entry.degraded:
                return make_icon("warning", "warning", "cream")
            if self.pending_check is not None and entry.layer is LayerKind.MOD and self.pending_check(entry):
                return make_icon("quill", "ink_soft", "cream")
            return None
        if role == Qt.ItemDataRole.ForegroundRole:
            if column == COL_ORIGIN:
                return theme.color(ORIGIN_COLORS[origin_of(entry)])
            if column == COL_KEY:
                return theme.color("syntax_key")
            if column == COL_FILE:
                return theme.color("ink_muted")
            return None
        if role == Qt.ItemDataRole.FontRole and column in (COL_KEY, COL_FILE):
            return self._mono
        if role == ENTRY_ROLE:
            return entry
        return None

    def _tooltip(self, entry: LocEntry, column: str) -> str | None:
        if column == COL_FILE:
            return tr("texts.file_tooltip", path=str(entry.rel), line=entry.line or "?")
        if column == COL_ORIGIN:
            return tr(ORIGIN_TOOLTIPS[origin_of(entry)])
        if column == COL_KEY:
            parts = [entry.key]
            if entry.degraded:
                parts.append(tr("texts.degraded_tooltip"))
            if entry.created_by_studio:
                parts.append(tr("texts.studio_tooltip", prefix=self.prefix))
            return "\n".join(parts)
        if column in ENDONYMS:
            text = entry.texts.get(column, "")
            return text if len(text) > 40 else None
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or not self.editable:
            return False
        column = COLUMNS[index.column()]
        if column not in ENDONYMS:
            return False
        entry = self.entries[index.row()]
        text = "" if value is None else str(value)
        if text == entry.texts.get(column, ""):
            return False
        self._accepted = None
        self.edit_requested.emit(entry.key, column, text)
        accepted, self._accepted = bool(self._accepted), None
        return accepted

    def accept_edit(self, accepted: bool) -> None:
        """Respuesta de quien escucha ``edit_requested`` (síncrona): ``setData`` la devuelve."""
        self._accepted = accepted


class LocEntriesProxy(QAbstractTableModel):
    """Filas visibles de ``LocEntriesModel`` por filtro y búsqueda, calculadas de una vez en Python (como la tabla
    de «Archivos CSV»: con 21 000 claves, filtrar fila a fila en Qt costaría décimas)."""

    def __init__(self, source: LocEntriesModel, parent=None):
        super().__init__(parent)
        self.source = source
        self._rows: list[int] = []
        self._filter = FILTER_ALL
        self._needle = ""
        self._haystack: list[str] | None = None
        source.modelAboutToBeReset.connect(self.beginResetModel)
        source.modelReset.connect(self._on_source_reset)
        source.dataChanged.connect(self._on_source_changed)
        source.headerDataChanged.connect(self.headerDataChanged)
        self._rows = self._visible()

    def set_filter(self, kind: str) -> None:
        if kind != self._filter:
            self._filter = kind
            self.refresh()

    def filter(self) -> str:
        return self._filter

    def set_query(self, text: str) -> None:
        needle = fold(text.strip())
        if needle != self._needle:
            self._needle = needle
            self.refresh()

    def matches(self, entry: LocEntry, kind: str | None = None) -> bool:
        kind = self._filter if kind is None else kind
        if kind == FILTER_STUDIO:
            return entry.created_by_studio
        if kind == FILTER_UNTRANSLATED:
            check = self.source.pending_check
            return entry.layer is LayerKind.MOD and check is not None and bool(check(entry))
        if kind == FILTER_OVERRIDES:
            return entry.overrides_game
        if kind == FILTER_DEGRADED:
            return entry.degraded
        return True

    def counts(self) -> dict[str, int]:
        """Filas de cada filtro (sin la búsqueda), en una sola pasada."""
        counts = dict.fromkeys((data for data, _ in FILTERS), 0)
        check = self.source.pending_check
        for entry in self.source.entries:
            counts[FILTER_ALL] += 1
            counts[FILTER_STUDIO] += entry.created_by_studio
            counts[FILTER_OVERRIDES] += entry.overrides_game
            counts[FILTER_DEGRADED] += entry.degraded
            if entry.layer is LayerKind.MOD and check is not None and check(entry):
                counts[FILTER_UNTRANSLATED] += 1
        return counts

    def _visible(self) -> list[int]:
        rows = [i for i, entry in enumerate(self.source.entries) if self.matches(entry)]
        if self._needle:
            haystack = self._search_texts()
            rows = [i for i in rows if self._needle in haystack[i]]
        return rows

    def refresh(self) -> None:
        """Vuelve a filtrar. Sin reiniciar el modelo: la vista conserva la selección y el desplazamiento."""
        rows = self._visible()
        if rows == self._rows:
            if rows:
                self.dataChanged.emit(self.index(0, 0), self.index(len(rows) - 1, len(COLUMNS) - 1))
            return
        self.layoutAboutToBeChanged.emit()
        before = self.persistentIndexList()
        sources = [self._rows[i.row()] if 0 <= i.row() < len(self._rows) else None for i in before]
        self._rows = rows
        self.changePersistentIndexList(before, [self._index_for(source, index.column())
                                                for source, index in zip(sources, before)])
        self.layoutChanged.emit()

    def _index_for(self, source: int | None, column: int) -> QModelIndex:
        row = None if source is None else self.proxy_row(source)
        return QModelIndex() if row is None else self.index(row, column)

    def _on_source_reset(self) -> None:
        self._haystack = None
        self._rows = self._visible()
        self.endResetModel()

    def _search_texts(self) -> list[str]:
        if self._haystack is None:
            self._haystack = [fold("\x00".join((e.key, *e.texts.values()))) for e in self.source.entries]
        return self._haystack

    def source_row(self, row: int) -> int:
        return self._rows[row]

    def proxy_row(self, source_row: int) -> int | None:
        position = bisect_left(self._rows, source_row)
        return position if position < len(self._rows) and self._rows[position] == source_row else None

    def _on_source_changed(self, top_left: QModelIndex, bottom_right: QModelIndex, roles=()) -> None:
        self._haystack = None
        self.refresh()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def _source_index(self, index: QModelIndex) -> QModelIndex:
        return self.source.index(self._rows[index.row()], index.column())

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        return self.source.headerData(section, orientation, role) if orientation == Qt.Orientation.Horizontal \
            else None

    def flags(self, index: QModelIndex):
        return self.source.flags(self._source_index(index)) if index.isValid() else Qt.ItemFlag.NoItemFlags

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        return self.source.data(self._source_index(index), role)

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return False
        return self.source.setData(self._source_index(index), value, role)


class TextsPage(BasePage):
    """La tabla de textos efectivos. ``preset`` fija el filtro inicial (``FILTER_UNTRANSLATED`` en «Pendientes»)."""

    key = "localisation.all"
    title_key = N_("section.localisation.all")
    subtitle_key = N_("section.localisation.all.intro")
    icon_name = "localisation"

    def __init__(self, session, *, preset: str = FILTER_ALL, parent: QWidget | None = None):
        self.session = session
        self.preset = preset
        if preset == FILTER_UNTRANSLATED:
            self.key = "localisation.pending"
            self.title_key = N_("section.localisation.pending")
            self.subtitle_key = N_("section.localisation.pending.intro")
            self.icon_name = "quill"
        super().__init__(parent)
        session.projectOpened.connect(self._on_project_changed)
        session.projectClosed.connect(self._on_project_changed)
        session.textsReady.connect(self.refresh)
        session.textsChanged.connect(self._queue_refresh)
        self._on_project_changed()

    # --- construcción --------------------------------------------------------------------------------

    def build(self) -> None:
        self.exec_dialog = lambda dialog: dialog.exec()   # la ventana lo sustituye (y las pruebas)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self.refresh)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self._apply_search)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("textsSearch")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(220)
        self.search_edit.addAction(make_icon("search", "ink_muted"), QLineEdit.ActionPosition.LeadingPosition)
        self.search_edit.textChanged.connect(lambda _: self._search_timer.start())
        bar.addWidget(self.search_edit, 2)
        self.filter_combo = QComboBox()
        self.filter_combo.setObjectName("textsFilter")
        self.filter_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for data, _ in FILTERS:
            self.filter_combo.addItem("", data)
        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        bar.addWidget(self.filter_combo)
        self.extra_check = QCheckBox()
        self.extra_check.setObjectName("textsExtraLanguages")
        self.extra_check.toggled.connect(self._apply_columns)
        bar.addWidget(self.extra_check)
        bar.addStretch(1)
        self.add_button = QPushButton()
        self.add_button.setObjectName("textsAddKey")
        self.add_button.setProperty("accent", True)
        self.add_button.setIcon(make_icon("plus", "gold_pale"))
        self.add_button.clicked.connect(self.add_key)
        bar.addWidget(self.add_button)
        self.body.addLayout(bar)

        self.count_label = QLabel()
        self.count_label.setObjectName("textsCount")
        self.count_label.setProperty("role", "caption")
        self.count_label.setFont(theme.font("caption"))
        self.count_label.setWordWrap(True)
        self.body.addWidget(self.count_label)

        self.stack = QStackedWidget()
        self.empty = EmptyState(self.icon_name)
        self.stack.addWidget(self.empty)
        self.table_box = QWidget()
        box = QVBoxLayout(self.table_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self.model = LocEntriesModel(self)
        self.model.edit_requested.connect(self._on_edit_requested)
        self.proxy = LocEntriesProxy(self.model, self)
        self.proxy.modelReset.connect(self._update_counts)
        self.proxy.layoutChanged.connect(self._update_counts)   # filtrar o buscar
        self.table = QTableView()
        self.table.setObjectName("textsTable")
        mark_data(self.table)
        self.table.setModel(self.proxy)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed
                                   | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setCornerButtonEnabled(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 8)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(MIN_COLUMN_WIDTH)
        for section, column in enumerate(COLUMNS):
            if column in COLUMN_WIDTHS:
                header.resizeSection(section, COLUMN_WIDTHS[column])
            else:  # los textos ocupan lo que dejan la clave, el archivo y el origen
                header.setSectionResizeMode(section, QHeaderView.ResizeMode.Stretch)
        self._file_delegate = PathElideDelegate(self.table)
        self.table.setItemDelegateForColumn(COLUMNS.index(COL_FILE), self._file_delegate)
        box.addWidget(self.table, 1)
        self.hint = QLabel()
        self.hint.setObjectName("textsHint")
        self.hint.setTextFormat(Qt.TextFormat.PlainText)
        self.hint.setProperty("role", "caption")
        self.hint.setFont(theme.font("caption"))
        self.hint.setWordWrap(True)
        box.addWidget(self.hint)
        self.stack.addWidget(self.table_box)
        self.body.addWidget(self.stack, 1)
        if self.preset != FILTER_ALL:
            self.filter_combo.setCurrentIndex([data for data, _ in FILTERS].index(self.preset))
        self._apply_columns()

    # --- API -----------------------------------------------------------------------------------------

    def refresh(self) -> None:
        """Vuelve a leer los textos efectivos de ``LocSync`` conservando la celda seleccionada."""
        self._refresh_timer.stop()
        locsync = self.session.locsync
        ready = locsync is not None and self.session.texts_ready()
        self.model.editable = ready and not self.session.is_read_only()
        if locsync is not None:
            self.model.languages = tuple(locsync.languages)
            self.model.pending_check = locsync.untranslated
            self.model.prefix = locsync.prefix
        current = self._current_key()
        column = max(self.table.currentIndex().column(), 0)
        entries = locsync.entries() if ready else []
        self.model.set_entries(entries)
        if current is not None and self._current_key() != current:
            self.select_key(current, column, scroll=False, reveal=False)
        self._update_state()
        self._retranslate_hint()

    def _retranslate_hint(self) -> None:
        locsync = self.session.locsync
        target = str(locsync.target_file("overrides").name) if locsync is not None else "00_overrides.csv"
        self.hint.setText(tr("texts.hint", file=target))

    def select_key(self, key: str, column: int | str = 0, *, scroll: bool = True, reveal: bool = True) -> bool:
        """Selecciona la celda de ``key`` (columna por índice o idioma). Con ``reveal``, si la búsqueda o el filtro
        la ocultaban, los quita; sin él (al refrescar), deja la vista como está."""
        if isinstance(column, str):
            column = COLUMNS.index(column)
        source = self.model.row_of(key)
        if source is None:
            return False
        row = self.proxy.proxy_row(source)
        if row is None and not reveal:
            return False
        if row is None:
            self.search_edit.blockSignals(True)
            self.search_edit.clear()
            self.search_edit.blockSignals(False)
            self.proxy.set_query("")
            if not self.proxy.matches(self.model.entries[source]):
                self.filter_combo.setCurrentIndex(0)
            row = self.proxy.proxy_row(source)
            if row is None:
                return False
        index = self.proxy.index(row, column)
        self.table.setCurrentIndex(index)
        if scroll:
            self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        return True

    def visible_keys(self) -> list[str]:
        return [self.model.entries[self.proxy.source_row(row)].key for row in range(self.proxy.rowCount())]

    def set_text(self, key: str, lang: str, text: str) -> bool:
        """Lo que hace editar una celda: escribe ``text`` según la política de ``LocSync`` (deshacible)."""
        locsync = self.session.locsync
        if locsync is None or self.session.project is None:
            return False
        try:
            with self.session.edit(LABEL_EDIT, key=key, lang=ENDONYMS.get(lang, lang)):
                rel = locsync.set_text(key, lang, text)
        except InvalidFieldError as exc:
            self.request_status("texts.status_invalid", error=exc.message(core_language()))
            return False
        except UnencodableTextError as exc:
            char = exc.problems[0][3]
            self.request_status("texts.status_unencodable", char=char, code=f"U+{ord(char):04X}")
            return False
        except ReadOnlyDocumentError:
            self.request_status("texts.status_read_only")
            return False
        self.request_status("texts.status_written", name=key, file=str(rel))
        self._queue_refresh()   # fuera de setData: la vista aún está cerrando el editor
        return True

    def add_key(self) -> int:
        """Abre «Añadir clave»; si se acepta, crea la clave y la selecciona."""
        from ...dialogs.add_key import AddKeyDialog

        locsync = self.session.locsync
        if locsync is None or self.session.is_read_only():
            return 0
        dialog = AddKeyDialog(locsync, self)
        result = self.exec_dialog(dialog)
        values = dialog.values() if result else None
        if not values:
            return result
        key, area, texts = values
        try:
            with self.session.edit(LABEL_ADD, key=key):
                locsync.ensure({key: texts}, area=area)
        except (InvalidFieldError, UnencodableTextError) as exc:
            self.request_status("texts.status_invalid", error=exc.message(core_language())
                         if isinstance(exc, InvalidFieldError) else str(exc))
            return 0
        self.refresh()
        self.select_key(key, "es" if "es" in texts else "en")
        self.request_status("texts.status_added", name=key, file=str(locsync.target_file(area)))
        return result

    def is_busy(self) -> bool:
        return self._refresh_timer.isActive() or self._search_timer.isActive()

    # --- interno -------------------------------------------------------------------------------------

    def _current_key(self) -> str | None:
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        return self.model.entries[self.proxy.source_row(index.row())].key

    def _queue_refresh(self) -> None:
        self._refresh_timer.start()

    def _on_project_changed(self, *args) -> None:
        self.refresh()

    def _on_edit_requested(self, key: str, lang: str, text: str) -> None:
        self.model.accept_edit(self.set_text(key, lang, text))

    def _on_filter_changed(self, index: int) -> None:
        self.proxy.set_filter(FILTERS[max(index, 0)][0])
        self._update_counts()

    def _apply_search(self) -> None:
        self.proxy.set_query(self.search_edit.text())

    def _apply_columns(self, *args) -> None:
        show = self.extra_check.isChecked()
        for language in EXTRA_LANGUAGES:
            self.table.setColumnHidden(COLUMNS.index(language), not show)

    def _update_state(self) -> None:
        session = self.session
        # Los textos del estado vacío se ponen siempre, se vea o no: oculto también cambia de idioma.
        if session.project is None:
            self.empty.set_texts(tr("texts.empty_no_project_title"), tr("texts.empty_no_project"))
        else:
            self.empty.set_texts(tr("texts.loading_title"), tr("texts.loading"))
        ready = session.project is not None and session.locsync is not None and session.texts_ready()
        show_in_stack(self.stack, self.table_box if ready else self.empty)
        writable = session.project is not None and session.locsync is not None and not session.is_read_only()
        self.add_button.setEnabled(writable and session.texts_ready())
        self.search_edit.setEnabled(self.stack.currentWidget() is self.table_box)
        self.filter_combo.setEnabled(self.stack.currentWidget() is self.table_box)
        self._retranslate_filters()
        self._update_counts()

    def _retranslate_filters(self) -> None:
        counts = self.proxy.counts()
        for position, (data, key) in enumerate(FILTERS):
            self.filter_combo.setItemText(position, tr(key, count=format_number(counts[data])))

    def _update_counts(self, *args) -> None:
        total = len(self.model.entries)
        shown = self.proxy.rowCount()
        if self.session.project is None or not self.session.texts_ready():
            self.count_label.setText("")
            return
        text = tr("texts.count_one" if total == 1 else "texts.count", total=format_number(total))
        if shown != total:
            text += " " + tr("texts.shown", shown=format_number(shown))
        if self.session.is_read_only():
            text += " · " + tr("texts.read_only")
        self.count_label.setText(text)

    def retranslate(self) -> None:
        super().retranslate()
        if not hasattr(self, "model"):
            return
        self.search_edit.setPlaceholderText(tr("texts.search_placeholder"))
        self.search_edit.setToolTip(tr("texts.search_tooltip"))
        self.filter_combo.setToolTip(tr("texts.filter_tooltip"))
        self.extra_check.setText(tr("texts.extra_languages"))
        self.extra_check.setToolTip(tr("texts.extra_languages_tooltip"))
        self.add_button.setText(tr("texts.add_key"))
        self.add_button.setToolTip(tr("texts.add_key_tooltip"))
        self._retranslate_hint()
        self.model.retranslate()
        self._update_state()
