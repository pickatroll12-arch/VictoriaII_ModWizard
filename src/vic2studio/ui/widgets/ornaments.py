"""Ornamentación vectorial: marcos de bronce, remaches, medallones, emblema y filetes."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import theme
from .icons import draw_icon

C = theme.color


def paint_rivet(p: QPainter, center: QPointF, radius: float) -> None:
    gradient = QRadialGradient(center + QPointF(-radius * 0.35, -radius * 0.35), radius * 1.4)
    gradient.setColorAt(0.0, C("gold_pale"))
    gradient.setColorAt(0.45, C("gold"))
    gradient.setColorAt(1.0, C("bronze_dark"))
    p.setPen(QPen(C("wood_dark", 200), 0.8))
    p.setBrush(gradient)
    p.drawEllipse(center, radius, radius)


def _band_gradient(start: QPointF, end: QPointF, lit: bool) -> QLinearGradient:
    g = QLinearGradient(start, end)
    if lit:
        g.setColorAt(0.0, C("bronze_dark"))
        g.setColorAt(0.3, C("gold_light"))
        g.setColorAt(0.55, C("gold"))
        g.setColorAt(1.0, C("bronze"))
    else:
        g.setColorAt(0.0, C("wood_dark"))
        g.setColorAt(0.35, C("bronze"))
        g.setColorAt(0.6, QColor("#a67f3a"))
        g.setColorAt(1.0, C("bronze_dark"))
    return g


def paint_ornate_border(p: QPainter, rect: QRectF, band: float = 7.0, corner: float = 20.0,
                        rivets: bool = True) -> None:
    """Moldura doble de bronce/oro envejecido con placas en las esquinas y remaches.

    Cada lado es un trapecio con su propio degradado (luz desde arriba a la izquierda).
    """
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    o = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    i = o.adjusted(band, band, -band, -band)
    sides = [
        ([o.topLeft(), o.topRight(), i.topRight(), i.topLeft()], QPointF(0, o.top()), QPointF(0, i.top()), True),
        ([o.topLeft(), i.topLeft(), i.bottomLeft(), o.bottomLeft()], QPointF(o.left(), 0), QPointF(i.left(), 0), True),
        ([o.bottomLeft(), o.bottomRight(), i.bottomRight(), i.bottomLeft()], QPointF(0, o.bottom()), QPointF(0, i.bottom()), False),
        ([o.topRight(), o.bottomRight(), i.bottomRight(), i.topRight()], QPointF(o.right(), 0), QPointF(i.right(), 0), False),
    ]
    p.setPen(Qt.PenStyle.NoPen)
    for points, start, end, lit in sides:
        p.setBrush(_band_gradient(start, end, lit))
        p.drawPolygon(QPolygonF(points))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(C("wood_dark"), 1.0))
    p.drawRect(o)
    p.setPen(QPen(C("bronze_dark"), 1.0))
    p.drawRect(i)
    # Segundo filete interior: el "doble borde".
    p.setPen(QPen(C("bronze", 210), 1.0))
    p.drawRect(i.adjusted(3.5, 3.5, -3.5, -3.5))
    p.setPen(QPen(C("gold_light", 90), 1.0))
    p.drawRect(i.adjusted(4.5, 4.5, -4.5, -4.5))

    if corner > 0:
        for cx, cy in ((o.left(), o.top()), (o.right() - corner, o.top()),
                       (o.left(), o.bottom() - corner), (o.right() - corner, o.bottom() - corner)):
            plate = QRectF(cx, cy, corner, corner)
            g = QLinearGradient(plate.topLeft(), plate.bottomRight())
            g.setColorAt(0.0, C("gold_pale"))
            g.setColorAt(0.4, C("gold"))
            g.setColorAt(1.0, C("bronze_dark"))
            p.setPen(QPen(C("wood_dark"), 1.0))
            p.setBrush(g)
            p.drawRect(plate)
            p.setPen(QPen(C("bronze_dark", 220), 1.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            c = plate.center()
            d = corner * 0.34
            p.drawPolygon(QPolygonF([c + QPointF(0, -d), c + QPointF(d, 0), c + QPointF(0, d), c + QPointF(-d, 0)]))
            paint_rivet(p, c, corner * 0.16)
    if rivets:
        radius = max(1.6, band * 0.26)
        mid = band / 2
        for x in _rivet_positions(o.left() + corner, o.right() - corner, 150):
            paint_rivet(p, QPointF(x, o.top() + mid), radius)
            paint_rivet(p, QPointF(x, o.bottom() - mid), radius)
        for y in _rivet_positions(o.top() + corner, o.bottom() - corner, 150):
            paint_rivet(p, QPointF(o.left() + mid, y), radius)
            paint_rivet(p, QPointF(o.right() - mid, y), radius)
    p.restore()


def _rivet_positions(start: float, end: float, spacing: float) -> list[float]:
    length = end - start
    count = int(length // spacing)
    if count < 1:
        return []
    step = length / (count + 1)
    return [start + step * (k + 1) for k in range(count)]


def paint_thin_border(p: QPainter, rect: QRectF, corner: float = 10.0) -> None:
    """Borde fino de tarjeta: filete bronce doble con esquineras en ángulo."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    o = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(C("bronze"), 1.2))
    p.drawRect(o)
    p.setPen(QPen(C("bronze", 150), 1.0))
    p.drawRect(o.adjusted(3, 3, -3, -3))
    p.setPen(QPen(C("velvet_text"), 1.6))
    for (x, y, dx, dy) in ((o.left(), o.top(), 1, 1), (o.right(), o.top(), -1, 1),
                           (o.left(), o.bottom(), 1, -1), (o.right(), o.bottom(), -1, -1)):
        path = QPainterPath(QPointF(x + dx * corner, y + dy * 1.5))
        path.lineTo(x + dx * 1.5, y + dy * 1.5)
        path.lineTo(x + dx * 1.5, y + dy * corner)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C("velvet_text"))
        p.drawEllipse(QPointF(x + dx * 6, y + dy * 6), 1.4, 1.4)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(C("velvet_text"), 1.6))
    p.restore()


