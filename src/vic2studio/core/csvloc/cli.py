"""Línea de órdenes: ``python -m vic2studio.core.csvloc {check,tojson,fromjson} ...``.

Códigos de salida de ``check``: 0 sin errores, 1 con errores (o con avisos si
se pasa ``--strict``), 2 si alguna ruta no se pudo leer.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

from .diagnostics import DEFAULT_LANG, MESSAGES, Severity
from .serialization import from_json, read_csv_file, to_json, write_csv_file

_SUMMARY = {
    "en": "{files} file(s): {errors} error(s), {warnings} warning(s), {infos} info",
    "es": "{files} archivo(s): {errors} error(es), {warnings} aviso(s), {infos} info",
}
_NOT_FOUND = {"en": "cannot read {path}: {error}", "es": "no se puede leer {path}: {error}"}


def _csv_paths(raw_paths: Sequence[str]) -> tuple[list[Path], list[tuple[str, str]]]:
    paths, missing = [], []
    for raw in raw_paths:
        path = Path(raw)
        if path.is_dir():
            paths.extend(sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".csv"))
        elif path.is_file():
            paths.append(path)
        else:
            missing.append((raw, "not found" if not path.exists() else "not a file"))
    return paths, missing


def _write_out(text: str, output: str | None) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8", newline="")
        return
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
    else:
        sys.stdout.flush()
        buffer.write(text.encode("utf-8"))
        buffer.flush()


def _check(args: argparse.Namespace) -> int:
    lang = args.lang
    paths, missing = _csv_paths(args.paths)
    status = 0
    for raw, error in missing:
        print(_NOT_FOUND[lang].format(path=raw, error=error), file=sys.stderr)
        status = 2
    severities: Counter = Counter()
    codes: Counter = Counter()
    for path in paths:
        try:
            file = read_csv_file(path)
        except (OSError, UnicodeDecodeError) as exc:
            print(_NOT_FOUND[lang].format(path=path, error=exc), file=sys.stderr)
            status = 2
            continue
        for diag in file.diagnostics:
            severities[diag.severity] += 1
            codes[diag.code] += 1
            if not args.summary:
                print(diag.format(lang))
    if args.summary:
        for code, count in sorted(codes.items(), key=lambda item: (-item[1], item[0])):
            print(f"{count:7d}  {code}")
    print(_SUMMARY[lang].format(files=len(paths), errors=severities[Severity.ERROR],
                                warnings=severities[Severity.WARNING], infos=severities[Severity.INFO]))
    if status:
        return status
    if severities[Severity.ERROR] or (args.strict and severities[Severity.WARNING]):
        return 1
    return 0


def _tojson(args: argparse.Namespace) -> int:
    file = read_csv_file(args.file)
    _write_out(json.dumps(to_json(file), ensure_ascii=False, indent=args.indent) + "\n", args.output)
    return 0


def _fromjson(args: argparse.Namespace) -> int:
    with open(args.file, encoding="utf-8") as handle:
        file = from_json(json.load(handle))
    write_csv_file(args.output, file, backup=not args.no_backup)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m vic2studio.core.csvloc",
                                     description="Herramientas para la localización CSV de Victoria II.")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="valida archivos .csv o carpetas (recursivo)")
    check.add_argument("paths", nargs="+", metavar="RUTA")
    check.add_argument("--lang", choices=sorted(MESSAGES), default=DEFAULT_LANG,
                       help="idioma de los mensajes")
    check.add_argument("--summary", action="store_true", help="solo cuenta los diagnósticos por código")
    check.add_argument("--strict", action="store_true", help="los avisos también dan código de salida 1")
    check.set_defaults(run=_check)

    tojson = commands.add_parser("tojson", help="convierte un .csv a JSON")
    tojson.add_argument("file", metavar="ARCHIVO")
    tojson.add_argument("-o", "--output", metavar="SALIDA", help="archivo de salida (por defecto stdout)")
    tojson.add_argument("--indent", type=int, default=1)
    tojson.set_defaults(run=_tojson)

    fromjson = commands.add_parser("fromjson", help="escribe un .csv a partir del JSON de tojson")
    fromjson.add_argument("file", metavar="JSON")
    fromjson.add_argument("-o", "--output", metavar="SALIDA", required=True)
    fromjson.add_argument("--no-backup", action="store_true", help="no crear SALIDA.bak si ya existe")
    fromjson.set_defaults(run=_fromjson)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    return args.run(args)
