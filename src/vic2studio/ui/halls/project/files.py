"""Sección «Archivos»: la ``ProjectPage`` de la iteración 1 con insignias de capa en el explorador (wizard §21).

La página no cambia (``MainWindow.page("project")`` la sigue devolviendo con su
API y sus señales): aquí solo se le da el título de la sección y se le instala
``LayerBadgeDelegate`` en la primera columna del explorador, con un
``LayerResolver`` que sigue las rutas del juego y del mod de la propia página.

La iteración 4 añade el editor de texto de los scripts: el botón «Editar» del
visor abre un ``ScriptEditor`` sobre el documento efectivo del ``Workspace``.
Un archivo con cambios sin guardar se abre directamente en el editor, porque el
visor lee el disco y enseñaría la versión vieja.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject

from ....core.vfs import VPath
from ....i18n import N_
from ...pages.project_page import ProjectPage
from ...viewers.script_editor import ScriptEditor
from ...widgets import show_in_stack
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


class ScriptSection(QObject):
    """El ``ScriptEditor`` de la sección y sus conexiones con el visor y el explorador."""

    def __init__(self, page: ProjectPage, session):
        super().__init__(page)
        self.page = page
        self.session = session
        self.editor = ScriptEditor(session, page)
        page.script_editor = self.editor
        page.preview_stack.addWidget(self.editor)
        page.edit_requested.connect(self.open_path)
        page.file_activated.connect(self.open_if_in_memory)
        self.editor.back_requested.connect(self.back_to_viewer)

    def rel_for(self, path: Path) -> VPath | None:
        """``rel`` de una ruta del mod o del juego; fuera de las dos, ``None`` (no se edita)."""
        project = self.session.project
        if project is None or not path.is_file():
            return None
        roots = [project.mod_root]
        if project.game_root is not None:
            roots.append(project.game_root)
        for root in roots:
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            return VPath.of(relative.as_posix())
        return None

    def _show(self, rel: VPath) -> bool:
        # Si el archivo también está en el mod, ``ws.open`` devuelve la copia del mod y la barra lo dice.
        if not self.editor.open_document(rel):
            return False
        show_in_stack(self.page.preview_stack, self.editor)
        return True

    def open_path(self, path) -> None:
        """«Editar» sobre la ``Path`` mostrada en el visor."""
        rel = self.rel_for(Path(path))
        if rel is not None:
            self._show(rel)

    def open_if_in_memory(self, path) -> bool:
        """Un archivo con cambios sin guardar se abre en el editor, no en el visor que lee el disco."""
        rel = self.rel_for(Path(path))
        if rel is not None and self.session.in_memory(rel) is not None:
            return self._show(rel)
        return False

    def back_to_viewer(self) -> None:
        self.editor.commit_pending()
        show_in_stack(self.page.preview_stack, self.page.clausewitz_viewer)
        self.page.clausewitz_viewer.reload_if_changed()


class FilesPage(ProjectPage):
    """La página de Archivos: ``open_file`` desvía al editor lo que solo está en memoria."""

    def open_file(self, path: str | os.PathLike, line: int | None = None, column: int | None = None,
                  tab: str | None = None) -> bool:
        scripts = getattr(self, "scripts", None)
        if scripts is not None and scripts.open_if_in_memory(path):
            return True
        return super().open_file(path, line=line, column=column, tab=tab)


def files_section(session) -> ProjectPage:
    page = FilesPage()
    page.title_key = N_("section.project.files")
    page.subtitle_key = N_("section.project.files.subtitle")
    page.retranslate()
    install_layer_badges(page, session)
    page.scripts = ScriptSection(page, session)
    return page
