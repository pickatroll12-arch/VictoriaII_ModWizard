"""El pipeline del taller (wizard §18.3): registro de pasos, etapa de celdas y etapa de ráster.

- **Etapa de celdas** (``run_cells``): una sola vez en las coordenadas finales, sea cual sea la escala de la vista.
  Decide qué es cada cosa: relieve, agua, provincias provisionales, estados, continentes, climas, dueños, culturas,
  población, RGO, life rating y nombres.
- **Etapa de ráster** (``run_raster``): a la escala pedida (4 para la vista previa, 1 para el final). Dibuja las
  provincias provisionales, arregla fragmentos, compacta los ids y reconcilia; después vecinos, estrechos,
  posiciones, terreno, ríos y texturas.

Un PRNG por paso (``default_rng([semilla, crc32(paso)])``): regenerar los ríos no cambia el relieve. Los pasos son
puros (``ForgeWorld → ForgeWorld``) y cancelables entre pasos y dentro de los largos.
"""

from __future__ import annotations

import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass, replace

import numpy as np

from ..cancel import CancelCheck, raise_if_cancelled
from . import biomes, climate, economy, edits as edit_ops, graph, hydro, partition, rasterize, reconcile, relief, \
    society, textures
from .data.templates import TEMPLATES
from .names import MarkovNames
from .params import ForgeParams, Level, Owners
from .world import CLIMATES, CellLayers, ForgeRaster, ForgeWorld, InstallProfile, StepState

ProgressFn = Callable[[str, int, int], None]
ALL_LEVELS = frozenset(Level)


@dataclass(frozen=True)
class StepContext:
    rng: np.random.Generator
    scale: int = 1
    progress: ProgressFn | None = None
    cancelled: CancelCheck = None


@dataclass(frozen=True)
class Step:
    id: str
    deps: tuple[str, ...]
    levels: frozenset
    stage: str                  # "cells" | "raster"
    version: int
    run: Callable[[ForgeWorld, StepContext], ForgeWorld]


def rng_for(seed: int, step_id: str) -> np.random.Generator:
    return np.random.default_rng([int(seed) & 0xFFFFFFFF, zlib.crc32(step_id.encode())])


# --- creación -----------------------------------------------------------------------------------------------

def new_world(params: ForgeParams, install: InstallProfile | None = None) -> ForgeWorld:
    """El mundo vacío con la rejilla fija de ``params.lattice_spec()`` (paso 1)."""
    from .install import synthetic_profile

    spec = params.lattice_spec()
    lat = graph.make_lattice(params.width, params.height, spec.cells, kind=spec.kind, jitter=spec.jitter,
                             wrap_x=spec.wrap_x, seed=spec.seed)
    nbr = graph.neighbors(lat)
    edges = graph.edges_from_padded(nbr)
    cells = CellLayers(pts=lat.pts, nbr=nbr, edges=edges, seam_edge=graph.seam_edges(lat, edges))
    return ForgeWorld(params=params, lattice=lat, cells=cells, install=install or synthetic_profile(),
                      steps={"lattice": StepState("computed")})


# --- pasos de la etapa de celdas ------------------------------------------------------------------------------

def _relief(world: ForgeWorld, ctx: StepContext) -> ForgeWorld:
    p = world.params
    imported = world.imported.get("heightmap")
    if imported is not None:
        # Un mapa de alturas importado trae su costa (agua < 20): no se recoloca el nivel del mar.
        h = np.asarray(imported, np.float64).copy()
    else:
        hm = relief.Heightmap(world.lattice, world.cells.nbr, ctx.rng, cancelled=ctx.cancelled)
        hm.run_template(p.template_text or TEMPLATES.get(p.template, TEMPLATES["continents"]))
        h = relief.sea_level(hm.h, p.land_fraction)
    h = edit_ops.apply_relief_edits(world, h)
    return world.evolve(cells=world.cells.evolve(h=h))


def _features(world: ForgeWorld, ctx: StepContext) -> ForgeWorld:
    h, land, ocean, lake = relief.features(world.cells.h, world.cells.edges, world.params.min_lake_cells)
    return world.evolve(cells=world.cells.evolve(h=h, land=land, ocean=ocean, lake=lake))


