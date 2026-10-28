"""Navegador de entidades (wizard §13.5): lista con filtro, cintas de origen y los botones Nuevo, Duplicar,
Borrar y Restaurar.

La lista sale de ``session.entities.list(kind, view=...)``: la vista efectiva, con lo sin guardar. En un
``GroupedIn`` de nivel 1 (culturas) es un árbol por grupo; elegir un grupo emite su ``RecordRef`` del esquema del
grupo (``culture_group``). Los botones solo emiten señales: el ``EntityEditorPage`` hace las transacciones.
"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.schema import RecordRef
from ...core.schema.layouts import GroupedIn
from ...core.vfs import LayerKind
from ...i18n import N_, tr, translator
from ..widgets import mark_data

ORIGIN_KEYS = {
    "game": N_("entity.origin.game"),
    "mod": N_("entity.origin.mod"),
    "mod_over_game": N_("entity.origin.mod_over_game"),
    "new": N_("entity.origin.new"),
}

_REF_ROLE = Qt.ItemDataRole.UserRole


def origin_of_rel(session, rel) -> str:
    """Cinta de origen de un archivo sin abrir registros (barato para toda la lista)."""
    project = session.project
    if project is None:
        return "game"
    handle = project.ws.peek(rel)
    if handle is not None and not handle.deleted:
        if handle.origin is None:
            return "new"
        if handle.origin.layer.kind is not LayerKind.MOD:
            return "game"
    elif handle is not None and handle.deleted:
        return "game"
    entry = project.vfs.resolve(rel)
    if entry is None:
        return "new"
    if entry.layer.kind is not LayerKind.MOD:
        return "game"
    if any(other.layer.kind is not LayerKind.MOD for other in project.vfs.stack(rel)):
        return "mod_over_game"
    return "mod"


class EntityNavigator(QWidget):
    """API: ``refresh()``, ``current_ref()``, ``select(ref)``; señales ``current_changed(ref)``,
    ``new_requested()``, ``duplicate_requested(ref)``, ``delete_requested(ref)`` y ``restore_requested(ref)``."""

    current_changed = Signal(object)
    new_requested = Signal()
    duplicate_requested = Signal(object)
    delete_requested = Signal(object)
    restore_requested = Signal(object)

    def __init__(self, session, schema, view: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.schema = schema
        self.view = view
        self.grouped = isinstance(schema.layout, GroupedIn) and schema.layout.level > 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("entityFilter")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        outer.addWidget(self.filter_edit)
        self.tree = mark_data(QTreeWidget())
        self.tree.setObjectName("entityList")
        self.tree.setColumnCount(2)
        self.tree.setRootIsDecorated(self.grouped)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setStretchLastSection(True)
        self.tree.header().setSectionResizeMode(0, self.tree.header().ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(self._on_current)
        outer.addWidget(self.tree, 1)
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        self.new_button = QPushButton()
        self.new_button.setObjectName("entityNew")
        self.new_button.clicked.connect(self.new_requested)
        self.duplicate_button = QPushButton()
        self.duplicate_button.setObjectName("entityDuplicate")
        self.duplicate_button.clicked.connect(lambda: self._emit_for(self.duplicate_requested))
        self.delete_button = QPushButton()
        self.delete_button.setObjectName("entityDelete")
        self.delete_button.clicked.connect(lambda: self._emit_for(self.delete_requested))
        self.restore_button = QPushButton()
        self.restore_button.setObjectName("entityRestore")
        self.restore_button.clicked.connect(lambda: self._emit_for(self.restore_requested))
        for button in (self.new_button, self.duplicate_button, self.delete_button, self.restore_button):
            buttons.addWidget(button)
        outer.addLayout(buttons)
        self._summaries = []
        translator().languageChanged.connect(self._on_language_changed)
        self.retranslate()
        self._update_buttons()

    def _on_language_changed(self, code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.filter_edit.setPlaceholderText(tr("entity.filter"))
        self.tree.setHeaderLabels([tr("entity.col.id"), tr("entity.col.origin")])
        self.new_button.setText(tr("entity.new"))
        self.new_button.setToolTip(tr("entity.new_tooltip"))
        self.duplicate_button.setText(tr("entity.duplicate"))
        self.duplicate_button.setToolTip(tr("entity.duplicate_tooltip"))
        self.delete_button.setText(tr("entity.delete"))
        self.restore_button.setText(tr("entity.restore"))
        self.restore_button.setToolTip(tr("entity.restore_tooltip"))
        root = self.tree.invisibleRootItem()
        for item in self._items(root):
            origin = item.data(1, _REF_ROLE)
            if origin:
                item.setText(1, tr(ORIGIN_KEYS[origin]))

    def _items(self, parent):
        for index in range(parent.childCount()):
            child = parent.child(index)
            yield child
            yield from self._items(child)

    # --- lista ------------------------------------------------------------------------------------

    def refresh(self) -> None:
        """Vuelve a leer la lista (vista efectiva) conservando la selección si sigue existiendo."""
        current = self.current_ref()
        entities = getattr(self.session, "entities", None)
        self._summaries = [] if entities is None else entities.list(self.schema.kind, view=self.view)
        with QSignalBlocker(self.tree):
            self.tree.clear()
            groups: dict[str, QTreeWidgetItem] = {}
            for summary in self._summaries:
                parent = self.tree.invisibleRootItem()
                if self.grouped and summary.parent:
                    parent = groups.get(summary.parent)
                    if parent is None:
                        parent = QTreeWidgetItem(self.tree, [summary.parent, ""])
                        parent.setData(0, _REF_ROLE, RecordRef(self._group_kind(), summary.parent, summary.rel))
                        parent.setExpanded(False)
                        groups[summary.parent] = parent
                item = QTreeWidgetItem(parent, [summary.ref.ident, ""])
                origin = origin_of_rel(self.session, summary.rel)
                item.setData(0, _REF_ROLE, RecordRef(summary.ref.kind, summary.ref.ident, summary.rel))
                item.setData(1, _REF_ROLE, origin)
                item.setText(1, tr(ORIGIN_KEYS[origin]))
        self._apply_filter(self.filter_edit.text())
        if current is not None and self.select(current, emit=False):
            pass
        elif self.tree.topLevelItemCount():
            first = self.tree.topLevelItem(0)
            self.tree.setCurrentItem(first.child(0) if self.grouped and first.childCount() else first)
        else:
            self.current_changed.emit(None)
        self._update_buttons()

    def _group_kind(self) -> str:
        from ...core.schema import registry

        for schema in registry.all_schemas():
            layout = schema.layout
            if isinstance(layout, GroupedIn) and layout.level == 0 and layout.path == self.schema.layout.path:
                return schema.kind
        return self.schema.kind

    def count(self) -> int:
        return len(self._summaries)

    def idents(self) -> list[str]:
        return [summary.ref.ident for summary in self._summaries]

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        root = self.tree.invisibleRootItem()
        for index in range(root.childCount()):
            top = root.child(index)
            if self.grouped and top.childCount():
                any_visible = False
                for child_index in range(top.childCount()):
                    child = top.child(child_index)
                    visible = not needle or needle in child.text(0).lower() or needle in top.text(0).lower()
                    child.setHidden(not visible)
                    any_visible |= visible
                top.setHidden(not any_visible)
                if needle and any_visible:
                    top.setExpanded(True)
            else:
                top.setHidden(bool(needle) and needle not in top.text(0).lower())

    def current_ref(self) -> RecordRef | None:
        item = self.tree.currentItem()
        return None if item is None else item.data(0, _REF_ROLE)

    def select(self, ref, *, emit: bool = True) -> bool:
        """Selecciona ``ref`` (por tipo e id); False si no está en la lista."""
        for item in self._items(self.tree.invisibleRootItem()):
            data = item.data(0, _REF_ROLE)
            if data is not None and data.ident == ref.ident and data.kind == ref.kind:
                if item.parent() is not None:
                    item.parent().setExpanded(True)
                if not emit:
                    with QSignalBlocker(self.tree):
                        self.tree.setCurrentItem(item)
                    self._update_buttons()
                else:
                    self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                return True
        return False

    def _on_current(self, current, previous) -> None:
        self._update_buttons()
        self.current_changed.emit(None if current is None else current.data(0, _REF_ROLE))

    def _emit_for(self, signal) -> None:
        ref = self.current_ref()
        if ref is not None:
            signal.emit(ref)

    def _update_buttons(self) -> None:
        ref = self.current_ref()
        writable = (self.session.project is not None and not self.session.is_read_only() and self.schema.editable)
        own = ref is not None and ref.kind == self.schema.kind
        self.new_button.setEnabled(writable)
        self.duplicate_button.setEnabled(writable and own)
        self.delete_button.setEnabled(writable and own)
        entities = getattr(self.session, "entities", None)
        can_restore = False
        if writable and own and entities is not None:
            try:
                can_restore = entities.can_restore_vanilla(ref)
            except Exception:  # noqa: BLE001 - un registro que ya no está
                can_restore = False
        self.restore_button.setEnabled(can_restore)
