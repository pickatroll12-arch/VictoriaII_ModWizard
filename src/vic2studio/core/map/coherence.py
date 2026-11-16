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

import re
import threading
from functools import cached_property

from ..cancel import CancelCheck, raise_if_cancelled
from ..clausewitz import Severity
from ..clausewitz.nodes import Block
from ..index.model import KIND_PROVINCE, KIND_PROVINCE_HISTORY, KIND_SEA_PROVINCE
from ..tablecsv import cell_int
from ..validate.model import Problem
from ..vfs.paths import InvalidPathError, VPath
from .adjacency import TYPE_SEA, TYPES, AdjacencyTable
from .default_map import DEFAULT_MAP_REL, DefaultMap
from .definition import DefinitionTable
from .positions import Positions

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
    # Ya lo da ``loc_key_missing`` (familia «localisation») con la clave ``PROV<id>``: no se repite aquí.
    "missing_prov_localisation": "loc_key_missing",
})

# Códigos que ya registraba la familia «provinces» antes de la iteración 5: ``check_map`` llama a sus reglas.
EXISTING = frozenset({"bmp_color_unmapped", "province_id_invalid", "land_province_without_region",
                      "land_province_multiple_regions", "sea_in_region", "land_province_without_continent",
                      "province_history_duplicate"})
# Códigos nuevos (los registra ``core/validate/rules/map.py``).
NEW_CODES = tuple(code for code in CODES if code not in EXISTING)

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
    from ..validate.registry import discover_rules

    discover_rules()                     # los códigos nuevos se registran en validate/rules/map.py
    wanted = set(CODES) if codes is None else set(codes)
    for code in wanted:
        CODES[code]                      # KeyError si no es del mapa
    if cancelled is None:
        cancelled = getattr(ctx, "cancelled", None)
    checker = _Checker(ctx, wanted, raster, cancelled)
    checker.run()
    return sorted(checker.problems, key=lambda p: (str(p.rel or ""), p.line or 0, p.code, str(sorted(p.args.items()))))


