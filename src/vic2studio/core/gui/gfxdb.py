"""Catálogo de sprites de ``interface/*.gfx`` (wizard §17.1).

Un ``.gfx`` agrupa definiciones con nombre en contenedores (``spriteTypes``, ``objectTypes``, ``bitmapfonts``…).
Aquí interesan las de ``spriteTypes``: ``spriteType``, ``textSpriteType``, ``corneredTileSpriteType``,
``maskedShieldType``, ``progressbartype``… Cada una da un ``Sprite`` con su textura resuelta en la vista
efectiva. El juego busca las claves y los nombres sin distinguir mayúsculas, y admite la textura con la otra
extensión (``.tga`` ↔ ``.dds``, H23): el catálogo hace lo mismo.

Hechos medidos en vanilla (66 archivos): 1 264 definiciones en ``spriteTypes`` (1 067 ``spriteType``, 88
``textSpriteType``, 48 ``progressbartype``…); 432 de ellas nombran una textura que solo existe con la otra
extensión (445 referencias contando ``textureFile1``/``textureFile2`` y ``objectTypes``); 26 nombran una que no
existe de ninguna forma (las ilustraciones del tutorial, entre otras), y 13 nombres están definidos más de una vez
contando todos los contenedores (gana el último cargado, [verificar en juego]). Los dos últimos grupos salen como
problemas heredados, no del mod.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..cancel import CancelCheck, raise_if_cancelled
from ..clausewitz.nodes import Block, Document, Entry, Scalar
from ..vfs.paths import InvalidPathError, VPath
from .source import GuiSource

GFX_FOLDER = "interface"
GFX_PATTERN = "*.gfx"
GUI_PATTERN = "*.gui"

# Contenedores de un .gfx cuyas definiciones son sprites que un .gui puede nombrar.
SPRITE_CONTAINERS = ("spritetypes",)
# Todos los contenedores con definiciones con nombre: los nombres repetidos se buscan entre todas.
DEFINITION_CONTAINERS = ("spritetypes", "objecttypes", "bitmapfonts", "fonts", "lighttypes")
TEXTURE_KEYS = ("texturefile", "texturefile1")
TEXTURE2_KEYS = ("texturefile2",)
ALTERNATIVE_SUFFIX = {".tga": ".dds", ".dds": ".tga"}
# Claves de un elemento de .gui que nombran un sprite de los .gfx. ``background`` solo lo hace en una lista
# (``listboxType``); en una ventana nombra a uno de sus hijos, igual que ``slider`` o ``track`` en una barra.
SPRITE_REF_KEYS = ("spritetype", "quadtexturesprite")
SPRITE_REF_KEYS_BY_TYPE = {"listboxtype": ("background",)}


def _text(block: Block, key: str) -> str | None:
    entry = block.find(key, ignore_case=True)
    if entry is None or not isinstance(entry.value, Scalar):
        return None
    return entry.value.text


def _first_text(block: Block, keys: Iterable[str]) -> str | None:
    for key in keys:
        value = _text(block, key)
        if value:
            return value
    return None


def _int(block: Block, key: str, default: int) -> int:
    value = _text(block, key)
    try:
        return int(float(value)) if value is not None else default
    except ValueError:
        return default


def _pair(block: Block, key: str) -> tuple[int, int] | None:
    entry = block.find(key, ignore_case=True)
    if entry is None or not isinstance(entry.value, Block):
        return None
    return _int(entry.value, "x", 0), _int(entry.value, "y", 0)


def normalize_texture(raw: str) -> VPath | None:
    """La ruta de una textura tal como la escribe un ``.gfx`` (``gfx\\\\interface\\\\x.tga``, ``gfx//x.dds``) como
    ruta relativa; None si no es una ruta válida (vacía, absoluta, con ``..``)."""
    try:
        return VPath.of(raw.strip().replace("\\", "/"))
    except (InvalidPathError, TypeError):
        return None


def resolve_texture(raw: str, find: Callable[[VPath], VPath | None]) -> VPath | None:
    """El archivo efectivo de la textura ``raw``: el que nombra o, si falta, el de la otra extensión (H23)."""
    rel = normalize_texture(raw)
    if rel is None:
        return None
    found = find(rel)
    if found is not None:
        return found
    other = ALTERNATIVE_SUFFIX.get(rel.suffix)
    if other is None:
        return None
    return find(VPath.of(str(rel)[:-len(rel.suffix)] + other))


@dataclass(frozen=True)
class Sprite:
    """Una definición de ``spriteTypes``. ``kind`` es la clave del bloque en minúsculas; ``resolved`` es la
    textura encontrada (quizá con la otra extensión) o None si falta."""

    name: str
    kind: str
    texture: str
    texture2: str | None
    frames: int
    border: tuple[int, int] | None
    rel: VPath
    line: int
    resolved: VPath | None
    effect: str | None = None
    container: str = "spritetypes"
    size: tuple[int, int] | None = None      # ``size = { x y }`` declarado (``corneredTileSpriteType``…)

    @property
    def key(self) -> str:
        return self.name.lower()

    @property
    def alternative_extension(self) -> bool:
        """True si la textura solo existe con la otra extensión."""
        wanted = normalize_texture(self.texture)
        return self.resolved is not None and wanted is not None and self.resolved.suffix != wanted.suffix


def sprite_entries(doc: Document, containers: tuple[str, ...] = SPRITE_CONTAINERS
                   ) -> Iterable[tuple[Entry, Block]]:
    """Las definiciones de ``containers`` (por defecto ``spriteTypes``) de un ``.gfx``: ``(entrada, bloque)`` en
    orden de archivo."""
    for entry, block, _ in definition_entries(doc, containers):
        yield entry, block


def definition_entries(doc: Document, containers: tuple[str, ...] = DEFINITION_CONTAINERS
                       ) -> Iterable[tuple[Entry, Block, str]]:
    """Las definiciones de ``containers``: ``(entrada, bloque, contenedor en minúsculas)``."""
    for container in doc.entries:
        if container.key is None or not isinstance(container.value, Block):
            continue
        name = container.key.text.lower()
        if name not in containers:
            continue
        for entry in container.value.entries:
            if entry.key is not None and isinstance(entry.value, Block):
                yield entry, entry.value, name


def sprite_of(entry: Entry, rel: VPath, find: Callable[[VPath], VPath | None],
              container: str = "spritetypes") -> Sprite | None:
    """El ``Sprite`` de una entrada de ``spriteTypes`` (u otro contenedor); None si no tiene nombre."""
    block = entry.value
    name = _text(block, "name")
    if not name:
        return None
    texture = _first_text(block, TEXTURE_KEYS) or ""
    return Sprite(
        name=name, kind=entry.key.text.lower(), texture=texture, texture2=_first_text(block, TEXTURE2_KEYS),
        frames=max(1, _int(block, "noofframes", 1)), border=_pair(block, "bordersize"), rel=rel,
        line=entry.line or 0, resolved=resolve_texture(texture, find) if texture else None,
        effect=_text(block, "effectfile"), container=container, size=_pair(block, "size"))


class SpriteDB:
    """Todos los sprites de la vista efectiva, por nombre sin mayúsculas.

    Con un nombre repetido, ``get`` da la última definición en orden de carga (archivos por orden alfabético
    sin mayúsculas; dentro de un archivo, la última). Cuál gana de verdad es [verificar en juego]:
    ``duplicates`` las da todas para que la validación lo avise.
    """

    def __init__(self, sprites: Iterable[Sprite] = ()) -> None:
        self._by_name: dict[str, list[Sprite]] = {}
        self._all_defs: dict[str, list[Sprite]] = {}
        self._usages: dict[str, list[tuple[VPath, int]]] | None = None
        for sprite in sprites:
            self._all_defs.setdefault(sprite.key, []).append(sprite)
            if sprite.container in SPRITE_CONTAINERS:
                self._by_name.setdefault(sprite.key, []).append(sprite)

    @classmethod
    def build(cls, source: GuiSource, *, cancelled: CancelCheck = None) -> SpriteDB:
        """Lee todos los ``interface/*.gfx`` de ``source``. Un archivo ilegible se salta (lo dice la sintaxis)."""
        sprites: list[Sprite] = []
        for rel in source.rels(GFX_FOLDER, GFX_PATTERN):
            raise_if_cancelled(cancelled)
            doc = source.document(rel)
            if doc is None:
                continue
            for entry, _, container in definition_entries(doc):
                sprite = sprite_of(entry, rel, source.find, container)
                if sprite is not None:
                    sprites.append(sprite)
        db = cls(sprites)
        db._source = source
        return db

    _source: GuiSource | None = None

    def __len__(self) -> int:
        return len(self._by_name)

    def __contains__(self, name: str) -> bool:
        return name.lower() in self._by_name

    def names(self) -> list[str]:
        """Nombres (con la grafía de la definición que gana), ordenados sin mayúsculas."""
        return [found[-1].name for _, found in sorted(self._by_name.items())]

    def sprites(self) -> list[Sprite]:
        """La definición que gana de cada nombre, ordenadas por nombre."""
        return [found[-1] for _, found in sorted(self._by_name.items())]

    def all(self) -> list[Sprite]:
        """Todas las definiciones, repetidas incluidas, en orden de carga."""
        return [sprite for found in self._by_name.values() for sprite in found]

    def get(self, name: str) -> Sprite | None:
        found = self._by_name.get(name.lower())
        return found[-1] if found else None

    def duplicates(self) -> dict[str, list[Sprite]]:
        """Nombres definidos más de una vez en cualquier contenedor de los ``.gfx``, con todas sus definiciones
        en orden de carga."""
        return {found[-1].name: list(found) for found in self._all_defs.values() if len(found) > 1}

    def missing_textures(self) -> list[Sprite]:
        """Definiciones cuya textura no existe con ninguna de las dos extensiones (las sin textura no cuentan)."""
        return [s for s in self.all() if s.texture and s.resolved is None]

    def usages(self, name: str, source: GuiSource | None = None) -> list[tuple[VPath, int]]:
        """Los ``.gui`` que nombran el sprite: ``(archivo, línea)``. Se calcula una vez por catálogo."""
        if self._usages is None:
            source = source or self._source
            self._usages = {} if source is None else sprite_usages(source)
        return list(self._usages.get(name.lower(), ()))


def sprite_references(doc: Document) -> Iterable[tuple[str, Entry]]:
    """Cada cita de un sprite en un ``.gui``: ``(nombre, entrada que lo cita)``, recorriendo todo el árbol."""
    stack: list[tuple[Block, str]] = [(doc, "")]
    while stack:
        block, owner = stack.pop()
        extra = SPRITE_REF_KEYS_BY_TYPE.get(owner, ())
        for entry in block.entries:
            if entry.key is None:
                continue
            key = entry.key.text.lower()
            if isinstance(entry.value, Block):
                stack.append((entry.value, key))
            elif (key in SPRITE_REF_KEYS or key in extra) and isinstance(entry.value, Scalar) and entry.value.text:
                yield entry.value.text, entry


def sprite_usages(source: GuiSource, *, cancelled: CancelCheck = None) -> dict[str, list[tuple[VPath, int]]]:
    """Citas de sprites en todos los ``interface/*.gui``: nombre en minúsculas → ``(archivo, línea)``."""
    found: dict[str, list[tuple[VPath, int]]] = {}
    for rel in source.rels(GFX_FOLDER, GUI_PATTERN):
        raise_if_cancelled(cancelled)
        doc = source.document(rel)
        if doc is None:
            continue
        for name, entry in sprite_references(doc):
            found.setdefault(name.lower(), []).append((rel, entry.line or 0))
    for uses in found.values():
        uses.sort(key=lambda use: (use[0].key, use[1]))
    return found
