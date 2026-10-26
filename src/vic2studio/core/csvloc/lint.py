"""Validación de un ``LocalisationFile`` (ver los códigos en ``diagnostics``)."""

from __future__ import annotations

import codecs

from ..encoding import GAME_ENCODING, UTF8_BOM, UnencodableTextError, encode_text
from . import diagnostics as d
from .model import LANGUAGE_COUNT, LocalisationFile, LocRow, RowKind, marker_index


def is_header_row(row: LocRow) -> bool:
    """Cabecera al estilo "key;English;French;..." que algunos mods copian de hojas de cálculo."""
    return (row.kind is RowKind.DATA and row.key.strip().lower() == "key"
            and row.get(1).strip().lower() == "english")


def quoted_semicolons(line: str) -> list[tuple[int, int]]:
    """(columna CSV, posición) de cada campo entre comillas, al estilo CSV, que encierra un ";".

    Solo cuenta comillas que abren al principio de un campo y cierran justo antes
    de un ";" o del final de la línea; las comillas sueltas o sin cerrar no
    cambian nada en el juego y se ignoran.
    """
    found = []
    column, start, size = 0, 0, len(line)
    while start < size:
        if line[start] == '"':
            close, scan = -1, start + 1
            while scan < size:
                if line[scan] == '"':
                    if scan + 1 < size and line[scan + 1] == '"':
                        scan += 2
                        continue
                    close = scan
                    break
                scan += 1
            if close >= 0 and (close + 1 == size or line[close + 1] == ";"):
                inner = line.count(";", start, close)
                if inner:
                    found.append((column, start))
                    column += inner + 1
                    start = close + 2
                    continue
        separator = line.find(";", start)
        if separator < 0:
            break
        column += 1
        start = separator + 1
    return found


def _normalize(encoding: str) -> str:
    return codecs.lookup(encoding).name


def lint_file(file: LocalisationFile, encoding: str = GAME_ENCODING) -> list[d.CsvDiagnostic]:
    """Diagnósticos de ``file``; ``encoding`` es la codificación en la que se va a guardar."""
    path = str(file.path) if file.path is not None else None
    found: list[d.CsvDiagnostic] = []

    def add(code: str, line: int | None, column: int | None = None, **args) -> None:
        found.append(d.make(code, line, column, path, **args))

    target = _normalize(encoding)
    current = _normalize(file.encoding)
    if current != GAME_ENCODING:
        add(d.NON_GAME_ENCODING, None, None, encoding=current, expected=GAME_ENCODING,
            bom=current == UTF8_BOM)

    first_seen: dict[str, int] = {}
    for number, row in enumerate(file.rows, 1):
        if row.kind is not RowKind.DATA:
            continue
        key = row.key
        if not key.strip():
            add(d.EMPTY_KEY, number, 1, key=key)
            continue
        if key != key.strip():
            add(d.KEY_WHITESPACE, number, 1, key=key)
        previous = first_seen.get(key)
        if previous is None:
            first_seen[key] = number
        else:
            add(d.DUPLICATE_KEY, number, 1, key=key, first_line=previous)
        if is_header_row(row):
            add(d.HEADER_ROW, number, 1, key=key)
            continue
        fields = row.fields
        marker = marker_index(fields)
        languages = marker if marker is not None else len(fields)
        if languages < LANGUAGE_COUNT:
            add(d.TOO_FEW_COLUMNS, number, None, key=key, count=languages, expected=LANGUAGE_COUNT)
        if marker != LANGUAGE_COUNT:
            add(d.MISSING_END_MARKER, number, None, key=key,
                found_column=marker + 1 if marker is not None else None)
        if any('"' in f for f in fields):
            for column, position in quoted_semicolons(row.to_line()):
                add(d.SEMICOLON_IN_QUOTES, number, position + 1, key=key, field=column)

    try:
        encode_text(file.to_source(), target)
    except UnencodableTextError as exc:
        # Cada fila ocupa exactamente una línea de ``to_source``.
        by_line: dict[int, list] = {}
        for problem in exc.problems:
            by_line.setdefault(problem[1], []).append(problem)
        for number, problems in by_line.items():
            _, _, column, char = problems[0]
            row = file.rows[number - 1]
            add(d.UNENCODABLE_CHARACTER, number, column, key=row.key, char=char,
                codepoint=f"{ord(char):04X}", count=len(problems), encoding=target)
        found.sort(key=lambda diag: diag.line or 0)
    return found
