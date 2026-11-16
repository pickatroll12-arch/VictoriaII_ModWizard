"""Selector global de la fecha de trabajo (wizard §13.2, §16.3). Contrato de la iteración 5.

Vive en la cabecera de la ventana y manda en toda la aplicación: lo que muestra y lo que escribe un editor con
historia fechada (provincias, y países desde la iteración 6) es en esa fecha. Ofrece las fechas de inicio del
proyecto (``common/bookmarks.txt``, por orden) y deja escribir cualquier otra dentro de ``start_date`` –
``end_date`` de ``defines.lua``. Es una vista de ``Session.working_date``: elegir llama a
``Session.set_working_date`` y ``Session.workingDateChanged`` lo pone al día si la fecha cambia por otro lado.

En el commit de contrato solo existe el constructor; lo demás lanza ``NotImplementedError`` (cadena B).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from ...core.clausewitz.nodes import ClausewitzDate


class WorkingDateSelector(QWidget):
    dateChosen = Signal(object)                   # ClausewitzDate elegida por el usuario (no por set_date)

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session

    def date(self) -> ClausewitzDate:
        """La fecha que muestra (la de ``session.working_date``)."""
        raise NotImplementedError

    def set_date(self, date: ClausewitzDate) -> None:
        """Muestra ``date`` sin emitir ``dateChosen`` ni tocar la sesión."""
        raise NotImplementedError

    def bookmark_dates(self) -> list[ClausewitzDate]:
        """Las fechas de inicio que ofrece, sin repetir y en orden cronológico."""
        raise NotImplementedError

    def reload(self) -> None:
        """Relee las fechas de inicio (al abrir un proyecto y cuando cambian los bookmarks)."""
        raise NotImplementedError

    def retranslate(self) -> None:
        raise NotImplementedError
