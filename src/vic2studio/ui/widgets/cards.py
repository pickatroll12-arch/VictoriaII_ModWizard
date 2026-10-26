"""Piezas de contenido reutilizables: insignias de estado, estados vacíos, cintas y hoja de ruta.

Ninguna traduce por sí misma: el dueño les pasa el texto ya traducido y las
vuelve a rellenar en su ``retranslate()``.
"""

from __future__ import annotations

import html
import re

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from .. import theme
from .icons import draw_icon
from .ornaments import Medallion, paint_medallion

C = theme.color

LEVEL_ICONS = {"ok": "check", "warning": "warning", "error": "error", "neutral": "info"}
LEVEL_COLORS = {"ok": "success", "warning": "warning", "error": "danger", "neutral": "ink_muted"}

_CODE = re.compile(r"`([^`]+)`")


def rich(text: str, code_point_size: float = 9.5) -> str:
    """Texto de catálogo -> HTML: los fragmentos entre comillas invertidas se muestran como código."""
    family = theme.resolve_family(theme.MONO_FAMILIES) or "monospace"

    def code(match: re.Match) -> str:
        return (f"<span style=\"font-family:'{family}'; font-size:{code_point_size:g}pt;"
                f" color:{theme.PALETTE['velvet_text']};\">{match.group(1)}</span>")
    return _CODE.sub(code, html.escape(text, quote=False))


def mark_data(widget: QWidget) -> QWidget:
    """Marca un widget cuyo texto es un dato (ruta, nombre de archivo) y no se traduce."""
    widget.setProperty("i18nData", True)
    return widget


