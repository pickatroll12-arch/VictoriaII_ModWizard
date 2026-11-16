"""Texturas del juego para las vistas previas (wizard §17.1): DDS y TGA a imagen RGBA, con caché.

Los DDS sin comprimir los decodifica ``core/gfx/dds.py`` (también DXT1/3/5 a través de Pillow); el resto de
formatos (TGA, PNG, BMP…) los abre Pillow. ``split_frame`` recorta un fotograma de una tira horizontal
(``noOfFrames``) y ``nine_slice`` estira un ``corneredTileSpriteType`` conservando sus esquinas
(``borderSize``). La caché es LRU por ruta y huella, acotada en número de imágenes: el arte se lee de la
instalación del usuario y nunca se copia al repositorio.
"""

from __future__ import annotations

import io
from collections import OrderedDict
from collections.abc import Callable

from PIL import Image

from ..gfx.dds import DDS_MAGIC, DdsError, read_dds
from ..vfs.paths import VPath

DEFAULT_CACHE_SIZE = 256


class TextureError(ValueError):
    """La textura no se puede decodificar."""


def load_image(data: bytes) -> Image.Image:
    """``data`` (DDS, TGA, PNG…) como imagen RGBA; ``TextureError`` si no se entiende."""
    if data[:4] == DDS_MAGIC:
        try:
            return Image.fromarray(read_dds(data).rgba, "RGBA")
        except DdsError as exc:
            raise TextureError(str(exc)) from None
    try:
        with Image.open(io.BytesIO(data)) as image:
            return image.convert("RGBA")
    except (OSError, ValueError, SyntaxError) as exc:
        raise TextureError(str(exc)) from None


def frame_box(size: tuple[int, int], frames: int, index: int = 0) -> tuple[int, int, int, int]:
    """Caja ``(x0, y0, x1, y1)`` del fotograma ``index`` de una tira horizontal de ``frames`` fotogramas."""
    frames = max(1, frames)
    index = min(max(0, index), frames - 1)
    width = size[0] // frames
    return index * width, 0, (index + 1) * width if width else size[0], size[1]


def split_frame(image: Image.Image, frames: int, index: int = 0) -> Image.Image:
    """El fotograma ``index`` de ``image``."""
    if frames <= 1:
        return image
    return image.crop(frame_box(image.size, frames, index))


def nine_slice(image: Image.Image, border: tuple[int, int], size: tuple[int, int]) -> Image.Image:
    """``image`` estirada a ``size`` conservando un borde de ``border`` píxeles (ancho, alto) sin deformar."""
    width, height = max(1, int(size[0])), max(1, int(size[1]))
    source_w, source_h = image.size
    bx = max(0, min(int(border[0]), source_w // 2, width // 2))
    by = max(0, min(int(border[1]), source_h // 2, height // 2))
    result = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    xs = ((0, bx, 0, bx), (bx, source_w - bx, bx, width - bx), (source_w - bx, source_w, width - bx, width))
    ys = ((0, by, 0, by), (by, source_h - by, by, height - by), (source_h - by, source_h, height - by, height))
    for sy0, sy1, dy0, dy1 in ys:
        for sx0, sx1, dx0, dx1 in xs:
            if sx1 <= sx0 or sy1 <= sy0 or dx1 <= dx0 or dy1 <= dy0:
                continue
            piece = image.crop((sx0, sy0, sx1, sy1))
            if piece.size != (dx1 - dx0, dy1 - dy0):
                piece = piece.resize((dx1 - dx0, dy1 - dy0), Image.Resampling.NEAREST)
            result.paste(piece, (dx0, dy0))
    return result


class TextureCache:
    """Imágenes decodificadas por ruta. ``read(rel)`` da los bytes efectivos (None si no existe).

    Una textura que no se puede leer o decodificar se recuerda como ausente: la vista previa cae en el estilo
    procedural sin reintentar en cada repintado. ``invalidate`` olvida una ruta (o todas) tras un cambio.
    """

    def __init__(self, read: Callable[[VPath], bytes | None], *, size: int = DEFAULT_CACHE_SIZE) -> None:
        self._read = read
        self._size = max(1, size)
        self._images: OrderedDict[str, Image.Image | None] = OrderedDict()

    def get(self, rel: VPath | str | None) -> Image.Image | None:
        if rel is None:
            return None
        rel = VPath.of(rel)
        key = rel.key
        if key in self._images:
            self._images.move_to_end(key)
            return self._images[key]
        image: Image.Image | None = None
        data = self._read(rel)
        if data is not None:
            try:
                image = load_image(data)
            except TextureError:
                image = None
        self._images[key] = image
        while len(self._images) > self._size:
            self._images.popitem(last=False)
        return image

    def size_of(self, rel: VPath | str | None) -> tuple[int, int] | None:
        image = self.get(rel)
        return None if image is None else image.size

    def invalidate(self, rel: VPath | str | None = None) -> None:
        if rel is None:
            self._images.clear()
        else:
            self._images.pop(VPath.of(rel).key, None)

    def __len__(self) -> int:
        return len(self._images)
