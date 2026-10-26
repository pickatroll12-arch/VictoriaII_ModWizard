"""Barra de navegación entre módulos: placas de bronce con icono, nombre y número de atajo."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QHBoxLayout, QSizePolicy, QWidget

from .. import theme
from .icons import draw_icon

C = theme.color

_KEYBOARD_REASONS = {
    Qt.FocusReason.TabFocusReason,
    Qt.FocusReason.BacktabFocusReason,
    Qt.FocusReason.ShortcutFocusReason,
    Qt.FocusReason.OtherFocusReason,
}


class NavButton(QAbstractButton):
    POINTER = 7.0

    def __init__(self, icon_name: str, number: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.number = number
        self._keyboard_focus = False
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFont(theme.font("nav"))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        fm = QFontMetricsF(self.font())
        return QSize(int(fm.horizontalAdvance(self.text()) + 92), 54)

    def minimumSizeHint(self) -> QSize:
        return QSize(112, 54)

    def focusInEvent(self, event) -> None:
        self._keyboard_focus = event.reason() in _KEYBOARD_REASONS
        super().focusInEvent(event)

    def mousePressEvent(self, event) -> None:
        self._keyboard_focus = False
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        checked, hovered, pressed = self.isChecked(), self.underMouse(), self.isDown()
        plate = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5 - self.POINTER)
        g = QLinearGradient(plate.topLeft(), plate.bottomLeft())
        if checked:
            g.setColorAt(0.0, C("velvet_light"))
            g.setColorAt(0.5, C("velvet"))
            g.setColorAt(1.0, C("velvet_dark"))
        elif pressed:
            g.setColorAt(0.0, C("wood_dark"))
            g.setColorAt(1.0, C("wood"))
        elif hovered:
            g.setColorAt(0.0, theme.color("wood_light").lighter(125))
            g.setColorAt(1.0, C("wood"))
        else:
            g.setColorAt(0.0, C("wood_light", 230))
            g.setColorAt(1.0, C("wood_dark", 230))
        path = QPainterPath()
        path.addRoundedRect(plate, 4, 4)
        p.fillPath(path, g)

        border = C("gold_light") if checked or hovered else C("bronze")
        p.setPen(QPen(C("wood_dark"), 1.0))
        p.drawRoundedRect(plate.adjusted(-0.5, -0.5, 0.5, 0.5), 4.5, 4.5)
        p.setPen(QPen(border, 1.3))
        p.drawRoundedRect(plate, 4, 4)
        p.setPen(QPen(C("gold_pale", 70 if checked else 40), 1.0))
        p.drawLine(QPointF(plate.left() + 5, plate.top() + 2), QPointF(plate.right() - 5, plate.top() + 2))

        if checked:
            cx, bottom = plate.center().x(), plate.bottom()
            p.setPen(QPen(C("wood_dark"), 1.0))
            p.setBrush(C("gold"))
            p.drawPolygon(QPolygonF([QPointF(cx - 8, bottom + 0.5), QPointF(cx + 8, bottom + 0.5),
                                     QPointF(cx, bottom + self.POINTER)]))

        icon_rect = QRectF(plate.left() + 12, plate.center().y() - 12, 24, 24)
        icon_color = C("gold_pale") if checked else (C("gold_light") if hovered else C("gold"))
        draw_icon(p, self.icon_name, icon_rect, icon_color)

        number_rect = QRectF(plate.right() - 26, plate.center().y() - 9, 18, 18)
        p.setPen(QPen(C("gold", 170) if checked else C("bronze"), 1.0))
        p.setBrush(C("wood_dark", 120))
        p.drawEllipse(number_rect)
        p.setFont(theme.font("badge"))
        p.setPen(C("gold_light") if checked else C("cream_muted"))
        p.drawText(number_rect, Qt.AlignmentFlag.AlignCenter, str(self.number))

        text_rect = QRectF(icon_rect.right() + 10, plate.top(), number_rect.left() - icon_rect.right() - 16, plate.height())
        p.setFont(self.font())
        p.setPen(C("gold_pale") if checked else C("cream"))
        text = QFontMetricsF(self.font()).elidedText(self.text(), Qt.TextElideMode.ElideRight, text_rect.width())
        p.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)

        if self.hasFocus() and self._keyboard_focus:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(C("gold_pale"), 1.4, Qt.PenStyle.DashLine))
            p.drawRoundedRect(plate.adjusted(3, 3, -3, -3), 3, 3)


class NavBar(QWidget):
    """Fila de ``NavButton`` exclusivos; ← y → cambian de módulo con el teclado."""

    currentChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("surface", "wood")
        self.buttons: list[NavButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idToggled.connect(self._on_toggled)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

    def add_button(self, icon_name: str) -> NavButton:
        button = NavButton(icon_name, len(self.buttons) + 1, self)
        self._group.addButton(button, len(self.buttons))
        self.buttons.append(button)
        self._layout.addWidget(button)
        return button

    def current_index(self) -> int:
        return self._group.checkedId()

    def set_current_index(self, index: int) -> None:
        if 0 <= index < len(self.buttons) and not self.buttons[index].isChecked():
            self.buttons[index].setChecked(True)

    def _on_toggled(self, index: int, checked: bool) -> None:
        if checked:
            self.currentChanged.emit(index)

    def keyPressEvent(self, event) -> None:
        step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}.get(Qt.Key(event.key()))
        focused = next((i for i, b in enumerate(self.buttons) if b.hasFocus()), None)
        if step is None or focused is None:
            super().keyPressEvent(event)
            return
        target = (focused + step) % len(self.buttons)
        self.buttons[target].setFocus(Qt.FocusReason.TabFocusReason)
        self.set_current_index(target)