class IconWidget(QWidget):
    def __init__(self, icon_name: str, size: int = 20, color: str = "ink_soft", parent: QWidget | None = None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._color = color
        self.setFixedSize(size, size)

    def set_icon(self, icon_name: str, color: str | None = None) -> None:
        self._icon_name = icon_name
        if color:
            self._color = color
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        draw_icon(p, self._icon_name, QRectF(self.rect()), C(self._color))


class StatusBadge(QWidget):
    """Icono + mensaje coloreado según el nivel (``ok``, ``warning``, ``error``, ``neutral``)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.icon = IconWidget("info", 18, "ink_muted")
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.label, 1)
        self.level = "neutral"

    def set_status(self, level: str, text: str) -> None:
        self.level = level
        self.icon.set_icon(LEVEL_ICONS[level], LEVEL_COLORS[level])
        self.label.setProperty("level", level)
        self.label.setText(text)
        self.label.style().unpolish(self.label)
        self.label.style().polish(self.label)


def show_in_stack(stack: QStackedWidget, widget: QWidget) -> None:
    """Muestra ``widget`` en ``stack``; las páginas ocultas no imponen su tamaño mínimo."""
    for index in range(stack.count()):
        page = stack.widget(index)
        policy = QSizePolicy.Policy.Preferred if page is widget else QSizePolicy.Policy.Ignored
        page.setSizePolicy(policy, policy)
    stack.setCurrentWidget(widget)


class FolderChip(QLabel):
    """Píldora con el nombre de una carpeta esperada; verde si existe."""

    def __init__(self, folder: str, parent: QWidget | None = None):
        super().__init__(folder, parent)
        self.folder = folder
        self.setObjectName("folderChip")
        mark_data(self)
        self.set_present(False)

    def set_present(self, present: bool) -> None:
        self.setProperty("present", present)
        self.style().unpolish(self)
        self.style().polish(self)


class EmptyState(QWidget):
    """Estado vacío elegante: medallón, título, texto explicativo y acciones opcionales.

    Si no cabe entero oculta el medallón para que el texto nunca se solape.
    """

    def __init__(self, icon_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(8)
        layout.addStretch(1)
        self.medallion = Medallion(icon_name, 64)
        layout.addWidget(self.medallion, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = QLabel()
        self.title.setProperty("role", "empty-title")
        self.title.setFont(theme.font("heading", 14))
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.text = QLabel()
        self.text.setProperty("role", "empty-text")
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.text)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self.actions.addStretch(1)
        self.actions.addStretch(1)
        layout.addLayout(self.actions)
        self.extra = QVBoxLayout()
        layout.addLayout(self.extra)
        layout.addStretch(1)

    def set_texts(self, title: str, text: str) -> None:
        self.title.setText(title)
        self.text.setText(rich(text))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        layout = self.layout()
        # Altura necesaria con el medallón visible, se esté mostrando o no.
        extra = 0 if not self.medallion.isHidden() else self.medallion.height() + layout.spacing()
        needed = layout.totalHeightForWidth(self.width()) if layout.hasHeightForWidth() \
            else layout.totalSizeHint().height()
        show = self.height() >= needed + extra
        if show == self.medallion.isHidden():
            self.medallion.setVisible(show)

    def add_action(self, widget: QWidget) -> None:
        self.actions.insertWidget(self.actions.count() - 1, widget)


class RibbonBadge(QLabel):
    """Cinta de terciopelo con extremos en cola de golondrina y texto en oro."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setFont(theme.font("badge", 9.5))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        fm = QFontMetricsF(self.font())
        return QSize(int(fm.horizontalAdvance(self.text()) + 44), int(fm.height() + 12))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        notch = 9.0
        shape = QPolygonF([
            r.topLeft(), r.topRight(), QPointF(r.right() - notch, r.center().y()), r.bottomRight(),
            r.bottomLeft(), QPointF(r.left() + notch, r.center().y()),
        ])
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0.0, C("velvet_light"))
        g.setColorAt(0.5, C("velvet"))
        g.setColorAt(1.0, C("velvet_dark"))
        p.setPen(QPen(C("gold"), 1.2))
        p.setBrush(g)
        p.drawPolygon(shape)
        p.setPen(QPen(C("gold", 120), 0.8, Qt.PenStyle.DotLine))
        p.drawLine(QPointF(r.left() + notch + 4, r.top() + 3), QPointF(r.right() - notch - 4, r.top() + 3))
        p.drawLine(QPointF(r.left() + notch + 4, r.bottom() - 3), QPointF(r.right() - notch - 4, r.bottom() - 3))
        p.setFont(self.font())
        p.setPen(C("gold_pale"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text())


ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")


class NumeralBadge(QWidget):
    """Medallón con numeral romano (pasos de asistente, hitos)."""

    def __init__(self, number: int, size: int = 40, fill: str = "velvet", parent: QWidget | None = None):
        super().__init__(parent)
        self._text = ROMAN[number - 1]
        self._fill = fill
        self.setFixedSize(size, size)

    def set_fill(self, fill: str) -> None:
        self._fill = fill
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        f = theme.font("numeral")
        paint_medallion(p, QRectF(self.rect()), fill=self._fill, text=self._text, text_font=f)


class RoadmapStrip(QWidget):
    """Hoja de ruta horizontal: un hito por iteración unido por un riel de bronce."""

    def __init__(self, count: int, current: int, highlight: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.current = current
        self.highlight = highlight
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.badges: list[NumeralBadge] = []
        self.titles: list[QLabel] = []
        self.states: list[QLabel] = []
        for n in range(1, count + 1):
            column = QVBoxLayout()
            column.setSpacing(4)
            fill = "velvet" if n == highlight else ("success" if n == current else "bronze")
            badge = NumeralBadge(n, 38, fill)
            column.addWidget(badge, 0, Qt.AlignmentFlag.AlignHCenter)
            title = QLabel()
            title.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            title.setWordWrap(True)
            title.setFont(theme.font("body_bold", 9.5) if n == highlight else theme.font("small"))
            title.setProperty("role", "value" if n in (highlight, current) else "caption")
            state = QLabel()
            state.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            state.setFont(theme.font("caption", 9))
            state.setProperty("role", "heading" if n == highlight else "caption")
            column.addWidget(title)
            column.addWidget(state)
            column.addStretch(1)
            layout.addLayout(column, 1)
            self.badges.append(badge)
            self.titles.append(title)
            self.states.append(state)

    def paintEvent(self, event) -> None:
        if len(self.badges) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        first, last = self.badges[0], self.badges[-1]
        y = first.geometry().center().y()
        x1, x2 = first.geometry().center().x(), last.geometry().center().x()
        rail = QPainterPath()
        rail.addRoundedRect(QRectF(x1, y - 2.5, x2 - x1, 5), 2.5, 2.5)
        g = QLinearGradient(QPointF(0, y - 2.5), QPointF(0, y + 2.5))
        g.setColorAt(0.0, C("gold_light"))
        g.setColorAt(1.0, C("bronze_dark"))
        p.fillPath(rail, g)
        p.setPen(QPen(C("bronze_dark"), 0.8))
        p.drawPath(rail)
