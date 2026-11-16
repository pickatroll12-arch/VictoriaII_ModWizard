"""Guerras y diplomacia de inicio (wizard §14.8, §14.2 «Diplomacia»). Contrato e implementación de la iteración 6.

**Guerras** (``history/wars/<archivo>.txt``): ``name = "…"`` (opcional; vanilla lo deja comentado en una) y
bloques fechados con ``add_attacker``, ``add_defender``, ``rem_attacker``, ``rem_defender`` y
``war_goal = { casus_belli actor receiver [state_province_id] [country] }``. ``read_war`` lo convierte en un
``WarModel`` (línea temporal y objetivos) sin cambiar nada; ``war_text`` escribe una guerra nueva con la misma
forma: el nombre, una línea en blanco, el bloque de la fecha de inicio con los bandos y los objetivos (cada uno
en su bloque) y, si hay fecha de fin, otro bloque con las salidas. ``create_war`` la crea en una transacción
(``undo.new_war``) y ``plan_war`` la enseña sin crearla.

**Diplomacia** (``history/diplomacy/*.txt``): bloques ``alliance``, ``vassal``, ``substate``, ``union`` y
``guarantee`` con ``first``, ``second``, ``start_date`` y ``end_date``. ``relations`` los lee todos y
``add_relation`` / ``remove_relation`` editan sin pérdidas (el resto del archivo queda byte a byte).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..clausewitz.nodes import Block, ClausewitzDate, EditError, Scalar
from ..encoding import GAME_ENCODING
from ..rules.names import clean_file_name
from ..vfs.paths import VPath

if TYPE_CHECKING:
    from ..project import Project
    from ..validate.model import ChangePlan

UNDO_NEW_WAR = "undo.new_war"
UNDO_RELATION_ADD = "undo.diplomacy_add"
UNDO_RELATION_REMOVE = "undo.diplomacy_remove"
WARS_FOLDER = "history/wars"
DIPLOMACY_FOLDER = "history/diplomacy"
WAR_ACTIONS = ("add_attacker", "add_defender", "rem_attacker", "rem_defender")
GOAL_KEYS = ("casus_belli", "actor", "receiver", "state_province_id", "country")
RELATION_TYPES = ("alliance", "vassal", "substate", "union", "guarantee")
# Archivo de vanilla donde va cada tipo de relación nueva (si no existe, se crea con el prefijo del proyecto).
RELATION_FILES = {"alliance": "Alliances.txt", "vassal": "PuppetStates.txt", "substate": "PuppetStates.txt",
                  "union": "Unions.txt", "guarantee": "Guarantees.txt"}


class WarError(ValueError):
    """``code``: ``no_name``, ``no_date``, ``no_sides`` (falta atacante o defensor), ``same_side`` (un TAG en los
    dos bandos), ``dates_order`` (el fin no es posterior al inicio), ``file_exists``, ``relation_type``,
    ``relation_same`` o ``relation_exists``."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class WarGoal:
    casus_belli: str
    actor: str
    receiver: str
    state_province_id: int | None = None
    country: str | None = None
    date: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class WarEvent:
    date: str
    action: str                 # uno de WAR_ACTIONS
    tag: str
    line: int | None = None


@dataclass
class WarModel:
    name: str
    events: list[WarEvent] = field(default_factory=list)
    goals: list[WarGoal] = field(default_factory=list)

    @property
    def start(self) -> str | None:
        dates = [e.date for e in self.events]
        return min(dates, key=_date_key) if dates else None

    @property
    def end(self) -> str | None:
        removals = [e.date for e in self.events if e.action.startswith("rem_")]
        return max(removals, key=_date_key) if removals else None

    def side(self, action: str) -> list[str]:
        return list(dict.fromkeys(e.tag for e in self.events if e.action == action))

    @property
    def attackers(self) -> list[str]:
        return self.side("add_attacker")

    @property
    def defenders(self) -> list[str]:
        return self.side("add_defender")

    def participants(self) -> set[str]:
        return {tag.upper() for tag in self.attackers + self.defenders}

    def active_at(self, date: str) -> bool:
        start, end = self.start, self.end
        if start is None:
            return False
        return _date_key(start) <= _date_key(date) and (end is None or _date_key(date) < _date_key(end))


def _parse_date(text) -> ClausewitzDate | None:
    if not isinstance(text, str):
        return None
    try:
        return ClausewitzDate.parse(text.strip())
    except EditError:
        return None


def _date_key(text: str) -> tuple:
    parsed = _parse_date(text)
    return (parsed.year, parsed.month, parsed.day) if parsed is not None else (9999, 99, 99)


def is_date(text: str) -> bool:
    return _parse_date(text) is not None


