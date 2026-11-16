"""Imágenes del juego que el modder importa (wizard §17.3): eventos, decisiones, tecnologías, noticias,
pantallas de carga y sprites de interfaz.

Cada familia vive en una carpeta con un formato y un tamaño: los de vanilla son TGA de 521×203 para los
eventos, DDS de 95×95 para las decisiones, TGA de 165×185 para las tecnologías, DDS de 1024×1024 para las
pantallas de carga y TGA de 93×64 para las banderas. El tamaño esperado de una carpeta se calcula con el más
común de los archivos que ya tiene (``common_size``, que solo lee cabeceras); el de la tabla es el de reserva
cuando no hay juego configurado. ``fit_image`` encuadra una imagen cualquiera y ``encode_image`` la escribe
como DDS A8R8G8B8 sin comprimir o TGA de 32 bits, y la relee para no guardar nunca una imagen rota. Sin E/S.
"""

from __future__ import annotations

import io
import struct
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import numpy as np
from PIL import Image

from ..vfs.paths import VPath
from .dds import DDS_MAGIC, DdsError, dds_info, read_dds, write_dds
from .flags import FIT_MODES, write_tga

FORMAT_DDS = "dds"
FORMAT_TGA = "tga"
FORMATS = (FORMAT_DDS, FORMAT_TGA)
HEADER_BYTES = 128                       # basta para la cabecera de DDS, TGA, PNG y BMP


@dataclass(frozen=True)
class PictureSlot:
    """Una familia de imágenes: su carpeta, su formato y el tamaño de reserva (el más común de vanilla)."""

    key: str
    folder: str
    format: str
    size: tuple[int, int]
    recursive: bool = False


PICTURE_SLOTS: tuple[PictureSlot, ...] = (
    PictureSlot("event", "gfx/pictures/events", FORMAT_TGA, (521, 203)),
    PictureSlot("decision", "gfx/pictures/decisions", FORMAT_DDS, (95, 95)),
    PictureSlot("flag", "gfx/flags", FORMAT_TGA, (93, 64)),
    PictureSlot("tech", "gfx/pictures/tech", FORMAT_TGA, (165, 185)),
    PictureSlot("news", "gfx/pictures/news", FORMAT_DDS, (521, 203)),
    PictureSlot("loadingscreen", "gfx/loadingscreens", FORMAT_DDS, (1024, 1024)),
)
IMAGE_SUFFIXES = (".tga", ".dds", ".png", ".bmp", ".jpg", ".jpeg")


def slot(key: str) -> PictureSlot:
    for candidate in PICTURE_SLOTS:
        if candidate.key == key:
            return candidate
    raise KeyError(key)


def slot_of(rel: VPath | str) -> PictureSlot | None:
    """La familia a la que pertenece una ruta (por su carpeta), o None."""
    rel = VPath.of(rel)
    for candidate in PICTURE_SLOTS:
        if rel.is_under(candidate.folder):
            return candidate
    return None


