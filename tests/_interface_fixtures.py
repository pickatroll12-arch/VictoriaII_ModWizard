"""Datos inventados de la suite de interfaces (iteración 8): ``.gfx``, ``.gui``, texturas y una fuente.

Nada sale del juego: las texturas se generan aquí con colores lisos y degradados, y la fuente es una rejilla de
bloques. Los nombres imitan la forma de los de vanilla (``Event_Country_Window``, ``GFX_…``) para que la vista
previa de eventos los encuentre, pero los valores, las medidas y el arte son propios.

``INTERFACE_FILES`` se pasa como ``game_files`` a ``build_minigame`` (no cambia los recuentos del minijuego).
"""

from __future__ import annotations

import numpy as np

from vic2studio.core.gfx.dds import write_dds
from vic2studio.core.gfx.flags import write_tga

CRLF = "\r\n"


def _crlf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", CRLF)


def gradient(width: int, height: int, start: tuple[int, int, int], end: tuple[int, int, int],
             alpha: int = 255) -> np.ndarray:
    """Degradado vertical RGBA (alto, ancho, 4)."""
    t = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
    a = np.array(start, np.float32)[None, None, :]
    b = np.array(end, np.float32)[None, None, :]
    rgb = np.broadcast_to(a + (b - a) * t, (height, width, 3)).astype(np.uint8)
    out = np.empty((height, width, 4), np.uint8)
    out[..., :3] = rgb
    out[..., 3] = alpha
    return out


def frames_strip(width: int, height: int, colors: list[tuple[int, int, int]]) -> np.ndarray:
    """Tira horizontal de fotogramas, uno por color."""
    return np.concatenate([gradient(width, height, c, tuple(max(0, v - 60) for v in c)) for c in colors], axis=1)


