"""Páginas de los cinco módulos, en el orden de la barra de navegación."""

from .base import BasePage
from .countries_page import CountriesPage
from .events_page import EventsPage
from .localisation_page import LocalisationPage
from .map_page import MapPage
from .project_page import ProjectPage

PAGE_CLASSES = (ProjectPage, MapPage, CountriesPage, EventsPage, LocalisationPage)
PAGE_KEYS = tuple(cls.key for cls in PAGE_CLASSES)

__all__ = [
    "BasePage", "CountriesPage", "EventsPage", "LocalisationPage", "MapPage", "PAGE_CLASSES", "PAGE_KEYS",
    "ProjectPage",
]
