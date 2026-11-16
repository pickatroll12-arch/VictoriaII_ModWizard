"""Sprites e imágenes nuevos desde una imagen propia (wizard §17.3, criterio 3 de la iteración 8).

- ``new_sprite``: «Nuevo sprite». Convierte la imagen a DDS A8R8G8B8 sin comprimir en
  ``gfx/interface/<P>/<nombre>.dds`` y crea su ``spriteType`` (o ``corneredTileSpriteType`` con ``borderSize``)
  al final de ``spriteTypes`` en ``interface/<p>_studio.gfx``. Todo en **una** transacción: un Ctrl+Z lo deshace.
- ``import_picture``: «Importar…» del gestor de imágenes. Encuadra la imagen al tamaño de su familia (eventos,
  decisiones, banderas, tecnologías, noticias, pantallas de carga) y la deja con el formato de esa familia.

Las dos releen lo escrito antes de ponerlo (``encode_image``): nunca se guarda una imagen que el juego no leería.
Sin Qt; quien llama abre la sesión y muestra el resultado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from PIL import Image

from ..gfx.images import FORMAT_DDS, PictureSlot, encode_image, fit_image
from ..project.binary import put_bytes
from ..vfs.paths import VPath

SPRITE_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CORNERED = "corneredTileSpriteType"
SPRITE_KINDS = ("spriteType", CORNERED)


class SpriteError(ValueError):
    """El sprite no se puede crear: ``code`` es ``bad_name``, ``taken``, ``bad_frames`` o ``bad_image``."""

    def __init__(self, code: str, **params) -> None:
        super().__init__(code)
        self.code = code
        self.params = params


@dataclass(frozen=True)
class NewSprite:
    name: str
    kind: str
    texture: VPath
    gfx: VPath
    frames: int
    size: tuple[int, int]


def sprite_paths(prefix: str, name: str) -> tuple[VPath, VPath]:
    """``(textura, .gfx)`` de un sprite nuevo del proyecto con prefijo ``prefix``."""
    folder = prefix or "mod"
    return VPath.of(f"gfx/interface/{folder}/{name}.dds"), VPath.of(f"interface/{folder.lower()}_studio.gfx")


def check_sprite(name: str, image: Image.Image, frames: int, exists) -> None:
    """Lanza ``SpriteError`` si el nombre, los fotogramas o la imagen no valen. ``exists(name)``: ocupado."""
    if not SPRITE_NAME_RE.fullmatch(name or ""):
        raise SpriteError("bad_name", name=name)
    if exists(name):
        raise SpriteError("taken", name=name)
    if frames < 1 or image.size[0] % frames:
        raise SpriteError("bad_frames", frames=frames, width=image.size[0])
    if image.size[0] < 1 or image.size[1] < 1:
        raise SpriteError("bad_image")


def new_sprite(ws, entities, name: str, image: Image.Image, *, frames: int = 1, kind: str = "spriteType",
               border: tuple[int, int] | None = None, prefix: str | None = None) -> NewSprite:
    """Crea la textura y el sprite en una transacción (``undo.new_sprite``) de ``ws``.

    ``entities`` es el ``Entities`` del proyecto y ``prefix`` el de sus archivos (``settings.prefix``).
    ``border`` solo cuenta en un ``corneredTileSpriteType``."""
    if kind not in SPRITE_KINDS:
        raise SpriteError("bad_kind", kind=kind)
    sprites = {item.ref.ident.lower() for item in entities.list("sprite")}
    check_sprite(name, image, frames, lambda candidate: candidate.lower() in sprites)
    prefix = prefix or "mod"
    texture, gfx = sprite_paths(prefix, name)
    data = encode_image(fit_image(image), FORMAT_DDS)
    values: dict = {"type": kind, "texturefile": str(texture)}
    if frames > 1:
        values["noOfFrames"] = frames
    if kind == CORNERED and border is not None:
        values["borderSize"] = {"x": int(border[0]), "y": int(border[1])}
    with ws.transaction("undo.new_sprite", name=name):
        put_bytes(ws, texture, data)
        entities.create("sprite", name, values, target_rel=gfx)
    return NewSprite(name, kind, texture, gfx, frames, image.size)


def import_picture(ws, slot: PictureSlot, name: str, image: Image.Image, size: tuple[int, int], *,
                   mode: str = "cover", focus: tuple[float, float] = (0.5, 0.5)) -> VPath:
    """Deja ``image`` como ``<carpeta de la familia>/<name>.<formato>`` encuadrada a ``size``, en una
    transacción (``undo.import_picture``). Devuelve la ruta escrita."""
    if not re.fullmatch(r"[A-Za-z0-9_ .\-]+", name or "") or name.strip(" .") != name:
        raise SpriteError("bad_name", name=name)
    rel = VPath.of(f"{slot.folder}/{name}.{slot.format}")
    data = encode_image(fit_image(image, size, mode=mode, focus=focus), slot.format)
    with ws.transaction("undo.import_picture", name=name, folder=slot.folder):
        put_bytes(ws, rel, data)
    return rel
