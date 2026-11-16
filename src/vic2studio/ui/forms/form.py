"""Formulario generado de un esquema (wizard §13.6): ``FormBuilder`` y ``EntityForm``.

Cada ``Section`` del esquema es una tarjeta de pergamino plegable con un ``QFormLayout``; cada ``Field``, una fila
con la etiqueta «Nombre (clave)» (P4) y el editor de su tipo (``EDITORS``). Los campos ``advanced`` se ocultan
en modo sencillo, los de ``visible_if`` según el valor del que dependen y los de una variante (``unit``: land o
naval) según el valor del discriminador. Las claves dinámicas son casillas (``checklist``), una tabla de bienes
(``grid`` de un ``Group``: ``GoodsAmountsField``) o una tabla clave/valor (catálogo abierto). Los bloques de guion
se editan como código: su botón pide la pestaña Código.

**Cada edición es una transacción** con ``Session.edit(etiqueta, merge_key="form.<kind>.<id>.<campo>")``: teclear
en el mismo campo se funde en un solo paso de deshacer, igual que el descriptor. El formulario nunca guarda
nodos: lee y escribe a través de ``session.entities`` con la ``RecordRef`` (D3, §0.2), y se vuelve a enlazar
cuando el documento cambia (deshacer, la pestaña Código, otro formulario).
"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.clausewitz.diagnostics import EditError
from ...core.schema.fields import (
    MISSING,
    OPEN_CATALOG,
    Children,
    DynamicKeys,
    Field,
    Group,
    Opaque,
    Script,
    Section,
    field_text_key,
)
from ...i18n import N_, tr, translator
from ..pickers import GoodsAmountsField
from ..widgets import ParchmentCard, mark_data
from .editors import CodeOnlyEditor, FieldEditor, FieldState, editor_for

SIMPLE, ADVANCED = "simple", "advanced"
UNDO_EDIT = N_("forms.undo_edit")


def has_text(key: str) -> bool:
    return key in translator().catalog()


class SectionCard(ParchmentCard):
    """Una ``Section`` del esquema: título que pliega y despliega, y el contenido en un ``QFormLayout``."""

    def __init__(self, title_key: str, collapsed: bool = False, parent: QWidget | None = None):
        super().__init__(padding=10, parent=parent)
        self.title_key = title_key
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        self.toggle = QToolButton()
        self.toggle.setObjectName("sectionToggle")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(not collapsed)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setProperty("role", "title")
        self.toggle.toggled.connect(self._on_toggled)
        outer.addWidget(self.toggle)
        self.content = QWidget()
        self.form = QFormLayout(self.content)
        self.form.setContentsMargins(4, 0, 4, 0)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        outer.addWidget(self.content)
        self._on_toggled(self.toggle.isChecked())

    def _on_toggled(self, expanded: bool) -> None:
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.content.setVisible(expanded)

    def expand(self) -> None:
        self.toggle.setChecked(True)

    def retranslate(self) -> None:
        self.toggle.setText(tr(self.title_key))


class _Row:
    """Una fila del formulario: el campo, su etiqueta, su editor y su tarjeta."""

    def __init__(self, item, label: QLabel, editor: QWidget, card: SectionCard, variant: str | None):
        self.item = item
        self.label = label
        self.editor = editor
        self.card = card
        self.variant = variant

    @property
    def key(self) -> str:
        return getattr(self.item, "key", None) or getattr(self.item, "name", "")


class DynamicChecklist(QWidget):
    """Casillas de un ``DynamicKeys`` de sí/no (ideologías de un gobierno): una por clave del catálogo."""

    toggled = Signal(str, bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.checks: dict[str, QCheckBox] = {}

    def set_items(self, names: list[str], values: dict) -> None:
        for check in self.checks.values():
            check.deleteLater()
        self.checks = {}
        for position, name in enumerate(sorted(set(names) | set(values))):
            check = mark_data(QCheckBox(name))
            check.setObjectName(f"dynamic_{name}")
            check.setChecked(bool(values.get(name)))
            check.toggled.connect(lambda on, n=name: self.toggled.emit(n, on))
            self.grid.addWidget(check, position // 3, position % 3)
            self.checks[name] = check

    def set_values(self, values: dict) -> None:
        for name, check in self.checks.items():
            with QSignalBlocker(check):
                check.setChecked(bool(values.get(name)))


class DynamicTable(QWidget):
    """Tabla clave → valor de un catálogo abierto (efectos de un modificador): editar, añadir y quitar filas."""

    changed = Signal(object)    # dict completo

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self.table = mark_data(QTableWidget(0, 2))
        self.table.setObjectName("dynamicTable")
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(lambda _item: self._emit())
        self.table.setMaximumHeight(180)
        outer.addWidget(self.table)
        row = QHBoxLayout()
        self.key_edit = mark_data(QLineEdit())
        self.key_edit.setObjectName("dynamicKey")
        row.addWidget(self.key_edit, 1)
        self.add_button = QPushButton()
        self.add_button.setObjectName("dynamicAdd")
        self.add_button.clicked.connect(self._add)
        row.addWidget(self.add_button)
        self.remove_button = QPushButton()
        self.remove_button.setObjectName("dynamicRemove")
        self.remove_button.clicked.connect(self._remove)
        row.addWidget(self.remove_button)
        outer.addLayout(row)
        self._filling = False
        self.retranslate()

    def retranslate(self) -> None:
        self.table.setHorizontalHeaderLabels([tr("forms.dynamic.key"), tr("forms.dynamic.value")])
        self.key_edit.setPlaceholderText(tr("forms.dynamic.new_key"))
        self.add_button.setText(tr("forms.dynamic.add"))
        self.remove_button.setText(tr("forms.dynamic.remove"))

    def set_values(self, values: dict) -> None:
        self._filling = True
        try:
            self.table.setRowCount(0)
            for key, value in values.items():
                self._append(key, value)
        finally:
            self._filling = False

    def _append(self, key, value) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        item = QTableWidgetItem(key)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 0, item)
        self.table.setItem(row, 1, QTableWidgetItem(f"{value:g}" if isinstance(value, float) else str(value)))

    def values(self) -> dict:
        result = {}
        for row in range(self.table.rowCount()):
            key, value = self.table.item(row, 0), self.table.item(row, 1)
            if key is None or value is None:
                continue
            try:
                result[key.text()] = float(value.text().replace(",", "."))
            except ValueError:
                continue
        return result

    def _add(self) -> None:
        key = self.key_edit.text().strip()
        if not key or key in self.values():
            return
        self.key_edit.clear()
        self._filling = True
        try:
            self._append(key, 0.0)
        finally:
            self._filling = False
        self._emit()

    def _remove(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self._emit()

    def _emit(self) -> None:
        if not self._filling:
            self.changed.emit(self.values())


class EntityForm(QWidget):
    """El formulario de un esquema. ``bind(ref)`` lo enlaza a un registro; ``focus_field(ruta)`` lleva a un campo."""

    record_changed = Signal(object)          # RecordRef tras una edición
    code_requested = Signal(str)             # clave del campo que se edita como código
    status_requested = Signal(str, object)

    def __init__(self, session, schema, *, mode: str = SIMPLE, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.schema = schema
        self.mode = mode
        self.ref = None
        self._applying = False
        self.rows: list[_Row] = []
        self.cards: list[SectionCard] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("formScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        holder = QWidget()
        self.column = QVBoxLayout(holder)
        self.column.setContentsMargins(0, 0, 6, 0)
        self.column.setSpacing(8)
        self.scroll.setWidget(holder)
        outer.addWidget(self.scroll)
        self._build_items(schema.fields, None)
        variants = schema.variants
        if variants is not None:
            for value, items in variants.cases.items():
                self._build_items(items, value)
        self.column.addStretch(1)
        session.documentsChanged.connect(self._on_documents_changed)
        translator().languageChanged.connect(self._on_language_changed)
        self.retranslate()
        self._apply_visibility(None)

    # --- construcción -----------------------------------------------------------------------------

    def _build_items(self, items, variant: str | None) -> None:
        loose = [item for item in items if not isinstance(item, Section)]
        if loose:
            self._build_card(f"schema.{self.schema.kind}.title", loose, variant, False)
        for item in items:
            if isinstance(item, Section):
                self._build_card(f"schema.{self.schema.kind}.section.{item.name}", item.items, variant,
                                 item.collapsed)

    def _build_card(self, title_key: str, items, variant, collapsed: bool) -> None:
        card = SectionCard(title_key, collapsed)
        card.setProperty("variant", variant)
        added = False
        for item in items:
            row = self._build_row(item, card, variant)
            if row is not None:
                self.rows.append(row)
                card.form.addRow(row.label, row.editor)
                added = True
        if added:
            self.cards.append(card)
            self.column.addWidget(card)
            if self.schema.kind == "bookmark" and title_key.endswith(".section.camera"):
                self._add_map_view_button(card)
        else:
            card.deleteLater()

    def _add_map_view_button(self, card: SectionCard) -> None:
        """«Usar la vista actual del mapa» (wizard §16.3): ``cameraX``/``cameraY`` del bookmark = el centro del
        lienzo de la sala Mapa, en un solo paso de deshacer."""
        self.map_view_button = QPushButton()
        self.map_view_button.setObjectName("useMapView")
        self.map_view_button.clicked.connect(self.use_map_view)
        card.form.addRow(QLabel(), self.map_view_button)

    def use_map_view(self) -> bool:
        map_session = getattr(self.session, "map", None)
        center = None if map_session is None else map_session.view_center
        if center is None or self.ref is None:
            self.status_requested.emit(N_("forms.map_view.none"), {})
            return False
        x, y = center

        def apply(record) -> None:
            record.set("cameraX", int(x))
            record.set("cameraY", int(y))

        done = self._edit("cameraX", apply)
        if done:
            self.status_requested.emit(N_("forms.map_view.done"), {"x": int(x), "y": int(y)})
        return done

    def _build_row(self, item, card: SectionCard, variant) -> _Row | None:
        kind = self.schema.kind
        label = QLabel()
        label.setWordWrap(True)
        if isinstance(item, Field):
            editor = editor_for(item.type, session=self.session, kind=kind, key=item.key, ui=item.ui)
            if item.default is not MISSING:
                editor.set_default(item.default)
            editor.value_committed.connect(lambda value, key=item.key: self._commit_field(key, value))
        elif isinstance(item, (Script, Opaque)):
            editor = CodeOnlyEditor(None, session=self.session, kind=kind, key=item.key)
            editor.code_requested.connect(self.code_requested)
        elif isinstance(item, DynamicKeys):
            if item.key_kind == OPEN_CATALOG or item.widget == "table":
                editor = DynamicTable()
                editor.changed.connect(lambda values, name=item.name: self._commit_dynamic(name, values))
            else:
                editor = DynamicChecklist()
                editor.toggled.connect(lambda key, on, name=item.name: self._commit_dynamic(name, {key: on},
                                                                                            partial=True))
        elif isinstance(item, Group) and item.dynamic is not None:
            editor = GoodsAmountsField(self._catalog(item.dynamic.key_kind))
            editor.value_committed.connect(lambda values, name=item.dynamic.name: self._commit_dynamic(name, values))
        elif isinstance(item, Children):
            return None
        else:
            return None
        editor.setObjectName(f"row_{getattr(item, 'key', None) or getattr(item, 'name', '')}")
        return _Row(item, label, editor, card, variant)

    def _catalog(self, kind: str) -> list[str]:
        index = getattr(self.session, "index", None)
        if index is None:
            return []
        try:
            return list(index.names(kind))
        except Exception:  # noqa: BLE001
            return []

    # --- textos -----------------------------------------------------------------------------------

    def _label_of(self, row: _Row) -> tuple[str, str]:
        kind = self.schema.kind
        item = row.item
        if isinstance(item, (DynamicKeys, Group)):
            name = item.name if isinstance(item, DynamicKeys) else item.dynamic.name
            return tr(f"schema.{kind}.dynamic.{name}"), ""
        base = field_text_key(kind, item.key)
        help_key = f"{base}.help"
        return tr("forms.label", label=tr(base), key=item.key), tr(help_key) if has_text(help_key) else ""

    def _on_language_changed(self, code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        button = getattr(self, "map_view_button", None)
        if button is not None:
            button.setText(tr("forms.map_view"))
            button.setToolTip(tr("forms.map_view.tooltip"))
        for card in self.cards:
            card.retranslate()
        for row in self.rows:
            text, help_text = self._label_of(row)
            row.label.setText(text)
            row.label.setToolTip(help_text)
            retranslate = getattr(row.editor, "retranslate", None)
            if retranslate is not None:
                retranslate()

    # --- enlace -----------------------------------------------------------------------------------

    def record(self):
        entities = getattr(self.session, "entities", None)
        if entities is None or self.ref is None:
            return None
        try:
            return entities.open(self.ref)
        except (KeyError, FileNotFoundError):
            return None

    def bind(self, ref, date=None) -> None:
        """Enlaza el formulario a ``ref`` (o lo vacía con None) y rellena los valores. ``date``: fecha de trabajo
        de la historia (iteración 5)."""
        self.ref = ref
        record = self.record()
        read_only = self.session.is_read_only() or record is None or not self.schema.editable
        problems = {}
        if record is not None:
            entities = self.session.entities
            for problem in record.issues(entities.check_context()):
                if problem.field:
                    problems.setdefault(problem.field[0], []).append(problem)
        ident_field = self.schema.ident.value if self.schema.ident.mode == "field" else None
        for row in self.rows:
            self._fill_row(row, record, problems)
            # El campo que da el id (``name`` de un bookmark) no se cambia aquí: sería renombrar (wizard §15).
            locked = read_only or (ident_field is not None and row.key == ident_field)
            setter = getattr(row.editor, "set_read_only", None)
            if setter is not None:
                setter(locked)
            row.editor.setEnabled(not locked)
        self._apply_visibility(record)

    def _fill_row(self, row: _Row, record, problems: dict) -> None:
        item = row.item
        if record is None:
            if isinstance(row.editor, FieldEditor):
                row.editor.set_value(None)
            return
        if isinstance(item, Field):
            value = record.get(item.key, None) if record.node(item.key) is not None else None
            origin = "default" if record.node(item.key) is None else "mod"
            row.editor.set_value(value, FieldState(origin, None, tuple(problems.get(item.key, ()))))
        elif isinstance(item, (Script, Opaque)):
            row.editor.set_value(record.node(item.key))
        elif isinstance(item, DynamicKeys):
            values = record.dynamic(item.name)
            if isinstance(row.editor, DynamicChecklist):
                row.editor.set_items(self._catalog(item.key_kind), values)
            else:
                row.editor.set_values(values)
        elif isinstance(item, Group):
            row.editor.set_value(record.dynamic(item.dynamic.name))

    def _apply_visibility(self, record) -> None:
        variant_value = record._variant_value() if record is not None else None
        for row in self.rows:
            visible = row.variant is None or row.variant == variant_value
            item = row.item
            if isinstance(item, Field):
                if item.advanced and self.mode == SIMPLE:
                    visible = False
                if item.visible_if is not None and record is not None and not item.visible_if.evaluate(record):
                    visible = False
            row.label.setVisible(visible)
            row.editor.setVisible(visible)
        for card in self.cards:
            variant = card.property("variant")
            card.setVisible(variant is None or variant == variant_value)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._apply_visibility(self.record())

    def commit_pending(self) -> None:
        for row in self.rows:
            pending = getattr(row.editor, "commit_pending", None)
            if pending is not None and row.editor.isVisible():
                pending()

    def row(self, key: str) -> _Row | None:
        return next((row for row in self.rows if row.key == key), None)

    def editor(self, key: str):
        row = self.row(key)
        return None if row is None else row.editor

    def focus_field(self, path) -> bool:
        """Lleva al campo de ``path`` (``("duration",)``): despliega su tarjeta, pasa a modo avanzado si hace falta
        y le da el foco. False si el esquema no tiene ese campo en el formulario."""
        if not path:
            return False
        row = self.row(path[0])
        if row is None:
            return False
        if isinstance(row.item, Field) and row.item.advanced and self.mode == SIMPLE:
            self.set_mode(ADVANCED)
        row.card.expand()
        row.editor.setVisible(True)
        row.label.setVisible(True)
        self.scroll.ensureWidgetVisible(row.editor)
        target = row.editor.focusProxy() or row.editor
        children = [w for w in row.editor.findChildren(QWidget) if w.focusPolicy() != Qt.FocusPolicy.NoFocus]
        (children[0] if children else target).setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    # --- edición ----------------------------------------------------------------------------------

    def _merge_key(self, key: str) -> str:
        return f"form.{self.schema.kind}.{self.ref.ident}.{key}"

    def _edit(self, key: str, apply) -> bool:
        if self.ref is None or self.session.project is None or self.session.is_read_only():
            return False
        self._applying = True
        try:
            with self.session.edit(UNDO_EDIT, merge_key=self._merge_key(key), field=key, ident=self.ref.ident):
                record = self.session.entities.open(self.ref)
                apply(record)
        except (ValueError, KeyError, EditError, PermissionError, FileNotFoundError) as exc:
            self.status_requested.emit(N_("forms.edit_failed"), {"field": key, "error": str(exc)})
            self.bind(self.ref)
            return False
        finally:
            self._applying = False
        self.bind(self.ref)
        self.record_changed.emit(self.ref)
        return True

    def _commit_field(self, key: str, value) -> bool:
        return self._edit(key, lambda record: record.set(key, value))

    def _commit_dynamic(self, name: str, values: dict, *, partial: bool = False) -> bool:
        def apply(record) -> None:
            current = record.dynamic(name)
            for key, value in values.items():
                if current.get(key) != value:
                    record.set_dynamic(name, key, value)
            if not partial:
                for key in current:
                    if key not in values:
                        record.set_dynamic(name, key, None)

        return self._edit(name, apply)

    def _on_documents_changed(self, rels) -> None:
        if self._applying or self.ref is None:
            return
        record_rel = self.ref.rel
        keys = {getattr(rel, "key", str(rel)) for rel in rels}
        if record_rel is None or record_rel.key in keys:
            self.bind(self.ref)


class FormBuilder:
    """Construye el ``EntityForm`` de un esquema (wizard §13.6)."""

    def __init__(self, session, *, mode: str = SIMPLE) -> None:
        self.session = session
        self.mode = mode

    def build(self, schema, ref=None, *, date=None) -> EntityForm:
        form = EntityForm(self.session, schema, mode=self.mode)
        if ref is not None:
            form.bind(ref, date)
        return form
