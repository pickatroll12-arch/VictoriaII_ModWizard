"""Banderas de país: TGA de 32 bits, 93×64, con el origen abajo a la izquierda (wizard §14.2, H22).

Cada país tiene 5 en ``gfx/flags/``: ``<TAG>.tga`` y ``<TAG>_communist``, ``_fascist``, ``_monarchy`` y
``_republic``. ``fit_flag`` lleva una imagen cualquiera al tamaño de bandera y ``make_flag_set`` las convierte en
TGA (tipo 2, sin comprimir, descriptor ``0x08``: 8 bits de alfa y filas de abajo arriba, como las de vanilla), que
se releen con Pillow para verificarlas. Sin E/S: devuelve bytes; las escribe el guardado del proyecto.
"""

from __future__ import annotations

import io
import struct
from collections.abc import Mapping

import numpy as np
from PIL import Image

FLAG_SIZE = (93, 64)                      # (ancho, alto)
FLAG_SUFFIXES = ("", "_communist", "_fascist", "_monarchy", "_republic")
FIT_MODES = ("cover", "contain", "stretch")
TGA_TRUE_COLOR = 2
TGA_DESCRIPTOR = 0x08                     # 8 bits de alfa; bit 5 a 0 = origen abajo a la izquierda


def write_tga(rgba: np.ndarray) -> bytes:
    """TGA tipo 2 de 32 bits de ``rgba`` (``(alto, ancho, 4)`` uint8, filas de arriba abajo como
    ``numpy.asarray(Image)``); en el archivo, de abajo arriba y en BGRA."""
    rgba = np.asarray(rgba)
    if rgba.dtype != np.uint8 or rgba.ndim != 3 or rgba.shape[2] != 4 or 0 in rgba.shape[:2]:
        raise ValueError(f"se esperaba (alto, ancho, 4) uint8, no {rgba.shape} {rgba.dtype}")
    height, width = rgba.shape[:2]
    header = struct.pack("<BBBHHBHHHHBB", 0, 0, TGA_TRUE_COLOR, 0, 0, 0, 0, 0, width, height, 32, TGA_DESCRIPTOR)
    return header + np.ascontiguousarray(rgba[::-1][..., [2, 1, 0, 3]]).tobytes()


def _rgba(image: Image.Image) -> Image.Image:
    """Copia en RGBA (P con transparencia, L, LA, RGB…); los modos sin conversión directa pasan por RGB."""
    if image.mode == "RGBA":
        return image.copy()
    try:
        return image.convert("RGBA")
    except ValueError:
        return image.convert("RGB").convert("RGBA")


