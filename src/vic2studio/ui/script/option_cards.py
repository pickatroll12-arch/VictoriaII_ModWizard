"""Opciones de un evento: una tarjeta por ``option`` (wizard §14.7).

Cada tarjeta lleva el texto de la opción en ES y EN (la clave es el valor de ``name``; el texto se edita con
``LocSync``, en la misma transacción), un ``EffectBuilder`` con el resto del bloque y un ``MtthEditor`` para
su ``ai_chance``. «Añadir opción» propone la siguiente clave libre ``EVTOPT<letra><id>``. En vanilla un
evento tiene de 1 a 5 opciones (987 de 1 064 tienen una o dos) y solo 72 de 1 655 llevan ``ai_chance``, así
que ese editor va plegado.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


class OptionCard(QWidget):
    """Una opción. ``effects`` es su ``EffectBuilder``, ``ai_chance`` su ``MtthEditor`` y ``index`` su
    posición entre las opciones del evento."""

    index: int
    effects: object
    ai_chance: object

    def __init__(self, session, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        raise NotImplementedError

    def name_key(self) -> str | None:
        """La clave de localización de la opción (el valor de ``name``); None si no tiene."""
        raise NotImplementedError

    def text(self, lang: str) -> str:
        """El texto de la opción en ``lang`` (vacío si la clave no tiene texto)."""
        raise NotImplementedError

    def set_text(self, lang: str, text: str) -> bool:
        """Cambia el texto en ``lang`` (un paso de deshacer)."""
        raise NotImplementedError


class OptionCards(QWidget):
    """Las tarjetas de las opciones del evento enlazado."""

    changed = Signal()                           # tras añadir, quitar, mover o editar una opción
    current_changed = Signal(int)                # la tarjeta con el foco (la vista previa la resalta)
    status_requested = Signal(str, object)

    def __init__(self, session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        raise NotImplementedError

    def bind(self, ref) -> None:
        """Enlaza con las opciones del evento ``ref`` (None: vacío)."""
        raise NotImplementedError

    def count(self) -> int:
        raise NotImplementedError

    def card(self, index: int) -> OptionCard:
        raise NotImplementedError

    def add_option(self) -> bool:
        """Añade una opción al final con su clave ``EVTOPT<letra><id>`` y sus textos vacíos."""
        raise NotImplementedError

    def remove_option(self, index: int) -> bool:
        """Quita la opción (su texto se borra solo si ningún otro evento usa la clave)."""
        raise NotImplementedError

    def move_option(self, index: int, to: int) -> bool:
        raise NotImplementedError

    def set_read_only(self, read_only: bool) -> None:
        raise NotImplementedError

    def commit_pending(self) -> None:
        raise NotImplementedError

    def retranslate(self) -> None:
        raise NotImplementedError