def _climate(world: ForgeWorld, ctx: StepContext) -> ForgeWorld:
    p, c = world.params, world.cells
    t = climate.temperature(world.lattice, c.h, lat_s=p.lat_south, lat_n=p.lat_north, t_eq=p.temp_equator,
                            t_np=p.temp_poles[0], t_sp=p.temp_poles[1])
    pr = climate.precipitation(world.lattice, c.h, t, modifier=p.precipitation, lat_s=p.lat_south,
                               lat_n=p.lat_north)
    return world.evolve(cells=c.evolve(temp=t, prec=pr))


def _hydro(world: ForgeWorld, ctx: StepContext) -> ForgeWorld:
    c = world.cells
    recv, flux, river = hydro.hydrology(c.h, c.nbr, c.prec, c.land, ~c.land,
                                        flux_quantile=world.params.river_flux_quantile, cancelled=ctx.cancelled)
    river = edit_ops.apply_river_edits(world, river)
    return world.evolve(cells=c.evolve(recv=recv, flux=flux, river=river))


def _biomes(world: ForgeWorld, ctx: StepContext) -> ForgeWorld:
    p, c = world.params, world.cells
    moist = biomes.moisture(c.prec, c.nbr, c.river)
    cat, suit = biomes.categories(c.h, c.land, c.temp, moist, c.river, hills=p.hills_height,
                                  mountain=p.mountain_height, farmland_share=p.farmland_share)
    cat = edit_ops.apply_category_edits(world, cat)
    return world.evolve(cells=c.evolve(category=cat, suit=suit))


def _provinces(world: ForgeWorld, ctx: StepContext) -> ForgeWorld:
    """Provincias provisionales. Las bloqueadas (§18.4) conservan sus celdas: se excluyen del reparto y vuelven
    con un índice nuevo (los índices provisionales se renumeran: las ediciones van por uid de celda, no por id)."""
    p, c = world.params, world.cells
    edges_ns = c.edges[~c.seam_edge]
    prev = world.provisional
    locked_cells = np.zeros(c.h.size, bool)
    if prev is not None and c.province0 is not None and prev.locked is not None and prev.locked.any():
        keep = c.province0
        locked_cells = prev.locked[keep] & (c.land == ~prev.is_sea[keep])
    n_locked = int(np.unique(c.province0[locked_cells]).size) if locked_cells.any() else 0
    free = partition.provinces(c.pts, edges_ns, c.h, c.land, c.suit, c.river,
                               land_target=max(1, p.land_target() - n_locked), sea_target=p.sea_target(),
                               size_variance=p.size_variance, W=world.lattice.W,
                               rng_land=rng_for(p.seed, "prov_land"), rng_sea=rng_for(p.seed, "prov_sea"),
                               mountain=p.mountain_height, exclude=locked_cells)
    prov0 = free
    if locked_cells.any():
        land_free = c.land & ~locked_cells
        nl = int(free[land_free].max()) + 1 if land_free.any() else 0
        old = np.unique(c.province0[locked_cells])
        prov0 = free.copy()
        sea_cells = ~c.land & ~locked_cells
        prov0[sea_cells] = free[sea_cells] + old.size
        for i, o in enumerate(old.tolist()):
            prov0[locked_cells & (c.province0 == o)] = nl + i
    t, pairs = partition.table(prov0, c.land, c.pts, c.category, c.suit, c.temp, c.edges, world.lattice.W)
    if locked_cells.any():
        t.locked[np.unique(prov0[locked_cells])] = True
    t.locked[:] = edit_ops.apply_locks(world, t.locked, prov0)
    ent = dict(world.entities)
    ent["pairs"] = pairs
    return world.evolve(cells=c.evolve(province0=prov0), provisional=t, entities=ent)


def _states(world: ForgeWorld, ctx: StepContext) -> ForgeWorld:
    p, t = world.params, world.provisional
    pairs = world.entities.get("pairs")
    st = partition.states(t, pairs, per_state=p.provinces_per_state, W=world.lattice.W, rng=ctx.rng)
    k = len(p.continents) or len(world.install.continents) or 6
    cont = partition.continents(t, pairs, k=k, W=world.lattice.W, rng=rng_for(p.seed, "continents"))
    clim = partition.climates(t)
    return world.evolve(provisional=t.evolve(state=st, continent=cont, climate=clim))


