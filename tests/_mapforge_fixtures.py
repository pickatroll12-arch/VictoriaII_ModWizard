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


def fmg_json_full(cols: int = 20, rows: int = 10, version: str = "1.99.05", cell: float = 48.0) -> bytes:
    """Un JSON con la forma de «Export to JSON → Full» de FMG (``getFullDataJson``), inventado: una rejilla de
    ``cols``×``rows`` celdas cuadradas (200 por defecto) con dos continentes, 3 estados, 6 provincias, 2 culturas, 1
    río y un burgo capital por estado. El norte arriba, como en FMG."""
    import json

    def vid(x: int, y: int) -> int:
        return y * (cols + 1) + x

    vertices = [{"i": vid(x, y), "p": [x * cell, y * cell], "v": [], "c": []}
                for y in range(rows + 1) for x in range(cols + 1)]
    left = range(2, 2 + max(2, cols * 7 // 20))
    right = range(cols - 2 - max(2, cols * 7 // 20), cols - 2)
    band = range(2, max(3, rows - 2))
    cells = []
    for y in range(rows):
        for x in range(cols):
            i = y * cols + x
            land = y in band and (x in left or x in right)
            if not land:
                state = province = 0
                f = 1
            elif x in left:
                state, f = 1, 2
                province = 1 if x < left.start + len(left) // 2 else 2
            else:
                f = 3
                mid = right.start + len(right) // 2
                state = 2 if x < mid else 3
                province = {2: 3, 3: 5}[state] + (0 if y < band.start + len(band) // 2 else 1)
            nbs = [j for j, ok in ((i - 1, x > 0), (i + 1, x < cols - 1), (i - cols, y > 0), (i + cols, y < rows - 1))
                   if ok]
            cells.append({"i": i, "v": [vid(x, y), vid(x + 1, y), vid(x + 1, y + 1), vid(x, y + 1)], "c": nbs,
                          "p": [(x + 0.5) * cell, (y + 0.5) * cell], "g": i,
                          "h": (70 if land and x == left.start + 1 else 40) if land else 5, "area": cell * cell,
                          "f": f, "t": 1 if land else -1, "haven": 0, "harbor": 0, "fl": 0, "r": 0, "conf": 0,
                          "biome": 6 if land else 0, "s": 10, "pop": 5, "culture": (1 if state == 1 else 2) if land
                          else 0, "burg": 0, "religion": 1 if land else 0, "state": state, "province": province})
    caps = {1: (left.start + 1) + band.start * cols, 2: right.start + band.start * cols,
            3: (right.stop - 1) + (band.stop - 1) * cols}
    burgs = [{}] + [{"i": s, "cell": c, "x": cells[c]["p"][0], "y": cells[c]["p"][1], "state": s,
                     "name": f"Burgo {s}", "capital": 1} for s, c in caps.items()]
    for s, c in caps.items():
        cells[c]["burg"] = s
    states = [{"i": 0, "name": "Neutrals"}] + [{"i": s, "name": n, "capital": s, "culture": 1 if s == 1 else 2,
                                                "color": "#aa3322"} for s, n in ((1, "Velmora"), (2, "Ostrand"),
                                                                                   (3, "Kaldun"))]
    provinces = [0] + [{"i": p, "state": st, "name": n, "fullName": n, "center": 0, "burg": 0}
                       for p, st, n in ((1, 1, "Arvel"), (2, 1, "Brisa"), (3, 2, "Corran"), (4, 2, "Dunas"),
                                        (5, 3, "Esker"), (6, 3, "Fenna"))]
    cultures = [{"i": 0, "name": "Wildlands"}, {"i": 1, "name": "Velmorian"}, {"i": 2, "name": "Ostric"}]
    river_cells = [left.start + x + (band.start + 1) * cols for x in range(len(left))]
    data = {"info": {"version": version, "description": "fixture", "exportedAt": "2026-11-16", "mapName": "Prueba",
                     "width": cols * cell, "height": rows * cell, "seed": "1", "mapId": 1},
            "settings": {}, "mapCoordinates": {},
            "pack": {"cells": cells, "vertices": vertices, "features": [0], "cultures": cultures, "burgs": burgs,
                     "states": states, "provinces": provinces,
                     "religions": [{"i": 0, "name": "No religion"}, {"i": 1, "name": "Fe"}],
                     "rivers": [{"i": 1, "source": river_cells[0], "mouth": river_cells[-1], "cells": river_cells,
                                 "name": "Río"}], "markers": []},
            "grid": {"cells": [], "vertices": []}, "biomesData": {}, "notes": [], "nameBases": []}
    return json.dumps(data).encode("utf-8")
