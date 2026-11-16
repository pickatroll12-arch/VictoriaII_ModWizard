"""El catálogo de sprites (wizard §17.3): rejilla de miniaturas con buscador, filtro por archivo, usos y repetidos.

Lee el ``SpriteDB`` del renderizador compartido (``renderer_of``), así que ve lo mismo que el lienzo: la vista
efectiva con lo que aún no se ha guardado. Las miniaturas se dibujan poco a poco con un temporizador (vanilla
tiene 1 264 sprites) y, sin arte del juego, son el recuadro procedural. Al elegir un sprite se ven su tipo, su
textura (y si falta o solo existe con la otra extensión), dónde se define, si está repetido y los ``.gui`` que
lo usan. Doble clic en un uso emite ``usage_activated(ruta, línea)``.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

from ...core.vfs.paths import VPath
from ...i18n import N_, tr, translator
from ..widgets import make_icon, mark_data
from . import renderer_of, to_pixmap

THUMB = 64
BATCH = 24                                   # miniaturas por vuelta del temporizador
ROLE_NAME = Qt.ItemDataRole.UserRole
ROLE_USAGE = Qt.ItemDataRole.UserRole + 1
# La grafía habitual de cada tipo de definición (el catálogo los guarda en minúsculas).
KIND_NAMES = {"spritetype": "spriteType", "corneredtilespritetype": "corneredTileSpriteType",
              "textspritetype": "textSpriteType", "maskedshieldtype": "maskedShieldType",
              "progressbartype": "progressbarType", "linecharttype": "LineChartType",
              "piecharttype": "PieChartType", "scrollingspritetype": "scrollingSpriteType"}


def thumbnail(renderer, sprite, size: int = THUMB):
    """Miniatura cuadrada (PIL) del primer fotograma del sprite, o el recuadro procedural si no hay imagen."""
    from PIL import Image

    image = renderer.sprite_image(sprite.name) if renderer is not None else None
    if image is None:
        return renderer.placeholder((size, size), "") if renderer is not None else Image.new("RGBA", (size, size))
    picture = image.copy()
    picture.thumbnail((size, size))
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(picture, ((size - picture.size[0]) // 2, (size - picture.size[1]) // 2))
    return canvas


class SpriteBrowser(QWidget):
    """Rejilla de sprites con su ficha. ``new_requested`` lo emite el botón «Nuevo sprite…»."""

    sprite_selected = Signal(str)
    usage_activated = Signal(object, int)
    new_requested = Signal()

    def __init__(self, session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.setObjectName("spriteBrowser")
        self.sprites: list = []
        self.duplicates: set[str] = set()
        self._pending: list[QListWidgetItem] = []
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._paint_batch)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("spriteSearch")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill)
        self.file_filter = mark_data(QComboBox())
        self.file_filter.setObjectName("spriteFile")
        self.file_filter.currentIndexChanged.connect(self._fill)
        self.only_duplicates = QCheckBox()
        self.only_duplicates.setObjectName("spriteDuplicates")
        self.only_duplicates.toggled.connect(self._fill)
        self.only_missing = QCheckBox()
        self.only_missing.setObjectName("spriteMissing")
        self.only_missing.toggled.connect(self._fill)
        self.new_button = QPushButton()
        self.new_button.setObjectName("spriteNew")
        self.new_button.setIcon(make_icon("plus", "gold_light"))
        self.new_button.clicked.connect(self.new_requested)
        bar.addWidget(self.search, 2)
        bar.addWidget(self.file_filter, 1)
        bar.addWidget(self.only_duplicates)
        bar.addWidget(self.only_missing)
        bar.addWidget(self.new_button)
        outer.addLayout(bar)
        self.count_label = QLabel()
        self.count_label.setObjectName("spriteCount")
        outer.addWidget(self.count_label)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.grid = mark_data(QListWidget())
        self.grid.setObjectName("spriteGrid")
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setIconSize(QSize(THUMB, THUMB))
        self.grid.setGridSize(QSize(THUMB + 64, THUMB + 46))
        self.grid.setSpacing(4)
        self.grid.setWordWrap(True)
        self.grid.setUniformItemSizes(True)
        self.grid.currentItemChanged.connect(self._on_current)
        split.addWidget(self.grid)
        side = QWidget()
        column = QVBoxLayout(side)
        column.setContentsMargins(8, 0, 0, 0)
        self.preview = QLabel()
        self.preview.setObjectName("spritePreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(140)
        self.title = mark_data(QLabel())
        self.title.setObjectName("spriteTitle")
        self.title.setProperty("role", "heading")
        self.detail = mark_data(QLabel())
        self.detail.setObjectName("spriteDetail")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.usages_title = QLabel()
        self.usages = mark_data(QListWidget())
        self.usages.setObjectName("spriteUsages")
        self.usages.itemDoubleClicked.connect(self._on_usage)
        for widget in (self.preview, self.title, self.detail, self.usages_title):
            column.addWidget(widget)
        column.addWidget(self.usages, 1)
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        outer.addWidget(split, 1)
        translator().languageChanged.connect(self._on_language)
        self.retranslate()

    # --- textos ------------------------------------------------------------------------------------

    def _on_language(self, _code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.search.setPlaceholderText(tr(N_("interface.sprites.search")))
        self.only_duplicates.setText(tr(N_("interface.sprites.only_duplicates")))
        self.only_missing.setText(tr(N_("interface.sprites.only_missing")))
        self.new_button.setText(tr(N_("interface.sprites.new")))
        self.usages_title.setText(tr(N_("interface.sprites.usages")))
        if self.file_filter.count():
            self.file_filter.setItemText(0, tr(N_("interface.sprites.all_files")))
        self._update_count()
        self._show(self.current_name())

    # --- datos -------------------------------------------------------------------------------------

    def renderer(self):
        return renderer_of(self.session)

    def reload(self) -> None:
        """Vuelve a leer el catálogo (sin proyecto, vacío) y conserva el filtro y el sprite elegido."""
        renderer = self.renderer()
        current = self.current_name()
        db = renderer.sprites if renderer is not None else None
        self.sprites = sorted(db.all(), key=lambda s: s.name.lower()) if db is not None else []
        self.duplicates = {name.lower() for name in db.duplicates()} if db is not None else set()
        chosen = self.file_filter.currentData()
        self.file_filter.blockSignals(True)
        self.file_filter.clear()
        self.file_filter.addItem(tr(N_("interface.sprites.all_files")), None)
        for rel in sorted({str(s.rel) for s in self.sprites}, key=str.lower):
            self.file_filter.addItem(rel, rel)
        index = self.file_filter.findData(chosen) if chosen else 0
        self.file_filter.setCurrentIndex(max(0, index))
        self.file_filter.blockSignals(False)
        self.new_button.setEnabled(self.session.project is not None and not self.session.is_read_only())
        self._fill()
        if current:
            self.select(current)

    def visible_sprites(self) -> list:
        text = self.search.text().strip().lower()
        rel = self.file_filter.currentData()
        found = []
        for sprite in self.sprites:
            if text and text not in sprite.name.lower() and text not in (sprite.texture or "").lower():
                continue
            if rel and str(sprite.rel) != rel:
                continue
            if self.only_duplicates.isChecked() and sprite.key not in self.duplicates:
                continue
            if self.only_missing.isChecked() and not (sprite.texture and sprite.resolved is None):
                continue
            found.append(sprite)
        return found

    def _fill(self, *_args) -> None:
        current = self.current_name()
        self._timer.stop()
        self.grid.blockSignals(True)
        self.grid.clear()
        self._pending = []
        blank = QIcon(make_icon("file_image", "ink_soft"))
        for sprite in self.visible_sprites():
            # Un nombre repetido sale una vez por definición; la ficha enseña la última, que es la que usa el juego.
            item = QListWidgetItem(blank, sprite.name)
            item.setData(ROLE_NAME, sprite.name)
            item.setToolTip(f"{sprite.name}\n{sprite.rel}:{sprite.line}")
            self.grid.addItem(item)
            self._pending.append(item)
        self.grid.blockSignals(False)
        self._update_count()
        if self._pending:
            self._timer.start()
        if not self.select(current) and self.grid.count():
            self.grid.setCurrentRow(0)
        elif not self.grid.count():
            self._show(None)

    def _update_count(self) -> None:
        self.count_label.setText(tr(N_("interface.sprites.count"), shown=self.grid.count(), total=len(self.sprites),
                                    duplicates=len(self.duplicates)))

    def _paint_batch(self) -> None:
        renderer = self.renderer()
        by_key: dict[str, list] = {}
        for sprite in self.sprites:
            by_key.setdefault(sprite.key, []).append(sprite)
        for item in self._pending[:BATCH]:
            name = item.data(ROLE_NAME)
            found = by_key.get(name.lower())
            if found:
                item.setIcon(QIcon(to_pixmap(thumbnail(renderer, found[-1]))))
        del self._pending[:BATCH]
        if not self._pending:
            self._timer.stop()

    def is_busy(self) -> bool:
        return bool(self._pending)

    def finish(self) -> None:
        """Dibuja ya todas las miniaturas pendientes (pruebas y capturas)."""
        while self._pending:
            self._paint_batch()

    # --- selección ---------------------------------------------------------------------------------

    def current_name(self) -> str | None:
        item = self.grid.currentItem()
        return item.data(ROLE_NAME) if item is not None else None

    def select(self, name: str | None) -> bool:
        if not name:
            return False
        for row in range(self.grid.count()):
            item = self.grid.item(row)
            if item.data(ROLE_NAME).lower() == name.lower():
                self.grid.setCurrentItem(item)
                self._show(item.data(ROLE_NAME))
                return True
        return False

    def _on_current(self, item, _previous=None) -> None:
        name = item.data(ROLE_NAME) if item is not None else None
        self._show(name)
        if name:
            self.sprite_selected.emit(name)

    def _show(self, name: str | None) -> None:
        renderer = self.renderer()
        sprite = renderer.sprites.get(name) if renderer is not None and name else None
        self.usages.clear()
        if sprite is None:
            self.title.setText("")
            self.detail.setText(tr(N_("interface.sprites.none")))
            self.preview.clear()
            return
        self.title.setText(sprite.name)
        if sprite.resolved is None and sprite.texture:
            state = tr(N_("interface.sprites.texture_missing"))
        elif sprite.alternative_extension:
            state = tr(N_("interface.sprites.texture_alt"), file=str(sprite.resolved))
        else:
            state = tr(N_("interface.sprites.texture_ok"))
        lines = [tr(N_("interface.sprites.kind"), kind=KIND_NAMES.get(sprite.kind, sprite.kind), frames=sprite.frames),
                 tr(N_("interface.sprites.texture"), file=sprite.texture or "—", state=state),
                 tr(N_("interface.sprites.defined"), file=str(sprite.rel), line=sprite.line)]
        if sprite.border:
            lines.append(tr(N_("interface.sprites.border"), x=sprite.border[0], y=sprite.border[1]))
        if sprite.key in self.duplicates:
            repeated = {key.lower(): found for key, found in renderer.sprites.duplicates().items()}
            places = [f"{s.rel}:{s.line}" for s in repeated.get(sprite.key, [])]
            lines.append(tr(N_("interface.sprites.duplicate"), places=", ".join(places)))
        self.detail.setText("\n".join(lines))
        image = renderer.sprite_image(sprite.name)
        if image is not None:
            picture = image.copy()
            picture.thumbnail((240, 140))
            self.preview.setPixmap(to_pixmap(picture))
        else:
            self.preview.setPixmap(to_pixmap(renderer.placeholder((120, 80), sprite.name)))
        for rel, line in renderer.sprites.usages(sprite.name):
            item = QListWidgetItem(f"{rel}:{line}")
            item.setData(ROLE_USAGE, f"{line}:{rel}")
            self.usages.addItem(item)
        if not self.usages.count():
            self.usages.addItem(tr(N_("interface.sprites.unused")))

    def _on_usage(self, item: QListWidgetItem) -> None:
        found = item.data(ROLE_USAGE)
        if found:
            line, _, rel = str(found).partition(":")
            self.usage_activated.emit(VPath.of(rel), int(line))
