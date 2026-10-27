"""Familia «descriptor»: los campos del ``.mod`` y sus ``replace_path`` (wizard §11, §14.1, §5.3).

Los códigos ``descriptor_*`` son los de ``modcheck.check_descriptor`` (sobre el
descriptor efectivo del contexto, con los cambios sin guardar), más
``descriptor_user_dir_empty``. ``replace_path_empty``: el mod deja vacía una
carpeta reemplazada (el juego se quedaría sin esos archivos).
``replace_path_hides_referenced``: algo sigue nombrando archivos del juego que
``replace_path`` oculta y el mod no trae.
"""

from __future__ import annotations

from ...clausewitz import Severity
from ...modcheck import check_descriptor
from ...modfile import descriptor_from_result
from ...vfs.model import LayerKind
from ...vfs.paths import DESCRIPTOR_REL, VPath, folder_key
from ...index.model import KIND_COUNTRY_FILE, KIND_FILE, KIND_IMAGE
from ..registry import make_problem, rule

E, W = Severity.ERROR, Severity.WARNING
DESCRIPTOR_CODES = {
    "descriptor_no_name": W, "descriptor_no_path": E, "descriptor_bad_path": E, "descriptor_other_folder": E,
    "descriptor_missing_folder": E, "descriptor_bad_user_dir": E, "descriptor_bad_replace_path": E,
    "descriptor_user_dir_empty": W,
}


def _register(fn):
    for code, severity in DESCRIPTOR_CODES.items():
        fn = rule(code, severity)(fn)
    return fn


def descriptor_of(ctx):
    """``ModDescriptor`` efectivo (con los cambios sin guardar) o None si el proyecto no tiene ``.mod``."""
    entry = ctx.entry(DESCRIPTOR_REL)
    result = ctx.parse(DESCRIPTOR_REL)
    if result is None:
        return None
    from pathlib import Path

    path = entry.path if entry is not None else Path("descriptor.mod")
    return descriptor_from_result(path, result)


def _mod_root(ctx):
    return next((layer.root for layer in ctx.snapshot.layers if layer.kind is LayerKind.MOD), None)


@_register
def descriptor_fields(ctx):
    descriptor = descriptor_of(ctx)
    if descriptor is None:
        return []
    root = _mod_root(ctx)
    problems = []
    for issue in check_descriptor(descriptor, mod_dir=root):
        problems.append(make_problem(issue.code, DESCRIPTOR_REL, **issue.args))
    if not (descriptor.user_dir or "").strip():
        problems.append(make_problem("descriptor_user_dir_empty", DESCRIPTOR_REL))
    return problems


def _referenced_targets(ctx) -> list:
    """Archivos que el índice ve nombrados: ``oob``, archivos de país y texturas, como rutas relativas."""
    found = []
    index = ctx.index
    for ref in index.refs(KIND_FILE):
        found.append((ref, ref.name))
    for ref in index.refs(KIND_COUNTRY_FILE):
        found.append((ref, "common/" + ref.name))
    for ref in index.refs(KIND_IMAGE):
        found.append((ref, ref.name))
    return found


@rule("replace_path_empty", E)
@rule("replace_path_hides_referenced", E)
def replace_paths(ctx):
    descriptor = descriptor_of(ctx)
    if descriptor is None or not descriptor.replace_paths:
        return []
    problems = []
    mod_keys = {key for key, stack in ctx.snapshot.entries.items()
                if any(e.layer.kind is LayerKind.MOD for e in stack)}
    mod_keys |= {VPath.of(rel).key for rel in ctx.overrides}
    targets = None
    for raw in descriptor.replace_paths:
        folder = folder_key(raw)
        if not folder:
            continue
        if not any(key.startswith(folder + "/") for key in mod_keys):
            problems.append(make_problem("replace_path_empty", DESCRIPTOR_REL, replace_path=raw))
        if targets is None:
            targets = _referenced_targets(ctx)
        hidden_refs = [ref for ref, target in targets if target.upper().startswith(folder + "/")
                       and ctx.layer_of(VPath.of(target)) is None
                       and any(e.layer.kind is LayerKind.GAME for e in ctx.stack(VPath.of(target)))]
        if hidden_refs:
            first = hidden_refs[0]
            problems.append(make_problem("replace_path_hides_referenced", DESCRIPTOR_REL, replace_path=raw,
                                         count=len(hidden_refs), example=str(first.rel)))
    return problems
