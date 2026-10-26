"""Capturas automáticas de la ventana principal, sin pantalla (QT_QPA_PLATFORM=offscreen).

Uso:
    python3 tools/screenshot.py --out DIR [--lang es|en|all] [--page all|project|map|...]
                                [--size 1440x900] [--mod RUTA] [--game RUTA]
                                [--open-file RUTA [--line N] [--tab structure|source|diagnostics|json]]
                                [--search TEXTO] [--validate] [--left-tab files|validation]

Genera ``<lang>_<n>_<page>.png``. Usa una carpeta de preferencias temporal, de
modo que nunca lee ni modifica la configuración real del usuario.

``--open-file`` (relativa al mod si no es absoluta) abre un script o una imagen
en la vista previa de «Proyecto y Archivos» y un ``.csv`` en «Localización».
``--validate`` ejecuta «Validar mod» y espera a que termine antes de capturar.
``--search`` escribe en el buscador del visor abierto (estructura o tabla CSV).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def parse_size(text: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in text.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"tamaño inválido: {text!r} (usa ANCHOxALTO)") from None
    return width, height


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path, help="carpeta de salida")
    parser.add_argument("--lang", default="all", help="es, en o all")
    parser.add_argument("--page", default="all", help="all o la clave de una página")
    parser.add_argument("--size", default="1440x900", type=parse_size, help="ANCHOxALTO de la ventana")
    parser.add_argument("--mod", type=Path, help="carpeta del mod a configurar")
    parser.add_argument("--game", type=Path, help="carpeta del juego base a configurar")
    parser.add_argument("--open-file", type=Path, help="archivo a abrir en la vista previa o en Localización")
    parser.add_argument("--line", type=int, help="línea a mostrar del archivo abierto")
    parser.add_argument("--tab", choices=("structure", "source", "diagnostics", "json"),
                        help="pestaña del visor Clausewitz")
    parser.add_argument("--search", help="texto para el buscador del visor abierto")
    parser.add_argument("--validate", action="store_true", help="ejecutar «Validar mod» antes de capturar")
    parser.add_argument("--left-tab", choices=("files", "validation"), help="pestaña del panel izquierdo")
    return parser


def settle(app, window, timeout: float = 60.0, quiet: float = 0.3) -> None:
    """Procesa eventos hasta que ninguna página esté ocupada durante ``quiet`` segundos."""
    from PySide6.QtCore import QEventLoop

    deadline = time.monotonic() + timeout
    quiet_since = None
    while time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        if any(page.is_busy() for page in window.pages):
            quiet_since = None
        elif quiet_since is None:
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since >= quiet:
            return
        time.sleep(0.01)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    settings_dir = tempfile.mkdtemp(prefix="vic2studio-shots-")
    os.environ["VIC2STUDIO_SETTINGS_DIR"] = settings_dir
    try:
        return _run(args)
    finally:
        shutil.rmtree(settings_dir, ignore_errors=True)


def _run(args: argparse.Namespace) -> int:
    from vic2studio.app import create_application

    app = create_application([])

    from vic2studio.i18n import available_languages, set_language
    from vic2studio.ui.main_window import MainWindow
    from vic2studio.ui.pages import PAGE_KEYS

    languages = [code for code, _ in available_languages()]
    lang_list = languages if args.lang == "all" else [args.lang]
    page_list = list(PAGE_KEYS) if args.page == "all" else [args.page]
    unknown = [code for code in lang_list if code not in languages] + [k for k in page_list if k not in PAGE_KEYS]
    if unknown:
        print(f"valores desconocidos: {', '.join(unknown)}", file=sys.stderr)
        return 2

    window = MainWindow()
    window.resize(*args.size)
    window.show()
    project = window.page("project")
    if args.game:
        project.set_game_path(args.game.resolve())
    if args.mod:
        project.set_mod_path(args.mod.resolve())
    settle(app, window)
    if args.validate:
        if not project.validate_mod():
            print("no hay un mod válido que validar (usa --mod)", file=sys.stderr)
            return 1
        settle(app, window)
    if args.open_file:
        target = args.open_file
        if not target.is_absolute() and args.mod:
            target = args.mod / target
        target = target.resolve()
        if target.suffix.lower() == ".csv":
            window.open_in_localisation(target, line=args.line)
        elif not project.open_file(target, line=args.line, tab=args.tab):
            print(f"no se pudo abrir {target}", file=sys.stderr)
            return 1
        settle(app, window)
    if args.search:
        if args.open_file and args.open_file.suffix.lower() == ".csv":
            window.page("localisation").search_edit.setText(args.search)
        else:
            project.clausewitz_viewer.set_search(args.search)
            if args.tab:
                project.clausewitz_viewer.select_tab(args.tab)
        settle(app, window)
    if args.left_tab:
        project.left_tabs.setCurrentIndex(project.LEFT_TABS.index(args.left_tab))
        settle(app, window)

    args.out.mkdir(parents=True, exist_ok=True)
    for code in lang_list:
        set_language(code)
        for key in page_list:
            index = PAGE_KEYS.index(key)
            window.set_current_page(index)
            settle(app, window)
            target = args.out / f"{code}_{index + 1}_{key}.png"
            if not window.grab().save(os.fspath(target)):
                print(f"no se pudo guardar {target}", file=sys.stderr)
                return 1
            print(target)
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
