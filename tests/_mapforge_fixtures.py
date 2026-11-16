"""Mundos pequeños del taller de mapas (wizard §19, iteración 9a): rápidos, deterministas y sin datos del juego.

``tiny_params`` da un mapa de 576×288 (unas 2 000 celdas, 60 provincias de tierra y 15 de mar) que se genera en
menos de medio segundo; ``tiny_world`` lo cachea por parámetros dentro del proceso de pruebas.
"""

from __future__ import annotations

import functools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.mapforge import pipeline  # noqa: E402
from vic2studio.core.mapforge.params import ForgeParams  # noqa: E402

TINY_SIZE = (576, 288)


def tiny_params(**kw) -> ForgeParams:
    base = dict(size=TINY_SIZE, seed=3, land_provinces=60, sea_provinces=15, existing_tags=3)
    base.update(kw)
    return ForgeParams(**base)


def tiny_install():
    """El perfil sintético con tres TAG inventados (sin instalación del juego)."""
    from dataclasses import replace

    from vic2studio.core.mapforge.install import synthetic_profile
    from vic2studio.core.mapforge.world import TagInfo

    tags = [TagInfo("AAA", 30, 1, "cultura_a", "fe_a", True, "history/countries/AAA - Alfa.txt"),
            TagInfo("BBB", 20, 2, "cultura_b", "fe_a", False, "history/countries/BBB - Beta.txt"),
            TagInfo("CCC", 10, 3, "cultura_c", "fe_b", False, "history/countries/CCC - Gamma.txt")]
    return replace(synthetic_profile(), tags=tags, top_culture="cultura_a", top_religion="fe_a")


@functools.lru_cache(maxsize=8)
def _cached(seed: int, template: str, owners_none: bool):
    from vic2studio.core.mapforge.params import Owners

    p = tiny_params(seed=seed, template=template, owners=Owners.NONE if owners_none else Owners.EXISTING_TAGS)
    return pipeline.run_all(p, tiny_install())


def tiny_world(seed: int = 3, template: str = "continents", *, owners_none: bool = False):
    """Un mundo generado completo (rejilla, celdas y ráster a escala 1) con el perfil sintético."""
    return _cached(seed, template, owners_none)
