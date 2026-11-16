"""Buscador del catálogo: lo que se puede añadir a un grupo, por categorías (wizard §14.7).

Una caja de búsqueda (por etiqueta ES/EN y por clave cruda, sin acentos), la lista de categorías
(``catalog.categories``) y los resultados (``catalog.suggestions``), cada uno con su etiqueta y su clave. Al
elegir una familia (un TAG, una provincia, una tecnología…) pide la clave concreta con
``catalog.family_keys``. Lo que se teclea y no está catalogado se puede añadir como clave cruda.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


class CatalogPicker(QWidget):
    """Buscador de claves del catálogo para un tipo de guion y un ámbito."""

    picked = Signal(object, str)                 # (ScriptKeyDef, clave concreta: el nombre, o la de la familia)
    raw_requested = Signal(str)                  # clave tecleada que el catálogo no conoce
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        raise NotImplementedError

    def set_context(self, catalog, kind, scope, *, roles=None) -> None:
        """Qué se ofrece: las sugerencias de ``catalog`` para ``kind`` y ``scope``; ``roles`` limita los
        papeles (``Role.SCOPE`` e ``ITERATOR`` en «+ Ámbito»)."""
        raise NotImplementedError

    def set_filter(self, text: str) -> None:
        """Texto de búsqueda (lo mismo que teclear en la caja)."""
        raise NotImplementedError

    def set_category(self, category: str | None) -> None:
        """Filtra por una categoría de ``CATEGORIES`` (None: todas)."""
        raise NotImplementedError

    def results(self) -> list:
        """Las ``ScriptKeyDef`` que se ven ahora, en orden."""
        raise NotImplementedError

    def pick(self, definition, key: str | None = None) -> None:
        """Elige una definición (como un doble clic). En una familia sin ``key`` pasa a pedir la clave."""
        raise NotImplementedError

    def retranslate(self) -> None:
        raise NotImplementedError
