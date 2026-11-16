"""Editor de MTTH, ``ai_chance`` y ``ai_will_do``: base, modificadores y resultado efectivo (wizard §14.7).

La base (meses, días o años en un MTTH; el factor en los otros dos) y una tarjeta por
``modifier = { factor = F <condiciones> }`` con su factor, su frase y el botón que abre el
``TriggerBuilder`` de sus condiciones. Cada modificador lleva una casilla «se cumple» que no escribe nada:
sirve para simular, y el pie enseña el tiempo efectivo (``core.script.mtth.effective`` y
``format_duration``): 6 meses × 0,75 × 0,95 = 4,3 meses.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from ...core.script.mtth import MTTH_KEY


class MtthEditor(QWidget):
    """Editor de un bloque de pesos (``WeightModel``)."""

    changed = Signal()                           # tras una edición aplicada
    effective_changed = Signal(float)            # el resultado simulado (meses, o peso) cambió
    conditions_requested = Signal(int)           # abrir el constructor del modificador N
    status_requested = Signal(str, object)

    def __init__(self, session, *, key: str = MTTH_KEY, parent: QWidget | None = None) -> None:
        """``key``: ``MTTH_KEY``, ``AI_CHANCE_KEY`` o ``AI_WILL_DO_KEY`` (cambia la base y los textos)."""
        super().__init__(parent)
        raise NotImplementedError

    def bind(self, ref, path: tuple = ()) -> None:
        """Enlaza con el bloque ``key`` del registro ``ref``, o del grupo en ``path``
        (``("option", 1)`` para el ``ai_chance`` de la segunda opción). None: vacío."""
        raise NotImplementedError

    def set_model(self, model) -> None:
        """Pone un ``WeightModel`` a mano, sin registro (pruebas)."""
        raise NotImplementedError

    def model(self):
        raise NotImplementedError

    # --- operaciones (cada una, un paso de deshacer) -------------------------------------------------

    def set_base(self, value: float | None, unit: str | None = None) -> bool:
        """Cambia la base; ``unit`` cambia además la clave (``months`` → ``days``) en un MTTH."""
        raise NotImplementedError

    def add_modifier(self, factor: float = 1.0) -> bool:
        raise NotImplementedError

    def set_factor(self, index: int, factor: float) -> bool:
        raise NotImplementedError

    def remove_modifier(self, index: int) -> bool:
        raise NotImplementedError

    # --- simulación (no escribe nada) ---------------------------------------------------------------

    def set_satisfied(self, index: int, satisfied: bool) -> None:
        """Marca si el modificador ``index`` se cumple en la simulación."""
        raise NotImplementedError

    def effective(self) -> float | None:
        """El resultado con las casillas actuales: meses en un MTTH, peso en los otros; None sin base."""
        raise NotImplementedError

    def set_read_only(self, read_only: bool) -> None:
        raise NotImplementedError

    def commit_pending(self) -> None:
        raise NotImplementedError

    def retranslate(self) -> None:
        raise NotImplementedError
