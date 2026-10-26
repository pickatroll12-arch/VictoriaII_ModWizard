"""Tema visual "victoriano": paleta, tipografías, texturas procedurales y hoja de estilo.

Nada procede del juego: las texturas (pergamino, madera, terciopelo) se generan
con ruido espectral en numpy, son periódicas (se repiten sin costuras) y se
cachean por proceso. Los glifos que necesita la hoja de estilo (flechas,
marcas) se dibujan con QPainter en una carpeta temporal que se borra al salir.
"""

from __future__ import annotations

import atexit
import logging
import shutil
import tempfile
from pathlib import Path
from string import Template

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QGradient,
    QImage,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parents[1]
FONTS_DIR = PACKAGE_DIR / "assets" / "fonts"
STYLESHEET_PATH = Path(__file__).with_name("style.qss")

PALETTE = {
    "parchment": "#e8d7ae",
    "parchment_light": "#f2e6c7",
    "parchment_pale": "#faf3df",
    "parchment_dark": "#d6c08e",
    "parchment_shadow": "#a88c5a",
    "ink": "#2a1a0c",
    "ink_soft": "#5b4126",
    "ink_muted": "#6e5233",
    "wood_dark": "#1c110a",
    "wood": "#3a2414",
    "wood_light": "#5b3a20",
    "velvet_dark": "#3d0b10",
    "velvet": "#6a151d",
    "velvet_light": "#8e2630",
    "velvet_text": "#7a1c24",
    "bronze_dark": "#4a3214",
    "bronze": "#8a6428",
    "gold": "#c9a24a",
    "gold_light": "#e8cc82",
    "gold_pale": "#f6e7b4",
    "cream": "#f3e6c4",
    "cream_muted": "#cdb98f",
    "cream_disabled": "#8f7c5c",
    "success": "#2f5d23",
    "warning": "#7a4e00",
    "danger": "#8b1a1a",
    # Resaltado de sintaxis Clausewitz sobre pergamino claro (contraste >= 5:1).
    "syntax_comment": "#5a6633",
    "syntax_string": "#24456b",
    "syntax_number": "#80480f",
    "syntax_keyword": "#5b2a6e",
    "syntax_key": "#7a1c24",
    "syntax_brace": "#4a3214",
}

DISPLAY_FAMILIES = (
    "Cinzel", "Cormorant SC", "Cormorant Garamond", "EB Garamond", "Libre Baskerville",
    "Palatino Linotype", "Book Antiqua", "P052", "Palatino", "Georgia", "C059",
    "Noto Serif", "DejaVu Serif", "Liberation Serif",
)
BODY_FAMILIES = (
    "EB Garamond", "Libre Baskerville", "Georgia", "Noto Serif", "Palatino Linotype",
    "Book Antiqua", "P052", "Cormorant Garamond", "DejaVu Serif", "Liberation Serif",
)
MONO_FAMILIES = (
    "Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono", "Noto Sans Mono",
    "Liberation Mono", "Courier New",
)

BODY_POINT_SIZE = 10.5

# rol -> (familias, tamaño en puntos, peso, versalitas, cursiva, espaciado %)
_FONT_ROLES = {
    "body": (BODY_FAMILIES, BODY_POINT_SIZE, QFont.Weight.Normal, False, False, 100),
    "body_bold": (BODY_FAMILIES, BODY_POINT_SIZE, QFont.Weight.DemiBold, False, False, 100),
    "caption": (BODY_FAMILIES, 9.5, QFont.Weight.Normal, False, True, 100),
    "small": (BODY_FAMILIES, 9.0, QFont.Weight.Normal, False, False, 100),
    "banner": (DISPLAY_FAMILIES, 23.0, QFont.Weight.DemiBold, True, False, 108),
    "tagline": (BODY_FAMILIES, 10.0, QFont.Weight.Normal, False, True, 102),
    "title": (DISPLAY_FAMILIES, 19.0, QFont.Weight.DemiBold, True, False, 106),
    "subtitle": (BODY_FAMILIES, 10.5, QFont.Weight.Normal, False, True, 100),
    "heading": (DISPLAY_FAMILIES, 12.0, QFont.Weight.DemiBold, True, False, 105),
    "nav": (DISPLAY_FAMILIES, 11.0, QFont.Weight.DemiBold, True, False, 104),
    "badge": (DISPLAY_FAMILIES, 9.0, QFont.Weight.Bold, True, False, 112),
    "numeral": (DISPLAY_FAMILIES, 15.0, QFont.Weight.Bold, False, False, 100),
    "mono": (MONO_FAMILIES, 9.5, QFont.Weight.Normal, False, False, 100),
}

