"""Vista previa de imágenes (TGA, DDS, BMP, PNG, JPG) decodificadas con Pillow en segundo plano.

Pillow se usa también para formatos que Qt lee, porque con archivos dañados
falla limpiamente en vez de llenar el registro de avisos. ``QImage`` (no
``QPixmap``) puede crearse fuera del hilo de la interfaz.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from .. import theme
from ..tasks import TaskRunner
from ..widgets import EmptyState, show_in_stack
from .common import ViewerHeader, format_size

IMAGE_SUFFIXES = frozenset({".tga", ".dds", ".bmp", ".png", ".jpg", ".jpeg"})
MAX_DISPLAY_SIDE = 8192   # las imágenes mayores se reducen para mostrarlas
MAX_UPSCALE = 6.0         # «Ajustar» amplía como mucho 6×, sin suavizar (píxeles nítidos)
CHECKER = 10


@dataclass
class ImageLoad:
    path: Path
    image: QImage
    width: int
    height: int
    mode: str
    format: str
    size: int
    reduced: bool


class ImageLoadError(Exception):
    """Pillow no pudo abrir o decodificar la imagen."""


@dataclass
class ImageFailure:
    """Resultado de una carga fallida esperable (archivo dañado o formato no admitido)."""

    path: Path
    message: str


def try_load_image(path: str | os.PathLike) -> ImageLoad | ImageFailure:
    try:
        return load_image(path)
    except (ImageLoadError, OSError) as exc:
        return ImageFailure(Path(path), str(exc))


def load_image(path: str | os.PathLike) -> ImageLoad:
    path = Path(path)
    try:
        with Image.open(path) as im:
            width, height = im.size
            mode, fmt = im.mode, im.format or path.suffix[1:].upper()
            im.load()
            reduced = max(width, height) > MAX_DISPLAY_SIDE
            if reduced:
                im.thumbnail((MAX_DISPLAY_SIDE, MAX_DISPLAY_SIDE))
            rgba = im.convert("RGBA")
    except Exception as exc:  # noqa: BLE001 - cualquier fallo de Pillow se muestra como mensaje amable
        raise ImageLoadError(f"{type(exc).__name__}: {exc}") from exc
    data = rgba.tobytes("raw", "RGBA")
    image = QImage(data, rgba.width, rgba.height, 4 * rgba.width, QImage.Format.Format_RGBA8888).copy()
    return ImageLoad(path, image, width, height, mode, fmt, path.stat().st_size, reduced)


_checker_pixmap: QPixmap | None = None


def _checker() -> QPixmap:
    """Damero de pergamino para ver las transparencias (cacheado)."""
    global _checker_pixmap
    if _checker_pixmap is None:
        pixmap = QPixmap(2 * CHECKER, 2 * CHECKER)
        pixmap.fill(theme.color("parchment_pale"))
        p = QPainter(pixmap)
        dark = theme.color("parchment_dark")
        p.fillRect(CHECKER, 0, CHECKER, CHECKER, dark)
        p.fillRect(0, CHECKER, CHECKER, CHECKER, dark)
        p.end()
        _checker_pixmap = pixmap
    return _checker_pixmap


class ImageCanvas(QWidget):
    """Dibuja la imagen sobre un damero (transparencias) ajustada o a tamaño real."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._fit = True
        self._viewport = QSize(1, 1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap
        self._relayout()

    def set_fit(self, fit: bool) -> None:
        self._fit = fit
        self._relayout()

    def set_viewport(self, size: QSize) -> None:
        self._viewport = size
        self._relayout()

    def scale(self) -> float:
        if self._pixmap is None or self._pixmap.isNull():
            return 1.0
        if not self._fit:
            return 1.0
        w, h = self._pixmap.width(), self._pixmap.height()
        vw, vh = max(1, self._viewport.width() - 16), max(1, self._viewport.height() - 16)
        return min(vw / w, vh / h, MAX_UPSCALE)

    def _relayout(self) -> None:
        if self._pixmap is None:
            self.setFixedSize(self._viewport)
        else:
            s = self.scale()
            w = max(self._viewport.width(), int(self._pixmap.width() * s) + 16)
            h = max(self._viewport.height(), int(self._pixmap.height() * s) + 16)
            self.setFixedSize(w, h)
        self.update()

    def paintEvent(self, event) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        p = QPainter(self)
        s = self.scale()
        w, h = self._pixmap.width() * s, self._pixmap.height() * s
        target = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        p.setBrushOrigin(target.topLeft())
        p.fillRect(target, QBrush(_checker()))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, s < 1.0)
        p.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
        p.setPen(QColor(74, 50, 20, 200))
        p.drawRect(target.adjusted(-0.5, -0.5, 0.5, 0.5))


class _Scroll(QScrollArea):
    resized = Signal(QSize)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resized.emit(self.viewport().size())


