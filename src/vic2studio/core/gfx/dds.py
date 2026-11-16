"""DDS: escritor A8R8G8B8 sin comprimir con las cabeceras de vanilla, y lector (wizard D11, §17.3, §18.5, H8, H23).

Pillow lee los DDS del juego (también DXT1/3/5), pero no garantiza escribirlos, así que el escritor es propio:
A8R8G8B8 sin comprimir con los mismos campos que ``map/terrain/colormap.dds`` (``flags`` ``0x81007``,
``pitchOrLinearSize`` = ancho·alto·4, ``caps`` ``0x1000``) y, con mips, que ``colormap_water.dds`` (``flags``
``0xA1007``, ``caps`` ``0x401008`` y niveles hasta 1×1). El lector decodifica él mismo los DDS sin comprimir de 24
y 32 bits a partir de sus máscaras (A8R8G8B8, X8R8G8B8, A8B8G8R8 y R8G8B8, los cuatro que hay en vanilla) y pasa
los comprimidos a Pillow; Pillow 10.0 y 10.1 (dentro del mínimo del proyecto) leen X8R8G8B8 como si fuera de 24 bits
y devuelven los colores corridos. Sin E/S: trabaja con bytes.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass

import numpy as np

DDS_MAGIC = b"DDS "
HEADER_SIZE = 128                       # "DDS " + DDS_HEADER (124)

DDSD_CAPS, DDSD_HEIGHT, DDSD_WIDTH, DDSD_PIXELFORMAT = 0x1, 0x2, 0x4, 0x1000
DDSD_MIPMAPCOUNT, DDSD_LINEARSIZE = 0x20000, 0x80000
DDPF_ALPHAPIXELS, DDPF_FOURCC, DDPF_RGB = 0x1, 0x4, 0x40
DDSCAPS_COMPLEX, DDSCAPS_TEXTURE, DDSCAPS_MIPMAP = 0x8, 0x1000, 0x400000

FLAGS = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT | DDSD_LINEARSIZE          # 0x81007
FLAGS_MIPS = FLAGS | DDSD_MIPMAPCOUNT                                                     # 0xA1007
CAPS = DDSCAPS_TEXTURE                                                                    # 0x1000
CAPS_MIPS = DDSCAPS_COMPLEX | DDSCAPS_TEXTURE | DDSCAPS_MIPMAP                            # 0x401008
ARGB_MASKS = (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
COMPRESSED = ("DXT1", "DXT3", "DXT5")

DDS_NOT_DDS = "dds_not_dds"
DDS_UNSUPPORTED = "dds_unsupported"
DDS_TRUNCATED = "dds_truncated"
DDS_SHAPE = "dds_shape"


class DdsError(ValueError):
    """DDS que este módulo no sabe leer o escribir; ``code`` dice por qué."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)

    def __reduce__(self):
        return (type(self), (self.code, self.detail))


@dataclass(frozen=True)
class DdsInfo:
    width: int
    height: int
    flags: int
    pitch: int                          # pitchOrLinearSize
    mip_count: int                      # dwMipMapCount tal cual (0 si no hay)
    pf_flags: int
    fourcc: str | None                  # "DXT1"… o None si no es comprimido
    bit_count: int
    masks: tuple[int, int, int, int]    # R, G, B, A
    caps: int
    caps2: int


@dataclass(frozen=True)
class DdsImage:
    rgba: np.ndarray                    # nivel 0, (alto, ancho, 4) uint8, filas de arriba abajo
    info: DdsInfo


def dds_info(data: bytes) -> DdsInfo:
    """Los campos de la cabecera, sin decodificar nada."""
    if len(data) < HEADER_SIZE or data[:4] != DDS_MAGIC:
        raise DdsError(DDS_NOT_DDS, "no empieza por «DDS »" if data[:4] != DDS_MAGIC else "cabecera incompleta")
    flags, height, width, pitch, _depth, mips = struct.unpack_from("<IIIIII", data, 8)
    pf_flags, = struct.unpack_from("<I", data, 80)
    fourcc_raw = data[84:88]
    bit_count, red, green, blue, alpha = struct.unpack_from("<IIIII", data, 88)
    caps, caps2 = struct.unpack_from("<II", data, 108)
    fourcc = fourcc_raw.decode("latin-1") if pf_flags & DDPF_FOURCC else None
    return DdsInfo(width, height, flags, pitch, mips, pf_flags, fourcc, bit_count, (red, green, blue, alpha),
                   caps, caps2)


