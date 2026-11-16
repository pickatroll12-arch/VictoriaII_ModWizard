"""Taller de banderas (wizard §14.2, paso 2 del asistente y pestaña «Banderas» de la ficha).

Importa una imagen (PNG, JPG o TGA) común o una por variante (``""``, ``_communist``, ``_fascist``,
``_monarchy``, ``_republic``), la encuadra (cubrir, contener o estirar, con punto focal) y enseña las 5 banderas
tal como quedarán. ``flags()`` da los 5 TGA de 93×64 y 32 bits con origen abajo a la izquierda
(``core.gfx.flags.make_flag_set``), ya releídos con Pillow. Sin imagen, una bandera de tres franjas con el color
del país (``default_flag``), para que un país nuevo nunca se quede sin bandera.
"""

from __future__ import annotations

from PIL import Image
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QVBoxLayout, QWidget,
)

from ...core.gfx.flags import FIT_MODES, FLAG_SIZE, FLAG_SUFFIXES, fit_flag, make_flag_set
from ...i18n import N_, tr, translator

MODE_LABELS = {"cover": N_("countries.flags.mode.cover"), "contain": N_("countries.flags.mode.contain"),
               "stretch": N_("countries.flags.mode.stretch")}
SUFFIX_LABELS = {"": N_("countries.flags.variant.base"), "_communist": N_("countries.flags.variant.communist"),
                 "_fascist": N_("countries.flags.variant.fascist"), "_monarchy": N_("countries.flags.variant.monarchy"),
                 "_republic": N_("countries.flags.variant.republic")}
# Variaciones de la bandera por defecto para cada gobierno (franjas horizontales o verticales y un tono).
_DEFAULT_SHADES = {"": 1.0, "_communist": 0.75, "_fascist": 0.55, "_monarchy": 1.0, "_republic": 1.0}