def font_atlas() -> tuple[str, np.ndarray]:
    """Una fuente BMFont inventada: cada carácter ASCII es un bloque de 6×9 con un hueco, en un atlas 128×128."""
    atlas = np.zeros((128, 128, 4), np.uint8)
    lines = ['info face="MgFont" size=10', "common lineHeight=12 base=10 scaleW=128 scaleH=128 pages=1"]
    for index, code in enumerate(range(32, 127)):
        x, y = (index % 16) * 8, (index // 16) * 11
        if code != 32:
            atlas[y:y + 9, x:x + 6, :] = 255
            atlas[y + 3:y + 6, x + 2:x + 4, 3] = 0
        lines.append(f"char id={code} x={x} y={y} width=6 height=9 xoffset=0 yoffset=1 xadvance=7 page=0")
    lines.append("kerning first=65 second=86 amount=-1")
    return "\n".join(lines) + "\n", atlas


FONT_FNT, FONT_ATLAS = font_atlas()

EVENT_GFX = _crlf("""\
spriteTypes = {
\tspriteType = {
\t\tname = "GFX_event_country_bg"
\t\ttexturefile = "gfx\\\\interface\\\\mg_event_bg.dds"
\t}
\tspriteType = {
\t\tname = "GFX_event_no_image"
\t\ttexturefile = "gfx/interface/mg_no_image.tga"
\t}
\tspriteType = {
\t\tname = "GFX_event_country_button"
\t\ttexturefile = "gfx/interface/mg_option.tga"
\t\tnoOfFrames = 3
\t}
\tcorneredTileSpriteType = {
\t\tname = "GFX_mg_panel"
\t\tsize = { x = 64 y = 64 }
\t\ttexturefile = "gfx/interface/mg_panel.dds"
\t\tborderSize = { x = 8 y = 8 }
\t}
\tspriteType = {
\t\tname = "GFX_mg_alt"
\t\ttexturefile = "gfx/interface/mg_alt.tga"
\t}
\tspriteType = {
\t\tname = "GFX_mg_lost"
\t\ttexturefile = "gfx/interface/mg_lost.dds"
\t}
\tspriteType = {
\t\tname = "GFX_mg_twice"
\t\ttexturefile = "gfx/interface/mg_no_image.tga"
\t}
}
bitmapfonts = {
\tbitmapfont = {
\t\tname = "mg_font_black"
\t\tfontname = "mg_font"
\t\tcolor = 0xff201810
\t}
}
""")

# Un segundo .gfx que repite un nombre (como los 13 repetidos de vanilla).
EXTRA_GFX = _crlf("""\
spriteTypes = {
\tSpriteType = {
\t\tName = "GFX_MG_TWICE"
\t\tTextureFile = "gfx/interface/mg_option.tga"
\t}
}
""")

EVENT_GUI = _crlf("""\
guiTypes = {
\twindowType = {
\t\tname = "Event_Country_Window"
\t\tbackGround = "Background"
\t\tposition = { x = -260 y = -250 }
\t\tsize = { x = 480 y = 400 }
\t\tmoveable = 1
\t\tfullScreen = no
\t\tOrientation = "CENTER"

\t\tguiButtonType = {
\t\t\tname = "Background"
\t\t\tquadTextureSprite = "GFX_event_country_bg"
\t\t}
\t\ticonType = {
\t\t\tname = "event_images"
\t\t\tspriteType = "GFX_event_no_image"
\t\t\tposition = { x = 30 y = 90 }
\t\t\tOrientation = "UPPER_LEFT"
\t\t}
\t\tinstantTextBoxType = {
\t\t\tname = "Title"
\t\t\tposition = { x = 10 y = 14 }
\t\t\tfont = "mg_font_black"
\t\t\ttext = "MG_TITLE"
\t\t\tmaxWidth = 460
\t\t\tmaxHeight = 40
\t\t\tformat = centre
\t\t}
\t\tinstantTextBoxType = {
\t\t\tname = "Description"
\t\t\tposition = { x = 24 y = 280 }
\t\t\tfont = "mg_font_black"
\t\t\ttext = "MG_DESC"
\t\t\tmaxWidth = 430
\t\t\tmaxHeight = 90
\t\t}
\t}
\tguiButtonType = {
\t\tname = "Event_Country_OptionButton"
\t\tposition = { x = 240 y = 420 }
\t\tquadTextureSprite = "GFX_event_country_button"
\t\tbuttonText = "MG_OPTION"
\t\tbuttonFont = "mg_font_black"
\t}
}
""")

PANEL_GUI = _crlf("""\
guiTypes = {
\twindowType = {
\t\tname = "mg_panel_window"
\t\tposition = { x = 20 y = 30 }
\t\tsize = { x = 300 y = 200 }
\t\tmoveable = 1
\t\tOrientation = "UPPER_LEFT"
\t\ticonType = {
\t\t\tname = "mg_frame"
\t\t\tspriteType = "GFX_mg_panel"
\t\t\tposition = { x = 0 y = 0 }
\t\t}
\t\ticonType = {
\t\t\tname = "mg_alt_icon"
\t\t\tspriteType = "GFX_mg_alt"
\t\t\tposition = { x = 40 y = 50 }
\t\t\tOrientation = "UPPERL_LEFT"
\t\t}
\t\tguiButtonType = {
\t\t\tname = "mg_close"
\t\t\tposition = { x = -40 y = 8 }
\t\t\tquadTextureSprite = "GFX_event_country_button"
\t\t\torientation = "UPPER_RIGHT"
\t\t}
\t\tguiButtonType = {
\t\t\tname = "mg_ghost"
\t\t\tposition = { x = 10 y = -30 }
\t\t\tquadTextureSprite = "GFX_mg_nowhere"
\t\t\tOrientation = LOWER_LEFT
\t\t}
\t\twindowType = {
\t\t\tname = "mg_inner"
\t\t\tposition = { x = 150 y = 100 }
\t\t\tsize = { x = 100 y = 60 }
\t\t\tinstantTextBoxType = {
\t\t\t\tname = "mg_label"
\t\t\t\tposition = { x = 5 y = 5 }
\t\t\t\tfont = "mg_font_black"
\t\t\t\ttext = "Hola"
\t\t\t\tmaxWidth = 90
\t\t\t\tmaxHeight = 20
\t\t\t}
\t\t}
\t\tpositionType = {
\t\t\tname = "mg_anchor"
\t\t\tposition = { x = 3 y = 4 }
\t\t}
\t}
}
""")


def interface_files() -> dict[str, bytes | str]:
    """Los archivos de interfaz del minijuego: dos ``.gfx``, dos ``.gui``, sus texturas y la fuente."""
    return {
        "interface/mg_event.gfx": EVENT_GFX,
        "interface/mg_extra.gfx": EXTRA_GFX,
        "interface/event_country_window.gui": EVENT_GUI,
        "interface/mg_panel.gui": PANEL_GUI,
        "gfx/interface/mg_event_bg.dds": write_dds(gradient(480, 400, (214, 196, 150), (180, 156, 110))),
        "gfx/interface/mg_no_image.tga": write_tga(gradient(420, 160, (90, 120, 150), (40, 60, 90))),
        "gfx/interface/mg_option.tga": write_tga(frames_strip(200, 30, [(170, 140, 90), (200, 170, 110),
                                                                          (120, 100, 70)])),
        "gfx/interface/mg_panel.dds": write_dds(gradient(64, 64, (60, 50, 40), (20, 16, 12))),
        # Se nombra .tga pero solo existe .dds: la otra extensión (H23).
        "gfx/interface/mg_alt.dds": write_dds(gradient(32, 32, (200, 40, 40), (120, 20, 20))),
        "gfx/fonts/mg_font.fnt": FONT_FNT,
        "gfx/fonts/mg_font.tga": write_tga(FONT_ATLAS),
    }


INTERFACE_FILES = interface_files()
