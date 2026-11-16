"""Suite de interfaces: modelo de los ``.gfx`` y ``.gui`` del juego (wizard §17.1).

- ``source``: de dónde se leen los archivos efectivos (``Workspace`` o ``ValidationContext``).
- ``gfxdb``: ``SpriteDB``, el catálogo de sprites de ``interface/*.gfx`` con sus texturas resueltas.
- ``guimodel``: ``GuiDocument`` y ``GuiElement``, vista editable y sin pérdidas de un ``.gui``.
- ``layout``: posición absoluta de cada elemento según su anclaje.
- ``bmfont``: fuentes de mapa de bits (``gfx/fonts/*.fnt`` + ``.tga``).
- ``textures``: carga de DDS y TGA con caché, fotogramas y 9-slice.

Todo es Python puro, sin Qt. El arte del juego solo se lee en tiempo de ejecución, de la instalación del
usuario; nada de él vive en el repositorio.
"""

from __future__ import annotations

from .bmfont import BMFont, BMFontError, Glyph
from .gfxdb import SPRITE_CONTAINERS, Sprite, SpriteDB, normalize_texture, resolve_texture
from .guimodel import ELEMENT_TYPES, HIDDEN_POSITION, GuiDocument, GuiElement, element_path
from .layout import ANCHORS, Rect, anchor_point, layout, local_position
from .source import ContextSource, GuiSource, SnapshotSource, WorkspaceSource
from .textures import TextureCache, TextureError, frame_box, load_image, nine_slice, split_frame

__all__ = [
    "ANCHORS", "BMFont", "BMFontError", "ContextSource", "ELEMENT_TYPES", "Glyph", "GuiDocument", "GuiElement",
    "GuiSource", "HIDDEN_POSITION", "Rect", "SPRITE_CONTAINERS", "SnapshotSource", "Sprite", "SpriteDB", "TextureCache",
    "TextureError", "WorkspaceSource", "anchor_point", "element_path", "frame_box", "layout", "load_image",
    "local_position", "nine_slice", "normalize_texture", "resolve_texture", "split_frame",
]
