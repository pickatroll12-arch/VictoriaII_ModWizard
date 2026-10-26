"""Vista previa de imágenes (TGA, DDS, BMP, PNG, JPG, GIF) decodificadas con Pillow en segundo plano.

Pillow se usa también para formatos que Qt lee, porque con archivos dañados
falla limpiamente en vez de llenar el registro de avisos. ``QImage`` (no
``QPixmap``) puede crearse fuera del hilo de la interfaz. Volver a seleccionar
una imagen (o ``reload_if_changed``) la recarga si cambió en disco desde que se
mostró (fecha o tamaño). Si el archivo ni siquiera se puede leer (permiso, borrado),
se explica como en el visor Clausewitz y no como un fallo de Pillow, y se reintenta
siempre.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
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

from ...core.cancel import CancelCheck, Cancelled, raise_if_cancelled
from ...i18n import tr
from .. import theme
from ..tasks import POOL_IMAGES, TaskRunner
from ..widgets import EmptyState, show_in_stack
from .common import LOADING_DELAY_MS, ViewerHeader, describe_os_error, file_stamp, format_size

IMAGE_SUFFIXES = frozenset({".tga", ".dds", ".bmp", ".png", ".jpg", ".jpeg", ".gif"})
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
    mtime_ns: int = 0  # con ``size``, permite saber si el archivo cambió desde que se cargó


class ImageLoadError(Exception):
    """Pillow no pudo abrir o decodificar la imagen."""


@dataclass
class ImageFailure:
    """Resultado de una carga fallida esperable: archivo dañado o formato no admitido, o que no se
    pudo leer (``error``, la excepción: ``describe_os_error`` la explica en el idioma de cada momento)."""

    path: Path
    message: str
    stamp: tuple[int, int] | None = None  # ``file_stamp`` antes de intentarlo
    error: OSError | None = None


def try_load_image(path: str | os.PathLike, *, cancelled: CancelCheck = None) -> ImageLoad | ImageFailure:
    stamp = file_stamp(path)
    try:
        return load_image(path, cancelled=cancelled)
    except ImageLoadError as exc:
        return ImageFailure(Path(path), str(exc), stamp)
    except OSError as exc:
        return ImageFailure(Path(path), str(exc), stamp, exc)


def load_image(path: str | os.PathLike, *, cancelled: CancelCheck = None) -> ImageLoad:
    """Decodifica ``path``; si ``cancelled()`` ya es True tras leer la cabecera, lanza ``Cancelled``.

    Un archivo que no se puede abrir lanza su ``OSError``; lo que falle después es de Pillow (``ImageLoadError``).
    """
    path = Path(path)
    stat = path.stat()
    with open(path, "rb") as file:
        try:
            with Image.open(file) as im:
                width, height = im.size
                mode, fmt = im.mode, im.format or path.suffix[1:].upper()
                raise_if_cancelled(cancelled)  # antes de decodificar, que es lo que tarda
                im.load()
                reduced = max(width, height) > MAX_DISPLAY_SIDE
                if reduced:
                    im.thumbnail((MAX_DISPLAY_SIDE, MAX_DISPLAY_SIDE))
                rgba = im.convert("RGBA")
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - cualquier fallo de Pillow se muestra como mensaje amable
            raise ImageLoadError(f"{type(exc).__name__}: {exc}") from exc
    data = rgba.tobytes("raw", "RGBA")
    image = QImage(data, rgba.width, rgba.height, 4 * rgba.width, QImage.Format.Format_RGBA8888).copy()
    return ImageLoad(path, image, width, height, mode, fmt, stat.st_size, reduced, stat.st_mtime_ns)


def _unchanged(load: ImageLoad) -> bool:
    return file_stamp(load.path) == (load.mtime_ns, load.size)


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
        self._read_error: OSError | None = None  # el archivo no se pudo leer (no es cosa de Pillow)
        self._failed_stamp: tuple[int, int] | None = None  # ``file_stamp`` del intento fallido
        self._runner = TaskRunner(self, pool=POOL_IMAGES)
        self._runner.finished.connect(self._on_loaded)
        self._runner.failed.connect(self._on_failed)
        # Al reintentar un fallo, este sigue a la vista hasta que haya respuesta o pase el plazo.
        self._loading_timer = QTimer(self)
        self._loading_timer.setSingleShot(True)
        self._loading_timer.setInterval(LOADING_DELAY_MS)
        self._loading_timer.timeout.connect(self._show_loading)

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
        self._set_tools_enabled(False)
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
        """Carga ``path`` en segundo plano, salvo si ya se muestra (o se está cargando) y no cambió en disco."""
        path = Path(path)
        self._root = root
        if path == self._path:
            load = self.current_load()
            if self._runner.is_busy() or (load is not None and _unchanged(load)):
                self.retranslate()  # la raíz puede ser otra
                return
        retrying = path == self._path and self._error is not None
        self._path = path
        self._load = None
        if retrying:
            self._loading_timer.start()
        else:
            self._show_loading()
        self.header.set_file(path, self._details(), self._shown_path())
        self.retranslate()
        self._runner.start(lambda ctx: try_load_image(path, cancelled=ctx.cancelled))

    def reload_if_changed(self) -> bool:
        """Vuelve a cargar la imagen si cambió en disco desde que se leyó; ``True`` si lo hace.

        Si no se pudo leer la reintenta siempre, como ``ClausewitzViewer.reload_if_changed``; si Pillow
        no pudo decodificarla, solo si cambió.
        """
        if self._path is None or self._runner.is_busy():
            return False
        load = self.current_load()
        if load is not None:
            stamp = load.mtime_ns, load.size
        elif self._error is not None:
            stamp = self._failed_stamp
        else:
            return False
        if self._read_error is None and stamp == file_stamp(self._path):
            return False
        self.load(self._path, root=self._root)
        return True

    def cancel(self) -> None:
        """Detiene la carga en curso sin vaciar el visor; volver a pedir la imagen la recarga."""
        self._runner.cancel()
        self._loading_timer.stop()  # un reintento cancelado deja el fallo, no «cargando…» sin carga

    def set_fit(self, fit: bool) -> None:
        (self.fit_button if fit else self.actual_button).setChecked(True)

    # --- interno -------------------------------------------------------------------------

    def _show_loading(self) -> None:
        """Lienzo vacío mientras carga (de un reintento, solo si tarda más de ``LOADING_DELAY_MS``)."""
        self._loading_timer.stop()
        self._error = self._read_error = None
        self.canvas.set_pixmap(None)
        self._set_tools_enabled(False)
        show_in_stack(self.stack, self.scroll)
        self.retranslate()

    def _on_loaded(self, load: ImageLoad | ImageFailure) -> None:
        if load.path != self._path:
            return
        self._loading_timer.stop()
        if isinstance(load, ImageFailure):
            self._show_failure(load.message, load.stamp, load.error)
            return
        self._error = self._read_error = None
        self._load = load
        show_in_stack(self.stack, self.scroll)
        self.canvas.set_pixmap(QPixmap.fromImage(load.image))
        self._set_tools_enabled(True)
        self.retranslate()
        self.loaded.emit(load.path)

    def _on_failed(self, failure) -> None:
        self._loading_timer.stop()
        self._show_failure(str(failure.exception), file_stamp(self._path))

    def _show_failure(self, message: str, stamp: tuple[int, int] | None, error: OSError | None = None) -> None:
        self._error = message
        self._read_error = error
        self._failed_stamp = stamp
        show_in_stack(self.stack, self.failure)
        self.retranslate()
        self.loaded.emit(self._path)

    def _set_tools_enabled(self, enabled: bool) -> None:
        self.fit_button.setEnabled(enabled)
        self.actual_button.setEnabled(enabled)

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

    def _details(self) -> str:
        load = self.current_load()
        if self._path is None:
            return ""
        if self._read_error is not None:
            return tr("viewer.details_failed", path=self._shown_path())
        if self._error is not None:
            return tr("image.details_failed", path=self._shown_path())
        if load is None:
            return tr("image.details_loading", path=self._shown_path())
        details = tr("image.details", path=self._shown_path(), format=load.format, width=load.width,
                     height=load.height, mode=load.mode, size=format_size(load.size))
        if load.reduced:
            details += " · " + tr("image.reduced", side=max(load.image.width(), load.image.height()))
        return details

    def retranslate(self) -> None:
        self.fit_button.setText(tr("image.fit"))
        self.fit_button.setToolTip(tr("image.fit_tooltip"))
        self.actual_button.setText(tr("image.actual"))
        self.actual_button.setToolTip(tr("image.actual_tooltip"))
        self.header.set_details(self._details(), self._shown_path())
        error, tooltip = self._read_error, ""
        if error is not None:
            reason, detail = describe_os_error(error)
            self.failure.set_texts(tr("viewer.failed_title"), tr("viewer.failed_text", error=reason))
            if self._path is not None:
                tooltip = tr("file_error.detail", path=os.fspath(self._path), detail=detail)
        else:
            dds = self._path is not None and self._path.suffix.lower() == ".dds"
            self.failure.set_texts(tr("image.failed_title"),
                                   tr("image.failed_dds" if dds else "image.failed_text", error=self._error or ""))
        self.failure.setToolTip(tooltip)
        self._retranslate_zoom()
