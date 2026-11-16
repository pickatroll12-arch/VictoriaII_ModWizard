"""La ventana de un evento compuesta con su ``.gui`` real (wizard §13.8, iteración 8).

``render_event`` usa ``interface/event_country_window.gui`` (o ``event_province_window.gui``) de la vista
efectiva: la ventana, su fondo, la ilustración en ``event_images``, el título y la descripción en sus cajas de
texto con sus fuentes, y un botón por opción con el aspecto de ``Event_<Tipo>_OptionButton``, apilados bajo la
ventana. Si falta el ``.gui``, la ventana o el arte de su fondo (sin juego, o con ``game_art=False``) devuelve
None y la interfaz usa la vista procedural de siempre.
"""

from __future__ import annotations

from collections.abc import Sequence

from PIL import Image

from ..vfs.paths import VPath
from .guimodel import GuiDocument, GuiElement
from .layout import Rect
from .render import GuiRenderer

EVENT_WINDOWS = {
    False: ("interface/event_country_window.gui", "Event_Country_Window", "Event_Country_OptionButton"),
    True: ("interface/event_province_window.gui", "Event_Province_Window", "Event_Province_OptionButton"),
}
OPTION_GAP = 4
SCREEN = (1024, 768)


def _top(document: GuiDocument, name: str) -> GuiElement | None:
    for element in document.windows():
        if element.name.lower() == name.lower():
            return element
    return None


def event_window(renderer: GuiRenderer, source, province: bool):
    """``(documento, ventana, botón de opción)`` del evento o None si no se puede dibujar con el arte real."""
    rel, window_name, button_name = EVENT_WINDOWS[bool(province)]
    if not renderer.game_art:
        return None
    raw = source.document(VPath.of(rel))
    if raw is None:
        return None
    document = GuiDocument(raw)
    window = _top(document, window_name)
    if window is None:
        return None
    background = document.background_of(window)
    sprite = (background.sprite if background is not None else None) or window.sprite
    if renderer.sprite_image(sprite) is None:
        return None                       # sin el fondo, la vista procedural se entiende mejor
    return document, window, _top(document, button_name)


def render_event(renderer: GuiRenderer, source, *, province: bool, title: str, desc: str,
                 options: Sequence[str], picture: Image.Image | None = None,
                 screen: tuple[int, int] = SCREEN) -> Image.Image | None:
    """La ventana del evento con sus textos y sus opciones, recortada a lo que ocupa; None sin arte real."""
    found = event_window(renderer, source, province)
    if found is None:
        return None
    document, window, button = found
    overrides: dict[str, object] = {"title": title, "description": desc}
    if picture is not None:
        overrides["event_images"] = picture
    image, rects = renderer.render(document, window, screen, overrides=overrides)
    box = rects[window.uid]
    bottom = box.bottom
    if button is not None and options:
        size = renderer.sprite_size(button.sprite or "") or (box.w - 40, 30)
        x = box.x + (box.w - size[0]) // 2
        for index, text in enumerate(options):
            rect = Rect(x, box.bottom + OPTION_GAP + index * (size[1] + OPTION_GAP), size[0], size[1])
            picture_ = renderer.element_image(button, size, {button.name.lower(): text})
            if picture_ is not None and rect.bottom <= image.size[1]:
                image.alpha_composite(picture_, (max(0, rect.x), max(0, rect.y)))
                bottom = rect.bottom
    left, top = max(0, box.x), max(0, box.y)
    right, lower = min(image.size[0], box.right), min(image.size[1], max(box.bottom, bottom))
    return image.crop((left, top, right, lower))
