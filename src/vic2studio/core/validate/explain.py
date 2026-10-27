"""Explicador de conflicto (wizard §11.1): por qué el juego verá lo que verá.

Reconstruye, con ``VfsSnapshot.stack``, el índice y ``LocalisationDB.definitions``,
qué capas definen lo mismo y en qué orden las carga el juego (archivo del mod que
sustituye al de vanilla, clave de localización que gana por orden de archivos,
``replace_path`` que oculta una carpeta, TAG detrás de ``dynamic_tags``…). Cada paso
lleva la línea real de su capa y su veredicto; la explicación termina en una frase
sobre el efecto en el juego y en los arreglos disponibles. Los heredados también
se explican. Hay una explicación para cada código del catálogo; uno sin
explicador propio da una genérica con la pila de capas del archivo.

Los títulos y las frases son ``explain.title.<código>`` y ``explain.outcome.<código>``
(``explain.title.generic``/``explain.outcome.generic`` si un código no tiene los
suyos), con los ``args`` del problema más los que añada cada explicador. Los pasos
van en el orden en que el juego mira las capas: primero la que gana.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from types import MappingProxyType

from ..encoding import decode_bytes
from ..index import model as m
from ..rules.ids import flag_tag
from ..vfs.model import LayerKind
from ..vfs.paths import VPath
from .context import ValidationContext
from .model import (
    LAYER_DEPENDENCY,
    LAYER_GAME,
    LAYER_MOD,
    LAYER_REPLACE_PATH,
    LAYER_UNSAVED,
    VERDICT_HIDDEN,
    VERDICT_LOSES,
    VERDICT_MISSING,
    VERDICT_NOT_LOADED,
    VERDICT_WINS,
    ExplainStep,
    Explanation,
    Problem,
)

_log = logging.getLogger(__name__)
_LAYERS = {LayerKind.GAME: LAYER_GAME, LayerKind.DEPENDENCY: LAYER_DEPENDENCY, LayerKind.MOD: LAYER_MOD}
MAX_EXCERPT = 160
MAX_STEPS = 12

Explainer = Callable[[Problem, ValidationContext], Explanation]
EXPLAINERS: dict[str, Explainer] = {}


def explainer(*codes: str) -> Callable[[Explainer], Explainer]:
    def register(fn: Explainer) -> Explainer:
        for code in codes:
            EXPLAINERS[code] = fn
        return fn

    return register


def explain(problem: Problem, ctx: ValidationContext) -> Explanation:
    fn = EXPLAINERS.get(problem.code, _generic)
    try:
        return fn(problem, ctx)
    except Exception:  # noqa: BLE001 - explicar nunca falla: si el propio falla, el genérico
        _log.exception("el explicador de %s falló", problem.code)
        return _generic(problem, ctx)


# --- piezas ------------------------------------------------------------------------------------------


def _keys(code: str) -> tuple[str, str]:
    from ..texts import load_texts

    texts = load_texts("en")
    title = f"explain.title.{code}"
    outcome = f"explain.outcome.{code}"
    return (title if title in texts else "explain.title.generic",
            outcome if outcome in texts else "explain.outcome.generic")


def _explanation(problem: Problem, steps: list[ExplainStep], *, max_steps: int = MAX_STEPS,
                 **extra) -> Explanation:
    title, outcome = _keys(problem.code)
    args = {k: v for k, v in problem.args.items() if k != "source"}
    args.setdefault("rel", str(problem.rel) if problem.rel is not None else "")
    args.update(extra)
    return Explanation(title, tuple(steps[:max_steps]), outcome, MappingProxyType(args), tuple(problem.fixes))


def _lines(data: bytes | None) -> list[str]:
    if not data:
        return []
    text = decode_bytes(data).text
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _excerpt(lines: list[str], line: int | None) -> str:
    if line is None or not 1 <= line <= len(lines):
        return ""
    text = lines[line - 1].strip()
    return text if len(text) <= MAX_EXCERPT else text[:MAX_EXCERPT - 1] + "…"


def _find_line(lines: list[str], wanted: str) -> int | None:
    wanted = wanted.strip()
    if not wanted:
        return None
    for number, text in enumerate(lines, start=1):
        if text.strip() == wanted:
            return number
    return None


def layer_steps(ctx: ValidationContext, rel: VPath | None, line: int | None) -> list[ExplainStep]:
    """La pila de capas de ``rel`` (el documento sin guardar primero; luego el mod, las dependencias y el juego),
    cada una con su línea y su veredicto. ``line`` es la del ganador; en las demás capas se busca la misma línea
    de texto y, si no está, se muestra la del mismo número."""
    if rel is None:
        return []
    steps: list[ExplainStep] = []
    winner_text = ""
    if ctx.unsaved(rel):
        data = ctx.read(rel)
        if data is not None:
            winner_text = _excerpt(_lines(data) if line is not None else [], line)
            steps.append(ExplainStep(LAYER_UNSAVED, rel, line, winner_text, VERDICT_WINS))
    stack = ctx.stack(rel)
    winner = None if steps else ctx.entry(rel)
    for entry in stack:
        # Sin línea no hay extracto: no se lee ni se decodifica el archivo (un BMP de 11 MB costaba 0,5 s).
        lines = _lines(ctx.read_entry(entry)) if line is not None else []
        if ctx.hidden(rel) and entry.layer.kind is LayerKind.GAME:
            layer, verdict = LAYER_REPLACE_PATH, VERDICT_HIDDEN
        else:
            layer = _LAYERS[entry.layer.kind]
            verdict = VERDICT_WINS if entry is winner else VERDICT_LOSES
        if entry is winner:
            number = line
            winner_text = _excerpt(lines, line)
        else:
            number = _find_line(lines, winner_text) or line
        steps.append(ExplainStep(layer, entry.rel, number, _excerpt(lines, number), verdict))
    if not steps:
        steps.append(ExplainStep(LAYER_MOD, rel, None, "", VERDICT_MISSING))
    return steps


def _step_at(ctx: ValidationContext, rel: VPath, line: int | None, verdict: str) -> ExplainStep:
    layer = ctx.layer_of(rel)
    name = LAYER_UNSAVED if ctx.unsaved(rel) else _LAYERS.get(layer, LAYER_MOD)
    excerpt = _excerpt(_lines(ctx.read(rel)), line) if line is not None else ""
    return ExplainStep(name, rel, line, excerpt, verdict)


def _generic(problem: Problem, ctx: ValidationContext) -> Explanation:
    return _explanation(problem, layer_steps(ctx, problem.rel, problem.line))


# --- explicadores propios ------------------------------------------------------------------------------

COUNTRIES_REL = VPath.of("common/countries.txt")
PROVINCE_ROLES = ("owner", "controller", "add_core")


@explainer("tag_not_registered")
def _tag_not_registered(problem: Problem, ctx: ValidationContext) -> Explanation:
    """Lo que hay del TAG (historia, archivo de país, banderas, provincias y demás usos) frente a ``countries.txt``."""
    from .rules.countries import TAG_USE_ROLES

    tag = problem.entity[1] if problem.entity else str(problem.args.get("tag", ""))
    index = ctx.index
    steps: list[ExplainStep] = []
    registry = ctx.read(COUNTRIES_REL)
    lines = _lines(registry)
    anchor = next((n for n, text in enumerate(lines, start=1) if text.strip().lower().startswith("dynamic_tags")),
                  len(lines) or None)
    if registry is not None:
        steps.append(_step_at(ctx, COUNTRIES_REL, anchor, VERDICT_MISSING))
    histories = index.lookup(m.KIND_COUNTRY_HISTORY, tag)
    country_files = []
    for history in histories:
        stem = history.rel.name.rsplit(".", 1)[0][3:].strip().lstrip("-").strip()
        if stem:
            country_files.append(VPath.of(f"common/countries/{stem}.txt"))
    for rel in country_files:
        if ctx.layer_of(rel) is not None:
            steps.append(_step_at(ctx, ctx.entry(rel).rel if ctx.entry(rel) else rel, 1, VERDICT_NOT_LOADED))
    for history in histories:
        steps.append(_step_at(ctx, history.rel, 1, VERDICT_NOT_LOADED))
    flags = [s for s in index.symbols(m.KIND_IMAGE) if flag_tag(s.name) == tag]
    for flag in flags:
        steps.append(ExplainStep(_LAYERS.get(flag.layer, LAYER_MOD), flag.rel, None, flag.rel.name,
                                 VERDICT_NOT_LOADED))
    # Las provincias que lo usan (dueño, controlador o núcleo): la primera línea de cada una; después, los demás
    # usos (guerras, diplomacia, ``union``/``primary`` de las culturas), el primero de cada archivo.
    refs = index.refs_to(m.KIND_TAG, tag)
    uses = [r for r in refs if r.role in PROVINCE_ROLES]
    first_use: dict[str, object] = {}
    for ref in uses:
        first_use.setdefault(ref.rel.key, ref)
    for ref in refs:
        if ref.role in TAG_USE_ROLES and ref.role not in PROVINCE_ROLES:
            first_use.setdefault(ref.rel.key, ref)
    provinces = sorted({r.rel.name.split(" ")[0].split("-")[0].strip() for r in uses}, key=_numeric)
    for ref in first_use.values():
        steps.append(_step_at(ctx, ref.rel, ref.line, VERDICT_MISSING))
    return _explanation(problem, steps, max_steps=len(steps), tag=tag, flags=len(flags),
                        provinces=", ".join(provinces), uses=len(uses))


def _numeric(text: str) -> tuple:
    return (0, int(text), "") if text.isdigit() else (1, 0, text)


def _csv_row_at(data: bytes, line: int | None) -> tuple[str, str, list[str]] | None:
    """``(texto, clave, campos)`` de la fila ``line`` de un CSV de localización, partida como ``csvloc.parse_csv``
    (filas por LF, sin el CR final ni el BOM): para no analizar el archivo entero. None si no existe."""
    if line is None or line < 1:
        return None
    pieces = decode_bytes(data).text.split("\n", line)
    if len(pieces) < line:
        return None
    raw = pieces[line - 1]
    if raw.endswith("\r"):
        raw = raw[:-1]
    if line == 1:
        raw = raw.lstrip("\ufeff")
    parts = raw.split(";")
    return raw, parts[0], parts[1:]


def _degraded_example(problem: Problem, mod_data: bytes, game_data: bytes):
    """La fila de ejemplo del problema en el mod y en el juego, ``((línea, raw, campos), …)``: la que nombran sus
    ``args`` (``key`` y ``game_line``, la del problema en el mod) o, si faltan o ya no cuadran, la primera
    degradada (recalculada)."""
    from .rules.localisation import degraded_rows, is_degraded

    key = problem.args.get("key")
    game_line = problem.args.get("game_line")
    if isinstance(key, str) and isinstance(game_line, int):
        mod_row = _csv_row_at(mod_data, problem.line)
        game_row = _csv_row_at(game_data, game_line)
        if (mod_row is not None and game_row is not None and mod_row[1] == key == game_row[1]
                and is_degraded(mod_row[0], game_row[0])):
            return (problem.line, mod_row[0], mod_row[2]), (game_line, game_row[0], game_row[2])
    rows = degraded_rows(mod_data, game_data)
    if not rows:
        return None
    mod_row, game_row, _ = rows[0]
    return (mod_row.line, mod_row.raw, mod_row.fields), (game_row.line, game_row.raw, game_row.fields)


@explainer("loc_copy_degraded")
def _loc_copy_degraded(problem: Problem, ctx: ValidationContext) -> Explanation:
    """El CSV del mod sustituye al del juego con el mismo nombre: una fila de ejemplo en las dos capas."""
    from ..csvloc.model import LANGUAGE_CODES

    rel = problem.rel
    game = next((e for e in ctx.stack(rel) if e.layer.kind is LayerKind.GAME), None)
    mod_data = ctx.read(rel)
    game_data = ctx.read_entry(game) if game is not None else None
    if mod_data is None or game_data is None:
        return _generic(problem, ctx)
    example = _degraded_example(problem, mod_data, game_data)
    if example is None:
        return _generic(problem, ctx)
    (mod_line, mod_raw, mod_fields), (game_line, game_raw, game_fields) = example
    # ``fields`` son las columnas tras la clave: el índice 0 es el inglés (columna 1 del CSV).
    position = next((i for i, (a, b) in enumerate(zip(mod_fields, game_fields)) if a != b), 0)
    column = position + 1
    lang = next((code for code, number in LANGUAGE_CODES.items() if number == column), "en")
    mod_layer = LAYER_UNSAVED if ctx.unsaved(rel) else LAYER_MOD
    steps = [ExplainStep(mod_layer, rel, mod_line, _clip(mod_raw), VERDICT_WINS),
             ExplainStep(LAYER_GAME, game.rel, game_line, _clip(game_raw), VERDICT_LOSES)]
    shown = mod_fields[position] if position < len(mod_fields) else ""
    original = game_fields[position] if position < len(game_fields) else ""
    key = mod_raw.split(";", 1)[0]
    return _explanation(problem, steps, key=key, example=_clip(shown, 60), original=_clip(original, 60),
                        column=column, lang=lang)


def _clip(text: str, limit: int = MAX_EXCERPT) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _definition_steps(ctx: ValidationContext, problem: Problem) -> list[ExplainStep]:
    """Cada definición del símbolo del problema (la efectiva gana; las demás pierden)."""
    if problem.entity is None:
        return layer_steps(ctx, problem.rel, problem.line)
    kind, name = problem.entity
    index = ctx.index
    if kind == m.KIND_TAG and problem.code == "country_history_duplicate":
        kind = m.KIND_COUNTRY_HISTORY
    elif kind == m.KIND_PROVINCE and problem.code == "province_history_duplicate":
        kind = m.KIND_PROVINCE_HISTORY
    symbols = index.lookup(kind, name)
    steps = []
    for number, symbol in enumerate(symbols):
        effective = index.is_effective(symbol)
        verdict = VERDICT_WINS if effective and number == 0 else VERDICT_LOSES
        steps.append(_step_at(ctx, symbol.rel, symbol.line, verdict) if effective else
                     ExplainStep(_LAYERS.get(symbol.layer, LAYER_MOD), symbol.rel, symbol.line, "", verdict))
    return steps or layer_steps(ctx, problem.rel, problem.line)


@explainer("province_history_duplicate", "country_history_duplicate", "event_id_duplicate", "decision_duplicate",
           "tag_taken")
def _duplicates(problem: Problem, ctx: ValidationContext) -> Explanation:
    return _explanation(problem, _definition_steps(ctx, problem))


# Dónde se define cada tipo (para «falta» en las referencias rotas).
DEFINED_IN = {
    m.KIND_CULTURE: "common/cultures.txt", m.KIND_RELIGION: "common/religion.txt",
    m.KIND_GOVERNMENT: "common/governments.txt", m.KIND_NATIONAL_VALUE: "common/nationalvalues.txt",
    m.KIND_GOODS: "common/goods.txt", m.KIND_BUILDING: "common/buildings.txt", m.KIND_CB: "common/cb_types.txt",
    m.KIND_TECH_SCHOOL: "common/technology.txt", m.KIND_IDEOLOGY: "common/ideologies.txt",
    m.KIND_GRAPHICAL_CULTURE: "common/graphicalculturetype.txt", m.KIND_TERRAIN: "map/terrain.txt",
    m.KIND_PROVINCE: "map/definition.csv", m.KIND_ISSUE_OPTION: "common/issues.txt",
    m.KIND_TAG: "common/countries.txt",
}
DEFINED_IN_FOLDER = {m.KIND_TECHNOLOGY: "technologies", m.KIND_INVENTION: "inventions",
                     m.KIND_POP_TYPE: "poptypes", m.KIND_UNIT_TYPE: "units", m.KIND_DECISION: "decisions",
                     m.KIND_EVENT: "events", m.KIND_LOC_KEY: "localisation"}


@explainer("culture_unknown", "religion_unknown", "government_unknown", "nationalvalue_unknown",
           "technology_unknown", "invention_unknown", "goods_unknown", "building_unknown", "pop_type_unknown",
           "cb_unknown", "unit_unknown", "tech_school_unknown", "ideology_unknown", "graphical_culture_unknown",
           "terrain_unknown", "province_unknown", "decision_unknown", "reform_unknown", "event_ref_missing",
           "loc_key_missing", "oob_file_missing", "peace_order_unknown", "country_file_missing")
def _unknown(problem: Problem, ctx: ValidationContext) -> Explanation:
    """El uso (gana: el juego lo lee) frente a dónde tendría que estar definido (falta)."""
    steps = []
    if problem.rel is not None and problem.line is not None:
        steps.append(_step_at(ctx, problem.rel, problem.line, VERDICT_WINS))
    kind = problem.entity[0] if problem.entity else None
    name = problem.entity[1] if problem.entity else ""
    if problem.code == "oob_file_missing":
        target = VPath.of(str(problem.args.get("file", name)))
        steps.append(ExplainStep(LAYER_MOD, target, None, "", VERDICT_MISSING))
    elif problem.code == "country_file_missing":
        target = VPath.of("common/" + str(problem.args.get("file", "")).replace("\\", "/").lstrip("/"))
        steps.extend(layer_steps(ctx, target, None) if ctx.stack(target) else
                     [ExplainStep(LAYER_MOD, target, None, "", VERDICT_MISSING)])
    elif kind in DEFINED_IN:
        target = VPath.of(DEFINED_IN[kind])
        entry = ctx.entry(target)
        layer = _LAYERS[entry.layer.kind] if entry is not None else LAYER_GAME
        steps.append(ExplainStep(layer, entry.rel if entry is not None else target, None, name, VERDICT_MISSING))
    elif kind in DEFINED_IN_FOLDER:
        folder = DEFINED_IN_FOLDER[kind]
        steps.append(ExplainStep(LAYER_GAME, None, None, f"{folder}/", VERDICT_MISSING))
    if not steps:
        steps = layer_steps(ctx, problem.rel, problem.line)
    return _explanation(problem, steps, name=name)


@explainer("tag_after_dynamic_tags")
def _after_dynamic(problem: Problem, ctx: ValidationContext) -> Explanation:
    rel = problem.rel or COUNTRIES_REL
    lines = _lines(ctx.read(rel))
    anchor = next((n for n, text in enumerate(lines, start=1) if text.strip().lower().startswith("dynamic_tags")),
                  None)
    steps = []
    if anchor is not None:
        steps.append(_step_at(ctx, rel, anchor, VERDICT_WINS))
    steps.append(_step_at(ctx, rel, problem.line, VERDICT_LOSES))
    return _explanation(problem, steps)


@explainer("ruling_party_not_of_country", "ruling_party_ideology_not_allowed")
def _ruling_party(problem: Problem, ctx: ValidationContext) -> Explanation:
    """La línea de la historia, el archivo de país del TAG con sus partidos y el gobierno."""
    from .rules.countries import country_file_of, parties_by_file

    steps = [_step_at(ctx, problem.rel, problem.line, VERDICT_WINS)] if problem.rel is not None else []
    tag = str(problem.args.get("tag", ""))
    party = str(problem.args.get("party", ""))
    index = ctx.index
    file = country_file_of(index, tag) if tag else None
    if file is not None:
        symbol = index.get(m.KIND_COUNTRY_FILE, file)
        own = parties_by_file(index).get(file, {})
        found = own.get(party)
        if found is not None:
            steps.append(_step_at(ctx, found.rel, found.line, VERDICT_WINS))
        elif symbol is not None:
            steps.append(ExplainStep(_LAYERS.get(symbol.layer, LAYER_MOD), symbol.rel, None, party, VERDICT_MISSING))
    government = problem.args.get("government")
    if government:
        symbol = index.get(m.KIND_GOVERNMENT, str(government))
        if symbol is not None:
            steps.append(_step_at(ctx, symbol.rel, symbol.line, VERDICT_WINS))
    return _explanation(problem, steps)


@explainer("replace_path_empty", "replace_path_hides_referenced")
def _replace_path(problem: Problem, ctx: ValidationContext) -> Explanation:
    """El descriptor y los archivos del juego que oculta la carpeta reemplazada."""
    steps = layer_steps(ctx, problem.rel, problem.line)
    folder = str(problem.args.get("replace_path", "")).replace("\\", "/").strip("/").upper()
    hidden = sorted(key for key in ctx.snapshot.hidden if key.startswith(folder + "/"))
    for key in hidden[:MAX_STEPS - len(steps)]:
        entry = ctx.snapshot.entries[key][-1]
        steps.append(ExplainStep(LAYER_REPLACE_PATH, entry.rel, None, entry.rel.name, VERDICT_HIDDEN))
    return _explanation(problem, steps, hidden=len(hidden))
