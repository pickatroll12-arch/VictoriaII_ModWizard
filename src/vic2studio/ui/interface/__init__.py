"""Suite de interfaces en la interfaz (wizard §17.2, §17.3, iteración 8).

- ``gui_canvas``: el lienzo de una ventana ``.gui`` con sus elementos, arrastrables y redimensionables.
- ``gui_tree``: la jerarquía de la ventana, sincronizada con el lienzo.
- ``sprite_browser``: la rejilla de sprites con buscador, filtro por archivo, usos y repetidos.
- ``import_dialog``: «Nuevo sprite» desde una imagen propia.
- ``picture_manager``: imágenes de eventos, decisiones, banderas, tecnologías, noticias y pantallas de carga.

Aquí, lo común: el origen de los archivos (el ``Workspace`` vivo), el renderizador con su caché (se rehace
cuando cambia algún ``.gfx``, ``.gui`` o archivo de ``gfx/``, o las ``replace_path`` de la vista) y la conversión de
imágenes de Pillow a Qt.
``VIC2STUDIO_NO_GAME_ART`` (lo pone ``tools/screenshot.py --no-game-art``) apaga el arte del juego.
"""

from __future__ import annotations

import os

from PySide6.QtGui import QImage, QPixmap

ART_FOLDERS = ("interface/", "gfx/")


def game_art_allowed() -> bool:
    """False si las capturas piden no usar arte del juego (D12)."""
    return not os.environ.get("VIC2STUDIO_NO_GAME_ART")


def source_of(session):
    """``core.gui.WorkspaceSource`` del proyecto abierto, o None."""
    project = getattr(session, "project", None)
    if project is None:
        return None
    from ...core.gui import WorkspaceSource

    return WorkspaceSource(project.ws)


class RendererCache:
    """El ``GuiRenderer`` de la sesión, rehecho solo cuando cambia algo de ``interface/`` o ``gfx/`` o las
    ``replace_path`` de la VFS (que pueden ocultar los ``.gfx`` del juego sin que se nombre ninguno).

    Las ``replace_path`` se comparan al pedirlo, no con una señal: las salas que lo piden al recibir
    ``replacePathsChanged`` se conectaron antes que la caché y lo pedirían antes de que se enterase."""

    def __init__(self, session) -> None:
        self.session = session
        self._renderer = None
        self._project = None
        self._replaced = None
        if hasattr(session, "documentsChanged"):
            session.documentsChanged.connect(self._on_documents)
        if hasattr(session, "projectClosed"):
            session.projectClosed.connect(self.invalidate)

    def _on_documents(self, rels=None) -> None:
        if rels is None or any(str(rel).lower().startswith(ART_FOLDERS) for rel in rels):
            self.invalidate()

    def invalidate(self, *_args) -> None:
        self._renderer = None

    def get(self, *, game_art: bool | None = None):
        project = getattr(self.session, "project", None)
        if project is None:
            return None
        allowed = game_art_allowed() if game_art is None else game_art
        replaced = getattr(getattr(project, "vfs", None), "replace_paths", None)
        if self._renderer is None or self._project is not project or self._renderer.game_art != allowed \
                or self._replaced != replaced:
            from ...core.gui.render import GuiRenderer

            self._renderer = GuiRenderer.from_source(source_of(self.session), game_art=allowed)
            self._project = project
            self._replaced = replaced
        return self._renderer


def renderer_of(session, *, game_art: bool | None = None):
    """El renderizador compartido de la sesión (se crea la primera vez)."""
    cache = getattr(session, "_gui_renderer_cache", None)
    if cache is None:
        cache = RendererCache(session)
        try:
            session._gui_renderer_cache = cache
        except AttributeError:
            pass
    return cache.get(game_art=game_art)


def to_qimage(image) -> QImage:
    """``QImage`` (copia propia) de una imagen de Pillow."""
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    return QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()


def to_pixmap(image) -> QPixmap:
    return QPixmap.fromImage(to_qimage(image))