def image_size(header: bytes) -> tuple[int, int] | None:
    """Ancho y alto de una imagen a partir del principio del archivo (DDS, TGA, PNG y BMP); None si no se
    reconoce. No decodifica los píxeles."""
    if len(header) >= 24 and header[:4] == DDS_MAGIC:
        try:
            info = dds_info(header)
        except DdsError:
            return None
        return info.width, info.height
    if len(header) >= 24 and header[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", header[16:24])
        return width, height
    if len(header) >= 26 and header[:2] == b"BM":
        width, height = struct.unpack("<ii", header[18:26])
        return width, abs(height)
    if len(header) >= 18 and header[2] in (1, 2, 3, 9, 10, 11) and header[1] in (0, 1):
        width, height = struct.unpack("<HH", header[12:16])
        if width and height and header[16] in (8, 15, 16, 24, 32):
            return width, height
    return None


def common_size(headers: Iterable[bytes | None]) -> tuple[int, int] | None:
    """El tamaño más repetido entre las cabeceras (el menor en caso de empate, para que sea estable)."""
    counts: Counter[tuple[int, int]] = Counter()
    for header in headers:
        size = image_size(header) if header else None
        if size is not None:
            counts[size] += 1
    if not counts:
        return None
    best = max(counts.values())
    return min(size for size, count in counts.items() if count == best)


def expected_size(candidate: PictureSlot, read_header: Callable[[VPath], bytes | None],
                  rels: Iterable[VPath]) -> tuple[int, int]:
    """Tamaño esperado de una familia: el más común de sus archivos efectivos o, sin ellos, el de la tabla."""
    return common_size(read_header(rel) for rel in rels) or candidate.size


def _rgba(image: Image.Image) -> Image.Image:
    if image.mode == "RGBA":
        return image.copy()
    try:
        return image.convert("RGBA")
    except ValueError:
        return image.convert("RGB").convert("RGBA")


def fit_image(image: Image.Image, size: tuple[int, int] | None = None, *, mode: str = "cover",
              focus: tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    """Imagen RGBA de ``size`` (None: su tamaño). ``cover`` escala hasta cubrir y recorta alrededor de
    ``focus``; ``contain`` escala hasta caber y rellena con transparente; ``stretch`` deforma."""
    if mode not in FIT_MODES:
        raise ValueError(f"modo {mode!r}; los posibles son {FIT_MODES}")
    source = _rgba(image)
    if size is None or source.size == tuple(size):
        return source
    width, height = int(size[0]), int(size[1])
    if width <= 0 or height <= 0:
        raise ValueError(f"tamaño {size}")
    fx, fy = (min(1.0, max(0.0, float(v))) for v in focus)
    if mode == "stretch":
        return source.resize((width, height), Image.LANCZOS)
    w, h = source.size
    if mode == "cover":
        scale = max(width / w, height / h)
        scaled_size = (max(width, round(w * scale)), max(height, round(h * scale)))
        scaled = source.resize(scaled_size, Image.LANCZOS)
        left, top = round((scaled_size[0] - width) * fx), round((scaled_size[1] - height) * fy)
        return scaled.crop((left, top, left + width, top + height))
    scale = min(width / w, height / h)
    scaled_size = (max(1, min(width, round(w * scale))), max(1, min(height, round(h * scale))))
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.paste(source.resize(scaled_size, Image.LANCZOS),
                 ((width - scaled_size[0]) // 2, (height - scaled_size[1]) // 2))
    return canvas


def encode_image(image: Image.Image, fmt: str = FORMAT_DDS) -> bytes:
    """``image`` como DDS A8R8G8B8 sin comprimir o TGA de 32 bits. Se relee antes de devolverla: si no da los
    mismos píxeles, ``ValueError`` (nunca se guarda una imagen que el juego no leería)."""
    rgba = np.ascontiguousarray(np.asarray(_rgba(image)))
    if fmt == FORMAT_DDS:
        data = write_dds(rgba)
        reread = read_dds(data).rgba
    elif fmt == FORMAT_TGA:
        data = write_tga(rgba)
        with Image.open(io.BytesIO(data)) as check:
            reread = np.asarray(check.convert("RGBA"))
    else:
        raise ValueError(f"formato {fmt!r}; los posibles son {FORMATS}")
    if reread.shape != rgba.shape or not np.array_equal(reread, rgba):
        raise ValueError("la imagen no se relee igual")
    return data


def import_image(image: Image.Image, size: tuple[int, int] | None, fmt: str, *, mode: str = "cover",
                 focus: tuple[float, float] = (0.5, 0.5)) -> bytes:
    """Encuadra ``image`` a ``size`` y la codifica en ``fmt``: lo que hace «Importar imagen»."""
    return encode_image(fit_image(image, size, mode=mode, focus=focus), fmt)
