"""Tabla temperatura × humedad → categoría de Victoria II (wizard §18.3, paso 7), editable en la pantalla 4.

Cada franja de temperatura (°C, desde ``t_min`` incluido) lista umbrales de humedad de mayor a menor; la primera
categoría cuyo umbral se supera gana y ``else`` es la de la humedad más baja. Altura, pantanos y farmlands se
aplican después (``biomes.categories``).
"""

from __future__ import annotations

BIOME_TABLE: tuple[dict, ...] = (
    {"t_min": -999.0, "bands": (), "else": "arctic"},
    {"t_min": -4.0, "bands": ((25.0, "forest"),), "else": "steppe"},
    {"t_min": 5.0, "bands": ((45.0, "forest"), (25.0, "woods"), (10.0, "plains")), "else": "steppe"},
    {"t_min": 18.0, "bands": ((50.0, "jungle"), (15.0, "plains"), (8.0, "steppe")), "else": "desert"},
)

# Coste de paso por categoría para la expansión de países y culturas (paso 12).
EXPANSION_COST = {"mountain": 4.0, "hills": 2.0, "marsh": 2.0, "desert": 3.0, "arctic": 5.0, "jungle": 2.5}

# Bienes por categoría dominante (paso 15). Solo se usan los que existen en la instalación (``goods``).
GOODS_BY_CATEGORY = {
    "plains": ("grain", "cattle", "wool"), "farmlands": ("grain", "fruit", "cotton"), "forest": ("timber", "fur"),
    "woods": ("timber", "cattle"), "hills": ("coal", "iron", "wool"), "mountain": ("iron", "coal", "precious_metal"),
    "steppe": ("cattle", "wool"), "jungle": ("tropical_wood", "rubber", "coffee"), "marsh": ("rice", "fish"),
    "desert": ("sulphur", "cattle"), "arctic": ("fur", "fish"),
}
MINING_GOODS = frozenset({"coal", "iron", "sulphur", "precious_metal"})

# Distribución objetivo del life rating (vanilla: medida por cuantiles de idoneidad, §18.3, paso 15).
LIFE_RATING_TARGET = ((10, 2), (15, 3), (20, 6), (25, 10), (30, 14), (35, 45), (40, 12), (45, 5), (50, 3))
