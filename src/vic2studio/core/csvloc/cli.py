"""Línea de órdenes: ``python -m vic2studio.core.csvloc {check,tojson,fromjson} ...``.

``check`` recorre los archivos y carpetas que se le pasan; en las carpetas solo
analiza los ``.csv`` de localización (``is_localisation_csv``) y los que están
directamente en la carpeta indicada, y cuenta en el resumen los que se saltó
(``map/definition.csv``...). Un archivo indicado explícitamente se analiza siempre.

Códigos de salida: ``check`` da 0 sin errores, 1 con errores (o con avisos si se
pasa ``--strict``) y 2 si alguna ruta no se pudo leer. ``tojson`` y ``fromjson``
dan 0 si todo fue bien, 1 si el texto tiene caracteres que no caben en la
codificación (con su línea y columna) y 2 si no se pudo leer o escribir un
archivo, el JSON no es válido o el archivo de destino cambió mientras tanto.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

from ..encoding import UnencodableTextError
from .diagnostics import DEFAULT_LANG, MESSAGES, Severity
from .model import CSV_SUFFIX, is_localisation_csv
from .serialization import from_json, read_csv_file, to_json, write_csv_file

_SUMMARY = {
    "en": "{files} file(s): {errors} error(s), {warnings} warning(s), {infos} info",
    "es": "{files} archivo(s): {errors} error(es), {warnings} aviso(s), {infos} info",
}
_SKIPPED = {
    "en": "; {count} .csv skipped (not localisation)",
    "es": "; {count} .csv omitido(s) (no son de localización)",
}
_NOT_FOUND = {"en": "cannot read {path}: {error}", "es": "no se puede leer {path}: {error}"}
_MISSING = {"en": "not found", "es": "no existe"}
_NOT_A_FILE = {"en": "not a file", "es": "no es un archivo"}
_CANNOT_WRITE = {"en": "cannot write {path}: {error}", "es": "no se puede escribir {path}: {error}"}
_BAD_JSON = {"en": "{path}: invalid JSON: {error}", "es": "{path}: JSON no válido: {error}"}
_UNENCODABLE = {
    "en": "{path}:{line}:{column}: '{char}' (U+{codepoint}) cannot be saved in {encoding} ({count} character(s) in all)",
    "es": "{path}:{line}:{column}: '{char}' (U+{codepoint}) no se puede guardar en {encoding} ({count} carácter(es) en total)",
}


def _csv_paths(raw_paths: Sequence[str]) -> tuple[list[Path], list[tuple[str, dict[str, str]]], int]:
    """(archivos a analizar, rutas que faltan con su motivo, .csv saltados por no ser de localización)."""
    paths, missing, skipped = [], [], 0
    for raw in raw_paths:
        path = Path(raw)
        if path.is_dir():
            for found in sorted(p for p in path.rglob("*") if p.suffix.lower() == CSV_SUFFIX and p.is_file()):
                if found.parent == path or is_localisation_csv(found):
                    paths.append(found)
                else:
                    skipped += 1
        elif path.is_file():
            paths.append(path)
        else:
            missing.append((raw, _MISSING if not path.exists() else _NOT_A_FILE))
    return paths, missing, skipped


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
    paths, missing, skipped = _csv_paths(args.paths)
    status = 0
    for raw, reason in missing:
        print(_NOT_FOUND[lang].format(path=raw, error=reason[lang]), file=sys.stderr)
        status = 2
    severities: Counter = Counter()
    codes: Counter = Counter()
    for path in paths:
        try:
            file = read_csv_file(path)
        except (OSError, ValueError, LookupError) as exc:
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
    summary = _SUMMARY[lang].format(files=len(paths), errors=severities[Severity.ERROR],
                                    warnings=severities[Severity.WARNING], infos=severities[Severity.INFO])
    print(summary + (_SKIPPED[lang].format(count=skipped) if skipped else ""))
    if status:
        return status
    if severities[Severity.ERROR] or (args.strict and severities[Severity.WARNING]):
        return 1
    return 0


def _fail(template: dict[str, str], lang: str, status: int, **values) -> int:
    print(template[lang].format(**values), file=sys.stderr)
    return status


def _tojson(args: argparse.Namespace) -> int:
    try:
        file = read_csv_file(args.file)
    except (OSError, ValueError, LookupError) as exc:
        return _fail(_NOT_FOUND, args.lang, 2, path=args.file, error=exc)
    try:
        _write_out(json.dumps(to_json(file), ensure_ascii=False, indent=args.indent) + "\n", args.output)
    except OSError as exc:
        return _fail(_CANNOT_WRITE, args.lang, 2, path=args.output or "stdout", error=exc)
    return 0


def _fromjson(args: argparse.Namespace) -> int:
    try:
        with open(args.file, encoding="utf-8") as handle:
            obj = json.load(handle)
    except OSError as exc:
        return _fail(_NOT_FOUND, args.lang, 2, path=args.file, error=exc)
    except ValueError as exc:  # JSON mal formado o no UTF-8
        return _fail(_BAD_JSON, args.lang, 2, path=args.file, error=exc)
    try:
        file = from_json(obj)
    except ValueError as exc:
        return _fail(_BAD_JSON, args.lang, 2, path=args.file, error=exc)
    try:
        write_csv_file(args.output, file, backup=not args.no_backup)
    except UnencodableTextError as exc:
        _, line, column, char = exc.problems[0]
        return _fail(_UNENCODABLE, args.lang, 1, path=args.output, line=line, column=column, char=char,
                     codepoint=f"{ord(char):04X}", encoding=exc.encoding, count=len(exc.problems))
    except OSError as exc:
        return _fail(_CANNOT_WRITE, args.lang, 2, path=args.output, error=exc)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m vic2studio.core.csvloc",
                                     description="Herramientas para la localización CSV de Victoria II.")
    commands = parser.add_subparsers(dest="command", required=True)

    def add_lang(command: argparse.ArgumentParser) -> None:
        command.add_argument("--lang", choices=sorted(MESSAGES), default=DEFAULT_LANG,
                             help="idioma de los mensajes")

    check = commands.add_parser("check", help="valida archivos .csv o carpetas (los .csv de localización)")
    check.add_argument("paths", nargs="+", metavar="RUTA")
    add_lang(check)
    check.add_argument("--summary", action="store_true", help="solo cuenta los diagnósticos por código")
    check.add_argument("--strict", action="store_true", help="los avisos también dan código de salida 1")
    check.set_defaults(run=_check)

    tojson = commands.add_parser("tojson", help="convierte un .csv a JSON")
    tojson.add_argument("file", metavar="ARCHIVO")
    tojson.add_argument("-o", "--output", metavar="SALIDA", help="archivo de salida (por defecto stdout)")
    tojson.add_argument("--indent", type=int, default=1)
    add_lang(tojson)
    tojson.set_defaults(run=_tojson)

    fromjson = commands.add_parser("fromjson", help="escribe un .csv a partir del JSON de tojson")
    fromjson.add_argument("file", metavar="JSON")
    fromjson.add_argument("-o", "--output", metavar="SALIDA", required=True)
    fromjson.add_argument("--no-backup", action="store_true", help="no crear SALIDA.bak si ya existe")
    add_lang(fromjson)
    fromjson.set_defaults(run=_fromjson)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    return args.run(args)