def _owners(world: ForgeWorld, ctx: StepContext) -> ForgeWorld:
    p, t, c = world.params, world.provisional, world.cells
    adj = society.adjacency(t, world.entities.get("pairs"), c.province0, c.nbr, c.land)
    res = society.owners_for_map(t, adj, list(world.install.tags), mode=p.owners, k=p.existing_tags,
                                 colonized=p.colonized_fraction, W=world.lattice.W, rng=ctx.rng,
                                 top_culture=world.install.top_culture, top_religion=world.install.top_religion)
    owner = edit_ops.apply_owner_edits(world, res["owner"], res["owners"])
    ent = dict(world.entities)
    ent.update(owners=res["owners"], civilized=res.get("civilized", []), cultures=res["cultures"],
               religions=res["religions"])
    return world.evolve(provisional=t.evolve(owner=owner, culture=res["culture"], religion=res["religion"],
                                             capitals=res["capitals"]), entities=ent)


def _economy(world: ForgeWorld, ctx: StepContext) -> ForgeWorld:
    p, t = world.params, world.provisional
    goods = economy.trade_goods(t, ctx.rng, world.install.goods)
    return world.evolve(provisional=t.evolve(goods=goods, life_rating=economy.life_rating(t),
                                             population=economy.population(t, p.total_population)))


def _names(world: ForgeWorld, ctx: StepContext) -> ForgeWorld:
    p, t = world.params, world.provisional
    gen = MarkovNames(int(ctx.rng.integers(2 ** 31)), p.name_source, p.custom_names)
    ent = dict(world.entities)
    ent["province_names"] = [gen.name("province") for _ in range(t.count)]
    n_states = int(t.state.max()) + 1 if t.state is not None and t.state.size and t.state.max() >= 0 else 0
    ent["state_names"] = [gen.name("state") for _ in range(n_states)]
    n_cont = int(t.continent.max()) + 1 if t.continent is not None and t.continent.size and t.continent.max() >= 0 \
        else 0
    names = list(p.continents) or list(world.install.continents)
    ent["continent_names"] = [names[i] if i < len(names) else f"forge_continent_{i + 1}" for i in range(n_cont)]
    ent["climate_names"] = _climate_names(world.install)
    ent["names_seed"] = int(ctx.rng.integers(2 ** 31))
    world = world.evolve(entities=ent)
    return edit_ops.apply_name_edits(world)


def _climate_names(install: InstallProfile) -> list[str]:
    """Nombre de clima de la instalación para cada clase (mild, temperate, harsh, inhospitable). Una clase que la
    instalación no tiene usa la más cercana que sí tenga; sin climas, nombres propios."""
    found = {}
    for c in CLIMATES:
        match = next((n for n in install.climates if n.lower().startswith(c)), None)
        if match:
            found[c] = match
    if not found:
        return [f"{c}_climate" for c in CLIMATES]
    order = list(CLIMATES)
    out = []
    for i, c in enumerate(order):
        if c in found:
            out.append(found[c])
            continue
        near = sorted((abs(j - i), j) for j, other in enumerate(order) if other in found)
        out.append(found[order[near[0][1]]])
    return out


CELL_STEPS: tuple[Step, ...] = (
    Step("relief", (), ALL_LEVELS, "cells", 1, _relief),
    Step("features", ("relief",), ALL_LEVELS, "cells", 1, _features),
    Step("climate", ("features",), ALL_LEVELS, "cells", 1, _climate),
    Step("hydro", ("climate",), ALL_LEVELS, "cells", 1, _hydro),
    Step("biomes", ("hydro",), ALL_LEVELS, "cells", 1, _biomes),
    Step("provinces", ("biomes",), ALL_LEVELS, "cells", 1, _provinces),
    Step("states", ("provinces",), ALL_LEVELS, "cells", 1, _states),
    Step("owners", ("states",), ALL_LEVELS, "cells", 1, _owners),
    Step("economy", ("owners",), ALL_LEVELS, "cells", 1, _economy),
    Step("names", ("economy",), ALL_LEVELS, "cells", 1, _names),
)
RASTER_STEPS = ("raster", "fix", "ids", "reconcile", "adjacency", "positions", "terrain_px", "rivers_px", "textures")


def steps() -> tuple[Step, ...]:
    return CELL_STEPS


def step_ids() -> tuple[str, ...]:
    return tuple(s.id for s in CELL_STEPS)