class _Checker:
    def __init__(self, ctx, wanted: set[str], raster, cancelled) -> None:
        self.ctx = ctx
        self.wanted = wanted
        self._raster = raster
        self._raster_loaded = raster is not None
        self.cancelled = cancelled
        self.problems: list[Problem] = []
        files = getattr(ctx.rules, "map_files", None) or {}
        self.files = {key: self._rel(files.get(key), default) for key, default in _MAP_DEFAULTS.items()}

    @staticmethod
    def _rel(name, default: str) -> VPath:
        try:
            return VPath.of(f"map/{name}") if name else VPath.of(f"map/{default}")
        except (InvalidPathError, TypeError):
            return VPath.of(f"map/{default}")

    def want(self, *codes: str) -> bool:
        return any(code in self.wanted for code in codes)

    def add(self, code: str, rel, line=None, *, province=None, **args) -> None:
        from ..validate.registry import make_problem

        if code not in self.wanted:
            return
        entity = None
        if province is not None:
            kind = KIND_SEA_PROVINCE if int(province) in self.sea else KIND_PROVINCE
            entity = (kind, str(province))
            args.setdefault("province", str(province))
        self.problems.append(make_problem(code, rel, line, entity=entity, **args))

    def step(self) -> None:
        raise_if_cancelled(self.cancelled)

    # --- datos compartidos ------------------------------------------------------------------------

    @cached_property
    def definition(self):
        data = self.ctx.read(self.files["definitions"])
        if data is None:
            return None
        return DefinitionTable.parse(data, rel=self.files["definitions"])

    @cached_property
    def ids(self) -> set[int]:
        found = self.definition
        return set() if found is None else {pid for pid in found[0].ids() if pid > 0}

    @cached_property
    def default_map(self) -> DefaultMap | None:
        parsed = self.ctx.parse(DEFAULT_MAP_REL)
        return None if parsed is None else DefaultMap(parsed.document)

    @cached_property
    def sea(self) -> set[int]:
        return set(getattr(self.ctx.rules, "sea", ()) or ())

    @property
    def raster(self):
        if not self._raster_loaded:
            self._raster_loaded = True
            bmp = self.ctx.read(self.files["provinces"])
            csv = self.ctx.read(self.files["definitions"])
            if bmp is not None and csv is not None:
                from .bmp import BmpError
                from .cache import load_or_build

                try:
                    self._raster = load_or_build(bmp, csv, forbidden=_layer_roots(self.ctx),
                                                 cancelled=self.cancelled)[0]
                except (BmpError, ValueError):
                    self._raster = None
        return self._raster

    # --- comprobaciones ---------------------------------------------------------------------------

    def run(self) -> None:
        existing = self.wanted & EXISTING
        if existing:
            self.existing(existing)
        self.step()
        if self.want("definition_duplicate_color", "definition_duplicate_id", "definition_bad_row",
                     "definition_bad_number"):
            self.definition_rows()
        if self.want("max_provinces_too_small", "sea_start_unknown", "sea_start_duplicate"):
            self.default_map_checks()
        if self.want("region_empty", "climate_layout"):
            self.group_checks()
        if self.want("positions_missing"):
            self.positions()
        if self.want("missing_history", "province_file_name"):
            self.histories()
        if self.want("adjacency_unknown_province", "adjacency_bad_type", "adjacency_through_not_sea"):
            self.adjacencies()
        self.step()
        if self.want(*RASTER_CODES):
            self.raster_checks()

    def existing(self, codes: set[str]) -> None:
        from ..validate.rules import provinces as rules

        functions = {rules.unmapped_colors: {"bmp_color_unmapped"},
                     rules.province_ids: {"province_id_invalid"},
                     rules.province_history_duplicates: {"province_history_duplicate"},
                     rules.region_invariants: {"land_province_without_region", "land_province_multiple_regions",
                                               "sea_in_region", "land_province_without_continent"}}
        for function, produced in functions.items():
            if produced & codes:
                self.problems.extend(p for p in function(self.ctx) if p.code in codes)

    def definition_rows(self) -> None:
        found = self.definition
        if found is None:
            return
        table, parse_problems = found
        rel = self.files["definitions"]
        for problem in parse_problems:
            self.add(problem.code, rel, problem.line, **dict(problem.args))
        if "definition_bad_number" in self.wanted:
            for row in table.rows():
                if row.id is None:
                    continue
                fields = row.raw.split(";")
                for column, text in enumerate(fields[:4]):
                    stripped = text.strip()
                    value = cell_int(stripped)
                    if value is not None and stripped != str(value):
                        self.add("definition_bad_number", rel, row.line, province=row.id, text=stripped,
                                 value=value)
                        break

    def default_map_checks(self) -> None:
        default = self.default_map
        if default is None:
            return
        rel = DEFAULT_MAP_REL
        maximum = default.max_provinces()
        largest = max(self.ids, default=0)
        if maximum is not None and self.ids and maximum <= largest:
            self.add("max_provinces_too_small", rel, max=maximum, largest=largest)
        starts = default.sea_starts()
        if self.ids:
            for pid in dict.fromkeys(starts):
                if pid not in self.ids:
                    self.add("sea_start_unknown", rel, province=pid)
        for pid, count in sorted(default.sea_start_duplicates().items()):
            self.add("sea_start_duplicate", rel, province=pid, count=count)

    def group_checks(self) -> None:
        from .groups import CLIMATE_REL, LAYOUT_FLAT, read_groups

        region_rel = self.files["region"]
        data = self.ctx.read(region_rel)
        if data is not None and "region_empty" in self.wanted:
            parsed = self.ctx.parse(region_rel)
            lines = _lines(parsed.document) if parsed is not None else {}
            for name, members in read_groups(data, LAYOUT_FLAT).items():
                if not members:
                    self.add("region_empty", region_rel, lines.get(name), region=name)
        if "climate_layout" in self.wanted:
            parsed = self.ctx.parse(CLIMATE_REL)
            if parsed is None:
                return
            entries: dict[str, list] = {}
            for entry in parsed.document:
                if entry.key is not None and isinstance(entry.value, Block):
                    entries.setdefault(entry.key.text, []).append(entry)
            for name, found in entries.items():
                lists = [e for e in found if len(e.value) and all(c.key is None for c in e.value)]
                modifiers = [e for e in found if e not in lists]
                if len(lists) != 1 or len(modifiers) > 1 or len(found) != 2:
                    self.add("climate_layout", CLIMATE_REL, found[0].line, climate=name, entries=len(found),
                             lists=len(lists))

    def positions(self) -> None:
        rel = self.files["positions"]
        parsed = self.ctx.parse(rel)
        if parsed is None or not self.ids:
            return
        present = set(Positions(parsed.document).ids())
        for pid in sorted(self.ids - present):
            self.add("positions_missing", rel, province=pid)

    def histories(self) -> None:
        index = self.ctx.index
        histories = {}
        for symbol in index.symbols(KIND_PROVINCE_HISTORY):
            histories[symbol.name] = symbol
            if "province_file_name" in self.wanted and not _regular_name(symbol.rel.name):
                self.add("province_file_name", symbol.rel, province=int(symbol.name), file=symbol.rel.name)
        if "missing_history" in self.wanted:
            land = [int(name) for name in index.names(KIND_PROVINCE) if name.isdigit()]
            folder = VPath.of("history/provinces")
            for pid in sorted(land):
                if str(pid) not in histories and pid not in self.sea:
                    self.add("missing_history", folder, province=pid)

    def adjacencies(self) -> None:
        rel = self.files["adjacencies"]
        data = self.ctx.read(rel)
        if data is None:
            return
        table, problems = AdjacencyTable.parse(data, rel=rel)
        for problem in problems:
            if problem.code == "adjacency_bad_type":
                self.add("adjacency_bad_type", rel, problem.line, type=problem.args.get("type", ""))
        if not self.ids:
            return
        for row in table.rows():
            if row.start is None or row.end is None or row.type not in TYPES:
                continue
            for pid in (row.start, row.end):
                if pid not in self.ids:
                    self.add("adjacency_unknown_province", rel, row.line, province=pid)
            if row.type == TYPE_SEA and row.through:
                if row.through not in self.ids:
                    self.add("adjacency_unknown_province", rel, row.line, province=row.through)
                elif row.through not in self.sea:
                    self.add("adjacency_through_not_sea", rel, row.line, province=row.through,
                             start=row.start, end=row.end, type=row.type)

    def raster_checks(self) -> None:
        provinces_rel = self.files["provinces"]
        main = self.ctx.read(provinces_rel)
        if main is None:
            return
        from .bmp import BmpError, bmp_size, read_bmp

        try:
            size = bmp_size(main)
        except BmpError:
            return
        layers = {}
        for key in ("terrain", "rivers"):
            data = self.ctx.read(self.files[key])
            if data is None:
                continue
            try:
                other = bmp_size(data)
            except BmpError:
                continue
            if other != size:
                self.add("bmp_size_mismatch", self.files[key], file=self.files[key].name,
                         width=other[0], height=other[1], expected_width=size[0], expected_height=size[1])
            else:
                layers[key] = data
        if not self.want("province_without_pixels", "province_fragmented", "region_not_contiguous",
                         "terrain_sea_mismatch"):
            return
        raster = self.raster
        if raster is None:
            return
        definitions = self.files["definitions"]
        lines = {}
        if self.definition is not None:
            lines = {row.id: row.line for row in self.definition[0].rows() if row.id is not None}
        counts = raster.pixel_count
        if "province_without_pixels" in self.wanted:
            for pid in sorted(self.ids):
                if pid >= counts.shape[0] or counts[pid] == 0:
                    self.add("province_without_pixels", definitions, lines.get(pid), province=pid)
        self.step()
        if "province_fragmented" in self.wanted:
            for pid, pieces in sorted(self.fragments(raster, main).items()):
                if pid in self.ids:
                    self.add("province_fragmented", provinces_rel, province=pid, parts=pieces)
        if "region_not_contiguous" in self.wanted:
            self.contiguity(raster)
        if "terrain_sea_mismatch" in self.wanted and "terrain" in layers:
            try:
                image = read_bmp(layers["terrain"])
            except BmpError:
                return
            if image.pixels.ndim != 2:
                return
            terrain_txt = self.ctx.read(self.files["terrain_definition"])
            if terrain_txt is None:
                return
            from .facts import terrain_types

            kinds = terrain_types(terrain_txt)
            water = _water_categories(self.ctx.index)
            majority = raster.majority(image.pixels)
            for pid in sorted(self.ids):
                if pid >= majority.shape[0] or majority[pid] < 0:
                    continue
                category = kinds.get(int(majority[pid]))
                if category is None:
                    continue
                is_water = category in water
                if is_water != (pid in self.sea):
                    self.add("terrain_sea_mismatch", self.files["terrain"], province=pid, terrain=category)

    def fragments(self, raster, bmp: bytes) -> dict[int, int]:
        """``{id: trozos}`` de las provincias partidas; se recuerda por el contenido del BMP y de definition.csv
        (contarlos en vanilla cuesta segundos y cada validación lo pediría)."""
        from .cache import raster_key
        from .geometry import parts

        key = raster_key(bmp, self.ctx.read(self.files["definitions"]) or b"")
        with _FRAGMENTS_LOCK:
            found = _FRAGMENTS.get(key)
        if found is not None:
            return found
        found = {}
        counts = raster.pixel_count
        for pid in range(1, counts.shape[0]):
            if counts[pid]:
                pieces = parts(raster, pid)
                if pieces > 1:
                    found[pid] = pieces
            if pid % 256 == 0:
                self.step()
        with _FRAGMENTS_LOCK:
            _FRAGMENTS[key] = found
            while len(_FRAGMENTS) > 4:
                _FRAGMENTS.pop(next(iter(_FRAGMENTS)))
        return found

    def contiguity(self, raster) -> None:
        neighbors = raster.neighbors()
        straits: dict[int, set[int]] = {}
        data = self.ctx.read(self.files["adjacencies"])
        if data is not None:
            for row in AdjacencyTable.parse(data)[0].rows():
                if row.start is not None and row.end is not None and row.type != "impassable":
                    straits.setdefault(row.start, set()).add(row.end)
                    straits.setdefault(row.end, set()).add(row.start)
        region_rel = self.files["region"]
        data = self.ctx.read(region_rel)
        if data is None:
            return
        from .groups import read_groups

        parsed = self.ctx.parse(region_rel)
        lines = _lines(parsed.document) if parsed is not None else {}
        for name, members in read_groups(data).items():
            group = set(members)
            if len(group) < 2:
                continue
            start = next(iter(group))
            seen = {start}
            stack = [start]
            while stack:
                pid = stack.pop()
                for other in (*neighbors.get(pid, ()), *straits.get(pid, ())):
                    if other in group and other not in seen:
                        seen.add(other)
                        stack.append(other)
            if seen != group:
                self.add("region_not_contiguous", region_rel, lines.get(name), region=name,
                         apart=" ".join(str(p) for p in sorted(group - seen)))


