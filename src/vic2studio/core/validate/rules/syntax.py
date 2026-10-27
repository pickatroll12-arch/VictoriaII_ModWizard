"""Familia «syntax»: lo que hacía ``modcheck.check_file``, sobre los bytes efectivos del contexto (wizard §11).

Revisa los scripts Clausewitz y los CSV de localización que carga el juego (las
carpetas de ``modcheck.GAME_FOLDERS`` y el descriptor ``.mod``), con los
documentos sin guardar. Cada diagnóstico del parser o del lint es un ``Problem``
con su mismo código, su gravedad y su mensaje (``args["source"]``).
"""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

from ...cancel import raise_if_cancelled
from ...clausewitz import CLAUSEWITZ_SUFFIXES, Severity
from ...modcheck import GAME_FOLDERS, KIND_CSV, check_data
from ...vfs.paths import DESCRIPTOR_REL, VPath
from ..model import SOURCE_CLAUSEWITZ, SOURCE_CSV, Problem
from ..registry import RULES, SCOPE_FILE, make_problem, rule

E, W, INFO = Severity.ERROR, Severity.WARNING, Severity.INFO
TO_CP1252 = ("convert_to_cp1252",)

# Diagnósticos del parser Clausewitz (``clausewitz.diagnostics``) y del lint del CSV (``csvloc.lint``).
PARSER_CODES = {
    "unclosed_block": (E, ("add_closing_brace",)), "unexpected_close_brace": (E, ()), "missing_value": (E, ()),
    "missing_key": (E, ()), "unterminated_string": (E, ()), "invalid_key": (E, ()),
    "unexpected_operator": (E, ()), "invalid_character": (E, ()), "multiline_string": (W, ()),
    "control_character": (W, ()), "invisible_character": (W, ()), "non_game_encoding": (W, TO_CP1252),
    "unreadable_encoding": (E, TO_CP1252), "stray_bom": (W, TO_CP1252), "suspicious_close_brace": (INFO, ()),
}
CSV_CODES = {
    "missing_end_marker": (W, ()), "too_few_columns": (W, ()), "duplicate_key": (W, ()), "empty_key": (W, ()),
    "key_whitespace": (W, ()), "semicolon_in_quotes": (W, ()), "unencodable_character": (E, ()),
    "header_row": (INFO, ()),
}
OTHER_CODES = {"read_error": (E, ()), "check_failed": (E, ())}


def checked_rels(ctx) -> list[VPath]:
    """Archivos que revisa la sintaxis: scripts y CSV de localización de las carpetas del juego, y el ``.mod``."""
    found = []
    for rel in ctx.all_rels():
        top = rel.parts[0].casefold() if rel.parts else ""
        if top not in GAME_FOLDERS:
            continue
        suffix = rel.suffix
        if suffix in CLAUSEWITZ_SUFFIXES or (suffix == ".csv" and len(rel.parts) == 2 and top == "localisation"):
            found.append(rel)
    if ctx.layer_of(DESCRIPTOR_REL) is not None:
        found.insert(0, DESCRIPTOR_REL)
    return found


def problems_of(rel: VPath, data: bytes | None, cancelled=None) -> list[Problem]:
    """Los problemas de sintaxis de unos bytes (``read_error`` si no se pudieron leer)."""
    if data is None:
        return [make_problem("read_error", rel, error="")]
    found = []
    for issue in check_data(data, str(rel), cancelled=cancelled):
        code = issue.code if issue.code in RULES else "check_failed"
        args = dict(issue.args)
        if issue.diagnostic is not None:
            args["source"] = SOURCE_CSV if issue.kind == KIND_CSV else SOURCE_CLAUSEWITZ
        # Los argumentos del diagnóstico van tal cual (el lint del CSV usa «field», que make_problem reserva).
        problem = replace(make_problem(code, rel, issue.line, issue.column), args=MappingProxyType(args))
        if problem.severity is not issue.severity:
            problem = replace(problem, severity=issue.severity)
        found.append(problem)
    return found


def _register(fn):
    for code, (severity, fixes) in {**PARSER_CODES, **CSV_CODES, **OTHER_CODES}.items():
        fn = rule(code, severity, scope=SCOPE_FILE, fixes=fixes)(fn)
    return fn


@_register
def syntax(ctx):
    problems: list[Problem] = []
    for rel in checked_rels(ctx):
        if not ctx.wants(rel):
            continue
        raise_if_cancelled(ctx.cancelled)
        problems.extend(problems_of(rel, ctx.read(rel), ctx.cancelled))
    return problems

