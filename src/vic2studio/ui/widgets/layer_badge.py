"""Insignias de capa del explorador: J (solo en el juego base), M (solo en el mod) y M⊃J (el mod sustituye al
archivo del juego base) (wizard §13.5, §21).

``LayerResolver`` decide la capa de un archivo mirando si existe la misma ruta
relativa en la otra carpeta, sin distinguir mayúsculas (el juego corre en
Windows); guarda lo que ya miró hasta ``invalidate``. ``LayerBadgeDelegate`` pinta
la insignia a la derecha del nombre en la primera columna del explorador y da su
explicación en la ayuda emergente. Las carpetas no llevan insignia.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QIcon, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QToolTip

from ...i18n import N_, tr
from .. import theme

LAYER_GAME = "game"
LAYER_MOD = "mod"
LAYER_OVERRIDE = "override"
LAYERS = (LAYER_GAME, LAYER_MOD, LAYER_OVERRIDE)
SHORT_KEYS = {LAYER_GAME: N_("layer.game_short"), LAYER_MOD: N_("layer.mod_short"),
              LAYER_OVERRIDE: N_("layer.override_short")}
TOOLTIP_KEYS = {LAYER_GAME: N_("layer.game_tooltip"), LAYER_MOD: N_("layer.mod_tooltip"),
                LAYER_OVERRIDE: N_("layer.override_tooltip")}
# Colores de las cintas de origen (§13.5): juego base en pizarra, mod en verde, sustituye en ámbar.
COLORS = {LAYER_GAME: "#4d5a63", LAYER_MOD: theme.PALETTE["success"], LAYER_OVERRIDE: "#9a6408"}
BADGE_FONT_SIZE = 8.0
BADGE_MARGIN = 6


def layer_text(layer: str) -> str:
    return tr(SHORT_KEYS[layer])


def layer_tooltip(layer: str) -> str:
    return tr(TOOLTIP_KEYS[layer])


def badge_width(layer: str) -> float:
    metrics = QFontMetricsF(theme.font("badge", BADGE_FONT_SIZE))
    return metrics.horizontalAdvance(layer_text(layer)) + 12


def paint_layer_badge(painter: QPainter, rect: QRectF, layer: str) -> None:
    """Píldora con la letra de la capa, centrada verticalmente en ``rect``."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(COLORS[layer])
    painter.setPen(QPen(color.darker(140), 1.0))
    painter.setBrush(color)
    painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    painter.setFont(theme.font("badge", BADGE_FONT_SIZE))
    painter.setPen(theme.color("cream"))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, layer_text(layer))
    painter.restore()


class LayerResolver:
    """Capa de un archivo del juego o del mod comparando con la otra carpeta (sin mayúsculas)."""

    def __init__(self, game_root: Path | None = None, mod_root: Path | None = None):
        self.game_root = game_root
        self.mod_root = mod_root
        self._layers: dict[str, str | None] = {}
        self._listings: dict[str, dict[str, str]] = {}

    def set_roots(self, game_root: Path | None, mod_root: Path | None) -> None:
        self.game_root, self.mod_root = game_root, mod_root
        self.invalidate()

    def invalidate(self) -> None:
        self._layers.clear()
        self._listings.clear()

    def _listing(self, folder: Path) -> dict[str, str]:
        key = os.fspath(folder)
        listing = self._listings.get(key)
        if listing is None:
            try:
                listing = {entry.name.casefold(): entry.name for entry in os.scandir(folder)}
            except OSError:
                listing = {}
            self._listings[key] = listing
        return listing

    def _exists(self, root: Path, relative: Path) -> bool:
        if (root / relative).is_file():
            return True
        current = root
        for part in relative.parts:
            name = self._listing(current).get(part.casefold())
            if name is None:
                return False
            current = current / name
        return current.is_file()

    @staticmethod
    def _relative(path: Path, root: Path | None) -> Path | None:
        if root is None:
            return None
        try:
            return path.relative_to(root)
        except ValueError:
            return None

    def layer_of(self, path: Path) -> str | None:
        key = os.fspath(path)
        if key in self._layers:
            return self._layers[key]
        layer = None
        if path.is_file():
            in_mod = self._relative(path, self.mod_root)
            in_game = None if in_mod is not None else self._relative(path, self.game_root)
            if in_mod is not None:
                shadowed = self.game_root is not None and self._exists(self.game_root, in_mod)
                layer = LAYER_OVERRIDE if shadowed else LAYER_MOD
            elif in_game is not None and in_game.parts and in_game.parts[0].casefold() != "mod":
                shadowed = self.mod_root is not None and self._exists(self.mod_root, in_game)
                layer = LAYER_OVERRIDE if shadowed else LAYER_GAME
        self._layers[key] = layer
        return layer


class LayerBadgeDelegate(QStyledItemDelegate):
    """Pinta la insignia de capa a la derecha de la primera columna; ``layer_for(index)`` la da (o None)."""

    def __init__(self, layer_for: Callable[[QModelIndex], str | None], parent=None):
        super().__init__(parent)
        self.layer_for = layer_for

    def _badge_rect(self, option: QStyleOptionViewItem, layer: str) -> QRectF:
        width = badge_width(layer)
        rect = QRectF(option.rect)
        height = min(16.0, rect.height() - 4)
        return QRectF(rect.right() - BADGE_MARGIN - width, rect.center().y() - height / 2, width, height)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        layer = self.layer_for(index) if index.column() == 0 else None
        if layer is None:
            super().paint(painter, option, index)
            return
        badge = self._badge_rect(option, layer)
        narrowed = QStyleOptionViewItem(option)
        narrowed.rect = option.rect.adjusted(0, 0, -int(badge.width() + 2 * BADGE_MARGIN), 0)
        # El fondo de selección y de fila alterna ocupa la fila entera; el texto, solo lo que queda.
        style = option.widget.style() if option.widget is not None else None
        if style is not None:
            background = QStyleOptionViewItem(option)
            self.initStyleOption(background, index)
            background.text = ""
            background.icon = QIcon()
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, background, painter, option.widget)
        super().paint(painter, narrowed, index)
        paint_layer_badge(painter, badge, layer)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        layer = self.layer_for(index) if index.column() == 0 else None
        if layer is not None:
            size.setWidth(size.width() + int(badge_width(layer)) + 2 * BADGE_MARGIN)
        return size

    def helpEvent(self, event, view, option, index) -> bool:
        if event is not None and event.type() == QEvent.Type.ToolTip and index.isValid() and index.column() == 0:
            layer = self.layer_for(index)
            if layer is not None and self._badge_rect(option, layer).contains(event.pos()):
                QToolTip.showText(event.globalPos(), layer_tooltip(layer), view)
                return True
        return super().helpEvent(event, view, option, index)
