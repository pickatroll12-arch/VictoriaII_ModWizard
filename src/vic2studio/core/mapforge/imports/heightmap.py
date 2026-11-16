"""Importar un mapa de alturas (wizard §18.6): PNG o BMP en gris de 8 o 16 bits, de cualquier tamaño.

La escala del taller es 0–100 con el mar por debajo de ``SEA_LEVEL`` (20). Un gris genérico se estira a 0–100
(``v / máximo``). El PNG del editor de alturas de FMG guarda ``v = h/100·255`` en tierra y el agua dividida por
1,5: se reconoce porque **no tiene valores entre 35 y 50** (el hueco que deja la división) y se invierte.

Las imágenes se reciben en el orden del juego (fila 0 = ``y`` 0); voltear es cosa de quien llama (``bitmaps``).
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from ..world import SEA_LEVEL

FMG_GAP = (35, 51)          # valores que el PNG de FMG no usa (agua ÷ 1,5 por debajo, tierra por encima)
FMG_MIN_PIXELS = 1000


def load_gray(data: bytes) -> tuple[np.ndarray, str]:
    """``(gris, modo)`` de los bytes de una imagen, en el orden de la imagen (fila 0 = arriba). 16 bits se conserva
    como ``uint16``; el resto se convierte a ``L``."""
    img = Image.open(io.BytesIO(data))
    mode = img.mode
    if mode in ("I;16", "I;16B", "I;16L", "I"):
        arr = np.asarray(img, dtype=np.int64)
        return np.clip(arr, 0, 65535).astype(np.uint16), mode
    return np.asarray(img.convert("L"), dtype=np.uint8), mode


def is_fmg(gray: np.ndarray) -> bool:
    """El PNG del editor de alturas de FMG: 8 bits, con agua y tierra y nada en el hueco ``FMG_GAP``."""
    if gray.dtype != np.uint8 or gray.size < FMG_MIN_PIXELS:
        return False
    counts = np.bincount(gray.ravel(), minlength=256)
    lo, hi = FMG_GAP
    return bool(counts[:lo].sum() > 0 and counts[hi:].sum() > 0 and counts[lo:hi].sum() == 0)


def to_heights(gray: np.ndarray, *, fmg: bool | None = None) -> np.ndarray:
    """Alturas 0–100 (``float64``) de un gris. ``fmg=None`` lo detecta."""
    if fmg is None:
        fmg = is_fmg(gray)
    g = gray.astype(np.float64)
    if fmg:
        lo, hi = FMG_GAP
        return np.where(g >= hi, g / 255 * 100, g * 1.5 / 255 * 100)
    top = 65535.0 if gray.dtype == np.uint16 else 255.0
    return g / top * 100


def resample(heights: np.ndarray, width: int, height: int) -> np.ndarray:
    """Remuestreo bilineal a ``width × height`` (sin cambiar el orden de las filas)."""
    if heights.shape == (height, width):
        return heights.astype(np.float64)
    img = Image.fromarray(heights.astype(np.float32), "F").resize((width, height), Image.BILINEAR)
    return np.asarray(img, dtype=np.float64)


def heights_from_image(img: np.ndarray, cells: np.ndarray, size: tuple[int, int], *,
                       fmg: bool | None = None) -> np.ndarray:
    """Altura por celda (``cells`` = puntos ``(n, 2)`` en coordenadas del juego de un mapa ``size``): el píxel más
    cercano del gris ``img`` (orden del juego), en la escala 0–100 del taller."""
    W, H = size
    h = to_heights(img, fmg=fmg)
    ih, iw = h.shape
    x = np.clip((cells[:, 0] / W * iw).astype(np.int64), 0, iw - 1)
    y = np.clip((cells[:, 1] / H * ih).astype(np.int64), 0, ih - 1)
    return h[y, x]


def pseudo_relief(categories: np.ndarray, water: np.ndarray, *, passes: int = 3) -> np.ndarray:
    """Pseudorrelieve de un ``terrain.bmp`` (§18.6): montaña 75, colinas 50, resto 30 y agua 10, suavizado 3 veces
    con una caja 3×3. ``categories`` son los índices de ``world.CATS`` por píxel."""
    from ..world import CAT_INDEX

    h = np.full(categories.shape, 30.0, np.float32)
    h[categories == CAT_INDEX["mountain"]] = 75.0
    h[categories == CAT_INDEX["hills"]] = 50.0
    h[water] = 10.0
    for _ in range(passes):
        # Caja 3×3 separable (filas y luego columnas), con los bordes repetidos.
        p = np.pad(h, ((0, 0), (1, 1)), mode="edge")
        r = p[:, :-2] + p[:, 1:-1] + p[:, 2:]
        p = np.pad(r, ((1, 1), (0, 0)), mode="edge")
        h = (p[:-2] + p[1:-1] + p[2:]) / np.float32(9.0)
    # La costa la decide la importación, no el suavizado.
    h = np.where(water, np.minimum(h, SEA_LEVEL - 1), np.maximum(h, SEA_LEVEL + 1))
    return h


__all__ = ["load_gray", "is_fmg", "to_heights", "resample", "heights_from_image", "pseudo_relief"]
