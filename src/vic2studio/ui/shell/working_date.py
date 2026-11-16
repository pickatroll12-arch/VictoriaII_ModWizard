"""Selector global de la fecha de trabajo (wizard §13.2, §16.3).

Vive en la cabecera de la ventana y manda en toda la aplicación: lo que muestra y lo que escribe un editor con
historia fechada (provincias, y países desde la iteración 6) es en esa fecha. Ofrece las fechas de inicio del
proyecto (``common/bookmarks.txt``, por orden) y deja escribir cualquier otra dentro de ``start_date`` –
``end_date`` de ``defines.lua``. Es una vista de ``Session.working_date``: elegir llama a
``Session.set_working_date`` y ``Session.workingDateChanged`` lo pone al día si la fecha cambia por otro lado.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from ...core.clausewitz.nodes import ClausewitzDate
from ...core.schema.record import bookmark_dates
from ...i18n import tr, translator


def _rules(session):
    project = getattr(session, "project", None)
    if project is None:
        return None
    rules = getattr(project, "rules", None)
    if rules is None and getattr(session, "map", None) is not None:
        rules = session.map.rules()
    return rules


class WorkingDateSelector(QWidget):
    dateChosen = Signal(object)                   # ClausewitzDate elegida por el usuario (no por set_date)

    def __init__(self, session, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._dates: list[ClausewitzDate] = []
        self._setting = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.label = QLabel()
        self.combo = QComboBox()
        self.combo.setObjectName("workingDateCombo")
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo.setMinimumContentsLength(10)
        self.label.setBuddy(self.combo)
        row.addWidget(self.label)
        row.addWidget(self.combo)
        self.combo.activated.connect(self._on_activated)
        self.combo.lineEdit().editingFinished.connect(self._on_typed)
        session.workingDateChanged.connect(self.set_date)
        translator().languageChanged.connect(self._on_language)
        self.reload()
        self.retranslate()

    # --- API ------------------------------------------------------------------------------------------

    def date(self) -> ClausewitzDate:
        """La fecha que muestra (la de ``session.working_date``)."""
        return self.session.working_date

    def set_date(self, date: ClausewitzDate) -> None:
        """Muestra ``date`` sin emitir ``dateChosen`` ni tocar la sesión."""
        self._setting = True
        try:
            index = self.combo.findData(str(date))
            if index >= 0:
                self.combo.setCurrentIndex(index)
            self.combo.setEditText(str(date))
            self._mark(True)
        finally:
            self._setting = False

    def bookmark_dates(self) -> list[ClausewitzDate]:
        """Las fechas de inicio que ofrece, sin repetir y en orden cronológico."""
        return list(self._dates)

    def reload(self) -> None:
        """Relee las fechas de inicio (al abrir un proyecto y cuando cambian los bookmarks)."""
        found = set(bookmark_dates(getattr(self.session, "index", None)))
        rules = _rules(self.session)
        if rules is not None:
            found.update(rules.bookmarks)
        self._dates = sorted(found)
        self._setting = True
        try:
            self.combo.clear()
            for date in self._dates:
                self.combo.addItem(str(date), str(date))
        finally:
            self._setting = False
        self.set_date(self.session.working_date)

    def _on_language(self, _code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.label.setText(tr("map.working_date"))
        self.combo.setToolTip(tr("map.working_date_tooltip"))

    # --- elegir ----------------------------------------------------------------------------------------

    def bounds(self) -> tuple[ClausewitzDate | None, ClausewitzDate | None]:
        """``(start_date, end_date)`` de ``defines.lua`` (None sin proyecto)."""
        rules = _rules(self.session)
        if rules is None:
            return None, None
        return rules.start_date, rules.end_date

    def parse(self, text: str) -> ClausewitzDate | None:
        """La fecha de ``text`` si es válida y cae dentro de los límites; None si no."""
        try:
            date = ClausewitzDate.parse(text.strip())
        except (TypeError, ValueError):
            return None
        low, high = self.bounds()
        if (low is not None and date < low) or (high is not None and date > high):
            return None
        return date

    def _mark(self, valid: bool) -> None:
        self.combo.setProperty("invalid", not valid)
        self.combo.style().unpolish(self.combo)
        self.combo.style().polish(self.combo)

    def _choose(self, text: str) -> None:
        if self._setting:
            return
        date = self.parse(text)
        if date is None:
            self._mark(False)
            self.combo.setToolTip(tr("map.working_date_invalid", text=text.strip()))
            return
        self._mark(True)
        self.combo.setToolTip(tr("map.working_date_tooltip"))
        if date != self.session.working_date:
            self.session.set_working_date(date)
            self.dateChosen.emit(date)
        self.set_date(date)

    def _on_activated(self, index: int) -> None:
        self._choose(self.combo.itemText(index))

    def _on_typed(self) -> None:
        self._choose(self.combo.currentText())
