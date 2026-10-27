"""Localización: cada fila con clave de ``localisation/*.csv`` define un ``loc_key`` (wizard §7, §8).

Gana la primera definición por orden de carga (archivos por nombre, filas en
orden), igual que ``csvloc.LocalisationDB``: el índice ordena por ruta y línea.
Los textos no se copian al índice: se leen de la ``LocalisationDB`` efectiva.
La cabecera ``key;English;…`` que algunos mods copian de una hoja de cálculo (la
que el lint señala con ``header_row``) no es una clave: no se define (si no,
salía como ``loc_key_orphan``).
"""

from __future__ import annotations

from ...csvloc.lint import is_header_row
from ...csvloc.model import RowKind
from ...csvloc.serialization import parse_csv
from ...encoding import decode_bytes
from ..model import KIND_LOC_KEY, extractor
from ._support import Facts


@extractor("localisation/*.csv", version=2)
def loc_keys(rel, data, layer):
    facts = Facts(rel, layer)
    decoded = decode_bytes(data)
    file = parse_csv(decoded.text, encoding=decoded.encoding)
    data_kind = RowKind.DATA
    for row in file.rows:
        if row.kind is data_kind and row.key:
            if is_header_row(row):
                continue
            facts.define(KIND_LOC_KEY, row.key, row.line)
    return facts.result()
