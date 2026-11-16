"""El gestor de imágenes (wizard §17.3): eventos, decisiones, banderas, tecnologías, noticias y pantallas de carga.

A la izquierda, las familias (``core.gfx.images.PICTURE_SLOTS``) con su formato y su tamaño esperado, que es el
más común de los archivos que ya hay en su carpeta (solo se leen las cabeceras). En el centro, las imágenes de
la familia elegida, con miniaturas que se dibujan poco a poco; sin arte del juego (``VIC2STUDIO_NO_GAME_ART``)
se ven solo los nombres. «Importar…» abre ``PictureImportDialog``: encuadre (cubrir, encajar o estirar), punto
de interés y una vista previa dentro del marco real. Una imagen de evento se ve compuesta en la ventana del
evento (``core.gui.event_window``) cuando hay arte para ella.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListView,
    QListWidget, QListWidgetItem, QPushButton, QSlider, QSplitter, QVBoxLayout, QWidget,
)

from ...core.vfs.paths import VPath
from ...i18n import N_, tr, translator
from ..widgets import make_icon, mark_data
from . import game_art_allowed, renderer_of, source_of, to_pixmap
from .import_dialog import IMAGE_FILTER, read_image_file, sprite_error_text

THUMB = 72
BATCH = 12
ROLE_REL = Qt.ItemDataRole.UserRole
SLOT_LABELS = {"event": N_("interface.images.slot.event"), "decision": N_("interface.images.slot.decision"),
               "flag": N_("interface.images.slot.flag"), "tech": N_("interface.images.slot.tech"),
               "news": N_("interface.images.slot.news"), "loadingscreen": N_("interface.images.slot.loadingscreen")}
MODE_LABELS = {"cover": N_("interface.images.mode.cover"), "contain": N_("interface.images.mode.contain"),
               "stretch": N_("interface.images.mode.stretch")}
IMAGE_SUFFIXES = (".tga", ".dds", ".png", ".bmp", ".jpg", ".jpeg")


def read_header(session, rel) -> bytes | None:
    """Los primeros bytes del archivo efectivo ``rel`` (lo abierto sin guardar manda). Solo lee."""
    from ...core.gfx.images import HEADER_BYTES

    project = getattr(session, "project", None)
    if project is None:
        return None
    ws = project.ws
    handle = ws.peek(rel)
    if handle is not None and not handle.deleted and isinstance(handle.model, (bytes, bytearray)):
        return bytes(handle.model[:HEADER_BYTES])
    entry = ws.vfs.resolve(rel)
    if entry is None:
        return None
    try:
        with open(entry.path, "rb") as stream:
            return stream.read(HEADER_BYTES)
    except OSError:
        return None


def slot_pictures(session, slot) -> list:
    """Las imágenes efectivas de la carpeta de ``slot``, ordenadas por nombre."""
    source = source_of(session)
    if source is None:
        return []
    return [rel for rel in source.rels(slot.folder, "*") if rel.suffix.lower() in IMAGE_SUFFIXES]


def slot_size(session, slot) -> tuple[int, int]:
    """Tamaño esperado de la familia: el más común de su carpeta o, sin archivos, el de la tabla."""
    from ...core.gfx.images import expected_size

    return expected_size(slot, lambda rel: read_header(session, rel), slot_pictures(session, slot))


def picture_image(session, rel) -> Image.Image | None:
    """La imagen efectiva ``rel`` en RGBA, o None (sin arte del juego, o ilegible)."""
    if not game_art_allowed():
        return None
    source = source_of(session)
    data = source.read(rel) if source is not None else None
    if data is None:
        return None
    from ...core.gui import load_image

    try:
        return load_image(data)
    except ValueError:
        return None


class PictureManager(QWidget):
    """Familias de imágenes, sus archivos y «Importar…»."""

    imported = Signal(object)                     # VPath escrita

    def __init__(self, session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.setObjectName("pictureManager")
        self.sizes: dict[str, tuple[int, int]] = {}
        self._pending: list[QListWidgetItem] = []
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._paint_batch)
        self.dialog: PictureImportDialog | None = None
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.slots = QListWidget()
        self.slots.setObjectName("pictureSlots")
        self.slots.currentRowChanged.connect(self._on_slot)
        split.addWidget(self.slots)
        middle = QWidget()
        column = QVBoxLayout(middle)
        column.setContentsMargins(8, 0, 0, 0)
        bar = QHBoxLayout()
        self.slot_info = QLabel()
        self.slot_info.setObjectName("pictureSlotInfo")
        self.slot_info.setWordWrap(True)
        self.import_button = QPushButton()
        self.import_button.setObjectName("pictureImport")
        self.import_button.setIcon(make_icon("plus", "gold_light"))
        self.import_button.clicked.connect(self.open_import)
        bar.addWidget(self.slot_info, 1)
        bar.addWidget(self.import_button)
        column.addLayout(bar)
        self.grid = mark_data(QListWidget())
        self.grid.setObjectName("pictureGrid")
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setIconSize(QSize(THUMB, THUMB))
        self.grid.setGridSize(QSize(THUMB + 60, THUMB + 34))
        self.grid.setWordWrap(True)
        self.grid.currentItemChanged.connect(self._on_picture)
        column.addWidget(self.grid, 1)
        self.detail = mark_data(QLabel())
        self.detail.setObjectName("pictureDetail")
        self.detail.setWordWrap(True)
        column.addWidget(self.detail)
        split.addWidget(middle)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 4)
        outer.addWidget(split)
        from ...core.gfx.images import PICTURE_SLOTS

        for candidate in PICTURE_SLOTS:
            item = QListWidgetItem(make_icon("file_image", "ink_soft"), "")
            item.setData(ROLE_REL, candidate.key)
            self.slots.addItem(item)
        translator().languageChanged.connect(self._on_language)
        self.retranslate()

    # --- textos ------------------------------------------------------------------------------------

    def _on_language(self, _code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        for row in range(self.slots.count()):
            item = self.slots.item(row)
            item.setText(tr(SLOT_LABELS[item.data(ROLE_REL)]))
        self.import_button.setText(tr(N_("interface.images.import")))
        self._show_slot_info()

    # --- datos -------------------------------------------------------------------------------------

    def current_slot(self):
        from ...core.gfx.images import slot

        item = self.slots.currentItem()
        return slot(item.data(ROLE_REL)) if item is not None else None

    def select_slot(self, key: str) -> bool:
        for row in range(self.slots.count()):
            if self.slots.item(row).data(ROLE_REL) == key:
                self.slots.setCurrentRow(row)
                return True
        return False

    def reload(self) -> None:
        self.sizes = {}
        if self.slots.currentRow() < 0 and self.slots.count():
            self.slots.setCurrentRow(0)
        else:
            self._on_slot(self.slots.currentRow())

    def expected(self, candidate) -> tuple[int, int]:
        if candidate.key not in self.sizes:
            self.sizes[candidate.key] = slot_size(self.session, candidate) if self.session.project is not None \
                else candidate.size
        return self.sizes[candidate.key]

    def _show_slot_info(self) -> None:
        candidate = self.current_slot()
        if candidate is None:
            self.slot_info.setText("")
            return
        width, height = self.expected(candidate)
        self.slot_info.setText(tr(N_("interface.images.slot_info"), folder=candidate.folder,
                                  format=candidate.format.upper(), w=width, h=height, count=self.grid.count()))

    def _on_slot(self, _row: int) -> None:
        candidate = self.current_slot()
        self._timer.stop()
        self.grid.clear()
        self._pending = []
        if candidate is not None and self.session.project is not None:
            blank = make_icon("file_image", "ink_soft")
            for rel in slot_pictures(self.session, candidate):
                item = QListWidgetItem(blank, rel.name)
                item.setData(ROLE_REL, str(rel))
                item.setToolTip(str(rel))
                self.grid.addItem(item)
                self._pending.append(item)
        if self._pending and game_art_allowed():
            self._timer.start()
        else:
            self._pending = []
        self.import_button.setEnabled(candidate is not None and self.session.project is not None
                                      and not self.session.is_read_only())
        self._show_slot_info()
        self.detail.setText("")

    def _paint_batch(self) -> None:
        for item in self._pending[:BATCH]:
            image = picture_image(self.session, VPath.of(item.data(ROLE_REL)))
            if image is not None:
                image.thumbnail((THUMB, THUMB))
                item.setIcon(QIcon(to_pixmap(image)))
        del self._pending[:BATCH]
        if not self._pending:
            self._timer.stop()

    def is_busy(self) -> bool:
        return bool(self._pending)

    def finish(self) -> None:
        while self._pending:
            self._paint_batch()

    def select_picture(self, name: str) -> bool:
        for row in range(self.grid.count()):
            item = self.grid.item(row)
            if VPath.of(item.data(ROLE_REL)).name.lower() == name.lower():
                self.grid.setCurrentItem(item)
                return True
        return False

    def _on_picture(self, item, _previous=None) -> None:
        if item is None:
            self.detail.setText("")
            return
        rel = VPath.of(item.data(ROLE_REL))
        from ...core.gfx.images import image_size

        size = image_size(read_header(self.session, rel) or b"")
        size_text = f"{size[0]}×{size[1]}" if size else "?"
        self.detail.setText(tr(N_("interface.images.detail"), file=str(rel), size=size_text))

    # --- importar ----------------------------------------------------------------------------------

    def import_dialog(self) -> PictureImportDialog | None:
        """El diálogo «Importar…» de la familia elegida, sin abrirlo (las pruebas lo rellenan)."""
        candidate = self.current_slot()
        if candidate is None or self.session.project is None:
            return None
        self.dialog = PictureImportDialog(self.session, candidate, self.expected(candidate), self)
        self.dialog.accepted.connect(self._on_imported)
        return self.dialog

    def open_import(self) -> None:
        dialog = self.import_dialog()
        if dialog is not None:
            dialog.open()

    def _on_imported(self) -> None:
        rel = self.dialog.written if self.dialog is not None else None
        self.sizes = {}
        self._on_slot(self.slots.currentRow())
        if rel is not None:
            self.select_picture(rel.name)
            self.imported.emit(rel)


class PictureImportDialog(QDialog):
    """«Importar…»: la imagen propia encuadrada al tamaño de su familia, con vista previa en el marco real."""

    def __init__(self, session, slot, size: tuple[int, int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.slot = slot
        self.size = (int(size[0]), int(size[1]))
        self.image: Image.Image | None = None
        self.written = None
        self.setObjectName("pictureImportDialog")
        self.setWindowTitle(tr(N_("interface.images.import_title"), family=tr(SLOT_LABELS[slot.key])))
        layout = QVBoxLayout(self)
        info = QLabel(tr(N_("interface.images.import_intro"), folder=slot.folder, format=slot.format.upper(),
                         w=self.size[0], h=self.size[1]))
        info.setWordWrap(True)
        layout.addWidget(info)
        row = QHBoxLayout()
        self.pick_button = QPushButton(tr(N_("interface.new_sprite.pick")))
        self.pick_button.setObjectName("pictureImportPick")
        self.pick_button.clicked.connect(self.ask_image)
        self.file_label = mark_data(QLabel())
        row.addWidget(self.pick_button)
        row.addWidget(self.file_label, 1)
        layout.addLayout(row)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("pictureImportName")
        self.name_edit.textChanged.connect(self.refresh)
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("pictureImportMode")
        from ...core.gfx.flags import FIT_MODES

        for mode in FIT_MODES:
            self.mode_combo.addItem(tr(MODE_LABELS[mode]), mode)
        self.mode_combo.currentIndexChanged.connect(self.refresh)
        self.focus_x = QSlider(Qt.Orientation.Horizontal)
        self.focus_x.setObjectName("pictureImportFocusX")
        self.focus_y = QSlider(Qt.Orientation.Horizontal)
        self.focus_y.setObjectName("pictureImportFocusY")
        for slider in (self.focus_x, self.focus_y):
            slider.setRange(0, 100)
            slider.setValue(50)
            slider.valueChanged.connect(self.refresh)
        form.addRow(tr(N_("interface.images.name")), self.name_edit)
        form.addRow(tr(N_("interface.images.mode")), self.mode_combo)
        form.addRow(tr(N_("interface.images.focus_x")), self.focus_x)
        form.addRow(tr(N_("interface.images.focus_y")), self.focus_y)
        layout.addLayout(form)
        self.preview = QLabel()
        self.preview.setObjectName("pictureImportPreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(360, 220)
        layout.addWidget(self.preview, 1)
        self.plan_label = mark_data(QLabel())
        self.plan_label.setObjectName("pictureImportPlan")
        layout.addWidget(self.plan_label)
        self.error_label = QLabel()
        self.error_label.setObjectName("pictureImportError")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.import_button = buttons.addButton(tr(N_("interface.images.do_import")),
                                               QDialogButtonBox.ButtonRole.AcceptRole)
        self.import_button.setObjectName("pictureImportDo")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr(N_("interface.cancel")))
        buttons.accepted.connect(self.import_and_close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def ask_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr(N_("interface.new_sprite.pick")), "",
                                              tr(N_("interface.image_filter"), patterns=IMAGE_FILTER))
        if not path:
            return
        image = read_image_file(path)
        if image is None:
            self.error_label.setText(tr(N_("interface.unreadable"), file=path))
            return
        self.set_image(image, Path(path).stem, label=path)

    def set_image(self, image: Image.Image, stem: str = "", *, label: str = "") -> None:
        self.image = image
        self.file_label.setText(label or f"{image.size[0]}×{image.size[1]}")
        if stem and not self.name_edit.text():
            self.name_edit.setText(stem)
        self.refresh()

    def fitted(self) -> Image.Image | None:
        from ...core.gfx.images import fit_image

        if self.image is None:
            return None
        return fit_image(self.image, self.size, mode=self.mode_combo.currentData(),
                         focus=(self.focus_x.value() / 100, self.focus_y.value() / 100))

    def preview_image(self) -> Image.Image | None:
        """Lo que enseña la vista previa: la ventana del evento con la imagen en su marco (si hay arte) o la
        imagen encuadrada sobre un marco procedural."""
        picture = self.fitted()
        if picture is None:
            return None
        if self.slot.key == "event":
            renderer = renderer_of(self.session)
            source = source_of(self.session)
            if renderer is not None and source is not None:
                from ...core.gui.event_window import render_event

                composed = render_event(renderer, source, province=False, title=self.name_edit.text(), desc="",
                                        options=(), picture=picture)
                if composed is not None:
                    return composed
        frame = Image.new("RGBA", (picture.size[0] + 12, picture.size[1] + 12), (122, 86, 48, 255))
        frame.alpha_composite(picture, (6, 6))
        return frame

    def refresh(self, *_args) -> None:
        name = self.name_edit.text().strip()
        self.plan_label.setText(f"{self.slot.folder}/{name or '…'}.{self.slot.format}")
        self.error_label.setText("")
        self.focus_x.setEnabled(self.mode_combo.currentData() == "cover")
        self.focus_y.setEnabled(self.mode_combo.currentData() == "cover")
        image = self.preview_image()
        if image is None:
            self.preview.setText(tr(N_("interface.new_sprite.no_image")))
            self.import_button.setEnabled(False)
            return
        shown = image.copy()
        shown.thumbnail((640, 420))
        self.preview.setPixmap(to_pixmap(shown))
        self.import_button.setEnabled(bool(name) and self.session.project is not None
                                      and not self.session.is_read_only())

    def do_import(self):
        """Escribe la imagen (un paso de deshacer). Devuelve la ruta escrita o None con el error a la vista."""
        from ...core.gui.sprites import SpriteError, import_picture

        if self.image is None or self.session.project is None:
            return None
        name = self.name_edit.text().strip()
        try:
            with self.session.edit("undo.import_picture", name=name, folder=self.slot.folder):
                self.written = import_picture(self.session.project.ws, self.slot, name, self.image, self.size,
                                              mode=self.mode_combo.currentData(),
                                              focus=(self.focus_x.value() / 100, self.focus_y.value() / 100))
        except SpriteError as exc:
            self.error_label.setText(sprite_error_text(exc))
            return None
        except (OSError, ValueError, PermissionError) as exc:
            self.error_label.setText(tr(N_("interface.write_failed"), error=str(exc)))
            return None
        return self.written

    def import_and_close(self) -> None:
        if self.do_import() is not None:
            self.accept()
