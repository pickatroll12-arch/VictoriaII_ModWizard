"""Interfaz e imágenes: sprites de ``.gfx``, ventanas de ``.gui`` y archivos de ``gfx/`` (wizard §7, H23)."""

from __future__ import annotations

from ...clausewitz.nodes import Scalar
from ..model import KIND_GUI_WINDOW, KIND_IMAGE, KIND_SPRITE, extractor
from ..parsing import as_int, document
from ._support import Facts, path_name

# Claves de textura de un sprite (sin distinguir mayúsculas, H23: ``texturefile``/``textureFile``).
TEXTURE_KEYS = ("texturefile", "texturefile1", "texturefile2")
# Ventanas de primer nivel de un .gui.
WINDOW_TYPES = frozenset({"windowtype", "eu3dialogtype"})


@extractor("interface/*.gfx", version=1)
def sprites(rel, data, layer):
    """Cada ``*Type = { name = … texturefile = … }`` de ``spriteTypes``; la textura es una referencia ``image``."""
    facts = Facts(rel, layer)
    for root in document(data).entries:
        if root.key is None or root.value.__class__ is Scalar or root.key.text.lower() != "spritetypes":
            continue
        for entry in root.value.entries:
            if entry.key is None or entry.value.__class__ is Scalar:
                continue
            block = entry.value
            name = block.get_text("name", ignore_case=True)
            if not name:
                continue
            textures = []
            for key in TEXTURE_KEYS:
                found = block.find(key, ignore_case=True)
                if found is None or found.value.__class__ is not Scalar or not found.value.text.strip():
                    continue
                target = path_name(found.value.text)
                if target is not None:
                    textures.append(target)
                    facts.ref(KIND_IMAGE, target, found, "texturefile")
            frames = as_int(block.get_text("noOfFrames", ignore_case=True))
            facts.define(KIND_SPRITE, name, entry.line, {
                "type": entry.key.text, "texture": textures[0] if textures else None, "textures": textures,
                "frames": frames if frames is not None else 1})
    return facts.result()


@extractor("interface/*.gui", version=1)
def gui_windows(rel, data, layer):
    """Ventanas de primer nivel de ``guiTypes`` (``windowType``/``eu3dialogtype`` con ``name``)."""
    facts = Facts(rel, layer)
    for root in document(data).entries:
        if root.key is None or root.value.__class__ is Scalar or root.key.text.lower() != "guitypes":
            continue
        for entry in root.value.entries:
            if entry.key is None or entry.value.__class__ is Scalar or entry.key.text.lower() not in WINDOW_TYPES:
                continue
            name = entry.value.get_text("name", ignore_case=True)
            if name:
                facts.define(KIND_GUI_WINDOW, name, entry.line, {"type": entry.key.text})
    return facts.result()


@extractor("gfx/**/*", version=1, needs_data=False)
def images(rel, data, layer):
    """Cada archivo de ``gfx/`` es un símbolo ``image`` con su ruta en minúsculas (no se lee el archivo; la ruta
    con sus mayúsculas es ``Symbol.rel``)."""
    facts = Facts(rel, layer)
    facts.define(KIND_IMAGE, rel.lower(), None)
    return facts.result()
