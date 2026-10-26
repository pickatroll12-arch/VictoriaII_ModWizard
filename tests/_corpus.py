"""Localiza carpetas de mods reales para las pruebas de corpus.

``VIC2_CORPUS`` admite varias rutas separadas por ``os.pathsep``. Si no está
definida se usa ``../Plantilla Mod`` respecto a la raíz del proyecto, cuando existe.
Las pruebas de corpus se omiten si no hay ninguna carpeta disponible.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLAUSEWITZ_SUFFIXES = {".txt", ".mod", ".gfx", ".gui", ".sfx", ".asset"}


def corpus_roots() -> list[Path]:
    raw = os.environ.get("VIC2_CORPUS")
    if raw:
        candidates = [Path(p) for p in raw.split(os.pathsep) if p]
    else:
        candidates = [PROJECT_ROOT.parent / "Plantilla Mod"]
    return [p for p in candidates if p.is_dir()]


def corpus_files(suffixes: set[str]) -> list[Path]:
    files = []
    for root in corpus_roots():
        files.extend(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in suffixes)
    return sorted(files)
