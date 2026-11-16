"""Modelo editable y sin pérdidas de un ``.gui`` (wizard §17.1).

Un ``.gui`` es ``guiTypes = { windowType = { name = … position = { x = … y = … } <elementos> } … }``. El
ejecutable busca claves y nombres sin distinguir mayúsculas (``Orientation``/``orientation``, H23), así que el
modelo lee sin mayúsculas y, al escribir, conserva la grafía que haya: mover un elemento cambia solo el texto
de su ``x`` y de su ``y`` (criterio 2 de la iteración 8).

``GuiElement`` es una vista sobre una entrada del CST: no copia nada. Tras deshacer o recargar, el documento es
otro y hay que volver a construir el ``GuiDocument`` (las vistas guardan rutas —``element_path``—, nunca nodos).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..clausewitz.nodes import Block, Document, Entry, Scalar

# Tipos de elemento de vanilla (59 archivos), en minúsculas.
ELEMENT_TYPES = frozenset({
    "windowtype", "guibuttontype", "icontype", "instanttextboxtype", "textboxtype", "checkboxtype",
    "listboxtype", "scrollbartype", "positiontype", "overlappingelementsboxtype", "editboxtype", "shieldtype",
    "eu3dialogtype",
})
HIDDEN_POSITION = (-4000, -4000)           # fuera de cualquier pantalla, sea cual sea el anclaje
CONTAINER_TYPES = frozenset({"windowtype", "eu3dialogtype"})
GUI_CONTAINERS = ("guitypes",)
SPRITE_KEYS = ("spritetype", "quadtexturesprite")
TEXT_KEYS = ("text", "buttontext")
FONT_KEYS = ("font", "buttonfont")
DEFAULT_ORIENTATION = "UPPER_LEFT"


def _scalar(block: Block, key: str) -> Scalar | None:
    entry = block.find(key, ignore_case=True)
    if entry is None or not isinstance(entry.value, Scalar):
        return None
    return entry.value


def _text(block: Block, *keys: str) -> str | None:
    for key in keys:
        value = _scalar(block, key)
        if value is not None:
            return value.text
    return None


def _number(value: Scalar | None, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(float(value.text))
    except ValueError:
        return default


def _pair(block: Block, key: str) -> tuple[int, int] | None:
    entry = block.find(key, ignore_case=True)
    if entry is None or not isinstance(entry.value, Block):
        return None
    return _number(_scalar(entry.value, "x")), _number(_scalar(entry.value, "y"))


@dataclass(eq=False)
class GuiElement:
    """Un elemento de un ``.gui``. ``type`` es la clave en minúsculas; ``uid``, su número de orden en el
    documento (estable mientras no cambie la estructura); ``parent`` es None en los de primer nivel."""

    entry: Entry
    type: str
    name: str
    children: list[GuiElement] = field(default_factory=list)
    position: tuple[int, int] = (0, 0)
    size: tuple[int, int] | None = None
    orientation: str = DEFAULT_ORIENTATION
    sprite: str | None = None
    text: str | None = None
    font: str | None = None
    format: str | None = None
    uid: int = 0
    parent: GuiElement | None = None

    @property
    def block(self) -> Block:
        return self.entry.value

    @property
    def line(self) -> int:
        return self.entry.line or 0

    @property
    def is_container(self) -> bool:
        return self.type in CONTAINER_TYPES

    def walk(self):
        """El elemento y todos sus descendientes, en orden de archivo."""
        stack = [self]
        while stack:
            element = stack.pop()
            yield element
            stack.extend(reversed(element.children))


def element_path(element: GuiElement) -> str:
    """Ruta estable del elemento: ``ventana/hijo/nieto``, con ``#n`` si el nombre se repite entre hermanos."""
    parts: list[str] = []
    current: GuiElement | None = element
    while current is not None:
        siblings = current.parent.children if current.parent is not None else None
        label = current.name or current.type
        if siblings is not None:
            same = [s for s in siblings if (s.name or s.type).lower() == label.lower()]
            if len(same) > 1:
                label = f"{label}#{same.index(current)}"
        parts.append(label)
        current = current.parent
    return "/".join(reversed(parts))


