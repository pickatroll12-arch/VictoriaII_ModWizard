"""Página de módulo planificado: tarjetas de pergamino con las funcionalidades y la hoja de ruta."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPolygonF
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...i18n import N_, tr
from .. import theme
from ..widgets import Medallion, NumeralBadge, ParchmentCard, RibbonBadge, RoadmapStrip, rich
from .base import BasePage

CURRENT_ITERATION = 1
ROADMAP_KEYS = (
    N_("roadmap.it1"), N_("roadmap.it2"), N_("roadmap.it3"), N_("roadmap.it4"), N_("roadmap.it5"),
)


@dataclass(frozen=True)
class FeatureGroup:
    title_key: str
    items: tuple[str, ...]
    icon_name: str = "gear"


class _Bullet(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(12, 18)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(theme.color("bronze_dark"))
        p.setBrush(theme.color("velvet_text"))
        cx, cy, d = 6.0, 10.0, 3.6
        p.drawPolygon(QPolygonF([QPointF(cx, cy - d), QPointF(cx + d, cy), QPointF(cx, cy + d), QPointF(cx - d, cy)]))


class FeatureCard(ParchmentCard):
    def __init__(self, group: FeatureGroup, number: int | None = None, parent: QWidget | None = None):
        super().__init__(padding=18, parent=parent)
        self.group = group
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(10)
        if number is not None:
            head.addWidget(NumeralBadge(number, 36))
        else:
            head.addWidget(Medallion(group.icon_name, 32, "bronze"))
        self.title = QLabel()
        self.title.setProperty("role", "heading")
        self.title.setFont(theme.font("heading", 12.5))
        self.title.setWordWrap(True)
        head.addWidget(self.title, 1)
        layout.addLayout(head)
        self.items: list[QLabel] = []
        for _ in group.items:
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(_Bullet(), 0, Qt.AlignmentFlag.AlignTop)
            label = QLabel()
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            row.addWidget(label, 1)
            layout.addLayout(row)
            self.items.append(label)
        layout.addStretch(1)

    def retranslate(self) -> None:
        self.title.setText(tr(self.group.title_key))
        for label, key in zip(self.items, self.group.items):
            label.setText(rich(tr(key)))


class PlannedModulePage(BasePage):
    """Módulo aún no implementado: explica qué hará y en qué iteración llegará."""

    iteration = CURRENT_ITERATION
    intro_key = ""
    groups: tuple[FeatureGroup, ...] = ()
    numbered = False
    columns = 2

    def build(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setAutoFillBackground(False)
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 6, 0)
        column.setSpacing(14)

        hero = ParchmentCard(padding=20)
        hero_row = QHBoxLayout(hero)
        hero_row.setSpacing(18)
        hero_text = QVBoxLayout()
        hero_text.setSpacing(8)
        self.ribbon = RibbonBadge()
        hero_text.addWidget(self.ribbon, 0, Qt.AlignmentFlag.AlignLeft)
        self.intro = QLabel()
        self.intro.setWordWrap(True)
        self.intro.setTextFormat(Qt.TextFormat.RichText)
        self.intro.setFont(theme.font("body", 11))
        hero_text.addWidget(self.intro)
        self.arrival = QLabel()
        self.arrival.setProperty("role", "caption")
        self.arrival.setFont(theme.font("caption"))
        self.arrival.setWordWrap(True)
        hero_text.addWidget(self.arrival)
        hero_row.addLayout(hero_text, 1)
        hero_row.addWidget(Medallion(self.icon_name, 86), 0, Qt.AlignmentFlag.AlignVCenter)
        column.addWidget(hero)

        self.features_heading = QLabel()
        self.features_heading.setProperty("role", "heading")
        self.features_heading.setFont(theme.font("heading", 13))
        column.addWidget(self.features_heading)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        self.cards: list[FeatureCard] = []
        for index, group in enumerate(self.groups):
            card = FeatureCard(group, index + 1 if self.numbered else None)
            grid.addWidget(card, index // self.columns, index % self.columns)
            self.cards.append(card)
        for c in range(self.columns):
            grid.setColumnStretch(c, 1)
        column.addLayout(grid)

        roadmap_card = ParchmentCard(padding=18, tone="dark")
        roadmap_layout = QVBoxLayout(roadmap_card)
        roadmap_layout.setSpacing(10)
        self.roadmap_heading = QLabel()
        self.roadmap_heading.setProperty("role", "heading")
        self.roadmap_heading.setFont(theme.font("heading", 12.5))
        roadmap_layout.addWidget(self.roadmap_heading)
        self.roadmap = RoadmapStrip(len(ROADMAP_KEYS), CURRENT_ITERATION, self.iteration)
        roadmap_layout.addWidget(self.roadmap)
        column.addWidget(roadmap_card)
        column.addStretch(1)

        scroll.setWidget(content)
        self.body.addWidget(scroll)

    def retranslate(self) -> None:
        super().retranslate()
        self.ribbon.setText(tr("planned.ribbon", n=self.iteration))
        self.ribbon.updateGeometry()
        self.intro.setText(rich(tr(self.intro_key), 10))
        self.arrival.setText(tr("planned.arrives", n=self.iteration))
        self.features_heading.setText(tr("planned.steps" if self.numbered else "planned.features"))
        for card in self.cards:
            card.retranslate()
        self.roadmap_heading.setText(tr("roadmap.title"))
        for n, (title, state) in enumerate(zip(self.roadmap.titles, self.roadmap.states), start=1):
            title.setText(tr(ROADMAP_KEYS[n - 1]))
            if n == self.iteration:
                state.setText(tr("roadmap.state_module", n=n))
            elif n == CURRENT_ITERATION:
                state.setText(tr("roadmap.state_current", n=n))
            else:
                state.setText(tr("roadmap.state", n=n))
