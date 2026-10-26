"""Capturas automáticas de la ventana principal, sin pantalla (QT_QPA_PLATFORM=offscreen).

Uso:
    python3 tools/screenshot.py --out DIR [--lang es|en|all] [--page all|project|map|...]
                                [--size 1440x900] [--mod RUTA] [--game RUTA]
                                [--open-file RUTA [--line N] [--tab structure|source|diagnostics|json]
                                 [--search TEXTO]]
                                [--validate] [--left-tab files|validation] [--report ESTADO.json]

Genera ``<lang>_<n>_<page>.png``. Usa una carpeta de preferencias temporal, de
modo que nunca lee ni modifica la configuración real del usuario.

``--open-file`` (relativa al mod si no es absoluta) abre el archivo como lo haría
«Proyecto y Archivos»: un script o una imagen en su vista previa y un CSV de
``localisation/`` en «Localización». Si no existe o no se puede leer, o si no tiene la
línea ``--line``, sale con 1 sin capturar (una imagen que no se puede decodificar sí
se captura, con su aviso). Las opciones que no tendrían efecto con ese archivo
(``--tab`` sin un script; ``--line`` o ``--search`` sin visor) salen con 2.
``--search`` escribe en el buscador de ese visor (estructura o tabla CSV) y se
aplica antes que ``--line``, para que la búsqueda no mueva ni oculte la línea pedida
(en un CSV, si la fila no coincide con la búsqueda, el buscador se vacía para mostrarla
y se avisa en stderr).
``--validate`` ejecuta «Validar mod» y espera a que termine antes de capturar.
``--report`` guarda en JSON lo que muestran las capturas (archivo de cada visor,
búsqueda, línea y resumen de la validación): así una prueba puede comprobarlo.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vic2studio.core.modcheck import KIND_CLAUSEWITZ, KIND_CSV, file_kind  # noqa: E402  (sin Qt)


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
    parser.add_argument("--line", type=int, help="línea a mostrar del script o CSV abierto")
    parser.add_argument("--tab", choices=("structure", "source", "diagnostics", "json"),
                        help="pestaña del visor Clausewitz (solo con un script)")
    parser.add_argument("--search", help="texto para el buscador del script o CSV abierto")
    parser.add_argument("--validate", action="store_true", help="ejecutar «Validar mod» antes de capturar")
    parser.add_argument("--left-tab", choices=("files", "validation"), help="pestaña del panel izquierdo")
    parser.add_argument("--report", type=Path, help="JSON con el estado de la ventana capturada")
    return parser


def check_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Rechaza las opciones que no tendrían efecto con ese archivo (``_open_file`` comprueba después la línea)."""
    given = [f"--{name}" for name in ("line", "tab", "search") if getattr(args, name) is not None]
    if args.open_file is None:
        if given:
            parser.error(f"{', '.join(given)} necesita --open-file")
        return
    # La ruta resuelta, como la abre _open_file: «00_a.csv» desde la propia carpeta localisation es un CSV.
    kind = file_kind(resolve_target(args))
    if args.tab is not None and kind != KIND_CLAUSEWITZ:
        parser.error("--tab solo sirve con un script Clausewitz (.txt, .gui, .gfx...)")
    if kind is None and given:
        parser.error(f"{', '.join(given)} solo sirve con un script o un CSV de localisation/")


def resolve_target(args: argparse.Namespace) -> Path:
    target = args.open_file
    if not target.is_absolute() and args.mod:
        target = args.mod / target
    return target.resolve()


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


def shows(window, target: Path) -> bool:
    """True si el visor que le corresponde a ``target`` lo muestra: un CSV o un script leídos.

    Una imagen vale aunque no se pueda decodificar (su aviso también es una captura
    útil) y un archivo sin visor, con que exista («Proyecto y Archivos» muestra su ficha).
    """
    if file_kind(target) == KIND_CSV:
        localisation = window.page("localisation")
        load = localisation.editor.current_load() if localisation.central_widget() is localisation.editor else None
        return load is not None and load.path == target
    project = window.page("project")
    viewer = project.preview_widget()
    if viewer is None:
        return target.is_file()
    if viewer is project.image_viewer:
        return viewer.current_path() == target
    load = viewer.current_load()
    return load is not None and load.path == target


def window_state(window) -> dict:
    """Lo que muestran las capturas (``--report``): script y CSV abiertos, búsquedas, líneas y validación."""
    from vic2studio.core.clausewitz import Severity

    project, localisation = window.page("project"), window.page("localisation")
    viewer, editor = project.clausewitz_viewer, localisation.editor
    script = viewer.current_load() if project.preview_widget() is viewer else None
    table = editor.current_load() if localisation.central_widget() is editor else None
    report = project.validation_report()
    return {
        "script": None if script is None else {
            "path": os.fspath(script.path), "tab": viewer.current_tab(), "line": viewer.code.current_line(),
            "search": viewer.search_edit.text(), "matches": len(viewer.matches()),
        },
        "csv": None if table is None else {
            "path": os.fspath(table.path), "rows": editor.total_rows(), "visible_rows": editor.visible_rows(),
            "search": localisation.search_edit.text(), "selected_line": editor.selected_line(),
        },
        "validation": None if report is None else {
            "files": report.files, "errors": report.count(Severity.ERROR), "warnings": report.count(Severity.WARNING),
            "files_with_errors": report.files_with(Severity.ERROR),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    check_args(parser, args)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    settings_dir = tempfile.mkdtemp(prefix="vic2studio-shots-")
    os.environ["VIC2STUDIO_SETTINGS_DIR"] = settings_dir
    try:
        return _run(args)
    finally:
        shutil.rmtree(settings_dir, ignore_errors=True)


def _open_file(app, window, args: argparse.Namespace) -> str | None:
    """Abre ``--open-file`` y aplica ``--search``, ``--line`` y ``--tab``; devuelve el error, si lo hay."""
    project, localisation = window.page("project"), window.page("localisation")
    target = resolve_target(args)
    csv = file_kind(target) == KIND_CSV
    # Con búsqueda, la línea se aplica después: buscar mueve el cursor del script y filtra las filas del CSV.
    if not project.open_file(target, line=None if args.search else args.line, tab=args.tab):
        return f"no existe {target}"
    settle(app, window)
    if not shows(window, target):
        return f"no se pudo abrir {target}: {window.status_label.text()}"
    if args.search:
        if csv:
            localisation.search_edit.setText(args.search)
            localisation.editor.set_query(args.search)
            if args.line is not None:
                localisation.editor.select_line(args.line)
                if localisation.search_edit.text() != args.search:
                    print(f"aviso: la línea {args.line} no coincide con la búsqueda; se vació el buscador para mostrarla",
                          file=sys.stderr)
        else:
            viewer = project.clausewitz_viewer
            viewer.set_search(args.search)
            if args.line is not None:
                viewer.go_to_line(args.line)
            if args.tab:
                viewer.select_tab(args.tab)
        settle(app, window)
    if args.line is not None:
        # Una línea que no existe no se selecciona: la captura mostraría otra cosa.
        state = window_state(window)
        shown = state["csv"]["selected_line"] if csv else state["script"]["line"]
        if shown != args.line:
            return f"no existe la línea {args.line} en {target}"
    return None


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
        if project.validation_report() is None:
            print("la validación no terminó a tiempo", file=sys.stderr)
            return 1
    if args.open_file:
        error = _open_file(app, window, args)
        if error:
            print(error, file=sys.stderr)
            return 1
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
    if args.report:
        args.report.write_text(json.dumps(window_state(window), ensure_ascii=False, indent=2), encoding="utf-8")
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
