"""Iconos del armazón: Inicio, guardar, deshacer, rehacer, historial y capas (rejilla de 24×24)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath

from ..icons import _faint, _icon, _line, _pen, _poly


@_icon("home")
def _home(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.5))
    p.setBrush(_faint(c, 0.25))
    p.drawPolygon(_poly((2.8, 11.5), (12, 3.2), (21.2, 11.5)))
    p.setBrush(_faint(c, 0.12))
    p.drawRect(QRectF(5.5, 11.2, 13, 9.8))
    p.setBrush(c)
    p.drawRoundedRect(QRectF(10, 14.2, 4, 6.8), 1.6, 1.6)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(QRectF(15.4, 4.4, 2.4, 4.4))


@_icon("save")
def _save(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.18))
    body = QPainterPath(QPointF(4, 4))
    body.lineTo(17, 4)
    body.lineTo(20, 7)
    body.lineTo(20, 20)
    body.lineTo(4, 20)
    body.closeSubpath()
    p.drawPath(body)
    p.setBrush(_faint(c, 0.45))
    p.drawRect(QRectF(7.5, 4, 8, 5.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(7, 12.5, 10, 7.5))
    p.setPen(_pen(c, 1.1))
    _line(p, 9, 15, 15, 15)
    _line(p, 9, 17.5, 15, 17.5)


def _arrow_arc(p: QPainter, c: QColor, mirror: bool) -> None:
    p.save()
    if mirror:
        p.translate(24, 0)
        p.scale(-1, 1)
    p.setPen(_pen(c, 1.8))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(6.5, 10))
    path.cubicTo(9, 5.5, 17.5, 5.5, 19.5, 11)
    path.cubicTo(21, 15.5, 17.5, 19.5, 12.5, 19.5)
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawPolygon(_poly((3.2, 6.4), (10.2, 9.4), (4.6, 13.8)))
    p.restore()


@_icon("undo")
def _undo(p: QPainter, c: QColor) -> None:
    _arrow_arc(p, c, mirror=False)


@_icon("redo")
def _redo(p: QPainter, c: QColor) -> None:
    _arrow_arc(p, c, mirror=True)


@_icon("history")
def _history(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.5))
    p.setBrush(_faint(c, 0.15))
    p.drawEllipse(QPointF(12.5, 12.5), 8.5, 8.5)
    p.setPen(_pen(c, 1.7))
    _line(p, 12.5, 12.5, 12.5, 7.2)
    _line(p, 12.5, 12.5, 16.2, 14.6)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    for k in range(12):
        angle = k * math.pi / 6
        p.drawEllipse(QPointF(12.5 + 6.6 * math.cos(angle), 12.5 + 6.6 * math.sin(angle)), 0.55, 0.55)
    p.drawPolygon(_poly((1.6, 9.5), (6.4, 9.0), (3.4, 13.4)))


@_icon("layers")
def _layers(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.3))
    for k, alpha in ((2, 0.15), (1, 0.28), (0, 0.45)):
        y = 6 + k * 4.2
        p.setBrush(_faint(c, alpha))
        p.drawPolygon(_poly((12, y - 3.6), (21, y + 0.6), (12, y + 4.8), (3, y + 0.6)))
