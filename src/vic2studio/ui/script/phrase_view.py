"""Frase legible de un bloque de guion, bajo cada constructor y en el formulario (wizard §12.3, §13.6).

``PhraseView`` enseña la frase de ``core.script.phrases`` en una línea que se despliega por niveles
(``phrase_lines``), marca los nodos crudos y los problemas, y lleva el botón «Editar condiciones…» /
«Editar efectos…». En el formulario generado es el editor de un campo ``Script`` (el gancho de ``ui/forms``
sustituye al botón «Editar como código…» de la iteración 4, que queda como alternativa).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


class PhraseView(QWidget):
    """La frase de un ``ScriptTree`` (o un texto ya hecho)."""

    edit_requested = Signal()                    # el botón que abre el constructor
    node_activated = Signal(object)              # tuple[int, ...]: clic en una línea de la frase desplegada

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        raise NotImplementedError

    def set_tree(self, tree, *, lead: str | None = None, index=None, loc=None) -> None:
        """Enseña la frase de ``tree`` (None: «sin bloque»). ``lead``: uno de ``phrases.LEADS``."""
        raise NotImplementedError

    def set_text(self, text: str) -> None:
        """Enseña un texto ya hecho (pruebas, vistas previas)."""
        raise NotImplementedError

    def text(self) -> str:
        """La frase en una línea, tal como se ve."""
        raise NotImplementedError

    def set_problem_count(self, count: int) -> None:
        """Cuántos problemas tiene el bloque (insignia junto al botón)."""
        raise NotImplementedError

    def set_expanded(self, expanded: bool) -> None:
        raise NotImplementedError

    def set_read_only(self, read_only: bool) -> None:
        raise NotImplementedError

    def retranslate(self) -> None:
        raise NotImplementedError
