"""Parámetros del taller (wizard §18.7): nivel, origen, destino, rejilla y ``ForgeParams``.

``ForgeParams`` es inmutable y se guarda en ``project.json`` (``to_json``/``from_json``). ``validate`` da los
problemas que se ven antes de calcular nada (tamaño, número de ids).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields, replace
from enum import Enum
from types import MappingProxyType
from typing import ClassVar

VANILLA_SIZE = (5616, 2160)
VANILLA_LAND, VANILLA_SEA = 2700, 545          # provincias de tierra y de mar objetivo a 5616×2160 (escaladas)
MAX_IDS = 65535                                # provinces.bmp se traduce a uint16 (textura de 256×256 [R1])
SIZE_STEP = 24                                 # W y H múltiplos de 24 (las texturas se dividen por 3, 6 y 8)
MIN_CELLS, MAX_CELLS = 2000, 200_000
DEFAULT_SECONDARY = MappingProxyType({"building_construction": 6, "military_construction": 7, "factory": 8,
                                      "fort": 10, "railroad": 5})


class Level(Enum):
    MAP = "map"
    WORLD = "world"
    OVERLAY = "overlay"


class Origin(Enum):
    GENERATE = "generate"
    BITMAPS = "bitmaps"
    HEIGHTMAP = "heightmap"
    FMG_JSON = "fmg_json"


class Owners(Enum):
    """Opción «Dueños» de Solo mapa (pantalla 7)."""

    EXISTING_TAGS = "existing_tags"
    NONE = "none"


@dataclass(frozen=True)
class ExportTarget:
    kind: str = "this_mod"                     # "this_mod" | "new_mod"
    new_mod_name: str | None = None


@dataclass(frozen=True)
class LatticeSpec:
    """La rejilla de celdas: se fija en la pantalla 1 y no cambia con los demás parámetros (§18.4)."""

    cells: int
    seed: int
    kind: str = "hex"
    jitter: float = 0.3
    wrap_x: bool = True


@dataclass(frozen=True)
class ForgeParams:
    level: Level = Level.MAP
    origin: Origin = Origin.GENERATE
    target: ExportTarget = ExportTarget()
    size: tuple[int, int] = VANILLA_SIZE
    seed: int = 0
    lattice: LatticeSpec | None = None         # None = automática (``lattice_spec``)
    template: str = "continents"
    template_text: str | None = None           # plantilla propia (sintaxis de FMG con la y del juego)
    land_fraction: float = 0.34
    lat_south: float = -60.0
    lat_north: float = 75.0
    temp_equator: float = 27.0
    temp_poles: tuple[float, float] = (-30.0, -25.0)
    precipitation: float = 1.0
    river_flux_quantile: float = 0.75
    min_lake_cells: int = 4
    land_provinces: int | None = None          # None = 2 700 escaladas con el área
    sea_provinces: int | None = None           # None = 545 escaladas con el área
    size_variance: float = 0.75
    provinces_per_state: float = 4.92
    continents: tuple[str, ...] = ()           # vacío = los de la instalación
    hills_height: int = 44
    mountain_height: int = 67
    farmland_share: float = 0.2
    strait_max_gap_px: int = 8
    explicit_terrain: str = "overrides_only"
    terrain_min_index_share: float = 0.005
    owners: Owners = Owners.EXISTING_TAGS
    existing_tags: int = 60
    colonized_fraction: float = 0.85
    countries: int = 60
    civilized_fraction: float = 0.5
    keep_existing_tags: bool = True
    cultures: int = 24
    culture_groups: int = 8
    religion_mode: str = "map_existing"
    total_population: int = 250_000_000
    name_source: str = "syllables"             # "syllables" | "custom"
    custom_names: tuple[str, ...] = ()
    flag_style: str = "simple"
    secondary_point_px: MappingProxyType = field(default=DEFAULT_SECONDARY)

    # Lo que el modo sencillo enseña; el resto es «avanzado» (§18.2).
    SIMPLE: ClassVar[frozenset[str]] = frozenset({"size", "template", "seed", "countries", "owners", "existing_tags"})

    @property
    def width(self) -> int:
        return int(self.size[0])

    @property
    def height(self) -> int:
        return int(self.size[1])

    def area_scale(self) -> float:
        return (self.width * self.height) / float(VANILLA_SIZE[0] * VANILLA_SIZE[1])

    def land_target(self) -> int:
        if self.land_provinces is not None:
            return max(1, int(self.land_provinces))
        return max(8, int(round(VANILLA_LAND * self.area_scale())))

    def sea_target(self) -> int:
        if self.sea_provinces is not None:
            return max(1, int(self.sea_provinces))
        return max(4, int(round(VANILLA_SEA * self.area_scale())))

    def lattice_spec(self) -> LatticeSpec:
        """La rejilla efectiva: N = ⌈7,3 · L / f_tierra⌉ acotado a [2 000, 200 000] (§18.3, paso 1)."""
        if self.lattice is not None:
            return self.lattice
        cells = math.ceil(7.3 * self.land_target() / max(self.land_fraction, 0.05))
        return LatticeSpec(cells=min(MAX_CELLS, max(MIN_CELLS, cells)), seed=self.seed)

    def with_(self, **changes) -> ForgeParams:
        return replace(self, **changes)

    def validate(self) -> list[tuple[str, dict]]:
        """Problemas de los parámetros como ``(código, argumentos)`` (los textos están en ``issues``)."""
        out: list[tuple[str, dict]] = []
        w, h = self.size
        if w % SIZE_STEP or h % SIZE_STEP or (w, h) != VANILLA_SIZE:
            out.append(("forge_size", {"width": w, "height": h}))
        total = self.land_target() + self.sea_target()
        if total > MAX_IDS:
            out.append(("forge_too_many_provinces", {"count": total, "limit": MAX_IDS}))
        return out

    # --- persistencia ---------------------------------------------------------------------------------------

    def __reduce__(self):
        # ``MappingProxyType`` no se puede picklear: cruza al proceso trabajador como JSON.
        return (_params_from_json, (self.to_json(),))

    def to_json(self) -> dict:
        data = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, Enum):
                value = value.value
            elif isinstance(value, (ExportTarget, LatticeSpec)):
                value = asdict(value)
            elif isinstance(value, MappingProxyType):
                value = dict(value)
            elif isinstance(value, tuple):
                value = list(value)
            data[f.name] = value
        return data

    @classmethod
    def from_json(cls, data: dict) -> ForgeParams:
        known = {f.name: f for f in fields(cls)}
        values = {}
        for key, value in (data or {}).items():
            if key not in known:
                continue
            if key == "level":
                value = Level(value)
            elif key == "origin":
                value = Origin(value)
            elif key == "owners":
                value = Owners(value)
            elif key == "target":
                value = ExportTarget(**value)
            elif key == "lattice":
                value = LatticeSpec(**value) if value else None
            elif key == "secondary_point_px":
                value = MappingProxyType({str(k): int(v) for k, v in value.items()})
            elif isinstance(value, list):
                value = tuple(value)
            values[key] = value
        return cls(**values)


def _params_from_json(data: dict) -> ForgeParams:
    return ForgeParams.from_json(data)
