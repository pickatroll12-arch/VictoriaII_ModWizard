"""Países, culturas y grupos culturales nuevos del nivel «Mundo» (wizard §18.1 y §18.3, pasos 12–17; iteración 9b).

Dos mitades:

- ``name_world`` (en el paso de nombres, sin proyecto): da a los ``k`` países de ``society.owners_for_world`` un
  nombre, un adjetivo, un TAG libre (``domain.tags.suggest_tags`` contra los TAG de la instalación), un color y
  sus banderas; a cada país una cultura con ≥ 50 nombres y apellidos, y a cada zona un grupo cultural. Sustituye
  los marcadores ``__i`` de ``entities["owners"]``/``["cultures"]`` por los TAG y las claves de cultura, así que
  las historias de provincia y las POPs de ``export`` ya salen con ellos.
- ``apply_world`` (en la transacción de la exportación): crea cada país con la receta de la iteración 6
  (``domain.country.build_new_country``: ``countries.txt`` antes de ``dynamic_tags``, archivo de país con sus
  partidos, historia, banderas y textos) y añade los grupos culturales al final de ``common/cultures.txt``, con sus
  textos en ``localisation/00_<P>_forge_world.csv``.

Gobierno, partidos, tecnologías y escuela salen de un país modelo de la instalación (el TAG con más provincias,
civilizado o no según el país): el partido gobernante es el del modelo si su ideología está entre las que admite
el gobierno (H12) o, si no, el primero que lo esté.
"""

from __future__ import annotations

import random
from dataclasses import replace

import numpy as np

from ..domain.tags import check_tag, suggest_tags
from .names import MarkovNames, ascii_name, cp1252_name, key_name

N_NAMES = 60                       # nombres y apellidos por cultura (el criterio pide ≥ 50)
WORLD_LOC_AREA = "forge_world"
CULTURES_REL = "common/cultures.txt"
GRAPHICAL_CULTURES = ("EuropeanGC", "AsianGC", "AfricanGC", "MiddleEasternGC", "SouthAmericanGC")
LEADERS = ("european", "asian", "african", "middle_eastern", "south_american")


def _palette(n: int, seed: int) -> list[tuple[int, int, int]]:
    """``n`` colores de país distintos (ángulo áureo en HSV con saturación y brillo alternos)."""
    import colorsys

    out = []
    h = (seed % 997) / 997.0
    for i in range(n):
        h = (h + 0.618033988749895) % 1.0
        s = 0.45 + 0.35 * ((i * 7) % 5) / 4
        v = 0.55 + 0.35 * ((i * 3) % 4) / 3
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        out.append((int(r * 255), int(g * 255), int(b * 255)))
    return out


def _unique_color(color, used: set) -> tuple[int, int, int]:
    r, g, b = color
    while (r, g, b) in used or (r, g, b) in ((0, 0, 0), (255, 255, 255)):
        r = (r + 7) % 256
    used.add((r, g, b))
    return r, g, b


def assign_tags(names: list[str], taken) -> list[str]:
    """Un TAG libre por nombre, sin repetirse entre ellos ni con ``taken`` (colección o función)."""
    used: set[str] = set()

    def is_taken(tag: str) -> bool:
        if tag in used:
            return True
        return taken(tag) if callable(taken) else tag in taken

    tags = []
    for name in names:
        options = suggest_tags(name, is_taken, count=1) or suggest_tags("X" + name, is_taken, count=1)
        tag = options[0]
        used.add(tag)
        tags.append(tag)
    return tags


