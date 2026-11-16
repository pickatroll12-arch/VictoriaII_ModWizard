"""Editor genérico de entidades (wizard §13.5): navegador, pestañas y controles especiales."""

from __future__ import annotations

from .dialogs import MoveGroupDialog, NewEntityDialog, RenameEntityDialog, UnitNamesDialog, UsesDialog
from .editor_page import EntityEditorPage, LocTextsPanel, OtherFieldsPanel, entity_section_factory
from .extras import EndDatePanel, RebelMatrix
from .navigator import EntityNavigator, origin_of_rel
from .unit_panel import UnitPanel

__all__ = ["EndDatePanel", "EntityEditorPage", "EntityNavigator", "LocTextsPanel", "MoveGroupDialog",
           "NewEntityDialog", "OtherFieldsPanel", "RebelMatrix", "RenameEntityDialog", "UnitNamesDialog", "UnitPanel",
           "UsesDialog", "entity_section_factory", "origin_of_rel"]
