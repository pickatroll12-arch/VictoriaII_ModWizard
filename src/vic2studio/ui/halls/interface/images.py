"""Sección «Imágenes y banderas» de la sala Interfaz (wizard §17.3). Iteración 8.

El gestor de imágenes (``PictureManager``): las familias de eventos, decisiones, banderas, tecnologías, noticias
y pantallas de carga, cada una con su tamaño esperado, y «Importar…» con encuadre y vista previa.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ....i18n import N_
from ...interface.picture_manager import PictureManager
from ...pages.base import BasePage
from ...session import replace_paths_touch


class ImagesPage(BasePage):
    key = "images"
    title_key = N_("section.interface.images")
    subtitle_key = N_("interface.images.subtitle")
    icon_name = "flag"

    def __init__(self, session, parent: QWidget | None = None):
        self.session = session
        self._stale = False
        super().__init__(parent)
        session.projectOpened.connect(self.reload)
        session.projectClosed.connect(self.reload)
        session.documentsChanged.connect(self._on_documents)
        session.replacePathsChanged.connect(self._on_replace_paths)
        self.reload()

    def build(self) -> None:
        self.manager = PictureManager(self.session)
        self.manager.imported.connect(self._on_imported)
        self.body.addWidget(self.manager, 1)

    def _on_documents(self, rels) -> None:
        if rels is None or any(str(rel).lower().startswith("gfx/") for rel in rels):
            self.reload()

    def _on_replace_paths(self, folders) -> None:
        """Otras ``replace_path``: las imágenes del juego de una familia dejan de contar, o vuelven."""
        if replace_paths_touch(folders, "gfx") and not self.session.named_in_this_flush("gfx"):
            self.reload()

    def reload(self, *args) -> None:
        if self.session.project is not None and not self.isVisible():
            self._stale = True
            return
        self._stale = False
        self.manager.reload()

    def _ensure_loaded(self) -> None:
        if self._stale:
            self._stale = False
            self.manager.reload()

    def showEvent(self, event) -> None:
        self._ensure_loaded()
        super().showEvent(event)

    def is_busy(self) -> bool:
        return self.manager.is_busy()

    def _on_imported(self, rel) -> None:
        self.request_status(N_("interface.images.done"), file=str(rel))
