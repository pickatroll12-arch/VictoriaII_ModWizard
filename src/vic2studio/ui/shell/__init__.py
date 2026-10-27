"""Armazón de la ventana principal (wizard §13.2): salas, índice de secciones, cambios pendientes e historial."""

from .hall import HallPage
from .history_dock import HistoryDock
from .pending_changes import PendingChangesPanel
from .section_rail import RailButton, SectionRail

__all__ = ["HallPage", "HistoryDock", "PendingChangesPanel", "RailButton", "SectionRail"]