_family_cache: dict[tuple[str, ...], str | None] = {}
_texture_cache: dict[str, QPixmap] = {}
_glyph_dir: Path | None = None
_fonts_loaded = False


def color(name: str, alpha: int | None = None) -> QColor:
    c = QColor(PALETTE[name])
    if alpha is not None:
        c.setAlpha(alpha)
    return c


# --- tipografías -------------------------------------------------------------------------

def load_bundled_fonts(directory: Path = FONTS_DIR) -> list[str]:
    """Registra los .ttf/.otf de ``assets/fonts`` (carpeta opcional); devuelve sus familias."""
    global _fonts_loaded
    families: list[str] = []
    if directory.is_dir():
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() not in {".ttf", ".otf"}:
                continue
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id < 0:
                log.warning("no se pudo cargar la fuente %s", path)
                continue
            families.extend(QFontDatabase.applicationFontFamilies(font_id))
    _fonts_loaded = True
    _family_cache.clear()
    return families


def resolve_family(candidates: tuple[str, ...]) -> str | None:
    """Primera familia instalada de la lista, o ``None`` si no hay ninguna."""
    if candidates not in _family_cache:
        # Qt añade " [fundición]" cuando una familia existe en varias fundiciones.
        installed = {}
        for name in QFontDatabase.families():
            base = name.split(" [", 1)[0]
            installed.setdefault(base.casefold(), base)
        _family_cache[candidates] = next(
            (installed[c.casefold()] for c in candidates if c.casefold() in installed), None
        )
    return _family_cache[candidates]


def font(role: str = "body", point_size: float | None = None) -> QFont:
    families, size, weight, small_caps, italic, spacing = _FONT_ROLES[role]
    result = QFont()
    family = resolve_family(families)
    if family:
        result.setFamily(family)
    result.setStyleHint(QFont.StyleHint.TypeWriter if families is MONO_FAMILIES else QFont.StyleHint.Serif)
    result.setPointSizeF(point_size or size)
    result.setWeight(weight)
    result.setItalic(italic)
    if small_caps:
        result.setCapitalization(QFont.Capitalization.SmallCaps)
    if spacing != 100:
        result.setLetterSpacing(QFont.SpacingType.PercentageSpacing, spacing)
    return result


# --- texturas procedurales ---------------------------------------------------------------

def _spectral_noise(rng: np.random.Generator, height: int, width: int, beta: float,
                    stretch: tuple[float, float] = (1.0, 1.0)) -> np.ndarray:
    """Ruido 1/f^beta periódico (normalizado a media 0, desviación 1).

    ``stretch`` atenúa las frecuencias de un eje: (1, 8) alarga las vetas en horizontal.
    """
    fy = np.fft.fftfreq(height)[:, None] * stretch[0]
    fx = np.fft.fftfreq(width)[None, :] * stretch[1]
    radius = np.hypot(fx, fy)
    radius[0, 0] = np.inf
    field = np.fft.ifft2(np.fft.fft2(rng.standard_normal((height, width))) / radius ** beta).real
    return (field - field.mean()) / (field.std() + 1e-12)


def _ramp(t: np.ndarray, stops: list[tuple[float, tuple[int, int, int]]]) -> np.ndarray:
    positions = np.array([p for p, _ in stops])
    colors = np.array([c for _, c in stops], dtype=float)
    return np.stack([np.interp(t, positions, colors[:, i]) for i in range(3)], axis=-1)


def _parchment_rgb(size: int = 512, seed: int = 1851) -> np.ndarray:
    rng = np.random.default_rng(seed)
    stains = _spectral_noise(rng, size, size, 2.1)
    mottle = _spectral_noise(rng, size, size, 1.4)
    fibres = _spectral_noise(rng, size, size, 1.1, stretch=(1.0, 6.0))
    grain = rng.standard_normal((size, size))
    t = 0.56 + 0.075 * stains + 0.04 * mottle + 0.03 * fibres + 0.018 * grain
    foxing = np.clip(stains - 1.9, 0.0, None) * 0.07
    rgb = _ramp(np.clip(t, 0, 1), [
        (0.0, (176, 146, 96)), (0.4, (214, 194, 148)), (0.55, (232, 215, 174)),
        (0.75, (243, 231, 200)), (1.0, (250, 242, 220)),
    ])
    return rgb * (1.0 - foxing[..., None] * np.array([0.6, 0.85, 1.25]))