def _byte_of(mask: int, bit_count: int) -> int | None:
    """Byte del píxel (en memoria, little-endian) que ocupa ``mask``; None si no es un byte entero."""
    for byte in range(bit_count // 8):
        if mask == 0xFF << (8 * byte):
            return byte
    return None


def read_dds(data: bytes) -> DdsImage:
    """Nivel 0 en RGBA. Sin comprimir (24 o 32 bits con máscaras de un byte por canal) lo decodifica aquí; DXT1/3/5
    con Pillow."""
    info = dds_info(data)
    width, height = info.width, info.height
    if width <= 0 or height <= 0:
        raise DdsError(DDS_UNSUPPORTED, f"tamaño {width}x{height}")
    if info.fourcc is not None:
        if info.fourcc not in COMPRESSED:
            raise DdsError(DDS_UNSUPPORTED, f"FourCC {info.fourcc!r}")
        from PIL import Image

        try:
            with Image.open(io.BytesIO(data)) as image:
                rgba = np.asarray(image.convert("RGBA")).copy()
        except (OSError, ValueError) as exc:
            raise DdsError(DDS_TRUNCATED, str(exc)) from None
        return DdsImage(rgba, info)
    if not info.pf_flags & DDPF_RGB or info.bit_count not in (24, 32):
        raise DdsError(DDS_UNSUPPORTED, f"formato {info.pf_flags:#x} de {info.bit_count} bits")
    size = info.bit_count // 8
    red, green, blue, alpha = (_byte_of(m, info.bit_count) for m in info.masks)
    has_alpha = bool(info.pf_flags & DDPF_ALPHAPIXELS) and info.masks[3]
    if None in (red, green, blue) or (has_alpha and alpha is None):
        raise DdsError(DDS_UNSUPPORTED, "máscaras " + " ".join(f"{m:#x}" for m in info.masks))
    count = width * height * size
    if len(data) < HEADER_SIZE + count:
        raise DdsError(DDS_TRUNCATED, f"faltan {HEADER_SIZE + count - len(data)} bytes")
    pixels = np.frombuffer(data, np.uint8, count, HEADER_SIZE).reshape(height, width, size)
    rgba = np.empty((height, width, 4), np.uint8)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = pixels[..., red], pixels[..., green], pixels[..., blue]
    rgba[..., 3] = pixels[..., alpha] if has_alpha else 255
    return DdsImage(rgba, info)


def _halve(level: np.ndarray) -> np.ndarray:
    """Nivel siguiente: la mitad de cada lado (redondeando hacia abajo, mínimo 1) con un filtro de caja; con un
    lado impar, la última fila o columna se descarta (como hacen las herramientas de DirectX)."""
    height, width = level.shape[:2]
    values = level.astype(np.uint16)
    if height > 1:
        rows = height // 2
        values = values[0:rows * 2:2] + values[1:rows * 2:2]
    else:
        values = values * 2
    if width > 1:
        cols = width // 2
        values = values[:, 0:cols * 2:2] + values[:, 1:cols * 2:2]
    else:
        values = values * 2
    return ((values + 2) // 4).astype(np.uint8)


def mip_levels(rgba: np.ndarray) -> list[np.ndarray]:
    """Los niveles de ``rgba`` hasta 1×1, el original primero."""
    levels = [rgba]
    while levels[-1].shape[0] > 1 or levels[-1].shape[1] > 1:
        levels.append(_halve(levels[-1]))
    return levels


def write_dds(rgba: np.ndarray, *, mipmaps: bool = False) -> bytes:
    """DDS A8R8G8B8 sin comprimir de ``rgba`` (``(alto, ancho, 4)`` uint8, filas de arriba abajo)."""
    rgba = np.asarray(rgba)
    if rgba.dtype != np.uint8 or rgba.ndim != 3 or rgba.shape[2] != 4 or 0 in rgba.shape[:2]:
        raise DdsError(DDS_SHAPE, f"se esperaba (alto, ancho, 4) uint8, no {rgba.shape} {rgba.dtype}")
    height, width = rgba.shape[:2]
    levels = mip_levels(rgba) if mipmaps else [rgba]
    header = struct.pack(
        "<4sIIIIIII44sII4sIIIIIIIIII",
        DDS_MAGIC, 124, FLAGS_MIPS if mipmaps else FLAGS, height, width, width * height * 4, 0,
        len(levels) if mipmaps else 0, bytes(44),
        32, DDPF_RGB | DDPF_ALPHAPIXELS, bytes(4), 32, *ARGB_MASKS,
        CAPS_MIPS if mipmaps else CAPS, 0, 0, 0, 0)
    body = [np.ascontiguousarray(level[..., [2, 1, 0, 3]]).tobytes() for level in levels]   # RGBA → BGRA
    return header + b"".join(body)


def write_dxt3(rgb: np.ndarray) -> bytes:
    """DXT3 sin mips (como ``colormap_no_shadow.dds`` de vanilla), con un codificador numpy propio: alfa explícito
    0xF y color BC1 de 4 niveles con extremos = mínimo y máximo por canal de cada bloque 4×4 (wizard §18.5).
    ``rgb`` es ``(alto, ancho, 3)`` uint8 con alto y ancho múltiplos de 4. Medido: error medio de 1,2–1,4 por canal
    al releerlo con Pillow [p7]."""
    rgb = np.asarray(rgb)
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.shape[0] % 4 or rgb.shape[1] % 4 \
            or 0 in rgb.shape[:2]:
        raise DdsError(DDS_SHAPE, f"se esperaba (alto, ancho, 3) uint8 múltiplo de 4, no {rgb.shape} {rgb.dtype}")
    h, w = rgb.shape[:2]
    b = rgb.reshape(h // 4, 4, w // 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3).astype(np.int32)
    lo = b.min(1)
    hi = b.max(1)

    def to565(c):
        return ((c[:, 0] >> 3) << 11) | ((c[:, 1] >> 2) << 5) | (c[:, 2] >> 3)

    def from565(v):
        r = (v >> 11) & 31
        g = (v >> 5) & 63
        bb = v & 31
        return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (bb << 3) | (bb >> 2)], 1)

    c0 = to565(hi)
    c1 = to565(lo)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    eq = c0 == c1                                   # bloque liso: c0 > c1 para el modo de 4 colores
    c0 = np.where(eq & (c0 < 0xFFFF), c0 + 1, c0)
    c1 = np.where(eq & (c0 == 0xFFFF) & (c1 > 0), c1 - 1, c1)
    e0 = from565(c0)
    e1 = from565(c1)
    pal = np.stack([e0, e1, (2 * e0 + e1) // 3, (e0 + 2 * e1) // 3], 1)
    d = ((b[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)
    idx = d.argmin(-1).astype(np.uint32)
    bits = (idx << (2 * np.arange(16, dtype=np.uint32))).sum(1).astype(np.uint32)
    nb = b.shape[0]
    out = np.zeros((nb, 16), np.uint8)
    out[:, 0:8] = 0xFF
    out[:, 8:10] = c0.astype("<u2").view(np.uint8).reshape(-1, 2)
    out[:, 10:12] = c1.astype("<u2").view(np.uint8).reshape(-1, 2)
    out[:, 12:16] = bits.astype("<u4").view(np.uint8).reshape(-1, 4)
    header = struct.pack(
        "<4sIIIIIII44sII4sIIIIIIIIII",
        DDS_MAGIC, 124, FLAGS, h, w, nb * 16, 0, 0, bytes(44),
        32, DDPF_FOURCC, b"DXT3", 0, 0, 0, 0, 0,
        CAPS, 0, 0, 0, 0)
    return header + out.tobytes()
