"""Cabecera-estandarte de terciopelo con emblema, título dorado en relieve y zona derecha."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .. import theme
from .ornaments import Emblem
from .surfaces import TexturedPanel

C = theme.color


class EmbossedLabel(QLabel):
    """Etiqueta con relleno de oro degradado, contorno y sombra (texto accesible vía ``text()``)."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setContentsMargins(0, 0, 3, 3)

    def sizeHint(self) -> QSize:
        fm = QFontMetricsF(self.font())
        m = self.contentsMargins()
        return QSize(int(fm.horizontalAdvance(self.text()) + m.left() + m.right() + 6),
                     int(fm.height() + m.top() + m.bottom() + 2))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fm = QFontMetricsF(self.font())
        cr = QRectF(self.contentsRect())
        baseline = cr.top() + (cr.height() - fm.height()) / 2 + fm.ascent()
        path = QPainterPath()
        path.addText(QPointF(cr.left() + 1, baseline), self.font(), self.text())
        p.save()
        p.translate(1.6, 2.2)
        p.fillPath(path, QColor(10, 0, 0, 150))
        p.restore()
        p.strokePath(path, QPen(C("velvet_dark"), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
        gold = QLinearGradient(QPointF(0, baseline - fm.ascent()), QPointF(0, baseline + fm.descent()))
        gold.setColorAt(0.0, C("gold_pale"))
        gold.setColorAt(0.45, C("gold_light"))
        gold.setColorAt(0.6, C("gold"))
        gold.setColorAt(1.0, QColor("#a17a32"))
        p.fillPath(path, gold)


class HeaderBanner(TexturedPanel):
    """Estandarte superior: emblema + título + lema, y un hueco a la derecha para controles."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__("velvet", vignette=0.55, parent=parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 10, 22, 14)
        layout.setSpacing(16)
        self.emblem = Emblem(66)
        layout.addWidget(self.emblem, 0, Qt.AlignmentFlag.AlignVCenter)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addStretch(1)
        self.title_label = EmbossedLabel()
        self.title_label.setObjectName("bannerTitle")
        self.title_label.setFont(theme.font("banner"))
        titles.addWidget(self.title_label)
        self.tagline_label = QLabel()
        self.tagline_label.setObjectName("bannerTagline")
        self.tagline_label.setFont(theme.font("tagline"))
        titles.addWidget(self.tagline_label)
        titles.addStretch(1)
        layout.addLayout(titles, 1)

        self.trailing = QHBoxLayout()
        self.trailing.setSpacing(10)
        layout.addLayout(self.trailing)

    def set_texts(self, title: str, tagline: str) -> None:
        self.title_label.setText(title)
        self.title_label.updateGeometry()
        self.tagline_label.setText(tagline)

    def add_trailing_widget(self, widget: QWidget) -> None:
        self.trailing.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)

    def paint_decoration(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w, h = self.width(), self.height()
        p.setPen(QPen(C("gold_light", 150), 1))
        p.drawLine(0, 0, w, 0)
        p.setPen(QPen(C("gold", 90), 1))
        p.drawLine(0, 3, w, 3)
        band = QLinearGradient(QPointF(0, h - 6), QPointF(0, h))
        band.setColorAt(0.0, C("wood_dark"))
        band.setColorAt(0.2, C("gold_light"))
        band.setColorAt(0.55, C("gold"))
        band.setColorAt(0.85, C("bronze_dark"))
        band.setColorAt(1.0, C("wood_dark"))
        p.fillRect(QRectF(0, h - 6, w, 6), band)
        p.setPen(QPen(C("gold", 110), 1))
        p.drawLine(0, h - 10, w, h - 10)
