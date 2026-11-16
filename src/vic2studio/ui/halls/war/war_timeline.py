"""Línea temporal de las guerras de inicio (sala Guerra › Guerras de inicio, wizard §14.8). Iteración 6.

Una barra por guerra, de su primera fecha a la última salida (abierta hasta el final de la partida si nadie
sale), sobre un eje de años; las fechas de inicio (bookmarks) son líneas verticales y la fecha de trabajo, una
línea dorada. Un clic elige una guerra (``warClicked``).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

ROW = 22
TOP = 24
LEFT = 8


def _year(text: str | None) -> float | None:
    if not text:
        return None
    parts = str(text).strip().split(".")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
    except ValueError:
        return None
    return year + (month - 1) / 12


class WarTimeline(QWidget):
    warClicked = Signal(int)            # fila de la guerra

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("warTimeline")
        self.setMinimumHeight(TOP + ROW * 3)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.wars: list[tuple[str, float | None, float | None]] = []
        self.bookmarks: list[float] = []
        self.working: float | None = None
        self.end_year: float = 1936
        self.selected = -1

    def set_data(self, wars, bookmarks=(), working=None, end=None) -> None:
        """``wars``: ``[(nombre, inicio, fin)]`` con fechas como texto ``AAAA.M.D``."""
        self.wars = [(name, _year(start), _year(stop)) for name, start, stop in wars]
        self.bookmarks = [y for y in (_year(str(b)) for b in bookmarks) if y is not None]
        self.working = _year(str(working)) if working is not None else None
        self.end_year = _year(str(end)) if end is not None else 1936
        self.setMinimumHeight(TOP + ROW * max(3, len(self.wars) + 1))
        self.update()

    def span(self) -> tuple[float, float]:
        years = [y for _name, start, stop in self.wars for y in (start, stop) if y is not None]
        years += self.bookmarks
        if self.working is not None:
            years.append(self.working)
        if not years:
            return (1836, 1936)
        low, high = min(years), max(years)
        if high - low < 10:
            high = low + 10
        return (low - 1, high + 1)

    def _x(self, year: float, low: float, high: float) -> float:
        width = max(1, self.width() - 2 * LEFT)
        return LEFT + (year - low) / (high - low) * width

    def row_at(self, y: float) -> int:
        row = int((y - TOP) // ROW)
        return row if 0 <= row < len(self.wars) else -1

    def mousePressEvent(self, event) -> None:  # noqa: N802 - API de Qt
        row = self.row_at(event.position().y())
        if row >= 0:
            self.selected = row
            self.update()
            self.warClicked.emit(row)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - API de Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        low, high = self.span()
        ink = self.palette().text().color()
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1))
        painter.setFont(font)
        step = 5 if high - low <= 60 else 10 if high - low <= 150 else 50
        first = int(low // step + 1) * step
        painter.setPen(QPen(QColor(ink.red(), ink.green(), ink.blue(), 60), 1))
        for year in range(first, int(high) + 1, step):
            x = self._x(year, low, high)
            painter.drawLine(int(x), TOP - 4, int(x), self.height())
            painter.drawText(QRectF(x - 20, 2, 40, TOP - 6), Qt.AlignmentFlag.AlignCenter, str(year))
        painter.setPen(QPen(QColor(120, 90, 160), 1, Qt.PenStyle.DashLine))
        for year in self.bookmarks:
            x = self._x(year, low, high)
            painter.drawLine(int(x), TOP - 4, int(x), self.height())
        if self.working is not None:
            painter.setPen(QPen(QColor(200, 160, 40), 2))
            x = self._x(self.working, low, high)
            painter.drawLine(int(x), TOP - 6, int(x), self.height())
        for row, (name, start, stop) in enumerate(self.wars):
            top = TOP + row * ROW + 3
            if start is None:
                continue
            end = stop if stop is not None else min(self.end_year, high)
            left, right = self._x(start, low, high), self._x(max(end, start + 0.25), low, high)
            rect = QRectF(left, top, max(4.0, right - left), ROW - 6)
            color = QColor(170, 40, 30) if stop is not None else QColor(200, 90, 30)
            if row == self.selected:
                painter.setPen(QPen(QColor(230, 190, 60), 2))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 3, 3)
            needed = painter.fontMetrics().horizontalAdvance(name) + 8
            middle = Qt.AlignmentFlag.AlignVCenter
            if rect.width() >= needed:              # dentro de la barra
                painter.setPen(QColor(255, 248, 230))
                painter.drawText(rect.adjusted(4, 0, -4, 0), Qt.AlignmentFlag.AlignLeft | middle, name)
            elif self.width() - rect.right() - 8 >= needed:     # a su derecha
                painter.setPen(ink)
                painter.drawText(QRectF(rect.right() + 4, top, needed, ROW - 6), Qt.AlignmentFlag.AlignLeft | middle,
                                 name)
            else:                                   # a su izquierda
                painter.setPen(ink)
                painter.drawText(QRectF(LEFT, top, max(0.0, rect.left() - LEFT - 4), ROW - 6),
                                 Qt.AlignmentFlag.AlignRight | middle, name)
        painter.end()
