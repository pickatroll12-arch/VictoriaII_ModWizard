"""La jerarquía de una ventana ``.gui`` (wizard §17.2), sincronizada con el lienzo.

Cada fila es un elemento: su nombre (dato del archivo, sin traducir) y su tipo. Elegir una fila emite
``selected(ruta)``; ``select_path`` hace lo contrario sin volver a emitir. Como el lienzo, el árbol solo guarda
rutas de elemento (``core.gui.element_path``), nunca nodos: se rehace entero cuando cambia el documento.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem

from ..widgets import mark_data

ROLE_PATH = Qt.ItemDataRole.UserRole


class GuiTree(QTreeWidget):
    """El árbol de elementos de la ventana que enseña el lienzo."""

    selected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("guiTree")
        mark_data(self)
        self.setColumnCount(2)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setUniformRowHeights(True)
        self.items_by_path: dict[str, QTreeWidgetItem] = {}
        self._quiet = False
        self.itemSelectionChanged.connect(self._on_selection)

    def set_headers(self, name: str, kind: str) -> None:
        self.setHeaderLabels([name, kind])

    def set_window(self, windows) -> None:
        """Rellena el árbol con ``windows`` (la ventana y los elementos sueltos que la acompañan)."""
        from ...core.gui import element_path

        self._quiet = True
        self.clear()
        self.items_by_path = {}

        def add(element, parent) -> None:
            item = QTreeWidgetItem([element.name or "—", element.entry.key.text])
            path = element_path(element)
            item.setData(0, ROLE_PATH, path)
            item.setToolTip(0, path)
            if parent is None:
                self.addTopLevelItem(item)
            else:
                parent.addChild(item)
            self.items_by_path[path] = item
            for child in element.children:
                add(child, item)

        for window in windows:
            add(window, None)
        self.expandAll()
        self.resizeColumnToContents(0)
        self.resizeColumnToContents(1)
        self._quiet = False

    def select_path(self, path: str | None) -> None:
        self._quiet = True
        self.clearSelection()
        item = self.items_by_path.get(path) if path else None
        if item is not None:
            item.setSelected(True)
            self.setCurrentItem(item)
            self.scrollToItem(item)
        self._quiet = False

    def selected_path(self) -> str | None:
        items = self.selectedItems()
        return items[0].data(0, ROLE_PATH) if items else None

    def _on_selection(self) -> None:
        if self._quiet:
            return
        path = self.selected_path()
        if path:
            self.selected.emit(path)
