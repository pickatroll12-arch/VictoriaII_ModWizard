"""Sección «Sprites» de la sala Interfaz (wizard §17.3). Iteración 8.

El catálogo de sprites (``SpriteBrowser``) con «Nuevo sprite…» (``NewSpriteDialog``). Doble clic en un uso abre
ese ``.gui`` en Ventanas con el elemento que lo cita elegido. Aloja el esquema ``sprite``: un problema de un
sprite abre esta página con él elegido.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ....i18n import N_
from ...interface.import_dialog import NewSpriteDialog
from ...interface.sprite_browser import SpriteBrowser
from ...pages.base import BasePage


class SpritesPage(BasePage):
    key = "sprites"
    title_key = N_("section.interface.sprites")
    subtitle_key = N_("interface.sprites.subtitle")
    icon_name = "file_image"

    def __init__(self, session, parent: QWidget | None = None):
        self.session = session
        self.dialog: NewSpriteDialog | None = None
        self._stale = False
        super().__init__(parent)
        session.projectOpened.connect(self.reload)
        session.projectClosed.connect(self.reload)
        session.documentsChanged.connect(self._on_documents)
        self.reload()

    def build(self) -> None:
        self.browser = SpriteBrowser(self.session)
        self.browser.new_requested.connect(self.open_new_sprite)
        self.browser.usage_activated.connect(self._open_usage)
        self.body.addWidget(self.browser, 1)

    # --- datos -------------------------------------------------------------------------------------

    def _on_documents(self, rels) -> None:
        if rels is None or any(str(rel).lower().startswith(("interface/", "gfx/")) for rel in rels):
            self.reload()

    def reload(self, *args) -> None:
        if self.session.project is not None and not self.isVisible():
            self._stale = True
            return
        self._stale = False
        self.browser.reload()

    def _ensure_loaded(self) -> None:
        if self._stale:
            self._stale = False
            self.browser.reload()

    def showEvent(self, event) -> None:
        self._ensure_loaded()
        super().showEvent(event)

    def is_busy(self) -> bool:
        return self.browser.is_busy()

    # --- acciones ----------------------------------------------------------------------------------

    def new_sprite_dialog(self) -> NewSpriteDialog:
        """El diálogo «Nuevo sprite» sin abrirlo (las pruebas lo rellenan y llaman a ``create``)."""
        self.dialog = NewSpriteDialog(self.session, self)
        self.dialog.accepted.connect(self._on_created)
        return self.dialog

    def open_new_sprite(self) -> None:
        if self.session.project is None:
            return
        self.new_sprite_dialog().open()

    def _on_created(self) -> None:
        created = self.dialog.created if self.dialog is not None else None
        self._ensure_loaded()
        self.browser.reload()
        if created is not None:
            self.browser.select(created.name)
            self.request_status(N_("interface.new_sprite.done"), name=created.name, file=str(created.gfx))

    def _open_usage(self, rel, line: int) -> None:
        window = self.window()
        show = getattr(window, "show_page", None)
        if show is None:
            return
        try:
            page = show("interface:windows")
        except KeyError:
            return
        page.open_location(rel, line)

    def focus_field(self, ref, field=()) -> bool:
        self._ensure_loaded()
        return self.browser.select(str(getattr(ref, "ident", ref)))
