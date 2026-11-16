"""Familia «interface»: sprites, texturas y ventanas de ``interface/*.gfx`` y ``*.gui`` (wizard §17, iteración 8).

- ``gui_sprite_missing`` (aviso): un ``.gui`` nombra un sprite que ningún ``.gfx`` define; el elemento sale sin
  imagen.
- ``texture_missing`` (aviso): un sprite nombra una textura que no existe con ninguna de sus dos extensiones
  (``.tga``/``.dds``, H23). Vanilla tiene 26, heredadas (las ilustraciones del tutorial, entre otras).
- ``sprite_duplicate`` (info): el mismo nombre está definido más de una vez en los ``.gfx`` (vanilla: 13,
  heredados). Cuál gana es [verificar en juego].
- ``gui_orientation_unknown`` (aviso): una ``orientation`` que el juego no conoce; se trata como
  ``UPPER_LEFT`` (vanilla tiene ``UPPERL_LEFT``).
- ``gui_named_element_removed`` (aviso): la copia de un ``.gui`` del juego en el mod ya no tiene un elemento con
  nombre que el original sí tiene. El ejecutable busca muchos elementos por su nombre: quitarlo puede romper
  esa ventana. La alternativa es ocultarlo (moverlo fuera de la pantalla, §17.4).
"""

from __future__ import annotations

from ...clausewitz import Severity
from ...gui.gfxdb import GFX_FOLDER, GUI_PATTERN, SpriteDB, sprite_references
from ...gui.guimodel import GuiDocument, element_path
from ...gui.layout import known_orientation
from ...gui.source import ContextSource
from ...vfs.model import LayerKind
from ..registry import make_problem, rule

E, W, I = Severity.ERROR, Severity.WARNING, Severity.INFO


def _gui_documents(ctx):
    for rel in ctx.rels(GFX_FOLDER, GUI_PATTERN):
        result = ctx.parse(rel)
        if result is not None:
            yield rel, result.document


def named_paths(document) -> dict[str, int]:
    """Rutas (sin mayúsculas) de los elementos con nombre de un ``.gui``, con su línea."""
    found: dict[str, int] = {}
    for element in GuiDocument(document).elements():
        if element.name:
            found.setdefault(element_path(element).lower(), element.line)
    return found


@rule("gui_sprite_missing", W)
@rule("texture_missing", W)
@rule("sprite_duplicate", I)
def sprites(ctx):
    source = ContextSource(ctx)
    db = SpriteDB.build(source, cancelled=ctx.cancelled)
    problems = []
    for sprite in db.missing_textures():
        problems.append(make_problem("texture_missing", sprite.rel, sprite.line, entity=("sprite", sprite.name),
                                     sprite=sprite.name, texture=sprite.texture))
    for name, definitions in db.duplicates().items():
        first = definitions[0]
        for other in definitions[1:]:
            problems.append(make_problem("sprite_duplicate", other.rel, other.line, entity=("sprite", name),
                                         sprite=name, other=str(first.rel), count=len(definitions)))
    if not len(db):
        return problems   # sin ningún .gfx (un proyecto sin juego) no hay con qué comparar
    for rel, document in _gui_documents(ctx):
        for name, entry in sprite_references(document):
            if name not in db:
                problems.append(make_problem("gui_sprite_missing", rel, entry.line or 0, sprite=name,
                                             key=entry.key.text if entry.key is not None else ""))
    return problems


@rule("gui_orientation_unknown", W)
def orientations(ctx):
    problems = []
    for rel, document in _gui_documents(ctx):
        for element in GuiDocument(document).elements():
            entry = element.block.find("orientation", ignore_case=True)
            if entry is not None and not known_orientation(element.orientation):
                problems.append(make_problem("gui_orientation_unknown", rel, entry.line or element.line,
                                             element=element_path(element), orientation=element.orientation))
    return problems


@rule("gui_named_element_removed", W)
def removed_elements(ctx):
    problems = []
    for rel, document in _gui_documents(ctx):
        if ctx.layer_of(rel) is not LayerKind.MOD:
            continue
        below = [entry for entry in ctx.stack(rel) if entry.layer.kind is not LayerKind.MOD]
        if not below:
            continue   # un .gui propio del mod: no hay original con el que comparar
        data = ctx.read_entry(below[0])
        if data is None:
            continue
        from ...project.codecs import parse_bytes

        original = named_paths(parse_bytes(data).document)
        current = named_paths(document)
        for path, line in original.items():
            if path not in current:
                problems.append(make_problem("gui_named_element_removed", rel, 0, element=path,
                                             original=str(below[0].rel), original_line=line))
    return problems
