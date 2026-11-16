"""Editor genérico de entidades (wizard §13.5): la sección que genera un esquema con ``hall`` y ``section``.

A la izquierda, el ``EntityNavigator`` (lista con filtro y los botones Nuevo, Duplicar, Borrar y Restaurar); a
la derecha, la cabecera del registro (id, cinta de origen y problemas) y las pestañas **Formulario** (el
``EntityForm`` generado), **Textos** (las ``LocSpec`` en ES y EN), **Usos** (``where_used``; doble clic abre el
archivo en su línea), **Código** (el ``ScriptEditor`` de Proyecto › Archivos sobre el archivo, en la línea del
bloque: decisión 2 del informe) y **Otros campos** (las claves que el esquema no conoce, I6). Los esquemas con
``MappingTable`` añaden **Rebeldes** (la matriz); los que tienen ``ActivateUnit``, **Unidad** (estadísticas
comparadas, dónde se desbloquea y el modelo); y las fechas de inicio, el editor de ``end_date``.

Crear, duplicar, renombrar (con su plan a la vista, §15), mover de grupo, borrar y restaurar son una
transacción cada uno (``Entities``); editar un campo o un texto,
una transacción con ``merge_key`` por campo. Nada se escribe en disco hasta Ctrl+S.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.clausewitz.diagnostics import EditError
from ...core.clausewitz.nodes import Scalar
from ...core.schema import EntityInUseError, InvalidIdentError
from ...core.schema.layouts import GroupedIn
from ...core.schema.record import ReadOnlySchemaError
from ...i18n import N_, language, tr
from ..forms import EntityForm
from ..pages.base import BasePage
from ..widgets import RibbonBadge, mark_data
from .dialogs import (
    IDENT_MESSAGES,
    MoveGroupDialog,
    NewEntityDialog,
    RenameEntityDialog,
    UnitNamesDialog,
    UsesDialog,
)
from .extras import EndDatePanel, RebelMatrix, mapping_table
from .navigator import ORIGIN_KEYS, EntityNavigator
from .unit_panel import UnitPanel, activate_unit

TAB_FORM, TAB_TEXTS, TAB_USES, TAB_CODE, TAB_OTHER, TAB_REBELS = "form", "texts", "uses", "code", "other", "rebels"
TAB_UNIT = "unit"
_REF = Qt.ItemDataRole.UserRole


class LocTextsPanel(QWidget):
    """Las claves de texto del registro en español e inglés, editables (``LocSync.set_text`` en una transacción)."""

    status_requested = Signal(str, object)
    LANGS = ("es", "en")

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.record_keys: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.table = mark_data(QTableWidget(0, 3))
        self.table.setObjectName("entityTexts")
        self.table.verticalHeader().hide()
        for column in range(3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_changed)
        outer.addWidget(self.table)
        self._filling = False
        self.retranslate()

    def retranslate(self) -> None:
        self.table.setHorizontalHeaderLabels([tr("entity.texts.key"), tr("entity.texts.es"), tr("entity.texts.en")])

    def bind(self, record) -> None:
        self._filling = True
        try:
            self.table.setRowCount(0)
            self.record_keys = [] if record is None else record.loc_keys()
            loc = self.session.locsync
            for spec, key in self.record_keys:
                row = self.table.rowCount()
                self.table.insertRow(row)
                item = QTableWidgetItem(key)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setData(_REF, spec.area)
                self.table.setItem(row, 0, item)
                for column, lang in enumerate(self.LANGS, start=1):
                    text = loc.text(key, lang) if loc is not None else None
                    cell = QTableWidgetItem(text or "")
                    if self.session.is_read_only():
                        cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, column, cell)
        finally:
            self._filling = False

    def _on_changed(self, item) -> None:
        if self._filling or item.column() == 0 or self.session.locsync is None or self.session.is_read_only():
            return
        key_item = self.table.item(item.row(), 0)
        key, area, lang = key_item.text(), key_item.data(_REF), self.LANGS[item.column() - 1]
        try:
            with self.session.edit(N_("entity.texts.undo"), merge_key=f"loc.{key}.{lang}", key=key, lang=lang):
                self.session.locsync.set_text(key, lang, item.text(), area=area)
        except (ValueError, KeyError, OSError) as exc:
            self.status_requested.emit(N_("entity.texts.failed"), {"key": key, "error": str(exc)})


class OtherFieldsPanel(QWidget):
    """Las claves que el esquema no conoce (I6): se conservan; las de valor suelto se pueden editar como texto."""

    status_requested = Signal(str, object)

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.ref = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.intro = QLabel()
        self.intro.setWordWrap(True)
        outer.addWidget(self.intro)
        self.table = mark_data(QTableWidget(0, 2))
        self.table.setObjectName("otherFields")
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_changed)
        outer.addWidget(self.table, 1)
        self._filling = False
        self.retranslate()

    def retranslate(self) -> None:
        self.intro.setText(tr("entity.other.intro"))
        self.table.setHorizontalHeaderLabels([tr("entity.other.key"), tr("entity.other.value")])

    def bind(self, ref, record) -> None:
        self.ref = ref
        self._filling = True
        try:
            self.table.setRowCount(0)
            for entry in ([] if record is None else record.unknown()):
                row = self.table.rowCount()
                self.table.insertRow(row)
                key = QTableWidgetItem(entry.key.text)
                key.setFlags(key.flags() & ~Qt.ItemFlag.ItemIsEditable)
                key.setData(_REF, row)
                self.table.setItem(row, 0, key)
                value = entry.value
                cell = QTableWidgetItem(value.text if isinstance(value, Scalar) else "{ … }")
                if not isinstance(value, Scalar) or self.session.is_read_only():
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 1, cell)
        finally:
            self._filling = False

    def _on_changed(self, item) -> None:
        if self._filling or item.column() != 1 or self.ref is None:
            return
        row = item.row()
        key = self.table.item(row, 0).text()
        position = sum(1 for r in range(row) if self.table.item(r, 0).text() == key)
        try:
            with self.session.edit(N_("entity.other.undo"), merge_key=f"other.{self.ref.kind}.{self.ref.ident}.{key}",
                                   key=key, ident=self.ref.ident):
                record = self.session.entities.open(self.ref)
                record._touch()
                entries = [entry for entry in record.unknown() if entry.key.text == key]
                entries[position].value = item.text()
        except (ValueError, KeyError, IndexError, EditError) as exc:
            self.status_requested.emit(N_("entity.other.failed"), {"key": key, "error": str(exc)})


class EntityEditorPage(BasePage):
    """La sección de un esquema (y de una vista, si la tiene). API: ``navigator``, ``form``, ``tabs``,
    ``show_record(ref)``, ``focus_field(ref, ruta)``, ``create(id, base=None, group=None)``, ``delete(ref)``,
    ``restore(ref)``, ``refresh()``. ``exec_dialog`` se puede sustituir (las pruebas lo hacen)."""

    location_requested = Signal(object, object)    # (rel, línea)

    def __init__(self, session, schema, view: str | None = None, parent: QWidget | None = None):
        self.session = session
        self.schema = schema
        self.view = view
        self.key = f"entity_{schema.kind}" + (f"_{view}" if view else "")
        self.title_key = f"schema.{schema.kind}.view.{view}" if view else f"schema.{schema.kind}.title"
        self.subtitle_key = f"schema.{schema.kind}.doc"
        self.icon_name = schema.icon
        self._stale = True
        self._current = None
        self.exec_dialog = lambda dialog: dialog.exec()
        super().__init__(parent)
        session.projectOpened.connect(self._on_project_opened)
        session.projectClosed.connect(self._mark_stale)
        session.symbolsChanged.connect(self._on_symbols_changed)
        session.documentsChanged.connect(self._on_documents_changed)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self._refresh_if_visible)

    # --- construcción -----------------------------------------------------------------------------

    def build(self) -> None:
        self.end_date_panel = None
        if self.schema.kind == "bookmark":
            self.end_date_panel = EndDatePanel(self.session)
            self.end_date_panel.status_requested.connect(self.status_requested)
            self.body.addWidget(self.end_date_panel)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("entitySplitter")
        self.navigator = EntityNavigator(self.session, self.schema, self.view)
        self.navigator.current_changed.connect(self._on_current)
        self.navigator.new_requested.connect(self.ask_new)
        self.navigator.duplicate_requested.connect(self.ask_duplicate)
        self.navigator.delete_requested.connect(self.delete)
        self.navigator.restore_requested.connect(self.restore)
        self.navigator.rename_requested.connect(self.ask_rename)
        self.navigator.move_requested.connect(self.ask_move)
        self.navigator.new_group_requested.connect(self.ask_new_group)
        self.splitter.addWidget(self.navigator)
        right = QWidget()
        column = QVBoxLayout(right)
        column.setContentsMargins(6, 0, 0, 0)
        column.setSpacing(6)
        header = QHBoxLayout()
        self.record_title = mark_data(QLabel())
        self.record_title.setObjectName("recordTitle")
        self.record_title.setProperty("role", "title")
        header.addWidget(self.record_title, 1)
        self.origin_badge = RibbonBadge()
        self.origin_badge.setObjectName("recordOrigin")
        header.addWidget(self.origin_badge)
        column.addLayout(header)
        self.empty_label = QLabel()
        self.empty_label.setObjectName("entityEmpty")
        self.empty_label.setWordWrap(True)
        column.addWidget(self.empty_label)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("entityTabs")
        self.problems_list = mark_data(QListWidget())
        self.problems_list.setObjectName("recordProblems")
        self.problems_list.setMaximumHeight(90)
        self.problems_list.itemActivated.connect(self._on_problem_activated)
        self.form = EntityForm(self.session, self.schema)
        self.form.status_requested.connect(self.status_requested)
        self.form.code_requested.connect(self.show_code)
        self.form.record_changed.connect(lambda _ref: self._bind_details())
        form_page = QWidget()
        form_column = QVBoxLayout(form_page)
        form_column.setContentsMargins(0, 0, 0, 0)
        self.problems_title = QLabel()
        form_column.addWidget(self.problems_title)
        form_column.addWidget(self.problems_list)
        form_column.addWidget(self.form, 1)
        self.texts = LocTextsPanel(self.session)
        self.texts.status_requested.connect(self.status_requested)
        self.uses = mark_data(QListWidget())
        self.uses.setObjectName("entityUses")
        self.uses.itemActivated.connect(self._on_use_activated)
        from ..viewers.script_editor import ScriptEditor

        self.code = ScriptEditor(self.session)
        self.code.back_button.hide()
        self.other = OtherFieldsPanel(self.session)
        self.other.status_requested.connect(self.status_requested)
        self._tab_keys = [TAB_FORM, TAB_TEXTS, TAB_USES, TAB_CODE, TAB_OTHER]
        for widget in (form_page, self.texts, self.uses, self.code, self.other):
            self.tabs.addTab(widget, "")
        self.rebels = None
        companion = mapping_table(self.schema)
        if companion is not None:
            self.rebels = RebelMatrix(self.session, companion)
            self.rebels.status_requested.connect(self.status_requested)
            self.tabs.addTab(self.rebels, "")
            self._tab_keys.append(TAB_REBELS)
        self.unit = None
        if activate_unit(self.schema) is not None:
            self.unit = UnitPanel(self.session, self.schema)
            self.unit.status_requested.connect(self.status_requested)
            self.unit.location_requested.connect(self.location_requested)
            self.tabs.addTab(self.unit, "")
            self._tab_keys.append(TAB_UNIT)
        self.tabs.currentChanged.connect(self._on_tab)
        column.addWidget(self.tabs, 1)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([260, 780])
        self.body.addWidget(self.splitter, 1)

    def retranslate(self) -> None:
        super().retranslate()
        for panel in (self.texts, self.other):
            panel.retranslate()
        names = {TAB_FORM: N_("entity.tab.form"), TAB_TEXTS: N_("entity.tab.texts"), TAB_USES: N_("entity.tab.uses"),
                 TAB_CODE: N_("entity.tab.code"), TAB_OTHER: N_("entity.tab.other"),
                 TAB_REBELS: N_("entity.tab.rebels"), TAB_UNIT: N_("entity.tab.unit")}
        for index, key in enumerate(self._tab_keys):
            self.tabs.setTabText(index, tr(names[key]))
        self._render_header()

    # --- estado -----------------------------------------------------------------------------------

    def _on_project_opened(self, project) -> None:
        self._mark_stale()

    def _on_symbols_changed(self, kinds) -> None:
        self._mark_stale()

    def _mark_stale(self) -> None:
        self._stale = True
        self._refresh_timer.start()

    def _on_documents_changed(self, rels) -> None:
        touches = getattr(self.schema.layout, "touches", None)
        relevant = touches is None or any(touches(rel) for rel in rels)
        if self.end_date_panel is not None:
            relevant = True
        if relevant:
            self._mark_stale()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._stale:
            self.refresh()

    def _refresh_if_visible(self) -> None:
        if self._stale and self.isVisible():
            self.refresh()

    def refresh(self) -> None:
        """Vuelve a leer la lista y el registro a la vista (vista efectiva)."""
        self._stale = False
        self.navigator.refresh()
        if self.end_date_panel is not None:
            self.end_date_panel.refresh()
        self._bind(self.navigator.current_ref())

    def count(self) -> int | None:
        """Contador del índice lateral: registros de la vista efectiva (None sin proyecto)."""
        entities = getattr(self.session, "entities", None)
        if entities is None:
            return None
        try:
            return len(entities.list(self.schema.kind, view=self.view))
        except Exception:  # noqa: BLE001 - un contador nunca rompe la ventana
            return None

    # --- registro a la vista ----------------------------------------------------------------------

    def current_ref(self):
        return self._current

    def _on_current(self, ref) -> None:
        self.form.commit_pending()
        self._bind(ref)

    def _schema_of(self, ref):
        from ...core.schema import registry

        return self.schema if ref is None or ref.kind == self.schema.kind else registry.get(ref.kind)

    def _bind(self, ref) -> None:
        self._current = ref
        if ref is not None and ref.kind != self.schema.kind:
            # Un grupo (culture_group) elegido en el árbol: su formulario propio.
            self._bind_group(ref)
            return
        self._ensure_main_form()
        self.form.bind(ref)
        self._bind_details()

    def _ensure_main_form(self) -> None:
        if self.form.schema is not self.schema:
            self._swap_form(EntityForm(self.session, self.schema))

    def _bind_group(self, ref) -> None:
        schema = self._schema_of(ref)
        if self.form.schema is not schema:
            self._swap_form(EntityForm(self.session, schema))
        self.form.bind(ref)
        self._bind_details()

    def _swap_form(self, form) -> None:
        old = self.form
        layout = old.parentWidget().layout()
        layout.replaceWidget(old, form)
        old.deleteLater()
        self.form = form
        form.status_requested.connect(self.status_requested)
        form.code_requested.connect(self.show_code)
        form.record_changed.connect(lambda _ref: self._bind_details())

    def record(self):
        return self.form.record()

    def _bind_details(self) -> None:
        ref = self._current
        record = self.form.record()
        self.texts.bind(record)
        self.other.bind(ref, record)
        self.uses.clear()
        self.problems_list.clear()
        entities = getattr(self.session, "entities", None)
        if record is not None and entities is not None:
            for use in entities.where_used(ref):
                item = QListWidgetItem(f"{use.rel}:{use.line or 0} · {use.role}")
                item.setData(_REF, (use.rel, use.line))
                self.uses.addItem(item)
            for problem in record.issues(entities.check_context()):
                item = QListWidgetItem(problem.message(language()))
                item.setData(_REF, problem.field)
                self.problems_list.addItem(item)
        if self.rebels is not None:
            self.rebels.bind(ref if ref is not None and ref.kind == self.schema.kind else None)
        if self.unit is not None:
            self.unit.bind(ref if record is not None else None)
        if self.tabs.currentIndex() == self._tab_keys.index(TAB_CODE):
            self._load_code()
        self._render_header()

    def _render_header(self) -> None:
        ref = self._current
        record = None if ref is None else self.form.record()
        has = record is not None
        self.tabs.setVisible(has)
        self.record_title.setVisible(has)
        self.origin_badge.setVisible(has)
        self.empty_label.setVisible(not has)
        if self.session.project is None:
            self.empty_label.setText(tr("entity.no_project"))
        else:
            self.empty_label.setText(tr("entity.empty", kind=tr(f"schema.{self.schema.kind}.title")))
        count = self.problems_list.count()
        self.problems_title.setText(tr("entity.problems", count=count))
        self.problems_title.setVisible(count > 0)
        self.problems_list.setVisible(count > 0)
        if has:
            self.record_title.setText(ref.ident)
            try:
                origin = self.session.entities.origin_of(ref)
            except (KeyError, FileNotFoundError):
                origin = "game"
            self.origin_badge.setText(tr(ORIGIN_KEYS[origin]))

    def show_record(self, ref) -> bool:
        if self._stale:
            self.refresh()
        return self.navigator.select(ref)

    def focus_field(self, ref, path=()) -> bool:
        """Selecciona ``ref`` y lleva al campo ``path`` en la pestaña Formulario (F7, Ctrl+K)."""
        if not self.show_record(ref):
            return False
        self.tabs.setCurrentIndex(self._tab_keys.index(TAB_FORM))
        if path:
            return self.form.focus_field(path)
        return True

    def show_tab(self, key: str) -> None:
        self.tabs.setCurrentIndex(self._tab_keys.index(key))

    def show_code(self, field: str | None = None) -> None:
        self.show_tab(TAB_CODE)
        self._load_code(field)

    def _on_tab(self, index: int) -> None:
        if 0 <= index < len(self._tab_keys) and self._tab_keys[index] == TAB_CODE:
            self._load_code()
        else:
            self.code.commit_pending()

    def _load_code(self, field: str | None = None) -> None:
        record = self.form.record()
        if record is None:
            return
        rel = record.handle.rel
        if self.code.current_rel() is None or self.code.current_rel().key != rel.key:
            if not self.code.open_document(rel):
                return
        node = record.node(field) if field else None
        line = node.line if node is not None and node.line else (
            record._entry.line if record._entry is not None else None)
        if line:
            block = self.code.editor.document().findBlockByNumber(line - 1)
            cursor = QTextCursor(block)
            self.code.editor.setTextCursor(cursor)
            self.code.editor.centerCursor()

    def _on_use_activated(self, item) -> None:
        rel, line = item.data(_REF)
        self.location_requested.emit(rel, line)

    def _on_problem_activated(self, item) -> None:
        field = item.data(_REF)
        if field:
            self.form.focus_field(field)

    def commit_pending(self) -> None:
        self.form.commit_pending()
        self.code.commit_pending()

    # --- operaciones ------------------------------------------------------------------------------

    def _groups(self) -> list[str]:
        layout = self.schema.layout
        if not isinstance(layout, GroupedIn) or layout.level == 0 or self.session.project is None:
            return []
        try:
            document = self.session.project.ws.open(layout.path).model.document
        except (FileNotFoundError, OSError):
            return []
        return [name for name, _, _ in layout.groups(document)]

    def _selected_group(self) -> str | None:
        ref = self._current
        if ref is None:
            return None
        if ref.kind != self.schema.kind:
            return ref.ident
        try:
            return self.session.entities.parent(ref)
        except (KeyError, FileNotFoundError):
            return None

    def ask_new(self, base=None) -> bool:
        """«Nuevo» (de la plantilla o «basado en…») y «Duplicar» (con ``base``): pide el id y crea."""
        entities = self.session.entities
        if entities is None:
            return False
        existing = [summary.ref for summary in entities.list(self.schema.kind)]
        dialog = NewEntityDialog(self.schema, existing, self._groups(), base=base, group=self._selected_group(),
                                 parent=self)
        if self.exec_dialog(dialog) != QDialog.DialogCode.Accepted:
            return False
        ident, chosen_base, group = dialog.result_values()
        return self.create(ident, chosen_base, group)

    def ask_duplicate(self, ref) -> bool:
        return self.ask_new(base=ref)

    def _template_values(self) -> dict:
        values = {}
        if self.view is not None and self.schema.variants is not None:
            values[self.schema.variants.field] = self.view   # «Nueva» en Unidades navales nace naval
        return values

    def create(self, ident: str, base=None, group: str | None = None) -> bool:
        """Crea ``ident`` (de la plantilla o «basado en» ``base``) en una transacción y lo selecciona."""
        entities = self.session.entities
        if entities is None or self.session.is_read_only():
            return False
        try:
            # La transacción de Entities queda dentro de la de Session (misma etiqueta): avisa al acabar.
            if base is not None:
                with self.session.edit(f"undo.duplicate_{self.schema.kind}", kind=self.schema.kind, ident=ident):
                    ref = entities.duplicate(base, ident)
            else:
                values = self._template_values()
                if group:
                    values["group"] = group
                with self.session.edit(f"undo.create_{self.schema.kind}", kind=self.schema.kind, ident=ident):
                    ref = entities.create(self.schema.kind, ident, values)
        except InvalidIdentError as exc:
            self.request_status(N_("entity.create_failed"), reason=tr(IDENT_MESSAGES.get(exc.code,
                                                                                         "entity.ident.bad_chars"),
                                                                     ident=ident))
            return False
        except (ReadOnlySchemaError, PermissionError, FileNotFoundError, ValueError) as exc:
            self.request_status(N_("entity.create_failed"), reason=str(exc))
            return False
        self.refresh()
        self.navigator.select(ref)
        self.request_status(N_("entity.created"), ident=ident)
        if self.rebels is not None:
            self.show_tab(TAB_REBELS)
        self._offer_unit_names(ref)
        return True

    def _offer_unit_names(self, ref) -> None:
        from ...core.schema import UnitNamesSlot
        from ...core.schema.companions import EditContext

        slot = next((c for c in self.schema.companions if isinstance(c, UnitNamesSlot)), None)
        entities = self.session.entities
        if slot is None or entities is None:
            return
        record = entities.open(ref)
        ctx = EditContext(entities.ws, entities.index, entities.loc)
        candidates = slot.candidates(ctx, record)
        if not candidates:
            return
        dialog = UnitNamesDialog(ref.ident, candidates, self)
        if self.exec_dialog(dialog) != QDialog.DialogCode.Accepted or not dialog.chosen():
            return
        with self.session.edit(N_("entity.unit_names_undo"), ident=ref.ident):
            slot.add_to(ctx, entities.open(ref), dialog.chosen())

    def delete(self, ref) -> bool:
        """Borra ``ref`` en una transacción; con usos, el borrado se bloquea y se enseñan."""
        entities = self.session.entities
        if entities is None or self.session.is_read_only():
            return False
        try:
            with self.session.edit(f"undo.delete_{ref.kind}", kind=ref.kind, ident=ref.ident):
                entities.delete(ref)
        except EntityInUseError as exc:
            self.exec_dialog(UsesDialog(ref.ident, exc.uses, self))
            self.request_status(N_("entity.delete_blocked_status"), ident=ref.ident, count=len(exc.uses))
            return False
        except (ReadOnlySchemaError, PermissionError, KeyError) as exc:
            self.request_status(N_("entity.delete_failed"), reason=str(exc))
            return False
        self.refresh()
        self.request_status(N_("entity.deleted"), ident=ref.ident)
        return True

    # --- renombrar y grupos (§15, §14.13) ---------------------------------------------------------

    def ask_rename(self, ref) -> bool:
        """«Renombrar»: enseña el plan (archivos, usos, claves de texto) y, si se acepta, renombra."""
        entities = self.session.entities
        if entities is None or ref is None or self.session.is_read_only():
            return False
        self.commit_pending()
        dialog = RenameEntityDialog(entities, ref, parent=self)
        if self.exec_dialog(dialog) != QDialog.DialogCode.Accepted:
            return False
        return self.rename(ref, dialog.new_ident())

    def rename(self, ref, new_ident: str) -> bool:
        """Renombrado seguro de ``ref`` (definición, usos, compañeros y claves de texto) en una transacción."""
        entities = self.session.entities
        if entities is None or self.session.is_read_only():
            return False
        try:
            with self.session.edit(f"undo.rename_{ref.kind}", kind=ref.kind, ident=ref.ident, new=new_ident):
                renamed = entities.rename(ref, new_ident)
        except InvalidIdentError as exc:
            self.request_status(N_("entity.rename.failed"), reason=tr(
                IDENT_MESSAGES.get(exc.code, "entity.ident.bad_chars"), ident=new_ident))
            return False
        except (ReadOnlySchemaError, PermissionError, KeyError, FileNotFoundError) as exc:
            reason = exc.message(language()) if hasattr(exc, "message") else str(exc)
            self.request_status(N_("entity.rename.failed"), reason=reason)
            return False
        self.refresh()
        self.navigator.select(renamed)
        self.request_status(N_("entity.rename.done"), ident=ref.ident, new=new_ident)
        return True

    def ask_move(self, ref) -> bool:
        """«Mover a otro grupo» (culturas): pide el grupo y mueve el bloque con su texto intacto."""
        entities = self.session.entities
        if entities is None or ref is None or ref.kind != self.schema.kind:
            return False
        try:
            current = entities.parent(ref)
        except (KeyError, FileNotFoundError):
            current = None
        dialog = MoveGroupDialog(ref.ident, entities.groups(ref.kind), current, parent=self)
        if self.exec_dialog(dialog) != QDialog.DialogCode.Accepted or dialog.group() is None:
            return False
        return self.move_to_group(ref, dialog.group())

    def move_to_group(self, ref, group: str) -> bool:
        entities = self.session.entities
        if entities is None or self.session.is_read_only():
            return False
        self.commit_pending()
        try:
            with self.session.edit(f"undo.move_{ref.kind}", kind=ref.kind, ident=ref.ident, group=group):
                moved = entities.move_to_group(ref, group)
        except InvalidIdentError as exc:
            self.request_status(N_("entity.move.failed"), reason=tr(
                IDENT_MESSAGES.get(exc.code, "entity.ident.no_group"), ident=group))
            return False
        except (ReadOnlySchemaError, PermissionError, KeyError, ValueError, FileNotFoundError) as exc:
            self.request_status(N_("entity.move.failed"), reason=str(exc))
            return False
        self.refresh()
        self.navigator.select(moved)
        self.request_status(N_("entity.move.done"), ident=ref.ident, group=group)
        return True

    def ask_new_group(self) -> bool:
        """«Nuevo grupo» (culturas): pide el id y crea el grupo vacío con su esquema."""
        from ...core.schema import registry

        entities = self.session.entities
        kind = None if entities is None else entities.group_kind(self.schema.kind)
        if kind is None:
            return False
        schema = registry.get(kind)
        existing = [summary.ref for summary in entities.list(kind)]
        dialog = NewEntityDialog(schema, existing, [], parent=self)
        if self.exec_dialog(dialog) != QDialog.DialogCode.Accepted:
            return False
        ident, base, _group = dialog.result_values()
        return self.create_group(ident, base)

    def create_group(self, ident: str, base=None) -> bool:
        entities = self.session.entities
        kind = None if entities is None else entities.group_kind(self.schema.kind)
        if kind is None or self.session.is_read_only():
            return False
        try:
            if base is not None:
                with self.session.edit(f"undo.duplicate_{kind}", kind=kind, ident=ident):
                    ref = entities.duplicate(base, ident)
            else:
                with self.session.edit(f"undo.create_{kind}", kind=kind, ident=ident):
                    ref = entities.create(kind, ident, {})
        except InvalidIdentError as exc:
            self.request_status(N_("entity.create_failed"), reason=tr(
                IDENT_MESSAGES.get(exc.code, "entity.ident.bad_chars"), ident=ident))
            return False
        except (ReadOnlySchemaError, PermissionError, FileNotFoundError, ValueError) as exc:
            self.request_status(N_("entity.create_failed"), reason=str(exc))
            return False
        self.refresh()
        self.navigator.select(ref)
        self.request_status(N_("entity.created"), ident=ident)
        return True

    def restore(self, ref) -> bool:
        entities = self.session.entities
        if entities is None:
            return False
        try:
            with self.session.edit("undo.restore_vanilla", kind=ref.kind, ident=ref.ident):
                entities.restore_vanilla(ref)
        except (KeyError, PermissionError, FileNotFoundError) as exc:
            self.request_status(N_("entity.restore_failed"), reason=str(exc))
            return False
        self.refresh()
        self.request_status(N_("entity.restored"), ident=ref.ident)
        return True


def entity_section_factory(schema, view: str | None = None):
    """``factory`` de la ``SectionSpec`` que genera el registro (``ui/halls/registry.py``)."""

    def factory(session):
        return EntityEditorPage(session, schema, view)

    return factory

