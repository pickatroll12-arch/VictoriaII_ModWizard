"""Familia «localisation»: claves que faltan, sin traducir, huérfanas y copias degradadas (wizard §11, §8, H15).

- ``loc_copy_degraded`` (aviso): un CSV del mod con el nombre de uno del juego (lo
  sustituye entero) cuyas filas solo difieren de las del juego porque las letras
  no ASCII se perdieron como ``?``. En el ``text.csv`` de VSM cada ``?`` sustituye
  a una letra acentuada y a 0–2 caracteres que la siguen (``Efficacité fiscale`` →
  ``Efficacit?fiscale``: el byte cp1252 leído como el inicio de una secuencia
  UTF-8). ``rows`` cuenta las claves cuya fila efectiva está degradada. Arreglo:
  ``restore_vanilla_loc_rows``.
- ``loc_key_missing`` (aviso): claves que el juego busca y no existen: ``TAG`` y
  ``TAG_ADJ`` de cada país registrado, ``PROV<id>`` de cada provincia, títulos y
  descripciones de decisiones (``<id>_title``/``<id>_desc``) y de eventos y sus
  opciones.
- ``loc_untranslated`` (info): claves nuevas del mod (que el juego no tiene) sin
  texto en alguno de los idiomas del proyecto (``ctx.languages``).
- ``loc_key_orphan`` (info): claves nuevas del mod que nada usa (ni una referencia
  ni el nombre de un símbolo con sus sufijos habituales).
"""

from __future__ import annotations

import re

from ...clausewitz import Severity
from ...csvloc.model import RowKind
from ...csvloc.serialization import parse_csv
from ...encoding import decode_bytes
from ...index import model as m
from ...vfs.model import LayerKind
from ..registry import make_problem, rule

W, I = Severity.WARNING, Severity.INFO
_NON_ASCII = "[^\\x00-\\x7f]"
# Un «?» del mod frente a una letra no ASCII del juego y hasta 2 caracteres más (o el mismo «?»).
_DEGRADED_GAP = "(?:\\?|" + _NON_ASCII + "[\\s\\S]{0,2})"
# Sufijos con que el juego deriva claves del nombre de un símbolo.
DERIVED_SUFFIXES = ("", "_desc", "_title", "_ADJ", "_setup", "_short", "_name")


def is_degraded(mod_line: str, game_line: str) -> bool:
    """True si ``mod_line`` es ``game_line`` con letras no ASCII perdidas como ``?`` (y nada más cambia)."""
    if mod_line == game_line or "?" not in mod_line:
        return False
    pattern = _DEGRADED_GAP.join(re.escape(part) for part in mod_line.split("?"))
    return re.fullmatch(pattern, game_line) is not None


def _rows(data: bytes):
    decoded = decode_bytes(data)
    return parse_csv(decoded.text, encoding=decoded.encoding)


def degraded_rows(mod_data: bytes, game_data: bytes) -> list[tuple[object, object, bool]]:
    """``(fila del mod, fila del juego, es_la_primera_de_su_clave)`` de cada fila degradada, en orden de archivo.

    Las filas se emparejan por clave y por orden de aparición (una clave repetida en el mod se compara con la
    misma repetición en el juego).
    """
    game: dict[str, list] = {}
    for row in _rows(game_data).rows:
        if row.kind is RowKind.DATA and row.key:
            game.setdefault(row.key, []).append(row)
    seen: dict[str, int] = {}
    found = []
    for row in _rows(mod_data).rows:
        if row.kind is not RowKind.DATA or not row.key:
            continue
        index = seen.get(row.key, 0)
        seen[row.key] = index + 1
        candidates = game.get(row.key)
        if candidates is None or index >= len(candidates):
            continue
        other = candidates[index]
        if is_degraded(row.raw, other.raw):
            found.append((row, other, index == 0))
    return found


def replaced_game_csvs(ctx):
    """``(rel, entrada del juego)`` de cada CSV del mod (o sin guardar) que sustituye a uno del juego."""
    for rel in ctx.rels("localisation", "*.csv"):
        if ctx.layer_of(rel) is not LayerKind.MOD:
            continue
        game = next((e for e in ctx.stack(rel) if e.layer.kind is LayerKind.GAME), None)
        if game is not None:
            yield rel, game