def paint_medallion(p: QPainter, rect: QRectF, icon_name: str | None = None, fill: str = "velvet",
                    icon_color: str = "gold_pale", text: str | None = None, text_font: QFont | None = None) -> None:
    """Medallón redondo: aro de oro biselado, disco de terciopelo y un icono o numeral."""
    side = min(rect.width(), rect.height())
    c = rect.center()
    r = side / 2 - 1
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    ring = QLinearGradient(c + QPointF(-r, -r), c + QPointF(r, r))
    ring.setColorAt(0.0, C("gold_pale"))
    ring.setColorAt(0.45, C("gold"))
    ring.setColorAt(1.0, C("bronze_dark"))
    p.setPen(QPen(C("wood_dark", 220), 1.0))
    p.setBrush(ring)
    p.drawEllipse(c, r, r)
    disc = QRadialGradient(c + QPointF(-r * 0.3, -r * 0.35), r * 1.1)
    base = C(fill)
    disc.setColorAt(0.0, base.lighter(150))
    disc.setColorAt(0.6, base)
    disc.setColorAt(1.0, base.darker(170))
    p.setPen(QPen(C("bronze_dark"), 1.0))
    p.setBrush(disc)
    inner = r * 0.8
    p.drawEllipse(c, inner, inner)
    if icon_name:
        size = inner * 1.15
        draw_icon(p, icon_name, QRectF(c.x() - size / 2, c.y() - size / 2, size, size), C(icon_color))
    elif text:
        f = QFont(text_font) if text_font else theme.font("numeral")
        f.setPixelSize(max(6, round(inner * 0.95)))
        p.setFont(f)
        p.setPen(C(icon_color))
        p.drawText(QRectF(c.x() - inner, c.y() - inner, inner * 2, inner * 2), Qt.AlignmentFlag.AlignCenter, text)
    p.restore()


