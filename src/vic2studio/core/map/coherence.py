"""Invariantes de coherencia del mapa: ``check_map`` (wizard §16.6). Contrato de la iteración 5.

Reúne lo que un archivo solo no puede comprobar: el BMP contra ``definition.csv``, ``default.map`` contra los
dos, regiones, continentes y climas contra las provincias, ``positions.txt``, las historias y ``adjacencies.csv``.
Trabaja sobre un ``ValidationContext`` (bytes efectivos e índice inmutables, I12): vale en un hilo de tarea y
nunca escribe (I4). Los problemas se crean con ``validate.registry.make_problem``, así que cada código está
registrado como regla en ``core/validate/rules/map.py`` (familia «map») o en ``rules/provinces.py`` (los que ya
existían), con sus textos ``issue.``, ``explain.title.`` y ``explain.outcome.`` en ES y EN.

``CODES`` fija el código definitivo y la gravedad de cada invariante. Varios nombres de §16.6 ya existían con
otro nombre desde la iteración 3 (tienen textos, línea base y pruebas): se conservan los existentes
(``RENAMED``). Sobre el juego base el resultado es la línea base de «problemas conocidos» (I11): en vanilla, los
27 colores sin fila, el «223.» de la fila 1826, las historias duplicadas 1396 y 1397 y el 2800 repetido en
``sea_starts`` (criterio 8); ningún otro error.
"""

from __future__ import annotations

from collections.abc import Collection
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..cancel import CancelCheck
from ..clausewitz import Severity
from ..validate.model import Problem

if TYPE_CHECKING:
    from ..validate.context import ValidationContext
    from .raster import ProvinceRaster

_E, _W, _I = Severity.ERROR, Severity.WARNING, Severity.INFO

# Código definitivo → gravedad. El comentario dice qué mira; «(ya existe)» = regla registrada antes de la 5.
CODES = MappingProxyType({
    # BMP y definition.csv
    "bmp_size_mismatch": _E,                 # terrain.bmp o rivers.bmp no miden lo mismo que provinces.bmp
    "bmp_color_unmapped": _W,                # color del BMP sin fila con id (ya existe); args: color, pixels
    "definition_duplicate_color": _W,        # dos filas con el mismo color (ya existe como aviso de parse)
    "definition_duplicate_id": _W,           # dos filas con el mismo id (ya existe como aviso de parse)
    "definition_bad_row": _W,                # fila con id sin tres colores numéricos (ya existe)
    "definition_bad_number": _I,             # un número con cola («223.»): el juego lee 223
    "province_id_invalid": _E,               # id fuera de 1 ≤ id < max_provinces (ya existe)
    "province_without_pixels": _W,           # fila con id cuyo color no está en el BMP
    "province_fragmented": _I,               # provincia en varios trozos
    # default.map
    "max_provinces_too_small": _E,           # max_provinces ≤ mayor id de definition.csv
    "sea_start_unknown": _E,                 # sea_starts nombra un id sin fila
    "sea_start_duplicate": _W,               # un id repetido en sea_starts (2800 en vanilla); args: province, count
    # regiones, continentes y climas
    "land_province_without_region": _E,      # (ya existe)
    "land_province_multiple_regions": _E,    # (ya existe)
    "sea_in_region": _E,                     # (ya existe)
    "land_province_without_continent": _E,   # (ya existe)
    "region_empty": _I,                      # estado sin provincias (las 3 de region_sea de vanilla no cuentan)
    "region_not_contiguous": _I,             # estado cuyas provincias no se tocan (ni por un estrecho)
    "climate_layout": _W,                    # un clima sin su pareja de entradas, o con más de una lista
    # positions.txt, historias y localización
    "positions_missing": _I,                 # provincia sin bloque en positions.txt
    "missing_history": _W,                   # provincia de tierra sin historia
    "province_history_duplicate": _E,        # un id con dos historias (ya existe; 1396 y 1397 en vanilla)
    "province_file_name": _I,                # nombre irregular (sin « - »); 1337 y 3246 en vanilla
    "missing_prov_localisation": _W,         # falta PROV<id>
    # adjacencies.csv
    "adjacency_unknown_province": _E,        # una provincia de la fila no existe
    "adjacency_bad_type": _E,                # tipo distinto de sea, impassable y canal
    "adjacency_through_not_sea": _E,         # el «a través» de un estrecho o canal no es de mar
    # terrain.bmp
    "terrain_sea_mismatch": _W,              # terreno de agua en una provincia de tierra, o al revés
})

# Nombre de wizard §16.6 → código definitivo, donde difieren.
RENAMED = MappingProxyType({
    "definition_color_duplicate": "definition_duplicate_color",
    "duplicate_id": "definition_duplicate_id",
    "definition_id_ge_max": "province_id_invalid",
    "province_multiple_regions": "land_province_multiple_regions",
    "province_without_continent": "land_province_without_continent",
})

# Códigos que necesitan el ráster (leer el BMP: segundos la primera vez, ≤ 0,5 s desde la caché).
RASTER_CODES = frozenset({"bmp_size_mismatch", "bmp_color_unmapped", "province_without_pixels",
                          "province_fragmented", "region_not_contiguous", "terrain_sea_mismatch"})


def check_map(ctx: ValidationContext, *, codes: Collection[str] | None = None,
              raster: ProvinceRaster | None = None, cancelled: CancelCheck = None) -> list[Problem]:
    """Los problemas de coherencia del mapa de la vista efectiva de ``ctx``, ordenados por archivo y línea.

    ``codes`` limita la comprobación (None = todos los de ``CODES``; uno desconocido, ``KeyError``). Si hacen
    falta códigos de ``RASTER_CODES`` y no se pasa ``raster``, lo carga con ``cache.load_or_build`` de los bytes
    efectivos; si el BMP falta o no se puede leer, esos códigos no dan nada (el problema del archivo ya lo da la
    familia «files»). Un archivo del mapa que falta no lanza: sus invariantes simplemente no se evalúan.

    No marca nada como heredado: eso lo hace el validador con la línea base (I11). ``Cancelled`` si se cancela.
    """
    raise NotImplementedError


def severity_of(code: str) -> Severity:
    """Gravedad de un código de ``CODES`` (``KeyError`` si no es del mapa)."""
    return CODES[code]
