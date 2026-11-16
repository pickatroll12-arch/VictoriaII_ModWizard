"""El modelo del taller (wizard §18.7): ``ForgeWorld`` y sus tablas.

- ``CellLayers``: una fila por celda de la rejilla (etapa de celdas, coordenadas finales).
- ``ProvisionalTable``: una fila por provincia provisional (las del grafo de celdas, antes del ráster).
- ``ForgeRaster``: el ráster a una escala (ids compactados, terreno, ríos, posiciones y estrechos).
- ``InstallProfile``: lo aprendido de la instalación en tiempo de ejecución (paletas, índices, TAG…). Nunca se
  guarda en el repositorio ni en el mod (§18.13).

Todo son arrays de numpy y tipos simples: un ``ForgeWorld`` cruza el proceso trabajador con ``pickle``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace

import numpy as np

from .params import ForgeParams

# Categorías de Victoria II que usa el taller (el orden es el de los arrays ``category``; 0 = agua).
CATS = ("ocean", "arctic", "farmlands", "forest", "hills", "woods", "mountain", "steppe", "plains", "jungle",
        "marsh", "desert")
CAT_INDEX = {name: i for i, name in enumerate(CATS)}
CLIMATES = ("mild", "temperate", "harsh", "inhospitable")
SEA_LEVEL = 20


def digest(*arrays) -> str:
    """Huella sha256 (16 hex) de arrays o bytes, para comparar etapas y comprobar el determinismo."""
    h = hashlib.sha256()
    for a in arrays:
        if isinstance(a, (bytes, bytearray)):
            h.update(bytes(a))
        elif a is None:
            h.update(b"\0")
        else:
            arr = np.ascontiguousarray(a)
            h.update(str(arr.dtype).encode() + str(arr.shape).encode())
            h.update(arr.tobytes())
    return h.hexdigest()[:16]


@dataclass
class CellLayers:
    """Capas por celda. ``edges`` son las aristas del grafo (E, 2); ``seam_edge`` marca las que cruzan x = 0/W."""

    pts: np.ndarray
    nbr: np.ndarray
    edges: np.ndarray
    seam_edge: np.ndarray
    h: np.ndarray | None = None
    land: np.ndarray | None = None
    ocean: np.ndarray | None = None
    lake: np.ndarray | None = None
    temp: np.ndarray | None = None
    prec: np.ndarray | None = None
    flux: np.ndarray | None = None
    recv: np.ndarray | None = None
    river: np.ndarray | None = None
    category: np.ndarray | None = None
    suit: np.ndarray | None = None
    province0: np.ndarray | None = None

    def evolve(self, **changes) -> CellLayers:
        return replace(self, **changes)


@dataclass
class ProvisionalTable:
    """Atributos por provincia provisional. ``-1`` = sin valor (el mar no tiene estado, continente ni clima)."""

    is_sea: np.ndarray
    cx: np.ndarray
    cy: np.ndarray
    cells: np.ndarray
    dom_cat: np.ndarray
    suit: np.ndarray
    temp: np.ndarray
    state: np.ndarray | None = None
    continent: np.ndarray | None = None
    climate: np.ndarray | None = None
    owner: np.ndarray | None = None
    culture: np.ndarray | None = None
    religion: np.ndarray | None = None
    goods: list | None = None
    life_rating: np.ndarray | None = None
    population: np.ndarray | None = None
    capitals: np.ndarray | None = None          # provincia provisional capital de cada dueño (índice de ``owners``)
    locked: np.ndarray | None = None

    @property
    def count(self) -> int:
        return int(self.is_sea.size)

    @property
    def land_count(self) -> int:
        return int((~self.is_sea).sum())

    def evolve(self, **changes) -> ProvisionalTable:
        return replace(self, **changes)


@dataclass
class ForgeRaster:
    """El ráster en coordenadas del juego (H1: fila 0 = sur) a una escala (1 = final, 4 = vista previa).

    ``ids`` compactados (tierra 1..L, mar L+1..N); ``parent[id]`` es la provincia provisional madre (0-based) o
    -1. Las tablas ``province_*`` son por id final (índice 0 sin uso), ya reconciliadas."""

    ids: np.ndarray
    parent: np.ndarray
    is_sea: np.ndarray
    scale: int
    land_count: int
    pix_cat: np.ndarray | None = None
    h_px: np.ndarray | None = None
    terrain: np.ndarray | None = None
    rivers: np.ndarray | None = None
    edges: np.ndarray | None = None              # pares de vecinos (a < b), con la costura
    positions: dict | None = None
    straits: np.ndarray | None = None            # (k, 4): a, b, through, hueco
    state: np.ndarray | None = None
    continent: np.ndarray | None = None
    climate: np.ndarray | None = None
    owner: np.ndarray | None = None
    culture: np.ndarray | None = None
    religion: np.ndarray | None = None
    goods: list | None = None
    life_rating: np.ndarray | None = None
    population: np.ndarray | None = None
    capitals: list | None = None                 # id final de la capital de cada dueño (-1: sin tierra)
    names: list | None = None                    # nombre por id final
    colors: np.ndarray | None = None             # (N+1,) RGB empaquetado 0xRRGGBB
    report: dict = field(default_factory=dict)

    @property
    def count(self) -> int:
        return int(self.is_sea.size - 1)

    @property
    def width(self) -> int:
        return int(self.ids.shape[1])

    @property
    def height(self) -> int:
        return int(self.ids.shape[0])

    def evolve(self, **changes) -> ForgeRaster:
        return replace(self, **changes)


@dataclass(frozen=True)
class TagInfo:
    """Un TAG existente de la instalación efectiva (para «Repartir entre TAG existentes»)."""

    tag: str
    provinces: int
    capital: int | None
    culture: str | None
    religion: str | None
    civilized: bool
    history_rel: str | None


@dataclass
class InstallProfile:
    """Lo aprendido de la instalación (juego + mod) en tiempo de ejecución, o la paleta procedural sin instalación."""

    cat_of: dict
    idx_by_cat: dict
    widths: list
    width_share: list
    terrain_palette: bytes
    rivers_palette: bytes
    cm_pal: np.ndarray
    water_mean: np.ndarray
    tags: list = field(default_factory=list)
    pop_dates: list = field(default_factory=list)
    top_culture: str = "default_culture"
    top_religion: str = "default_religion"
    continents: list = field(default_factory=list)
    climates: list = field(default_factory=list)          # nombres de clima de la instalación
    climate_blocks: str = ""                               # bloques de modificadores de climate.txt (texto)
    default_map: str = ""                                  # default.map de la instalación (para copiar sus claves)
    continent_text: str = ""                               # continent.txt de la instalación (sus modificadores)
    goods: list = field(default_factory=list)
    synthetic: bool = False
    source_digest: str = ""

    def index_category(self, index: int) -> str | None:
        return self.cat_of.get(int(index))


@dataclass
class StepState:
    """Estado de un paso en el asistente: pending, computed, edited, imported o locked."""

    status: str = "pending"
    digest: str = ""
    seconds: float = 0.0


@dataclass
class ForgeEntity:
    """Una entidad del mundo con uid estable (las ediciones van por uid, nunca por id de provincia)."""

    uid: str
    kind: str
    name: str
    data: dict = field(default_factory=dict)
    locked: bool = False


@dataclass
class ForgeWorld:
    params: ForgeParams
    lattice: object                               # graph.Lattice
    cells: CellLayers
    provisional: ProvisionalTable | None = None
    install: InstallProfile | None = None
    entities: dict = field(default_factory=dict)  # "owner" | "culture" | "religion" | "name" -> lista o dict
    imported: dict = field(default_factory=dict)
    raster: ForgeRaster | None = None
    steps: dict = field(default_factory=dict)
    edits: tuple = ()

    def evolve(self, **changes) -> ForgeWorld:
        return replace(self, **changes)

    def cells_digest(self) -> str:
        c = self.cells
        return digest(c.h, c.land, c.category, c.river, c.province0)

    def world_digest(self) -> str:
        p = self.provisional
        if p is None:
            return ""
        return digest(p.state, p.continent, p.climate, p.owner, p.culture, p.religion, p.life_rating,
                      np.array([g or "" for g in (p.goods or [])], dtype="U32"))
