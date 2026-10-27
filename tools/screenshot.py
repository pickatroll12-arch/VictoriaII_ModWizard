"""Capturas automáticas de la ventana principal, sin pantalla (QT_QPA_PLATFORM=offscreen).

Uso:
    python3 tools/screenshot.py --out DIR [--lang es|en|all] [--size 1440x900] [--mod RUTA] [--game RUTA]
                                [--page all|project|localisation|SALA|SALA:SECCIÓN ...]
                                [--hall all|SALA[,SALA...]] [--section all|SECCIÓN]
                                [--dialog save_review|new_mod|conflict|recovery ...]
                                [--demo-game] [--demo-changes] [--fake-project] [--no-game-art]
                                [--open-file RUTA [--line N] [--tab structure|source|diagnostics|json]
                                 [--search TEXTO]]
                                [--validate] [--left-tab files|validation] [--report ESTADO.json]
                                [--demo-index] [--check] [--explain N] [--palette TEXTO]
                                [--texts-search TEXTO] [--texts-filter FILTRO]

Genera ``<lang>_<n>_<sala>[_<sección>].png`` (``n`` es el atajo Ctrl+n de la sala) y,
con ``--dialog``, ``<lang>_dialog_<nombre>.png``. ``--page`` (repetible o separado por
comas) admite las claves de la iteración 1 (``project`` es «Archivos» y
``localisation`` «Archivos CSV»: ``<lang>_1_project.png``, ``<lang>_7_localisation.png``),
una sala o ``sala:sección``; ``--hall`` y ``--section`` eligen salas y secciones
(``--section all``: todas las de cada sala). Sin ``--page`` ni ``--hall`` se captura
cada sala en su sección por defecto. Usa una carpeta de preferencias temporal, de
modo que nunca lee ni modifica la configuración real del usuario (ni sus datos: el
bloqueo y las cachés también van a carpetas temporales).

``--demo-game`` crea un juego sintético en una carpeta temporal (carpetas del juego
con unos pocos archivos inventados y el ejecutable), copia ``--mod`` (y su ``.mod``)
a su carpeta ``mod/`` y abre esa copia: así Inicio muestra las tarjetas de mods y el
descriptor sus problemas, sin datos de Paradox. ``--demo-changes`` hace dos cambios a
través de la sesión (el ``user_dir`` del descriptor y un archivo del juego base, que se
copiará al mod) para que «Cambios pendientes» y el diálogo de revisión tengan qué
mostrar. ``--fake-project`` abre el proyecto con el ``Project`` falso de las pruebas
(``tests/_fake_project.py``) en lugar del real. ``--no-game-art``
dibuja solo con la estética procedural (wizard D12): es lo que se hace siempre que
``--out`` está dentro de ``docs/capturas``, y hoy el Studio aún no usa arte del juego.

``--open-file`` (relativa al mod si no es absoluta) abre el archivo como lo haría
«Archivos»: un script o una imagen en su vista previa y un CSV de ``localisation/`` en
«Archivos CSV». Si no existe o no se puede leer, o si no tiene la línea ``--line``, sale
con 1 sin capturar (una imagen que no se puede decodificar sí se captura, con su aviso).
Las opciones que no tendrían efecto con ese archivo (``--tab`` sin un script; ``--line``
o ``--search`` sin visor) salen con 2. ``--search`` escribe en el buscador de ese visor
(estructura o tabla CSV) y se aplica antes que ``--line``, para que la búsqueda no mueva
ni oculte la línea pedida (en un CSV, si la fila no coincide con la búsqueda, el buscador
se vacía para mostrarla y se avisa en stderr). ``--validate`` ejecuta «Validar mod» y
espera a que termine antes de capturar. ``--report`` guarda en JSON lo que muestran las
capturas (archivo de cada visor, búsqueda, línea y resumen de la validación): así una
prueba puede comprobarlo.

Iteración 3: ``--demo-index`` abre la sesión con el índice, la validación y la línea base
de demostración (los falsos de ``tests/_fake_index.py``, con sus textos ES/EN), para
capturar Validación y Ctrl+K aunque el núcleo aún no los tenga. ``--check`` valida con el
validador del núcleo (Proyecto › Validación, F7) y espera el informe; ``--explain N``
además abre el explicador del problema N de la tabla (empezando en 0) y espera a que llegue
(se explica en segundo plano); ``--report`` dice en ``checks.explainer_layout`` lo que se
vería mal en él (vacío si nada: veredictos, alto de las capas, frase final). ``--palette TEXTO``
abre Ctrl+K con ese texto en cada captura (``<lang>_<n>_<sala>_palette.png``).
``--texts-search`` y ``--texts-filter`` (``all``, ``studio``, ``untranslated``,
``overrides``, ``degraded``) preparan Textos › Todos los textos.
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

DOCS_CAPTURES = ROOT / "docs" / "capturas"
DIALOGS = ("save_review", "new_mod", "conflict", "recovery")
TEXTS_FILTERS = ("all", "studio", "untranslated", "overrides", "degraded")
# Juego sintético de --demo-game: carpetas que reconoce evaluate_game y unos pocos archivos inventados.
DEMO_GAME_FILES = {
    "v2game.exe": b"MZ",
    "common/countries.txt": b'AAA = "countries/Aland.txt"\r\nBBB = "countries/Borea.txt"\r\n',
    "common/defines.lua": b"defines = {\r\n\tstart_date = '1836.1.1',\r\n}\r\n",
    "events/demo_events.txt": b"country_event = {\r\n\tid = 1\r\n}\r\n",
    "decisions/demo_decisions.txt": b"political_decisions = {\r\n}\r\n",
    "gfx/flags/AAA.tga": b"",
    "interface/demo.gui": b"guiTypes = {\r\n}\r\n",
    "localisation/demo.csv": (b"DEMO_KEY;Demo;;;;Demo;;;;;;;;;x\r\n"
                              b"AAA;Aland;Alande;Aland;;Alandia;;;;;;;;x\r\n"
                              b"BBB;Borea;Bor\xe9e;Borea;;Borea;;;;;;;;x\r\n"),
    "map/default.map": b"max_provinces = 4\r\n",
    # Misma ruta que un archivo del mod de muestra: en «Archivos» sale con la insignia M⊃J.
    "history/countries/SOM - Somalia.txt": b"capital = 1\r\n",
}
DEMO_PROVINCES = {f"history/provinces/demo/{n} - Demo{n}.txt": b"owner = AAA\r\n" for n in range(1, 13)}


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
    parser.add_argument("--page", action="append", default=[],
                        help="all, project, localisation, una sala o sala:sección (repetible o con comas)")
    parser.add_argument("--hall", help="all o salas separadas por comas")
    parser.add_argument("--section", help="all o la clave de una sección de la sala de --hall")
    parser.add_argument("--dialog", action="append", default=[], choices=DIALOGS,
                        help="diálogo que capturar además de la ventana (repetible)")
    parser.add_argument("--size", default="1440x900", type=parse_size, help="ANCHOxALTO de la ventana")
    parser.add_argument("--mod", type=Path, help="carpeta del mod a configurar")
    parser.add_argument("--game", type=Path, help="carpeta del juego base a configurar")
    parser.add_argument("--demo-game", action="store_true", help="juego sintético temporal con una copia de --mod")
    parser.add_argument("--demo-changes", action="store_true", help="dos cambios sin guardar para enseñar")
    parser.add_argument("--fake-project", action="store_true", help="Project falso de tests/_fake_project.py")
    parser.add_argument("--no-game-art", action="store_true",
                        help="solo estética procedural (siempre en docs/capturas)")
    parser.add_argument("--open-file", type=Path, help="archivo a abrir en la vista previa o en Archivos CSV")
    parser.add_argument("--line", type=int, help="línea a mostrar del script o CSV abierto")
    parser.add_argument("--tab", choices=("structure", "source", "diagnostics", "json"),
                        help="pestaña del visor Clausewitz (solo con un script)")
    parser.add_argument("--search", help="texto para el buscador del script o CSV abierto")
    parser.add_argument("--validate", action="store_true", help="ejecutar «Validar mod» antes de capturar")
    parser.add_argument("--left-tab", choices=("files", "validation"), help="pestaña del panel izquierdo")
    parser.add_argument("--report", type=Path, help="JSON con el estado de la ventana capturada")
    parser.add_argument("--demo-index", action="store_true",
                        help="índice, validación y línea base de demostración (tests/_fake_index.py)")
    parser.add_argument("--check", action="store_true", help="validar con el validador del núcleo (F7) antes")
    parser.add_argument("--explain", type=int, metavar="N", help="abrir el explicador del problema N (con --check)")
    parser.add_argument("--palette", metavar="TEXTO", help="abrir Ctrl+K con TEXTO en cada captura")
    parser.add_argument("--texts-search", metavar="TEXTO", help="buscador de Textos › Todos los textos")
    parser.add_argument("--texts-filter", choices=TEXTS_FILTERS, help="filtro de Textos › Todos los textos")
    return parser


def check_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Rechaza las opciones que no tendrían efecto (``_open_file`` comprueba después la línea)."""
    if args.section and (not args.hall or args.hall == "all" or "," in args.hall) and args.section != "all":
        parser.error("--section necesita una sola sala en --hall (o --section all)")
    if args.demo_game and args.game:
        parser.error("--demo-game crea su propio juego: no se puede combinar con --game")
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