def paint_fleuron_rule(p: QPainter, rect: QRectF, line: QColor, accent: QColor) -> None:
    """Filete horizontal que se desvanece en los extremos con un rombo central."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    y = rect.center().y()
    cx = rect.center().x()
    gap = 16.0
    for x1, x2 in ((rect.left(), cx - gap), (cx + gap, rect.right())):
        g = QLinearGradient(QPointF(rect.left(), y), QPointF(rect.right(), y))
        faded = QColor(line)
        faded.setAlpha(0)
        g.setColorAt(0.0, faded)
        g.setColorAt(0.18, line)
        g.setColorAt(0.82, line)
        g.setColorAt(1.0, faded)
        p.setPen(QPen(g, 1.2))
        p.drawLine(QPointF(x1, y - 1.5), QPointF(x2, y - 1.5))
        p.setPen(QPen(g, 0.8))
        p.drawLine(QPointF(x1, y + 1.5), QPointF(x2, y + 1.5))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(accent)
    d = 5.0
    p.drawPolygon(QPolygonF([QPointF(cx, y - d), QPointF(cx + d, y), QPointF(cx, y + d), QPointF(cx - d, y)]))
    p.setBrush(line)
    for dx in (-10.0, 10.0):
        p.drawEllipse(QPointF(cx + dx, y), 1.8, 1.8)
    p.restore()


class Divider(QWidget):
    """Filete ornamental horizontal (bronce sobre pergamino, oro sobre madera)."""

    def __init__(self, on_dark: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._on_dark = on_dark
        self.setFixedHeight(14)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        line = C("gold") if self._on_dark else C("bronze")
        accent = C("gold_light") if self._on_dark else C("velvet_text")
        paint_fleuron_rule(p, QRectF(self.rect()), line, accent)


def paint_emblem(p: QPainter, rect: QRectF) -> None:
    """Emblema de la aplicación: rueda dentada industrial, laureles, corona y numeral II."""
    side = min(rect.width(), rect.height())
    c = rect.center()
    r = side / 2 - 1
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    teeth = 18
    points = []
    for k in range(teeth * 4):
        angle = 2 * math.pi * k / (teeth * 4) - math.pi / 2
        radius = r if k % 4 in (1, 2) else r * 0.88
        points.append(c + QPointF(radius * math.cos(angle), radius * math.sin(angle)))
    metal = QLinearGradient(c + QPointF(-r, -r), c + QPointF(r, r))
    metal.setColorAt(0.0, C("gold_light"))
    metal.setColorAt(0.5, C("bronze"))
    metal.setColorAt(1.0, C("bronze_dark"))
    p.setPen(QPen(C("wood_dark"), 1.0))
    p.setBrush(metal)
    p.drawPolygon(QPolygonF(points))

    ring = QLinearGradient(c + QPointF(0, -r), c + QPointF(0, r))
    ring.setColorAt(0.0, C("gold_pale"))
    ring.setColorAt(0.5, C("gold"))
    ring.setColorAt(1.0, C("bronze_dark"))
    p.setBrush(ring)
    p.setPen(QPen(C("bronze_dark"), 1.0))
    p.drawEllipse(c, r * 0.82, r * 0.82)

    disc = QRadialGradient(c + QPointF(-r * 0.2, -r * 0.3), r * 0.9)
    disc.setColorAt(0.0, C("velvet_light"))
    disc.setColorAt(0.7, C("velvet"))
    disc.setColorAt(1.0, C("velvet_dark"))
    p.setBrush(disc)
    p.drawEllipse(c, r * 0.72, r * 0.72)

    # Laureles: hojas a lo largo de dos arcos simétricos.
    leaf_color = C("gold_light")
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(leaf_color)
    for side_sign in (-1, 1):
        for k in range(6):
            t = math.radians(112 + k * 17)
            angle = math.pi / 2 + side_sign * (t - math.pi / 2)
            pos = c + QPointF(r * 0.6 * math.cos(angle), r * 0.6 * math.sin(angle))
            p.save()
            p.translate(pos)
            p.rotate(math.degrees(angle) + (90 if side_sign > 0 else -90) + side_sign * 35)
            p.drawEllipse(QPointF(0, 0), r * 0.05, r * 0.12)
            p.restore()

    crown = QPainterPath()
    w = r * 0.42
    top = c.y() - r * 0.5
    base_y = c.y() - r * 0.2
    crown.moveTo(c.x() - w / 2, base_y)
    crown.lineTo(c.x() - w / 2, top + r * 0.12)
    crown.lineTo(c.x() - w / 4, top + r * 0.2)
    crown.lineTo(c.x(), top)
    crown.lineTo(c.x() + w / 4, top + r * 0.2)
    crown.lineTo(c.x() + w / 2, top + r * 0.12)
    crown.lineTo(c.x() + w / 2, base_y)
    crown.closeSubpath()
    p.setBrush(C("gold_light"))
    p.setPen(QPen(C("bronze_dark"), 0.8))
    p.drawPath(crown)

    f = theme.font("numeral")
    f.setPixelSize(max(6, round(r * 0.62)))
    f.setWeight(QFont.Weight.Bold)
    text = QPainterPath()
    text.addText(QPointF(0, 0), f, "II")
    bounds = text.boundingRect()
    text.translate(c.x() - bounds.center().x(), c.y() + r * 0.2 - bounds.center().y())
    fill = QLinearGradient(QPointF(0, text.boundingRect().top()), QPointF(0, text.boundingRect().bottom()))
    fill.setColorAt(0.0, C("gold_pale"))
    fill.setColorAt(1.0, C("gold"))
    p.setPen(QPen(C("velvet_dark"), 1.0))
    p.setBrush(fill)
    p.drawPath(text)
    p.restore()


def emblem_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    paint_emblem(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


class Emblem(QWidget):
    def __init__(self, size: int = 64, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        paint_emblem(p, QRectF(self.rect()))


class Medallion(QWidget):
    """Medallón con icono (cabeceras de página, estados vacíos)."""

    def __init__(self, icon_name: str, size: int = 48, fill: str = "velvet", parent: QWidget | None = None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._fill = fill
        self.setFixedSize(size, size)

    def icon_name(self) -> str:
        return self._icon_name

    def set_icon(self, icon_name: str) -> None:
        if icon_name != self._icon_name:
            self._icon_name = icon_name
            self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        paint_medallion(p, QRectF(self.rect()), self._icon_name, self._fill)