def name_world(world, seed: int):
    """Nombres, TAG, colores, culturas y grupos del mundo (ver el docstring del módulo). Sin cambios si el mundo no
    tiene países de «Mundo» (marcadores ``__i``)."""
    ent = dict(world.entities)
    owners = list(ent.get("owners") or [])
    if not owners or not str(owners[0]).startswith("__"):
        return world
    p = world.params
    gen = MarkovNames(seed, p.name_source, p.custom_names)
    rnd = random.Random(seed)
    n = len(owners)
    groups = int(ent.get("groups") or 1)
    zone = list(ent.get("culture_group") or [0] * n)
    country_names = [gen.name("country") for _ in range(n)]
    taken = {t.tag for t in (world.install.tags if world.install else [])}
    tags = assign_tags(country_names, taken)
    used_colors: set = set()
    colors = [_unique_color(c, used_colors) for c in _palette(n, seed)]
    group_names = [gen.name("culture_group") for _ in range(groups)]
    group_keys = _unique_keys([f"{key_name(g)}_group" for g in group_names])
    culture_names = [gen.name("culture") for _ in range(n)]
    culture_keys = _unique_keys([key_name(c) for c in culture_names], reserved=set(group_keys))
    first = MarkovNames(seed + 1, p.name_source, p.custom_names)
    last = MarkovNames(seed + 2, p.name_source, p.custom_names)
    cultures = []
    for i in range(n):
        cultures.append({"key": culture_keys[i], "name": culture_names[i], "group": zone[i],
                         "color": colors[i],
                         "first_names": [first.name(f"first_{i}") for _ in range(N_NAMES)],
                         "last_names": [last.name(f"last_{i}") for _ in range(N_NAMES)]})
    civ = list(ent.get("civilized") or [True] * n)
    countries = []
    for i in range(n):
        name = country_names[i]
        countries.append({"tag": tags[i], "name": name, "adjective": _adjective(name), "color": colors[i],
                          "culture": culture_keys[i], "civilized": bool(civ[i]),
                          "graphical_culture": GRAPHICAL_CULTURES[zone[i] % len(GRAPHICAL_CULTURES)],
                          "flag_seed": rnd.randrange(2 ** 31)})
    ent["owners"] = tags
    ent["cultures"] = culture_keys
    ent["world"] = {"countries": countries, "cultures": cultures,
                    "groups": [{"key": group_keys[g], "name": group_names[g],
                                "leader": LEADERS[g % len(LEADERS)],
                                "unit": GRAPHICAL_CULTURES[g % len(GRAPHICAL_CULTURES)]} for g in range(groups)]}
    return world.evolve(entities=ent)


def _adjective(name: str) -> str:
    base = name.rstrip("aeiouy") or name
    return base + ("ian" if not base.endswith("i") else "an")


def _unique_keys(keys: list[str], reserved: set | None = None) -> list[str]:
    seen = set(reserved or ())
    out = []
    for k in keys:
        k = "forge_" + (k or "x") if not k[:1].isalpha() else k
        cand, i = k, 2
        while cand in seen:
            cand, i = f"{k}_{i}", i + 1
        seen.add(cand)
        out.append(cand)
    return out


def retag(world, taken) -> tuple[object, dict[str, str]]:
    """Cambia los TAG del mundo que ya estén ocupados en el proyecto (``taken``: colección o función); devuelve el
    mundo y ``{viejo: nuevo}``. Los TAG se eligieron contra la instalación del momento de generar; si el mod ha
    registrado otros desde entonces, la exportación no debe pisarlos."""
    data = (world.entities or {}).get("world")
    if not data:
        return world, {}
    is_taken = taken if callable(taken) else (lambda t: t in taken)
    changes: dict[str, str] = {}
    keep = {c["tag"] for c in data["countries"]}
    for c in data["countries"]:
        if not check_tag(c["tag"], is_taken).ok:
            new = assign_tags([c["name"]], lambda t: is_taken(t) or t in keep or t in changes.values())[0]
            changes[c["tag"]] = new
    if not changes:
        return world, {}
    ent = dict(world.entities)
    countries = [dict(c, tag=changes.get(c["tag"], c["tag"])) for c in data["countries"]]
    ent["world"] = dict(data, countries=countries)
    ent["owners"] = [changes.get(t, t) for t in ent.get("owners") or []]
    return world.evolve(entities=ent), changes


# --- exportación ------------------------------------------------------------------------------------------


def fit_graphical_cultures(world, index):
    """Cambia las culturas gráficas del mundo por las que el proyecto define (``graphicalculturetype.gfx``) si la
    elegida al generar no existe: la de la misma posición en la lista ordenada. Sin índice o sin ninguna, igual."""
    from ..index import model as m

    data = (world.entities or {}).get("world")
    known = sorted(index.names(m.KIND_GRAPHICAL_CULTURE)) if index is not None else []
    if not data or not known:
        return world
    folded = {k.casefold(): k for k in known}

    def fit(name: str, i: int) -> str:
        return folded.get(name.casefold()) or known[i % len(known)]

    countries = [dict(c, graphical_culture=fit(c["graphical_culture"], i)) for i, c in enumerate(data["countries"])]
    groups = [dict(g, unit=fit(g["unit"], i)) for i, g in enumerate(data["groups"])]
    ent = dict(world.entities)
    ent["world"] = dict(data, countries=countries, groups=groups)
    return world.evolve(entities=ent)