def _resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Remuestreo LANCZOS. Pillow (≥ 10, el mínimo del proyecto) premultiplica el alfa de una imagen RGBA al
    escalarla, así que el color de lo transparente no mancha los bordes (lo vigila una prueba)."""
    return image.resize(size, Image.LANCZOS)


def fit_flag(image: Image.Image, *, mode: str = "cover", focus: tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    """Imagen RGBA de ``FLAG_SIZE``.

    ``cover`` escala hasta cubrir y recorta alrededor de ``focus`` (fracciones de ancho y alto; (0, 0) es arriba a
    la izquierda); ``contain`` escala hasta caber y rellena con transparente, centrada; ``stretch`` deforma. Una
    imagen que ya mide 93×64 no se toca (salvo pasar a RGBA).
    """
    if mode not in FIT_MODES:
        raise ValueError(f"modo {mode!r}; los posibles son {FIT_MODES}")
    fx, fy = (min(1.0, max(0.0, float(v))) for v in focus)
    source = _rgba(image)
    width, height = FLAG_SIZE
    if source.size == FLAG_SIZE:
        return source
    if mode == "stretch":
        return _resize(source, FLAG_SIZE)
    w, h = source.size
    if mode == "cover":
        scale = max(width / w, height / h)
        size = (max(width, round(w * scale)), max(height, round(h * scale)))
        scaled = _resize(source, size)
        left, top = round((size[0] - width) * fx), round((size[1] - height) * fy)
        return scaled.crop((left, top, left + width, top + height))
    scale = min(width / w, height / h)
    size = (max(1, min(width, round(w * scale))), max(1, min(height, round(h * scale))))
    canvas = Image.new("RGBA", FLAG_SIZE, (0, 0, 0, 0))
    canvas.paste(_resize(source, size), ((width - size[0]) // 2, (height - size[1]) // 2))
    return canvas


def _verified(data: bytes, rgba: np.ndarray) -> bytes:
    """``data`` si Pillow lo relee como ``rgba``; si no, ``ValueError`` (nunca se guarda una bandera rota)."""
    with Image.open(io.BytesIO(data)) as reread:
        reread.load()
        if reread.size != (rgba.shape[1], rgba.shape[0]) or reread.mode != "RGBA" \
                or not np.array_equal(np.asarray(reread), rgba):
            raise ValueError("la bandera no se relee igual con Pillow")
    return data


def make_flag_set(images: Mapping[str, Image.Image], *, mode: str = "cover",
                  focus: tuple[float, float] = (0.5, 0.5)) -> dict[str, bytes]:
    """``{sufijo: imagen}`` → ``{sufijo: TGA}`` (sufijos de ``FLAG_SUFFIXES``), con ``fit_flag`` y verificadas."""
    unknown = [suffix for suffix in images if suffix not in FLAG_SUFFIXES]
    if unknown:
        raise ValueError(f"sufijos de bandera desconocidos: {unknown}; los posibles son {FLAG_SUFFIXES}")
    flags = {}
    for suffix in FLAG_SUFFIXES:
        if suffix in images:
            rgba = np.asarray(fit_flag(images[suffix], mode=mode, focus=focus))
            flags[suffix] = _verified(write_tga(rgba), rgba)
    return flags


# --- banderas procedurales (taller de mapas, iteración 9b) -------------------------------------------------

FLAG_PATTERNS = ("vertical", "horizontal", "cross", "nordic", "diagonal", "canton", "border", "disc")
# Variante por gobierno: el mismo país cambia de diseño con un matiz propio de cada ideología.
_VARIANT_SHIFT = {"": 0, "_communist": 3, "_fascist": 5, "_monarchy": 1, "_republic": 2}
_ACCENT = {"_communist": (190, 20, 30), "_fascist": (40, 40, 40), "_monarchy": (200, 160, 40),
           "_republic": (30, 70, 160)}


def _mix(color, other, t: float) -> tuple[int, int, int]:
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(color, other))


def procedural_flag(seed: int, colors: tuple[tuple[int, int, int], ...], *, suffix: str = "") -> Image.Image:
    """Una bandera de 93×64 dibujada con formas simples (franjas, cruces, cantón, borde o disco), estable para una
    semilla. ``colors`` son 2 o 3 colores del país; ``suffix`` (``_communist``…) da la variante de ese gobierno:
    el patrón se desplaza y lleva un acento de la ideología, para que las 5 banderas del país no sean iguales."""
    import random

    if suffix not in _VARIANT_SHIFT:
        raise ValueError(f"sufijo de bandera desconocido: {suffix!r}")
    rnd = random.Random(seed)
    cols = [tuple(int(v) for v in c) for c in colors] or [(200, 200, 200)]
    while len(cols) < 3:
        cols.append(_mix(cols[-1], (255, 255, 255) if sum(cols[-1]) < 384 else (0, 0, 0), 0.6))
    base = rnd.randrange(len(FLAG_PATTERNS))
    pattern = FLAG_PATTERNS[(base + _VARIANT_SHIFT[suffix]) % len(FLAG_PATTERNS)]
    if suffix in _ACCENT:
        cols[2] = _mix(cols[2], _ACCENT[suffix], 0.75)
    w, h = FLAG_SIZE
    img = np.zeros((h, w, 3), np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    a, b, c = (np.array(x, np.uint8) for x in cols[:3])
    img[:] = a
    if pattern == "vertical":
        img[:, w // 3:2 * w // 3] = b
        img[:, 2 * w // 3:] = c
    elif pattern == "horizontal":
        img[h // 3:2 * h // 3] = b
        img[2 * h // 3:] = c
    elif pattern == "cross":
        img[(abs(xx - w // 2) < 6) | (abs(yy - h // 2) < 6)] = b
        img[(abs(xx - w // 2) < 2) | (abs(yy - h // 2) < 2)] = c
    elif pattern == "nordic":
        img[(abs(xx - w // 3) < 7) | (abs(yy - h // 2) < 7)] = b
        img[(abs(xx - w // 3) < 3) | (abs(yy - h // 2) < 3)] = c
    elif pattern == "diagonal":
        img[yy * w > xx * h] = b
        img[abs(yy * w - xx * h) < 5 * w] = c
    elif pattern == "canton":
        img[h // 2:] = b
        img[:h // 2, :w // 2] = c
    elif pattern == "border":
        img[(xx < 7) | (xx >= w - 7) | (yy < 7) | (yy >= h - 7)] = b
        img[(abs(xx - w // 2) < 10) & (abs(yy - h // 2) < 10)] = c
    else:  # disc
        img[(xx - w // 2) ** 2 + (yy - h // 2) ** 2 < (h // 3) ** 2] = b
        img[(xx - w // 2) ** 2 + (yy - h // 2) ** 2 < (h // 6) ** 2] = c
    rgba = np.dstack([img, np.full((h, w), 255, np.uint8)])
    return Image.fromarray(rgba, "RGBA")


def procedural_flag_set(seed: int, colors: tuple[tuple[int, int, int], ...]) -> dict[str, bytes]:
    """Las 5 banderas TGA de un país (``FLAG_SUFFIXES``), verificadas con Pillow."""
    return make_flag_set({suffix: procedural_flag(seed, colors, suffix=suffix) for suffix in FLAG_SUFFIXES},
                         mode="stretch")