def _wood_rgb(width: int = 512, height: int = 256, seed: int = 1861) -> np.ndarray:
    rng = np.random.default_rng(seed)
    warp = _spectral_noise(rng, height, width, 2.2, stretch=(1.0, 7.0))
    streaks = _spectral_noise(rng, height, width, 1.15, stretch=(1.0, 16.0))
    pores = rng.standard_normal((height, width))
    y = np.arange(height, dtype=float)[:, None] / height
    rings = np.sin(2 * np.pi * (7 * y + 0.45 * warp))
    t = 0.5 + 0.2 * rings + 0.2 * streaks + 0.05 * pores
    return _ramp(np.clip(t, 0, 1), [
        (0.0, (24, 14, 8)), (0.35, (44, 27, 15)), (0.6, (62, 39, 21)), (0.85, (84, 55, 30)), (1.0, (100, 67, 38)),
    ])


def _velvet_rgb(size: int = 512, seed: int = 1871) -> np.ndarray:
    rng = np.random.default_rng(seed)
    folds = _spectral_noise(rng, size, size, 2.4)
    pile = _spectral_noise(rng, size, size, 1.0, stretch=(9.0, 1.0))
    grain = rng.standard_normal((size, size))
    t = 0.5 + 0.17 * folds + 0.07 * pile + 0.04 * grain
    return _ramp(np.clip(t, 0, 1), [
        (0.0, (40, 7, 11)), (0.4, (78, 15, 22)), (0.6, (100, 21, 29)), (0.85, (126, 32, 40)), (1.0, (146, 44, 50)),
    ])


_TEXTURES = {"parchment": _parchment_rgb, "wood": _wood_rgb, "velvet": _velvet_rgb}


def texture_image(name: str) -> QImage:
    rgb = np.ascontiguousarray(np.clip(_TEXTURES[name](), 0, 255).astype(np.uint8))
    height, width, _ = rgb.shape
    return QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()


def texture(name: str) -> QPixmap:
    """Textura periódica cacheada: ``parchment``, ``wood`` o ``velvet``."""
    if name not in _texture_cache:
        _texture_cache[name] = QPixmap.fromImage(texture_image(name))
    return _texture_cache[name]


def paint_surface(painter: QPainter, rect: QRectF, name: str, vignette: float = 0.0) -> None:
    """Rellena ``rect`` con la textura y, opcionalmente, oscurece los bordes (viñeta)."""
    painter.fillRect(rect, QBrush(texture(name)))
    if vignette > 0:
        # Coordenadas relativas al rectángulo: la viñeta es elíptica y se adapta al tamaño.
        gradient = QRadialGradient(QPointF(0.5, 0.5), 0.75)
        gradient.setCoordinateMode(QGradient.CoordinateMode.ObjectBoundingMode)
        edge = QColor(70, 38, 8) if name == "parchment" else QColor(0, 0, 0)
        edge.setAlphaF(min(1.0, vignette))
        gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
        gradient.setColorAt(0.5, QColor(0, 0, 0, 0))
        gradient.setColorAt(1.0, edge)
        painter.fillRect(rect, QBrush(gradient))


# --- glifos para la hoja de estilo -------------------------------------------------------

def _glyph_arrow(direction: str):
    def draw(p: QPainter, s: float, c: QColor) -> None:
        path = QPainterPath()
        if direction == "down":
            path.moveTo(s * 0.22, s * 0.36); path.lineTo(s * 0.78, s * 0.36); path.lineTo(s * 0.5, s * 0.7)
        elif direction == "up":
            path.moveTo(s * 0.22, s * 0.66); path.lineTo(s * 0.78, s * 0.66); path.lineTo(s * 0.5, s * 0.32)
        else:
            path.moveTo(s * 0.36, s * 0.22); path.lineTo(s * 0.36, s * 0.78); path.lineTo(s * 0.7, s * 0.5)
        path.closeSubpath()
        p.fillPath(path, c)
    return draw


