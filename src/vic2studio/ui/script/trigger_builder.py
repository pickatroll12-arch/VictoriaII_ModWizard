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

from dataclasses import dataclass

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import QWidget

from ...core.script.scopes import Scope, ScriptKind
from ...i18n import N_

# Roles del modelo, además de ``DisplayRole`` (la frase del nodo) y ``ToolTipRole`` (sus problemas).
NODE_ROLE = Qt.ItemDataRole.UserRole + 1         # ScriptNode
FORM_ROLE = Qt.ItemDataRole.UserRole + 2         # NodeForm
PROBLEMS_ROLE = Qt.ItemDataRole.UserRole + 3     # tuple[Problem, ...] del nodo (sin sus hijos)
PATH_ROLE = Qt.ItemDataRole.UserRole + 4         # tuple[int, ...]: ScriptNode.path


@dataclass(frozen=True)
class ScriptBinding:
    """De dónde sale el árbol de un constructor: un registro y la ruta de su campo de guion.

    ``path`` alterna claves de grupo e índices de repetición y acaba en la clave del ``Script``:
    ``("trigger",)``, ``("option", 1, REST)``, ``("mean_time_to_happen", "modifier", 0, REST)``.
    """

    ref: object                                  # RecordRef
    path: tuple[str | int, ...]


class ScriptTreeModel(QAbstractItemModel):
    """Modelo jerárquico de un ``ScriptTree``. Una columna. La raíz invisible es el AND implícito.

    ``set_tree`` reinicia el modelo; ``refresh`` lo hace si ``tree.version`` cambió. ``lang`` es el idioma de
    las frases (``set_language``); los nombres localizados salen de ``index`` y ``loc`` (``set_names``).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        raise NotImplementedError

    def set_tree(self, tree) -> None:
        """Cambia de árbol (``ScriptTree`` o None)."""
        raise NotImplementedError

    def tree(self):
        raise NotImplementedError

    def refresh(self) -> None:
        """Reconstruye las filas si el árbol cambió desde la última vez."""
        raise NotImplementedError

    def set_names(self, index, loc) -> None:
        """El índice y la localización de donde salen los nombres de las frases (None: ids)."""
        raise NotImplementedError

    def set_language(self, lang: str) -> None:
        raise NotImplementedError

    def node(self, index: QModelIndex):
        """El ``ScriptNode`` de ``index``; la raíz del árbol con un índice inválido."""
        raise NotImplementedError

    def index_of(self, path) -> QModelIndex:
        """El índice del nodo en ``path`` (``ScriptNode.path``); inválido si ya no existe."""
        raise NotImplementedError


class TriggerBuilder(QWidget):
    """Constructor de un bloque de condiciones. ``EffectBuilder`` es el mismo con ``kind = EFFECT``."""

    kind = ScriptKind.TRIGGER
    ADD_KEY = N_("script_ui.add_condition")          # texto del botón que abre el buscador
    RAW_KEY = N_("script_ui.raw_node")               # etiqueta de un nodo crudo

    changed = Signal()                               # tras una operación aplicada (ya dentro de su transacción)
    current_changed = Signal(object)                 # ScriptNode | None seleccionado
    code_requested = Signal(object)                  # ScriptNode: «Ver en el código» (lleva a su línea)
    status_requested = Signal(str, object)           # (clave i18n, formato): un cambio rechazado

    def __init__(self, session, *, catalog=None, parent: QWidget | None = None) -> None:
        """``catalog``: el ``ScriptCatalog`` (None: ``ScriptCatalog.load()`` ligado al índice de la sesión)."""
        super().__init__(parent)
        raise NotImplementedError

    # --- enlace -----------------------------------------------------------------------------------

    def bind(self, binding: ScriptBinding | None) -> None:
        """Enlaza con el campo de guion de un registro (None: vacío). Si el bloque no existe, el constructor
        se ve vacío y la primera operación lo crea (``Record.script(create=True)``) en la misma
        transacción."""
        raise NotImplementedError

    def set_tree(self, tree, *, scope: Scope | None = None) -> None:
        """Pone un árbol a mano, sin registro (pruebas y diálogos): las operaciones se aplican sobre él
        directamente, sin ``Session.edit``."""
        raise NotImplementedError

    def tree(self):
        """El ``ScriptTree`` que se está viendo (None si el bloque no existe)."""
        raise NotImplementedError

    def model(self) -> ScriptTreeModel:
        raise NotImplementedError

    def current_node(self):
        """El nodo seleccionado; la raíz si no hay ninguno."""
        raise NotImplementedError

    def select(self, path) -> bool:
        """Selecciona el nodo en ``path``; False si no existe."""
        raise NotImplementedError

    # --- operaciones (cada una, un paso de deshacer; devuelven False si no cambia nada) ------------

    def add(self, name: str, value=None) -> bool:
        """Añade ``name`` (una clave del catálogo, de una familia o cruda) al grupo seleccionado, o al grupo
        que contiene el nodo seleccionado, y lo selecciona."""
        raise NotImplementedError

    def set_value(self, value) -> bool:
        """Cambia el valor del nodo seleccionado (``ScriptNode.set_value``)."""
        raise NotImplementedError

    def wrap(self, op: str) -> bool:
        """Envuelve el nodo seleccionado en ``AND``, ``OR`` o ``NOT``."""
        raise NotImplementedError

    def unwrap(self) -> bool:
        """Deshace el grupo lógico seleccionado."""
        raise NotImplementedError

    def remove(self) -> bool:
        """Quita el nodo seleccionado."""
        raise NotImplementedError

    def move(self, index: int, *, to=None) -> bool:
        """Mueve el nodo seleccionado (arrastrar y soltar): ``ScriptNode.move``."""
        raise NotImplementedError

    def edit_as_text(self, text: str) -> bool:
        """Sustituye el nodo seleccionado por ``text`` (``ScriptNode.replace_source``). Con errores de
        sintaxis no cambia nada y los enseña."""
        raise NotImplementedError

    # --- estado -----------------------------------------------------------------------------------

    def open_picker(self, roles=None) -> None:
        """Abre el ``CatalogPicker`` para el grupo seleccionado («+ Condición» / «+ Ámbito»)."""
        raise NotImplementedError

    def set_read_only(self, read_only: bool) -> None:
        raise NotImplementedError

    def commit_pending(self) -> None:
        """Confirma lo tecleado en la fila en edición (Ctrl+S, cambiar de registro)."""
        raise NotImplementedError

    def retranslate(self) -> None:
        raise NotImplementedError
