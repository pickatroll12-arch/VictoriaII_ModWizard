"""Códec BMP propio con numpy: ``write_bmp(read_bmp(b)) == b`` (wizard D11, §6.1, §16.1, H1).

Los mapas del juego son BMP sin compresión: ``provinces.bmp`` de 24 bits y ``terrain.bmp``/``rivers.bmp`` de 8
bits con paleta, todos de abajo arriba (alto positivo) y con 2 bytes de más tras los píxeles. Pillow los lee,
pero no garantiza volver a escribirlos igual, así que aquí se guarda todo lo que no son píxeles —cabeceras
enteras, paleta, el hueco hasta los píxeles, el contenido del relleno de cada fila y lo que haya al final— y al
escribir solo se regeneran los píxeles (I3).

``BmpImage.pixels`` tiene la fila 0 arriba, como ``numpy.asarray(PIL.Image.open(...))``: en los mapas del juego
esa fila es la ``y`` del motor (H1); la vista se voltea en un solo sitio (``raster.to_display_row``, iteración 5).
Sin E/S: trabaja con bytes, sin bucles por píxel en Python.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

BMP_UNSUPPORTED = "bmp_unsupported"
BMP_TRUNCATED = "bmp_truncated"
BMP_NOT_BMP = "bmp_not_bmp"
BMP_SHAPE = "bmp_shape"

FILE_HEADER_SIZE = 14
INFO_HEADER_SIZE = 40
BI_RGB = 0
PIXELS_PER_METER = 2834      # la de los BMP de vanilla (72 ppp)


class BmpError(ValueError):
    """BMP que este códec no admite (comprimido, otra profundidad…) o roto; ``code`` dice cuál."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)

    def __reduce__(self):
        return (type(self), (self.code, self.detail))


@dataclass(eq=False)
class BmpImage:
    """Un BMP leído. ``pixels`` es ``(alto, ancho, 3)`` RGB en 24 bits o ``(alto, ancho)`` con índices en 8;
    ``palette`` es ``(n, 4)`` tal como está en el archivo (BGRA), o None en 24 bits. El resto es lo que hace falta
    para volver a escribir los mismos bytes."""

    width: int
    height: int
    bits: int
    pixels: np.ndarray
    palette: np.ndarray | None
    top_down: bool                       # alto negativo en la cabecera (filas de arriba abajo en el archivo)
    _prefix: bytes                       # desde el principio hasta los píxeles (cabeceras, paleta y hueco)
    _palette_offset: int
    _padding: np.ndarray                 # (alto, relleno) en el orden del archivo
    _trailer: bytes                      # lo que hay tras los píxeles


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _i32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<i", data, offset)[0]


