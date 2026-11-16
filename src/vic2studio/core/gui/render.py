"""Vista previa de una ventana ``.gui`` en una imagen (wizard §17.1, §17.2): el renderizador sin Qt.

``GuiRenderer`` compone una ventana con sus sprites (fotograma 0, 9-slice de los ``corneredTileSpriteType``), sus
textos con las fuentes de mapa de bits del juego (``bitmapfonts`` de los ``.gfx`` → ``gfx/fonts/<fontname>.fnt`` +
``.tga``) y, donde falta el arte, el **estilo procedural**: un panel de pergamino para las ventanas, un recuadro
discontinuo con el nombre para los elementos sin imagen y la fuente de Pillow para los textos. Sin juego
configurado (``game_art=False``) todo es procedural: es lo que usan las capturas (``--no-game-art``) y las pruebas,
y garantiza que nada del arte de Paradox acabe en el repositorio.

``overrides`` sustituye el contenido de un elemento por su nombre (sin mayúsculas): un texto (el título de un
evento) o una imagen (su ilustración). Lo usa la vista previa de eventos.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

from ..clausewitz.nodes import Block, Scalar
from ..vfs.paths import VPath
from .bmfont import BMFont, BMFontError
from .gfxdb import GFX_FOLDER, GFX_PATTERN, Sprite, SpriteDB
from .guimodel import GuiDocument, GuiElement
from .layout import Rect, element_size, layout
from .source import GuiSource
from .textures import TextureCache, nine_slice, split_frame

FONT_FOLDER = "gfx/fonts"
TEXT_TYPES = frozenset({"instanttextboxtype", "textboxtype", "editboxtype"})
BUTTON_TYPES = frozenset({"guibuttontype", "checkboxtype"})
SCREENS = ((1024, 768), (1280, 720), (1920, 1080))

# Colores del estilo procedural (pergamino y tinta, como el resto del Studio).
PARCHMENT = (226, 210, 170, 255)
PARCHMENT_EDGE = (120, 92, 52, 255)
INK = (52, 38, 20, 255)
PLACEHOLDER = (140, 110, 70, 255)
SCREEN_BACK = (28, 32, 38, 255)


@dataclass(frozen=True)
class FontDef:
    """Un ``bitmapfont`` de los ``.gfx``: su nombre, el archivo de ``gfx/fonts`` y su color ARGB."""

    name: str
    fontname: str
    color: tuple[int, int, int]
    color_codes: Mapping[str, tuple[int, int, int]] = field(default_factory=dict)


def _argb(text: str | None) -> tuple[int, int, int]:
    try:
        value = int(str(text), 0)
    except (TypeError, ValueError):
        return (255, 255, 255)
    return (value >> 16) & 255, (value >> 8) & 255, value & 255


def font_defs(source: GuiSource) -> dict[str, FontDef]:
    """Los ``bitmapfont`` de todos los ``interface/*.gfx``, por nombre sin mayúsculas (gana el último)."""
    found: dict[str, FontDef] = {}
    for rel in source.rels(GFX_FOLDER, GFX_PATTERN):
        doc = source.document(rel)
        if doc is None:
            continue
        for container in doc.entries:
            if container.key is None or container.key.text.lower() != "bitmapfonts" \
                    or not isinstance(container.value, Block):
                continue
            for entry in container.value.entries:
                if entry.key is None or entry.key.text.lower() != "bitmapfont" or not isinstance(entry.value, Block):
                    continue
                block = entry.value
                name = block.get_text("name", None, ignore_case=True)
                fontname = block.get_text("fontname", None, ignore_case=True)
                if not name or not fontname:
                    continue
                codes: dict[str, tuple[int, int, int]] = {}
                codes_entry = block.find("colorcodes", ignore_case=True)
                if codes_entry is not None and isinstance(codes_entry.value, Block):
                    for code in codes_entry.value.entries:
                        if code.key is None or not isinstance(code.value, Block):
                            continue
                        values = []
                        for item in code.value.entries:
                            if item.key is None and isinstance(item.value, Scalar):
                                try:
                                    values.append(int(float(item.value.text)))
                                except ValueError:
                                    pass
                        if len(values) >= 3:
                            codes[code.key.text] = (values[0], values[1], values[2])
                found[name.lower()] = FontDef(name, fontname, _argb(block.get_text("color", None, ignore_case=True)),
                                              codes)
    return found


class FontLibrary:
    """Fuentes de mapa de bits por nombre de ``bitmapfont`` (o de archivo), cargadas al pedirlas."""

    def __init__(self, source: GuiSource, defs: Mapping[str, FontDef] | None = None) -> None:
        self.source = source
        self.defs = dict(defs if defs is not None else font_defs(source))
        self._fonts: dict[str, BMFont | None] = {}

    def definition(self, name: str) -> FontDef:
        return self.defs.get(name.lower()) or FontDef(name, name, (255, 255, 255))

    def get(self, name: str) -> BMFont | None:
        fontname = self.definition(name).fontname
        key = fontname.lower()
        if key not in self._fonts:
            self._fonts[key] = self._load(fontname)
        return self._fonts[key]

    def _load(self, fontname: str) -> BMFont | None:
        base = fontname.replace("\\", "/").rsplit("/", 1)[-1]
        fnt = self.source.read(VPath.of(f"{FONT_FOLDER}/{base}.fnt"))
        atlas_bytes = self.source.read(VPath.of(f"{FONT_FOLDER}/{base}.tga"))
        if fnt is None or atlas_bytes is None:
            return None
        from .textures import TextureError, load_image

        try:
            return BMFont.load(fnt.decode("cp1252", errors="replace"), load_image(atlas_bytes))
        except (BMFontError, TextureError):
            return None


def _default_font(size: int = 12):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                     # Pillow < 10.1 no admite tamaño
        return ImageFont.load_default()


class GuiRenderer:
    """Compone ventanas de un ``.gui``. ``game_art=False`` dibuja todo en estilo procedural."""

    def __init__(self, sprites: SpriteDB, textures: TextureCache, fonts: FontLibrary | None = None, *,
                 game_art: bool = True, text_of: Callable[[str], str] | None = None) -> None:
        self.sprites = sprites
        self.textures = textures
        self.fonts = fonts
        self.game_art = game_art
        self.text_of = text_of

    @classmethod
    def from_source(cls, source: GuiSource, *, game_art: bool = True,
                    text_of: Callable[[str], str] | None = None) -> GuiRenderer:
        return cls(SpriteDB.build(source), TextureCache(source.read), FontLibrary(source), game_art=game_art,
                   text_of=text_of)

    # --- medidas -------------------------------------------------------------------------------

    def sprite_image(self, name: str | None, frame: int = 0) -> Image.Image | None:
        """Un fotograma del sprite ``name`` (None si no existe, no tiene textura o no hay arte del juego)."""
        if not name or not self.game_art:
            return None
        sprite = self.sprites.get(name)
        if sprite is None or sprite.resolved is None:
            return None
        image = self.textures.get(sprite.resolved)
        if image is None:
            return None
        return split_frame(image, sprite.frames, frame)

    def sprite_size(self, name: str) -> tuple[int, int] | None:
        """Tamaño de un fotograma del sprite (el ``size`` declarado en un ``corneredTile``)."""
        sprite = self.sprites.get(name)
        if sprite is None:
            return None
        declared = _declared_size(sprite)
        if declared is not None:
            return declared
        image = self.sprite_image(name)
        return None if image is None else image.size

    def layout(self, window: GuiElement, screen: tuple[int, int],
               warnings: list | None = None) -> dict[int, Rect]:
        return layout(window, screen, sprite_size=self.sprite_size, warnings=warnings)

    # --- dibujo --------------------------------------------------------------------------------

    def element_image(self, element: GuiElement, size: tuple[int, int],
                      overrides: Mapping[str, object] | None = None) -> Image.Image | None:
        """La imagen de un elemento a ``size`` (sin sus hijos); None si no dibuja nada (un contenedor sin fondo,
        una posición)."""
        width, height = max(1, size[0]), max(1, size[1])
        override = (overrides or {}).get(element.name.lower()) if element.name else None
        if isinstance(override, Image.Image):
            return override.convert("RGBA").resize((width, height), Image.Resampling.LANCZOS)
        if element.type == "positiontype":
            return None
        if element.type in TEXT_TYPES:
            text = override if isinstance(override, str) else self._text(element.text)
            return self.text_image(text, element.font, (width, height), element.format or "left")
        image = self._sprite_for(element, (width, height))
        if image is None and element.is_container:
            return None
        if element.type in BUTTON_TYPES:
            text = override if isinstance(override, str) else self._text(element.text)
            if image is None:
                image = self.placeholder((width, height), element.name if not text else "")
            if text:
                label = self.text_image(text, element.font, image.size, "centre")
                image = image.copy()
                image.alpha_composite(label, (0, max(0, (image.size[1] - label.size[1]) // 2)))
            return image
        return image if image is not None else self.placeholder((width, height), element.name)

    def _sprite_for(self, element: GuiElement, size: tuple[int, int]) -> Image.Image | None:
        if not element.sprite:
            return None
        frame = 0
        entry = element.block.find("frame", ignore_case=True)
        if entry is not None and isinstance(entry.value, Scalar):
            try:
                frame = max(0, int(entry.value.text) - 1)
            except ValueError:
                frame = 0
        image = self.sprite_image(element.sprite, frame)
        if image is None:
            return None
        sprite = self.sprites.get(element.sprite)
        if sprite is not None and sprite.kind == "corneredtilespritetype" and sprite.border is not None:
            return nine_slice(image, sprite.border, size)
        if image.size != size and element.size is not None:
            return image.resize(size, Image.Resampling.LANCZOS)
        return image

    def _text(self, raw: str | None) -> str:
        if not raw:
            return ""
        return self.text_of(raw) if self.text_of is not None else raw

    def text_image(self, text: str, font: str | None, size: tuple[int, int], align: str) -> Image.Image:
        width, height = max(1, size[0]), max(1, size[1])
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        if not text:
            return canvas
        bitmap = self.fonts.get(font) if self.fonts is not None and font and self.game_art else None
        if bitmap is not None:
            definition = self.fonts.definition(font)
            rendered = bitmap.render(text, max_width=width, align=align, color=definition.color,
                                     color_codes=definition.color_codes)
            canvas.alpha_composite(rendered.crop((0, 0, min(width, rendered.size[0]), min(height, rendered.size[1]))))
            return canvas
        draw = ImageDraw.Draw(canvas)
        pil_font = _default_font(12)
        lines = _wrap(draw, text, pil_font, width)
        y = 0
        for line in lines:
            box = draw.textbbox((0, 0), line, font=pil_font)
            line_w = box[2] - box[0]
            mode = (align or "left").lower()
            x = (width - line_w) // 2 if mode in ("centre", "center") else (width - line_w if mode == "right" else 0)
            draw.text((x, y), line, fill=INK, font=pil_font)
            y += (box[3] - box[1]) + 4
            if y > height:
                break
        return canvas

    def placeholder(self, size: tuple[int, int], label: str = "") -> Image.Image:
        """Recuadro discontinuo con el nombre del elemento: un elemento sin imagen o sin arte del juego."""
        width, height = max(1, size[0]), max(1, size[1])
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        for x in range(0, width, 6):
            draw.line([(x, 0), (min(x + 3, width - 1), 0)], fill=PLACEHOLDER)
            draw.line([(x, height - 1), (min(x + 3, width - 1), height - 1)], fill=PLACEHOLDER)
        for y in range(0, height, 6):
            draw.line([(0, y), (0, min(y + 3, height - 1))], fill=PLACEHOLDER)
            draw.line([(width - 1, y), (width - 1, min(y + 3, height - 1))], fill=PLACEHOLDER)
        if label and width > 12 and height > 10:
            draw.text((4, 2), label[: max(1, width // 7)], fill=PLACEHOLDER, font=_default_font(10))
        return image

    def panel(self, size: tuple[int, int]) -> Image.Image:
        """El fondo procedural de una ventana: pergamino con borde."""
        width, height = max(1, size[0]), max(1, size[1])
        image = Image.new("RGBA", (width, height), PARCHMENT)
        draw = ImageDraw.Draw(image)
        draw.rectangle([0, 0, width - 1, height - 1], outline=PARCHMENT_EDGE, width=3)
        return image

    def render(self, document: GuiDocument, window: GuiElement, screen: tuple[int, int], *,
               overrides: Mapping[str, object] | None = None, crop: bool = False,
               extra: list[GuiElement] | None = None) -> tuple[Image.Image, dict[int, Rect]]:
        """La ventana (y ``extra``, elementos sueltos del mismo archivo) sobre una pantalla de ``screen``.

        Devuelve la imagen y el rectángulo absoluto de cada elemento por ``uid``. Con ``crop``, la imagen es solo
        el rectángulo que ocupa la ventana."""
        rects = self.layout(window, screen)
        for loose in extra or ():
            rects.update(self.layout(loose, screen))
        image = Image.new("RGBA", (int(screen[0]), int(screen[1])), SCREEN_BACK)
        background = document.background_of(window)
        win_rect = rects[window.uid]
        own = self._sprite_for(window, (win_rect.w, win_rect.h)) if window.sprite else None
        back = None
        if background is not None:
            back = self._sprite_for(background, (win_rect.w, win_rect.h))
            if back is not None:
                rects[background.uid] = Rect(win_rect.x, win_rect.y, back.size[0], back.size[1])
        if own is None and back is None:
            image.alpha_composite(self.panel((win_rect.w, win_rect.h)), (max(0, win_rect.x), max(0, win_rect.y)))
        for element in [*window.walk(), *(el for loose in extra or () for el in loose.walk())]:
            if element is window:
                if own is not None:
                    _paste(image, own, win_rect)
                continue
            rect = rects[element.uid]
            if element is background and back is not None:
                _paste(image, back, win_rect)     # a su tamaño (el 9-slice ya lo estiró a la ventana)
                continue
            picture = self.element_image(element, (rect.w, rect.h), overrides)
            if picture is not None:
                _paste(image, picture, rect)
        if crop:
            box = (max(0, win_rect.x), max(0, win_rect.y), min(image.size[0], win_rect.right),
                   min(image.size[1], win_rect.bottom))
            if box[2] > box[0] and box[3] > box[1]:
                image = image.crop(box)
        return image, rects


def _declared_size(sprite: Sprite) -> tuple[int, int] | None:
    return sprite.size if sprite.kind == "corneredtilespritetype" else None


def _paste(target: Image.Image, picture: Image.Image, rect: Rect) -> None:
    x, y = rect.x, rect.y
    left, top = max(0, -x), max(0, -y)
    if left >= picture.size[0] or top >= picture.size[1]:
        return
    if left or top:
        picture = picture.crop((left, top, picture.size[0], picture.size[1]))
    target.alpha_composite(picture.convert("RGBA"), (max(0, x), max(0, y)))


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.replace("\\n", "\n").split("\n"):
        words = paragraph.split(" ")
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            box = draw.textbbox((0, 0), candidate, font=font)
            if current and box[2] - box[0] > width:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines


def element_size_of(element: GuiElement, renderer: GuiRenderer) -> tuple[int, int] | None:
    return element_size(element, renderer.sprite_size)