def run_cells(world: ForgeWorld, *, from_step: str | None = None, until: str | None = None,
              progress: ProgressFn | None = None, cancelled: CancelCheck = None) -> ForgeWorld:
    """Ejecuta los pasos de celdas desde ``from_step`` (incluido) hasta ``until`` (incluido)."""
    ids = step_ids()
    start = ids.index(from_step) if from_step else 0
    stop = ids.index(until) + 1 if until else len(ids)
    states = dict(world.steps)
    world = world.evolve(entities=dict(world.entities))
    for i, step in enumerate(CELL_STEPS[start:stop], start=start):
        raise_if_cancelled(cancelled)
        if progress:
            progress(step.id, i - start, stop - start)
        t0 = time.perf_counter()
        world = step.run(world, StepContext(rng=rng_for(world.params.seed, step.id), progress=progress,
                                            cancelled=cancelled))
        states[step.id] = StepState("edited" if edit_ops.edits_for(world, step.id) else "computed",
                                    seconds=round(time.perf_counter() - t0, 3))
        world = world.evolve(steps=states)
    for step in CELL_STEPS[stop:]:
        states[step.id] = StepState("pending")
    return world.evolve(steps=states, raster=None)


# --- etapa de ráster ----------------------------------------------------------------------------------------

def run_raster(world: ForgeWorld, *, scale: int, progress: ProgressFn | None = None, cancelled: CancelCheck = None,
               with_textures: bool = True) -> ForgeWorld:
    """Pasos 18–27 a la escala ``scale``: el ráster reconciliado listo para exportar o para la vista previa."""
    p, c, t = world.params, world.cells, world.provisional
    lat = world.lattice
    report: dict = {}
    times: dict = {}

    def tick(name: str, i: int):
        raise_if_cancelled(cancelled)
        if progress:
            progress(name, i, len(RASTER_STEPS))
        times[name] = time.perf_counter()

    tick("raster", 0)
    cell_r, hp = rasterize.raster(lat, c.h, c.land, scale=scale, rng=rng_for(p.seed, "warp"), cancelled=cancelled)
    P0 = t.count
    tick("fix", 1)
    pid0 = (c.province0[cell_r] + 1).astype(np.int64)
    is_sea_p = np.concatenate([[False], t.is_sea])
    pid, merged, flipped, created, is_sea_p2 = reconcile.fix_fragments(pid0, is_sea_p, wrap_x=False)
    parent = reconcile.parents_of_created(pid, pid0, P0, is_sea_p2.size)
    report["fix"] = {"merged": merged, "flipped": flipped, "created": created}
    del pid0
    tick("ids", 2)
    ids, remap, NL, NP = reconcile.compact_ids(pid, is_sea_p2)
    del pid
    is_sea = np.zeros(NP + 1, bool)
    is_sea[NL + 1:] = True
    present = np.flatnonzero(remap > 0)
    par = np.full(NP + 1, -1, np.int64)
    par[remap[present]] = parent[present] - 1
    tick("reconcile", 3)
    areas = np.bincount(ids.ravel(), minlength=NP + 1)
    prov = {"state": t.state, "continent": t.continent, "climate": t.climate, "owner": t.owner,
            "culture": t.culture, "religion": t.religion, "life_rating": t.life_rating, "population": t.population,
            "goods": t.goods}
    attrs, rep = reconcile.reconcile_attributes(par, NL, NP, prov, areas,
                                                t.capitals if t.capitals is not None else np.zeros(0, np.int64))
    vanished = np.setdiff1d(np.arange(P0), par[1:])
    rep["vanished"] = int(vanished.size)
    report["reconcile"] = rep
    names = _final_names(world, par, NL, NP)
    colors = rng_for(p.seed, "colors").choice(2 ** 24 - 2, size=NP, replace=False) + 1
    colors = np.concatenate([[0], colors]).astype(np.int64)
    return finish_raster(world, ids=ids, is_sea=is_sea, NL=NL, par=par, attrs=attrs, names=names, colors=colors,
                         cell_r=cell_r, hp=hp, scale=scale, report=report, tick=tick, times=times,
                         cancelled=cancelled, with_textures=with_textures)