class ImageViewer(QWidget):
    loaded = Signal(object)  # Path

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("imageViewer")
        self._path: Path | None = None
        self._root: Path | None = None
        self._load: ImageLoad | None = None
        self._error: str | None = None
        self._runner = TaskRunner(self)
        self._runner.finished.connect(self._on_loaded)
        self._runner.failed.connect(self._on_failed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.header = ViewerHeader("file_image")
        layout.addWidget(self.header)
        tools = QHBoxLayout()
        tools.setSpacing(4)
        self.fit_button = QToolButton()
        self.fit_button.setObjectName("imageFit")
        self.actual_button = QToolButton()
        self.actual_button.setObjectName("imageActual")
        group = QButtonGroup(self)
        group.setExclusive(True)
        for button in (self.fit_button, self.actual_button):
            button.setCheckable(True)
            group.addButton(button)
            tools.addWidget(button)
        self.fit_button.setChecked(True)
        self.fit_button.toggled.connect(self._on_fit_toggled)
        self.zoom_label = QLabel()
        self.zoom_label.setProperty("role", "caption")
        tools.addWidget(self.zoom_label)
        tools.addStretch(1)
        layout.addLayout(tools)

        self.stack = QStackedWidget()
        self.scroll = _Scroll()
        self.scroll.setObjectName("imageScroll")
        self.scroll.setFrameShape(QFrame.Shape.StyledPanel)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas = ImageCanvas()
        self.scroll.setWidget(self.canvas)
        self.scroll.resized.connect(self._on_viewport_resized)
        self.stack.addWidget(self.scroll)
        self.failure = EmptyState("file_image")
        self.stack.addWidget(self.failure)
        layout.addWidget(self.stack, 1)
        self.retranslate()

    # --- API -----------------------------------------------------------------------------

    def current_path(self) -> Path | None:
        return self._path

    def current_load(self) -> ImageLoad | None:
        return self._load if self._load is not None and self._load.path == self._path else None

    def error(self) -> str | None:
        return self._error

    def is_busy(self) -> bool:
        return self._runner.is_busy()

    def load(self, path: str | os.PathLike, *, root: Path | None = None) -> None:
        path = Path(path)
        self._root = root
        if path == self._path and (self._runner.is_busy() or self.current_load() is not None):
            return
        self._path = path
        self._error = None
        self._load = None
        self.canvas.set_pixmap(None)
        show_in_stack(self.stack, self.scroll)
        self.header.set_file(path)
        self.retranslate()
        self._runner.start(lambda ctx: try_load_image(path))

    def set_fit(self, fit: bool) -> None:
        (self.fit_button if fit else self.actual_button).setChecked(True)

    # --- interno -------------------------------------------------------------------------

    def _on_loaded(self, load: ImageLoad | ImageFailure) -> None:
        if load.path != self._path:
            return
        if isinstance(load, ImageFailure):
            self._show_failure(load.message)
            return
        self._load = load
        self.canvas.set_pixmap(QPixmap.fromImage(load.image))
        self.retranslate()
        self.loaded.emit(load.path)

    def _on_failed(self, failure) -> None:
        self._show_failure(str(failure.exception))

    def _show_failure(self, message: str) -> None:
        self._error = message
        show_in_stack(self.stack, self.failure)
        self.retranslate()
        self.loaded.emit(self._path)

    def _on_fit_toggled(self, fit: bool) -> None:
        self.canvas.set_fit(fit)
        self._retranslate_zoom()

    def _on_viewport_resized(self, size: QSize) -> None:
        self.canvas.set_viewport(size)
        self._retranslate_zoom()

    def _shown_path(self) -> str:
        if self._path is None:
            return ""
        if self._root is not None:
            try:
                return self._path.relative_to(self._root).as_posix()
            except ValueError:
                pass
        return self._path.as_posix()

    def _retranslate_zoom(self) -> None:
        if self.current_load() is None:
            self.zoom_label.setText("")
        else:
            self.zoom_label.setText(tr("image.zoom", percent=round(self.canvas.scale() * 100)))

    def retranslate(self) -> None:
        self.fit_button.setText(tr("image.fit"))
        self.fit_button.setToolTip(tr("image.fit_tooltip"))
        self.actual_button.setText(tr("image.actual"))
        self.actual_button.setToolTip(tr("image.actual_tooltip"))
        load = self.current_load()
        if self._path is None:
            self.header.set_details("")
        elif self._error is not None:
            self.header.set_details(tr("image.details_failed", path=self._shown_path()))
        elif load is None:
            self.header.set_details(tr("viewer.details_loading", path=self._shown_path()))
        else:
            details = tr("image.details", path=self._shown_path(), format=load.format, width=load.width,
                         height=load.height, mode=load.mode, size=format_size(load.size))
            if load.reduced:
                details += " · " + tr("image.reduced", side=load.image.width())
            self.header.set_details(details)
        dds = self._path is not None and self._path.suffix.lower() == ".dds"
        self.failure.set_texts(tr("image.failed_title"),
                               tr("image.failed_dds" if dds else "image.failed_text", error=self._error or ""))
        self._retranslate_zoom()
