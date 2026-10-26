"""Iconos vectoriales dibujados con QPainter sobre una rejilla de 24×24 unidades.

``draw_icon`` pinta directamente (nítido a cualquier escala); ``make_icon``
construye un ``QIcon`` con mapas de bits por tamaño, modo y densidad de píxel.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from .. import theme

DrawFn = Callable[[QPainter, QColor], None]
_ICONS: dict[str, DrawFn] = {}
_icon_cache: dict[tuple, QIcon] = {}


def _icon(name: str):
    def register(fn: DrawFn) -> DrawFn:
        _ICONS[name] = fn
        return fn
    return register


def icon_names() -> list[str]:
    return sorted(_ICONS)


def _pen(c: QColor, width: float = 1.6) -> QPen:
    return QPen(c, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)


def _faint(c: QColor, alpha: float) -> QColor:
    f = QColor(c)
    f.setAlphaF(c.alphaF() * alpha)
    return f


def _poly(*points: tuple[float, float]) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in points])


def _line(p: QPainter, x1: float, y1: float, x2: float, y2: float) -> None:
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


# --- módulos ----------------------------------------------------------------------------

@_icon("project")
def _project(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.setBrush(_faint(c, 0.18))
    p.drawRoundedRect(QRectF(4.5, 3, 15, 18), 1.6, 1.6)
    _line(p, 8, 3, 8, 21)
    p.setPen(_pen(c, 1.2))
    _line(p, 10.5, 7.5, 16.5, 7.5)
    _line(p, 10.5, 10, 15, 10)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRect(QRectF(18, 10, 2.6, 4.2))
    p.drawPolygon(_poly((13.5, 13.2), (15.4, 15.6), (13.5, 18), (11.6, 15.6)))


@_icon("map")
def _map(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(12, 12), 9.2, 9.2)
    p.setPen(Qt.PenStyle.NoPen)
    tips = [(12, 1.8), (22.2, 12), (12, 22.2), (1.8, 12)]
    inner = 1.9
    for i, (tx, ty) in enumerate(tips):
        angle = math.atan2(ty - 12, tx - 12)
        left = (12 + inner * math.cos(angle - math.pi / 2), 12 + inner * math.sin(angle - math.pi / 2))
        right = (12 + inner * math.cos(angle + math.pi / 2), 12 + inner * math.sin(angle + math.pi / 2))
        p.setBrush(c)
        p.drawPolygon(_poly((12, 12), (tx, ty), left))
        p.setBrush(_faint(c, 0.45))
        p.drawPolygon(_poly((12, 12), (tx, ty), right))
    for k in range(4):
        angle = math.pi / 4 + k * math.pi / 2
        tip = (12 + 6.2 * math.cos(angle), 12 + 6.2 * math.sin(angle))
        a1 = (12 + 1.6 * math.cos(angle - 0.9), 12 + 1.6 * math.sin(angle - 0.9))
        a2 = (12 + 1.6 * math.cos(angle + 0.9), 12 + 1.6 * math.sin(angle + 0.9))
        p.setBrush(_faint(c, 0.7))
        p.drawPolygon(_poly(a1, tip, a2, (12, 12)))
    p.setBrush(c)
    p.drawEllipse(QPointF(12, 12), 1.3, 1.3)


@_icon("countries")
def _countries(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.8))
    _line(p, 5.5, 3.5, 5.5, 21.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawEllipse(QPointF(5.5, 2.6), 1.4, 1.4)
    flag = QPainterPath(QPointF(6.6, 4.4))
    flag.cubicTo(10.5, 2.8, 13.5, 6.2, 20, 4.4)
    flag.lineTo(20, 13.4)
    flag.cubicTo(13.5, 15.2, 10.5, 11.8, 6.6, 13.4)
    flag.closeSubpath()
    p.setBrush(_faint(c, 0.35))
    p.drawPath(flag)
    p.save()
    p.setClipPath(flag)
    p.setBrush(c)
    p.drawRect(QRectF(6.6, 2, 4.5, 14))
    p.drawRect(QRectF(15.5, 2, 4.5, 14))
    p.restore()
    p.setPen(_pen(c, 1.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(flag)


@_icon("events")
def _events(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.15))
    p.drawRect(QRectF(6, 5, 12, 13.5))
    p.setBrush(_faint(c, 0.45))
    p.drawRoundedRect(QRectF(4, 2.8, 16, 3.6), 1.8, 1.8)
    p.drawRoundedRect(QRectF(4, 17.4, 16, 3.6), 1.8, 1.8)
    p.setPen(_pen(c, 1.1))
    for y in (9, 11.5, 14):
        _line(p, 8.5, y, 15.5 if y < 14 else 12.5, y)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawEllipse(QPointF(16.3, 15.4), 2.5, 2.5)
    p.drawPolygon(_poly((15.2, 17.2), (14.6, 21.6), (16.2, 20.4), (17.6, 21.6), (17.4, 17.2)))


@_icon("localisation")
def _localisation(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.12))
    p.drawEllipse(QPointF(12, 12), 9.2, 9.2)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(12, 12), 4.2, 9.2)
    _line(p, 2.8, 12, 21.2, 12)
    for y, bulge in ((7.2, -1.2), (16.8, 1.2)):
        path = QPainterPath(QPointF(4.4, y))
        path.quadTo(12, y + bulge, 19.6, y)
        p.drawPath(path)


# --- archivos y carpetas ----------------------------------------------------------------

@_icon("folder")
def _folder(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.3))
    tab = QPainterPath(QPointF(3, 8))
    tab.lineTo(3, 5.6)
    tab.quadTo(3, 4.6, 4, 4.6)
    tab.lineTo(9, 4.6)
    tab.lineTo(10.8, 6.6)
    tab.lineTo(20, 6.6)
    tab.quadTo(21, 6.6, 21, 7.6)
    tab.lineTo(21, 18.4)
    tab.quadTo(21, 19.4, 20, 19.4)
    tab.lineTo(4, 19.4)
    tab.quadTo(3, 19.4, 3, 18.4)
    tab.closeSubpath()
    p.drawPath(tab)
    _line(p, 3, 9, 21, 9)


@_icon("folder_open")
def _folder_open(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.15))
    back = QPainterPath(QPointF(3, 18.4))
    back.lineTo(3, 5.6)
    back.quadTo(3, 4.6, 4, 4.6)
    back.lineTo(9, 4.6)
    back.lineTo(10.8, 6.6)
    back.lineTo(19, 6.6)
    back.quadTo(20, 6.6, 20, 7.6)
    back.lineTo(20, 10)
    p.drawPath(back)
    p.setBrush(_faint(c, 0.45))
    p.drawPolygon(_poly((6.2, 10.4), (22.4, 10.4), (19.2, 19.4), (3, 19.4)))


def _page(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.14))
    page = QPainterPath(QPointF(6, 3))
    page.lineTo(14.5, 3)
    page.lineTo(19, 7.5)
    page.lineTo(19, 21)
    page.lineTo(6, 21)
    page.closeSubpath()
    p.drawPath(page)
    p.setBrush(_faint(c, 0.4))
    p.drawPolygon(_poly((14.5, 3), (14.5, 7.5), (19, 7.5)))


@_icon("file")
def _file(p: QPainter, c: QColor) -> None:
    _page(p, c)


@_icon("file_text")
def _file_text(p: QPainter, c: QColor) -> None:
    _page(p, c)
    p.setPen(_pen(c, 1.2))
    for y, x2 in ((11, 16.5), (14, 16.5), (17, 13.5)):
        _line(p, 8.6, y, x2, y)


@_icon("file_table")
def _file_table(p: QPainter, c: QColor) -> None:
    _page(p, c)
    p.setPen(_pen(c, 1.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(8.4, 10, 8.2, 8))
    _line(p, 8.4, 12.7, 16.6, 12.7)
    _line(p, 8.4, 15.3, 16.6, 15.3)
    _line(p, 11.6, 10, 11.6, 18)


@_icon("file_image")
def _file_image(p: QPainter, c: QColor) -> None:
    _page(p, c)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPolygon(_poly((8, 18.4), (11.2, 13.4), (13.2, 16), (14.6, 14.6), (17.2, 18.4)))
    p.drawEllipse(QPointF(15.2, 11.2), 1.3, 1.3)


@_icon("file_code")
def _file_code(p: QPainter, c: QColor) -> None:
    _page(p, c)
    p.setPen(_pen(c, 1.3))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(_poly((10.6, 11.6), (8.4, 14.4), (10.6, 17.2)))
    p.drawPolyline(_poly((14.4, 11.6), (16.6, 14.4), (14.4, 17.2)))


@_icon("file_mod")
def _file_mod(p: QPainter, c: QColor) -> None:
    _page(p, c)
    p.setPen(_pen(c, 1.2))
    p.setBrush(_faint(c, 0.3))
    p.drawEllipse(QPointF(12.5, 14.6), 3.4, 3.4)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawEllipse(QPointF(12.5, 14.6), 1.3, 1.3)


# --- acciones y estados -----------------------------------------------------------------

@_icon("search")
def _search(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 2.0))
    p.setBrush(_faint(c, 0.12))
    p.drawEllipse(QPointF(10.4, 10.4), 6.2, 6.2)
    p.setPen(_pen(c, 2.8))
    _line(p, 15.2, 15.2, 20.6, 20.6)


@_icon("check")
def _check(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.5))
    p.setBrush(_faint(c, 0.16))
    p.drawEllipse(QPointF(12, 12), 9, 9)
    p.setPen(_pen(c, 2.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(_poly((7.6, 12.4), (10.7, 15.4), (16.4, 8.8)))


@_icon("warning")
def _warning(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.5))
    p.setBrush(_faint(c, 0.16))
    p.drawPolygon(_poly((12, 3), (21.6, 20), (2.4, 20)))
    p.setPen(_pen(c, 2.2))
    _line(p, 12, 9, 12, 14)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawEllipse(QPointF(12, 17), 1.3, 1.3)


@_icon("error")
def _error(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.5))
    p.setBrush(_faint(c, 0.16))
    p.drawEllipse(QPointF(12, 12), 9, 9)
    p.setPen(_pen(c, 2.2))
    _line(p, 8.6, 8.6, 15.4, 15.4)
    _line(p, 15.4, 8.6, 8.6, 15.4)


@_icon("info")
def _info(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.5))
    p.setBrush(_faint(c, 0.16))
    p.drawEllipse(QPointF(12, 12), 9, 9)
    p.setPen(_pen(c, 2.2))
    _line(p, 12, 11, 12, 16.6)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawEllipse(QPointF(12, 7.6), 1.4, 1.4)


@_icon("collapse")
def _collapse(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.9))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(_poly((7, 4.5), (12, 9.5), (17, 4.5)))
    p.drawPolyline(_poly((7, 19.5), (12, 14.5), (17, 19.5)))
    p.setPen(_pen(c, 1.2))
    _line(p, 5, 12, 19, 12)


@_icon("expand")
def _expand(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.9))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(_poly((7, 9), (12, 4), (17, 9)))
    p.drawPolyline(_poly((7, 15), (12, 20), (17, 15)))
    p.setPen(_pen(c, 1.2))
    _line(p, 5, 12, 19, 12)


@_icon("chevron_up")
def _chevron_up(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 2.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(_poly((6, 15), (12, 9), (18, 15)))


@_icon("chevron_down")
def _chevron_down(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 2.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(_poly((6, 9), (12, 15), (18, 9)))


@_icon("lock")
def _lock(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.8))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(7.5, 3.5, 9, 10), 0, 180 * 16)
    _line(p, 7.5, 8.5, 7.5, 11)
    _line(p, 16.5, 8.5, 16.5, 11)
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.35))
    p.drawRoundedRect(QRectF(5, 11, 14, 10), 1.6, 1.6)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawEllipse(QPointF(12, 15.2), 1.5, 1.5)
    p.drawRect(QRectF(11.3, 15.6, 1.4, 3))


@_icon("validate")
def _validate(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.16))
    p.drawPolygon(_poly((12, 2.5), (19.5, 5.5), (19, 13), (12, 21.5), (5, 13), (4.5, 5.5)))
    p.setPen(_pen(c, 2.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(_poly((8.2, 11.6), (11, 14.4), (16, 8.6)))


@_icon("refresh")
def _refresh(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.9))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(4.5, 4.5, 15, 15), 40 * 16, 290 * 16)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPolygon(_poly((14.6, 2.6), (20.4, 6.6), (14.2, 9.4)))


@_icon("copy")
def _copy(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.1))
    p.drawRoundedRect(QRectF(4, 3.5, 11, 13), 1.2, 1.2)
    p.setBrush(_faint(c, 0.3))
    p.drawRoundedRect(QRectF(9, 7.5, 11, 13), 1.2, 1.2)


@_icon("external")
def _external(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(_poly((11, 5), (5, 5), (5, 19), (19, 19), (19, 13)))
    _line(p, 11.5, 12.5, 19.5, 4.5)
    p.drawPolyline(_poly((14, 4.5), (19.5, 4.5), (19.5, 10)))


@_icon("gear")
def _gear(p: QPainter, c: QColor) -> None:
    teeth = 9
    outer, inner = 9.6, 7.4
    points = []
    for i in range(teeth * 4):
        angle = 2 * math.pi * i / (teeth * 4)
        radius = outer if i % 4 in (1, 2) else inner
        points.append((12 + radius * math.cos(angle), 12 + radius * math.sin(angle)))
    gear = QPainterPath()
    gear.addPolygon(_poly(*points))
    gear.closeSubpath()
    gear.addEllipse(QPointF(12, 12), 3.2, 3.2)
    p.setPen(_pen(c, 1.2))
    p.setBrush(_faint(c, 0.4))
    p.drawPath(gear)


@_icon("quill")
def _quill(p: QPainter, c: QColor) -> None:
    vane = QPainterPath(QPointF(20.5, 2.5))
    vane.cubicTo(13, 3.5, 7.6, 9.5, 6.4, 17.6)
    vane.cubicTo(9.5, 15.6, 11.8, 14.4, 13.2, 12.2)
    vane.lineTo(11.2, 12.2)
    vane.cubicTo(13.8, 11, 16.8, 9.2, 18.2, 7.2)
    vane.lineTo(16.4, 7.4)
    vane.cubicTo(18.6, 6, 20, 4.6, 20.5, 2.5)
    vane.closeSubpath()
    p.setPen(_pen(c, 1.1))
    p.setBrush(_faint(c, 0.45))
    p.drawPath(vane)
    p.setPen(_pen(c, 1.6))
    _line(p, 17.6, 5.2, 4, 21)


@_icon("scroll_seal")
def _scroll_seal(p: QPainter, c: QColor) -> None:
    _events(p, c)


@_icon("roadmap")
def _roadmap(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.18))
    p.drawPolygon(_poly((3, 5.5), (9, 3.5), (15, 5.5), (21, 3.5), (21, 18.5), (15, 20.5), (9, 18.5), (3, 20.5)))
    _line(p, 9, 3.5, 9, 18.5)
    _line(p, 15, 5.5, 15, 20.5)


# --- API ---------------------------------------------------------------------------------

def draw_icon(painter: QPainter, name: str, rect: QRectF, color: QColor) -> None:
    """Pinta el icono ``name`` centrado y escalado dentro de ``rect``."""
    side = min(rect.width(), rect.height())
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(rect.center().x() - side / 2, rect.center().y() - side / 2)
    painter.scale(side / 24.0, side / 24.0)
    _ICONS[name](painter, QColor(color))
    painter.restore()


def icon_pixmap(name: str, size: int, color: QColor, device_pixel_ratio: float = 1.0) -> QPixmap:
    pixmap = QPixmap(QSize(round(size * device_pixel_ratio), round(size * device_pixel_ratio)))
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    draw_icon(painter, name, QRectF(0, 0, size, size), color)
    painter.end()
    return pixmap


def make_icon(name: str, normal: str = "ink_soft", selected: str = "cream", active: str | None = None) -> QIcon:
    """``QIcon`` multi-tamaño; los nombres de color son claves de ``theme.PALETTE``."""
    key = (name, normal, selected, active)
    if key not in _icon_cache:
        icon = QIcon()
        modes = {
            QIcon.Mode.Normal: theme.color(normal),
            QIcon.Mode.Selected: theme.color(selected),
            QIcon.Mode.Active: theme.color(active or normal),
            QIcon.Mode.Disabled: theme.color("cream_disabled" if normal in {"cream", "gold_light", "gold_pale"} else "parchment_shadow"),
        }
        for mode, tint in modes.items():
            for size in (16, 20, 24, 32, 48):
                for ratio in (1.0, 2.0):
                    icon.addPixmap(icon_pixmap(name, size, tint, ratio), mode)
        _icon_cache[key] = icon
    return _icon_cache[key]