@rule("loc_copy_degraded", W, fixes=("restore_vanilla_loc_rows",))
def degraded_copies(ctx):
    problems = []
    for rel, game in replaced_game_csvs(ctx):
        mod_data, game_data = ctx.read(rel), ctx.read_entry(game)
        if mod_data is None or game_data is None:
            continue
        rows = degraded_rows(mod_data, game_data)
        effective = sum(1 for _, _, first in rows if first)
        if effective:
            first_row = rows[0][0]
            problems.append(make_problem("loc_copy_degraded", rel, first_row.line, file=rel.name, rows=effective))
    return problems


def _has(loc, key: str) -> bool:
    return loc is not None and key in loc


@rule("loc_key_missing", W)
def missing_keys(ctx):
    index, loc = ctx.index, ctx.loc
    if loc is None or not len(loc):
        return []
    problems = []
    for tag in index.symbols(m.KIND_TAG):
        for key in (tag.name, f"{tag.name}_ADJ"):
            if not _has(loc, key):
                problems.append(make_problem("loc_key_missing", tag.rel, tag.line, entity=(m.KIND_TAG, tag.name),
                                             key=key))
    for kind in (m.KIND_PROVINCE, m.KIND_SEA_PROVINCE):
        for province in index.symbols(kind):
            key = f"PROV{province.name}"
            if not _has(loc, key):
                problems.append(make_problem("loc_key_missing", province.rel, province.line,
                                             entity=(kind, province.name), key=key))
    for ref in index.refs(m.KIND_LOC_KEY):
        if not _has(loc, ref.name):
            problems.append(make_problem("loc_key_missing", ref.rel, ref.line, ref.column,
                                         entity=(m.KIND_LOC_KEY, ref.name), field=(ref.role,), key=ref.name))
    return problems


def mod_only_keys(ctx) -> list:
    """Claves efectivas que solo define el mod (ni el juego ni una dependencia las tienen)."""
    index = ctx.index
    found = []
    for symbol in index.symbols(m.KIND_LOC_KEY):
        if symbol.layer is not LayerKind.MOD:
            continue
        if all(other.layer is LayerKind.MOD for other in index.lookup(m.KIND_LOC_KEY, symbol.name)):
            found.append(symbol)
    return found


@rule("loc_untranslated", I)
def untranslated(ctx):
    loc = ctx.loc
    if loc is None:
        return []
    problems = []
    for symbol in mod_only_keys(ctx):
        row = loc.entry(symbol.name)
        if row is None:
            continue
        missing = [lang for lang in ctx.languages if not (row.get(lang) or "").strip()]
        if missing:
            problems.append(make_problem("loc_untranslated", symbol.rel, symbol.line,
                                         entity=(m.KIND_LOC_KEY, symbol.name), key=symbol.name,
                                         languages=", ".join(missing)))
    return problems


def used_names(index) -> set[str]:
    """Claves que algo usa: referencias explícitas y nombres de símbolos con sus sufijos derivados."""
    used = {ref.name for ref in index.refs(m.KIND_LOC_KEY)}
    for kind in index.kinds():
        if kind in (m.KIND_LOC_KEY, m.KIND_IMAGE, m.KIND_POP_BLOCK):
            continue
        for symbol in index.symbols(kind):
            names = [symbol.name]
            if kind in (m.KIND_PROVINCE, m.KIND_SEA_PROVINCE):
                names = [f"PROV{symbol.name}"]
            elif kind == m.KIND_PARTY:
                names = [str(symbol.attrs.get("party", symbol.name))]
            elif kind == m.KIND_CB and symbol.attrs.get("war_name"):
                war = str(symbol.attrs["war_name"])
                names += [f"NORMAL_{war}", f"AGRESSION_{war}", war]
            for name in names:
                used.update(name + suffix for suffix in DERIVED_SUFFIXES)
    return used


@rule("loc_key_orphan", I)
def orphans(ctx):
    candidates = mod_only_keys(ctx)
    if not candidates:
        return []
    used = used_names(ctx.index)
    return [make_problem("loc_key_orphan", s.rel, s.line, entity=(m.KIND_LOC_KEY, s.name), key=s.name)
            for s in candidates if s.name not in used]
