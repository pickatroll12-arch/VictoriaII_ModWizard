"""Línea de órdenes del parser Clausewitz.

    python -m vic2studio.core.clausewitz check RUTA... [--lang es|en]
    python -m vic2studio.core.clausewitz tojson ARCHIVO [--comments] [--lang es|en]

``check`` recorre archivos y carpetas e imprime un diagnóstico por línea
(``archivo:línea:columna: severidad: mensaje``); sale con 1 si hay errores.
``tojson`` imprime el árbol como JSON (diagnósticos por stderr).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .diagnostics import Severity
from .json_bridge import to_json
from .parser import parse_file

SUFFIXES = (".txt", ".mod", ".gfx", ".gui", ".sfx", ".asset")

_TEXTS = {
    "es": {
        "unreadable": "{path}: error: no se puede leer: {error}",
        "summary": "{files} archivo(s), {errors} error(es), {warnings} aviso(s)",
    },
    "en": {
        "unreadable": "{path}: error: cannot read: {error}",
        "summary": "{files} file(s), {errors} error(s), {warnings} warning(s)",
    },
}


def _iter_files(paths):
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            yield from sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in SUFFIXES)
        else:
            yield path


def _check(args) -> int:
    texts = _TEXTS[args.lang]
    files = errors = warnings = 0
    for path in _iter_files(args.paths):
        files += 1
        try:
            result = parse_file(path)
        except (OSError, UnicodeError) as exc:
            print(texts["unreadable"].format(path=path, error=exc))
            errors += 1
            continue
        for diagnostic in result.diagnostics:
            print(diagnostic.format(path, args.lang))
            if diagnostic.severity is Severity.ERROR:
                errors += 1
            elif diagnostic.severity is Severity.WARNING:
                warnings += 1
    sys.stdout.flush()
    print(texts["summary"].format(files=files, errors=errors, warnings=warnings), file=sys.stderr)
    return 1 if errors else 0


def _tojson(args) -> int:
    try:
        result = parse_file(args.file)
    except (OSError, UnicodeError) as exc:
        print(_TEXTS[args.lang]["unreadable"].format(path=args.file, error=exc), file=sys.stderr)
        return 1
    for diagnostic in result.diagnostics:
        print(diagnostic.format(args.file, args.lang), file=sys.stderr)
    json.dump(to_json(result.document, include_comments=args.comments), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if result.ok else 1


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(prog="python -m vic2studio.core.clausewitz")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="valida archivos y carpetas")
    check.add_argument("paths", nargs="+", metavar="RUTA")
    check.add_argument("--lang", choices=("es", "en"), default="es")
    check.set_defaults(handler=_check)
    tojson = commands.add_parser("tojson", help="imprime el árbol de un archivo como JSON")
    tojson.add_argument("file", metavar="ARCHIVO")
    tojson.add_argument("--comments", action="store_true", help="incluye los comentarios")
    tojson.add_argument("--lang", choices=("es", "en"), default="es")
    tojson.set_defaults(handler=_tojson)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