def _model_profiles(project, world) -> dict[bool, dict]:
    """Perfil de país modelo (``domain.country.country_profile``) civilizado y no civilizado."""
    from ..domain.country import country_profile

    out: dict[bool, dict] = {}
    for info in sorted(world.install.tags if world.install else [], key=lambda t: -t.provinces):
        if info.civilized not in out:
            prof = country_profile(project, info.tag)
            prof["model_tag"] = info.tag
            out[info.civilized] = prof
        if len(out) == 2:
            break
    return out


def _government_and_party(project, tag: str, profile: dict, parties) -> tuple[str | None, str | None]:
    from ..index import model as m

    index = project.index
    governments = list(index.names(m.KIND_GOVERNMENT)) if index is not None else []
    gov = profile.get("government") if profile.get("government") in governments else (governments[0] if governments
                                                                                        else None)
    allowed = None
    if gov is not None:
        sym = index.get(m.KIND_GOVERNMENT, gov)
        allowed = set((sym.attrs.get("ideologies") or ()) if sym is not None else ())
    ruling = None
    for party in parties:
        if not allowed or party.ideology in allowed:
            ruling = party.name
            break
    return gov, ruling


def flag_colors(color) -> tuple[tuple[int, int, int], ...]:
    """Los 3 colores de las banderas (y del uniforme) de un país: el suyo, uno más claro y su complementario."""
    base = np.array(color, np.int64)
    return (tuple(int(x) for x in base), tuple(int(x) for x in np.clip(base + 90, 0, 255)),
            tuple(int(x) for x in 255 - base))


def flag_preview(country: dict, suffix: str = ""):
    """La bandera (``PIL.Image`` de 93×64) de un país del mundo, la misma que escribe la exportación."""
    from ..gfx.flags import procedural_flag

    return procedural_flag(int(country["flag_seed"]), flag_colors(country["color"]), suffix=suffix)


def _party_texts(party) -> dict[str, str]:
    """El nombre visible de un partido nuevo: su ideología con mayúscula, igual en los dos idiomas (como hace
    ``build_new_country`` en inglés)."""
    label = party.ideology.replace("_", " ").capitalize() or party.name
    return {"en": label, "es": label}


def country_specs(project, world) -> list:
    """Un ``NewCountrySpec`` por país del mundo, con sus banderas, su capital y lo copiado del país modelo."""
    from ..domain.country import NewCountrySpec, party_template
    from ..gfx.flags import procedural_flag_set

    data = world.entities["world"]
    r = world.raster
    models = _model_profiles(project, world)
    religions = world.entities.get("religions") or []
    religion_of = {}
    if r is not None and r.owner is not None and r.religion is not None:
        for pid in range(1, r.land_count + 1):
            o = int(r.owner[pid])
            if o >= 0 and o not in religion_of and 0 <= int(r.religion[pid]) < len(religions):
                religion_of[o] = religions[int(r.religion[pid])]
    files = country_file_names(data["countries"], lambda rel: file_exists(project, rel))
    specs = []
    for i, c in enumerate(data["countries"]):
        name = cp1252_name(c["name"], c["tag"])
        adjective = cp1252_name(c["adjective"], name)
        model = models.get(c["civilized"]) or models.get(not c["civilized"]) or {}
        parties = tuple(replace(party, texts=_party_texts(party)) for party in party_template(c["tag"],
                                                                                               project.index))
        gov, ruling = _government_and_party(project, c["tag"], model, parties)
        cap = int(r.capitals[i]) if r is not None and r.capitals is not None and i < len(r.capitals) else None
        colors = flag_colors(c["color"])
        specs.append(NewCountrySpec(
            tag=c["tag"], name={"en": name, "es": name},
            adjective={"en": adjective, "es": adjective},
            file_name=files[i], color=tuple(c["color"]),
            graphical_culture=c["graphical_culture"], flags=procedural_flag_set(int(c["flag_seed"]), colors),
            uniform_colors=colors,
            primary_culture=c["culture"], religion=religion_of.get(i) or (religions[0] if religions else None),
            parties=parties, government=gov, ruling_party=ruling, civilized=bool(c["civilized"]),
            literacy=model.get("literacy", 0.3 if c["civilized"] else 0.05),
            plurality=model.get("plurality", 0.0), nationalvalue=model.get("nationalvalue"),
            technologies=tuple(model.get("technologies") or ()) if c["civilized"] else (),
            capital=cap if cap and cap > 0 else None))
    return specs


