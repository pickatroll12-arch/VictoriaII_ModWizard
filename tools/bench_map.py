"""Banco de pruebas del mapa (wizard §16, criterio 3 de la iteración 5).

Uso::

    python tools/bench_map.py [carpeta_del_juego]      # por defecto, $VIC2_GAME

Mide, sobre el juego dado (nada se escribe en él; la caché va a una carpeta temporal):

- el ráster de ``provinces.bmp`` construido de cero y leído de la caché (objetivo: ≤ 4 s y ≤ 0,5 s);
- los hechos por provincia en la primera fecha de inicio;
- cada modo de mapa: la LUT más la imagen completa con ``numpy.take`` (objetivo: ≤ 150 ms);
- el repintado del lienzo tras cambiar el dueño de una provincia (objetivo: ≤ 50 ms), con Qt sin pantalla.

Sale con código 1 si algún objetivo no se cumple.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TARGETS = {"build": 4.0, "cache": 0.5, "mode": 0.150, "repaint": 0.050}


def _time(function):
    start = time.perf_counter()
    result = function()
    return result, time.perf_counter() - start


def main(argv: list[str]) -> int:
    game = Path(argv[1] if len(argv) > 1 else os.environ.get("VIC2_GAME", ""))
    if not (game / "map/provinces.bmp").is_file():
        print("uso: python tools/bench_map.py <carpeta del juego> (o VIC2_GAME)")
        return 2
    scratch = Path(tempfile.mkdtemp(prefix="bench_map_"))
    for name in ("VIC2STUDIO_CONFIG_DIR", "VIC2STUDIO_DATA_DIR", "VIC2STUDIO_CACHE_DIR"):
        os.environ[name] = str(scratch / name)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    import numpy as np

    from vic2studio.core.index import build_index
    from vic2studio.core.map import cache
    from vic2studio.core.map.bmp import read_bmp
    from vic2studio.core.map.facts import ProvinceFacts, terrain_types
    from vic2studio.core.map.modes import discover_modes
    from vic2studio.core.project import Project
    from vic2studio.core.rules.game import GameRules

    failures = []

    def report(name: str, seconds: float, target: float | None = None) -> None:
        verdict = ""
        if target is not None:
            verdict = "OK" if seconds <= target else f"LENTO (objetivo {target * 1000:.0f} ms)"
            if seconds > target:
                failures.append(name)
        print(f"{name:<28} {seconds * 1000:9.1f} ms  {verdict}")

    bmp = (game / "map/provinces.bmp").read_bytes()
    csv = (game / "map/definition.csv").read_bytes()
    root = scratch / "raster"
    (raster, _hit), seconds = _time(lambda: cache.load_or_build(bmp, csv, root=root))
    report("ráster (de cero)", seconds, TARGETS["build"])
    (_again, hit), seconds = _time(lambda: cache.load_or_build(bmp, csv, root=root))
    report("ráster (caché)", seconds, TARGETS["cache"])
    assert hit, "la segunda carga no salió de la caché"
    print(f"  {raster.width}×{raster.height}, {raster.max_id} ids, {len(raster.unknown)} colores sin fila")

    mod = scratch / "mod"                              # un mod vacío: el juego no se abre para escribir
    mod.mkdir()
    project = Project.open(game, mod)
    snapshot = project.vfs.snapshot()
    index, seconds = _time(lambda: build_index(snapshot, None))
    report("índice", seconds)
    rules = GameRules.from_snapshot(snapshot)
    terrain = read_bmp((game / "map/terrain.bmp").read_bytes())
    majority, seconds = _time(lambda: raster.majority(terrain.pixels))
    report("terreno mayoritario", seconds)
    types = terrain_types((game / "map/terrain.txt").read_bytes())
    date = rules.bookmarks[0] if rules.bookmarks else rules.start_date
    facts, seconds = _time(lambda: ProvinceFacts.build(index, rules, date, size=raster.max_id + 1,
                                                       terrain_majority=majority, terrain_types=types))
    report(f"hechos en {date}", seconds)

    tag = next(iter(facts.tags[1:]), None)
    for mode in discover_modes():
        param = tag if mode.param else None

        def paint(mode=mode, param=param):
            return np.take(mode.lut(facts, index, param=param), raster.ids)

        _image, seconds = _time(paint)
        report(f"modo {mode.key}", seconds, TARGETS["mode"])

    from PySide6.QtWidgets import QApplication

    from vic2studio.ui.map.canvas import MapCanvas

    app = QApplication.instance() or QApplication([])
    canvas = MapCanvas()
    canvas.resize(1200, 800)
    canvas._facts = lambda: facts                     # sin MapSession: los hechos de este banco
    canvas._index = lambda: index
    canvas.set_raster(raster)
    canvas.show()
    app.processEvents()
    pid = int(np.argmax(raster.pixel_count[1:])) + 1
    owner = int(facts.owner[pid])
    facts.owner[pid] = (owner + 1) % max(len(facts.tags), 2)
    facts.generation += 1
    _none, seconds = _time(lambda: (canvas.refresh([pid]), app.processEvents()))
    report(f"repintado tras cambiar {pid}", seconds, TARGETS["repaint"])
    canvas.close()
    project.close(discard=True)

    print("\nTodo dentro de los objetivos." if not failures else f"\nFuera de objetivo: {', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
