"""Secciones que aún no existen: tarjeta «en desarrollo» con lo que harán y su iteración; y la hoja de ruta.

``PlannedSectionPage`` se construye a partir de una ``SectionSpec`` sin ``factory``
(wizard §13.1): su ``planned_keys`` da la entrada (la primera clave) y las
funcionalidades. La hoja de ruta (``RoadmapCard``, los 10 hitos de wizard §22)
vive en Inicio.
"""

from __future__ import annotations

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
from ..widgets import Medallion, ParchmentCard, RibbonBadge, RoadmapStrip, rich
from .base import BasePage

CURRENT_ITERATION = 8   # la anterior, hecha; esta, en curso (la iteración 7 se cerró el 16-11-2026)
# Plan de docs/diseno/wizard.md §22; el hito 9 reúne las iteraciones 9a y 9b del taller de mapas.
ROADMAP_KEYS = (
    N_("roadmap.it1"), N_("roadmap.it2"), N_("roadmap.it3"), N_("roadmap.it4"), N_("roadmap.it5"),
    N_("roadmap.it6"), N_("roadmap.it7"), N_("roadmap.it8"), N_("roadmap.it9"), N_("roadmap.it10"),
)
# A partir de cuántas funcionalidades la lista va en dos columnas.
TWO_COLUMNS_FROM = 5


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


class PlannedSectionPage(BasePage):
    """Sección planificada: explica qué hará y en qué iteración llegará (wizard §22)."""

    def __init__(self, hall, spec, parent: QWidget | None = None):
        self.hall_spec = hall
        self.spec = spec
        self.key = f"{hall.key}.{spec.key}"
        self.title_key = spec.title_key
        self.subtitle_key = hall.title_key
        self.icon_name = spec.icon
        self.iteration = spec.iteration
        super().__init__(parent)

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
        self.intro.setObjectName("plannedIntro")
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

        features = ParchmentCard(padding=18)
        features_layout = QVBoxLayout(features)
        features_layout.setSpacing(10)
        self.features_heading = QLabel()
        self.features_heading.setProperty("role", "heading")
        self.features_heading.setFont(theme.font("heading", 12.5))
        features_layout.addWidget(self.features_heading)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        items = self.spec.planned_keys[1:]
        columns = 2 if len(items) >= TWO_COLUMNS_FROM else 1
        rows = -(-len(items) // columns)
        self.items: list[QLabel] = []
        for index, _ in enumerate(items):
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(_Bullet(), 0, Qt.AlignmentFlag.AlignTop)
            label = QLabel()
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            row.addWidget(label, 1)
            grid.addLayout(row, index % rows, index // rows)
            self.items.append(label)
        for c in range(columns):
            grid.setColumnStretch(c, 1)
        features_layout.addLayout(grid)
        column.addWidget(features)
        if not items:
            features.hide()
        column.addStretch(1)

        scroll.setWidget(content)
        self.body.addWidget(scroll)

    def retranslate(self) -> None:
        self.header.set_texts(tr(self.title_key), tr("planned.subtitle", hall=tr(self.hall_spec.title_key)))
        self.ribbon.setText(tr("planned.ribbon", n=self.iteration))
        self.ribbon.updateGeometry()
        keys = self.spec.planned_keys
        self.intro.setText(rich(tr(keys[0]), 10) if keys else "")
        self.arrival.setText(tr("planned.arrives", n=self.iteration))
        self.features_heading.setText(tr("planned.features"))
        for label, key in zip(self.items, keys[1:]):
            label.setText(rich(tr(key)))


class RoadmapCard(ParchmentCard):
    """Hoja de ruta de wizard §22: un hito por iteración, con la que está en curso resaltada."""

    def __init__(self, current: int = CURRENT_ITERATION, parent: QWidget | None = None):
        super().__init__(padding=18, tone="dark", parent=parent)
        self.current = current
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.heading = QLabel()
        self.heading.setProperty("role", "heading")
        self.heading.setFont(theme.font("heading", 12.5))
        layout.addWidget(self.heading)
        self.strip = RoadmapStrip(len(ROADMAP_KEYS), current, current)
        layout.addWidget(self.strip)

    def retranslate(self) -> None:
        self.heading.setText(tr("roadmap.title"))
        for n, (title, state) in enumerate(zip(self.strip.titles, self.strip.states), start=1):
            title.setText(tr(ROADMAP_KEYS[n - 1]))
            if n < self.current:
                state.setText(tr("roadmap.state_done", n=n))
            elif n == self.current:
                state.setText(tr("roadmap.state_current", n=n))
            else:
                state.setText(tr("roadmap.state", n=n))
