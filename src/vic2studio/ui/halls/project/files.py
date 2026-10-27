"""Sección «Archivos»: la ``ProjectPage`` de la iteración 1 con insignias de capa en el explorador (wizard §21).

La página no cambia (``MainWindow.page("project")`` la sigue devolviendo con su
API y sus señales): aquí solo se le da el título de la sección y se le instala
``LayerBadgeDelegate`` en la primera columna del explorador, con un
``LayerResolver`` que sigue las rutas del juego y del mod de la propia página.
"""

from __future__ import annotations

from PySide6.QtCore import QObject

from ....i18n import N_
from ...pages.project_page import ProjectPage
from ...widgets.layer_badge import LayerBadgeDelegate, LayerResolver


class LayerBadges(QObject):
    """Las insignias de una ``ProjectPage``: hija de la página, así que sus conexiones mueren con ella."""

    def __init__(self, page: ProjectPage, session=None):
        super().__init__(page)
        self.page = page
        self.resolver = LayerResolver(page.game_path(), page.mod_path())
        self.delegate = LayerBadgeDelegate(self.layer_for, page.tree)
        page.tree.setItemDelegateForColumn(0, self.delegate)
        page.game_path_changed.connect(self.refresh)
        page.mod_path_changed.connect(self.refresh)
        page.fs.directoryLoaded.connect(self.forget)
        if session is not None:
            session.saved.connect(self.forget)  # un guardado puede haber copiado archivos del juego al mod

    def layer_for(self, index):
        return self.resolver.layer_of(self.page.model.file_path(index)) if index.isValid() else None

    def refresh(self, *args) -> None:
        self.resolver.set_roots(self.page.game_path(), self.page.mod_path())
        self.page.tree.viewport().update()

    def forget(self, *args) -> None:
        self.resolver.invalidate()
        self.page.tree.viewport().update()


def install_layer_badges(page: ProjectPage, session=None) -> LayerResolver:
    """Insignias J / M / M⊃J en el explorador de ``page``; devuelve el resolvedor (también en ``page.layers``)."""
    page.layer_badges = LayerBadges(page, session)
    page.layers = page.layer_badges.resolver
    return page.layers


def files_section(session) -> ProjectPage:
    page = ProjectPage()
    page.title_key = N_("section.project.files")
    page.subtitle_key = N_("section.project.files.subtitle")
    page.retranslate()
    install_layer_badges(page, session)
    return page