def read_war(document: Block, fallback_name: str = "") -> WarModel:
    """El ``WarModel`` de un archivo de guerra (no cambia nada)."""
    name = document.get_text("name") or fallback_name
    model = WarModel(name)
    for entry in document.entries:
        if entry.key is None or not isinstance(entry.value, Block) or not is_date(entry.key.text):
            continue
        date = entry.key.text
        for child in entry.value.entries:
            if child.key is None:
                continue
            key = child.key.text.lower()
            if key in WAR_ACTIONS and isinstance(child.value, Scalar):
                model.events.append(WarEvent(date, key, child.value.text, child.line))
            elif key == "war_goal" and isinstance(child.value, Block):
                values = {k: child.value.get_text(k) for k in GOAL_KEYS}
                state = values.get("state_province_id")
                model.goals.append(WarGoal(values.get("casus_belli") or "", values.get("actor") or "",
                                           values.get("receiver") or "",
                                           int(state) if state and state.isdigit() else None,
                                           values.get("country"), date, child.line))
    return model


@dataclass(frozen=True)
class WarSpec:
    """Lo que reúne el asistente «Nueva guerra»: el primero de cada bando es su líder."""

    name: str
    start: str
    attackers: tuple[str, ...]
    defenders: tuple[str, ...]
    goals: tuple[WarGoal, ...] = ()
    end: str | None = None
    file_name: str | None = None


def check_war(spec: WarSpec) -> None:
    if not spec.name.strip():
        raise WarError("no_name")
    if not is_date(spec.start):
        raise WarError("no_date")
    if not spec.attackers or not spec.defenders:
        raise WarError("no_sides")
    both = {t.upper() for t in spec.attackers} & {t.upper() for t in spec.defenders}
    if both:
        raise WarError("same_side", ", ".join(sorted(both)))
    if spec.end is not None and (not is_date(spec.end) or _date_key(spec.end) <= _date_key(spec.start)):
        raise WarError("dates_order", spec.end or "")


def war_rel(spec: WarSpec, prefix: str) -> VPath:
    base = spec.file_name or f"{prefix}_{spec.name}"
    return VPath.of(f"{WARS_FOLDER}/{clean_file_name(base)}.txt")


def war_text(spec: WarSpec) -> bytes:
    lines = [f'name = "{spec.name}"', "", f"{spec.start} = {{"]
    lines += [f"\tadd_attacker = {tag}" for tag in spec.attackers]
    lines += [f"\tadd_defender = {tag}" for tag in spec.defenders]
    for goal in spec.goals:
        lines += ["", "\twar_goal = {", f"\t\tcasus_belli = {goal.casus_belli}", f"\t\tactor = {goal.actor}",
                  f"\t\treceiver = {goal.receiver}"]
        if goal.state_province_id is not None:
            lines.append(f"\t\tstate_province_id = {int(goal.state_province_id)}")
        if goal.country:
            lines.append(f"\t\tcountry = {goal.country}")
        lines.append("\t}")
    lines.append("}")
    if spec.end:
        lines += ["", f"{spec.end} = {{"]
        lines += [f"\trem_attacker = {tag}" for tag in spec.attackers]
        lines += [f"\trem_defender = {tag}" for tag in spec.defenders]
        lines.append("}")
    return ("\r\n".join(lines) + "\r\n").encode(GAME_ENCODING)


def _exists(project: Project, rel: VPath) -> bool:
    handle = project.ws.peek(rel)
    if handle is not None:
        return not handle.deleted
    return project.vfs.resolve(rel) is not None


def _prefix(project: Project) -> str:
    settings = getattr(project, "settings", None)
    return getattr(settings, "prefix", None) or "MOD"


def build_war(project: Project, spec: WarSpec) -> VPath:
    check_war(spec)
    rel = war_rel(spec, _prefix(project))
    if _exists(project, rel):
        raise WarError("file_exists", str(rel))
    handle = project.ws.open(rel, create=True)
    project.ws.replace_text(handle, war_text(spec))
    return rel


def create_war(project: Project, spec: WarSpec) -> VPath:
    with project.ws.transaction(UNDO_NEW_WAR, name=spec.name):
        return build_war(project, spec)


def plan_war(project: Project, spec: WarSpec) -> ChangePlan:
    from .country import dry_run

    check_war(spec)
    return dry_run(project, "new_war", lambda: build_war(project, spec))


# --- diplomacia -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Relation:
    type: str
    first: str
    second: str
    start_date: str | None = None
    end_date: str | None = None
    rel: VPath | None = None
    line: int | None = None
    position: int = 0           # n-ésima entrada de primer nivel del archivo (para quitarla)


def _relation_files(project: Project) -> list[VPath]:
    rels = {}
    for entry in project.vfs.list(DIPLOMACY_FOLDER, "*.txt"):
        rels[entry.rel.key] = entry.rel
    for handle in project.ws.documents():
        if str(handle.rel).lower().startswith(DIPLOMACY_FOLDER + "/") and not handle.deleted:
            rels[handle.rel.key] = handle.rel
    return sorted(rels.values(), key=lambda r: r.key)


