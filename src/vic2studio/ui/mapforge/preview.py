"""Vista previa del taller (wizard §18.2): el ráster a W/4 con el norte arriba, en 16 modos, y los pinceles.

``render(world, mode)`` pinta con numpy (sin Qt) una imagen RGB en el orden del juego; ``PreviewView`` la voltea
solo para enseñarla (``to_display_row``) y traduce el ratón a coordenadas normalizadas del juego (``x/W``,
``y/H`` con y hacia el norte), que son las de las ediciones (``EditOp``), independientes de la escala.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...core.mapforge.world import CAT_INDEX, CATS, SEA_LEVEL
from ...i18n import N_

MODES = ("relief", "landsea", "temperature", "precipitation", "rivers", "biomes", "terrain", "provinces", "states",
         "continents", "climates", "owners", "cultures", "religions", "population", "problems")
MODE_LABELS = {
    "relief": N_("forge.mode.relief"), "landsea": N_("forge.mode.landsea"),
    "temperature": N_("forge.mode.temperature"), "precipitation": N_("forge.mode.precipitation"),
    "rivers": N_("forge.mode.rivers"), "biomes": N_("forge.mode.biomes"), "terrain": N_("forge.mode.terrain"),
    "provinces": N_("forge.mode.provinces"), "states": N_("forge.mode.states"),
    "continents": N_("forge.mode.continents"), "climates": N_("forge.mode.climates"),
    "owners": N_("forge.mode.owners"), "cultures": N_("forge.mode.cultures"),
    "religions": N_("forge.mode.religions"), "population": N_("forge.mode.population"),
    "problems": N_("forge.mode.problems"),
}
SEA = np.array([38, 66, 104], np.uint8)
SEA_DEEP = np.array([22, 44, 78], np.uint8)
NONE = np.array([196, 186, 160], np.uint8)
CAT_COLORS = np.array([
    (38, 66, 104), (232, 236, 240), (196, 190, 92), (54, 110, 52), (150, 122, 80), (96, 140, 70), (120, 110, 104),
    (190, 170, 110), (150, 180, 90), (40, 120, 60), (90, 120, 100), (220, 196, 140)], np.uint8)
CLIMATE_COLORS = np.array([(132, 190, 96), (190, 196, 96), (196, 140, 80), (150, 150, 160)], np.uint8)


def palette(n: int, seed: int = 0) -> np.ndarray:
    """``n`` colores distintos y estables (ángulo áureo en HSV, sin aleatoriedad)."""
    i = np.arange(n, dtype=np.float64) + seed
    h = (i * 0.618033988749895) % 1.0
    s = 0.45 + 0.25 * ((i * 0.37) % 1.0)
    v = 0.70 + 0.22 * ((i * 0.53) % 1.0)
    k = np.floor(h * 6)
    f = h * 6 - k
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    k = k.astype(int) % 6
    r = np.choose(k, [v, q, p, p, t, v])
    g = np.choose(k, [t, v, v, q, p, p])
    b = np.choose(k, [p, p, t, v, v, q])
    return (np.stack([r, g, b], 1) * 255).astype(np.uint8)


def _ramp(values: np.ndarray, lo: float, hi: float, a, b) -> np.ndarray:
    t = np.clip((values - lo) / max(hi - lo, 1e-9), 0, 1)[..., None]
    return (np.asarray(a, np.float64) * (1 - t) + np.asarray(b, np.float64) * t).astype(np.uint8)


def _shade(h: np.ndarray) -> np.ndarray:
    """Relieve sombreado (luz del noroeste) con tintas hipsométricas."""
    gy, gx = np.gradient(h.astype(np.float64))
    light = np.clip(0.75 + (gx - gy) * 0.06, 0.35, 1.25)[..., None]
    land = _ramp(h, SEA_LEVEL, 90, (96, 140, 76), (236, 228, 214))
    hill = _ramp(h, 45, 70, (170, 150, 104), (130, 116, 104))
    base = np.where((h >= 45)[..., None], hill, land)
    water = _ramp(h, 0, SEA_LEVEL, SEA_DEEP, (70, 110, 150))
    out = np.where((h >= SEA_LEVEL)[..., None], np.clip(base * light, 0, 255), water)
    return out.astype(np.uint8)


def _by_id(r, values: np.ndarray | None, n_colors: int | None = None) -> np.ndarray:
    """Color por id según un atributo entero (``-1`` = sin valor), con el mar en azul."""
    ids = r.ids
    out = np.empty(ids.shape + (3,), np.uint8)
    if values is None:
        out[:] = NONE
    else:
        v = np.asarray(values)
        k = int(v.max()) + 1 if v.size and v.max() >= 0 else 1
        pal = np.vstack([NONE[None, :], palette(n_colors or k)])
        out[:] = pal[np.clip(v, -1, None)[ids] + 1]
    out[r.is_sea[ids]] = SEA
    return out


def _borders(img: np.ndarray, ids: np.ndarray, color=(40, 30, 20)) -> np.ndarray:
    edge = np.zeros(ids.shape, bool)
    edge[:, 1:] |= ids[:, 1:] != ids[:, :-1]
    edge[1:, :] |= ids[1:, :] != ids[:-1, :]
    img = img.copy()
    img[edge] = (img[edge] * 0.55 + np.asarray(color) * 0.45).astype(np.uint8)
    return img


def render(world, mode: str, *, problems: set[int] | None = None) -> np.ndarray | None:
    """Imagen RGB ``(H, W, 3)`` del ráster de ``world`` en el modo pedido (orden del juego), o None sin ráster."""
    r = getattr(world, "raster", None)
    if r is None:
        return None
    c = world.cells
    cell_r = r.report.get("cell_r")
    sea_px = r.is_sea[r.ids]
    if mode == "relief":
        return _shade(r.h_px)
    if mode == "landsea":
        out = np.where(sea_px[..., None], SEA, np.array([170, 160, 120], np.uint8)).astype(np.uint8)
        return out
    if mode in ("temperature", "precipitation"):
        if cell_r is None or getattr(c, "temp" if mode == "temperature" else "prec") is None:
            return _shade(r.h_px)
        v = (c.temp if mode == "temperature" else c.prec)[cell_r]
        img = _ramp(v, -25, 30, (60, 90, 200), (220, 60, 40)) if mode == "temperature" else \
            _ramp(v, 0, float(np.quantile(c.prec, 0.95)) or 1.0, (230, 214, 170), (40, 90, 180))
        img[sea_px] = (img[sea_px] * 0.45 + SEA * 0.55).astype(np.uint8)
        return img
    if mode == "rivers":
        img = np.where(sea_px[..., None], SEA, np.array([196, 190, 160], np.uint8)).astype(np.uint8)
        riv = (r.rivers < 254) if r.rivers is not None else np.zeros(sea_px.shape, bool)
        img[riv] = (30, 90, 200)
        return img
    if mode in ("biomes", "terrain"):
        cat = r.pix_cat if r.pix_cat is not None else np.zeros(r.ids.shape, np.int8)
        img = CAT_COLORS[np.clip(cat, 0, len(CATS) - 1)]
        return _borders(img, r.ids) if mode == "terrain" else img
    if mode == "provinces":
        cols = r.colors
        img = np.stack([(cols >> 16) & 255, (cols >> 8) & 255, cols & 255], 1).astype(np.uint8)[r.ids]
        return _borders(img, r.ids)
    if mode in ("states", "continents", "owners", "cultures", "religions"):
        attr = {"states": "state", "continents": "continent", "owners": "owner", "cultures": "culture",
                "religions": "religion"}[mode]
        return _borders(_by_id(r, getattr(r, attr, None)), r.ids)
    if mode == "climates":
        v = r.climate
        img = np.empty(r.ids.shape + (3,), np.uint8)
        img[:] = NONE
        if v is not None:
            pal = np.vstack([NONE[None, :], CLIMATE_COLORS])
            img = pal[np.clip(np.asarray(v), -1, 3)[r.ids] + 1]
        img[sea_px] = SEA
        return _borders(img, r.ids)
    if mode == "population":
        pop = np.asarray(r.population if r.population is not None else np.zeros(r.count + 1), np.float64)
        area = np.maximum(np.bincount(r.ids.ravel(), minlength=pop.size), 1)
        dens = pop / area
        top = float(np.quantile(dens[1:r.land_count + 1], 0.95)) if r.land_count else 1.0
        img = _ramp(dens[r.ids], 0, top or 1.0, (238, 230, 200), (150, 30, 30))
        img[sea_px] = SEA
        return img
    if mode == "problems":
        img = (_shade(r.h_px) * 0.5 + 100).astype(np.uint8)
        if problems:
            mark = np.isin(r.ids, np.fromiter(problems, np.int64))
            img[mark] = (210, 40, 30)
        return _borders(img, r.ids)
    return _shade(r.h_px)


def to_qimage(rgb: np.ndarray) -> QImage:
    """QImage con el norte arriba (la única conversión de filas de la vista)."""
    view = np.ascontiguousarray(rgb[::-1])
    h, w = view.shape[:2]
    return QImage(view.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class PreviewView(QWidget):
    """La imagen escalada con su proporción. Emite coordenadas normalizadas del juego."""

    stroke = Signal(float, float, bool)      # (x, y, primero) mientras se arrastra con un pincel
    strokeFinished = Signal()
    picked = Signal(float, float)            # clic sin pincel
    renamed = Signal(float, float)           # doble clic
    hovered = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("forgePreview")
        self.setMouseTracking(True)
        self.setMinimumSize(360, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image: QImage | None = None
        self.brush_radius = 0.0                  # normalizado al ancho; 0 = sin pincel
        self._cursor: QPointF | None = None
        self._dragging = False

    def set_image(self, image: QImage | None) -> None:
        self.image = image
        self.update()

    def _rect(self) -> QRectF:
        if self.image is None or self.image.isNull():
            return QRectF(self.rect())
        iw, ih = self.image.width(), self.image.height()
        s = min(self.width() / iw, self.height() / ih)
        w, h = iw * s, ih * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _norm(self, pos) -> tuple[float, float] | None:
        r = self._rect()
        if r.width() <= 0 or not r.contains(pos):
            return None
        x = (pos.x() - r.left()) / r.width()
        y = 1.0 - (pos.y() - r.top()) / r.height()     # al orden del juego (y hacia el norte)
        return float(x), float(y)

    def paintEvent(self, event) -> None:  # noqa: N802 - API de Qt
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(30, 34, 40))
        if self.image is not None and not self.image.isNull():
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawImage(self._rect(), self.image)
        if self.brush_radius > 0 and self._cursor is not None:
            r = self._rect()
            rad = self.brush_radius * r.width()
            p.setPen(QPen(QColor(255, 236, 170), 1.5))
            p.drawEllipse(self._cursor, rad, rad)
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        n = self._norm(event.position())
        if n is None or event.button() != Qt.MouseButton.LeftButton:
            return
        if self.brush_radius > 0:
            self._dragging = True
            self.stroke.emit(n[0], n[1], True)
        else:
            self.picked.emit(*n)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._cursor = event.position()
        n = self._norm(event.position())
        if n is not None:
            self.hovered.emit(*n)
            if self._dragging:
                self.stroke.emit(n[0], n[1], False)
        if self.brush_radius > 0:
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._dragging:
            self._dragging = False
            self.strokeFinished.emit()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        n = self._norm(event.position())
        if n is not None:
            self.renamed.emit(*n)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._cursor = None
        self.update()


__all__ = ["MODES", "MODE_LABELS", "render", "to_qimage", "PreviewView", "palette", "CAT_INDEX"]