def _glyph_check(p: QPainter, s: float, c: QColor) -> None:
    pen = QPen(c, s * 0.16, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    path = QPainterPath(QPointF(s * 0.2, s * 0.52))
    path.lineTo(s * 0.42, s * 0.74)
    path.lineTo(s * 0.8, s * 0.28)
    p.drawPath(path)


def _glyph_dot(p: QPainter, s: float, c: QColor) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawEllipse(QPointF(s / 2, s / 2), s * 0.22, s * 0.22)


def _glyph_grip(vertical: bool):
    def draw(p: QPainter, s: float, c: QColor) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        for i in (-1, 0, 1):
            offset = s / 2 + i * s * 0.26
            center = QPointF(s / 2, offset) if vertical else QPointF(offset, s / 2)
            p.drawEllipse(center, s * 0.09, s * 0.09)
    return draw


_GLYPHS = {
    "arrow_down": (_glyph_arrow("down"), 12),
    "arrow_up": (_glyph_arrow("up"), 12),
    "arrow_right": (_glyph_arrow("right"), 12),
    "check": (_glyph_check, 14),
    "dot": (_glyph_dot, 14),
    "grip_v": (_glyph_grip(True), 16),
    "grip_h": (_glyph_grip(False), 16),
}
_GLYPH_COLORS = {"ink": "ink_soft", "gold": "gold_light", "cream": "cream", "muted": "cream_disabled"}


def glyph_dir() -> Path:
    """Carpeta (temporal, por proceso) con los glifos PNG en 1x y @2x."""
    global _glyph_dir
    if _glyph_dir is None:
        directory = Path(tempfile.mkdtemp(prefix="vic2studio-theme-"))
        atexit.register(shutil.rmtree, directory, True)
        for name, (draw, size) in _GLYPHS.items():
            for suffix_color, palette_name in _GLYPH_COLORS.items():
                for scale, suffix in ((1, ""), (2, "@2x")):
                    image = QImage(size * scale, size * scale, QImage.Format.Format_ARGB32_Premultiplied)
                    image.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(image)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    painter.scale(scale, scale)
                    draw(painter, float(size), color(palette_name))
                    painter.end()
                    image.save(str(directory / f"{name}_{suffix_color}{suffix}.png"))
        _glyph_dir = directory
    return _glyph_dir


# --- paleta Qt y hoja de estilo ----------------------------------------------------------

def build_palette() -> QPalette:
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: "parchment",
        QPalette.ColorRole.WindowText: "ink",
        QPalette.ColorRole.Base: "parchment_pale",
        QPalette.ColorRole.AlternateBase: "parchment_light",
        QPalette.ColorRole.Text: "ink",
        QPalette.ColorRole.PlaceholderText: "ink_muted",
        QPalette.ColorRole.Button: "wood_light",
        QPalette.ColorRole.ButtonText: "cream",
        QPalette.ColorRole.BrightText: "gold_pale",
        QPalette.ColorRole.Highlight: "velvet",
        QPalette.ColorRole.HighlightedText: "cream",
        QPalette.ColorRole.ToolTipBase: "parchment_pale",
        QPalette.ColorRole.ToolTipText: "ink",
        QPalette.ColorRole.Link: "velvet_light",
        QPalette.ColorRole.LinkVisited: "velvet",
        QPalette.ColorRole.Light: "gold_light",
        QPalette.ColorRole.Midlight: "gold",
        QPalette.ColorRole.Mid: "bronze",
        QPalette.ColorRole.Dark: "bronze_dark",
        QPalette.ColorRole.Shadow: "wood_dark",
    }
    for role, name in roles.items():
        pal.setColor(role, color(name))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, color("ink_muted"))
    return pal


def stylesheet_tokens() -> dict[str, str]:
    tokens = dict(PALETTE)
    glyphs = glyph_dir()
    for name in _GLYPHS:
        for suffix_color in _GLYPH_COLORS:
            tokens[f"img_{name}_{suffix_color}"] = (glyphs / f"{name}_{suffix_color}.png").as_posix()
    tokens["body_pt"] = f"{BODY_POINT_SIZE:g}"
    return tokens


def build_stylesheet() -> str:
    return Template(STYLESHEET_PATH.read_text(encoding="utf-8")).substitute(stylesheet_tokens())


def apply_theme(app: QApplication) -> None:
    """Aplica estilo base Fusion, fuentes, paleta y hoja de estilo a la aplicación."""
    app.setStyle("Fusion")
    if not _fonts_loaded:
        load_bundled_fonts()
    app.setFont(font("body"))
    app.setPalette(build_palette())
    app.setStyleSheet(build_stylesheet())