def finish_raster(world: ForgeWorld, *, ids, is_sea, NL, par, attrs, names, colors, cell_r, hp, scale, report,
                  tick, times, cancelled=None, with_textures=True, pcat=None, terrain=None, rivers=None,
                  positions=None) -> ForgeWorld:
    """Pasos 22–27 sobre un ráster con ids ya compactados (generado o importado): vecinos, estrechos, posiciones,
    terreno, ríos y texturas. ``pcat``/``terrain``/``rivers``/``positions`` importados sustituyen a los suyos."""
    p, c, lat = world.params, world.cells, world.lattice
    tick("adjacency", 4)
    from ..map.adjacency import suggest_straits
    from ..map.positions import generate

    pe = reconcile.raster_edges(ids.astype(np.int32), True)
    pe = pe[pe[:, 0] > 0]
    straits = suggest_straits(ids, is_sea, pe, max_gap=max(2, p.strait_max_gap_px // scale))
    tick("positions", 5)
    pos = positions if positions is not None else generate(
        ids, is_sea, secondary={k: max(1, v // scale) if scale > 1 else v for k, v in p.secondary_point_px.items()})
    tick("terrain_px", 6)
    pix_land = ~is_sea[ids]
    if pcat is None:
        pcat = rasterize.pixel_categories(cell_r, c.category, hp, pix_land, hills=p.hills_height,
                                          mountain=p.mountain_height)
        pcat = edit_ops.apply_pixel_terrain(world, pcat, ids)
    if terrain is None:
        state_of_id = np.where(attrs["state"] >= 0, attrs["state"], -1)
        terrain = rasterize.terrain_pixels(pcat, ids, state_of_id, world.install.idx_by_cat,
                                           rng_for(p.seed, "tindex"), pix_land)
    tick("rivers_px", 7)
    if rivers is None:
        rivers, rstats = rasterize.river_pixels(lat, ~pix_land, c.river, c.recv, c.flux, c.land, scale=scale,
                                                widths=list(world.install.widths),
                                                width_share=list(world.install.width_share), cancelled=cancelled)
    else:
        rstats = {"imported": True}
    report["rivers"] = rstats
    if scale > 1:
        report["cell_r"] = cell_r          # la vista previa pinta las capas por celda (temperatura, lluvia…)
    tex = None
    if with_textures:
        tick("textures", 8)
        owner_px = attrs["owner"][ids] if attrs.get("owner") is not None else None
        tex = textures.build(pcat, hp, world.install.cm_pal, world.install.water_mean, rng_for(p.seed, "grain"),
                             owner_px=owner_px)
    t_end = time.perf_counter()
    keys = list(times)
    report["seconds"] = {k: round((times[keys[i + 1]] if i + 1 < len(keys) else t_end) - times[k], 3)
                         for i, k in enumerate(keys)}
    r = ForgeRaster(ids=ids, parent=par, is_sea=is_sea, scale=scale, land_count=NL, pix_cat=pcat, h_px=hp,
                    terrain=terrain, rivers=rivers, edges=pe, positions=pos, straits=straits, state=attrs["state"],
                    continent=attrs["continent"], climate=attrs["climate"], owner=attrs["owner"],
                    culture=attrs["culture"], religion=attrs["religion"], goods=attrs["goods"],
                    life_rating=attrs["life_rating"], population=attrs["population"], capitals=attrs["capitals"],
                    names=names, colors=colors, report=report)
    if tex is not None:
        r.report["textures"] = tex
    return world.evolve(raster=r)


def _final_names(world: ForgeWorld, par: np.ndarray, nl: int, n: int) -> list:
    """Nombre por id final: el de su madre provisional; las hijas de ``fix`` reciben uno propio."""
    base = world.entities.get("province_names") or []
    gen = MarkovNames(int(world.entities.get("names_seed", 0)) + 1, world.params.name_source,
                      world.params.custom_names)
    for nm in base:
        gen.used.setdefault("province", set()).add(nm)
    out: list = [None] * (n + 1)
    seen: set[int] = set()
    for i in range(1, n + 1):
        pp = int(par[i])
        if 0 <= pp < len(base) and pp not in seen:
            out[i] = base[pp]
            seen.add(pp)
        else:
            out[i] = gen.name("province")
    return out


def run_all(params: ForgeParams, install: InstallProfile | None = None, *, scale: int = 1,
            progress: ProgressFn | None = None, cancelled: CancelCheck = None,
            with_textures: bool = True) -> ForgeWorld:
    """Atajo: rejilla, etapa de celdas y etapa de ráster («Generación rápida»)."""
    world = new_world(params, install)
    world = run_cells(world, progress=progress, cancelled=cancelled)
    return run_raster(world, scale=scale, progress=progress, cancelled=cancelled, with_textures=with_textures)


def with_params(world: ForgeWorld, params: ForgeParams) -> ForgeWorld:
    """El mismo mundo con otros parámetros (la rejilla no cambia: se fijó en la pantalla 1)."""
    return replace(world, params=params)


__all__ = ["Step", "StepContext", "new_world", "run_cells", "run_raster", "run_all", "steps", "step_ids",
           "rng_for", "with_params", "RASTER_STEPS", "Owners"]
