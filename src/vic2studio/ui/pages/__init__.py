"""Páginas que viven como secciones de las salas (wizard §13.1) y la tarjeta de las secciones planificadas.

``ProjectPage`` es la sección «Archivos» de la sala Proyecto y ``LocalisationPage``
la sección «Archivos CSV» de la sala Textos. ``PAGE_KEYS`` es la compatibilidad
con la navegación de la iteración 1: ``MainWindow.page(key)``, ``show_page(key)`` y
``set_current_page(PAGE_KEYS.index(key))`` siguen llevando a esas dos páginas.
"""

from .base import BasePage
from .localisation_page import LocalisationPage
from .planned import PlannedSectionPage, RoadmapCard
from .project_page import ProjectPage

PAGE_CLASSES = (ProjectPage, LocalisationPage)
PAGE_KEYS = tuple(cls.key for cls in PAGE_CLASSES)

__all__ = [
    "BasePage", "LocalisationPage", "PAGE_CLASSES", "PAGE_KEYS", "PlannedSectionPage", "ProjectPage",
    "RoadmapCard",
]
