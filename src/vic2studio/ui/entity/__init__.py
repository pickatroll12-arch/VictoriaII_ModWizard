"""Editor genérico de entidades (wizard §13.5): navegador, pestañas y controles especiales."""

from __future__ import annotations

from .dialogs import NewEntityDialog, UnitNamesDialog, UsesDialog
from .editor_page import EntityEditorPage, LocTextsPanel, OtherFieldsPanel, entity_section_factory
from .extras import EndDatePanel, RebelMatrix
from .navigator import EntityNavigator, origin_of_rel

__all__ = ["EndDatePanel", "EntityEditorPage", "EntityNavigator", "LocTextsPanel", "NewEntityDialog",
           "OtherFieldsPanel", "RebelMatrix", "UnitNamesDialog", "UsesDialog", "entity_section_factory",
           "origin_of_rel"]
