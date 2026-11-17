"""Exportación de «Solo mapa» (wizard §18.8): los archivos en orden, en una sola transacción con diario.

``render_files`` es puro (cabe en el proceso trabajador): del ``ForgeWorld`` con su ráster final y de unas
``ExportInputs`` leídas del proyecto saca los bytes de cada archivo. ``gather_inputs`` lee esas entradas (historias
de país, rutas ``oob``, bookmarks, archivos del mod que van a la papelera). ``export_plan`` da la tabla archivo ·
acción · clase · tamaño sin tocar nada; ``export`` lo aplica todo dentro de una transacción (un Ctrl+Z deshace la
exportación entera y el guardado la escribe con el diario).

Acciones: G generar, M modificar (copia desde el juego si hace falta), T mover a la papelera, E archivo vacío.
Clases (R1 §4): A el juego no carga sin él, B no se puede jugar, C calidad.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from ..map.bmp import new_bmp
from ..map.positions import generated_text
from . import nations
from .economy import presence
from .names import ascii_name, cp1252_text, key_name
from .params import Level
from .world import CLIMATES, ForgeWorld

CRLF = "\r\n"
GENERATED = "# Generado por Victoria II Mod Studio (Taller de mapas)"
REPLACED_FOLDERS = ("history/provinces", "history/pops", "history/units", "history/wars", "history/diplomacy")
ADJ_HEADER = "#From;To;Type;Through;Data;Comment"
DEF_HEADER = "province;red;green;blue;x;x"
UNDO_EXPORT = "undo.mapforge_export"

ACTION_GENERATE, ACTION_MODIFY, ACTION_TRASH, ACTION_EMPTY = "G", "M", "T", "E"


@dataclass
class ExportInputs:
    """Lo que la exportación lee del proyecto (en el proceso de la interfaz; cruza al trabajador con pickle)."""

    prefix: str = "MOD"
    country_histories: dict = field(default_factory=dict)     # rel → bytes de las historias de país efectivas
    oob_paths: list = field(default_factory=list)             # history/units/... citadas que existen
    bookmarks: bytes | None = None
    region_sea_cites: bool = False
    mod_trash: list = field(default_factory=list)             # archivos del propio mod bajo carpetas reemplazadas
    replace_paths: list = field(default_factory=list)
    has_descriptor: bool = False
    taken_tags: list = field(default_factory=list)            # TAG registrados en el proyecto («Mundo» no los pisa)


@dataclass(frozen=True)
class PlannedFile:
    rel: str
    action: str
    cls: str
    size: int


def _enc(text: str) -> bytes:
    """En cp1252, el juego. Lo que no cabe se translitera ('Ő' → 'O') en vez de quedar como '?'."""
    return cp1252_text_lines(text).encode("cp1252", errors="replace")


def cp1252_text_lines(text: str) -> str:
    """``cp1252_text`` línea a línea (conserva los saltos y las tabulaciones); lo que ya cabe no se toca."""
    try:
        text.encode("cp1252")
        return text
    except UnicodeEncodeError:
        return "".join(part if part in ("\r", "\n", "\t") or not part else _fold_part(part)
                       for part in re.split(r"([\r\n\t])", text))


def _fold_part(part: str) -> str:
    """Un trozo sin saltos: lo que cabe se deja igual (con sus espacios) y solo se pliegan los caracteres que no."""
    out = []
    for ch in part:
        try:
            ch.encode("cp1252")
            out.append(ch)
        except UnicodeEncodeError:
            out.append(cp1252_text(ch) or ("" if not ch.isspace() else " "))
    return "".join(out)


def _loc(name: str) -> str:
    """Un nombre para una celda de la localización: en cp1252 y sin ';' ni saltos, que partirían la fila."""
    return cp1252_text(str(name)).replace(";", ",")


def _lines(lines: list[str]) -> bytes:
    return _enc(CRLF.join(lines) + CRLF)


# --- archivos del mapa ----------------------------------------------------------------------------------

def _rgb_lut(colors: np.ndarray) -> np.ndarray:
    lut = np.zeros((colors.size, 3), np.uint8)
    lut[:, 0] = colors >> 16
    lut[:, 1] = (colors >> 8) & 255
    lut[:, 2] = colors & 255
    return lut


def _palette(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, np.uint8).reshape(256, 3)


def definition_csv(world: ForgeWorld) -> bytes:
    r = world.raster
    c = r.colors
    rows = [DEF_HEADER]
    for i in range(1, r.count + 1):
        v = int(c[i])
        rows.append(f"{i};{v >> 16};{(v >> 8) & 255};{v & 255};{ascii_name(r.names[i])};x")
    return _lines(rows)


def default_map(world: ForgeWorld) -> bytes:
    r = world.raster
    n = r.count
    seas = list(range(r.land_count + 1, n + 1))
    sea_block = "sea_starts = {" + CRLF + "".join(
        "\t" + " ".join(map(str, seas[i:i + 20])) + CRLF for i in range(0, len(seas), 20)) + "}"
    base = world.install.default_map if world.install else ""
    if not base.strip():
        base = CRLF.join([
            "max_provinces = 0", "sea_starts = {", "}", 'definitions = "definition.csv"',
            'provinces = "provinces.bmp"', 'positions = "positions.txt"', 'terrain = "terrain.bmp"',
            'rivers = "rivers.bmp"', 'terrain_definition = "terrain.txt"', 'tree_definition = "trees.txt"',
            'continent = "continent.txt"', 'adjacencies = "adjacencies.csv"', 'region = "region.txt"',
            'region_sea = "region_sea.txt"', 'province_flag_sprite = "province_flag_sprites"',
            "border_heights = {", "\t500", "\t800", "\t1100", "}", "terrain_sheet_heights = {", "\t500", "}",
            "tree = 1100", "border_cutoff = 1100.0", ""])
    text = re.sub(r"max_provinces\s*=\s*\d+", f"max_provinces = {n + 1}", base, count=1)
    text = re.sub(r"sea_starts\s*=\s*\{[^}]*\}", lambda _m: sea_block, text, count=1)
    if "sea_starts" not in text:
        text = sea_block + CRLF + text
    text = text.replace("\r\n", "\n").replace("\n", CRLF)
    return _enc(text if text.endswith(CRLF) else text + CRLF)


def adjacencies_csv(world: ForgeWorld) -> bytes:
    r = world.raster
    rows = [ADJ_HEADER]
    for a, b, through, _gap in (r.straits.tolist() if r.straits is not None else []):
        rows.append(f"{a};{b};sea;{through};0;{ascii_name(r.names[a])}-{ascii_name(r.names[b])}")
    return _lines(rows)


def state_key(prefix: str, s: int) -> str:
    return f"{prefix}_STATE_{s + 1}"


def region_txt(world: ForgeWorld, prefix: str) -> bytes:
    r = world.raster
    rows = [GENERATED]
    land = np.arange(1, r.land_count + 1)
    st = r.state[1:r.land_count + 1]
    for s in np.unique(st[st >= 0]).tolist():
        mem = land[st == s].tolist()
        rows.append(f"{state_key(prefix, s)} = {{ " + " ".join(map(str, mem)) + " }")
    return _lines(rows)


def _top_blocks(text: str) -> list[tuple[str, str]]:
    """``(nombre, interior)`` de cada bloque de primer nivel (con llaves equilibradas)."""
    out = []
    i = 0
    text = re.sub(r"#[^\r\n]*", "", text)
    pat = re.compile(r"([A-Za-z0-9_.\-]+)\s*=\s*\{")
    while True:
        m = pat.search(text, i)
        if not m:
            break
        depth = 1
        j = m.end()
        while j < len(text) and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        out.append((m.group(1), text[m.end():j - 1]))
        i = j
    return out


def continent_txt(world: ForgeWorld) -> bytes:
    r = world.raster
    names = world.entities.get("continent_names") or []
    source = ""
    if world.install is not None:
        source = getattr(world.install, "continent_text", "") or ""
    blocks = dict(_top_blocks(source))
    rows = [GENERATED]
    land = np.arange(1, r.land_count + 1)
    cont = r.continent[1:r.land_count + 1]
    for k, name in enumerate(names):
        mem = land[cont == k].tolist()
        if not mem:
            continue
        inner = re.sub(r"provinces\s*=\s*\{[^}]*\}", "", blocks.get(name, "")).strip()
        rows.append(f"{name} = {{")
        rows.append("\tprovinces = {")
        for i in range(0, len(mem), 20):
            rows.append("\t\t" + " ".join(map(str, mem[i:i + 20])))
        rows.append("\t}")
        for line in inner.splitlines():
            if line.strip():
                rows.append("\t" + line.strip())
        rows.append("}")
    return _lines(rows)


def climate_txt(world: ForgeWorld) -> bytes:
    """Por cada clima con provincias: su bloque de modificadores de la instalación y su lista (H7). Un clima sin
    provincias no se escribe (``check_map`` pide exactamente una lista y un bloque por clima)."""
    r = world.raster
    names = world.entities.get("climate_names") or [f"{c}_climate" for c in CLIMATES]
    blocks = dict(_top_blocks(world.install.climate_blocks if world.install else ""))
    land = np.arange(1, r.land_count + 1)
    clim = r.climate[1:r.land_count + 1]
    members: dict[str, list[int]] = {}
    for k, name in enumerate(names):
        members.setdefault(name, []).extend(land[clim == k].tolist())
    rows = [GENERATED]
    for name, mem in members.items():
        if not mem:
            continue
        rows.append(f"{name} = {{")
        for line in blocks.get(name, "").strip().splitlines():
            if line.strip():
                rows.append("\t" + line.strip())
        rows.append("}")
        rows.append(f"{name} = {{ " + " ".join(map(str, sorted(mem))) + " }")
    return _lines(rows)


def localisation(world: ForgeWorld, prefix: str) -> bytes:
    r = world.raster
    rows = []
    for i in range(1, r.count + 1):
        n = _loc(r.names[i])
        rows.append(f"PROV{i};{n};{n};{n};;{n};;;;;;;;;x")
    sn = world.entities.get("state_names") or []
    st = r.state[1:r.land_count + 1]
    for s in np.unique(st[st >= 0]).tolist():
        n = _loc(sn[s]) if s < len(sn) else ""
        n = n or state_key(prefix, s)
        rows.append(f"{state_key(prefix, s)};{n};{n};{n};;{n};;;;;;;;;x")
    return _lines(rows)


def province_histories(world: ForgeWorld) -> dict[str, bytes]:
    r = world.raster
    owners = world.entities.get("owners") or []
    conts = world.entities.get("continent_names") or []
    out = {}
    for p in range(1, r.land_count + 1):
        lines = [GENERATED]
        o = int(r.owner[p]) if r.owner is not None else -1
        if 0 <= o < len(owners):
            tag = owners[o]
            lines += [f"owner = {tag}", f"controller = {tag}", f"add_core = {tag}"]
        if r.goods and r.goods[p]:
            lines.append(f"trade_goods = {r.goods[p]}")
        lines.append(f"life_rating = {int(r.life_rating[p])}")
        k = int(r.continent[p])
        folder = key_name(conts[k]) if 0 <= k < len(conts) else "studio"
        out[f"history/provinces/{folder}/{p} - {ascii_name(r.names[p])}.txt"] = _lines(lines)
    return out


def pops(world: ForgeWorld, prefix: str) -> tuple[dict[str, bytes], dict]:
    r = world.raster
    civ = world.entities.get("civilized") or []
    cultures = world.entities.get("cultures") or ["default_culture"]
    religions = world.entities.get("religions") or ["default_religion"]
    caps = {c for k, c in enumerate(r.capitals or []) if c > 0 and k < len(civ) and civ[k]}
    dates = list(world.install.pop_dates if world.install and world.install.pop_dates else ["1836.1.1"])
    out = {}
    stats = {"urban_in_unowned": 0, "provinces_with_craftsmen": 0, "total": 0}
    for di, date in enumerate(dates):
        factor = 1.0 + 0.12 * di
        blocks = [GENERATED]
        for p in range(1, r.land_count + 1):
            owned = int(r.owner[p]) >= 0 if r.owner is not None else False
            mix = presence(r.goods[p] if r.goods else None, owned, p in caps)
            c = cultures[max(0, int(r.culture[p]))] if r.culture is not None and r.culture[p] >= 0 else cultures[0]
            rel = religions[max(0, int(r.religion[p]))] if r.religion is not None and r.religion[p] >= 0 \
                else religions[0]
            size = int(r.population[p] * factor) if r.population is not None else 1000
            if di == 0:
                stats["total"] += size
                if not owned and any(k in mix for k in ("craftsmen", "clerks", "capitalists", "bureaucrats",
                                                        "officers")):
                    stats["urban_in_unowned"] += 1
                if "craftsmen" in mix:
                    stats["provinces_with_craftsmen"] += 1
            blocks.append(f"{p} = {{")
            for k, v in mix.items():
                blocks.append(f"\t{k} = {{ culture = {c} religion = {rel} size = {max(1, int(size * v))} }}")
            blocks.append("}")
        out[f"history/pops/{date}/00_{prefix}_mapforge.txt"] = _lines(blocks)
    return out, stats


def _set_capital(data: bytes, cap: int) -> bytes:
    text = data.decode("cp1252", errors="replace")
    new, n = re.subn(r"(?m)^(\s*capital\s*=\s*)\d+", lambda m: f"{m.group(1)}{cap}", text, count=1)
    if not n:
        nl = "\r\n" if "\r\n" in text else "\n"
        new = f"capital = {cap}{nl}" + text
    return new.encode("cp1252", errors="replace")


def country_capitals(world: ForgeWorld, inputs: ExportInputs) -> dict[str, bytes]:
    """``capital`` de los TAG con tierra y de los TAG sin tierra cuya capital ya no es tierra (solo esa clave)."""
    r = world.raster
    owners = world.entities.get("owners") or []
    cap_of = {tag: int(r.capitals[k]) for k, tag in enumerate(owners) if r.capitals and k < len(r.capitals)
              and r.capitals[k] > 0}
    biggest = None
    if r.owner is not None and owners:
        counts = np.bincount(r.owner[1:r.land_count + 1][r.owner[1:r.land_count + 1] >= 0], minlength=len(owners))
        if counts.size and counts.max() > 0:
            biggest = cap_of.get(owners[int(np.argmax(counts))])
    out = {}
    for rel, data in sorted(inputs.country_histories.items()):
        m = re.match(r"([A-Za-z0-9]{3})", rel.rsplit("/", 1)[-1])
        if not m:
            continue
        tag = m.group(1).upper()
        text = data.decode("cp1252", errors="replace")
        cm = re.search(r"(?m)^\s*capital\s*=\s*(\d+)", text)
        old = int(cm.group(1)) if cm else None
        if tag in cap_of:
            new = cap_of[tag]
        elif old is not None and 1 <= old <= r.land_count:
            continue
        elif biggest is not None:
            new = biggest
        else:
            continue
        if old == new:
            continue
        out[rel] = _set_capital(data, new)
    return out


def bookmarks(world: ForgeWorld, inputs: ExportInputs) -> bytes | None:
    if not inputs.bookmarks:
        return None
    r = world.raster
    pos = r.positions
    owners = world.entities.get("owners") or []
    target = None
    if owners and r.capitals:
        counts = np.bincount(r.owner[1:r.land_count + 1][r.owner[1:r.land_count + 1] >= 0], minlength=len(owners))
        if counts.size and counts.max() > 0 and r.capitals[int(np.argmax(counts))] > 0:
            target = r.capitals[int(np.argmax(counts))]
    if target is None and r.land_count:
        target = int(np.argmax(np.bincount(r.ids.ravel(), minlength=r.count + 1)[1:r.land_count + 1])) + 1
    if target is None:
        return None
    x, y = int(pos["ux"][target]), int(pos["uy"][target])
    text = inputs.bookmarks.decode("cp1252", errors="replace")
    text = re.sub(r"(cameraX\s*=\s*)[\d.]+", lambda m: f"{m.group(1)}{x}", text)
    text = re.sub(r"(cameraY\s*=\s*)[\d.]+", lambda m: f"{m.group(1)}{y}", text)
    return text.encode("cp1252", errors="replace")


def render_files(world: ForgeWorld, inputs: ExportInputs) -> tuple[dict[str, bytes], dict]:
    """Todos los archivos generados o modificados (rel → bytes) y un informe con las cifras de la exportación."""
    r = world.raster
    if r is None or r.scale != 1:
        raise ValueError("render_files necesita el ráster final (escala 1)")
    check_level(world)
    world, retagged = nations.retag(world, set(inputs.taken_tags))
    files: dict[str, bytes] = {}
    lut = _rgb_lut(r.colors)
    files["map/provinces.bmp"] = new_bmp(lut[r.ids])
    files["map/definition.csv"] = definition_csv(world)
    files["map/default.map"] = default_map(world)
    files["map/terrain.bmp"] = new_bmp(r.terrain, _palette(world.install.terrain_palette))
    files["map/rivers.bmp"] = new_bmp(r.rivers, _palette(world.install.rivers_palette))
    kept = r.positions.get("__text__") if isinstance(r.positions, dict) else None
    files["map/positions.txt"] = kept if kept is not None else generated_text(r.positions, r.land_count,
                                                                              header=GENERATED)
    files["map/adjacencies.csv"] = adjacencies_csv(world)
    files["map/region.txt"] = region_txt(world, inputs.prefix)
    files["map/continent.txt"] = continent_txt(world)
    files["map/climate.txt"] = climate_txt(world)
    if inputs.region_sea_cites:
        files["map/region_sea.txt"] = _lines([GENERATED])
    tex = r.report.get("textures") or {}
    files.update(tex)
    files.update(province_histories(world))
    pop_files, pop_stats = pops(world, inputs.prefix)
    files.update(pop_files)
    for rel in inputs.oob_paths:
        files[rel] = b""
    files.update(country_capitals(world, inputs))
    bm = bookmarks(world, inputs)
    if bm is not None:
        files["common/bookmarks.txt"] = bm
    files[f"localisation/00_{inputs.prefix}_map.csv"] = localisation(world, inputs.prefix)
    # Una carpeta que el descriptor reemplaza no puede quedar vacía (``replace_path_empty``): las guerras y la
    # diplomacia del juego citan provincias y TAG del mapa viejo, así que se sustituyen por un archivo sin nada.
    for folder in REPLACED_FOLDERS:
        if not any(rel.startswith(folder + "/") for rel in files):
            files[f"{folder}/00_{inputs.prefix}_mapforge.txt"] = _lines([GENERATED])
    owned = int((r.owner[1:r.land_count + 1] >= 0).sum()) if r.owner is not None else 0
    report = {"pops": pop_stats, "owned_provinces": owned, "files": len(files),
              "bytes": sum(len(b) for b in files.values()), "retagged": retagged,
              "new_countries": len(((world.entities or {}).get("world") or {}).get("countries") or [])}
    return files, report


# --- entradas, plan y aplicación --------------------------------------------------------------------------

def gather_inputs(project, world: ForgeWorld, index=None) -> ExportInputs:
    """Lee del proyecto lo que la exportación necesita (lecturas de la VFS; no escribe nada). ``index`` (el de la
    sesión) da los TAG registrados para «Mundo»; sin él se usa ``project.index`` si lo hay."""
    from ..vfs.model import LayerKind

    vfs = project.vfs
    inputs = ExportInputs(prefix=project.settings.prefix or "MOD")
    oob: set[str] = set()
    for entry in vfs.list("history/countries", "*.txt", recursive=False):
        data = vfs.read_bytes(entry)
        inputs.country_histories[str(entry.rel)] = data
        for m in re.finditer(r'(?m)^\s*oob\s*=\s*"?([^"\r\n]+?)"?\s*$', data.decode("cp1252", errors="replace")):
            rel = f"history/units/{m.group(1).strip()}"
            if vfs.resolve(rel) is not None:
                oob.add(str(vfs.resolve(rel).rel))
    inputs.oob_paths = sorted(oob)
    bm = vfs.resolve("common/bookmarks.txt")
    inputs.bookmarks = vfs.read_bytes(bm) if bm is not None else None
    rs = vfs.resolve("map/region_sea.txt")
    if rs is not None:
        inputs.region_sea_cites = bool(re.search(rb"\d", re.sub(rb"#[^\r\n]*", b"", vfs.read_bytes(rs))))
    trash = []
    for folder in (*REPLACED_FOLDERS, "map/cache"):
        for entry in vfs.list(folder, "*", recursive=True):
            if entry.layer.kind is LayerKind.MOD:
                trash.append(str(entry.rel))
    inputs.mod_trash = sorted(set(trash))
    desc = getattr(project, "descriptor", None)
    inputs.has_descriptor = desc is not None
    inputs.replace_paths = list(desc.replace_paths) if desc is not None else []
    if world.params.level is Level.WORLD:
        from ..domain.tags import taken_tags

        index = index if index is not None else getattr(project, "index", None)
        inputs.taken_tags = sorted(taken_tags(index)) if index is not None else []
    return inputs


CLASS_OF = (("map/provinces.bmp", "A"), ("map/definition.csv", "A"), ("map/default.map", "A"),
            ("map/terrain.bmp", "A"), ("map/rivers.bmp", "B"), ("map/positions.txt", "B"),
            ("map/adjacencies.csv", "A"), ("map/region", "B"), ("map/continent.txt", "B"),
            ("map/climate.txt", "B"), ("map/terrain/", "C"), ("history/provinces/", "B"), ("history/pops/", "B"),
            ("history/units/", "A"), ("history/countries/", "A"), ("common/bookmarks.txt", "C"),
            ("gfx/interface/minimap.dds", "C"), ("localisation/", "C"))


def class_of(rel: str) -> str:
    for prefix, cls in CLASS_OF:
        if rel.startswith(prefix):
            return cls
    return "C"


def export_plan(files: dict[str, bytes], inputs: ExportInputs, exists, world: ForgeWorld | None = None) \
        -> list[PlannedFile]:
    """Archivo · acción · clase · tamaño. ``exists(rel)`` dice si la ruta ya existe en la vista efectiva. Con un
    ``world`` de «Mundo», también los archivos de los países y las culturas nuevas (tamaño 0: se escriben al
    aplicar)."""
    plan = [PlannedFile(rel, ACTION_TRASH, "A", 0) for rel in inputs.mod_trash if rel not in files]
    for rel in sorted(files):
        data = files[rel]
        if rel in inputs.oob_paths:
            action = ACTION_EMPTY
        elif exists(rel) and (rel.startswith("history/countries/") or rel == "common/bookmarks.txt"):
            action = ACTION_MODIFY
        else:
            action = ACTION_GENERATE
        plan.append(PlannedFile(rel, action, class_of(rel), len(data)))
    if inputs.has_descriptor:
        missing = [f for f in REPLACED_FOLDERS if f not in {p.strip("/").replace("\\", "/") for p in
                                                             inputs.replace_paths}]
        if missing:
            plan.append(PlannedFile("@descriptor.mod", ACTION_MODIFY, "A", 0))
    if world is not None and world.params.level is Level.WORLD:
        retagged, _ = nations.retag(world, set(inputs.taken_tags))
        for rel, action in nations.world_plan_rows(retagged, exists):
            if rel not in files:
                plan.append(PlannedFile(rel, ACTION_MODIFY if action == "M" else ACTION_GENERATE, "C", 0))
    return plan


def apply_export(project, files: dict[str, bytes], inputs: ExportInputs, *, extra: dict[str, bytes] | None = None,
                 label: str = UNDO_EXPORT, transaction=None, world: ForgeWorld | None = None,
                 domain=None) -> list[str]:
    """Aplica la exportación en **una** transacción: papelera, archivos, ``replace_path``, los del proyecto del
    taller (``extra``) y, con un ``world`` de «Mundo», los países y las culturas nuevas (``nations.apply_world``).
    ``domain`` es el ``DomainContext`` de quien llama (índice, textos, entidades); sin él se usa ``project``.
    Devuelve las rutas tocadas. Si algo falla, la transacción se revierte entera.
    ``transaction(label, **fmt)`` es la de quien llama (la sesión de la interfaz); por defecto, la del ``Workspace``."""
    from ..project.binary import put_bytes

    ws = project.ws
    touched: list[str] = []
    with (transaction or ws.transaction)(label, files=len(files)) as txn:
        doomed = [rel for rel in inputs.mod_trash if rel not in files]
        if doomed:
            ws.delete_many(doomed)
        for rel in sorted(files):
            put_bytes(ws, rel, files[rel])
        for rel, data in sorted((extra or {}).items()):
            put_bytes(ws, rel, data)
        if inputs.has_descriptor:
            _add_replace_paths(project)
        if world is not None and world.params.level is Level.WORLD:
            retagged, _ = nations.retag(world, set(inputs.taken_tags))
            nations.apply_world(domain if domain is not None else project, retagged)
        touched = [str(r) for r in txn.touched()]
    return touched


def _add_replace_paths(project) -> None:
    from ..modfile import DescriptorSpec, apply_descriptor
    from ..vfs.paths import DESCRIPTOR_REL

    desc = project.descriptor
    if desc is None:
        return
    have = {p.strip("/").replace("\\", "/") for p in desc.replace_paths}
    want = tuple(desc.replace_paths) + tuple(f for f in REPLACED_FOLDERS if f not in have)
    if len(want) == len(desc.replace_paths):
        return
    spec = DescriptorSpec.from_descriptor(desc)
    spec = DescriptorSpec(spec.name, spec.folder, spec.user_dir, want, spec.dependencies)
    ws = project.ws
    handle = ws.open(DESCRIPTOR_REL)
    ws.touch(handle)
    apply_descriptor(handle.model.document, spec)


def check_level(world: ForgeWorld) -> None:
    """«Solo mapa» y «Mundo» se exportan; «Sobre vanilla» no está hecho (ver el informe de la iteración 9b)."""
    if world.params.level is Level.OVERLAY:
        raise NotImplementedError("el nivel «Sobre vanilla» no se exporta todavía")