def _document(project: Project, rel: VPath):
    handle = project.ws.open(rel)
    return handle, handle.model.document


def relations(project: Project, tag: str | None = None) -> list[Relation]:
    """Todas las relaciones de ``history/diplomacy`` (las de ``tag`` como ``first`` o ``second`` si se da)."""
    found = []
    wanted = tag.upper() if tag else None
    for rel in _relation_files(project):
        try:
            handle, doc = _document(project, rel)
        except (FileNotFoundError, OSError):
            continue
        if handle.deleted:
            continue
        for position, entry in enumerate(doc.entries):
            if entry.key is None or not isinstance(entry.value, Block):
                continue
            kind = entry.key.text.lower()
            if kind not in RELATION_TYPES:
                continue
            block = entry.value
            first, second = block.get_text("first") or "", block.get_text("second") or ""
            if wanted and wanted not in (first.upper(), second.upper()):
                continue
            found.append(Relation(kind, first, second, block.get_text("start_date"), block.get_text("end_date"),
                                  handle.rel, entry.line, position))
    return found


def _quoted_date(text: str | None) -> str | None:
    return None if not text else text


def add_relation(project: Project, kind: str, first: str, second: str, start_date: str,
                 end_date: str | None = None) -> VPath:
    """Añade una relación al final de su archivo (``RELATION_FILES``) en una transacción ``undo.diplomacy_add``."""
    if kind not in RELATION_TYPES:
        raise WarError("relation_type", kind)
    if first.upper() == second.upper():
        raise WarError("relation_same", first)
    for existing in relations(project, first):
        if existing.type == kind and existing.first.upper() == first.upper() \
                and existing.second.upper() == second.upper():
            raise WarError("relation_exists", f"{kind} {first} {second}")
    rel = VPath.of(f"{DIPLOMACY_FOLDER}/{RELATION_FILES[kind]}")
    block = Block()
    block.append("first", Scalar(first))
    block.append("second", Scalar(second))
    block.append("start_date", Scalar(start_date, True))
    if end_date:
        block.append("end_date", Scalar(end_date, True))
    with project.ws.transaction(UNDO_RELATION_ADD, kind=kind, first=first, second=second):
        handle = project.ws.open(rel, create=True)
        project.ws.touch(handle)
        handle.model.document.append(kind, block)
    return rel


def remove_relation(project: Project, relation: Relation) -> None:
    """Quita esa entrada (la de su posición, si sigue siendo la misma relación)."""
    if relation.rel is None:
        raise WarError("relation_type", relation.type)
    with project.ws.transaction(UNDO_RELATION_REMOVE, kind=relation.type, first=relation.first,
                                second=relation.second):
        handle = project.ws.open(relation.rel)
        doc = handle.model.document
        entries = list(doc.entries)
        target = entries[relation.position] if relation.position < len(entries) else None
        ok = (target is not None and target.key is not None and target.key.text.lower() == relation.type
              and isinstance(target.value, Block)
              and (target.value.get_text("first") or "").upper() == relation.first.upper()
              and (target.value.get_text("second") or "").upper() == relation.second.upper())
        if not ok:
            raise WarError("relation_type", relation.type)
        project.ws.touch(handle)
        doc.remove_entry(target)


def wars(project: Project) -> list[tuple[VPath, WarModel]]:
    """Las guerras de la vista efectiva (con lo sin guardar), por nombre de archivo."""
    found = []
    seen = set()
    rels = [entry.rel for entry in project.vfs.list(WARS_FOLDER, "*.txt")]
    rels += [h.rel for h in project.ws.documents() if str(h.rel).lower().startswith(WARS_FOLDER + "/")]
    for rel in rels:
        if rel.key in seen:
            continue
        seen.add(rel.key)
        try:
            handle = project.ws.open(rel)
        except (FileNotFoundError, OSError):
            continue
        if handle.deleted:
            continue
        found.append((handle.rel, read_war(handle.model.document, rel.name.rsplit(".", 1)[0])))
    found.sort(key=lambda item: item[0].name.lower())
    return found


def tags_in(items: Iterable[str]) -> list[str]:
    return [item.strip().upper() for item in items if item and item.strip()]


def leaders(spec: WarSpec) -> tuple[str | None, str | None]:
    return (spec.attackers[0] if spec.attackers else None, spec.defenders[0] if spec.defenders else None)


__all__: Sequence[str] = (
    "WarError", "WarGoal", "WarEvent", "WarModel", "WarSpec", "Relation", "read_war", "war_text", "check_war",
    "build_war", "create_war", "plan_war", "relations", "add_relation", "remove_relation", "wars",
)
