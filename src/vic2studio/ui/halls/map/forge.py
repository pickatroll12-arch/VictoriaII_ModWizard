"""Sección «Taller de mapas» de la sala Mapa (wizard §18): generar o importar un mapa nuevo y sus recursos.

La página aloja el asistente (``ui/mapforge/wizard.py``) y le pasa la apertura y el cierre del proyecto (para
aprender la instalación efectiva y listar los proyectos del taller guardados en ``.vic2studio/mapforge``).
Reemite ``navigate_requested`` (pantalla 13: «Abrir en el editor de mapa») y ``status_requested``.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from ....i18n import N_
from ...mapforge.wizard import ForgeWizard
from ...pages.base import BasePage


class ForgePage(BasePage):
    key = "forge"
    title_key = N_("section.map.forge")
    subtitle_key = N_("forge.subtitle")
    icon_name = "anvil"
    navigate_requested = Signal(str)

    def __init__(self, session, parent: QWidget | None = None):
        self.session = session
        super().__init__(parent)
        session.projectOpened.connect(self.wizard.on_project_opened)
        session.projectClosed.connect(self.wizard.on_project_closed)
        if session.project is not None:
            self.wizard.on_project_opened(session.project)

    def build(self) -> None:
        self.wizard = ForgeWizard(self.session)
        self.wizard.navigate_requested.connect(self.navigate_requested)
        self.wizard.status_requested.connect(self.status_requested)
        self.body.addWidget(self.wizard, 1)

    def retranslate(self) -> None:
        super().retranslate()
        if hasattr(self, "wizard"):
            self.wizard.retranslate()

    def is_busy(self) -> bool:
        return self.wizard.client.busy