def cultures_block(world, newline: str = "\r\n") -> str:
    """Los grupos culturales nuevos con sus culturas, en el formato de ``common/cultures.txt``."""
    data = world.entities["world"]
    lines = ["", "# Grupos culturales del taller de mapas (Victoria II Mod Studio)"]
    for g, group in enumerate(data["groups"]):
        members = [c for c in data["cultures"] if c["group"] == g]
        if not members:
            continue
        lines += [f"{group['key']} = {{", f"\tleader = {group['leader']}", f"\tunit = {group['unit']}",
                  "\tis_overseas = no", ""]
        for c in members:
            r, gr, b = c["color"]
            lines += [f"\t{c['key']} = {{", f"\t\tcolor = {{ {r} {gr} {b} }}", "",
                      "\t\tfirst_names = {", "\t\t\t" + " ".join(_token(n) for n in c["first_names"]), "\t\t}",
                      "\t\tlast_names = {", "\t\t\t" + " ".join(_token(n) for n in c["last_names"]), "\t\t}",
                      "\t}"]
        lines += ["}", ""]
    return newline.join(lines) + newline


def _token(name: str) -> str:
    return f'"{name}"' if (" " in name or "-" in name or "'" in name) else name


def apply_world(project, world) -> None:
    """Crea los países y las culturas de ``world`` dentro de la transacción **abierta** de quien llama."""
    from ..domain.country import build_new_country
    from ..encoding import GAME_ENCODING
    from ..validate.fixes import current

    data = (world.entities or {}).get("world")
    if not data:
        return
    world = fit_graphical_cultures(world, project.index)
    for spec in country_specs(project, world):
        build_new_country(project, spec)
    state = current(project, CULTURES_REL)
    text = state.data.decode(state.encoding or GAME_ENCODING, errors="replace") if state.data else ""
    newline = "\r\n" if "\r\n" in text or not text else "\n"
    text = text + ("" if not text or text.endswith(("\n", "\r")) else newline) + cultures_block(world, newline)
    handle = project.ws.open(CULTURES_REL, create=True)
    project.ws.replace_text(handle, text.encode(state.encoding or GAME_ENCODING, errors="replace"))
    texts = {}
    for g in data["groups"]:
        name = cp1252_name(g["name"], g["key"])
        texts[g["key"]] = {"en": name, "es": name}
    for c in data["cultures"]:
        name = cp1252_name(c["name"], c["key"])
        texts[c["key"]] = {"en": name, "es": name}
    if getattr(project, "loc", None) is not None:
        project.loc.ensure(texts, area=WORLD_LOC_AREA)


def file_exists(project, rel: str) -> bool:
    """Si ``rel`` existe en el proyecto, con lo sin guardar (un documento borrado sin guardar ya no cuenta)."""
    ws = getattr(project, "ws", None)
    handle = ws.peek(rel) if ws is not None else None
    if handle is not None:
        return not handle.deleted
    vfs = getattr(project, "vfs", None)
    return vfs is not None and vfs.resolve(rel) is not None


def country_file_names(countries, exists=None) -> list[str]:
    """El nombre de archivo (sin ``.txt``) de cada país nuevo: su nombre en ASCII, o el TAG si no le queda ninguna
    letra ASCII o si repite el de otro país nuevo o el de un archivo que ya existe (``exists(rel)``). Antes, dos
    nombres que se quedaban en lo mismo (todos los de otra escritura daban «x») hacían fallar la exportación."""
    from ..rules.names import country_file_name

    used: set[str] = set()
    out = []
    for c in countries:
        tag = str(c["tag"])
        base = country_file_name(ascii_name(c["name"]).replace(" ", ""))[:-4]
        candidates = [base, f"{base}_{tag}", tag, f"{tag}_{len(out)}"] if base and base != "x" else \
            [tag, f"{tag}_{len(out)}"]
        for name in candidates:
            if name.lower() in used or (exists is not None and exists(f"common/countries/{name}.txt")):
                continue
            break
        used.add(name.lower())
        out.append(name)
    return out


def world_plan_rows(world, exists=None) -> list[tuple[str, str]]:
    """(ruta, acción) de lo que añade «Mundo» al plan de cambios."""
    data = (world.entities or {}).get("world")
    if not data:
        return []

    rows = [("common/countries.txt", "M"), (CULTURES_REL, "M")]
    for c, base in zip(data["countries"], country_file_names(data["countries"], exists)):
        rows += [(f"common/countries/{base}.txt", "G"), (f"history/countries/{c['tag']} - {base}.txt", "G")]
        rows += [(f"gfx/flags/{c['tag']}{s}.tga", "G") for s in ("", "_communist", "_fascist", "_monarchy",
                                                                   "_republic")]
    return rows


__all__ = ["apply_world", "assign_tags", "country_file_names", "country_specs", "cultures_block", "file_exists",
           "name_world", "retag", "world_plan_rows"]
