"""Banco de pruebas de la aplicación entera (wizard §22, criterios 1 y 2 de la iteración 10).

Uso::

    python tools/bench_app.py [carpeta_del_juego]      # por defecto, $VIC2_GAME

Abre la ventana de verdad (Qt sin pantalla) con el juego dado y un mod vacío en una carpeta temporal; nada se
escribe en el juego, y las preferencias, los datos y las cachés van a esa carpeta temporal. Cada medida corre en un
proceso nuevo, para que la memoria y las cachés de Python no se mezclen:

- **abrir el mod con el índice en frío** (caché vacía): de elegir el mod a ``index_state() == "ready"``, con los
  textos y las reglas que se cargan a la vez (objetivo: < 6 s);
- **índice en caliente**: solo ``build_index`` con la caché de la pasada anterior, en un proceso nuevo (objetivo:
  < 1 s); abrir el mod entero en caliente se enseña aparte, sin objetivo;
- **arranque con el índice en caché**: del proceso nuevo a la ventana con el proyecto abierto y el índice listo
  (objetivo: ≤ 3 s);
- **memoria con el mapa abierto**: la memoria residente del proceso con Mapa › Mundo mostrando el mapa del juego,
  con el ráster y los hechos ya calculados (objetivo: < 600 MB). Se lee de ``/proc/self/status`` (Linux); en otros
  sistemas no se mide.

Sale con código 1 si algún objetivo no se cumple.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"index_cold": 6.0, "index_warm": 1.0, "startup": 3.0, "rss_mb": 600.0}
WAIT_S = 300.0


def _rss_mb() -> float | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    except OSError:
        return None
    return None


def child(game: Path, mod: Path, with_map: bool) -> dict:
    """Corre en el proceso hijo: abre la ventana, el proyecto y (si se pide) el mapa; devuelve las medidas."""
    born = time.perf_counter()
    sys.path.insert(0, str(ROOT / "src"))
    from PySide6.QtCore import QCoreApplication, QEventLoop

    from vic2studio.app import create_application
    from vic2studio.ui.main_window import MainWindow

    app = create_application([])

    def wait(predicate) -> bool:
        limit = time.perf_counter() + WAIT_S
        while time.perf_counter() < limit:
            if predicate():
                return True
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            time.sleep(0.005)
        return False

    window = MainWindow()
    window.show()
    page = window.page("project")
    opened = time.perf_counter()
    page.set_game_path(game)
    page.set_mod_path(mod)
    session = window.session
    ok = wait(lambda: session.project is not None and session.index_state() == "ready")
    ready = time.perf_counter()
    out = {"ok": ok, "startup": ready - born, "index": ready - opened}
    if with_map and ok:
        window.show_page("map:world")
        maps = session.map
        ok = wait(lambda: maps.raster_state == "ready" and maps.facts is not None)
        for _ in range(10):
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        out.update(ok=ok, map=time.perf_counter() - ready, rss_mb=_rss_mb())
    window.close()
    app.processEvents()
    return out


def _run_child(game: Path, mod: Path, env: dict, with_map: bool) -> dict:
    cmd = [sys.executable, __file__, "--child", str(game), str(mod)] + (["--map"] if with_map else [])
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=WAIT_S * 2)
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError(f"el proceso hijo no devolvió medidas (código {proc.returncode}):\n{proc.stderr[-2000:]}")


def _core_index(game: Path, mod: Path, env: dict) -> float:
    """``build_index`` con la caché que dejaron los procesos hijos, en un proceso nuevo y sin interfaz."""
    code = ("import sys, time; from pathlib import Path; sys.path.insert(0, sys.argv[1]);"
            "from vic2studio.core.project import Project; from vic2studio.core.index import FactsCache, build_index;"
            "p = Project.open(Path(sys.argv[2]), Path(sys.argv[3])); s = p.vfs.snapshot(); t = time.perf_counter();"
            "build_index(s, FactsCache()); print(time.perf_counter() - t); p.close()")
    proc = subprocess.run([sys.executable, "-c", code, str(ROOT / "src"), str(game), str(mod)], env=env,
                          capture_output=True, text=True, timeout=WAIT_S)
    return float(proc.stdout.strip().splitlines()[-1])


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] == "--child":
        print(json.dumps(child(Path(argv[2]), Path(argv[3]), "--map" in argv)), flush=True)
        return 0
    game = Path(argv[1] if len(argv) > 1 else os.environ.get("VIC2_GAME", ""))
    if not (game / "map/provinces.bmp").is_file():
        print("uso: python tools/bench_app.py <carpeta del juego> (o VIC2_GAME)")
        return 2
    scratch = Path(tempfile.mkdtemp(prefix="bench_app_"))
    mod = scratch / "mod" / "Bench"
    mod.mkdir(parents=True)
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    for name in ("VIC2STUDIO_SETTINGS_DIR", "VIC2STUDIO_DATA_DIR", "VIC2STUDIO_CACHE_DIR"):
        env[name] = str(scratch / name)

    failures: list[str] = []

    def report(name: str, value: float, target: float, unit: str = "s") -> None:
        ok = value <= target
        if not ok:
            failures.append(name)
        shown = f"{value:8.2f} s " if unit == "s" else f"{value:8.0f} MB"
        print(f"{name:<34} {shown}  {'OK' if ok else 'POR ENCIMA'} (objetivo {target:g} {unit})")

    cold = _run_child(game, mod, env, with_map=False)
    report("abrir el mod e índice, en frío", cold["index"], TARGETS["index_cold"])
    warm = _run_child(game, mod, env, with_map=False)
    print(f"{'abrir el mod e índice, en caliente':<34} {warm['index']:8.2f} s   (abrir, textos, reglas e índice)")
    report("índice en caliente (solo el índice)", _core_index(game, mod, env), TARGETS["index_warm"])
    report("arranque con el índice en caché", warm["startup"], TARGETS["startup"])
    mapped = _run_child(game, mod, env, with_map=True)
    if mapped.get("rss_mb") is not None:
        report("memoria con el mapa abierto", mapped["rss_mb"], TARGETS["rss_mb"], unit="MB")
        print(f"  (el mapa tardó {mapped['map']:.2f} s en verse con sus hechos)")
    else:
        print("memoria con el mapa abierto          sin medir (solo Linux)")
    if not all(r.get("ok") for r in (cold, warm, mapped)):
        failures.append("alguna espera no terminó")
    print("Todo dentro de objetivo." if not failures else "Fuera de objetivo: " + ", ".join(failures))
    shutil.rmtree(scratch, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
