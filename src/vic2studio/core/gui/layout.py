"""Posición absoluta de los elementos de una ventana (wizard §17.1).

La posición de un elemento es relativa a un punto de anclaje de su padre (o de la pantalla, para una ventana
de primer nivel): ``UPPER_LEFT``, ``UPPER_RIGHT``, ``LOWER_LEFT``, ``LOWER_RIGHT``, ``CENTER``, ``CENTER_UP`` y
``CENTER_DOWN``. Un valor desconocido (``UPPERL_LEFT``, que existe en vanilla) se trata como ``UPPER_LEFT`` y se
anota en ``warnings``. ``local_position`` es la inversa: de una posición absoluta a la ``position`` que hay que
escribir, que es lo que hace el lienzo al arrastrar.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .guimodel import DEFAULT_ORIENTATION, GuiElement

# Fracción del ancho y del alto del padre donde cae cada anclaje.
ANCHORS: dict[str, tuple[float, float]] = {
    "UPPER_LEFT": (0.0, 0.0),
    "UPPER_RIGHT": (1.0, 0.0),
    "LOWER_LEFT": (0.0, 1.0),
    "LOWER_RIGHT": (1.0, 1.0),
    "CENTER": (0.5, 0.5),
    "CENTER_UP": (0.5, 0.0),
    "CENTER_DOWN": (0.5, 1.0),
}
PLACEHOLDER_SIZE = (32, 32)   # un elemento sin tamaño ni sprite conocido: el lienzo lo dibuja discontinuo


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.right and self.y <= y < self.bottom


def known_orientation(orientation: str) -> bool:
    return orientation.upper() in ANCHORS


def anchor_point(orientation: str, parent: Rect) -> tuple[int, int]:
    """Punto absoluto del anclaje ``orientation`` dentro de ``parent`` (desconocido: arriba a la izquierda)."""
    fx, fy = ANCHORS.get(orientation.upper(), ANCHORS[DEFAULT_ORIENTATION])
    return parent.x + int(parent.w * fx), parent.y + int(parent.h * fy)


def local_position(orientation: str, parent: Rect, absolute: tuple[int, int]) -> tuple[int, int]:
    """La ``position`` que deja al elemento en ``absolute`` con ese anclaje y ese padre."""
    ax, ay = anchor_point(orientation, parent)
    return absolute[0] - ax, absolute[1] - ay


def element_size(el: GuiElement, sprite_size: Callable[[str], tuple[int, int] | None] | None) -> tuple[int, int] | None:
    """Tamaño del elemento: el suyo si lo declara; si no, el de su sprite (un fotograma); None si no se sabe."""
    if el.size is not None and (el.size[0] > 0 or el.size[1] > 0):
        return el.size
    if el.sprite and sprite_size is not None:
        return sprite_size(el.sprite)
    return None


def layout(window: GuiElement, screen: tuple[int, int], *,
           sprite_size: Callable[[str], tuple[int, int] | None] | None = None,
           warnings: list[tuple[GuiElement, str]] | None = None) -> dict[int, Rect]:
    """Rectángulo absoluto de ``window`` y de todos sus descendientes, por ``uid``.

    ``screen`` es la resolución (ancho, alto). ``sprite_size(nombre)`` da el tamaño de un fotograma del sprite
    (None si no se conoce: sin juego configurado). Un elemento sin tamaño conocido recibe ``PLACEHOLDER_SIZE``.
    ``warnings`` recoge ``(elemento, orientación)`` de cada anclaje desconocido.
    """
    rects: dict[int, Rect] = {}
    stack: list[tuple[GuiElement, Rect]] = [(window, Rect(0, 0, int(screen[0]), int(screen[1])))]
    while stack:
        element, parent = stack.pop()
        if warnings is not None and not known_orientation(element.orientation):
            warnings.append((element, element.orientation))
        ax, ay = anchor_point(element.orientation, parent)
        width, height = element_size(element, sprite_size) or PLACEHOLDER_SIZE
        rect = Rect(ax + element.position[0], ay + element.position[1], int(width), int(height))
        rects[element.uid] = rect
        # Los hijos se anclan a la caja de su padre; una ventana sin tamaño ancla a su esquina.
        base = rect if element_size(element, sprite_size) is not None else Rect(rect.x, rect.y, 0, 0)
        for child in reversed(element.children):
            stack.append((child, base))
    return rects
