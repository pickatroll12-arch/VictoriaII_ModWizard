"""Reglas de carga del juego por carpeta (wizard §5.2).

Deciden qué gana cuando el mod y el juego base tienen archivos en la misma
carpeta: un archivo entero (``WHOLE_FILE``), todos con el mod sustituyendo por
ruta (``UNION_BY_PATH``), por ruta y además por clave del nombre (``KEYED_UNION``:
TAG o id), solo si otro archivo lo nombra (``REFERENCED``), la localización por
orden alfabético (``LOCALISATION``), los archivos del mapa (``MAP_BUNDLE``) y los
binarios referenciados (``ASSET``). ``verified=False`` marca una regla
[verificar en juego]: el editor la usa, pero la trata como opción o aviso.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache
from dataclasses import dataclass
from enum import Enum

from .model import DocKind
from .paths import VPath


class LoadMode(Enum):
    WHOLE_FILE = "whole_file"
    UNION_BY_PATH = "union_by_path"
    KEYED_UNION = "keyed_union"
    REFERENCED = "referenced"
    LOCALISATION = "localisation"
    MAP_BUNDLE = "map_bundle"
    ASSET = "asset"


@dataclass(frozen=True)
class LoadRule:
    """``pattern`` es un glob relativo sin distinguir mayúsculas (``history/provinces/**/*.txt``)."""

    pattern: str
    mode: LoadMode
    doc_kind: DocKind
    recursive: bool = False
    key_of: Callable[[VPath], str | None] | None = None   # p. ej. entero inicial del nombre o TAG
    new_file: str | None = None                           # plantilla de nombre de un archivo nuevo del mod
    verified: bool = True                                  # False = [verificar en juego]


def tag_key(rel: VPath) -> str | None:
    """TAG de ``history/countries/<TAG> - <Nombre>.txt``: los 3 primeros caracteres en mayúsculas."""
    name = VPath.of(rel).name
    tag = name[:3]
    return tag.upper() if len(tag) == 3 and tag.isascii() and tag.isalnum() else None


_LEADING_INT_RE = re.compile(r"\s*(\d+)")


def leading_int_key(rel: VPath) -> str | None:
    """Id de ``history/provinces/**/<id> - <Nombre>.txt``: el entero inicial del nombre (H9), o None."""
    match = _LEADING_INT_RE.match(VPath.of(rel).name)
    return str(int(match.group(1))) if match else None


_W, _U, _K, _R = LoadMode.WHOLE_FILE, LoadMode.UNION_BY_PATH, LoadMode.KEYED_UNION, LoadMode.REFERENCED
_C, _L = DocKind.CLAUSEWITZ, DocKind.LOCALISATION

# Tabla de wizard §5.2, en orden: gana la primera regla cuyo patrón encaja (la más específica primero).
# Las últimas son comodines por extensión y, al final, BINARY / UNION_BY_PATH.
LOAD_RULES: tuple[LoadRule, ...] = (
    # El descriptor (.mod) es un archivo más de la capa MOD (paths.DESCRIPTOR_REL).
    LoadRule("@descriptor.mod", _W, _C),
    LoadRule("common/countries/*.txt", _R, _C, new_file="common/countries/{name}.txt"),
    LoadRule("common/defines.lua", _W, DocKind.LUA),
    LoadRule("common/*.txt", _W, _C),
    LoadRule("history/countries/*.txt", _K, _C, key_of=tag_key, new_file="history/countries/{tag} - {name}.txt"),
    LoadRule("history/provinces/**/*.txt", _K, _C, recursive=True, key_of=leading_int_key),
    LoadRule("history/pops/**/*.txt", _U, _C, recursive=True),
    LoadRule("history/units/**/*.txt", _R, _C, recursive=True),
    LoadRule("history/wars/*.txt", _U, _C, new_file="history/wars/{name}.txt"),
    LoadRule("history/diplomacy/*.txt", _U, _C),
    LoadRule("events/*.txt", _U, _C, new_file="events/{prefix}_studio.txt"),
    LoadRule("decisions/*.txt", _U, _C, new_file="decisions/{prefix}_studio.txt"),
    LoadRule("units/*.txt", _U, _C, new_file="units/{name}.txt"),
    LoadRule("news/*.txt", _U, _C),
    LoadRule("technologies/*.txt", _R, _C, verified=False),
    LoadRule("inventions/*.txt", _R, _C, verified=False),
    LoadRule("poptypes/*.txt", _U, _C),
    LoadRule("interface/*.gfx", _U, _C, new_file="interface/{prefix}_studio.gfx", verified=False),
    LoadRule("interface/*.gui", _W, _C),
    LoadRule("localisation/*.csv", LoadMode.LOCALISATION, _L, new_file="localisation/00_{prefix}_{area}.csv"),
    LoadRule("map/default.map", LoadMode.MAP_BUNDLE, _C),
    LoadRule("map/*.txt", LoadMode.MAP_BUNDLE, _C),
    LoadRule("map/*.csv", LoadMode.MAP_BUNDLE, DocKind.TABLE),
    LoadRule("map/*.bmp", LoadMode.MAP_BUNDLE, DocKind.BMP),
    LoadRule("map/**/*.dds", LoadMode.MAP_BUNDLE, DocKind.IMAGE, recursive=True),
    LoadRule("map/**/*", LoadMode.MAP_BUNDLE, DocKind.BINARY, recursive=True),
    LoadRule("gfx/**/*.tga", LoadMode.ASSET, DocKind.IMAGE, recursive=True),
    LoadRule("gfx/**/*.dds", LoadMode.ASSET, DocKind.IMAGE, recursive=True),
    LoadRule("gfx/**/*.png", LoadMode.ASSET, DocKind.IMAGE, recursive=True),
    LoadRule("gfx/**/*", LoadMode.ASSET, DocKind.BINARY, recursive=True),
    # Comodines (fuera de la tabla de §5.2): texto Clausewitz, Lua y el resto como binario.
    *(LoadRule(f"**/*{suffix}", _U, _C, recursive=True, verified=False)
      for suffix in (".txt", ".gui", ".gfx", ".sfx", ".asset", ".map")),
    LoadRule("**/*.lua", _W, DocKind.LUA, recursive=True, verified=False),
    LoadRule("**/*", _U, DocKind.BINARY, recursive=True, verified=False),
)


@lru_cache(maxsize=None)
def _compile(pattern: str) -> re.Pattern:
    """Glob sin mayúsculas: ``**/`` es cero o más carpetas, ``*`` y ``?`` no cruzan ``/``."""
    out = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append("(?:[^/]+/)*")
            index += 3
        elif pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif pattern[index] == "*":
            out.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(out), re.IGNORECASE | re.DOTALL)


_COMPILED = tuple((_compile(rule.pattern), rule) for rule in LOAD_RULES)


def rule_matches(rule: LoadRule, rel: str | VPath) -> bool:
    return _compile(rule.pattern).fullmatch(VPath.of(rel)) is not None


def rule_for(rel: str | VPath) -> LoadRule:
    """Primera regla de ``LOAD_RULES`` que encaja con ``rel`` (nunca falla: hay comodín)."""
    rel = VPath.of(rel)
    for regex, rule in _COMPILED:
        if regex.fullmatch(rel) is not None:
            return rule
    return LOAD_RULES[-1]
