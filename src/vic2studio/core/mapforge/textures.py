"""Texturas del mapa (wizard §18.5): colormaps, agua, sin sombra (DXT3), política y minimapa.

Color base por categoría con la paleta aprendida de la instalación (también bajo el mar, donde el agua la dibuja
otro shader); encima, sombreado del relieve con luz del noroeste (0,7–1,25) y grano. Cabeceras y medidas de vanilla
(a 5616×2160): ``colormap.dds`` y ``colormap_political.dds`` de 1880×720 (W/3 más 4 px por lado copiados
envolviendo), ``colormap_water.dds`` de 936×360 con 10 mips, ``colormap_no_shadow.dds`` de 1872×720 en DXT3 y
``gfx/interface/minimap.dds`` de 266×102.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from ..gfx.dds import write_dds, write_dxt3
from .world import SEA_LEVEL

PAD = 4
MINIMAP_SIZE = (266, 102)

# Paleta procedural propia (sin instalación): un color por categoría de ``world.CATS``.
PROCEDURAL_PALETTE = np.array([
    (134, 129, 89), (226, 230, 232), (150, 160, 80), (70, 105, 60), (130, 125, 85), (95, 125, 70),
    (120, 110, 100), (170, 160, 105), (140, 150, 85), (60, 110, 55), (90, 110, 85), (205, 185, 130)],
    dtype=np.float32)
PROCEDURAL_WATER = np.array((40, 70, 110), dtype=np.float32)


def _resize(a: np.ndarray, w: int, h: int, method=Image.BILINEAR) -> np.ndarray:
    return np.asarray(Image.fromarray(a.astype(np.float32), "F").resize((w, h), method), np.float32)


def _rgba(rgb: np.ndarray) -> np.ndarray:
    return np.dstack([rgb, np.full(rgb.shape[:2], 255, np.uint8)])


def build(pcat: np.ndarray, hp: np.ndarray, cm_pal: np.ndarray, water_mean: np.ndarray, rng: np.random.Generator,
          *, owner_px: np.ndarray | None = None) -> dict[str, bytes]:
    """Los cinco DDS a partir de la categoría por píxel (0 = agua) y la altura por píxel."""
    H, W = pcat.shape
    W3, H3 = max(4, W // 3), max(4, H // 3)
    sub_cat = pcat[1::3, 1::3][:H3, :W3]
    if sub_cat.shape != (H3, W3):
        sub_cat = np.asarray(Image.fromarray(pcat.astype(np.uint8)).resize((W3, H3), Image.NEAREST))
    sub_h = _resize(hp, W3, H3)
    col = np.asarray(cm_pal, np.float32)[sub_cat]
    gy, gx = np.gradient(sub_h)
    shade = np.clip(1 + 0.04 * (gx - gy), 0.7, 1.25)[..., None]
    grain = _resize(rng.uniform(-6, 6, (H3 // 8 + 1, W3 // 8 + 1)), W3, H3)[..., None]
    cm = np.clip(col * shade + grain, 0, 255).astype(np.uint8)
    cmp_ = np.concatenate([cm[:, -PAD:], cm, cm[:, :PAD]], axis=1)
    out = {"map/terrain/colormap.dds": write_dds(_rgba(cmp_))}
    W6, H6 = max(1, W // 6), max(1, H // 6)
    hw = _resize(hp, W6, H6)
    depth = np.clip((SEA_LEVEL - hw) / SEA_LEVEL, 0, 1)[..., None]
    wm = np.asarray(water_mean, np.float32)
    wat = np.clip(wm * (1.15 - 0.3 * depth), 0, 255)
    wat = np.where((hw >= SEA_LEVEL)[..., None], wm, wat).astype(np.uint8)
    out["map/terrain/colormap_water.dds"] = write_dds(_rgba(wat), mipmaps=True)
    nos = np.clip(col + grain, 0, 255).astype(np.uint8)
    h4, w4 = (H3 // 4) * 4, (W3 // 4) * 4
    out["map/terrain/colormap_no_shadow.dds"] = write_dxt3(np.ascontiguousarray(nos[:h4, :w4]))
    if owner_px is not None:
        o = owner_px[1::3, 1::3][:H3, :W3]
        tint = np.where(o[..., None] >= 0, 200, np.where(sub_cat[..., None] == 0, 90, 170))
    else:
        tint = np.where(sub_cat[..., None] == 0, 90, 200)
    pol = np.repeat(tint.astype(np.uint8), 3, axis=-1)
    pol = np.concatenate([pol[:, -PAD:], pol, pol[:, :PAD]], axis=1)
    out["map/terrain/colormap_political.dds"] = write_dds(_rgba(pol))
    mini = np.asarray(Image.fromarray(cm).resize(MINIMAP_SIZE, Image.BOX))
    out["gfx/interface/minimap.dds"] = write_dds(_rgba(mini))
    return out