def _stride(width: int, bits: int) -> int:
    return ((width * bits + 31) // 32) * 4


def read_bmp_header(data: bytes) -> tuple[int, int, int]:
    """(ancho, alto, bits por píxel) sin decodificar los píxeles (``GameRules.map_size``)."""
    if len(data) < FILE_HEADER_SIZE + 16 or data[:2] != b"BM":
        raise BmpError(BMP_NOT_BMP, "no empieza por «BM»" if data[:2] != b"BM" else "cabecera incompleta")
    return _i32(data, 18), abs(_i32(data, 22)), _u16(data, 28)


def read_bmp(data: bytes) -> BmpImage:
    """BMP sin compresión de 24 bits o de 8 bits con paleta (``BmpError`` si es otro)."""
    width, height, bits = read_bmp_header(data)
    header_size = _u32(data, 14)
    if header_size < INFO_HEADER_SIZE or len(data) < FILE_HEADER_SIZE + header_size:
        raise BmpError(BMP_UNSUPPORTED, f"cabecera de {header_size} bytes")
    compression = _u32(data, 30)
    if bits not in (8, 24) or compression != BI_RGB:
        raise BmpError(BMP_UNSUPPORTED, f"{bits} bits, compresión {compression}")
    if width <= 0 or height <= 0:
        raise BmpError(BMP_UNSUPPORTED, f"tamaño {width}x{height}")
    top_down = _i32(data, 22) < 0
    offset = _u32(data, 10)
    palette_offset = FILE_HEADER_SIZE + header_size
    if offset < palette_offset or offset > len(data):
        raise BmpError(BMP_TRUNCATED, f"los píxeles empiezan en {offset}")
    palette = None
    if bits == 8:
        used = _u32(data, 46) or 256
        entries = min(used, 256, (offset - palette_offset) // 4)
        palette = np.frombuffer(data, np.uint8, entries * 4, palette_offset).reshape(entries, 4).copy()
    stride = _stride(width, bits)
    row_bytes = width * bits // 8
    end = offset + stride * height
    if end > len(data):
        raise BmpError(BMP_TRUNCATED, f"faltan {end - len(data)} bytes de píxeles")
    rows = np.frombuffer(data, np.uint8, stride * height, offset).reshape(height, stride)
    stored = rows[:, :row_bytes]
    if bits == 24:
        stored = stored.reshape(height, width, 3)[:, :, ::-1]   # BGR → RGB
    pixels = np.ascontiguousarray(stored if top_down else stored[::-1])
    return BmpImage(width, height, bits, pixels, palette, top_down, bytes(data[:offset]), palette_offset,
                    rows[:, row_bytes:].copy(), bytes(data[end:]))


def write_bmp(img: BmpImage) -> bytes:
    """Los bytes de ``img``: los mismos que se leyeron salvo los píxeles (y la paleta) que hayan cambiado."""
    expected = (img.height, img.width, 3) if img.bits == 24 else (img.height, img.width)
    pixels = np.asarray(img.pixels)
    if pixels.shape != expected or pixels.dtype != np.uint8:
        raise BmpError(BMP_SHAPE, f"píxeles {pixels.shape} {pixels.dtype}, se esperaba {expected} uint8"
                       " (para otro tamaño, new_bmp)")
    prefix = img._prefix
    if img.palette is not None:
        palette = np.ascontiguousarray(img.palette, dtype=np.uint8).tobytes()
        start = img._palette_offset
        prefix = prefix[:start] + palette + prefix[start + len(palette):]
    stride = _stride(img.width, img.bits)
    row_bytes = img.width * img.bits // 8
    size = len(prefix) + stride * img.height
    # Un solo búfer: los píxeles se copian directamente a su sitio (sin copias intermedias de 36 MB).
    out = np.empty(size + len(img._trailer), np.uint8)
    out[:len(prefix)] = np.frombuffer(prefix, np.uint8)
    rows = out[len(prefix):size].reshape(img.height, stride)
    stored = pixels if img.top_down else pixels[::-1]
    if img.bits == 24:
        rows[:, :row_bytes].reshape(img.height, img.width, 3)[...] = stored[:, :, ::-1]
    else:
        rows[:, :row_bytes] = stored
    rows[:, row_bytes:] = img._padding
    out[size:] = np.frombuffer(img._trailer, np.uint8)
    return out.tobytes()


def new_bmp(pixels: np.ndarray, palette: np.ndarray | None = None) -> bytes:
    """BMP nuevo y estándar: 24 bits con ``(alto, ancho, 3)`` RGB, u 8 bits con ``(alto, ancho)`` y ``palette``
    ``(n, 3)`` RGB o ``(n, 4)`` BGRA (hasta 256). Cabecera de 54 B (más la paleta, completada a 256 entradas:
    1 078 B en 8 bits, como los del juego), filas de abajo arriba y relleno a 4 bytes con ceros."""
    pixels = np.asarray(pixels)
    if pixels.dtype != np.uint8 or pixels.ndim not in (2, 3) or (pixels.ndim == 3 and pixels.shape[2] != 3):
        raise BmpError(BMP_SHAPE, f"píxeles {pixels.shape} {pixels.dtype}")
    height, width = pixels.shape[:2]
    if width == 0 or height == 0:
        raise BmpError(BMP_SHAPE, "imagen vacía")
    bits = 24 if pixels.ndim == 3 else 8
    table = b""
    if bits == 8:
        if palette is None:
            raise BmpError(BMP_SHAPE, "una imagen de 8 bits necesita paleta")
        palette = np.asarray(palette, dtype=np.uint8)
        if palette.ndim != 2 or palette.shape[1] not in (3, 4) or not 0 < len(palette) <= 256:
            raise BmpError(BMP_SHAPE, f"paleta {palette.shape}")
        if palette.shape[1] == 3:   # RGB → BGRA con el cuarto byte a 0
            palette = np.concatenate([palette[:, ::-1], np.zeros((len(palette), 1), np.uint8)], axis=1)
        full = np.zeros((256, 4), np.uint8)
        full[:len(palette)] = palette
        table = full.tobytes()
    stride = _stride(width, bits)
    stored = pixels[::-1]
    if bits == 24:
        stored = stored[:, :, ::-1].reshape(height, width * 3)
    pad = stride - stored.shape[1]
    if pad:
        stored = np.concatenate([stored, np.zeros((height, pad), np.uint8)], axis=1)
    image = np.ascontiguousarray(stored).tobytes()
    offset = FILE_HEADER_SIZE + INFO_HEADER_SIZE + len(table)
    header = struct.pack("<2sIHHI", b"BM", offset + len(image), 0, 0, offset)
    info = struct.pack("<IiiHHIIiiII", INFO_HEADER_SIZE, width, height, 1, bits, BI_RGB, len(image),
                       PIXELS_PER_METER, PIXELS_PER_METER, 0, 0)
    return header + info + table + image
