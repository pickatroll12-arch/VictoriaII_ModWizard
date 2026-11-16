"""Banco de pruebas del taller de mapas (wizard §18.12, iteración 9a).

Uso::

    python tools/bench_mapforge.py [carpeta_del_juego] [--seeds 3]     # el juego, por defecto $VIC2_GAME

Con 5616×2160 y las cifras de vanilla (unas 60 000 celdas), en el proceso trabajador real, mide:

- la vista previa completa (todas las etapas de celdas y el ráster a W/4), una vez por semilla (≤ 3 s);
- el bloqueo del proceso que espera (un hilo que late cada 10 ms mientras el trabajador calcula, ≤ 100 ms);
- el render final en memoria (ráster a escala 1 con texturas, ≤ 25 s);
- el pico de memoria del trabajador (``VmHWM`` de ``/proc``, solo en Linux, ≤ 1,2 GiB);
- regenerar un paso de mundo (economía y nombres, ≤ 0,5 s);
- un trazo del pincel de relieve hasta la vista previa. **En la 9a el pincel regenera desde el relieve** (todas
  las etapas de celdas y el ráster a W/4): el criterio de 50 ms del diseño es el de un repintado local, que llega
  más adelante; aquí se mide e informa sin contar como fallo;
- con un juego: el perfil de la instalación (≤ 8 s) y la importación de sus bitmaps (``provinces.bmp``,
  ``terrain.bmp`` y ``rivers.bmp`` con ``definition.csv`` y ``default.map``) reconstruyendo lo que falta (≤ 10 s).

El JSON de FMG no se importa todavía (iteración 9b): no se mide. Nada se escribe en el juego.
Sale con código 1 si algún criterio no se cumple.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TARGETS = {"preview": 3.0, "block": 0.100, "final": 25.0, "rss_mib": 1228.8, "step": 0.5, "install": 8.0,
           "import": 10.0}


class Ticker:
    """Un hilo que late cada 10 ms: el mayor hueco entre latidos es lo que se bloquea quien espera."""

    def __init__(self) -> None:
        self.worst = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        last = time.perf_counter()
        while not self._stop.wait(0.010):
            now = time.perf_counter()
            self.worst = max(self.worst, now - last - 0.010)
            last = now

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join()


def _peak_rss_mib(pid: int) -> float | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024
    except OSError:
        return None
    return None


def _game_source(game: Path):
    """``PathSource`` de una carpeta del juego, sin VFS: lo que lee el perfil de la instalación."""
    from vic2studio.core.mapforge.install import FOLDERS, MAP_FILES, PathSource

    src = PathSource()
    wanted = {rel.lower(): rel for rel in MAP_FILES}
    for path in game.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(game).as_posix()
        key = rel.lower()
        if key in wanted or (any(key.startswith(f.lower().rstrip("/") + "/") for f in FOLDERS)
                             and key.endswith(".txt")):
            src.files[key] = str(path)
            src.names[key] = wanted.get(key, rel)
    return src


def _row(results: list, name: str, seconds: float, target: float | None, *, unit: str = "s",
         informative: bool = False) -> None:
    ok = None if target is None or informative else seconds <= target
    results.append((name, seconds, target, unit, ok))
    mark = "—" if ok is None else ("OK" if ok else "FALLA")
    limit = f"≤ {target:g} {unit}" if target is not None else ""
    print(f"  {name:<46} {seconds:>9.3f} {unit:<4} {limit:<14} {mark}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Banco de pruebas del taller de mapas")
    parser.add_argument("game", nargs="?", default=os.environ.get("VIC2_GAME", ""))
    parser.add_argument("--seeds", type=int, default=3)
    args = parser.parse_args(argv[1:])

    from vic2studio.core.mapforge import edits as edit_ops
    from vic2studio.core.mapforge import pipeline
    from vic2studio.core.mapforge.params import ForgeParams
    from vic2studio.core.mapforge.worker import ForgeCommand, ForgeWorker

    game = Path(args.game) if args.game else None
    install = None
    results: list = []
    print("Taller de mapas: 5616×2160, cifras de vanilla")
    if game is not None and (game / "map/provinces.bmp").is_file():
        from vic2studio.core.mapforge.install import learn_install

        src = _game_source(game)
        t = time.perf_counter()
        install = learn_install(src)
        _row(results, "perfil de la instalación", time.perf_counter() - t, TARGETS["install"])

    worker = ForgeWorker()
    worker.start()
    try:
        worker.submit(ForgeCommand("ping", {"value": 0})).result(120)
        world = None
        for seed in range(1, args.seeds + 1):
            params = ForgeParams(size=(5616, 2160), seed=seed)
            with Ticker() as ticker:
                t = time.perf_counter()
                reply = worker.submit(ForgeCommand("run_all", {"params": params, "install": install, "scale": 4,
                                                               "with_textures": False})).result(600)
                seconds = time.perf_counter() - t
            cells = len(reply.world.cells.pts)
            _row(results, f"vista previa W/4, semilla {seed} ({cells} celdas)", seconds, TARGETS["preview"])
            _row(results, f"  bloqueo de quien espera, semilla {seed}", ticker.worst, TARGETS["block"])
            world = world or reply.world
        with Ticker() as ticker:
            t = time.perf_counter()
            final = worker.submit(ForgeCommand("run_raster", {"world": world, "scale": 1})).result(900)
            _row(results, "render final 5616×2160 en memoria", time.perf_counter() - t, TARGETS["final"])
        _row(results, "  bloqueo de quien espera (final)", ticker.worst, TARGETS["block"])
        del final
        rss = _peak_rss_mib(worker._proc.pid) if worker._proc is not None else None
        if rss is not None:
            _row(results, "pico de memoria del trabajador", rss, TARGETS["rss_mib"], unit="MiB")
        t = time.perf_counter()
        pipeline.run_cells(world, from_step="economy")
        _row(results, "regenerar economía y nombres (en proceso)", time.perf_counter() - t, TARGETS["step"])
        stroke = edit_ops.make("relief_stroke", {"tool": "raise", "pts_norm": [[0.4, 0.5], [0.45, 0.5]],
                                                 "r_norm": 0.03, "strength": 0.5})
        edited = edit_ops.add(world, stroke)
        t = time.perf_counter()
        w2 = worker.submit(ForgeCommand("run_cells", {"world": edited, "from_step": "relief"})).result(600).world
        worker.submit(ForgeCommand("run_raster", {"world": w2, "scale": 4, "with_textures": False})).result(600)
        _row(results, "pincel: regenerar desde relieve + W/4", time.perf_counter() - t, 0.050, informative=True)
        if game is not None and (game / "map/provinces.bmp").is_file():
            from vic2studio.core.mapforge.imports.bitmaps import ImportSet

            files = {"provinces": game / "map/provinces.bmp", "terrain": game / "map/terrain.bmp",
                     "rivers": game / "map/rivers.bmp", "definition": game / "map/definition.csv",
                     "default_map": game / "map/default.map"}
            files = {slot: str(p) for slot, p in files.items() if p.is_file()}
            t = time.perf_counter()
            reply = worker.submit(ForgeCommand("import_bitmaps", {
                "files": ImportSet(files), "install": install, "build": True,
                "params": ForgeParams(size=(5616, 2160), seed=1)})).result(900)
            seconds = time.perf_counter() - t
            built = reply.world is not None
            _row(results, f"importar los bitmaps del juego ({'construido' if built else 'sin construir'})",
                 seconds, TARGETS["import"])
    finally:
        worker.close()
    failed = [r for r in results if r[4] is False]
    summary = f"\n{len(results) - len(failed)} de {len(results)} sin fallo"
    if failed:
        summary += "; fallan: " + ", ".join(r[0].strip() for r in failed)
    print(summary)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
