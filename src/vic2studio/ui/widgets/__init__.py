"""Widgets con la estética victoriana: superficies, marcos, cabecera, navegación e iconos."""

from .banner import EmbossedLabel, HeaderBanner
from .cards import (
    EmptyState,
    FolderChip,
    IconWidget,
    NumeralBadge,
    RibbonBadge,
    RoadmapStrip,
    StatusBadge,
    mark_data,
    rich,
    show_in_stack,
)
from .icons import draw_icon, icon_names, make_icon
from .navigation import NavBar, NavButton
from .ornaments import Divider, Emblem, Medallion, emblem_pixmap
from .surfaces import OrnateFrame, ParchmentCard, TexturedPanel

__all__ = [
    "Divider", "Emblem", "EmbossedLabel", "EmptyState", "FolderChip", "HeaderBanner", "IconWidget",
    "Medallion", "NavBar", "NavButton", "NumeralBadge", "OrnateFrame", "ParchmentCard", "RibbonBadge",
    "RoadmapStrip", "StatusBadge", "TexturedPanel", "draw_icon", "emblem_pixmap", "icon_names",
    "make_icon", "mark_data", "rich", "show_in_stack",
]
