"""Constructor de condiciones: el árbol TODAS/ALGUNA/NINGUNA sobre un ``ScriptTree`` (wizard §14.7).

``ScriptTreeModel`` adapta un ``ScriptTree`` a las vistas de Qt sin copiar el árbol: cada índice lleva el
``ScriptNode`` y se reconstruye cuando cambia ``ScriptTree.version`` o llega un árbol nuevo. ``TriggerBuilder``
lo pinta con corchetes de color por grupo (AND, OR, NOT), una fila por nodo con el control de su tipo
(``NodeForm``) y los botones «+ Condición», «+ Ámbito», «Envolver en…», «Texto» y «Quitar». Los nodos sin
catalogar se ven como «Clave no catalogada» con su código y se conservan.

Cada operación es **una** transacción (``Session.edit``, un paso de deshacer): el constructor vuelve a pedir el
árbol al registro, localiza el nodo por su ruta, aplica el cambio del núcleo y se vuelve a enlazar. Con un árbol
puesto a mano (``set_tree``, pruebas con el árbol falso) las operaciones se aplican directamente. Un valor que
no encaja o un documento de solo texto no cambian nada y se cuentan por ``status_requested``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QStyledItemDelegate,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ...core.clausewitz.nodes import Scalar
from ...core.script.scopes import LOGIC_KEYS, Scope, ScriptKind
from ...i18n import N_, language, tr, translator
from .. import theme
from ..widgets import make_icon, mark_data
from ..widgets.flow import FlowLayout

# Roles del modelo, además de ``DisplayRole`` (la frase del nodo) y ``ToolTipRole`` (sus problemas).
NODE_ROLE = Qt.ItemDataRole.UserRole + 1         # ScriptNode
FORM_ROLE = Qt.ItemDataRole.UserRole + 2         # NodeForm
PROBLEMS_ROLE = Qt.ItemDataRole.UserRole + 3     # tuple[Problem, ...] del nodo (sin sus hijos)
PATH_ROLE = Qt.ItemDataRole.UserRole + 4         # tuple[int, ...]: ScriptNode.path

# Color del corchete de cada grupo lógico (y de los ámbitos), del tema.
BRACKET_COLORS = {"AND": "bronze", "OR": "syntax_string", "NOT": "danger", "scope": "syntax_keyword"}
WRAP_KEYS = {"AND": N_("script_ui.wrap_and"), "OR": N_("script_ui.wrap_or"), "NOT": N_("script_ui.wrap_not")}
UNDO_KEYS = {
    "add": N_("script_ui.undo.add"), "value": N_("script_ui.undo.value"), "wrap": N_("script_ui.undo.wrap"),
    "unwrap": N_("script_ui.undo.unwrap"), "remove": N_("script_ui.undo.remove"),
    "move": N_("script_ui.undo.move"), "text": N_("script_ui.undo.text"),
}
REJECTED_KEY = N_("script_ui.rejected")


def phrase_language() -> str:
    """El idioma de las frases del núcleo: el de la interfaz si es ES o EN; si no (seudolocal), inglés."""
    lang = language()
    return lang if lang in ("es", "en") else "en"


def _form_name(node) -> str:
    return getattr(getattr(node, "form", None), "name", "")


def parse_value(value_type, text: str):
    """El valor de Python que ``value_type`` lee de ``text`` (``ValueError`` si no encaja). Los tipos del
    catálogo leen un nodo del CST, así que se les da un escalar."""
    text = (text or "").strip()
    if not text:
        raise ValueError("valor vacío")
    if value_type is None:
        return text
    return value_type.read(Scalar(text, False))


def value_text(value) -> str:
    """El valor de un nodo como se escribe en el campo de edición."""
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        return f"{value:.1f}"
    return str(value)


# --- binding: de un registro a su árbol -------------------------------------------------------------------


@dataclass(frozen=True)
class ScriptBinding:
    """De dónde sale el árbol de un constructor: un registro y la ruta de su campo de guion.

    ``path`` alterna claves de grupo e índices de repetición y acaba en la clave del ``Script``:
    ``("trigger",)``, ``("option", 1, REST)``, ``("mean_time_to_happen", "modifier", 0, REST)``.
    """

    ref: object                                  # RecordRef
    path: tuple[str | int, ...]


def record_at(record, path, *, create: bool = False):
    """La vista de grupo de ``record`` en ``path`` (claves e índices, sin la clave final). ``create`` añade
    un grupo que falta (mutación: dentro de una transacción). ``KeyError`` si no existe."""
    steps = list(path)
    position = 0
    while position < len(steps):
        name = steps[position]
        index = 0
        if position + 1 < len(steps) and isinstance(steps[position + 1], int):
            index = steps[position + 1]
            position += 1
        try:
            record = record.group(name, index)
        except KeyError:
            if not create or index != len(record.groups(name)):
                raise
            record = record.add_group(name, {})
        position += 1
    return record


def resolve_tree(session, binding: ScriptBinding, *, create: bool = False):
    """El ``ScriptTree`` del campo de ``binding`` (None si el bloque no existe y no se crea)."""
    entities = getattr(session, "entities", None)
    if entities is None or binding is None:
        return None
    record = entities.open(binding.ref)
    *groups, key = binding.path
    try:
        record = record_at(record, groups, create=create)
    except KeyError:
        return None
    return record.script(key, create=create)


# --- modelo -------------------------------------------------------------------------------------------------


class ScriptTreeModel(QAbstractItemModel):
    """Modelo jerárquico de un ``ScriptTree``. Una columna. La raíz invisible es el AND implícito.

    ``set_tree`` reinicia el modelo; ``refresh`` lo hace si ``tree.version`` cambió. ``lang`` es el idioma de
    las frases (``set_language``); los nombres localizados salen de ``index`` y ``loc`` (``set_names``).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tree = None
        self._version = None
        self._index = None
        self._loc = None
        self._lang = phrase_language()
        self._nodes: dict[int, object] = {}
        self._problems: dict[int, tuple] = {}
        self._ctx = None

    # --- estado ---

    def set_tree(self, tree) -> None:
        """Cambia de árbol (``ScriptTree`` o None)."""
        self.beginResetModel()
        self._tree = tree
        self._rebuild()
        self.endResetModel()

    def tree(self):
        return self._tree

    def refresh(self) -> None:
        """Reconstruye las filas si el árbol cambió desde la última vez."""
        if self._tree is not None and getattr(self._tree, "version", None) != self._version:
            self.set_tree(self._tree)

    def set_names(self, index, loc) -> None:
        """El índice y la localización de donde salen los nombres de las frases (None: ids)."""
        self._index, self._loc = index, loc
        self._emit_all()

    def set_check_context(self, ctx) -> None:
        """El ``CheckContext`` con el que se comprueban las referencias de los valores (None: no se miran)."""
        self._ctx = ctx

    def set_language(self, lang: str) -> None:
        self._lang = lang if lang in ("es", "en") else "en"
        self._emit_all()

    def _emit_all(self) -> None:
        if self._tree is not None:
            self.beginResetModel()
            self.endResetModel()

    def _rebuild(self) -> None:
        self._nodes = {}
        self._problems = {}
        tree = self._tree
        if tree is None:
            self._version = None
            return
        self._version = getattr(tree, "version", None)
        root = tree.root
        self._nodes[id(root)] = root
        for node in tree.walk():
            self._nodes[id(node)] = node
        for node in tree.walk():
            try:
                found = node.issues(self._ctx)
            except Exception:  # noqa: BLE001 - un aviso que falla no impide ver el árbol
                found = []
            if found:
                self._problems[id(node)] = tuple(found)

    # --- QAbstractItemModel ---

    def node(self, index: QModelIndex):
        """El ``ScriptNode`` de ``index``; la raíz del árbol con un índice inválido."""
        if self._tree is None:
            return None
        if not index.isValid():
            return self._tree.root
        return self._nodes.get(index.internalId())

    def index(self, row: int, column: int = 0, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        owner = self.node(parent)
        if owner is None or column != 0 or not 0 <= row < len(owner.children):
            return QModelIndex()
        child = owner.children[row]
        self._nodes[id(child)] = child
        return self.createIndex(row, 0, id(child))

    def parent(self, index: QModelIndex = QModelIndex()) -> QModelIndex:  # type: ignore[override]
        if not index.isValid():
            return QModelIndex()
        node = self._nodes.get(index.internalId())
        owner = getattr(node, "parent", None)
        if owner is None or owner.parent is None:
            return QModelIndex()
        try:
            row = owner.parent.children.index(owner)
        except ValueError:
            return QModelIndex()
        return self.createIndex(row, 0, id(owner))

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.column() > 0:
            return 0
        owner = self.node(parent)
        return 0 if owner is None else len(owner.children)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1

    def index_of(self, path) -> QModelIndex:
        """El índice del nodo en ``path`` (``ScriptNode.path``); inválido si ya no existe."""
        index = QModelIndex()
        for row in path or ():
            index = self.index(int(row), 0, index)
            if not index.isValid():
                return QModelIndex()
        return index

    def label(self, node) -> str:
        """El texto de la fila: el nombre del grupo o del ámbito, o la frase de la condición o el efecto."""
        from ...core.script.phrases import key_label

        form = _form_name(node)
        if form == "RAW":
            return f"{tr(TriggerBuilder.RAW_KEY)}: {node.source()}"
        if form in ("GROUP", "SCOPE") and node.definition is not None:
            label = key_label(node.definition, self._lang, node.key, self._index, self._loc)
            if node.logic is None and node.key.lower() != "limit":
                return label
            return f"{label}"
        try:
            return node.summary(self._lang, self._index, self._loc)
        except Exception:  # noqa: BLE001 - una frase que falla se ve como su código
            return node.source()

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        node = self.node(index) if index.isValid() else None
        if node is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self.label(node)
        if role == Qt.ItemDataRole.ToolTipRole:
            problems = self._problems.get(id(node), ())
            lines = [problem.message(self._lang) for problem in problems]
            lines.append(node.source())
            return "\n".join(lines)
        if role == Qt.ItemDataRole.ForegroundRole:
            if self._problems.get(id(node)):
                return theme.color("danger")
            if _form_name(node) == "RAW":
                return theme.color("ink_muted")
            return None
        if role == NODE_ROLE:
            return node
        if role == FORM_ROLE:
            return node.form
        if role == PROBLEMS_ROLE:
            return self._problems.get(id(node), ())
        if role == PATH_ROLE:
            return node.path
        return None

    def problem_count(self) -> int:
        return sum(len(value) for value in self._problems.values())

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


class _BracketDelegate(QStyledItemDelegate):
    """Pinta a la izquierda de cada fila de grupo o ámbito una barra con el color de su lógica."""

    def paint(self, painter: QPainter, option, index) -> None:
        super().paint(painter, option, index)
        node = index.data(NODE_ROLE)
        form = _form_name(node)
        if form not in ("GROUP", "SCOPE"):
            return
        logic = getattr(node, "logic", None) or "scope"
        color = theme.color(BRACKET_COLORS.get(logic, "bronze"))
        painter.save()
        painter.setPen(QPen(color, 3))
        rect: QRect = option.rect
        painter.drawLine(rect.left() + 1, rect.top() + 3, rect.left() + 1, rect.bottom() - 3)
        painter.restore()


class TextEditDialog(QDialog):
    """«Editar como texto»: el código de un nodo, con los errores de sintaxis a la vista."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("scriptTextDialog")
        self.setWindowTitle(tr(N_("script_ui.text_dialog.title")))
        self.resize(560, 320)
        layout = QVBoxLayout(self)
        self.edit = mark_data(QPlainTextEdit(text))
        self.edit.setObjectName("scriptTextEdit")
        self.edit.setFont(theme.font("mono"))
        layout.addWidget(self.edit, 1)
        self.errors = mark_data(QLabel())
        self.errors.setObjectName("scriptTextErrors")
        self.errors.setWordWrap(True)
        layout.addWidget(self.errors)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def text(self) -> str:
        return self.edit.toPlainText()


class TriggerBuilder(QWidget):
    """Constructor de un bloque de condiciones. ``EffectBuilder`` es el mismo con ``kind = EFFECT``."""

    kind = ScriptKind.TRIGGER
    ADD_KEY = N_("script_ui.add_condition")          # texto del botón que abre el buscador
    RAW_KEY = N_("script_ui.raw_node")               # etiqueta de un nodo crudo
    EMPTY_KEY = N_("script_ui.empty_conditions")

    changed = Signal()                               # tras una operación aplicada (ya dentro de su transacción)
    current_changed = Signal(object)                 # ScriptNode | None seleccionado
    code_requested = Signal(object)                  # ScriptNode: «Ver en el código» (lleva a su línea)
    status_requested = Signal(str, object)           # (clave i18n, formato): un cambio rechazado

    def __init__(self, session, *, catalog=None, parent: QWidget | None = None) -> None:
        """``catalog``: el ``ScriptCatalog`` (None: ``ScriptCatalog.load()`` ligado al índice de la sesión)."""
        super().__init__(parent)
        self.session = session
        self._catalog = catalog
        self._binding: ScriptBinding | None = None
        self._manual = False
        self._scope: Scope | None = None
        self._read_only = False
        self._selected: tuple[int, ...] = ()
        self._applying = False
        self.dialog = None
        self.picker_dialog = None
        self._model = ScriptTreeModel(self)
        self.setObjectName("scriptBuilder")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        bar_box = QWidget()
        bar = FlowLayout(bar_box, spacing=4)
        self.add_button = QPushButton()
        self.add_button.setObjectName("scriptAdd")
        self.add_button.setIcon(make_icon("plus", "gold_light"))
        self.add_button.clicked.connect(lambda: self.open_picker())
        self.scope_button = QPushButton()
        self.scope_button.setObjectName("scriptAddScope")
        self.scope_button.clicked.connect(self._open_scope_picker)
        self.wrap_button = QToolButton()
        self.wrap_button.setObjectName("scriptWrap")
        self.wrap_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.wrap_menu = QMenu(self.wrap_button)
        self.wrap_actions = {}
        for op in LOGIC_KEYS:
            action = self.wrap_menu.addAction("")
            action.triggered.connect(lambda _checked=False, op=op: self.wrap(op))
            self.wrap_actions[op] = action
        self.wrap_button.setMenu(self.wrap_menu)
        self.unwrap_button = QPushButton()
        self.unwrap_button.setObjectName("scriptUnwrap")
        self.unwrap_button.clicked.connect(self.unwrap)
        self.text_button = QPushButton()
        self.text_button.setObjectName("scriptText")
        self.text_button.clicked.connect(self.open_text_dialog)
        self.remove_button = QPushButton()
        self.remove_button.setObjectName("scriptRemove")
        self.remove_button.clicked.connect(self.remove)
        self.code_button = QPushButton()
        self.code_button.setObjectName("scriptCode")
        self.code_button.clicked.connect(lambda: self.code_requested.emit(self.current_node()))
        for widget in (self.add_button, self.scope_button, self.wrap_button, self.unwrap_button, self.text_button,
                       self.remove_button, self.code_button):
            bar.addWidget(widget)
        outer.addWidget(bar_box)

        self.view = mark_data(QTreeView())
        self.view.setObjectName("scriptTree")
        self.view.setHeaderHidden(True)
        self.view.setModel(self._model)
        self.view.setItemDelegate(_BracketDelegate(self.view))
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setUniformRowHeights(True)
        self.view.setMinimumHeight(120)
        self.view.selectionModel().currentChanged.connect(self._on_current)
        self.view.doubleClicked.connect(lambda _index: self._focus_value())
        outer.addWidget(self.view, 1)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("scriptEmpty")
        self.empty_label.setWordWrap(True)
        outer.addWidget(self.empty_label)

        # El control del nodo elegido: un valor, los campos de una estructura o nada (grupos y ámbitos).
        self.value_row = QWidget()
        value_layout = QHBoxLayout(self.value_row)
        value_layout.setContentsMargins(0, 0, 0, 0)
        self.value_label = QLabel()
        self.value_edit = mark_data(QLineEdit())
        self.value_edit.setObjectName("scriptValue")
        self.value_edit.returnPressed.connect(self.commit_pending)
        self.value_apply = QPushButton()
        self.value_apply.setObjectName("scriptValueApply")
        self.value_apply.clicked.connect(self.commit_pending)
        value_layout.addWidget(self.value_label)
        value_layout.addWidget(self.value_edit, 1)
        value_layout.addWidget(self.value_apply)
        outer.addWidget(self.value_row)
        self.struct_box = QWidget()
        self.struct_form = QFormLayout(self.struct_box)
        self.struct_form.setContentsMargins(0, 0, 0, 0)
        self.struct_edits: dict[str, QLineEdit] = {}
        outer.addWidget(self.struct_box)
        self.help_label = mark_data(QLabel())
        self.help_label.setObjectName("scriptHelp")
        self.help_label.setWordWrap(True)
        outer.addWidget(self.help_label)

        session_signal = getattr(session, "documentsChanged", None)
        if session_signal is not None:
            session_signal.connect(self._on_documents)
        translator().languageChanged.connect(self._on_language)
        self.retranslate()
        self._update_controls()

    # --- enlace -----------------------------------------------------------------------------------

    def catalog(self):
        if self._catalog is not None:
            return self._catalog
        tree = self.tree()
        if tree is not None:
            return tree.catalog
        from ...core.script.catalog import ScriptCatalog

        return ScriptCatalog.load().with_symbols(getattr(self.session, "index", None))

    def _names(self) -> None:
        index = getattr(self.session, "index", None)
        loc = None
        finder = getattr(self.session, "_loc_for_search", None)
        if callable(finder):
            try:
                loc = finder()
            except Exception:  # noqa: BLE001 - sin textos, las frases usan los ids
                loc = None
        entities = getattr(self.session, "entities", None)
        try:
            self._model.set_check_context(entities.check_context() if entities is not None else None)
        except Exception:  # noqa: BLE001
            self._model.set_check_context(None)
        self._model.set_names(index, loc)

    def bind(self, binding: ScriptBinding | None) -> None:
        """Enlaza con el campo de guion de un registro (None: vacío). Si el bloque no existe, el constructor
        se ve vacío y la primera operación lo crea (``Record.script(create=True)``) en la misma
        transacción."""
        if binding != self._binding or self._manual:
            self._selected = ()         # el mismo campo (tras una edición o un deshacer) conserva la selección
        self._binding = binding
        self._manual = False
        self._reload()

    def binding(self) -> ScriptBinding | None:
        return self._binding

    def _reload(self) -> None:
        tree = None
        if self._binding is not None:
            try:
                tree = resolve_tree(self.session, self._binding)
            except (KeyError, FileNotFoundError, OSError, ValueError):
                tree = None
        self._names()
        self._set_model_tree(tree)

    def _set_model_tree(self, tree) -> None:
        self._model.set_tree(tree)
        self.view.expandAll()
        if not self.select(self._selected) and self._selected:
            self._selected = ()
        self._update_controls()

    def set_tree(self, tree, *, scope: Scope | None = None) -> None:
        """Pone un árbol a mano, sin registro (pruebas y diálogos): las operaciones se aplican sobre él
        directamente, sin ``Session.edit``."""
        self._binding = None
        self._manual = True
        self._scope = scope
        self._selected = ()
        self._set_model_tree(tree)

    def tree(self):
        """El ``ScriptTree`` que se está viendo (None si el bloque no existe)."""
        return self._model.tree()

    def model(self) -> ScriptTreeModel:
        return self._model

    def current_node(self):
        """El nodo seleccionado; la raíz si no hay ninguno."""
        tree = self.tree()
        if tree is None:
            return None
        node = tree.node_at(self._selected) if self._selected else None
        return node if node is not None else tree.root

    def select(self, path) -> bool:
        """Selecciona el nodo en ``path``; False si no existe."""
        path = tuple(path or ())
        if not path:
            self.view.selectionModel().clearCurrentIndex()
            self.view.clearSelection()
            self._selected = ()
            self._update_controls()
            return self.tree() is not None
        index = self._model.index_of(path)
        if not index.isValid():
            return False
        self.view.setCurrentIndex(index)
        self.view.scrollTo(index)
        self._selected = path
        self._update_controls()
        return True

    def _on_current(self, current: QModelIndex, _previous=None) -> None:
        node = self._model.node(current) if current.isValid() else None
        self._selected = tuple(node.path) if node is not None and current.isValid() else ()
        self._update_controls()
        self.current_changed.emit(node if current.isValid() else None)

    def _on_documents(self, rels) -> None:
        if self._manual or self._binding is None or self._applying:
            return
        self._reload()

    # --- operaciones (cada una, un paso de deshacer; devuelven False si no cambia nada) ------------

    def _apply(self, action: str, operation: Callable, *, create: bool = False, **fmt) -> bool:
        """Aplica ``operation(tree) -> ruta a seleccionar | None`` en una transacción (o directamente sobre el
        árbol puesto a mano). Un error no cambia nada y se cuenta por ``status_requested``."""
        if self._read_only:
            self.status_requested.emit(N_("script_ui.read_only"), {})
            return False
        if self._manual:
            tree = self.tree()
            if tree is None:
                return False
            try:
                selected = operation(tree)
            except (ValueError, KeyError, RuntimeError, OSError) as exc:
                self.status_requested.emit(REJECTED_KEY, {"error": str(exc)})
                return False
            self._after(selected)
            return True
        if self._binding is None or getattr(self.session, "project", None) is None:
            return False
        self._applying = True
        try:
            with self.session.edit(UNDO_KEYS[action], **fmt):
                tree = resolve_tree(self.session, self._binding, create=create)
                if tree is None:
                    raise KeyError(str(self._binding.path))
                selected = operation(tree)
        except (ValueError, KeyError, RuntimeError, OSError) as exc:
            self.status_requested.emit(REJECTED_KEY, {"error": str(exc)})
            return False
        finally:
            self._applying = False
        self._selected = tuple(selected or ())
        self._reload()
        self.changed.emit()
        return True

    def _after(self, selected) -> None:
        self._selected = tuple(selected or ())
        self._set_model_tree(self.tree())
        self.changed.emit()

    def _target_group(self, tree):
        """El grupo donde se añade: el nodo elegido si admite hijos; si no, el grupo que lo contiene."""
        node = tree.node_at(self._selected) if self._selected else tree.root
        if node is None:
            node = tree.root
        while node is not None and _form_name(node) not in ("GROUP", "SCOPE"):
            node = node.parent
        return node or tree.root

    def add(self, name: str, value=None) -> bool:
        """Añade ``name`` (una clave del catálogo, de una familia o cruda) al grupo seleccionado, o al grupo
        que contiene el nodo seleccionado, y lo selecciona."""
        def operation(tree):
            group = self._target_group(tree)
            return group.add_child(name, value).path

        return self._apply("add", operation, create=True, key=name)

    def set_value(self, value) -> bool:
        """Cambia el valor del nodo seleccionado (``ScriptNode.set_value``)."""
        path = self._selected
        node = self.current_node()
        if not path or node is None:
            return False

        def operation(tree):
            target = tree.node_at(path)
            if target is None:
                raise KeyError(str(path))
            target.set_value(value)
            return path

        return self._apply("value", operation, key=node.key)

    def wrap(self, op: str) -> bool:
        """Envuelve el nodo seleccionado en ``AND``, ``OR`` o ``NOT``."""
        path = self._selected
        if not path:
            return False

        def operation(tree):
            target = tree.node_at(path)
            if target is None:
                raise KeyError(str(path))
            return target.wrap(op).path

        return self._apply("wrap", operation, op=op)

    def unwrap(self) -> bool:
        """Deshace el grupo lógico seleccionado."""
        path = self._selected
        node = self.current_node()
        if not path or node is None or node.logic is None:
            return False

        def operation(tree):
            target = tree.node_at(path)
            if target is None:
                raise KeyError(str(path))
            target.unwrap()
            return path[:-1]

        return self._apply("unwrap", operation)

    def remove(self) -> bool:
        """Quita el nodo seleccionado."""
        path = self._selected
        node = self.current_node()
        if not path or node is None:
            return False

        def operation(tree):
            target = tree.node_at(path)
            if target is None:
                raise KeyError(str(path))
            target.remove()
            return path[:-1]

        return self._apply("remove", operation, key=node.key)

    def move(self, index: int, *, to=None) -> bool:
        """Mueve el nodo seleccionado (arrastrar y soltar): ``ScriptNode.move``."""
        path = self._selected
        node = self.current_node()
        if not path or node is None:
            return False
        to_path = None if to is None else tuple(getattr(to, "path", to))

        def operation(tree):
            target = tree.node_at(path)
            if target is None:
                raise KeyError(str(path))
            destination = None if to_path is None else (tree.node_at(to_path) if to_path else tree.root)
            target.move(index, to=destination)
            return target.path

        return self._apply("move", operation, key=node.key)

    def edit_as_text(self, text: str) -> bool:
        """Sustituye el nodo seleccionado por ``text`` (``ScriptNode.replace_source``). Con errores de
        sintaxis no cambia nada y los enseña."""
        path = self._selected
        if not path:
            return False
        from ...core.script.tree import check_source

        errors = [d for d in check_source(text) if getattr(d.severity, "name", "") == "ERROR"]
        if errors:
            lang = phrase_language()
            message = "; ".join(f"{d.line}:{d.column} {d.message(lang)}" for d in errors)
            self.status_requested.emit(N_("script_ui.text_dialog.errors"), {"errors": message})
            return False

        def operation(tree):
            target = tree.node_at(path)
            if target is None:
                raise KeyError(str(path))
            nodes = target.replace_source(text)
            return nodes[0].path if nodes else path[:-1]

        return self._apply("text", operation)

    def open_text_dialog(self) -> None:
        node = self.current_node()
        if node is None or not self._selected:
            return
        self.dialog = TextEditDialog(node.source(), self)
        self.dialog.accepted.connect(lambda: self.edit_as_text(self.dialog.text()))
        self.dialog.open()

    # --- estado -----------------------------------------------------------------------------------

    def _context(self):
        tree = self.tree()
        group = self._target_group(tree) if tree is not None else None
        if group is not None:
            return group.inner_kind, group.inner_scope
        return self.kind, self._scope or Scope.ANY

    def open_picker(self, roles=None) -> None:
        """Abre el ``CatalogPicker`` para el grupo seleccionado («+ Condición» / «+ Ámbito»)."""
        from .catalog_picker import CatalogPickerDialog

        if self._read_only:
            return
        kind, scope = self._context()
        self.picker_dialog = CatalogPickerDialog(self)
        self.picker_dialog.picker.set_context(self.catalog(), kind, scope, roles=roles)
        self.picker_dialog.picker.picked.connect(self._on_picked)
        self.picker_dialog.picker.raw_requested.connect(self._on_raw)
        self.picker_dialog.open()

    def _open_scope_picker(self) -> None:
        from ...core.script.catalog import Role

        self.open_picker(roles=(Role.SCOPE, Role.ITERATOR, Role.LOGIC))

    def _on_picked(self, definition, key: str) -> None:
        if self.picker_dialog is not None:
            self.picker_dialog.accept()
        self.add(key or definition.name)

    def _on_raw(self, text: str) -> None:
        if self.picker_dialog is not None:
            self.picker_dialog.accept()
        key, _, value = text.partition("=")
        self.add(key.strip(), value.strip() or "yes")

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = bool(read_only)
        self._update_controls()

    def is_read_only(self) -> bool:
        return self._read_only

    def commit_pending(self) -> None:
        """Confirma lo tecleado en la fila en edición (Ctrl+S, cambiar de registro)."""
        node = self.current_node()
        if node is None or not self._selected or self._read_only:
            return
        form = _form_name(node)
        try:
            if form == "VALUE":
                text = self.value_edit.text()
                if text.strip() == value_text(node.value):
                    return
                self.set_value(parse_value(node.definition.value, text))
            elif form == "RAW" and node.value is not None:
                text = self.value_edit.text().strip()
                if text != str(node.value):
                    self.set_value(text)
            elif form == "STRUCT":
                current = node.value or {}
                changes = {}
                for item in node.definition.block:
                    edit = self.struct_edits.get(item.key)
                    if edit is None:
                        continue
                    text = edit.text().strip()
                    if text == value_text(current.get(item.key)):
                        continue
                    changes[item.key] = None if not text else parse_value(item.type, text)
                if changes:
                    self.set_value(changes)
        except ValueError as exc:
            self.status_requested.emit(REJECTED_KEY, {"error": str(exc)})

    def _focus_value(self) -> None:
        if self.value_row.isVisible():
            self.value_edit.setFocus()
            self.value_edit.selectAll()

    def _update_controls(self) -> None:
        tree = self.tree()
        node = self.current_node() if tree is not None else None
        has_node = node is not None and bool(self._selected)
        form = _form_name(node) if has_node else ""
        editable = not self._read_only and (tree is not None or self._binding is not None)
        self.add_button.setEnabled(editable)
        self.scope_button.setEnabled(editable)
        self.wrap_button.setEnabled(editable and has_node)
        self.unwrap_button.setEnabled(editable and has_node and node.logic is not None)
        self.text_button.setEnabled(editable and has_node)
        self.remove_button.setEnabled(editable and has_node)
        self.code_button.setEnabled(has_node and not self._manual)
        empty = tree is None or not tree.root.children
        self.empty_label.setVisible(empty)
        self.value_row.setVisible(has_node and (form == "VALUE" or (form == "RAW" and node.value is not None)))
        self.value_edit.setReadOnly(self._read_only)
        self.value_apply.setEnabled(not self._read_only)
        if self.value_row.isVisible():
            self.value_edit.setText(value_text(node.value))
        self._fill_struct(node if form == "STRUCT" else None)
        help_text = ""
        if has_node and node.definition is not None:
            lang = phrase_language()
            help_text = node.definition.help.get(lang) or node.definition.help.get("en", "") or ""
        self.help_label.setText(help_text)
        self.help_label.setVisible(bool(help_text))

    def _fill_struct(self, node) -> None:
        while self.struct_form.rowCount():
            self.struct_form.removeRow(0)
        self.struct_edits = {}
        if node is None:
            self.struct_box.hide()
            return
        values = node.value or {}
        for item in node.definition.block:
            edit = mark_data(QLineEdit(value_text(values.get(item.key))))
            edit.setObjectName(f"scriptField_{item.key}")
            edit.setReadOnly(self._read_only)
            edit.returnPressed.connect(self.commit_pending)
            self.struct_edits[item.key] = edit
            self.struct_form.addRow(mark_data(QLabel(item.key)), edit)
        self.struct_box.show()

    def problem_count(self) -> int:
        return self._model.problem_count()

    def _on_language(self, _code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.add_button.setText(tr(self.ADD_KEY))
        self.scope_button.setText(tr(N_("script_ui.add_scope")))
        self.wrap_button.setText(tr(N_("script_ui.wrap")))
        for op, action in self.wrap_actions.items():
            action.setText(tr(WRAP_KEYS[op]))
        self.unwrap_button.setText(tr(N_("script_ui.unwrap")))
        self.text_button.setText(tr(N_("script_ui.text")))
        self.remove_button.setText(tr(N_("script_ui.remove")))
        self.code_button.setText(tr(N_("script_ui.code")))
        self.value_label.setText(tr(N_("script_ui.value")))
        self.value_apply.setText(tr(N_("script_ui.apply")))
        self.empty_label.setText(tr(self.EMPTY_KEY))
        self._model.set_language(phrase_language())
        self.view.expandAll()


def bracket_color(op: str) -> QColor:
    """El color del corchete de un grupo (``AND``, ``OR``, ``NOT`` o ``scope``)."""
    return theme.color(BRACKET_COLORS.get(op, "bronze"))
