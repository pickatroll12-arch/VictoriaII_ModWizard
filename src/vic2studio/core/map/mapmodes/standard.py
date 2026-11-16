"""Los modos de mapa del núcleo (wizard §16.2): político, RGO, infraestructura, nivel de vida, terreno, regiones,
continentes, climas, cultura, religión, núcleos y población.

Cada uno es una LUT por provincia sobre ``ProvinceFacts`` y una leyenda. Los colores con nombre salen del índice
(el ``color`` del archivo del país, del bien, de la cultura y de la religión); los que no tienen color propio
usan ``hash_color``, estable entre ejecuciones.
"""

from __future__ import annotations

import math

import numpy as np

from ...index.model import KIND_COUNTRY_FILE, KIND_CULTURE, KIND_GOODS, KIND_RELIGION, KIND_TAG
from ..facts import CODED, NONE, ProvinceFacts
from ..modes import (
    EMPTY_COLOR, SEA_COLOR, LegendItem, MapMode, argb, coded_lut, count_codes, finish_lut, gradient, hash_color,
    register_mode,
)

LOW_COLOR = argb(150, 40, 30)
HIGH_COLOR = argb(40, 170, 60)
NONE_LEVEL = argb(200, 200, 200)
CORE_COLOR = argb(200, 40, 40)
OWNED_COLOR = argb(240, 170, 60)
LEGEND_LIMIT = 40                    # filas de leyenda de un modo con nombres (las de más provincias)


