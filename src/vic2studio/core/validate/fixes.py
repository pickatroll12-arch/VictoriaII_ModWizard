"""Arreglos de un clic (SimpleFix, wizard §11.1), con plan de cambios previo y confirmación.

Cada arreglo es un ``FixSpec`` registrado en ``FIXES`` con ``register_fix``.
``apply`` trabaja sobre el ``Project`` en el hilo de la interfaz, dentro de una
transacción con nombre (``undo.fix_<clave>``): deshacible en un paso, y no escribe
en disco hasta que el usuario guarda. ``plan`` calcula el mismo cambio sin
dejarlo aplicado (por ejemplo en una transacción que se revierte) y devuelve el
diff. Catálogo de la iteración 3: ``register_tag``, ``convert_to_cp1252``,
``add_closing_brace``, ``restore_vanilla_loc_rows`` y ``trash_identical_copies``.

Cómo se hace aquí: cada arreglo calcula, a partir de los bytes efectivos del
archivo (el documento abierto si lo hay; si no, el ganador de la VFS), los bytes
nuevos. ``plan`` solo los compara (no abre documentos ni toca la pila de deshacer:
el proyecto queda exactamente igual) y ``apply`` los pone con
``Workspace.replace_text`` (o ``delete`` para la papelera) en una sola
transacción. Como plan y apply usan el mismo cálculo, el diff del plan es
exactamente lo que hará el arreglo. Un arreglo que no se puede aplicar lanza
``FixError`` (con código y mensaje ES/EN en ``fix_error.<código>``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..clausewitz.diagnostics import ENCODING_CODES, Severity
from ..clausewitz.nodes import Scalar
from ..encoding import (
    GAME_ENCODING,
    STRAY_BOM,
    UnencodableTextError,
    decode_bytes,
    encode_text,
    match_bom,
    split_bom,
    split_extra_boms,
)
from ..vfs.model import LayerKind
from ..vfs.paths import VPath
from .model import (
    ACTION_COPY_FROM_GAME,
    ACTION_CREATE,
    ACTION_MODIFY,
    ACTION_TRASH,
    ChangePlan,
    FixSpec,
    PlannedChange,
    Problem,
)

if TYPE_CHECKING:
    from ..project import Project

FIXES: dict[str, FixSpec] = {}
# Arreglos que preparan su cambio una vez: ``(plan, aplicar)``. apply_fix lo usa para comparar con el plan que vio
# el usuario y aplicar justo eso, sin volver a calcularlo (la papelera de VSM compara 8462 archivos cada vez).
_PREPARE: dict[str, Callable[[Problem, Project], tuple[ChangePlan, Callable[[], None]]]] = {}

COUNTRIES_REL = VPath.of("common/countries.txt")
# Códigos de FixError (textos «fix_error.<código>»).
FIX_NOT_APPLICABLE = "not_applicable"
FIX_ALREADY_REGISTERED = "already_registered"
FIX_UNENCODABLE = "unencodable"
FIX_NOTHING_TO_DO = "nothing_to_do"
FIX_NO_GAME_FILE = "no_game_file"
FIX_MISSING_FILE = "missing_file"
FIX_READ_ONLY = "read_only"
FIX_PLAN_CHANGED = "plan_changed"
FIX_SYNTAX_ERRORS = "syntax_errors"
FIX_DESCRIPTOR_CHANGED = "descriptor_changed"
FIX_STILL_UTF8 = "still_utf8"
FIX_NO_COUNTRY_FILE = "no_country_file"


class FixError(ValueError):
    """El arreglo no se puede aplicar ahora (el archivo cambió, ya está arreglado…). No se cambia nada."""

    def __init__(self, code: str, **params) -> None:
        self.code = code
        self.params = params
        super().__init__(self.message("es"))

    def __reduce__(self):
        return (_fix_error, (self.code, self.params))

    def message(self, lang: str = "en") -> str:
        from ..texts import text

        return text(f"fix_error.{self.code}", lang, **self.params)


def _fix_error(code: str, params: dict) -> FixError:
    return FixError(code, **params)


def register_fix(spec: FixSpec) -> FixSpec:
    if spec.key in FIXES:
        raise ValueError(f"arreglo repetido: {spec.key}")
    FIXES[spec.key] = spec
    return spec


def fixes_for(problem: Problem) -> list[FixSpec]:
    """Los arreglos de ``problem`` en su orden (el primero es el SimpleFix) que estén registrados."""
    return [FIXES[key] for key in problem.fixes if key in FIXES]


def plan_fix(key: str, problem: Problem, project: Project) -> ChangePlan:
    """Vista previa sin cambiar nada (el proyecto queda exactamente igual, también su pila de deshacer)."""
    return FIXES[key].plan(problem, project)


def apply_fix(key: str, problem: Problem, project: Project, *, expected: ChangePlan | None = None) -> None:
    """Aplica el arreglo en una transacción deshacible; ``KeyError`` si la clave no existe.

    ``expected``: el plan que vio el usuario. Si el arreglo ya no haría eso (el archivo cambió entre medias),
    ``FixError(plan_changed)`` y no se cambia nada. En un proyecto de solo lectura, ``FixError(read_only)``.
    """
    if project.ws.read_only:
        raise FixError(FIX_READ_ONLY)
    spec = FIXES[key]
    prepare = _PREPARE.get(key)
    if prepare is None:
        if expected is not None and spec.plan(problem, project).changes != expected.changes:
            raise FixError(FIX_PLAN_CHANGED)
        spec.apply(problem, project)
        return
    plan, run = prepare(problem, project)
    if expected is not None and plan.changes != expected.changes:
        raise FixError(FIX_PLAN_CHANGED)
    run()


# --- base común: bytes efectivos → bytes nuevos ------------------------------------------------------


@dataclass(frozen=True)
class Current:
    """Estado efectivo de un archivo para un arreglo."""

    rel: VPath
    data: bytes | None              # None: no existe
    layer: LayerKind | None         # capa de la que viene (MOD para un documento nuevo o del mod)
    encoding: str
    new: bool = False               # documento nuevo sin guardar (no existe en disco)


@dataclass(frozen=True)
class Edit:
    rel: VPath
    before: Current
    after: bytes | None             # None: a la papelera


def current(project: Project, rel: VPath) -> Current:
    """Bytes efectivos de ``rel``: el documento abierto (con sus cambios) o el ganador de la VFS. No abre nada."""
    from ..project.codecs import codec_for

    rel = VPath.of(rel)
    handle = project.ws.peek(rel)
    if handle is not None and not handle.deleted:
        data = codec_for(handle.kind).snapshot(handle.model)
        layer = LayerKind.MOD if handle.origin is None else handle.origin.layer.kind
        return Current(handle.rel, data, layer, getattr(handle.model, "encoding", None) or GAME_ENCODING,
                       handle.is_new)
    entry = project.vfs.resolve(rel)
    if handle is not None and handle.deleted:
        # Lápida de la copia del mod: lo efectivo es lo que gana debajo (el juego o una dependencia), si lo hay.
        entry = _below_mod(project.vfs.stack(rel), project.vfs.snapshot().hidden, rel)
        if entry is None:
            return Current(handle.rel, None, None, GAME_ENCODING)
    if entry is None:
        return Current(rel, None, None, GAME_ENCODING)
    try:
        data = entry.path.read_bytes()
    except OSError:
        data = None
    return Current(entry.rel, data, entry.layer.kind, decode_bytes(data).encoding if data else GAME_ENCODING)


def _below_mod(stack, hidden, rel: VPath):
    """La entrada que carga el juego sin la del mod: la primera que no es del mod, salvo un archivo del juego que
    ``replace_path`` oculta."""
    key = VPath.of(rel).key
    return next((e for e in stack if e.layer.kind is not LayerKind.MOD
                 and not (key in hidden and e.layer.kind is LayerKind.GAME)), None)


def _action(edit: Edit) -> str:
    if edit.after is None:
        return ACTION_TRASH
    if edit.before.data is None or edit.before.new:
        return ACTION_CREATE
    return ACTION_MODIFY if edit.before.layer is LayerKind.MOD else ACTION_COPY_FROM_GAME


def make_plan(key: str, edits: list[Edit]) -> ChangePlan:
    from ..project.diffing import counted_diff

    changes = []
    for edit in edits:
        action = _action(edit)
        if action == ACTION_TRASH:
            changes.append(PlannedChange(edit.rel, action))
            continue
        encoding = edit.before.encoding if edit.before.data is not None else GAME_ENCODING
        try:
            diff, lines = counted_diff(edit.rel, edit.before.data, edit.after, encoding=encoding)
        except (LookupError, ValueError):
            diff, lines = counted_diff(edit.rel, edit.before.data, edit.after)
        changes.append(PlannedChange(edit.rel, action, diff, lines))
    return ChangePlan(key, tuple(changes))


def run_edits(project: Project, key: str, edits: list[Edit], fmt: dict) -> None:
    """Aplica ``edits`` en una transacción ``undo.fix_<key>`` (si una falla, la transacción no deja nada)."""
    ws = project.ws
    with ws.transaction(f"undo.fix_{key}", **fmt):
        for edit in edits:
            if edit.after is None:
                ws.delete(edit.rel)
            else:
                handle = ws.open(edit.rel, create=True)
                ws.replace_text(handle, edit.after)


def _byte_fix(key: str, label_args: Callable[[Problem], dict], safe: bool,
              compute: Callable[[Problem, Project], list[Edit]]) -> FixSpec:
    def plan(problem: Problem, project: Project) -> ChangePlan:
        return make_plan(key, compute(problem, project))

    def apply(problem: Problem, project: Project) -> None:
        run_edits(project, key, compute(problem, project), dict(label_args(problem)))

    def prepare(problem: Problem, project: Project) -> tuple[ChangePlan, Callable[[], None]]:
        edits = compute(problem, project)
        return make_plan(key, edits), lambda: run_edits(project, key, edits, dict(label_args(problem)))

    _PREPARE[key] = prepare
    return register_fix(FixSpec(key, f"fix.{key}", safe, plan, apply,
                                lambda problem: MappingProxyType(dict(label_args(problem)))))


def _require(state: Current) -> bytes:
    if state.data is None:
        raise FixError(FIX_MISSING_FILE, file=str(state.rel))
    return state.data


def _parse(data: bytes):
    from ..project.codecs import parse_bytes

    return parse_bytes(data)


def _render(result) -> bytes:
    from ..project.codecs import ClausewitzCodec

    return ClausewitzCodec().snapshot(result)


def _file_args(problem: Problem) -> dict:
    return {"file": problem.rel.name if problem.rel is not None else ""}


# --- register_tag (D7, H11) ------------------------------------------------------------------------


def _tag_of(problem: Problem) -> str:
    if problem.entity is not None and problem.entity[0] == "tag":
        return problem.entity[1]
    tag = problem.args.get("tag")
    if not tag:
        raise FixError(FIX_NOT_APPLICABLE)
    return str(tag)


def _effective_name(project: Project, rel: VPath) -> str | None:
    """El nombre con sus mayúsculas de ``rel`` si existe en la vista efectiva (con los documentos sin guardar: uno
    nuevo cuenta, una lápida deja ver lo de debajo); None si no existe. No lee nada."""
    rel = VPath.of(rel)
    handle = project.ws.peek(rel)
    if handle is not None and not handle.deleted:
        return handle.rel.name
    if handle is not None:
        entry = _below_mod(project.vfs.stack(rel), project.vfs.snapshot().hidden, rel)
    else:
        entry = project.vfs.resolve(rel)
    return None if entry is None else entry.rel.name


def country_file_for(project: Project, tag: str) -> str:
    """Valor para ``countries.txt`` (``countries/<Archivo>.txt``): el archivo de país que existe con el nombre de la
    historia del TAG (``SIL - Silesia.txt`` → ``countries/Silesia.txt``) o con el del TAG (``countries/FFF.txt``).

    Si no existe ninguno, ``FixError(no_country_file)``: el juego no carga un país cuyo archivo falta, y registrarlo
    cambiaría ``tag_not_registered`` por ``country_file_missing`` (con las banderas de CSR en VSM pasaba). El archivo
    lo crea el asistente de países (iteración 6) o el usuario."""
    from ..rules.names import country_file_name

    names = []
    for entry in project.vfs.list("history/countries", f"{tag}*.txt"):
        stem = entry.rel.name.rsplit(".", 1)[0]
        if stem[:3].upper() == tag.upper():
            name = stem[3:].strip().lstrip("-").strip()
            if name:
                names.append(country_file_name(name))
            break
    names.append(country_file_name(tag))
    for name in names:
        found = _effective_name(project, VPath.of(f"common/countries/{name}"))
        if found is not None:
            return f"countries/{found}"
    raise FixError(FIX_NO_COUNTRY_FILE, tag=tag, file=f"common/countries/{names[0]}")


def _register_tag(problem: Problem, project: Project) -> list[Edit]:
    tag = _tag_of(problem)
    state = current(project, COUNTRIES_REL)
    result = _parse(_require(state))
    if any(d.severity is Severity.ERROR and d.code not in ENCODING_CODES for d in result.diagnostics):
        # Con un bloque sin cerrar, dynamic_tags queda dentro y la línea iría detrás (D7, H11 lo prohíben).
        raise FixError(FIX_SYNTAX_ERRORS, file=str(state.rel))
    doc = result.document
    if any(e.key is not None and e.key.text == tag for e in doc.entries):
        raise FixError(FIX_ALREADY_REGISTERED, tag=tag)
    value = Scalar(country_file_for(project, tag), True)
    anchor = next((e for e in doc.entries if e.key is not None and e.key.text.lower() == "dynamic_tags"), None)
    if anchor is not None:
        # Justo antes de dynamic_tags, delante de los comentarios que lo preceden (D7, H11).
        doc.insert_before(anchor, tag, value)
    else:
        doc.append(tag, value)
    return [Edit(state.rel, state, _render(result))]


_byte_fix("register_tag", lambda p: {"tag": _tag_of(p)}, True, _register_tag)


# --- convert_to_cp1252 ------------------------------------------------------------------------------


def _convert(problem: Problem, project: Project) -> list[Edit]:
    if problem.rel is None:
        raise FixError(FIX_NOT_APPLICABLE)
    state = current(project, problem.rel)
    data = _require(state)
    decoded = decode_bytes(data)
    text, name = split_bom(decoded.text, match_bom(data, decoded.encoding))
    text, _ = split_extra_boms(text, name)
    if text.startswith(STRAY_BOM):
        text = text[len(STRAY_BOM):]
    try:
        converted = encode_text(text, GAME_ENCODING)
    except UnencodableTextError as exc:
        _, line, column, char = exc.problems[0]
        raise FixError(FIX_UNENCODABLE, file=str(state.rel), line=line, column=column, char=char) from None
    if converted == data:
        raise FixError(FIX_NOTHING_TO_DO)
    if decode_bytes(converted).encoding != GAME_ENCODING:
        # El texto ya estaba codificado dos veces («CafÃ©»): en cp1252 vuelve a ser UTF-8 válido, el juego (y la
        # detección) lo seguirían leyendo como UTF-8 y un segundo clic cambiaría el texto sin plan que lo enseñe.
        raise FixError(FIX_STILL_UTF8, file=str(state.rel))
    return [Edit(state.rel, state, converted)]


_byte_fix("convert_to_cp1252", _file_args, True, _convert)


# --- add_closing_brace (D17) -------------------------------------------------------------------------


def _close_blocks(problem: Problem, project: Project) -> list[Edit]:
    if problem.rel is None:
        raise FixError(FIX_NOT_APPLICABLE)
    state = current(project, problem.rel)
    result = _parse(_require(state))
    unclosed = result.document.unclosed_blocks()
    if not unclosed:
        raise FixError(FIX_NOTHING_TO_DO)
    for block in unclosed:
        block.close()
    return [Edit(state.rel, state, _render(result))]


_byte_fix("add_closing_brace", _file_args, True, _close_blocks)


# --- restore_vanilla_loc_rows (H15) --------------------------------------------------------------------


def _restore_rows(problem: Problem, project: Project) -> list[Edit]:
    from .rules.localisation import degraded_rows

    if problem.rel is None:
        raise FixError(FIX_NOT_APPLICABLE)
    state = current(project, problem.rel)
    data = _require(state)
    game = next((e for e in project.vfs.stack(problem.rel) if e.layer.kind is LayerKind.GAME), None)
    if game is None:
        raise FixError(FIX_NO_GAME_FILE, file=str(problem.rel))
    rows = degraded_rows(data, game.path.read_bytes())
    if not rows:
        raise FixError(FIX_NOTHING_TO_DO)
    decoded = decode_bytes(data)
    lines = decoded.text.split("\n")
    for mod_row, game_row, _ in rows:
        index = mod_row.line - 1
        old = lines[index]
        lines[index] = game_row.raw + ("\r" if old.endswith("\r") else "")
    try:
        restored = encode_text("\n".join(lines), decoded.encoding)
    except UnencodableTextError as exc:
        _, line, column, char = exc.problems[0]
        raise FixError(FIX_UNENCODABLE, file=str(state.rel), line=line, column=column, char=char) from None
    return [Edit(state.rel, state, restored)]


_byte_fix("restore_vanilla_loc_rows", lambda p: {**_file_args(p), "rows": p.args.get("rows", 0)}, True,
          _restore_rows)


# --- trash_identical_copies (decisión del usuario §24.4) ----------------------------------------------


def identical_copies(project: Project) -> list[VPath]:
    """Archivos del mod idénticos a lo que el juego cargaría sin ellos (el archivo del juego o, si hay una en
    medio, el de una dependencia), fuera de las carpetas con ``replace_path`` y sin documento abierto con cambios:
    los que manda a la papelera ``trash_identical_copies``. Compararlos solo con el del juego borraba copias que
    tapan una dependencia distinta (y cambiaba lo que carga el juego)."""
    from ..vfs.paths import DESCRIPTOR_REL

    vfs = project.vfs
    snapshot = vfs.snapshot()
    found = []
    for key in sorted(snapshot.entries):
        if key == DESCRIPTOR_REL.key or key in snapshot.hidden:
            continue
        stack = snapshot.entries[key]
        mod = next((e for e in stack if e.layer.kind is LayerKind.MOD), None)
        below = _below_mod(stack, snapshot.hidden, VPath.of(mod.rel) if mod is not None else key)
        if mod is None or below is None or mod.fingerprint.size != below.fingerprint.size:
            continue
        handle = project.ws.peek(mod.rel)
        if handle is not None and (handle.dirty or handle.deleted):
            continue
        if _same_file(mod.path, below.path):
            found.append(mod.rel)
    return found


def _require_current_replace_paths(project: Project) -> None:
    """``FixError(descriptor_changed)`` si el descriptor (abierto con cambios o guardado) nombra otros
    ``replace_path`` que los de la vista abierta: esta aún no los aplica (se aplican al abrir el proyecto) y la
    papelera se llevaría las copias que un ``replace_path`` nuevo hace imprescindibles."""
    from ..modfile import descriptor_from_result
    from ..vfs.paths import DESCRIPTOR_REL, folder_key

    state = current(project, DESCRIPTOR_REL)
    wanted: set[str] = set()
    if state.data is not None:
        descriptor = descriptor_from_result("descriptor.mod", _parse(state.data))   # solo sus replace_path
        wanted = {key for key in (folder_key(p) for p in descriptor.replace_paths) if key}
    if wanted != set(project.vfs.replace_paths):
        raise FixError(FIX_DESCRIPTOR_CHANGED)


def _same_file(a, b) -> bool:
    try:
        with open(a, "rb") as first, open(b, "rb") as second:
            while True:
                chunk = first.read(1 << 20)
                if chunk != second.read(1 << 20):
                    return False
                if not chunk:
                    return True
    except OSError:
        return False


def _trash_prepare(problem: Problem, project: Project) -> tuple[ChangePlan, Callable[[], None]]:
    _require_current_replace_paths(project)
    rels = identical_copies(project)
    plan = ChangePlan("trash_identical_copies", tuple(PlannedChange(rel, ACTION_TRASH) for rel in rels))

    def run() -> None:
        if not rels:
            raise FixError(FIX_NOTHING_TO_DO)
        with project.ws.transaction("undo.fix_trash_identical_copies", count=len(rels)):
            project.ws.delete_many(rels)

    return plan, run


def _trash_plan(problem: Problem, project: Project) -> ChangePlan:
    return _trash_prepare(problem, project)[0]


def _trash_apply(problem: Problem, project: Project) -> None:
    _trash_prepare(problem, project)[1]()


_PREPARE["trash_identical_copies"] = _trash_prepare
register_fix(FixSpec("trash_identical_copies", "fix.trash_identical_copies", False, _trash_plan, _trash_apply))