def no_game_art(args: argparse.Namespace) -> bool:
    """D12: las capturas del repositorio nunca llevan arte del juego."""
    try:
        args.out.resolve().relative_to(DOCS_CAPTURES)
        return True
    except ValueError:
        return args.no_game_art


def build_demo_game(base: Path, mod: Path | None) -> tuple[Path, Path | None]:
    """Juego sintético en ``base`` (sin datos de Paradox) y, si hay ``mod``, una copia en su carpeta ``mod/``."""
    game = base / "Victoria 2"
    for rel, data in {**DEMO_GAME_FILES, **DEMO_PROVINCES}.items():
        path = game / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (game / "mod").mkdir(exist_ok=True)
    if mod is None:
        return game, None
    copy = game / "mod" / mod.name
    shutil.copytree(mod, copy)
    for sibling in mod.parent.glob("*.mod"):
        shutil.copy2(sibling, game / "mod" / sibling.name)
    (game / "mod" / "Otro Mod.mod").write_bytes(b'name = "Otro Mod"\r\npath = "mod/OtroMod"\r\n')
    return game, copy


def settle(app, window, timeout: float = 60.0, quiet: float = 0.3) -> None:
    """Procesa eventos hasta que nada esté ocupado durante ``quiet`` segundos."""
    from PySide6.QtCore import QEventLoop

    deadline = time.monotonic() + timeout
    quiet_since = None
    while time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        if window.is_busy():
            quiet_since = None
        elif quiet_since is None:
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since >= quiet:
            return
        time.sleep(0.01)


