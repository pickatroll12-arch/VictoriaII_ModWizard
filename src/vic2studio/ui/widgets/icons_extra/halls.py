"""Iconos de las salas y sus secciones (Guerra, Interfaz, Naciones, Mapa), en la rejilla de 24×24."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath

from ..icons import _faint, _icon, _line, _pen, _poly


@_icon("swords")
def _swords(p: QPainter, c: QColor) -> None:
    for mirror in (False, True):
        p.save()
        if mirror:
            p.translate(24, 0)
            p.scale(-1, 1)
        p.setPen(_pen(c, 1.2))
        p.setBrush(_faint(c, 0.35))
        p.drawPolygon(_poly((3.2, 3.2), (6.2, 3.6), (17.2, 14.6), (14.6, 17.2), (3.6, 6.2)))
        p.setPen(_pen(c, 2.0))
        _line(p, 13.4, 18.8, 18.8, 13.4)
        _line(p, 17.4, 17.4, 20.6, 20.6)
        p.restore()


@_icon("window")
def _window(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.12))
    p.drawRoundedRect(QRectF(3, 4, 18, 16), 1.6, 1.6)
    p.setBrush(_faint(c, 0.45))
    p.drawRect(QRectF(3, 4, 18, 3.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(5.5, 10, 6, 7.5))
    p.setPen(_pen(c, 1.1))
    for y in (10.8, 13.4, 16):
        _line(p, 13.5, y, 18.5, y)


@_icon("crown")
def _crown(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.35))
    p.drawPolygon(_poly((3.5, 8), (8, 12.5), (12, 5), (16, 12.5), (20.5, 8), (19, 17.5), (5, 17.5)))
    p.setBrush(_faint(c, 0.55))
    p.drawRoundedRect(QRectF(4.6, 17.5, 14.8, 3), 1, 1)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    for x, y in ((3.5, 7.2), (12, 4.2), (20.5, 7.2)):
        p.drawEllipse(QPointF(x, y), 1.4, 1.4)


@_icon("ship")
def _ship(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.4))
    p.drawPolygon(_poly((2.5, 15), (21.5, 15), (18.5, 20), (5.5, 20)))
    _line(p, 12, 3, 12, 15)
    p.setBrush(_faint(c, 0.2))
    p.drawPolygon(_poly((12.8, 4), (19.5, 12.8), (12.8, 12.8)))
    p.drawPolygon(_poly((11.2, 6), (11.2, 12.8), (5.5, 12.8)))


@_icon("helmet")
def _helmet(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.3))
    dome = QPainterPath(QPointF(4.5, 15))
    dome.cubicTo(4.5, 6.5, 19.5, 6.5, 19.5, 15)
    dome.closeSubpath()
    p.drawPath(dome)
    p.setBrush(_faint(c, 0.5))
    p.drawRoundedRect(QRectF(2.5, 15, 19, 3), 1.2, 1.2)
    p.setPen(_pen(c, 1.8))
    _line(p, 12, 4, 12, 8.6)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawEllipse(QPointF(12, 3.6), 1.6, 1.6)


@_icon("calendar")
def _calendar(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.12))
    p.drawRoundedRect(QRectF(3.5, 5, 17, 15.5), 1.6, 1.6)
    p.setBrush(_faint(c, 0.45))
    p.drawRect(QRectF(3.5, 5, 17, 4))
    p.setPen(_pen(c, 1.8))
    _line(p, 8, 3, 8, 6.5)
    _line(p, 16, 3, 16, 6.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    for row in range(2):
        for col in range(3):
            p.drawRect(QRectF(6.2 + col * 4.4, 11.6 + row * 4, 2.4, 2.2))


@_icon("handshake")
def _handshake(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.3))
    p.drawPolygon(_poly((2, 9), (7, 7.5), (12, 10), (16, 13.5), (14, 16), (10, 14.5), (6.5, 16), (2, 14)))
    p.drawPolygon(_poly((22, 9), (17, 7.5), (11.5, 9.5), (9, 12), (11, 13), (14.5, 11.8), (19, 15.5), (22, 14)))
    p.setPen(_pen(c, 1.1))
    _line(p, 10.5, 15, 12.5, 17.5)
    _line(p, 13, 14.2, 15.2, 16.6)


@_icon("anvil")
def _anvil(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.4))
    top = QPainterPath(QPointF(2.5, 8))
    top.lineTo(19.5, 8)
    top.lineTo(21.5, 6.5)
    top.lineTo(21.5, 11)
    top.lineTo(16.5, 12)
    top.lineTo(15, 14.5)
    top.lineTo(9, 14.5)
    top.lineTo(7.5, 12)
    top.cubicTo(5, 12, 3, 10.5, 2.5, 8)
    top.closeSubpath()
    p.drawPath(top)
    p.setBrush(_faint(c, 0.25))
    p.drawPolygon(_poly((9.5, 14.5), (14.5, 14.5), (17, 19.5), (7, 19.5)))
    p.setPen(_pen(c, 1.2))
    for k, length in ((0, 2.6), (1, 3.4), (2, 2.6)):
        angle = -math.pi / 2 + (k - 1) * 0.55
        _line(p, 12 + 1.6 * math.cos(angle), 5.4 + 1.6 * math.sin(angle),
              12 + (1.6 + length) * math.cos(angle), 5.4 + (1.6 + length) * math.sin(angle))


@_icon("anchor")
def _anchor(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(12, 4.6), 2, 2)
    _line(p, 12, 6.6, 12, 20.5)
    _line(p, 7.5, 9.5, 16.5, 9.5)
    arc = QPainterPath(QPointF(4.5, 13.5))
    arc.cubicTo(5, 19, 9.5, 20.5, 12, 20.5)
    arc.cubicTo(14.5, 20.5, 19, 19, 19.5, 13.5)
    p.drawPath(arc)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPolygon(_poly((2.6, 15.2), (4.5, 11.6), (6.6, 15)))
    p.drawPolygon(_poly((17.4, 15), (19.5, 11.6), (21.4, 15.2)))


@_icon("climate")
def _climate(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.3))
    p.setBrush(_faint(c, 0.35))
    p.drawEllipse(QPointF(8.5, 8.5), 3.8, 3.8)
    p.setPen(_pen(c, 1.2))
    for k in range(8):
        angle = k * math.pi / 4
        _line(p, 8.5 + 5.2 * math.cos(angle), 8.5 + 5.2 * math.sin(angle),
              8.5 + 6.8 * math.cos(angle), 8.5 + 6.8 * math.sin(angle))
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.2))
    cloud = QPainterPath(QPointF(9, 20))
    cloud.cubicTo(5.5, 20, 5.5, 15, 9.5, 15)
    cloud.cubicTo(10, 11.5, 16, 11, 17, 14.5)
    cloud.cubicTo(21.5, 14.5, 21.5, 20, 18, 20)
    cloud.closeSubpath()
    p.drawPath(cloud)


@_icon("culture")
def _culture(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.3))
    for x, y, r in ((8, 8, 3), (16, 8, 3), (12, 6, 3.2)):
        p.drawEllipse(QPointF(x, y), r, r)
    for x, w in ((3, 10), (11, 10)):
        body = QPainterPath(QPointF(x, 20))
        body.cubicTo(x, 13.5, x + w, 13.5, x + w, 20)
        body.closeSubpath()
        p.drawPath(body)
    p.setBrush(_faint(c, 0.5))
    body = QPainterPath(QPointF(6.5, 21))
    body.cubicTo(6.5, 12.5, 17.5, 12.5, 17.5, 21)
    body.closeSubpath()
    p.drawPath(body)


@_icon("flag")
def _flag(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.3))
    p.setBrush(_faint(c, 0.12))
    p.drawRect(QRectF(3, 5.5, 18, 13))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_faint(c, 0.75))
    p.drawRect(QRectF(3, 5.5, 6, 13))
    p.setBrush(_faint(c, 0.35))
    p.drawRect(QRectF(9, 5.5, 6, 13))
