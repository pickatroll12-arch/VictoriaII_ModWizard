"""Censo del catálogo de guion sobre un juego instalado (wizard §12.1, criterio 2 de la iteración 7).

Recorre los bloques de guion de ``events/*.txt`` y ``decisions/*.txt`` del juego, construye su ``ScriptTree``
con el catálogo del Studio (resolviendo las familias contra el índice del juego) y cuenta cuántos usos de
claves reconoce el catálogo y cuántos quedan como nodos crudos. Además comprueba la ida y vuelta: serializar
cada archivo después de construir sus árboles da los mismos bytes.

No escribe nada en el juego (I1) y no copia ningún texto de él: solo imprime nombres de claves y recuentos.

Uso::

    python tools/catalog_census.py [RUTA_DEL_JUEGO] [--json salida.json] [--top 40]

Sin ruta usa ``VIC2_GAME``.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.clausewitz import Block, parse, to_source  # noqa: E402
from vic2studio.core.encoding import decode_bytes  # noqa: E402
from vic2studio.core.index.builder import build_index  # noqa: E402
from vic2studio.core.script.catalog import ScriptCatalog  # noqa: E402
from vic2studio.core.script.scopes import Scope, ScriptKind  # noqa: E402
from vic2studio.core.script.tree import ScriptTree  # noqa: E402
from vic2studio.core.vfs.vfs import VirtualFS  # noqa: E402

TRIGGER_BLOCKS = {"trigger": None, "potential": None, "allow": None}
EFFECT_BLOCKS = {"immediate": None, "effect": None}
WEIGHT_BLOCKS = ("mean_time_to_happen", "ai_chance", "ai_will_do")


def script_blocks(item: Block, scope: Scope):
    """``(bloque, tipo, ámbito, skip)`` de cada bloque de guion de un evento o una decisión."""
    for entry in item.entries:
        if entry.key is None or not isinstance(entry.value, Block):
            continue
        key = entry.key.text.lower()
        if key in TRIGGER_BLOCKS:
            yield entry.value, ScriptKind.TRIGGER, scope, ()
        elif key in EFFECT_BLOCKS:
            yield entry.value, ScriptKind.EFFECT, scope, ()
        elif key == "option":
            yield entry.value, ScriptKind.EFFECT, scope, ("name", "ai_chance")
            for sub in entry.value.entries:
                if sub.key is not None and sub.key.text.lower() == "ai_chance" and isinstance(sub.value, Block):
                    yield from weights(sub.value, scope)
        elif key in WEIGHT_BLOCKS:
            yield from weights(entry.value, scope)


def weights(block: Block, scope: Scope):
    for entry in block.entries:
        if entry.key is not None and entry.key.text.lower() == "modifier" and isinstance(entry.value, Block):
            yield entry.value, ScriptKind.TRIGGER, scope, ("factor",)


def items_of(rel_dir: str, document: Block):
    """Eventos (con su ámbito) o decisiones de un archivo."""
    for top in document.entries:
        if top.key is None or not isinstance(top.value, Block):
            continue
        if rel_dir == "events":
            scope = Scope.PROVINCE if top.key.text.lower() == "province_event" else Scope.COUNTRY
            yield top.value, scope
        else:
            for decision in top.value.entries:
                if isinstance(decision.value, Block):
                    yield decision.value, Scope.COUNTRY


def census(game: Path, *, symbols=None) -> dict:
    catalog = ScriptCatalog.load().with_symbols(symbols)
    used = {kind: collections.Counter() for kind in ScriptKind}
    raw = {kind: collections.Counter() for kind in ScriptKind}
    files = round_trip_failures = items = 0
    for rel_dir in ("events", "decisions"):
        for path in sorted((game / rel_dir).glob("*.txt")):
            data = path.read_bytes()
            decoded = decode_bytes(data)
            result = parse(decoded.text)
            files += 1
            for item, scope in items_of(rel_dir, result.document):
                items += 1
                for block, kind, start, skip in script_blocks(item, scope):
                    tree = ScriptTree(block, kind, start, catalog, skip=skip)
                    for node in tree.walk():
                        name = node.key
                        if node.definition is not None and node.definition.family:
                            name = f"<{node.definition.name}>"
                        (raw if node.raw else used)[node.kind][name.lower()] += 1
            if to_source(result.document) != decoded.text:
                round_trip_failures += 1
    report = {"files": files, "items": items, "round_trip_failures": round_trip_failures, "kinds": {}}
    for kind in ScriptKind:
        total = sum(used[kind].values()) + sum(raw[kind].values())
        covered = sum(used[kind].values())
        report["kinds"][kind.value] = {
            "uses": total, "covered": covered, "coverage": covered / total if total else 1.0,
            "distinct": len(set(used[kind]) | set(raw[kind])),
            "raw": raw[kind].most_common(),
        }
    return report


def game_index(game: Path):
    """El índice del juego solo (mod vacío en una carpeta temporal), para las familias del catálogo."""
    with tempfile.TemporaryDirectory(prefix="vic2_census_") as mod:
        vfs = VirtualFS(game, Path(mod))
        vfs.scan()
        return build_index(vfs.snapshot(), None)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("game", nargs="?", default=os.environ.get("VIC2_GAME"))
    parser.add_argument("--json", type=Path)
    parser.add_argument("--top", type=int, default=30)
    args = parser.parse_args(argv)
    if not args.game:
        parser.error("falta la ruta del juego (o VIC2_GAME)")
    game = Path(args.game)
    report = census(game, symbols=game_index(game))
    print(f"{report['files']} archivos, {report['items']} eventos y decisiones; "
          f"ida y vuelta fallida en {report['round_trip_failures']}")
    for kind, data in report["kinds"].items():
        print(f"{kind}: {data['covered']}/{data['uses']} usos reconocidos ({data['coverage']:.1%}), "
              f"{data['distinct']} claves distintas")
        for name, count in data["raw"][:args.top]:
            print(f"    {count:6d}  {name}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