class GuiDocument:
    """Vista de un documento ``.gui``: sus ventanas y elementos, y las ediciones de posición y tamaño.

    Las ediciones tocan el CST (``Block.set``): quien llama las hace dentro de una transacción del
    ``Workspace`` y marca el documento (``ws.touch``).
    """

    def __init__(self, doc: Document) -> None:
        self.doc = doc
        self._count = 0
        self._top: list[GuiElement] = []
        for container in doc.entries:
            if container.key is None or container.key.text.lower() not in GUI_CONTAINERS \
                    or not isinstance(container.value, Block):
                continue
            self._top.extend(self._children(container.value, None))
        self._by_uid = {el.uid: el for top in self._top for el in top.walk()}

    def _children(self, block: Block, parent: GuiElement | None) -> list[GuiElement]:
        found = []
        for entry in block.entries:
            if entry.key is None or not isinstance(entry.value, Block) \
                    or entry.key.text.lower() not in ELEMENT_TYPES:
                continue
            found.append(self._element(entry, parent))
        return found

    def _element(self, entry: Entry, parent: GuiElement | None) -> GuiElement:
        block = entry.value
        kind = entry.key.text.lower()
        size = _pair(block, "size")
        if size is None and kind in ("instanttextboxtype", "textboxtype"):
            width, height = _scalar(block, "maxwidth"), _scalar(block, "maxheight")
            if width is not None or height is not None:
                size = (_number(width), _number(height))
        sprite = _text(block, *SPRITE_KEYS)
        if sprite is None and kind == "listboxtype":
            sprite = _text(block, "background") or None
        self._count += 1
        element = GuiElement(
            entry=entry, type=kind, name=_text(block, "name") or "", position=_pair(block, "position") or (0, 0),
            size=size, orientation=(_text(block, "orientation") or DEFAULT_ORIENTATION).upper(),
            sprite=sprite or None, text=_text(block, *TEXT_KEYS), font=_text(block, *FONT_KEYS),
            format=_text(block, "format"), uid=self._count, parent=parent)
        element.children = self._children(block, element)
        return element

    # --- lectura ------------------------------------------------------------------------------

    def windows(self) -> list[GuiElement]:
        """Los elementos de primer nivel de ``guiTypes`` (ventanas y sueltos), en orden de archivo."""
        return list(self._top)

    def elements(self) -> list[GuiElement]:
        """Todos los elementos, en orden de archivo."""
        return [el for top in self._top for el in top.walk()]

    def by_uid(self, uid: int) -> GuiElement | None:
        return self._by_uid.get(uid)

    def find(self, path: str) -> GuiElement:
        """El elemento de ``path`` (``ventana/hijo``, nombres sin mayúsculas; ``nombre#n`` elige entre
        hermanos con el mismo nombre). ``KeyError`` si no existe."""
        level = self._top
        found: GuiElement | None = None
        for part in path.split("/"):
            label, _, index = part.partition("#")
            same = [el for el in level if (el.name or el.type).lower() == label.lower()]
            position = int(index) if index.isdigit() else 0
            if position >= len(same):
                raise KeyError(path)
            found = same[position]
            level = found.children
        if found is None:
            raise KeyError(path)
        return found

    def background_of(self, window: GuiElement) -> GuiElement | None:
        """El hijo que ``background = "<nombre>"`` señala como fondo de una ventana, si lo hay."""
        name = _text(window.block, "background")
        if not name:
            return None
        for child in window.children:
            if child.name.lower() == name.lower():
                return child
        return None

    # --- edición ------------------------------------------------------------------------------

    def set_position(self, el: GuiElement, x: int, y: int) -> None:
        """Pone ``position = { x = <x> y = <y> }`` cambiando solo los dos números (o creando el bloque)."""
        self._set_pair(el, "position", int(x), int(y))
        el.position = (int(x), int(y))

    def hide(self, el: GuiElement) -> None:
        """«Ocultar» (wizard §17.4): lo deja fuera de la pantalla en lugar de borrarlo, porque el ejecutable
        busca muchos elementos por su nombre. Solo cambia su ``position``."""
        self.set_position(el, *HIDDEN_POSITION)

    def set_size(self, el: GuiElement, w: int, h: int) -> None:
        """Cambia el tamaño: ``maxWidth``/``maxHeight`` en las cajas de texto que los usan; ``size`` en el
        resto."""
        w, h = max(0, int(w)), max(0, int(h))
        block = el.block
        if el.type in ("instanttextboxtype", "textboxtype") and block.find("size", ignore_case=True) is None:
            for key, value in (("maxWidth", w), ("maxHeight", h)):
                existing = block.find(key, ignore_case=True)
                block.set(existing.key.text if existing is not None else key, value,
                          ignore_case=existing is not None)
        else:
            self._set_pair(el, "size", w, h)
        el.size = (w, h)

    def set_orientation(self, el: GuiElement, orientation: str) -> None:
        existing = el.block.find("orientation", ignore_case=True)
        key = existing.key.text if existing is not None else "Orientation"
        value = Scalar(orientation, quoted=existing.value.quoted if existing is not None
                       and isinstance(existing.value, Scalar) else True)
        el.block.set(key, value, ignore_case=existing is not None)
        el.orientation = orientation.upper()

    def set_sprite(self, el: GuiElement, sprite: str) -> None:
        """Cambia el sprite del elemento en la clave que ya use (``spriteType`` o ``quadTextureSprite``)."""
        for key in (*SPRITE_KEYS, "background"):
            existing = el.block.find(key, ignore_case=True)
            if existing is not None and isinstance(existing.value, Scalar):
                existing.value = Scalar(sprite, quoted=existing.value.quoted)
                el.sprite = sprite
                return
        key = "quadTextureSprite" if el.type in ("guibuttontype", "checkboxtype") else "spriteType"
        el.block.set(key, Scalar(sprite, quoted=True))
        el.sprite = sprite

    def set_text(self, el: GuiElement, text: str) -> None:
        self._set_scalar(el, TEXT_KEYS, "buttonText" if el.type in ("guibuttontype", "checkboxtype") else "text",
                         text)
        el.text = text

    def set_font(self, el: GuiElement, font: str) -> None:
        self._set_scalar(el, FONT_KEYS, "buttonFont" if el.type in ("guibuttontype", "checkboxtype") else "font",
                         font)
        el.font = font

    def _set_scalar(self, el: GuiElement, keys: tuple[str, ...], new_key: str, value: str) -> None:
        for key in keys:
            existing = el.block.find(key, ignore_case=True)
            if existing is not None and isinstance(existing.value, Scalar):
                existing.value = Scalar(value, quoted=existing.value.quoted or not value)
                return
        el.block.set(new_key, Scalar(value, quoted=True))

    def _set_pair(self, el: GuiElement, key: str, x: int, y: int) -> None:
        existing = el.block.find(key, ignore_case=True)
        if existing is None or not isinstance(existing.value, Block):
            el.block.set(key, Block.from_pairs([("x", x), ("y", y)]))
            return
        inner = existing.value
        for name, value in (("x", x), ("y", y)):
            current = inner.find(name, ignore_case=True)
            if current is None:
                inner.set(name, value)
            elif _number(current.value if isinstance(current.value, Scalar) else None, value + 1) != value:
                current.value = value