def shows(window, target: Path) -> bool:
    """True si el visor que le corresponde a ``target`` lo muestra: un CSV o un script leídos.

    Una imagen vale aunque no se pueda decodificar (su aviso también es una captura
    útil) y un archivo sin visor, con que exista («Archivos» muestra su ficha).
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
    session = window.session
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
        "project": None if session.project is None else {
            "mod": os.fspath(session.project.mod_root), "dirty": session.dirty_count(),
        },
        **iteration3_state(window),
    }


def iteration3_state(window) -> dict:
    """Lo de la iteración 3 en ``--report``: el informe del validador, la tabla de Textos y Ctrl+K."""
    session = window.session
    report = session.report
    checks = window.page("project:validation")
    texts = window.page("localisation:all")
    palette = window.palette
    return {
        "checks": None if report is None else {
            "state": session.validation_state(), "shown": checks.model.rowCount(),
            "own": len(report.visible()), "inherited": report.inherited_count(),
            "explained": checks.explainer.title.text() if checks.explainer.isVisible() else None,
            # Lo que se vería mal en el explicador (veredictos fuera, capas sin su alto, frase cortada…): vacío si nada.
            "explainer_layout": checks.explainer.layout_problems() if checks.explainer.isVisible() else None,
            "stale": session.report_stale(),
        },
        "texts": None if not session.texts_ready() else {
            "rows": len(texts.model.entries), "visible": texts.proxy.rowCount(), "filter": texts.proxy.filter(),
            "search": texts.search_edit.text(),
        },
        "palette": None if not palette.isVisible() else {
            "text": palette.edit.text(), "results": palette.result_texts(),
        },
        "index": session.index_state(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    check_args(parser, args)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    scratch = Path(tempfile.mkdtemp(prefix="vic2studio-shots-"))
    for env, name in (("VIC2STUDIO_SETTINGS_DIR", "settings"), ("VIC2STUDIO_DATA_DIR", "data"),
                      ("VIC2STUDIO_CACHE_DIR", "cache")):
        os.environ[env] = os.fspath(scratch / name)
    try:
        if args.demo_game:
            args.game, args.mod = build_demo_game(scratch / "demo", args.mod.resolve() if args.mod else None)
        return _run(args)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _open_file(app, window, args: argparse.Namespace) -> str | None:
    """Abre ``--open-file`` y aplica ``--search``, ``--line`` y ``--tab``; devuelve el error, si lo hay."""
    project, localisation = window.page("project"), window.page("localisation")
    target = resolve_target(args)
    csv = file_kind(target) == KIND_CSV
    window.show_page("localisation" if csv else "project")
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


def targets(window, args: argparse.Namespace) -> list[tuple[str, str]]:
    """(clave para ``show_page``, nombre del archivo sin idioma) de cada captura de ventana."""
    halls = {hall.spec.key: hall for hall in window.halls}
    order = {key: index + 1 for index, key in enumerate(halls)}
    def hall_shot(key: str) -> tuple[str, str]:
        """La sala en la sección que muestra al abrirse (la primera que ya existe)."""
        section = halls[key].current_section()
        return f"{key}:{section.key}", f"{order[key]}_{key}"

    shots: list[tuple[str, str]] = []
    pages = [p.strip() for value in args.page for p in value.split(",") if p.strip()]
    if args.hall:
        keys = list(halls) if args.hall == "all" else [k.strip() for k in args.hall.split(",") if k.strip()]
        for key in keys:
            if key not in halls:
                raise KeyError(key)
            if args.section == "all":
                pages += [f"{key}:{s.key}" for s in halls[key].sections]
            elif args.section:
                pages.append(f"{key}:{args.section}")
            else:
                shots.append(hall_shot(key))
    elif not pages or pages == ["all"]:
        return [hall_shot(key) for key in halls]
    for page in pages:
        if page in ("project", "localisation"):  # claves de la iteración 1: «Archivos» y «Archivos CSV»
            shots.append((page, f"{order[page]}_{page}"))
        elif ":" in page:
            hall, section = page.split(":", 1)
            if hall not in halls:
                raise KeyError(page)
            halls[hall].section_index(section)  # KeyError si no existe
            shots.append((page, f"{order[hall]}_{hall}_{section}"))
        elif page in halls:
            shots.append(hall_shot(page))
        else:
            raise KeyError(page)
    return shots


def demo_changes(window) -> None:
    """Dos cambios sin guardar a través de la sesión: el ``user_dir`` del descriptor y un archivo del juego."""
    from vic2studio.core.clausewitz import Scalar
    from vic2studio.core.modfile import DescriptorSpec, apply_descriptor, descriptor_from_result
    from vic2studio.core.vfs import DESCRIPTOR_REL

    session = window.session
    project = session.project
    if project is None:
        return
    with session.edit("descriptor.undo_edit", field="user_dir"):
        handle = project.ws.open(DESCRIPTOR_REL)
        spec = DescriptorSpec.from_descriptor(descriptor_from_result(project.vfs.descriptor_path, handle.model))
        project.ws.touch(handle)
        apply_descriptor(handle.model.document, DescriptorSpec(spec.name, spec.folder, spec.folder + "_studio",
                                                               spec.replace_paths, spec.dependencies))
    game = project.game_root
    if game is not None and (game / "common" / "countries.txt").is_file():
        with session.edit("descriptor.undo_edit", field="countries"):
            handle = project.ws.open("common/countries.txt")
            project.ws.touch(handle)
            handle.model.document.append("CCC", Scalar("countries/Cimbria.txt", quoted=True))
    window.page("descriptor").reload()


def _prepare_iteration3(app, window, args: argparse.Namespace) -> str | None:
    """``--check``/``--explain`` y ``--texts-search``/``--texts-filter``; devuelve el error, si lo hay."""
    session = window.session
    if args.check or args.explain is not None:
        if session.project is None:
            return "no hay un mod abierto que validar (usa --mod)"
        settle(app, window)
        window.validate_mod()
        settle(app, window)
        if session.validation_state() != "ready":
            return f"la validación no terminó: {session.validation_state()} {session.validation_error() or ''}"
        if args.explain is not None:
            page = window.page("project:validation")
            if not 0 <= args.explain < page.model.rowCount():
                return f"no hay problema {args.explain} (la tabla tiene {page.model.rowCount()})"
            page.view.setCurrentIndex(page.model.index(args.explain, 0))
            if not page.show_explanation():
                return "no se pudo abrir el explicador"
            settle(app, window)   # se explica en segundo plano: settle espera a la sesión
            if not page.explainer.isVisible():
                return f"el explicador no llegó a mostrarse: {window.status_label.text()}"
        settle(app, window)
    if args.texts_search is not None or args.texts_filter:
        page = window.page("localisation:all")
        if args.texts_filter:
            page.filter_combo.setCurrentIndex(TEXTS_FILTERS.index(args.texts_filter))
        if args.texts_search is not None:
            page.search_edit.setText(args.texts_search)
        settle(app, window)
    return None


def dialog_for(window, name: str):
    from vic2studio.core.project import ChangeSet
    from vic2studio.ui.dialogs import ConflictDialog, NewModDialog, RecoveryDialog, SaveReviewDialog

    if name == "save_review":
        changeset = window.session.changeset() if window.session.project is not None else ChangeSet()
        return SaveReviewDialog(changeset, (), window)
    if name == "new_mod":
        dialog = NewModDialog(window.session, window.page("project").game_path(), window)
        dialog.name_edit.setText("Dark Age Mod")
        return dialog
    if name == "conflict":
        project = window.session.project
        rel = "common/countries.txt"
        return ConflictDialog(rel, lambda: window.session.external_diff(rel) if project is not None else "", parent=window)
    return RecoveryDialog(["20261026T101500-3fa2c1"], [], window)


def _run(args: argparse.Namespace) -> int:
    from vic2studio.app import create_application

    app = create_application([])

    from vic2studio.i18n import available_languages, set_language
    from vic2studio.ui.main_window import MainWindow
    from vic2studio.ui.session import Session

    languages = [code for code, _ in available_languages()]
    lang_list = languages if args.lang == "all" else [args.lang]
    unknown = [code for code in lang_list if code not in languages]
    if unknown:
        print(f"valores desconocidos: {', '.join(unknown)}", file=sys.stderr)
        return 2
    session = None
    engines: dict = {}
    if args.demo_index:
        sys.path.insert(0, str(ROOT / "tests"))
        from _fake_index import fake_engines

        engines = fake_engines()
    if args.fake_project:
        sys.path.insert(0, str(ROOT / "tests"))
        from _fake_project import FakeOpener

        session = Session(opener=FakeOpener(), **engines)
    elif engines:
        session = Session(**engines)
    os.environ["VIC2STUDIO_NO_GAME_ART"] = "1" if no_game_art(args) else ""

    window = MainWindow(session=session)
    window.resize(*args.size)
    try:
        shots = targets(window, args)
    except KeyError as error:
        print(f"valores desconocidos: {error.args[0]}", file=sys.stderr)
        window.close()
        return 2
    window.show()
    project = window.page("project")
    if args.game:
        project.set_game_path(args.game.resolve())
    if args.mod:
        project.set_mod_path(args.mod.resolve())
    settle(app, window)
    if args.demo_changes:
        demo_changes(window)
        settle(app, window)
    if args.validate:
        window.show_page("project")
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
    error = _prepare_iteration3(app, window, args)
    if error:
        print(error, file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    width, height = args.size
    for code in lang_list:
        set_language(code)
        for key, name in shots:
            window.show_page(key)
            settle(app, window)
            if args.palette:
                window.open_palette(args.palette)
                settle(app, window)
                name = f"{name}_palette"
            target = args.out / f"{code}_{name}.png"
            if not window.grab().save(os.fspath(target)):
                print(f"no se pudo guardar {target}", file=sys.stderr)
                return 1
            print(target)
        for name in args.dialog:
            dialog = dialog_for(window, name)
            if name == "save_review":  # el diff aprovecha el sitio; los demás tienen su tamaño
                dialog.resize(max(760, int(width * 0.78)), max(520, int(height * 0.85)))
            dialog.show()
            settle(app, window)
            target = args.out / f"{code}_dialog_{name}.png"
            saved = dialog.grab().save(os.fspath(target))
            dialog.close()
            dialog.deleteLater()
            if not saved:
                print(f"no se pudo guardar {target}", file=sys.stderr)
                return 1
            print(target)
    if args.report:
        args.report.write_text(json.dumps(window_state(window), ensure_ascii=False, indent=2), encoding="utf-8")
    window.ask_unsaved = lambda: "discard"  # las capturas nunca guardan lo que hayan cambiado
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
