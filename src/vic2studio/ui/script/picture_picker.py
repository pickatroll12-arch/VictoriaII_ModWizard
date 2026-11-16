"""Selector de imagen de un evento o una decisión, con importación (wizard §14.5, §14.7).

``PicturePicker`` es el editor del tipo ``Picture``: enseña la miniatura de la imagen actual (o «la del id»
cuando el campo falta en una decisión, H21), lista las de la carpeta y tiene «Importar…», que convierte una
imagen propia al formato del juego y la añade al mod como documento nuevo en la misma transacción que el
cambio del campo.

Formatos, medidos en vanilla: las 286 imágenes de evento son TGA de 521×203 sin comprimir (285 de 24 bits y
1 de 32); las 149 de decisión son DDS de 95×95 sin comprimir y de 32 bits. ``encode_picture`` escribe
exactamente eso: el DDS con ``core.gfx.dds.write_dds`` (A8R8G8B8, D11) y el TGA de 24 bits con Pillow. La
imagen de origen se recorta al centro con la proporción del destino y se reduce; nunca se deforma.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...core.vfs.paths import VPath
from ...i18n import N_, tr, translator
from ..widgets import mark_data


@dataclass(frozen=True)
class PictureSpec:
    """Dónde y cómo se guarda una imagen: carpeta relativa, tamaño en píxeles y extensión."""

    folder: str
    size: tuple[int, int]
    suffix: str

    def rel(self, name: str) -> VPath:
        """La ruta del archivo de la imagen ``name`` (el valor del campo ``picture``)."""
        return VPath.of(f"{self.folder}/{name}{self.suffix}")


EVENT_PICTURE = PictureSpec("gfx/pictures/events", (521, 203), ".tga")
DECISION_PICTURE = PictureSpec("gfx/pictures/decisions", (95, 95), ".dds")
SPECS = {"events": EVENT_PICTURE, "decisions": DECISION_PICTURE}      # por ``Picture.folder``
SUFFIXES = (".tga", ".dds")
UNDO_IMPORT = N_("script_ui.picture.undo_import")


def _open_image(source: Path | bytes):
    """La imagen de ``source`` en RGBA con Pillow; los DDS sin comprimir, con ``core.gfx.dds``."""
    from PIL import Image, UnidentifiedImageError

    data = Path(source).read_bytes() if isinstance(source, (str, Path)) else bytes(source)
    if data[:4] == b"DDS ":
        from ...core.gfx.dds import read_dds

        try:
            return Image.fromarray(read_dds(data).rgba, "RGBA")
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"DDS ilegible: {exc}") from exc
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"no es una imagen legible: {exc}") from exc
    return image.convert("RGBA")


def encode_picture(source: Path | bytes, spec: PictureSpec) -> bytes:
    """Los bytes del archivo del juego para la imagen ``source`` (una ruta o los bytes de un PNG, JPG, BMP,
    TGA o DDS): recorte centrado a la proporción de ``spec.size``, reducción y codificación según
    ``spec.suffix``. ``ValueError`` si no es una imagen legible. No escribe nada."""
    import numpy as np
    from PIL import Image

    image = _open_image(source)
    width, height = spec.size
    ratio = width / height
    src_w, src_h = image.size
    if src_w <= 0 or src_h <= 0:
        raise ValueError("imagen vacía")
    if src_w / src_h > ratio:
        crop_w, crop_h = round(src_h * ratio), src_h
    else:
        crop_w, crop_h = src_w, round(src_w / ratio)
    left, top = (src_w - crop_w) // 2, (src_h - crop_h) // 2
    image = image.crop((left, top, left + crop_w, top + crop_h)).resize((width, height), Image.Resampling.LANCZOS)
    if spec.suffix == ".dds":
        from ...core.gfx.dds import write_dds

        return write_dds(np.asarray(image, dtype=np.uint8))
    out = io.BytesIO()
    image.convert("RGB").save(out, format="TGA", compression=None)
    return out.getvalue()


def picture_bytes(session, rel: VPath) -> bytes | None:
    """Los bytes de la imagen ``rel`` en la vista efectiva: el documento en memoria (una importación sin
    guardar) o el archivo ganador de la VFS. None si no existe."""
    project = getattr(session, "project", None)
    if project is None:
        return None
    handle = project.ws.peek(rel)
    if handle is not None:
        if handle.deleted:
            return None
        if isinstance(handle.model, (bytes, bytearray)) and handle.model:
            return bytes(handle.model)
    try:
        entry = project.vfs.resolve(rel)
        return None if entry is None else project.vfs.read_bytes(entry)
    except (FileNotFoundError, OSError):
        return None


def find_picture(session, folder: str, name: str | None) -> tuple[VPath, bytes] | None:
    """La imagen ``name`` de ``folder`` con cualquiera de sus extensiones (las decisiones admiten TGA, H21)."""
    if not name:
        return None
    base = str(name).strip().replace("\\", "/")
    for suffix in SUFFIXES:
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
    for suffix in SUFFIXES:
        rel = VPath.of(f"{folder}/{base}{suffix}")
        data = picture_bytes(session, rel)
        if data:
            return rel, data
    return None


def image_from_bytes(data: bytes) -> QImage | None:
    """``QImage`` de un TGA, DDS, PNG… (Pillow decodifica; Qt pinta). None si no se puede leer."""
    try:
        image = _open_image(data)
    except ValueError:
        return None
    raw = image.tobytes("raw", "RGBA")
    qimage = QImage(raw, image.width, image.height, image.width * 4, QImage.Format.Format_RGBA8888)
    return qimage.copy()


class PicturePicker(QWidget):
    """Editor de un campo ``Picture``. Misma API mínima que los selectores de ``ui/pickers``."""

    value_committed = Signal(object)             # el nombre elegido (str) o None: sin valor
    imported = Signal(object)                    # VPath del archivo añadido al mod

    def __init__(self, spec: PictureSpec, session=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spec = spec
        self.session = session
        self._value: str | None = None
        self._default: str | None = None
        self._read_only = False
        self._filling = False
        self.setObjectName("picturePicker")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.thumb = QLabel()
        self.thumb.setObjectName("pictureThumb")
        width, height = spec.size
        scale = min(1.0, 160 / width, 90 / height)
        self.thumb.setFixedSize(max(24, int(width * scale)), max(24, int(height * scale)))
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setFrameShape(QLabel.Shape.Box)
        row.addWidget(self.thumb)
        column = QVBoxLayout()
        self.combo = mark_data(QComboBox())
        self.combo.setObjectName("pictureNames")
        self.combo.setEditable(True)
        self.combo.activated.connect(self._on_combo)
        self.combo.lineEdit().editingFinished.connect(self._on_combo)
        column.addWidget(self.combo)
        self.hint = QLabel()
        self.hint.setObjectName("pictureHint")
        self.hint.setWordWrap(True)
        column.addWidget(self.hint)
        self.import_button = QPushButton()
        self.import_button.setObjectName("pictureImport")
        self.import_button.clicked.connect(self._ask_import)
        column.addWidget(self.import_button)
        row.addLayout(column, 1)
        translator().languageChanged.connect(lambda _code: self.retranslate())
        self.retranslate()

    def value(self) -> str | None:
        return self._value

    def set_value(self, value: str | None) -> None:
        self._value = value if value else None
        self._fill()

    def set_default_name(self, name: str | None) -> None:
        """La imagen que usa el juego si el campo falta (el id de la decisión): se enseña atenuada."""
        self._default = name
        self._fill()

    def names(self) -> list[str]:
        """Las imágenes de la carpeta en la vista efectiva (sin extensión), ordenadas."""
        project = getattr(self.session, "project", None)
        if project is None:
            return []
        found = set()
        try:
            for entry in project.vfs.list(self.spec.folder, "*", recursive=False):
                name = entry.rel.name
                if name.lower().endswith(SUFFIXES):
                    found.add(name.rsplit(".", 1)[0])
        except (FileNotFoundError, OSError):
            pass
        prefix = self.spec.folder.lower() + "/"
        for handle in project.ws.dirty() if hasattr(project.ws, "dirty") else ():
            rel = handle.rel
            if rel.key.startswith(prefix) and rel.name.lower().endswith(SUFFIXES) and not handle.deleted:
                found.add(rel.name.rsplit(".", 1)[0])
        return sorted(found, key=str.lower)

    def _fill(self) -> None:
        self._filling = True
        try:
            self.combo.clear()
            self.combo.addItems(self.names())
            self.combo.setEditText(self._value or "")
            self.combo.lineEdit().setPlaceholderText(self._default or "")
        finally:
            self._filling = False
        self._render_thumb()

    def _render_thumb(self) -> None:
        name = self._value or self._default
        found = find_picture(self.session, self.spec.folder, name) if self.session is not None else None
        image = image_from_bytes(found[1]) if found is not None else None
        if image is None:
            self.thumb.setPixmap(QPixmap())
            self.thumb.setText("?" if name else "—")
            self.hint.setText(tr(N_("script_ui.picture.missing"), name=name) if name else
                              tr(N_("script_ui.picture.none")))
            return
        pixmap = QPixmap.fromImage(image).scaled(self.thumb.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation)
        self.thumb.setPixmap(pixmap)
        if self._value is None and self._default:
            self.hint.setText(tr(N_("script_ui.picture.default"), name=self._default))
        else:
            self.hint.setText(tr(N_("script_ui.picture.size"), width=image.width(), height=image.height()))

    def _on_combo(self, *_args) -> None:
        if self._filling or self._read_only:
            return
        text = self.combo.currentText().strip() or None
        if text != self._value:
            self._value = text
            self._render_thumb()
            self.value_committed.emit(text)

    def _ask_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr(N_("script_ui.picture.import_title")), "",
                                              tr(N_("script_ui.picture.import_filter")))
        if path:
            name = Path(path).stem.replace(" ", "_")
            self.import_image(Path(path), name)

    def import_image(self, source: Path, name: str) -> bool:
        """Convierte ``source``, la añade al mod como ``spec.rel(name)`` y confirma ``name`` como valor.
        Dentro de la transacción de quien confirma el campo; False (sin cambios) si no es una imagen."""
        if self._read_only or getattr(self.session, "project", None) is None:
            return False
        try:
            data = encode_picture(source, self.spec)
        except (ValueError, OSError):
            return False
        from ...core.project.binary import put_bytes

        rel = self.spec.rel(name)
        with self.session.edit(UNDO_IMPORT, name=name):
            put_bytes(self.session.project.ws, rel, data)
            self._value = name
            self.value_committed.emit(name)
        self._fill()
        self.imported.emit(rel)
        return True

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = bool(read_only)
        self.combo.setEnabled(not self._read_only)
        self.import_button.setEnabled(not self._read_only)

    def retranslate(self) -> None:
        self.import_button.setText(tr(N_("script_ui.picture.import")))
        self._render_thumb()