def default_flag(color, suffix: str = "") -> Image.Image:
    """Bandera de tres franjas (color · blanco · color) del tamaño del juego; verticales en ``_republic``."""
    width, height = FLAG_SIZE
    shade = _DEFAULT_SHADES.get(suffix, 1.0)
    r, g, b = (max(0, min(255, int(c * shade))) for c in color)
    image = Image.new("RGBA", FLAG_SIZE, (r, g, b, 255))
    if suffix == "_communist":
        image.paste((200, 20, 20, 255), (0, 0, width, height))
        image.paste((r, g, b, 255), (6, 6, 30, 30))
        return image
    if suffix == "_republic":
        image.paste((245, 245, 240, 255), (width // 3, 0, 2 * width // 3, height))
    else:
        image.paste((245, 245, 240, 255), (0, height // 3, width, 2 * height // 3))
    if suffix == "_monarchy":
        image.paste((212, 175, 55, 255), (width // 2 - 6, height // 2 - 6, width // 2 + 6, height // 2 + 6))
    return image


def to_pixmap(image: Image.Image, scale: int = 1) -> QPixmap:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()
    pixmap = QPixmap.fromImage(qimage)
    if scale != 1:
        pixmap = pixmap.scaled(rgba.width * scale, rgba.height * scale, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
    return pixmap


class FlagStudio(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.color = (128, 128, 128)
        self.images: dict[str, Image.Image] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        controls = QFormLayout()
        row = QHBoxLayout()
        self.import_button = QPushButton()
        self.import_button.setObjectName("flagImport")
        self.import_button.clicked.connect(self.ask_image)
        row.addWidget(self.import_button)
        self.per_variant = QCheckBox()
        self.per_variant.setObjectName("flagPerVariant")
        self.per_variant.toggled.connect(self._on_per_variant)
        row.addWidget(self.per_variant)
        self.variant_combo = QComboBox()
        self.variant_combo.setObjectName("flagVariant")
        for suffix in FLAG_SUFFIXES:
            self.variant_combo.addItem("", suffix)
        self.variant_combo.setEnabled(False)
        row.addWidget(self.variant_combo)
        self.clear_button = QPushButton()
        self.clear_button.setObjectName("flagClear")
        self.clear_button.clicked.connect(self.clear)
        row.addWidget(self.clear_button)
        row.addStretch(1)
        outer.addLayout(row)
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("flagMode")
        for mode in FIT_MODES:
            self.mode_combo.addItem("", mode)
        self.mode_combo.currentIndexChanged.connect(self.refresh)
        self.focus_x = QSlider(Qt.Orientation.Horizontal)
        self.focus_y = QSlider(Qt.Orientation.Horizontal)
        for slider in (self.focus_x, self.focus_y):
            slider.setRange(0, 100)
            slider.setValue(50)
            slider.valueChanged.connect(self.refresh)
        self.mode_label, self.fx_label, self.fy_label = QLabel(), QLabel(), QLabel()
        controls.addRow(self.mode_label, self.mode_combo)
        controls.addRow(self.fx_label, self.focus_x)
        controls.addRow(self.fy_label, self.focus_y)
        outer.addLayout(controls)
        grid = QGridLayout()
        self.previews: dict[str, QLabel] = {}
        self.preview_names: dict[str, QLabel] = {}
        for column, suffix in enumerate(FLAG_SUFFIXES):
            picture = QLabel()
            picture.setObjectName(f"flagPreview{suffix or '_base'}")
            picture.setFixedSize(FLAG_SIZE[0] + 4, FLAG_SIZE[1] + 4)
            picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
            picture.setStyleSheet("border: 1px solid #8a6d3b;")
            name = QLabel()
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(picture, 0, column)
            grid.addWidget(name, 1, column)
            self.previews[suffix] = picture
            self.preview_names[suffix] = name
        outer.addLayout(grid)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("flagNote")
        outer.addWidget(self.note)
        translator().languageChanged.connect(self._on_language)
        self.retranslate()
        self.refresh()

    def _on_language(self, code: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self.import_button.setText(tr(N_("countries.flags.import")))
        self.per_variant.setText(tr(N_("countries.flags.per_variant")))
        self.clear_button.setText(tr(N_("countries.flags.clear")))
        self.mode_label.setText(tr(N_("countries.flags.mode")))
        self.fx_label.setText(tr(N_("countries.flags.focus_x")))
        self.fy_label.setText(tr(N_("countries.flags.focus_y")))
        for i in range(self.mode_combo.count()):
            self.mode_combo.setItemText(i, tr(MODE_LABELS[self.mode_combo.itemData(i)]))
        for i in range(self.variant_combo.count()):
            self.variant_combo.setItemText(i, tr(SUFFIX_LABELS[self.variant_combo.itemData(i)]))
        for suffix, label in self.preview_names.items():
            label.setText(tr(SUFFIX_LABELS[suffix]))
        self.note.setText(tr(N_("countries.flags.note")))

    def _on_per_variant(self, on: bool) -> None:
        self.variant_combo.setEnabled(on)

    def set_color(self, color) -> None:
        self.color = tuple(int(c) for c in color)
        self.refresh()

    def mode(self) -> str:
        return self.mode_combo.currentData() or "cover"

    def focus(self) -> tuple[float, float]:
        return self.focus_x.value() / 100, self.focus_y.value() / 100

    def set_image(self, image: Image.Image, suffix: str | None = None) -> None:
        """La imagen común (``suffix`` None) o la de una variante."""
        if suffix is None:
            self.images = {"": image}
        else:
            self.images[suffix] = image
        self.refresh()

    def ask_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr(N_("countries.flags.import")), "",
                                              tr(N_("countries.flags.filter")))
        if not path:
            return
        try:
            with Image.open(path) as source:
                source.load()
                image = source.copy()
        except (OSError, ValueError):
            self.note.setText(tr(N_("countries.flags.unreadable"), file=path))
            return
        self.set_image(image, self.variant_combo.currentData() if self.per_variant.isChecked() else None)

    def clear(self) -> None:
        self.images = {}
        self.refresh()

    def source_for(self, suffix: str) -> Image.Image:
        if suffix in self.images:
            return self.images[suffix]
        if "" in self.images and not self.per_variant.isChecked():
            return self.images[""]
        if "" in self.images:
            return self.images[""]
        return default_flag(self.color, suffix)

    def fitted(self, suffix: str) -> Image.Image:
        return fit_flag(self.source_for(suffix), mode=self.mode(), focus=self.focus())

    def refresh(self, *args) -> None:
        for suffix, label in self.previews.items():
            label.setPixmap(to_pixmap(self.fitted(suffix)))
        self.changed.emit()

    def flags(self) -> dict[str, bytes]:
        """Los 5 TGA listos para escribir (verificados con Pillow)."""
        return make_flag_set({suffix: self.source_for(suffix) for suffix in FLAG_SUFFIXES}, mode=self.mode(),
                             focus=self.focus())
