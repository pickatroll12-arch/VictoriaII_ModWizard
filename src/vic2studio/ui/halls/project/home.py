"""Inicio (wizard §13.3): la carpeta del juego, los mods de ``<juego>/mod`` y «¿Qué quieres hacer?».

1. **Juego base**: la carpeta del juego, validada con ``evaluate_game``.
2. **Tu mod**: una tarjeta por cada ``<juego>/mod/*.mod`` (``read_descriptor``: nombre,
   carpeta y ``user_dir``), la del mod abierto resaltada, más «Crear mod nuevo» y
   «Abrir otra carpeta…»; debajo, el estado del proyecto (abriéndose, abierto, en solo
   lectura, cambios sin guardar o el motivo por el que no se abrió).
3. **¿Qué quieres hacer?**: tarjetas que llevan a cada flujo; las de capacidades que
   aún no existen dicen en qué iteración llegan.
4. **Hoja de ruta** (los 10 hitos de wizard §22).

La página no guarda rutas: emite ``game_path_selected``, ``mod_selected`` y
``new_mod_requested``, y la ventana se las pasa a «Archivos» (que las conserva en
las preferencias) y a ``Session``. ``set_game_path`` y ``set_mod_path`` le dicen lo
que hay elegido.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QDir, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ....core.modfile import ModDescriptor, descriptor_files, read_descriptor
from ....core.vfs.guard import evaluate_game, inspect_folder, same_folder
from ....i18n import N_, tr
from ... import theme
from ...pages.base import BasePage
from ...pages.planned import RoadmapCard
from ...viewers.common import ElidedLabel
from ...widgets import IconWidget, ParchmentCard, StatusBadge, make_icon, mark_data
from ...widgets.ornaments import paint_thin_border

C = theme.color

# (clave del título, icono, iteración en que llega o None si ya existe, destino «sala:sección»).
FLOWS = (
    (N_("home.flow.descriptor"), "file_mod", None, "project:descriptor"),
    (N_("home.flow.files"), "folder_open", None, "project:files"),
    (N_("home.flow.translate"), "localisation", None, "localisation:pending"),
    (N_("home.flow.unit"), "helmet", 4, "war:land"),
    (N_("home.flow.government"), "crown", 4, "nations:governments"),
    (N_("home.flow.culture"), "culture", 4, "nations:cultures"),
    (N_("home.flow.provinces"), "map", 5, "map:world"),
    (N_("home.flow.country"), "countries", 6, "nations:countries"),
    (N_("home.flow.war"), "swords", 6, "war:wars"),
    (N_("home.flow.event"), "events", 7, "events:events"),
    (N_("home.flow.decision"), "quill", 7, "events:decisions"),
    (N_("home.flow.window"), "window", 8, "interface:windows"),
    (N_("home.flow.map"), "anvil", 9, "map:forge"),
)


def mod_folder_of(descriptor: ModDescriptor, game_root: Path) -> Path:
    """Carpeta del mod que nombra un descriptor de ``<juego>/mod`` (por ``path``; si no tiene, por su nombre)."""
    if descriptor.path:
        return game_root / descriptor.path.replace("\\", "/")
    return descriptor.file.with_suffix("")


class Tile(QAbstractButton):
    """Tarjeta de pergamino que se pulsa (con el ratón, Intro o Espacio); ``checked`` la resalta en terciopelo."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.inner = QVBoxLayout(self)
        self.inner.setContentsMargins(14, 10, 14, 10)
        self.inner.setSpacing(2)

    def nextCheckState(self) -> None:
        """Pulsarla no la marca: lo hace quien la usa (el mod abierto)."""

    def sizeHint(self) -> QSize:
        return self.inner.sizeHint()

    def minimumSizeHint(self) -> QSize:
        return QSize(150, self.inner.minimumSize().height())

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self.inner.totalHeightForWidth(width)

    def add_label(self, role: str, font: str, *, data: bool = False, wrap: bool = True) -> QLabel:
        label = QLabel()
        label.setProperty("role", role)
        label.setFont(theme.font(font))
        label.setWordWrap(wrap)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if data:
            mark_data(label)
        self.inner.addWidget(label)
        return label

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        theme.paint_surface(p, rect, "parchment")
        wash = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        wash.setColorAt(0.0, C("parchment_pale", 150 if self.underMouse() else 110))
        wash.setColorAt(1.0, C("parchment_light", 40))
        p.fillRect(rect, wash)
        paint_thin_border(p, rect)
        if self.isChecked() or self.underMouse():
            p.setPen(QPen(C("velvet") if self.isChecked() else C("gold"), 2.2 if self.isChecked() else 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 3, 3)
        if self.hasFocus():
            p.setPen(QPen(C("velvet_light"), 1.2, Qt.PenStyle.DashLine))
            p.drawRoundedRect(rect.adjusted(4, 4, -4, -4), 2, 2)


class ModTile(Tile):
    """Un mod de ``<juego>/mod``: nombre, carpeta y ``user_dir``; «Abierto» si es el del proyecto."""

    def __init__(self, descriptor: ModDescriptor, folder: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.descriptor = descriptor
        self.folder = folder
        self.setObjectName("modTile")
        head = QHBoxLayout()
        head.setSpacing(8)
        icon = IconWidget("file_mod", 22, "velvet_text")
        icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        head.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        self.name = QLabel()
        self.name.setFont(theme.font("body_bold", 11.5))
        self.name.setWordWrap(True)
        self.name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        mark_data(self.name)
        head.addWidget(self.name, 1)
        self.inner.addLayout(head)
        self.path = self.add_label("caption", "caption", data=True)
        self.user_dir = self.add_label("caption", "caption")
        self.state = self.add_label("heading", "badge")
        self.state.setVisible(False)

    def retranslate(self) -> None:
        d = self.descriptor
        missing = tr("check.descriptor_missing_value")
        self.name.setText(d.name or d.file.stem)
        self.path.setText(f"{d.file.name} · {d.path or missing}")
        self.user_dir.setText(tr("home.mod_user_dir", user_dir=d.user_dir or missing))
        self.state.setText(tr("home.mod_open"))
        self.setToolTip(tr("home.mod_tooltip", folder=os.fspath(self.folder)))
        self.setAccessibleName(self.name.text())

    def set_current(self, current: bool) -> None:
        self.setChecked(current)
        self.state.setVisible(current)


class ActionTile(Tile):
    """«Crear mod nuevo» y «Abrir otra carpeta…»."""

    def __init__(self, icon_name: str, title_key: str, text_key: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.title_key = title_key
        self.text_key = text_key
        head = QHBoxLayout()
        head.setSpacing(8)
        icon = IconWidget(icon_name, 22, "velvet_text")
        icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        head.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        self.title = QLabel()
        self.title.setProperty("role", "heading")
        self.title.setFont(theme.font("heading", 11.5))
        self.title.setWordWrap(True)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        head.addWidget(self.title, 1)
        self.inner.addLayout(head)
        self.caption = self.add_label("caption", "caption")

    def retranslate(self) -> None:
        self.title.setText(tr(self.title_key))
        self.caption.setText(tr(self.text_key))
        self.setAccessibleName(self.title.text())


class FlowTile(Tile):
    """Una tarjeta de «¿Qué quieres hacer?»: icono, título y si ya está disponible o en qué iteración llega."""

    def __init__(self, title_key: str, icon_name: str, iteration: int | None, target: str,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.title_key = title_key
        self.iteration = iteration
        self.target = target
        self.setObjectName("flowTile")
        head = QHBoxLayout()
        head.setSpacing(10)
        icon = IconWidget(icon_name, 26, "velvet_text" if iteration is None else "ink_muted")
        icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        head.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        column = QVBoxLayout()
        column.setSpacing(2)
        self.title = QLabel()
        self.title.setFont(theme.font("body_bold", 10.5))
        self.title.setWordWrap(True)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        column.addWidget(self.title)
        self.state = QLabel()
        self.state.setProperty("role", "heading" if iteration is None else "caption")
        self.state.setFont(theme.font("caption", 9))
        self.state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        column.addWidget(self.state)
        head.addLayout(column, 1)
        self.inner.addLayout(head)

    def retranslate(self) -> None:
        self.title.setText(tr(self.title_key))
        self.state.setText(tr("home.flow_ready") if self.iteration is None
                           else tr("home.flow_planned", n=self.iteration))
        self.setToolTip(tr("home.flow_tooltip_ready") if self.iteration is None
                        else tr("home.flow_tooltip_planned", n=self.iteration))
        self.setAccessibleName(self.title.text())


class TileGrid(QWidget):
    """Rejilla de tarjetas de igual ancho: tantas columnas como quepan con ``min_width`` px cada una."""

    def __init__(self, min_width: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.min_width = min_width
        self.tiles: list[QWidget] = []
        self.columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(10)

    def set_tiles(self, tiles: list[QWidget]) -> None:
        for tile in self.tiles:
            self.grid.removeWidget(tile)
            if tile not in tiles:
                tile.deleteLater()
        self.tiles = list(tiles)
        self.columns = 0
        self._place(self.width() or self.min_width * 3)

    def _place(self, width: int) -> None:
        spacing = self.grid.horizontalSpacing()
        columns = max(1, min(len(self.tiles) or 1, (width + spacing) // (self.min_width + spacing)))
        if columns == self.columns:
            return
        for tile in self.tiles:
            self.grid.removeWidget(tile)
        for column in range(max(self.columns, columns)):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        for index, tile in enumerate(self.tiles):
            self.grid.addWidget(tile, index // columns, index % columns)
        self.columns = columns

    def resizeEvent(self, event) -> None:
        self._place(event.size().width())
        super().resizeEvent(event)


def _card(heading_key_holder: list, parent_layout: QVBoxLayout | QHBoxLayout, stretch: int = 0):
    card = ParchmentCard(padding=16)
    layout = QVBoxLayout(card)
    layout.setSpacing(8)
    heading = QLabel()
    heading.setProperty("role", "heading")
    heading.setFont(theme.font("heading", 12.5))
    layout.addWidget(heading)
    heading_key_holder.append(heading)
    parent_layout.addWidget(card, stretch)
    return card, layout, heading


class HomePage(BasePage):
    key = "home"
    title_key = N_("section.project.home")
    subtitle_key = N_("home.subtitle")
    icon_name = "home"

    game_path_selected = Signal(object)   # Path | None
    mod_selected = Signal(object)         # Path de la carpeta del mod
    new_mod_requested = Signal()
    navigate_requested = Signal(str)

    MOD_TILE_WIDTH = 230
    FLOW_TILE_WIDTH = 210

    def __init__(self, session, parent: QWidget | None = None):
        self.session = session
        self._game: Path | None = None
        self._mod: Path | None = None
        self._project_state: tuple[str, str, dict] = ("neutral", N_("home.project_none"), {})
        super().__init__(parent)
        session.projectOpening.connect(self._on_opening)
        session.projectOpened.connect(self._on_opened)
        session.projectOpenFailed.connect(self._on_open_failed)
        session.projectClosed.connect(self._on_closed)
        session.dirtyChanged.connect(self._on_dirty)  # métodos: Qt corta la conexión al destruir la página

    def build(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setAutoFillBackground(False)
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 8, 4)
        column.setSpacing(14)
        self._headings: list[QLabel] = []

        top = QHBoxLayout()
        top.setSpacing(14)
        game_card, game_layout, self.game_heading = _card(self._headings, top, 2)
        game_card.setObjectName("homeGameCard")
        self.game_hint = QLabel()
        self.game_hint.setProperty("role", "caption")
        self.game_hint.setFont(theme.font("caption"))
        self.game_hint.setWordWrap(True)
        game_layout.addWidget(self.game_hint)
        self.game_path = ElidedLabel()
        self.game_path.setObjectName("homeGamePath")
        self.game_path.setFont(theme.font("mono"))
        mark_data(self.game_path)
        game_layout.addWidget(self.game_path)
        self.game_badge = StatusBadge()
        game_layout.addWidget(self.game_badge)
        self.game_button = QPushButton()
        self.game_button.setObjectName("homeGameButton")
        self.game_button.setIcon(make_icon("folder_open", "gold_light"))
        self.game_button.clicked.connect(self._browse_game)
        game_layout.addWidget(self.game_button, 0, Qt.AlignmentFlag.AlignLeft)
        game_layout.addStretch(1)

        mods_card, mods_layout, self.mods_heading = _card(self._headings, top, 3)
        mods_card.setObjectName("homeModsCard")
        self.mods_hint = QLabel()
        self.mods_hint.setProperty("role", "caption")
        self.mods_hint.setFont(theme.font("caption"))
        self.mods_hint.setWordWrap(True)
        mods_layout.addWidget(self.mods_hint)
        self.mods_grid = TileGrid(self.MOD_TILE_WIDTH)
        mods_layout.addWidget(self.mods_grid)
        self.new_tile = ActionTile("save", N_("home.new_mod"), N_("home.new_mod_text"))
        self.new_tile.setObjectName("newModTile")
        self.new_tile.clicked.connect(self.new_mod_requested.emit)
        self.other_tile = ActionTile("folder_open", N_("home.other_folder"), N_("home.other_folder_text"))
        self.other_tile.setObjectName("otherFolderTile")
        self.other_tile.clicked.connect(self._browse_mod)
        self.project_badge = StatusBadge()
        self.project_badge.setObjectName("homeProjectState")
        mods_layout.addWidget(self.project_badge)
        self.pending_button = QPushButton()
        self.pending_button.setObjectName("homePendingButton")
        self.pending_button.setIcon(make_icon("scroll_seal", "gold_light"))
        self.pending_button.clicked.connect(lambda: self.navigate_requested.emit("project:pending"))
        mods_layout.addWidget(self.pending_button, 0, Qt.AlignmentFlag.AlignLeft)
        column.addLayout(top)

        flows_card, flows_layout, self.flows_heading = _card(self._headings, column)
        flows_card.setObjectName("homeFlowsCard")
        self.flows_hint = QLabel()
        self.flows_hint.setProperty("role", "caption")
        self.flows_hint.setFont(theme.font("caption"))
        self.flows_hint.setWordWrap(True)
        flows_layout.addWidget(self.flows_hint)
        self.flows_grid = TileGrid(self.FLOW_TILE_WIDTH)
        self.flow_tiles = [FlowTile(*flow) for flow in FLOWS]
        for tile in self.flow_tiles:
            tile.clicked.connect(lambda checked=False, t=tile: self.navigate_requested.emit(t.target))
        self.flows_grid.set_tiles(self.flow_tiles)
        flows_layout.addWidget(self.flows_grid)

        self.roadmap = RoadmapCard()
        column.addWidget(self.roadmap)
        column.addStretch(1)
        scroll.setWidget(content)
        self.body.addWidget(scroll)
        self.mod_tiles: list[ModTile] = []
        self._refresh_mods()

    # --- API -------------------------------------------------------------------------------------

    def game_root(self) -> Path | None:
        return self._game

    def set_game_path(self, path: Path | None) -> None:
        path = Path(path) if path else None
        if path == self._game:
            return
        self._game = path
        self._refresh_mods()
        self.retranslate()

    def set_mod_path(self, path: Path | None) -> None:
        self._mod = Path(path) if path else None
        self._mark_current()

    def refresh(self) -> None:
        """Vuelve a leer los ``.mod`` de ``<juego>/mod`` (p. ej. tras crear un mod)."""
        self._refresh_mods()
        self.retranslate()

    def current_mod_tile(self) -> ModTile | None:
        return next((tile for tile in self.mod_tiles if tile.isChecked()), None)

    # --- interno ---------------------------------------------------------------------------------

    def _refresh_mods(self) -> None:
        tiles: list[ModTile] = []
        if self._game is not None:
            for file in descriptor_files(self._game / "mod"):
                descriptor = read_descriptor(file)
                if descriptor is None:
                    continue
                tile = ModTile(descriptor, mod_folder_of(descriptor, self._game))
                tile.clicked.connect(lambda checked=False, t=tile: self._open_tile(t))
                tile.retranslate()
                tiles.append(tile)
        tiles.sort(key=lambda t: (t.name.text().casefold(), t.descriptor.file.name.casefold()))
        self.mod_tiles = tiles
        self.mods_grid.set_tiles([*tiles, self.new_tile, self.other_tile])
        self._mark_current()

    def _mark_current(self) -> None:
        for tile in self.mod_tiles:
            tile.set_current(self._mod is not None and same_folder(tile.folder, self._mod))

    def _open_tile(self, tile: ModTile) -> None:
        tile.setChecked(self._mod is not None and same_folder(tile.folder, self._mod))
        if not tile.folder.is_dir():
            self.request_status("home.mod_missing", folder=os.fspath(tile.folder))
            return
        self.mod_selected.emit(tile.folder)

    def _browse_game(self) -> None:
        start = os.fspath(self._game) if self._game and self._game.exists() else QDir.homePath()
        chosen = QFileDialog.getExistingDirectory(self, tr("project.paths.dialog_game"), start)
        if chosen:
            self.game_path_selected.emit(Path(chosen))

    def _browse_mod(self) -> None:
        base = self._game / "mod" if self._game is not None else None
        start = os.fspath(base) if base is not None and base.is_dir() else QDir.homePath()
        chosen = QFileDialog.getExistingDirectory(self, tr("project.paths.dialog_mod"), start)
        if chosen:
            self.mod_selected.emit(Path(chosen))

    def _on_opening(self, game, mod) -> None:
        self._project_state = ("neutral", N_("home.project_opening"), {"name": Path(mod).name})
        self._retranslate_project()

    def _on_opened(self, project) -> None:
        self._on_dirty(self.session.dirty_count())

    def _on_open_failed(self, key: str, fmt) -> None:
        self._project_state = ("error", N_("home.project_failed"), {"reason": tr(key, **dict(fmt or {}))})
        self._retranslate_project()

    def _on_closed(self) -> None:
        self._project_state = ("neutral", N_("home.project_none"), {})
        self._retranslate_project()

    def _on_dirty(self, count: int = 0) -> None:
        project = self.session.project
        if project is None:
            return
        name = project.descriptor.name if project.descriptor is not None and project.descriptor.name \
            else project.mod_root.name
        count = self.session.dirty_count()
        if project.read_only:
            self._project_state = ("warning", N_("home.project_read_only"), {"name": name})
        elif count:
            key = N_("home.project_dirty_one") if count == 1 else N_("home.project_dirty")
            self._project_state = ("ok", key, {"name": name, "count": count})
        else:
            self._project_state = ("ok", N_("home.project_open"), {"name": name})
        self._retranslate_project()

    def _retranslate_project(self) -> None:
        level, key, fmt = self._project_state
        self.project_badge.set_status(level, tr(key, **fmt))
        count = self.session.dirty_count()
        self.pending_button.setVisible(count > 0)
        self.pending_button.setText(tr("home.see_pending", count=count))

    def retranslate(self) -> None:
        super().retranslate()
        self.game_heading.setText(tr("home.game_title"))
        self.game_hint.setText(tr("home.game_hint"))
        report = inspect_folder(self._game)
        level, key, fmt = evaluate_game(report)
        self.game_badge.set_status(level, tr(key, **fmt))
        self.game_path.set_text(os.fspath(self._game) if self._game else tr("home.game_none"))
        self.game_path.setToolTip(os.fspath(self._game) if self._game else "")
        self.game_button.setText(tr("home.game_choose"))
        self.game_button.setToolTip(tr("project.paths.browse_game_tooltip"))
        self.mods_heading.setText(tr("home.mods_title"))
        if self._game is None:
            self.mods_hint.setText(tr("home.mods_no_game"))
        elif not self.mod_tiles:
            self.mods_hint.setText(tr("home.mods_none", folder=os.fspath(self._game / "mod")))
        else:
            self.mods_hint.setText(tr("home.mods_hint", count=len(self.mod_tiles)))
        for tile in (*self.mod_tiles, self.new_tile, self.other_tile, *self.flow_tiles):
            tile.retranslate()
        self.flows_heading.setText(tr("home.flows_title"))
        self.flows_hint.setText(tr("home.flows_hint"))
        self.roadmap.retranslate()
        self._retranslate_project()
