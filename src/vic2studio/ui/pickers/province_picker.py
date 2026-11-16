"""Selector de provincia y diálogo «elegir en el mapa» (wizard §13.7, §16). Contrato de la iteración 5.

``ProvincePicker`` es el selector de formulario de un id de provincia, con la misma API que los de
``ui/pickers/fields.py`` (``value()``, ``set_value()``, ``value_committed``, ``retranslate()``): un campo para
escribir el id o buscar por nombre y un botón que abre ``MapPickDialog``. ``MapPickDialog`` muestra un
``MapCanvas`` auxiliar (``follow=False``) en modo de elegir y devuelve las provincias elegidas. Ninguno edita
nada: el valor lo escribe el formulario en su transacción.

Los usan los campos con ``ui="map_pick"`` de los esquemas (``continent.provinces``, ``default_map.sea_starts``,
``adjacency``), el editor de estrechos y, desde la iteración 6, los de capital y unidades.

En el commit de contrato solo existen los constructores; lo demás lanza ``NotImplementedError`` (cadena B).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtWidgets import QDialog, QWidget

from .fields import _Picker

LAND, SEA, ANY = "land", "sea", "any"            # qué provincias admite un selector


class ProvincePicker(_Picker):
    """Un id de provincia. ``value()`` es un ``int`` o None («sin valor»)."""

    def __init__(self, session, *, allow: str = ANY, parent: QWidget | None = None):
        """``allow``: ``LAND``, ``SEA`` o ``ANY``; un id que no cumple se marca como inválido y no se confirma."""
        super().__init__(parent)
        self.session = session
        self.allow = allow
        self._value: int | None = None

    def value(self) -> int | None:
        raise NotImplementedError

    def set_value(self, value: int | None) -> None:
        """Pone el valor sin emitir ``value_committed``."""
        raise NotImplementedError

    def pick_on_map(self) -> bool:
        """Abre ``MapPickDialog`` centrado en el valor actual; si se acepta, pone la provincia elegida y emite
        ``value_committed``. False si se cancela o el mapa no está disponible."""
        raise NotImplementedError

    def reload(self) -> None:
        """Relee los candidatos del índice (tras ``symbolsChanged``)."""
        raise NotImplementedError


class MapPickDialog(QDialog):
    """Diálogo modal para elegir una provincia o varias en el mapa."""

    def __init__(self, session, *, multiple: bool = False, initial: Iterable[int] = (), allow: str = ANY,
                 accepts: Callable[[int], bool] | None = None, parent: QWidget | None = None):
        """``multiple``: varias (clic añade o quita) en vez de una (clic elige y acepta con doble clic o
        Aceptar). ``initial``: las ya elegidas, resaltadas y centradas. ``accepts(id)`` descarta provincias
        además de ``allow``. Si el ráster de ``session.map`` no está listo, lo pide y espera mostrándolo."""
        super().__init__(parent)
        self.session = session
        self.multiple = multiple
        self.allow = allow
        self.accepts = accepts
        self._provinces: tuple[int, ...] = tuple(dict.fromkeys(int(pid) for pid in initial))

    def provinces(self) -> tuple[int, ...]:
        """Las elegidas, en el orden en que se eligieron (una como mucho sin ``multiple``)."""
        raise NotImplementedError

    def set_provinces(self, pids: Iterable[int]) -> None:
        raise NotImplementedError

    @staticmethod
    def pick(session, *, multiple: bool = False, initial: Iterable[int] = (), allow: str = ANY,
             accepts: Callable[[int], bool] | None = None, parent: QWidget | None = None) -> tuple[int, ...] | None:
        """Abre el diálogo y devuelve las provincias elegidas; None si se cancela."""
        raise NotImplementedError
