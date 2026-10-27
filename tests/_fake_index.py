"""Índice de símbolos, validación y línea base falsos para las pruebas de la interfaz (wizard §20).

Las pruebas de la interfaz usan estos falsos (rápidos y sin depender de las reglas reales,
que prueban ``test_validate_*``), que siguen las firmas del contrato y se inyectan en
``Session(index=..., validation=..., baseline=...)``. El recorrido con los motores reales
está en ``test_e2e_it3`` y ``test_ui_validation.RealCoreTests``:

- ``FakeSymbolIndex``: la API de ``SymbolIndex`` (``names``, ``get``, ``lookup``,
  ``search``, ``display``, ``apply``…) sobre ``FileFacts`` reales, con una regla de carga
  simplificada (por ruta gana la capa de más prioridad).
- ``fake_extract``: extractores mínimos del minijuego (TAG de ``countries.txt``,
  historias de país y de provincia, eventos, decisiones, CB y claves de localización).
- ``FakeIndexEngine``, ``FakeValidationEngine`` y ``FakeBaselineEngine``: los motores de
  ``ui/session.py`` con contadores, compuertas (``threading.Event``) y fallos a la carta.
- Reglas falsas (``tag_not_registered``, ``loc_key_missing``, ``mod_shadow_identical``) y
  sus arreglos (``register_tag``, ``add_loc_key``, ``trash_identical_copies``), con plan
  por reversión: se aplica dentro de una transacción que se deshace al lanzar, así que
  el proyecto y su pila de deshacer quedan idénticos.

Los mensajes, las etiquetas de los arreglos y los textos del explicador son de los
falsos (``TEXTS``, ES/EN): los textos del núcleo están en ``core/validate/texts/issues.*.json``.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from vic2studio.core.clausewitz import Scalar, Severity
from vic2studio.core.index import model as index_model
from vic2studio.core.index.model import FileFacts, Symbol, SymbolRef, fold
from vic2studio.core.project.codecs import parse_bytes
from vic2studio.core.validate.model import (
    ACTION_COPY_FROM_GAME,
    ACTION_CREATE,
    ACTION_MODIFY,
    ACTION_TRASH,
    LAYER_GAME,
    LAYER_MOD,
    VERDICT_LOSES,
    VERDICT_MISSING,
    VERDICT_WINS,
    ChangePlan,
    Explanation,
    ExplainStep,
    FixSpec,
    PlannedChange,
    Problem,
    ValidationReport,
)
from vic2studio.core.vfs.model import Fingerprint, LayerKind, VfsSnapshot
from vic2studio.core.vfs.paths import VPath

TAG_RE = re.compile(r"^[A-Z][A-Z0-9]{2}$")
_LAYER_ORDER = {LayerKind.MOD: 0, LayerKind.DEPENDENCY: 1, LayerKind.GAME: 2}

# Textos de los falsos: lo que darían issues.{es,en}.json y los arreglos y el explicador del núcleo.
TEXTS = {
    "issue.tag_not_registered": {"es": "El país {tag} tiene historia pero no está en common/countries.txt.",
                                 "en": "Country {tag} has a history but is not in common/countries.txt."},
    "issue.loc_key_missing": {"es": "Falta el nombre del país {key} en la localización.",
                              "en": "The name of country {key} is missing from the localisation."},
    "issue.mod_shadow_identical": {"es": "{rel} es idéntico al del juego base.",
                                   "en": "{rel} is identical to the base game's."},
    "fix.register_tag": {"es": "Registrar {tag} en countries.txt", "en": "Register {tag} in countries.txt"},
    "fix.add_loc_key": {"es": "Añadir la clave {key}", "en": "Add key {key}"},
    "fix.trash_identical_copies": {"es": "Mover la copia a la papelera", "en": "Move the copy to the trash"},
    "explain.layer.game": {"es": "Juego base", "en": "Base game"},
    "explain.layer.mod": {"es": "Mod", "en": "Mod"},
    "explain.verdict.wins": {"es": "gana", "en": "wins"},
    "explain.verdict.loses": {"es": "pierde", "en": "loses"},
    "explain.verdict.missing": {"es": "falta", "en": "missing"},
    "explain.title.generic": {"es": "Por qué {rel} da este problema", "en": "Why {rel} has this problem"},
    "explain.outcome.tag_not_registered": {
        "es": "En partida, {tag} no existirá: el juego solo crea los países de countries.txt.",
        "en": "In game, {tag} will not exist: the game only creates the countries in countries.txt."},
    "explain.outcome.generic": {"es": "El juego carga la versión que gana.",
                                "en": "The game loads the winning version."},
}


def fake_text(key: str, lang: str, /, **fmt) -> str:
    entry = TEXTS.get(key)
    template = key if entry is None else entry.get(lang, entry["en"])
    try:
        return template.format(**fmt)
    except (KeyError, IndexError, ValueError):
        return template


# --- índice en memoria -------------------------------------------------------------------------------------


class FakeSymbolIndex:
    """``SymbolIndex`` en memoria: por cada ruta cuentan los hechos de la capa de más prioridad (mod, dependencia,
    juego); los de las capas que pierden salen después en ``lookup``. ``applied`` anota cada ``apply``."""

    def __init__(self, facts: Iterable[FileFacts] = (), *, snapshot=None) -> None:
        self.generation = 0
        self.applied: list[tuple[list[FileFacts], list]] = []
        self._facts: dict[tuple[str, LayerKind], list[FileFacts]] = {}
        for fact in facts:
            self._facts.setdefault((fact.rel.key, fact.layer), []).append(fact)
        self._rebuild()

    # --- mantenimiento ------------------------------------------------------------------------------------

    def apply(self, facts: Iterable[FileFacts], removed: Iterable = (), *, snapshot=None) -> None:
        facts, removed = list(facts), list(removed)
        replaced: set[tuple[str, LayerKind]] = set()
        for fact in facts:
            key = (fact.rel.key, fact.layer)
            if key not in replaced:
                self._facts[key] = []
                replaced.add(key)
            self._facts[key].append(fact)
        for rel, layer in removed:
            self._facts.pop((VPath.of(rel).key, layer), None)
        self.applied.append((facts, removed))
        self.generation += 1
        self._rebuild()

    def facts(self) -> list[FileFacts]:
        return [fact for group in self._facts.values() for fact in group]

    def _rebuild(self) -> None:
        winners: dict[str, LayerKind] = {}
        for rel_key, layer in self._facts:
            current = winners.get(rel_key)
            if current is None or _LAYER_ORDER[layer] < _LAYER_ORDER[current]:
                winners[rel_key] = layer
        self._defs: dict[str, dict[str, list[Symbol]]] = {}
        self._losers: dict[str, dict[str, list[Symbol]]] = {}
        self._refs: list[SymbolRef] = []
        self._by_rel: dict[str, list[Symbol]] = {}
        self._refs_by_rel: dict[str, list[SymbolRef]] = {}
        ordered = sorted(self._facts.items(), key=lambda item: (item[0][0], _LAYER_ORDER[item[0][1]]))
        for (rel_key, layer), group in ordered:
            effective = winners[rel_key] is layer
            for fact in group:
                for symbol in fact.defs:
                    target = self._defs if effective else self._losers
                    target.setdefault(symbol.kind, {}).setdefault(symbol.name, []).append(symbol)
                    if effective:
                        self._by_rel.setdefault(rel_key, []).append(symbol)
                if effective:
                    self._refs.extend(fact.refs)
                    self._refs_by_rel.setdefault(rel_key, []).extend(fact.refs)

    # --- consultas ----------------------------------------------------------------------------------------

    def kinds(self) -> list[str]:
        return sorted(kind for kind, names in self._defs.items() if names)

    def names(self, kind: str) -> list[str]:
        return list(self._defs.get(kind, {}))

    def count(self, kind: str) -> int:
        return len(self._defs.get(kind, {}))

    def get(self, kind: str, name: str) -> Symbol | None:
        found = self._defs.get(kind, {}).get(name)
        return found[0] if found else None

    def lookup(self, kind: str, name: str) -> list[Symbol]:
        return [*self._defs.get(kind, {}).get(name, ()), *self._losers.get(kind, {}).get(name, ())]

    def exists(self, kind: str, name: str, *, ignore_case: bool = False) -> bool:
        if not ignore_case:
            return name in self._defs.get(kind, {})
        folded = name.casefold()
        return any(other.casefold() == folded for other in self._defs.get(kind, {}))

    def attrs(self, kind: str, name: str, attr: str, default=None) -> object:
        symbol = self.get(kind, name)
        return default if symbol is None else symbol.attrs.get(attr, default)

    def symbols(self, kind: str) -> list[Symbol]:
        return [found[0] for found in self._defs.get(kind, {}).values()]

    def defs_in(self, rel) -> list[Symbol]:
        return list(self._by_rel.get(VPath.of(rel).key, ()))

    def refs_to(self, kind: str, name: str) -> list[SymbolRef]:
        return [ref for ref in self._refs if ref.kind == kind and ref.name == name]

    def refs_from(self, rel) -> list[SymbolRef]:
        return list(self._refs_by_rel.get(VPath.of(rel).key, ()))

    def refs(self, kind: str) -> list[SymbolRef]:
        return [ref for ref in self._refs if ref.kind == kind]

    @staticmethod
    def _loc_key(symbol: Symbol) -> str:
        return f"PROV{symbol.name}" if symbol.kind == index_model.KIND_PROVINCE else symbol.name

    def _localised(self, symbol: Symbol, loc, lang: str) -> str:
        if loc is None:
            return ""
        return loc.lookup(self._loc_key(symbol), lang) or ""

    def search(self, text: str, *, kinds: Collection[str] = (), loc=None, lang: str = "es",
               limit: int = 50) -> list[Symbol]:
        needle = fold(text.strip())
        if not needle:
            return []
        ranked = []
        for kind, names in self._defs.items():
            if kinds and kind not in kinds:
                continue
            for name, found in names.items():
                symbol = found[0]
                candidates = [fold(name)]
                localised = self._localised(symbol, loc, lang)
                if localised:
                    candidates.append(fold(localised))
                rank = min((0 if c == needle else 1 if c.startswith(needle) else 2 if needle in c else 3)
                           for c in candidates)
                if rank < 3:
                    ranked.append((rank, kind, name, symbol))
        ranked.sort(key=lambda item: item[:3])
        return [symbol for *_, symbol in ranked[:limit]]

    def display(self, kind: str, name: str, loc=None, lang: str = "es") -> str:
        symbol = self.get(kind, name)
        localised = self._localised(symbol, loc, lang) if symbol is not None else ""
        if not localised or localised == name:
            return name
        if kind == index_model.KIND_PROVINCE:
            return f"{name} {localised}"
        return f"{localised} ({name})"


# --- extractores del minijuego ---------------------------------------------------------------------------------


def _symbol(kind: str, name: str, rel: VPath, line, layer: LayerKind, **attrs) -> Symbol:
    return Symbol(kind, name, rel, line, layer, MappingProxyType(attrs))


def _clausewitz_facts(rel: VPath, data: bytes, layer: LayerKind) -> tuple[list[Symbol], list[SymbolRef]]:
    defs: list[Symbol] = []
    refs: list[SymbolRef] = []
    key = rel.key
    try:
        document = parse_bytes(data).document
    except Exception:  # noqa: BLE001 - un archivo roto da lo que se pueda
        return defs, refs
    if key == "COMMON/COUNTRIES.TXT":
        dynamic = False
        for entry in document:
            name = entry.key.text if entry.key is not None else ""
            if name == "dynamic_tags":
                dynamic = True
            elif TAG_RE.match(name):
                defs.append(_symbol(index_model.KIND_TAG, name, rel, entry.line, layer, dynamic=dynamic))
    elif key == "COMMON/CB_TYPES.TXT":
        for entry in document:
            name = entry.key.text if entry.key is not None else ""
            if name and name != "peace_order":
                defs.append(_symbol(index_model.KIND_CB, name, rel, entry.line, layer))
    elif key.startswith("HISTORY/COUNTRIES/"):
        tag = rel.name[:3].upper()
        defs.append(_symbol(index_model.KIND_COUNTRY_HISTORY, tag, rel, 1, layer))
    elif key.startswith("HISTORY/PROVINCES/"):
        match = re.match(r"\s*(\d+)", rel.name)
        if match:
            ident = str(int(match.group(1)))
            defs.append(_symbol(index_model.KIND_PROVINCE_HISTORY, ident, rel, 1, layer))
            defs.append(_symbol(index_model.KIND_PROVINCE, ident, rel, 1, layer))
            for entry in document:
                name = entry.key.text if entry.key is not None else ""
                if name in ("owner", "controller", "add_core") and isinstance(entry.value, Scalar):
                    refs.append(SymbolRef(index_model.KIND_TAG, entry.value.text, rel, entry.line, entry.column, name))
    elif key.startswith("EVENTS/"):
        for entry in document:
            name = entry.key.text if entry.key is not None else ""
            if name in ("country_event", "province_event") and not isinstance(entry.value, Scalar):
                ident = entry.value.find("id")
                if ident is not None and isinstance(ident.value, Scalar):
                    defs.append(_symbol(index_model.KIND_EVENT, ident.value.text, rel, entry.line, layer, type=name))
    elif key.startswith("DECISIONS/"):
        for entry in document:
            if entry.key is not None and entry.key.text == "political_decisions" and not isinstance(entry.value,
                                                                                                     Scalar):
                for decision in entry.value:
                    if decision.key is not None:
                        defs.append(_symbol(index_model.KIND_DECISION, decision.key.text, rel, decision.line, layer))
    return defs, refs


def _localisation_facts(rel: VPath, data: bytes, layer: LayerKind) -> tuple[list[Symbol], list[SymbolRef]]:
    from vic2studio.core.locsync import _load_csv

    defs = []
    file = _load_csv(data)
    for number, row in enumerate(file.rows, 1):
        if row.kind.value == "data" and row.key:
            defs.append(_symbol(index_model.KIND_LOC_KEY, row.key, rel, number, layer))
    return defs, []


def fake_extractable(rel) -> bool:
    rel = VPath.of(rel)
    key = rel.key
    if key.startswith("LOCALISATION/") and rel.suffix == ".csv":
        return True
    return rel.suffix == ".txt" and key.split("/", 1)[0] in ("COMMON", "HISTORY", "EVENTS", "DECISIONS")


def fake_extract(rel, data: bytes, layer: LayerKind) -> list[FileFacts]:
    """Hechos de un archivo del minijuego (uno por «extractor»: ``fake.clausewitz`` o ``fake.localisation``)."""
    rel = VPath.of(rel)
    if not fake_extractable(rel):
        return []
    if rel.suffix == ".csv":
        defs, refs, name = (*_localisation_facts(rel, data, layer), "fake.localisation")
    else:
        defs, refs, name = (*_clausewitz_facts(rel, data, layer), "fake.clausewitz")
    return [FileFacts(rel, layer, Fingerprint(len(data), 0), tuple(defs), tuple(refs), name, 1)]


def game_only(snapshot: VfsSnapshot) -> VfsSnapshot:
    """La instantánea con solo la capa del juego (lo que hará ``game_only_snapshot`` de A)."""
    layers = tuple(layer for layer in snapshot.layers if layer.kind is LayerKind.GAME)
    entries = {}
    for key, stack in snapshot.entries.items():
        kept = tuple(entry for entry in stack if entry.layer.kind is LayerKind.GAME)
        if kept:
            entries[key] = kept
    return VfsSnapshot(layers, MappingProxyType(entries), frozenset())


class _Gate:
    """Compuerta opcional y fallo a la carta de un motor falso (para probar esperas, cancelaciones y fallos)."""

    def __init__(self, gate: threading.Event | None, error: BaseException | None):
        self.gate = gate
        self.error = error
        self.started = threading.Event()

    def pass_through(self, cancelled) -> None:
        self.started.set()
        if self.gate is not None:
            while not self.gate.wait(0.01):
                if cancelled is not None and cancelled():
                    from vic2studio.core.cancel import Cancelled

                    raise Cancelled()
        if self.error is not None:
            raise self.error


class FakeIndexEngine(_Gate):
    """``IndexEngine`` falso: lee la instantánea con ``fake_extract``; anota construcciones y extracciones."""

    def __init__(self, *, gate: threading.Event | None = None, error: BaseException | None = None):
        super().__init__(gate, error)
        self.builds: list[tuple[VfsSnapshot, dict]] = []
        self.extracted: list[tuple[VPath, LayerKind]] = []
        self.lock = threading.Lock()

    def build(self, snapshot: VfsSnapshot, overrides: Mapping, *, progress=None, cancelled=None) -> FakeSymbolIndex:
        with self.lock:
            self.builds.append((snapshot, dict(overrides)))
        self.pass_through(cancelled)
        facts: list[FileFacts] = []
        stacks = [stack for stack in snapshot.entries.values()]
        for done, stack in enumerate(stacks, 1):
            for entry in stack:
                if entry.layer.kind is LayerKind.GAME and entry.rel.key in snapshot.hidden:
                    continue
                if fake_extractable(entry.rel):
                    facts.extend(fake_extract(entry.rel, entry.path.read_bytes(), entry.layer.kind))
            if progress is not None:
                progress(done, len(stacks))
        for rel, data in overrides.items():
            facts = [f for f in facts if not (f.rel.key == VPath.of(rel).key and f.layer is LayerKind.MOD)]
            facts.extend(fake_extract(rel, data, LayerKind.MOD))
        return FakeSymbolIndex(facts, snapshot=snapshot)

    def extract(self, rel, data: bytes, layer: LayerKind) -> list[FileFacts]:
        with self.lock:
            self.extracted.append((VPath.of(rel), layer))
        return fake_extract(rel, data, layer)


# --- validación ------------------------------------------------------------------------------------------------


class FakeProblem(Problem):
    """``Problem`` con el mensaje de ``TEXTS`` (los textos del núcleo aún no existen)."""

    def message(self, lang: str = "en") -> str:
        return fake_text(f"issue.{self.code}", lang, rel=self.rel or "", **dict(self.args))


@dataclass(frozen=True)
class FakeFixSpec(FixSpec):
    def label(self, problem: Problem, lang: str = "en") -> str:
        return fake_text(self.label_key, lang, **dict(self.label_args(problem) if self.label_args else {}))


@dataclass(frozen=True)
class FakeExplainStep(ExplainStep):
    def layer_text(self, lang: str = "en") -> str:
        return fake_text(f"explain.layer.{self.layer}", lang)

    def verdict_text(self, lang: str = "en") -> str:
        return fake_text(f"explain.verdict.{self.verdict}", lang)


@dataclass(frozen=True)
class FakeExplanation(Explanation):
    def title(self, lang: str = "en") -> str:
        return fake_text(self.title_key, lang, **dict(self.args))

    def outcome(self, lang: str = "en") -> str:
        return fake_text(self.outcome_key, lang, **dict(self.args))


SEVERITIES = {"tag_not_registered": Severity.ERROR, "loc_key_missing": Severity.WARNING,
              "mod_shadow_identical": Severity.INFO}
FIXES_OF = {"tag_not_registered": ("register_tag",), "loc_key_missing": ("add_loc_key",),
            "mod_shadow_identical": ("trash_identical_copies",)}


def problem(code: str, rel, line=None, *, entity=None, **args) -> FakeProblem:
    return FakeProblem(code, SEVERITIES[code], None if rel is None else VPath.of(rel), line, None, entity, (),
                       MappingProxyType(dict(args)), False, FIXES_OF[code])


@dataclass
class FakeContext:
    """Lo que ven las reglas falsas: instantánea, índice, documentos sin guardar y fecha."""

    snapshot: VfsSnapshot
    index: FakeSymbolIndex
    overrides: Mapping = field(default_factory=dict)
    date: object = None
    game_only: bool = False

    def read(self, rel) -> bytes | None:
        rel = VPath.of(rel)
        for other, data in self.overrides.items():
            if VPath.of(other).key == rel.key:
                return data
        entry = self.snapshot.resolve(rel)
        return None if entry is None else entry.path.read_bytes()


def fake_rules(context: FakeContext) -> list[FakeProblem]:
    index = context.index
    found: list[FakeProblem] = []
    tags = set(index.names(index_model.KIND_TAG))
    for history in index.symbols(index_model.KIND_COUNTRY_HISTORY):
        if history.name not in tags:
            found.append(problem("tag_not_registered", history.rel, 1, entity=("tag", history.name), tag=history.name))
    loc_keys = set(index.names(index_model.KIND_LOC_KEY))
    for tag in index.symbols(index_model.KIND_TAG):
        if tag.name not in loc_keys and not tag.attrs.get("dynamic"):
            found.append(problem("loc_key_missing", tag.rel, tag.line, entity=("tag", tag.name), key=tag.name))
    if not context.game_only:
        for key, stack in context.snapshot.entries.items():
            mod = next((e for e in stack if e.layer.kind is LayerKind.MOD), None)
            game = next((e for e in stack if e.layer.kind is LayerKind.GAME), None)
            if mod is not None and game is not None and mod.rel.key not in {VPath.of(r).key for r in context.overrides}:
                if mod.fingerprint.size == game.fingerprint.size and mod.path.read_bytes() == game.path.read_bytes():
                    found.append(problem("mod_shadow_identical", mod.rel, None))
    return found


def _sort_key(item: Problem):
    order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    return (order[item.severity], "" if item.rel is None else item.rel.key, item.line or 0, item.code)


class FakeValidationEngine(_Gate):
    """``ValidationEngine`` falso: ``fake_rules`` sobre un ``FakeContext``; arreglos y explicador de prueba."""

    def __init__(self, *, gate: threading.Event | None = None, error: BaseException | None = None):
        super().__init__(gate, error)
        self.validations = 0
        self.explained: list[Problem] = []
        self.applied: list[tuple[str, Problem]] = []
        self.fixes = {spec.key: spec for spec in make_fake_fixes(self)}

    def context(self, snapshot, index, overrides, *, date=None, cancelled=None) -> FakeContext:
        return FakeContext(snapshot, index, dict(overrides), date)

    def validate(self, context: FakeContext, baseline, *, progress=None, cancelled=None) -> ValidationReport:
        self.pass_through(cancelled)
        self.validations += 1
        found = fake_rules(context)
        if progress is not None:
            progress(1, 1)
        if baseline is not None:
            found = [FakeProblem(**{**_fields(p), "inherited": p.fingerprint() in baseline}) for p in found]
        found.sort(key=_sort_key)
        return ValidationReport(tuple(found), files=len(context.snapshot.entries), elapsed=0.01,
                                baseline_ready=baseline is not None)

    def explain(self, problem: Problem, context: FakeContext) -> FakeExplanation:
        self.explained.append(problem)
        steps = []
        for entry in context.snapshot.stack(problem.rel) if problem.rel is not None else []:
            data = entry.path.read_bytes().decode("cp1252", "replace").splitlines()
            line = problem.line or 1
            excerpt = data[line - 1] if 0 < line <= len(data) else ""
            layer = LAYER_MOD if entry.layer.kind is LayerKind.MOD else LAYER_GAME
            verdict = VERDICT_WINS if not steps else VERDICT_LOSES
            steps.append(FakeExplainStep(layer, entry.rel, line, excerpt, verdict))
        if problem.code == "tag_not_registered":
            steps.append(FakeExplainStep(LAYER_GAME, VPath.of("common/countries.txt"), None, "", VERDICT_MISSING))
            outcome = "explain.outcome.tag_not_registered"
        else:
            outcome = "explain.outcome.generic"
        return FakeExplanation("explain.title.generic", tuple(steps), outcome,
                               MappingProxyType({"rel": str(problem.rel or ""), **dict(problem.args)}),
                               tuple(problem.fixes))

    def fixes_for(self, problem: Problem) -> list[FixSpec]:
        return [self.fixes[key] for key in problem.fixes if key in self.fixes]

    def plan_fix(self, key: str, problem: Problem, project) -> ChangePlan:
        return self.fixes[key].plan(problem, project)

    def apply_fix(self, key: str, problem: Problem, project, expected=None) -> None:
        self.applied.append((key, problem))
        self.fixes[key].apply(problem, project)


def _fields(item: Problem) -> dict:
    return {name: getattr(item, name) for name in ("code", "severity", "rel", "line", "column", "entity", "field",
                                                   "args", "inherited", "fixes")}


class FakeBaselineEngine(_Gate):
    """``BaselineEngine`` falso: las reglas falsas sobre la capa del juego sola; anota cada cálculo."""

    def __init__(self, *, gate: threading.Event | None = None, error: BaseException | None = None):
        super().__init__(gate, error)
        self.computed = 0

    def compute(self, snapshot: VfsSnapshot, *, cancelled=None) -> frozenset:
        self.pass_through(cancelled)
        self.computed += 1
        game = game_only(snapshot)
        index = FakeIndexEngine().build(game, {})
        return frozenset(p.fingerprint() for p in fake_rules(FakeContext(game, index, {}, None, True)))


# --- arreglos de prueba ------------------------------------------------------------------------------------------

UNDO_LABEL = "pending.undo_revert"   # una etiqueta que ya existe en el catálogo (los «undo.fix_*» son de A)
ACTIONS = {"create": ACTION_CREATE, "modify": ACTION_MODIFY, "copy_from_game": ACTION_COPY_FROM_GAME,
           "trash": ACTION_TRASH}


class _Rollback(Exception):
    """Deshace la transacción del plan: el proyecto queda como estaba, pila de deshacer incluida."""


def plan_by_rollback(key: str, apply, problem: Problem, project) -> ChangePlan:
    captured: list = []
    try:
        with project.ws.transaction(UNDO_LABEL, name=key) as txn:
            apply(problem, project)
            captured.append(project.ws.changeset(txn.touched()))
            raise _Rollback
    except _Rollback:
        pass
    changes = tuple(PlannedChange(write.rel, ACTIONS[write.action.value], write.diff) for write in captured[0].writes)
    return ChangePlan(key, changes)


def _register_tag(problem: Problem, project) -> None:
    tag = problem.args["tag"]
    with project.edit(UNDO_LABEL, name="common/countries.txt"):
        handle = project.ws.open("common/countries.txt")
        project.ws.touch(handle)
        document = handle.model.document
        anchor = document.find("dynamic_tags")
        value = Scalar(f"countries/{tag}.txt", quoted=True)
        if anchor is None:
            document.append(tag, value)
        else:
            document.insert_before(anchor, tag, value)


def _add_loc_key(problem: Problem, project) -> None:
    from vic2studio.core.locsync import LocSync

    key = problem.args["key"]
    settings = project.settings
    with project.edit(UNDO_LABEL, name=key):
        LocSync(project.ws, project.vfs, prefix=settings.prefix).ensure({key: {"en": key}}, area="countries")


def _trash_copy(problem: Problem, project) -> None:
    with project.edit(UNDO_LABEL, name=str(problem.rel)):
        project.ws.delete(problem.rel)


def make_fake_fixes(engine) -> list[FakeFixSpec]:
    def spec(key: str, safe: bool, apply, args) -> FakeFixSpec:
        return FakeFixSpec(key, f"fix.{key}", safe, lambda p, project: plan_by_rollback(key, apply, p, project),
                           apply, args)

    return [
        spec("register_tag", True, _register_tag, lambda p: {"tag": p.args.get("tag", "")}),
        spec("add_loc_key", True, _add_loc_key, lambda p: {"key": p.args.get("key", "")}),
        spec("trash_identical_copies", False, _trash_copy, lambda p: {}),
    ]


def fake_engines(**options) -> dict:
    """Los tres motores falsos, listos para ``Session(**fake_engines())``."""
    return {"index": FakeIndexEngine(**options.get("index", {})),
            "validation": FakeValidationEngine(**options.get("validation", {})),
            "baseline": FakeBaselineEngine(**options.get("baseline", {}))}
