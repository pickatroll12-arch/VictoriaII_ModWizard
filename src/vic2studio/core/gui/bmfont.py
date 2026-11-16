"""Fuentes de mapa de bits del juego (``gfx/fonts/*.fnt`` + su atlas ``.tga``), wizard §17.1.

El ``.fnt`` es el formato de texto de AngelCode BMFont: líneas ``info``, ``common`` (``lineHeight``, ``base``),
``char id=… x=… y=… width=… height=… xoffset=… yoffset=… xadvance=…`` y ``kerning first=… second=… amount=…``.
``render`` compone un texto en una imagen RGBA con ajuste de línea, alineación y los códigos de color del
juego (``§Y…§W``; ``§!`` vuelve al color inicial). La fuente y el atlas se leen de la instalación del usuario
en tiempo de ejecución; el repositorio no trae ninguna.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from PIL import Image

COLOR_MARK = "§"
RESET_CODE = "!"
DEFAULT_COLOR = (255, 255, 255)
_PAIR_RE = re.compile(r'(\w+)=("[^"]*"|\S+)')


class BMFontError(ValueError):
    """El ``.fnt`` no tiene la forma de BMFont (sin ``common`` o sin caracteres)."""


@dataclass(frozen=True)
class Glyph:
    x: int
    y: int
    width: int
    height: int
    xoffset: int
    yoffset: int
    xadvance: int


def _fields(line: str) -> dict[str, str]:
    return {key: value.strip('"') for key, value in _PAIR_RE.findall(line)}


def _int(fields: Mapping[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(fields.get(key, default)))
    except ValueError:
        return default


class BMFont:
    def __init__(self, glyphs: Mapping[int, Glyph], atlas: Image.Image, *, line_height: int, base: int,
                 kerning: Mapping[tuple[int, int], int] | None = None) -> None:
        self.glyphs = dict(glyphs)
        self.atlas = atlas.convert("RGBA")
        self.line_height = line_height
        self.base = base
        self.kerning = dict(kerning or {})

    @classmethod
    def load(cls, fnt_text: str, atlas: Image.Image) -> BMFont:
        glyphs: dict[int, Glyph] = {}
        kerning: dict[tuple[int, int], int] = {}
        line_height = base = 0
        for line in fnt_text.splitlines():
            tag, _, rest = line.strip().partition(" ")
            fields = _fields(rest)
            if tag == "common":
                line_height, base = _int(fields, "lineHeight"), _int(fields, "base")
            elif tag == "char" and "id" in fields:
                glyphs[_int(fields, "id")] = Glyph(
                    _int(fields, "x"), _int(fields, "y"), _int(fields, "width"), _int(fields, "height"),
                    _int(fields, "xoffset"), _int(fields, "yoffset"), _int(fields, "xadvance"))
            elif tag == "kerning":
                kerning[(_int(fields, "first"), _int(fields, "second"))] = _int(fields, "amount")
        if not glyphs or line_height <= 0:
            raise BMFontError("no es un .fnt de BMFont: falta «common» o no hay caracteres")
        return cls(glyphs, atlas, line_height=line_height, base=base, kerning=kerning)

    # --- medida -------------------------------------------------------------------------------

    def _runs(self, text: str, color_codes: Mapping[str, tuple[int, int, int]],
              color: tuple[int, int, int]) -> list[tuple[str, tuple[int, int, int]]]:
        """El texto en caracteres con su color, tras interpretar ``§X``."""
        chars: list[tuple[str, tuple[int, int, int]]] = []
        current = color
        index = 0
        while index < len(text):
            char = text[index]
            if char == COLOR_MARK and index + 1 < len(text):
                code = text[index + 1]
                current = color if code == RESET_CODE else color_codes.get(code, color_codes.get(code.upper(), current))
                index += 2
                continue
            chars.append((char, current))
            index += 1
        return chars

    def _advance(self, char: str, previous: str | None) -> int:
        glyph = self.glyphs.get(ord(char))
        if glyph is None:
            return 0
        kern = self.kerning.get((ord(previous), ord(char)), 0) if previous is not None else 0
        return glyph.xadvance + kern

    def text_width(self, text: str) -> int:
        """Ancho en píxeles de una línea (sin códigos de color)."""
        width, previous = 0, None
        for char in text:
            width += self._advance(char, previous)
            previous = char
        return width

    def _wrap(self, chars: list[tuple[str, tuple[int, int, int]]], max_width: int):
        """Parte en líneas por los saltos y, si ``max_width`` > 0, por palabras."""
        lines: list[list[tuple[str, tuple[int, int, int]]]] = [[]]
        width = 0
        last_space = -1
        for char, color in chars:
            if char == "\n":
                lines.append([])
                width, last_space = 0, -1
                continue
            line = lines[-1]
            advance = self._advance(char, line[-1][0] if line else None)
            if max_width > 0 and line and width + advance > max_width and char != " ":
                if last_space >= 0:
                    rest = line[last_space + 1:]
                    del line[last_space:]
                    lines.append(rest)
                else:
                    lines.append([])
                line = lines[-1]
                width = sum(self._advance(c, line[i - 1][0] if i else None) for i, (c, _) in enumerate(line))
                last_space = -1
                advance = self._advance(char, line[-1][0] if line else None)
            if char == " ":
                last_space = len(line)
            line.append((char, color))
            width += advance
        return lines

    # --- dibujo -------------------------------------------------------------------------------

    def render(self, text: str, *, max_width: int = 0, align: str = "left",
               color_codes: Mapping[str, tuple[int, int, int]] | None = None,
               color: tuple[int, int, int] = DEFAULT_COLOR) -> Image.Image:
        """``text`` como imagen RGBA. ``align``: ``left``, ``centre``/``center`` o ``right`` dentro de
        ``max_width`` (o del ancho de la línea más larga). Los caracteres que la fuente no tiene se saltan."""
        lines = self._wrap(self._runs(text, color_codes or {}, color), max_width)
        widths = [self.text_width("".join(c for c, _ in line)) for line in lines]
        width = max(max_width, max(widths, default=0), 1)
        height = max(self.line_height * len(lines), 1)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        mode = align.lower()
        for row, line in enumerate(lines):
            if mode in ("centre", "center"):
                pen = (width - widths[row]) // 2
            elif mode == "right":
                pen = width - widths[row]
            else:
                pen = 0
            previous = None
            for char, tint in line:
                glyph = self.glyphs.get(ord(char))
                if glyph is None:
                    continue
                pen += self.kerning.get((ord(previous), ord(char)), 0) if previous is not None else 0
                if glyph.width > 0 and glyph.height > 0:
                    cell = self.atlas.crop((glyph.x, glyph.y, glyph.x + glyph.width, glyph.y + glyph.height))
                    image.alpha_composite(self._tint(cell, tint),
                                          (max(0, pen + glyph.xoffset), max(0, row * self.line_height + glyph.yoffset)))
                pen += glyph.xadvance
                previous = char
        return image

    @staticmethod
    def _tint(cell: Image.Image, color: tuple[int, int, int]) -> Image.Image:
        """El glifo (blanco con alfa en el atlas) teñido de ``color``."""
        if color == DEFAULT_COLOR:
            return cell
        red, green, blue, alpha = cell.split()
        scale = [color[0] / 255.0, color[1] / 255.0, color[2] / 255.0]
        bands = [band.point(lambda v, f=factor: int(v * f)) for band, factor in zip((red, green, blue), scale)]
        return Image.merge("RGBA", (*bands, alpha))