def color_from(value) -> int | None:
    """Color de un atributo ``color`` del índice (``[r, g, b]`` en 0–255, o en 0–1 como las religiones)."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        channels = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    if all(0.0 <= v <= 1.0 for v in channels) and any(not float(v).is_integer() for v in channels):
        channels = [v * 255.0 for v in channels]
    return argb(*(max(0, min(255, round(v))) for v in channels))


def _symbol_color(index, kind: str):
    def colors(name: str) -> int | None:
        if index is None:
            return None
        return color_from(index.attrs(kind, name, "color"))
    return colors


def _tag_color(index):
    def colors(tag: str) -> int | None:
        if index is None:
            return None
        file = index.attrs(KIND_TAG, tag, "file") or index.attrs(KIND_TAG, tag.upper(), "file")
        if not file:
            return None
        return color_from(index.attrs(KIND_COUNTRY_FILE, str(file), "color"))
    return colors


def _coded_legend(field_name: str, symbol_kind: str | None, colors_of):
    def legend(facts: ProvinceFacts, index, *, param=None) -> list[LegendItem]:
        colors = colors_of(index)
        table = getattr(facts, CODED[field_name])
        counts = count_codes(facts, field_name)
        items = []
        for code, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            if code == NONE:
                continue
            name = table[code]
            color = colors(name)
            items.append(LegendItem(hash_color(name) if color is None else color,
                                    symbol=(symbol_kind, name) if symbol_kind else None,
                                    text="" if symbol_kind else name, count=count))
        items = items[:LEGEND_LIMIT]
        if counts.get(NONE):
            items.append(LegendItem(EMPTY_COLOR, text_key="map.legend.none", count=counts[NONE]))
        return items
    return legend


def _coded_mode(key: str, field_name: str, order: int, symbol_kind: str | None, colors_of) -> MapMode:
    def lut(facts: ProvinceFacts, index, *, param=None) -> np.ndarray:
        return coded_lut(facts, field_name, colors_of(index))
    return MapMode(key, f"map.mode.{key}", lut, _coded_legend(field_name, symbol_kind, colors_of), order=order,
                   needs=(field_name,))


def _no_colors(index):
    return lambda name: None


def _level_mode(key: str, field_name: str, order: int, low: float, high: float) -> MapMode:
    def lut(facts: ProvinceFacts, index, *, param=None) -> np.ndarray:
        values = np.asarray(getattr(facts, field_name))
        colors = gradient(values, low, high, LOW_COLOR, HIGH_COLOR)
        colors[values <= 0] = NONE_LEVEL
        return finish_lut(facts, colors)

    def legend(facts: ProvinceFacts, index, *, param=None) -> list[LegendItem]:
        values = np.asarray(getattr(facts, field_name))[1:]
        land = ~np.asarray(facts.is_sea)[1:]
        found, counts = np.unique(values[land], return_counts=True)
        items = []
        for value, count in zip(found.tolist(), counts.tolist()):
            if value <= 0:
                items.append(LegendItem(NONE_LEVEL, text_key="map.legend.zero", count=count))
                continue
            color = int(gradient(np.array([value]), low, high, LOW_COLOR, HIGH_COLOR)[0])
            items.append(LegendItem(color, text=str(value), count=count))
        return items[:LEGEND_LIMIT]

    return MapMode(key, f"map.mode.{key}", lut, legend, order=order, needs=(field_name,))


def _cores_mode() -> MapMode:
    def lut(facts: ProvinceFacts, index, *, param=None) -> np.ndarray:
        colors = np.full(facts.size, EMPTY_COLOR, dtype=np.uint32)
        code = facts.code("tags", param) if param else NONE
        if code != NONE:
            owner = np.asarray(facts.owner)
            colors[owner == code] = OWNED_COLOR
            for pid, cores in enumerate(facts.cores):
                if code in cores:
                    colors[pid] = CORE_COLOR
        return finish_lut(facts, colors)

    def legend(facts: ProvinceFacts, index, *, param=None) -> list[LegendItem]:
        code = facts.code("tags", param) if param else NONE
        if code == NONE:
            return [LegendItem(EMPTY_COLOR, text_key="map.legend.pick_tag")]
        cores = sum(1 for item in facts.cores if code in item)
        owned = int(np.count_nonzero(np.asarray(facts.owner) == code))
        return [LegendItem(CORE_COLOR, text_key="map.legend.core", args=(("tag", param),), count=cores),
                LegendItem(OWNED_COLOR, text_key="map.legend.owned_no_core", args=(("tag", param),),
                           count=owned)]

    return MapMode("cores", "map.mode.cores", lut, legend, order=110, needs=("owner",), param="tag")


POPULATION_STEPS = (1_000, 10_000, 100_000, 1_000_000)


def _population_mode() -> MapMode:
    def lut(facts: ProvinceFacts, index, *, param=None) -> np.ndarray:
        values = np.asarray(facts.population, dtype=np.float64)
        logs = np.log10(np.maximum(values, 1.0))
        colors = gradient(logs, 2.0, 6.0, argb(240, 240, 200), argb(120, 20, 20))
        colors[values <= 0] = EMPTY_COLOR
        return finish_lut(facts, colors)

    def legend(facts: ProvinceFacts, index, *, param=None) -> list[LegendItem]:
        values = np.asarray(facts.population)[1:]
        land = ~np.asarray(facts.is_sea)[1:]
        items = []
        low = 0
        for high in (*POPULATION_STEPS, None):
            if high is None:
                mask = land & (values > low)
            else:
                mask = land & (values > low) & (values <= high)
            sample = math.log10(max(low, 1) * 3) if low else 2.0
            color = int(gradient(np.array([sample]), 2.0, 6.0, argb(240, 240, 200), argb(120, 20, 20))[0])
            if high is None:
                items.append(LegendItem(color, text_key="map.legend.more_than", args=(("low", low),),
                                        count=int(np.count_nonzero(mask))))
            else:
                items.append(LegendItem(color, text_key="map.legend.range", args=(("low", low), ("high", high)),
                                        count=int(np.count_nonzero(mask))))
            low = high or low
        empty = int(np.count_nonzero(land & (values <= 0)))
        if empty:
            items.append(LegendItem(EMPTY_COLOR, text_key="map.legend.no_pops", count=empty))
        return items

    return MapMode("population", "map.mode.population", lut, legend, order=120, needs=("population",))


register_mode(_coded_mode("political", "owner", 10, KIND_TAG, _tag_color))
register_mode(_coded_mode("rgo", "trade_goods", 20, KIND_GOODS, lambda index: _symbol_color(index, KIND_GOODS)))
register_mode(_level_mode("infrastructure", "railroad", 30, 0, 5))
register_mode(_level_mode("life_rating", "life_rating", 40, 0, 100))
register_mode(_coded_mode("terrain", "terrain", 50, "terrain", _no_colors))
register_mode(_coded_mode("regions", "region", 60, "region", _no_colors))
register_mode(_coded_mode("continents", "continent", 70, "continent", _no_colors))
register_mode(_coded_mode("climates", "climate", 80, "climate", _no_colors))
register_mode(_coded_mode("culture", "culture", 90, KIND_CULTURE, lambda index: _symbol_color(index, KIND_CULTURE)))
register_mode(_coded_mode("religion", "religion", 100, KIND_RELIGION,
                          lambda index: _symbol_color(index, KIND_RELIGION)))
register_mode(_cores_mode())
register_mode(_population_mode())


def _ids_mode() -> MapMode:
    """Modo IDs (§16.2): el color propio de cada provincia, apagado, con su número encima (capa ``ids`` de la
    interfaz)."""
    def lut(facts: ProvinceFacts, index, *, param=None) -> np.ndarray:
        colors = np.array([hash_color(f"id{pid}") for pid in range(facts.size)], dtype=np.uint32)
        channels = ((colors >> 16) & 255, (colors >> 8) & 255, colors & 255)
        soft = [(c.astype(np.uint32) + 2 * 230) // 3 for c in channels]
        colors = np.uint32(0xFF000000) | (soft[0] << 16) | (soft[1] << 8) | soft[2]
        return finish_lut(facts, colors.astype(np.uint32))

    def legend(facts: ProvinceFacts, index, *, param=None) -> list[LegendItem]:
        land = int(np.count_nonzero(~np.asarray(facts.is_sea)[1:]))
        return [LegendItem(argb(230, 230, 230), text_key="map.legend.ids", count=land)]

    return MapMode("ids", "map.mode.ids", lut, legend, order=130, overlay="ids")


register_mode(_ids_mode())