_FRAGMENTS: dict[str, dict[int, int]] = {}
_FRAGMENTS_LOCK = threading.Lock()
_MAP_DEFAULTS = {"definitions": "definition.csv", "provinces": "provinces.bmp", "positions": "positions.txt",
                 "terrain": "terrain.bmp", "rivers": "rivers.bmp", "terrain_definition": "terrain.txt",
                 "adjacencies": "adjacencies.csv", "region": "region.txt"}
_REGULAR_NAME = re.compile(r"^\s*\d+\s+-\s+.+\.txt$", re.IGNORECASE)


def _regular_name(name: str) -> bool:
    return bool(_REGULAR_NAME.match(name))


def _lines(document: Block) -> dict[str, int]:
    found: dict[str, int] = {}
    for entry in document:
        if entry.key is not None:
            found.setdefault(entry.key.text, entry.line)
    return found


def _water_categories(index) -> set[str]:
    from ..index.model import KIND_TERRAIN

    return {symbol.name for symbol in index.symbols(KIND_TERRAIN) if (symbol.attrs or {}).get("is_water")}


def _layer_roots(ctx) -> list:
    """Raíces del juego, el mod y las dependencias: la caché del ráster nunca escribe dentro."""
    roots = []
    for layer in getattr(ctx.snapshot, "layers", ()) or ():
        root = getattr(layer, "root", None)
        if root is not None:
            roots.append(root)
    return roots


def severity_of(code: str) -> Severity:
    """Gravedad de un código de ``CODES`` (``KeyError`` si no es del mapa)."""
    return CODES[code]
