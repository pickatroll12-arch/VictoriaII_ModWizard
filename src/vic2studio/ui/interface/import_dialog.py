"""«Nuevo sprite» desde una imagen propia (wizard §17.3, criterio 3 de la iteración 8).

El diálogo pide la imagen (PNG, TGA, DDS…), el nombre del sprite, su tipo (``spriteType`` o
``corneredTileSpriteType`` con su borde) y cuántos fotogramas tiene. Enseña la imagen partida en fotogramas y
el plan: la textura DDS sin comprimir que se escribirá en ``gfx/interface/<P>/`` y el ``.gfx`` donde irá la
definición. «Crear» llama a ``core.gui.sprites.new_sprite`` en **un** paso de deshacer; los errores
(``SpriteError``) se explican debajo sin cerrar el diálogo.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from ...i18n import N_, tr
from ..widgets import make_icon, mark_data
from . import to_pixmap

IMAGE_FILTER = "*.png *.tga *.dds *.bmp *.jpg *.jpeg"


def read_image_file(path) -> Image.Image | None:
    """La imagen de un archivo propio (PNG, TGA, DDS…) en RGBA, o None si no se entiende. Solo lee."""
    from ...core.gui import load_image

    try:
        return load_image(Path(path).read_bytes())
    except (OSError, ValueError):
        return None


def prefix_of(session) -> str:
    project = getattr(session, "project", None)
    settings = getattr(project, "settings", None)
    return (getattr(settings, "prefix", None) or "mod") if project is not None else "mod"


def sprite_error_text(exc) -> str:
    code = getattr(exc, "code", None)
    if code is None:
        return str(exc)
    return tr(f"gui.sprite_error.{code}", **getattr(exc, "params", {}))


class NewSpriteDialog(QDialog):
    """El diálogo «Nuevo sprite». ``set_image`` lo rellena sin abrir el selector de archivos (pruebas)."""

    def __init__(self, session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.setObjectName("newSpriteDialog")
        self.setWindowTitle(tr(N_("interface.new_sprite.title")))
        self.image: Image.Image | None = None
        self.created = None
        layout = QVBoxLayout(self)
        intro = QLabel(tr(N_("interface.new_sprite.intro")))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = QHBoxLayout()
        self.pick_button = QPushButton(tr(N_("interface.new_sprite.pick")))
        self.pick_button.setObjectName("newSpritePick")
        self.pick_button.setIcon(make_icon("file_image", "gold_light"))
        self.pick_button.clicked.connect(self.ask_image)
        self.file_label = mark_data(QLabel())
        self.file_label.setObjectName("newSpriteFile")
        row.addWidget(self.pick_button)
        row.addWidget(self.file_label, 1)
        layout.addLayout(row)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("newSpriteName")
        self.name_edit.textChanged.connect(self.refresh)
        self.kind_combo = mark_data(QComboBox())
        self.kind_combo.setObjectName("newSpriteKind")
        for kind in ("spriteType", "corneredTileSpriteType"):
            self.kind_combo.addItem(kind, kind)
        self.kind_combo.currentIndexChanged.connect(self.refresh)
        self.frames_spin = QSpinBox()
        self.frames_spin.setObjectName("newSpriteFrames")
        self.frames_spin.setRange(1, 64)
        self.frames_spin.valueChanged.connect(self.refresh)
        border = QHBoxLayout()
        self.border_x = QSpinBox()
        self.border_x.setObjectName("newSpriteBorderX")
        self.border_y = QSpinBox()
        self.border_y.setObjectName("newSpriteBorderY")
        for spin in (self.border_x, self.border_y):
            spin.setRange(0, 256)
            spin.setValue(8)
            border.addWidget(spin)
        self.border_box = QWidget()
        self.border_box.setLayout(border)
        border.setContentsMargins(0, 0, 0, 0)
        form.addRow(tr(N_("interface.new_sprite.name")), self.name_edit)
        form.addRow(tr(N_("interface.new_sprite.kind")), self.kind_combo)
        form.addRow(tr(N_("interface.new_sprite.frames")), self.frames_spin)
        form.addRow(tr(N_("interface.new_sprite.border")), self.border_box)
        layout.addLayout(form)
        self.preview = QLabel()
        self.preview.setObjectName("newSpritePreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(320, 120)
        layout.addWidget(self.preview, 1)
        self.plan_label = mark_data(QLabel())
        self.plan_label.setObjectName("newSpritePlan")
        self.plan_label.setWordWrap(True)
        layout.addWidget(self.plan_label)
        self.error_label = QLabel()
        self.error_label.setObjectName("newSpriteError")
        self.error_label.setWordWrap(True)
        self.error_label.setProperty("role", "error")
        layout.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.create_button = self.buttons.addButton(tr(N_("interface.new_sprite.create")),
                                                    QDialogButtonBox.ButtonRole.AcceptRole)
        self.create_button.setObjectName("newSpriteCreate")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr(N_("interface.cancel")))
        self.buttons.accepted.connect(self.create_and_close)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.refresh()

    # --- imagen ------------------------------------------------------------------------------------

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
        self.file_label.setText(label or tr(N_("interface.new_sprite.size"), w=image.size[0], h=image.size[1]))
        if stem and not self.name_edit.text():
            clean = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in stem)
            self.name_edit.setText(f"GFX_{prefix_of(self.session).lower()}_{clean}")
        self.refresh()

    # --- vista previa y plan ----------------------------------------------------------------------

    def refresh(self, *_args) -> None:
        from ...core.gui.sprites import CORNERED, sprite_paths

        cornered = self.kind_combo.currentData() == CORNERED
        self.border_box.setEnabled(cornered)
        name = self.name_edit.text().strip()
        texture, gfx = sprite_paths(prefix_of(self.session), name or "…")
        self.plan_label.setText(tr(N_("interface.new_sprite.plan"), texture=str(texture), gfx=str(gfx)))
        self.error_label.setText("")
        if self.image is None:
            self.preview.setText(tr(N_("interface.new_sprite.no_image")))
            self.create_button.setEnabled(False)
            return
        picture = self.image.copy()
        factor = min(480 / picture.size[0], 200 / picture.size[1])
        if factor >= 2:
            # Una imagen pequeña se amplía a múltiplos enteros, sin suavizar, para ver sus píxeles.
            factor = min(4, int(factor))
            picture = picture.resize((picture.size[0] * factor, picture.size[1] * factor), Image.NEAREST)
        else:
            picture.thumbnail((480, 200))
        pixmap = to_pixmap(picture)
        frames = self.frames_spin.value()
        if frames > 1:
            painter = QPainter(pixmap)
            painter.setPen(QPen(QColor(232, 190, 90), 1, Qt.PenStyle.DashLine))
            for index in range(1, frames):
                x = round(pixmap.width() * index / frames)
                painter.drawLine(x, 0, x, pixmap.height())
            painter.end()
        self.preview.setPixmap(pixmap)
        self.create_button.setEnabled(self.session.project is not None and not self.session.is_read_only())

    # --- crear -------------------------------------------------------------------------------------

    def create(self):
        """Crea el sprite (un paso de deshacer). Devuelve el ``NewSprite`` o None con el error a la vista."""
        from ...core.gui.sprites import CORNERED, SpriteError, new_sprite

        if self.image is None or self.session.project is None:
            return None
        name = self.name_edit.text().strip()
        kind = self.kind_combo.currentData()
        border = (self.border_x.value(), self.border_y.value()) if kind == CORNERED else None
        try:
            with self.session.edit("undo.new_sprite", name=name):
                self.created = new_sprite(self.session.project.ws, self.session.entities, name, self.image,
                                          frames=self.frames_spin.value(), kind=kind, border=border,
                                          prefix=prefix_of(self.session))
        except SpriteError as exc:
            self.error_label.setText(sprite_error_text(exc))
            return None
        except (OSError, ValueError, PermissionError) as exc:
            self.error_label.setText(tr(N_("interface.write_failed"), error=str(exc)))
            return None
        return self.created

    def create_and_close(self) -> None:
        if self.create() is not None:
            self.accept()
