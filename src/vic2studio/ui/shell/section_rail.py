"""Índice de una sala: panel de madera con remaches y una placa por sección (wizard §13.2).

Cada ``RailButton`` lleva el icono y el nombre de la sección (partido en dos
líneas si no cabe) y, a la derecha, un contador (``set_badge``) o la iteración en
que llega si aún no existe (``set_tag``). Con sitio, el índice es una columna a la
izquierda de la sección con el título largo de la sala; en ventanas estrechas
(``set_compact``) pasa a ser una franja horizontal encima de ella, para que la
sección conserve todo el ancho que tenía la página de la iteración 1: con placas
bajas si todos los nombres caben en una línea (así apenas le quita alto) y altas,
con los nombres en dos líneas, si no. Las flechas cambian de sección con el teclado.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QAbstractButton, QBoxLayout, QButtonGroup, QLabel, QSizePolicy, QWidget

from .. import theme
from ..widgets.icons import draw_icon
from ..widgets.ornaments import paint_rivet

C = theme.color

_KEYBOARD_REASONS = {
    Qt.FocusReason.TabFocusReason,
    Qt.FocusReason.BacktabFocusReason,
    Qt.FocusReason.ShortcutFocusReason,
    Qt.FocusReason.OtherFocusReason,
}
_STEPS = {Qt.Key.Key_Up: -1, Qt.Key.Key_Left: -1, Qt.Key.Key_Down: 1, Qt.Key.Key_Right: 1}


class RailButton(QAbstractButton):
    HEIGHT = 46
    POINTER = 7.0
    ICON = 22
    # En la franja (ventanas estrechas) las placas son bajas si todos los nombres caben en una línea, para que
    # la sección conserve casi todo su alto; si no, altas, con los nombres en dos líneas.
    STRIP_HEIGHT = 32
    TALL_STRIP_HEIGHT = 46
    STRIP_POINTER = 5.0
    STRIP_ICON = 17
    TRAILING_GAP = 8

    def __init__(self, icon_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.badge: int | None = None
        self.tag = ""
        self.horizontal = False
        self.tall = False                  # solo en la franja: placa alta, con sitio para dos líneas
        self._keyboard_focus = False
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFont(theme.font("nav", 10.0))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_badge(self, count: int | None) -> None:
        if count != self.badge:
            self.badge = count
            self.updateGeometry()
            self.update()

    def set_tag(self, text: str) -> None:
        if text != self.tag:
            self.tag = text
            self.updateGeometry()
            self.update()

    def set_horizontal(self, horizontal: bool) -> None:
        if horizontal != self.horizontal:
            self.horizontal = horizontal
            self.setSizePolicy(QSizePolicy.Policy.Preferred if horizontal else QSizePolicy.Policy.Expanding,
                               QSizePolicy.Policy.Fixed)
            self.updateGeometry()
            self.update()

    def set_tall(self, tall: bool) -> None:
        if tall != self.tall:
            self.tall = tall
            self.updateGeometry()
            self.update()

    @property
    def slim(self) -> bool:
        return self.horizontal and not self.tall

    @property
    def pointer(self) -> float:
        return self.STRIP_POINTER if self.horizontal else self.POINTER

    @property
    def icon_size(self) -> int:
        return self.STRIP_ICON if self.slim else self.ICON

    def height_hint(self) -> int:
        if not self.horizontal:
            return self.HEIGHT
        return self.TALL_STRIP_HEIGHT if self.tall else self.STRIP_HEIGHT

    def one_line_width(self) -> int:
        """Ancho de la placa baja de la franja con el nombre entero en una línea."""
        width = QFontMetricsF(self.font()).horizontalAdvance(self.text())
        return int(width + 26 + self.STRIP_ICON + self.TRAILING_GAP + self._trailing_width() + 2)

    def sizeHint(self) -> QSize:
        if not self.horizontal:
            return QSize(180, self.HEIGHT)
        return QSize(self.one_line_width() + (self.ICON - self.STRIP_ICON if self.tall else 0), self.height_hint())

    def minimumSizeHint(self) -> QSize:
        return QSize(96 if self.horizontal else 120, self.height_hint())

    def focusInEvent(self, event) -> None:
        self._keyboard_focus = event.reason() in _KEYBOARD_REASONS
        super().focusInEvent(event)

    def mousePressEvent(self, event) -> None:
        self._keyboard_focus = False
        super().mousePressEvent(event)

    def plate(self) -> QRectF:
        if self.horizontal:
            return QRectF(self.rect()).adjusted(1.5, 1.0, -1.5, -1.0 - self.pointer)
        return QRectF(self.rect()).adjusted(1.5, 2.0, -1.5 - self.pointer, -2.0)

    def _trailing_width(self) -> float:
        if self.badge:
            return 24.0 if self.horizontal else 26.0
        if self.tag:
            return QFontMetricsF(theme.font("badge", 8.0)).horizontalAdvance(self.tag) + 12
        return 0.0

    def text_rect(self) -> QRectF:
        plate = self.plate()
        left = plate.left() + 16 + self.icon_size
        right = plate.right() - self.TRAILING_GAP - self._trailing_width()
        return QRectF(left, plate.top(), max(right - left, 1.0), plate.height())

    def label_text(self) -> str:
        """El nombre tal como se pinta: en una línea, en dos partido entre palabras o, si no, recortado."""
        width = self.text_rect().width()
        metrics = QFontMetricsF(self.font())
        text = self.text()
        if metrics.horizontalAdvance(text) <= width:
            return text
        words = text.split()
        best = None
        for cut in range(1, len(words)):
            lines = " ".join(words[:cut]), " ".join(words[cut:])
            widest = max(metrics.horizontalAdvance(line) for line in lines)
            rank = len(words[cut - 1]) <= 2, widest
            if widest <= width and (best is None or rank < best[0]):
                best = rank, "\n".join(lines)
        if best is not None and 2 * metrics.lineSpacing() <= self.plate().height():
            return best[1]
        return metrics.elidedText(text, Qt.TextElideMode.ElideRight, width)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        checked, hovered = self.isChecked(), self.underMouse()
        plate = self.plate()
        if checked or hovered or self.isDown():
            g = QLinearGradient(plate.topLeft(), plate.bottomLeft())
            if checked:
                g.setColorAt(0.0, C("velvet_light"))
                g.setColorAt(0.5, C("velvet"))
                g.setColorAt(1.0, C("velvet_dark"))
            else:
                g.setColorAt(0.0, C("wood_light").lighter(120))
                g.setColorAt(1.0, C("wood"))
            path = QPainterPath()
            path.addRoundedRect(plate, 4, 4)
            p.fillPath(path, g)
            p.setPen(QPen(C("gold_light") if checked else C("bronze"), 1.2))
            p.drawRoundedRect(plate, 4, 4)
        if checked:
            p.setPen(QPen(C("wood_dark"), 1.0))
            p.setBrush(C("gold"))
            if self.horizontal:
                cx, bottom = plate.center().x(), plate.bottom()
                pointer = [QPointF(cx - 6, bottom + 0.5), QPointF(cx + 6, bottom + 0.5),
                           QPointF(cx, bottom + self.pointer)]
            else:
                cy, right = plate.center().y(), plate.right()
                pointer = [QPointF(right + 0.5, cy - 7), QPointF(right + 0.5, cy + 7),
                           QPointF(right + self.pointer, cy)]
            p.drawPolygon(QPolygonF(pointer))
        planned = bool(self.tag) and not checked
        color = C("gold_pale") if checked else (C("cream_muted") if planned else C("gold"))
        icon = self.icon_size
        draw_icon(p, self.icon_name, QRectF(plate.left() + 10, plate.center().y() - icon / 2, icon, icon), color)
        p.setFont(self.font())
        p.setPen(C("gold_pale") if checked else (C("cream_muted") if planned else C("cream")))
        p.drawText(self.text_rect(), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                   self.label_text())
        self._paint_trailing(p, plate, checked)
        if self.hasFocus() and self._keyboard_focus:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(C("gold_pale"), 1.3, Qt.PenStyle.DashLine))
            p.drawRoundedRect(plate.adjusted(3, 3, -3, -3), 3, 3)

    def _paint_trailing(self, p: QPainter, plate: QRectF, checked: bool) -> None:
        if self.badge:
            size = 18.0 if self.horizontal else 20.0
            rect = QRectF(plate.right() - 8 - size, plate.center().y() - size / 2, size, size)
            p.setPen(QPen(C("wood_dark"), 1.0))
            p.setBrush(C("gold") if not checked else C("gold_pale"))
            p.drawEllipse(rect)
            p.setFont(theme.font("badge", 8.5))
            p.setPen(C("wood_dark"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(self.badge) if self.badge < 100 else "99+")
        elif self.tag:
            font = theme.font("badge", 8.0)
            width = QFontMetricsF(font).horizontalAdvance(self.tag) + 10
            rect = QRectF(plate.right() - 6 - width, plate.center().y() - 9, width, 18)
            p.setPen(QPen(C("bronze"), 1.0))
            p.setBrush(C("wood_dark", 170))
            p.drawRoundedRect(rect, 9, 9)
            p.setFont(font)
            p.setPen(C("gold_light") if checked else C("cream_muted"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.tag)


class SectionRail(QWidget):
    """Índice de madera de una sala: el título largo y una placa exclusiva por sección."""

    currentChanged = Signal(int)
    WIDTH = 206
    STRIP_MARGINS = (10, 3, 10, 3)
    STRIP_HEIGHT = RailButton.STRIP_HEIGHT + STRIP_MARGINS[1] + STRIP_MARGINS[3]
    TALL_STRIP_HEIGHT = RailButton.TALL_STRIP_HEIGHT + STRIP_MARGINS[1] + STRIP_MARGINS[3]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("sectionRail")
        self.setProperty("surface", "wood")
        self.compact = False
        self.buttons: list[RailButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idToggled.connect(self._on_toggled)
        self._layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        self._layout.setSpacing(3)
        self.heading = QLabel()
        self.heading.setObjectName("railHeading")
        self.heading.setFont(theme.font("heading", 11.0))
        self.heading.setWordWrap(True)
        self.heading.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.heading.setStyleSheet(f"color: {theme.PALETTE['gold_light']};")
        self._layout.addWidget(self.heading)
        self._spacer = self._layout.count()
        self._layout.addSpacing(6)
        self._layout.addStretch(1)
        self._apply_orientation()

    def add_button(self, icon_name: str) -> RailButton:
        button = RailButton(icon_name, self)
        button.set_horizontal(self.compact)
        self._group.addButton(button, len(self.buttons))
        self.buttons.append(button)
        self._layout.insertWidget(self._layout.count() - 1, button)
        return button

    def current_index(self) -> int:
        return self._group.checkedId()

    def set_current_index(self, index: int) -> None:
        if 0 <= index < len(self.buttons) and not self.buttons[index].isChecked():
            self.buttons[index].setChecked(True)

    def set_heading(self, text: str) -> None:
        self.heading.setText(text)

    def set_compact(self, compact: bool) -> None:
        """Franja horizontal (True) o columna con el título (False)."""
        if compact != self.compact:
            self.compact = compact
            self._apply_orientation()

    def _apply_orientation(self) -> None:
        compact = self.compact
        self._layout.setDirection(QBoxLayout.Direction.LeftToRight if compact else QBoxLayout.Direction.TopToBottom)
        if compact:
            self._layout.setContentsMargins(*self.STRIP_MARGINS)
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self._layout.setContentsMargins(8, 12, 4, 12)
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.setFixedWidth(self.WIDTH)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.heading.setVisible(not compact)
        spacing = self._layout.itemAt(self._spacer)
        if spacing is not None and spacing.spacerItem() is not None:
            spacing.spacerItem().changeSize(0 if compact else 1, 0 if compact else 6)
        for button in self.buttons:
            button.set_horizontal(compact)
        self.update_strip()
        self._layout.invalidate()
        self.update()

    def strip_fits_one_line(self, width: int | None = None) -> bool:
        """Si en la franja de ``width`` px (la actual por defecto) caben todos los nombres en placas bajas."""
        width = self.width() if width is None else width
        left, _, right, _ = self.STRIP_MARGINS
        room = width - left - right - self._layout.spacing() * max(len(self.buttons) - 1, 0)
        return sum(button.one_line_width() for button in self.buttons) <= room

    def update_strip(self) -> None:
        """En la franja, placas bajas si caben los nombres en una línea y altas (dos líneas) si no."""
        if not self.compact:
            for button in self.buttons:
                button.set_tall(False)
            return
        tall = not self.strip_fits_one_line()
        for button in self.buttons:
            button.set_tall(tall)
        self.setFixedHeight(self.TALL_STRIP_HEIGHT if tall else self.STRIP_HEIGHT)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.compact and event.size().width() != event.oldSize().width():
            self.update_strip()

    def _on_toggled(self, index: int, checked: bool) -> None:
        if checked:
            self.currentChanged.emit(index)

    def keyPressEvent(self, event) -> None:
        step = _STEPS.get(Qt.Key(event.key()))
        focused = next((i for i, b in enumerate(self.buttons) if b.hasFocus()), None)
        if step is None or focused is None:
            super().keyPressEvent(event)
            return
        target = (focused + step) % len(self.buttons)
        self.buttons[target].setFocus(Qt.FocusReason.TabFocusReason)
        self.set_current_index(target)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = (RailButton.STRIP_POINTER if self.compact else RailButton.POINTER) - 3
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rect = rect.adjusted(0, 0, 0, -inset) if self.compact else rect.adjusted(0, 0, -inset, 0)
        path = QPainterPath()
        path.addRoundedRect(rect, 5, 5)
        p.save()
        p.setClipPath(path)
        theme.paint_surface(p, rect, "wood", 0.55)
        shade = QLinearGradient(rect.topLeft(), rect.bottomLeft() if self.compact else rect.topRight())
        shade.setColorAt(0.0, C("wood_dark", 90))
        shade.setColorAt(1.0, C("wood_dark", 20))
        p.fillRect(rect, shade)
        p.restore()
        p.setPen(QPen(C("wood_dark"), 1.0))
        p.drawRoundedRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5), 5.5, 5.5)
        p.setPen(QPen(C("bronze"), 1.4))
        p.drawRoundedRect(rect, 5, 5)
        for x, y in ((rect.left() + 5, rect.top() + 5), (rect.right() - 5, rect.top() + 5),
                     (rect.left() + 5, rect.bottom() - 5), (rect.right() - 5, rect.bottom() - 5)):
            paint_rivet(p, QPointF(x, y), 2.2)
