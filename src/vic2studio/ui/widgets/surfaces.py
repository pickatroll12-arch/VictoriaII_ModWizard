"""Superficies texturizadas: paneles de madera/terciopelo, marco ornamentado y tarjetas."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .. import theme
from .ornaments import paint_ornate_border, paint_thin_border


class TexturedPanel(QWidget):
    """Panel que pinta una textura procedural; expone ``surface`` para la hoja de estilo."""

    def __init__(self, texture: str = "wood", vignette: float = 0.0, parent: QWidget | None = None):
        super().__init__(parent)
        self._texture = texture
        self._vignette = vignette
        self.setProperty("surface", texture)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        theme.paint_surface(p, QRectF(self.rect()), self._texture, self._vignette)
        self.paint_decoration(p)

    def paint_decoration(self, painter: QPainter) -> None:
        """Gancho para ornamentos adicionales de las subclases."""


def _paint_inset_shadow(p: QPainter, rect: QRectF, depth: int = 6, strength: int = 70) -> None:
    for k in range(depth):
        alpha = int(strength * (1 - k / depth) ** 2)
        p.setPen(QPen(QColor(50, 28, 6, alpha), 1.0))
        p.drawRect(rect.adjusted(k + 0.5, k + 0.5, -k - 0.5, -k - 0.5))


class OrnateFrame(QWidget):
    """Marco de bronce doble con remaches y esquineras, relleno de pergamino envejecido."""

    def __init__(self, fill: str = "parchment", band: int = 8, corner: int = 22, padding: int = 14,
                 rivets: bool = True, vignette: float = 0.28, parent: QWidget | None = None):
        super().__init__(parent)
        self._fill = fill
        self._band = band
        self._corner = corner
        self._rivets = rivets
        self._vignette = vignette
        self.setProperty("surface", fill)
        margin = band + padding
        self.setContentsMargins(margin, margin, margin, margin)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        outer = QRectF(self.rect())
        inner = outer.adjusted(self._band, self._band, -self._band, -self._band)
        theme.paint_surface(p, inner, self._fill, self._vignette)
        # Cuando solo se repinta el interior (un hijo que cambia), la moldura, sus remaches
        # y la sombra interior (6 px) quedan fuera de la región: no hace falta dibujarlos.
        if inner.adjusted(8, 8, -8, -8).contains(QRectF(event.rect())):
            return
        _paint_inset_shadow(p, inner)
        paint_ornate_border(p, outer, self._band, self._corner, self._rivets)


class ParchmentCard(QWidget):
    """Tarjeta de pergamino claro con filete fino y esquineras (contenido secundario)."""

    def __init__(self, padding: int = 18, tone: str = "light", parent: QWidget | None = None):
        super().__init__(parent)
        self._tone = tone
        self.setProperty("surface", "parchment")
        self.setContentsMargins(padding, padding, padding, padding)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        rect = QRectF(self.rect())
        theme.paint_surface(p, rect, "parchment")
        top, bottom = (QColor(255, 250, 235, 120), QColor(255, 248, 228, 60)) if self._tone == "light" else (
            QColor(120, 80, 30, 40), QColor(120, 80, 30, 25))
        wash = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        wash.setColorAt(0.0, top)
        wash.setColorAt(1.0, bottom)
        p.fillRect(rect, wash)
        paint_thin_border(p, rect)
