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

from collections.abc import Callable
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
    raise NotImplementedError


def leading_int_key(rel: VPath) -> str | None:
    """Id de ``history/provinces/**/<id> - <Nombre>.txt``: el entero inicial del nombre (H9), o None."""
    raise NotImplementedError


# Tabla de wizard §5.2, en orden: gana la primera regla cuyo patrón encaja (la más específica primero).
# La implementa el agente A; la última regla es el comodín BINARY / UNION_BY_PATH.
LOAD_RULES: tuple[LoadRule, ...] = ()


def rule_for(rel: str | VPath) -> LoadRule:
    """Primera regla de ``LOAD_RULES`` que encaja con ``rel`` (nunca falla: hay comodín)."""
    raise NotImplementedError
