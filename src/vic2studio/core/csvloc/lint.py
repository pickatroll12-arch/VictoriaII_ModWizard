"""Validación de un ``LocalisationFile`` (ver los códigos en ``diagnostics``)."""

from __future__ import annotations

from ..cancel import CancelCheck, raise_if_cancelled
from ..encoding import GAME_ENCODING, GAME_UNREADABLE, UTF8_BOM, UnencodableTextError, encode_text, \
    has_stray_bom, normalize_encoding
from . import diagnostics as d
from .model import END_MARKER, LANGUAGE_COUNT, LAST_DISPLAYED_COLUMN, LocalisationFile, LocRow, RowKind, \
    marker_index

# Filas entre dos consultas a ``cancelled``.
CANCEL_EVERY = 0x1000


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


def _check_columns(row: LocRow, number: int, add) -> None:
    """Diagnósticos de estructura de una fila de datos (ver la gravedad en ``diagnostics``)."""
    fields, key = row.fields, row.key
    marker = marker_index(fields)
    if marker == LANGUAGE_COUNT:
        return
    if marker is None:
        last = next((i for i in range(len(fields) - 1, -1, -1) if fields[i].strip()), None)
        if last is not None and last < LAST_DISPLAYED_COLUMN and fields[last].strip() == END_MARKER:
            # Una «x» sola al final de un idioma visible: al editar se conserva como texto, pero el
            # juego la mostraría así y lo más probable es que sea el marcador fuera de sitio.
            marker = last
    if marker is None:
        languages = min(len(fields), LANGUAGE_COUNT)
        shifted = any(f.strip() for f in fields[LANGUAGE_COUNT:])  # texto donde iría la "x" o después
        found_column = None
    else:
        languages = min(marker, LANGUAGE_COUNT)
        shifted = marker > LANGUAGE_COUNT
        found_column = marker + 1
    if shifted:
        add(d.MISSING_END_MARKER, number, None, key=key, found_column=found_column)
    elif languages < LAST_DISPLAYED_COLUMN:
        add(d.TOO_FEW_COLUMNS, number, None, key=key, count=languages, expected=LANGUAGE_COUNT)
        add(d.MISSING_END_MARKER, number, None, key=key, found_column=found_column)
    else:
        # El juego ve todos sus idiomas: solo faltan columnas que no muestra, o la "x".
        add(d.MISSING_END_MARKER, number, None, severity=d.Severity.INFO, key=key, found_column=found_column,
            count=languages, expected=LANGUAGE_COUNT)


def lint_file(file: LocalisationFile, encoding: str = GAME_ENCODING, *,
              cancelled: CancelCheck = None) -> list[d.CsvDiagnostic]:
    """Diagnósticos de ``file``; ``encoding`` es la codificación en la que se va a guardar.

    Si ``cancelled()`` devuelve True lanza ``core.cancel.Cancelled``.
    """
    path = str(file.path) if file.path is not None else None
    found: list[d.CsvDiagnostic] = []

    def add(code: str, line: int | None, column: int | None = None, **args) -> None:
        found.append(d.make(code, line, column, path, **args))

    target = normalize_encoding(encoding)
    current = normalize_encoding(file.encoding)
    if current in GAME_UNREADABLE:
        add(d.NON_GAME_ENCODING, None, None, severity=d.Severity.ERROR, encoding=current,
            expected=GAME_ENCODING, utf16=True)
    elif current != GAME_ENCODING:
        add(d.NON_GAME_ENCODING, None, None, encoding=current, expected=GAME_ENCODING,
            bom=current == UTF8_BOM)
    elif file.rows and has_stray_bom(file.rows[0].to_line(), current):
        add(d.NON_GAME_ENCODING, 1, 1, encoding=current, expected=GAME_ENCODING, stray_bom=True,
            key=file.rows[0].key)

    first_seen: dict[str, int] = {}
    for number, row in enumerate(file.rows, 1):
        if not number & (CANCEL_EVERY - 1):
            raise_if_cancelled(cancelled)
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
        _check_columns(row, number, add)
        if any('"' in f for f in row.fields):
            for column, position in quoted_semicolons(row.to_line()):
                add(d.SEMICOLON_IN_QUOTES, number, position + 1, key=key, field=column)

    # Por bloques de filas, para poder parar a mitad. Cada fila ocupa una línea salvo que alguien
    # haya metido un salto en sus campos sin pasar por ``set``: se cuentan las líneas de verdad.
    rows, first_line, unencodable = file.rows, 1, False
    for start in range(0, len(rows), CANCEL_EVERY):
        raise_if_cancelled(cancelled)
        chunk = "\n".join(row.to_line() for row in rows[start:start + CANCEL_EVERY])
        try:
            encode_text(chunk, target)
        except UnencodableTextError as exc:
            unencodable = True
            by_line: dict[int, list] = {}
            for problem in exc.problems:
                by_line.setdefault(first_line + problem[1] - 1, []).append(problem)
            for number, problems in by_line.items():
                _, _, column, char = problems[0]
                key = rows[number - 1].key if number <= len(rows) else ""
                add(d.UNENCODABLE_CHARACTER, number, column, key=key, char=char,
                    codepoint=f"{ord(char):04X}", count=len(problems), encoding=target)
        first_line += chunk.count("\n") + 1
    if unencodable:
        found.sort(key=lambda diag: diag.line or 0)
    return found
