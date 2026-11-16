"""Iconos de la iteración 3: añadir (Textos), arreglar y «¿por qué?» (Validación y panel de problemas), en 24×24."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath

from ..icons import _faint, _icon, _line, _pen


@_icon("plus")
def _plus(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.18))
    p.drawEllipse(QRectF(3.5, 3.5, 17, 17))
    p.setPen(_pen(c, 2.2))
    _line(p, 12, 7.5, 12, 16.5)
    _line(p, 7.5, 12, 16.5, 12)


@_icon("wrench")
def _wrench(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.3))
    head = QPainterPath()
    head.addEllipse(QRectF(12.5, 3, 8.5, 8.5))
    notch = QPainterPath()
    notch.addRect(QRectF(16, 2, 3.2, 5))
    p.drawPath(head.subtracted(notch))
    pen = _pen(c, 3.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    _line(p, 14, 10, 5, 19)


@_icon("question")
def _question(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.18))
    p.drawEllipse(QRectF(3.5, 3.5, 17, 17))
    p.setPen(_pen(c, 2.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(9.2, 9.6))
    path.cubicTo(QPointF(9.2, 6.2), QPointF(15, 6.2), QPointF(14.8, 9.6))
    path.cubicTo(QPointF(14.6, 11.6), QPointF(12, 11.8), QPointF(12, 14.2))
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawEllipse(QRectF(10.8, 15.8, 2.4, 2.4))


@_icon("minus")
def _minus(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.4))
    p.setBrush(_faint(c, 0.18))
    p.drawEllipse(QRectF(3.5, 3.5, 17, 17))
    p.setPen(_pen(c, 2.2))
    _line(p, 7.5, 12, 16.5, 12)


@_icon("trash")
def _trash(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.5))
    p.setBrush(_faint(c, 0.18))
    body = QPainterPath(QPointF(6, 7.5))
    for x, y in ((18, 7.5), (16.8, 21), (7.2, 21)):
        body.lineTo(x, y)
    body.closeSubpath()
    p.drawPath(body)
    _line(p, 4, 7.5, 20, 7.5)
    p.setBrush(Qt.BrushStyle.NoBrush)
    lid = QPainterPath(QPointF(9.5, 7.5))
    lid.lineTo(10, 4)
    lid.lineTo(14, 4)
    lid.lineTo(14.5, 7.5)
    p.drawPath(lid)
    _line(p, 10.2, 10.5, 10.5, 18)
    _line(p, 13.8, 10.5, 13.5, 18)
