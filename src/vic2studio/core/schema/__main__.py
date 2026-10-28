"""CLI del motor de esquemas (wizard §10.9), siempre en la salida estándar.

    python -m vic2studio.core.schema list [--lang es]
    python -m vic2studio.core.schema show KIND [--lang es]
    python -m vic2studio.core.schema doc [--lang es] [--kind KIND]
    python -m vic2studio.core.schema check JUEGO [MOD] [--kind KIND] [--lang es]

``check`` valida los registros de la vista efectiva del juego (y del mod) sin abrir un proyecto: escanea las
carpetas, construye el índice en memoria y recorre los esquemas sobre bytes (``schema_problems``). No escribe
nada (I4) y sale con 1 si hay algún error que no sea heredado. ``doc`` escribe la referencia en la salida
estándar; ``tools/gen_reference.py`` la guarda en ``docs/referencia/``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..texts import text
from .registry import registry


def _kinds(kind: str | None, lang: str):
    if kind is None:
        return list(registry.all_schemas())
    try:
        return [registry.get(kind)]
    except KeyError:
        print(text("schema.cli.unknown_kind", lang, kind=kind), file=sys.stderr)
        raise SystemExit(2) from None


def _list(args) -> int:
    for schema in sorted(registry.all_schemas(), key=lambda s: s.kind):
        where = f"{schema.hall}:{schema.section}" if schema.hall and schema.section and schema.editable else "-"
        print(f"{schema.kind}\t{text(f'schema.{schema.kind}.title', args.lang)}\t{where}")
    return 0


def _show(args) -> int:
    from .docgen import render

    (schema,) = _kinds(args.kind, args.lang)
    sys.stdout.write(render(schema, args.lang))
    return 0


def _doc(args) -> int:
    from .docgen import render, render_index

    # Una línea en blanco separa el índice y cada esquema; con --kind no hay índice y la salida empieza por el
    # título, igual que su página de docs/referencia.
    parts = [render_index(args.lang)] if args.kind is None else []
    parts.extend(render(schema, args.lang) for schema in _kinds(args.kind, args.lang))
    sys.stdout.write("\n".join(parts))
    return 0


def _check(args) -> int:
    from ..clausewitz import Severity
    from ..index.builder import build_index
    from ..validate import build_context
    from ..vfs import VirtualFS
    from .validate import schema_problems

    game = Path(args.game)
    mod = Path(args.mod) if args.mod else None
    vfs = VirtualFS(game if mod is not None else None, mod if mod is not None else game)
    vfs.scan()
    snapshot = vfs.snapshot()
    index = build_index(snapshot, None, {})
    context = build_context(snapshot, index, {})
    wanted = {schema.kind for schema in _kinds(args.kind, args.lang)}
    problems = [p for p in schema_problems(context) if p.entity is None or p.entity[0] in wanted]
    errors = warnings = 0
    for problem in problems:
        if problem.inherited and mod is not None:
            continue
        if problem.severity is Severity.ERROR:
            errors += 1
        elif problem.severity is Severity.WARNING:
            warnings += 1
        where = f"{problem.rel}:{problem.line or 0}"
        print(f"{where}: {problem.severity.name.lower()}: {problem.code}: {problem.message(args.lang)}")
    records = 0
    for schema in registry.all_schemas():
        if schema.kind not in wanted or not schema.editable:
            continue
        for rel in schema.layout.context_rels(context):
            parsed = context.parse(rel)
            if parsed is not None:
                records += sum(1 for _ in schema.layout.entries(parsed.document, rel))
    print(text("schema.cli.checked", args.lang, records=records, kinds=len(wanted), errors=errors,
               warnings=warnings))
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m vic2studio.core.schema")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "show", "doc", "check"):
        command = commands.add_parser(name)
        command.add_argument("--lang", default="es", choices=("es", "en"))
        if name == "show":
            command.add_argument("kind")
        elif name in ("doc", "check"):
            command.add_argument("--kind")
        if name == "check":
            command.add_argument("game")
            command.add_argument("mod", nargs="?")
    args = parser.parse_args(argv)
    handler = {"list": _list, "show": _show, "doc": _doc, "check": _check}[args.command]
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
