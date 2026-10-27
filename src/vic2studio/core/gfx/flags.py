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
