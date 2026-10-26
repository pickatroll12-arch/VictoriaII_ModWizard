"""Integración del parser Clausewitz y del CSV en la interfaz (offscreen).

Usa el corpus de ``VIC2_CORPUS``: la plantilla (con ``localisation/text.csv``) y
el mod del usuario ``VSM`` (con dos decisiones a las que les falta la llave de
cierre de ``political_decisions``). Las pruebas que lo necesitan se omiten si no
está disponible. Todas fallan ante cualquier aviso de Qt.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
from _corpus import corpus_roots  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QElapsedTimer, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

APP = _qt.application()

from test_ui_smoke import MARK_OPEN, PSEUDO, collect_texts, pseudo_catalog  # noqa: E402
from vic2studio.core.clausewitz import Severity, parse_file, to_json, to_source  # noqa: E402
from vic2studio.core.csvloc import RowKind, read_csv_file  # noqa: E402
from vic2studio.core.modcheck import collect_files  # noqa: E402
from vic2studio.i18n import set_language, translator  # noqa: E402
from vic2studio.ui.main_window import MainWindow  # noqa: E402
from vic2studio.ui.pages import PAGE_KEYS  # noqa: E402
from vic2studio.ui.tasks import thread_pool  # noqa: E402
from vic2studio.ui.viewers.clausewitz_viewer import TAB_DIAGNOSTICS, TAB_JSON, TAB_SOURCE, TAB_STRUCTURE  # noqa: E402
from vic2studio.ui.viewers.diagnostics import ROW_ROLE  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LOAD_TIMEOUT_MS = 20000
CSV_LIMIT_SECONDS = 3.0
STALL_LIMIT_SECONDS = 0.5


def _find(relative: str, exclude: str | None = None) -> Path | None:
    """Primer ``<raíz>/relative`` o ``<raíz>/<carpeta>/relative`` del corpus (sin ``exclude`` en la ruta)."""
    for root in corpus_roots():
        for base in (root, *[p for p in root.iterdir() if p.is_dir()]):
            candidate = base / relative
            if candidate.is_file() and (exclude is None or exclude not in candidate.parts):
                return candidate
    return None


SOMALILAND = _find("decisions/somaliland_shago.txt")
ZULU = _find("decisions/zulu_expancionshago.txt")
USER_MOD = SOMALILAND.parents[1] if SOMALILAND else None
TEXT_CSV = _find("localisation/text.csv", exclude="VSM") or _find("localisation/text.csv")
TEMPLATE = TEXT_CSV.parents[1] if TEXT_CSV else None
PROVINCE = TEMPLATE / "history" / "provinces" / "france" / "400 - Dunkirk.txt" if TEMPLATE else None
VSM_DECISIONS_CSV = USER_MOD / "localisation" / "00_VSM_decisions.csv" if USER_MOD else None


def double_click(view, index) -> None:
    """Doble clic real (pulsar, soltar, doble clic): ``QTest.mouseDClick`` solo no activa la vista."""
    center = view.visualRect(index).center()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    _qt.process_events(20)


def needs(*paths):
    missing = [p for p in paths if p is None or not Path(p).exists()]
    return unittest.skipIf(missing, "sin corpus disponible (VIC2_CORPUS)")


class IntegrationCase(unittest.TestCase):
    def setUp(self):
        _qt.reset_settings()
        set_language("es")
        _qt.take_qt_messages()
        self.missing_before = translator().missing_keys()
        self.window = MainWindow()
        self.window.resize(1440, 900)
        self.window.show()
        _qt.process_events(30)
        self.project = self.window.page("project")
        self.localisation = self.window.page("localisation")

    def tearDown(self):
        self.window.close()
        thread_pool().waitForDone(10000)
        _qt.process_events()
        self.window.deleteLater()
        _qt.process_events()
        set_language("es")
        _qt.process_events()
        self.assertEqual(_qt.take_qt_messages(), [], "avisos de Qt durante la prueba")
        self.assertEqual(sorted(translator().missing_keys() - self.missing_before), [],
                         "claves pedidas en tiempo de ejecución que no existen")

    def wait(self, predicate, message: str, timeout: int = LOAD_TIMEOUT_MS) -> None:
        self.assertTrue(_qt.wait_until(predicate, timeout), message)

    def open_clausewitz(self, path: Path, **kwargs):
        viewer = self.project.clausewitz_viewer
        self.assertTrue(self.project.open_file(path, **kwargs))
        self.wait(lambda: viewer.current_load() is not None and viewer.current_load().path == path
                  and not viewer.is_busy(), f"{path.name} no terminó de cargar")
        self.assertIs(self.project.preview_widget(), viewer)
        return viewer

    def set_mod(self, path: Path) -> None:
        self.project.set_mod_path(path)
        self.wait(lambda: not self.project.is_busy(), "el explorador no terminó de cargar")


class ClausewitzPreviewTests(IntegrationCase):
    @needs(PROVINCE)
    def test_province_history_structure_source_and_json(self):
        self.set_mod(TEMPLATE)
        self.assertTrue(self.project.reveal_file(PROVINCE))
        viewer = self.project.clausewitz_viewer
        self.wait(lambda: viewer.current_load() is not None and viewer.current_load().path == PROVINCE,
                  "seleccionar el archivo en el explorador no abrió el visor")
        expected = parse_file(PROVINCE)
        tree = viewer.tree
        top = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
        self.assertEqual(top, [e.key.text for e in expected.document.entries])
        self.assertEqual(top[:3], ["owner", "controller", "add_core"])
        owner = tree.topLevelItem(0)
        self.assertEqual((owner.text(1), owner.text(2), owner.text(3)), ("=", "FRA", "1"))
        dated = tree.topLevelItem(tree.topLevelItemCount() - 1)
        self.assertEqual(dated.text(0), "1861.1.1")
        self.assertTrue(dated.isExpanded(), "un archivo pequeño debe mostrarse expandido")
        self.assertEqual(dated.child(0).text(0), "railroad")
        self.assertEqual(dated.child(0).text(2), "3")
        self.assertEqual(viewer.diagnostics_model.rowCount(), len(expected.diagnostics))
        self.assertEqual(viewer.header.badge.level, "ok")
        self.assertEqual(viewer.code.toPlainText(), to_source(expected.document))
        self.assertTrue(viewer.code.highlighted)
        self.assertIn("france/400 - Dunkirk.txt", viewer.header.details.text())
        self.assertIn("Windows-1252", viewer.header.details.text())
        # Seleccionar un nodo lleva el cursor del código a su línea.
        tree.setCurrentItem(dated.child(0))
        self.assertEqual(viewer.code.current_line(), 7)

        viewer.select_tab(TAB_JSON)
        self.wait(lambda: viewer.json_view.toPlainText() != "", "el JSON no se generó")
        self.assertEqual(json.loads(viewer.json_view.toPlainText()), to_json(expected.document))

    @needs(SOMALILAND)
    def test_unclosed_block_in_user_mod(self):
        viewer = self.open_clausewitz(SOMALILAND, tab=TAB_DIAGNOSTICS)
        self.assertEqual(viewer.current_tab(), TAB_DIAGNOSTICS)
        rows = viewer.diagnostics_model.all_rows()
        errors = [r for r in rows if r.severity == "error"]
        self.assertEqual([(r.code, r.line, r.column) for r in errors], [("unclosed_block", 1, 23)])
        self.assertEqual(errors[0].source.args["key"], "political_decisions")
        model = viewer.diagnostics_model
        message = model.data(model.index(0, 2))
        self.assertIn("political_decisions", message)
        self.assertIn("línea 1", message)
        self.assertEqual(viewer.header.badge.level, "error")
        self.assertEqual(viewer.code.markers().get(1), "error")
        root = viewer.tree.topLevelItem(0)
        self.assertEqual(root.text(0), "political_decisions")
        self.assertFalse(root.icon(0).isNull(), "el nodo sin cerrar debe llevar el icono de error")
        self.assertIn("sin cerrar", root.text(2))
        self.assertIn("(1)", viewer.tabs.tabText(viewer.tabs.currentIndex()))
        self.assertIn("1 error", self.window.status_label.text())

        # Doble clic en el diagnóstico: código en la línea y nodo seleccionado.
        double_click(viewer.diagnostics_view, model.index(0, 2))
        self.assertEqual(viewer.current_tab(), TAB_SOURCE)
        self.assertEqual(viewer.code.current_line(), 1)
        self.assertEqual(viewer.code.textCursor().positionInBlock(), 22)
        self.assertIs(viewer.tree.currentItem(), root)

    @needs(ZULU)
    def test_hint_jumps_to_its_line_and_deep_node(self):
        viewer = self.open_clausewitz(ZULU)
        hint = next(r for r in viewer.diagnostics_model.all_rows() if r.severity == "info")
        self.assertEqual((hint.code, hint.line), ("suspicious_close_brace", 155))
        viewer.show_diagnostic(hint)
        self.assertEqual(viewer.current_tab(), TAB_SOURCE)
        self.assertEqual(viewer.code.current_line(), 155)
        node = viewer.node_of_item(viewer.tree.currentItem())
        index = viewer.current_load().index
        self.assertLessEqual(index.lines[node], 155)
        self.assertEqual(index.key_path(node)[0], "political_decisions")

    @needs(SOMALILAND)
    def test_language_switch_with_open_file(self):
        viewer = self.open_clausewitz(SOMALILAND, tab=TAB_STRUCTURE)
        diagnostic = viewer.diagnostics_model.all_rows()[0].source
        model = viewer.diagnostics_model
        self.assertEqual(model.data(model.index(0, 2)), diagnostic.message("es"))
        self.assertEqual(viewer.tabs.tabText(0), "Estructura")
        self.assertIn("líneas", viewer.header.details.text())
        before = collect_texts(self.window)
        set_language("en")
        self.assertEqual(model.data(model.index(0, 2)), diagnostic.message("en"))
        self.assertEqual(model.headerData(2, Qt.Orientation.Horizontal), "Message")
        self.assertEqual(viewer.tabs.tabText(0), "Structure")
        self.assertEqual(viewer.tree.headerItem().text(0), "Key")
        self.assertIn("lines", viewer.header.details.text())
        self.assertIn("never closed", viewer.tree.topLevelItem(0).text(2))
        self.assertEqual(viewer.header.badge.label.text(), "1 error")
        after = collect_texts(self.window)
        self.assertEqual(before.keys(), after.keys())
        set_language("es")
        self.assertEqual(collect_texts(self.window), before)
        self.assertIn("sin cerrar", viewer.tree.topLevelItem(0).text(2))

    @needs(USER_MOD, TEMPLATE)
    def test_pseudo_locale_with_everything_open(self):
        """Con archivos abiertos y el mod validado, todo texto visible sigue viniendo del catálogo."""
        self.set_mod(USER_MOD)
        self.open_clausewitz(SOMALILAND)
        self.assertTrue(self.project.validate_mod())
        self.wait(lambda: self.project.validation_report() is not None, "la validación no terminó")
        self.window.open_in_localisation(VSM_DECISIONS_CSV)
        self.wait(lambda: self.localisation.editor.current_load() is not None, "el CSV no cargó")
        translator().register_catalog(PSEUDO, pseudo_catalog())
        try:
            for index in (0, PAGE_KEYS.index("localisation")):
                self.window.set_current_page(index)
                set_language(PSEUDO)
                texts = collect_texts(self.window)
                untranslated = {k: v for k, v in texts.items() if MARK_OPEN not in v}
                self.assertEqual(untranslated, {}, "textos visibles que no pasan por tr()")
                set_language("es")
        finally:
            set_language("es")

    @needs(SOMALILAND)
    def test_structure_search(self):
        viewer = self.open_clausewitz(SOMALILAND)
        viewer.set_search("UNITE_SOMALIA")
        matches = viewer.matches()
        self.assertTrue(matches)
        index = viewer.current_load().index
        self.assertTrue(all("unite_somalia" in index.haystack[m] for m in matches))
        self.assertEqual(viewer.node_of_item(viewer.tree.currentItem()), matches[0])
        self.assertEqual(viewer.match_label.text(), f"1 / {len(matches)}")
        viewer.next_match()
        if len(matches) > 1:
            self.assertEqual(viewer.node_of_item(viewer.tree.currentItem()), matches[1])
        viewer.set_search("zzz-no-existe")
        self.assertEqual(viewer.matches(), [])
        self.assertEqual(viewer.match_label.text(), "Sin coincidencias")

    @needs(USER_MOD)
    def test_descriptor_is_parsed_and_opens_in_preview(self):
        self.set_mod(USER_MOD)
        label = self.project.mod_field.descriptor.text()
        for fragment in ("VSM.mod", "Shago Mod", "mod/VSM", "user_dir"):
            self.assertIn(fragment, label)
        self.project.mod_field.descriptor.linkActivated.emit("descriptor")
        viewer = self.project.clausewitz_viewer
        descriptor = USER_MOD.parent / "VSM.mod"
        self.wait(lambda: viewer.current_load() is not None and viewer.current_load().path == descriptor,
                  "el descriptor no se abrió en la vista previa")
        keys = [viewer.tree.topLevelItem(i).text(0) for i in range(viewer.tree.topLevelItemCount())]
        self.assertEqual(keys, ["name", "path", "user_dir"])
        self.assertEqual(viewer.tree.topLevelItem(0).text(2), '"Shago Mod"')

    def test_images_and_friendly_dds_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp) / "ImgMod"
            flags = mod / "gfx" / "flags"
            flags.mkdir(parents=True)
            Image.new("RGBA", (93, 64), (20, 60, 200, 255)).save(flags / "IMG.tga")
            broken = flags / "BROKEN.dds"
            broken.write_bytes(b"DDS " + bytes(124) + b"\x00" * 64)
            self.set_mod(mod)
            image = self.project.image_viewer
            self.assertTrue(self.project.open_file(flags / "IMG.tga"))
            self.wait(lambda: image.current_load() is not None, "la imagen no cargó")
            self.assertIs(self.project.preview_widget(), image)
            load = image.current_load()
            self.assertEqual((load.width, load.height, load.image.width()), (93, 64, 93))
            self.assertIn("93 × 64 px", image.header.details.text())
            self.assertIn("Zoom", image.zoom_label.text())
            image.set_fit(False)
            self.assertEqual(image.canvas.scale(), 1.0)
            self.assertTrue(self.project.open_file(broken))
            self.wait(lambda: image.error() is not None, "el DDS dañado no dio un mensaje")
            self.assertIs(image.stack.currentWidget(), image.failure)
            self.assertIn("DDS", image.failure.text.text())
            self.assertIn("El juego lo leerá igualmente", image.failure.text.text())


class CompactLayoutTests(IntegrationCase):
    @needs(USER_MOD)
    def test_minimum_size_switches_to_compact_mode(self):
        self.set_mod(USER_MOD)
        self.open_clausewitz(SOMALILAND)
        field = self.project.mod_field
        self.assertFalse(field.status_action.isVisible())
        self.window.resize(1100, 700)
        _qt.process_events(50)
        self.assertLess(self.project.height(), 600)
        self.assertTrue(field.status_action.isVisible())
        self.assertFalse(field.chips_box.isVisibleTo(field))
        self.assertFalse(field.descriptor.isVisibleTo(field))
        self.assertFalse(self.project.clausewitz_viewer.diagnostics_hint.isVisibleTo(self.project.clausewitz_viewer))
        tooltip = field.status_action.toolTip()
        for fragment in ("Mod válido", "decisions", "VSM.mod", "Shago Mod"):
            self.assertIn(fragment, tooltip)
        translator().register_catalog(PSEUDO, pseudo_catalog())
        try:
            set_language(PSEUDO)
            untranslated = {k: v for k, v in collect_texts(self.window).items() if MARK_OPEN not in v}
            self.assertEqual(untranslated, {}, "textos del modo compacto que no pasan por tr()")
        finally:
            set_language("es")
        self.window.resize(1440, 900)
        _qt.process_events(50)
        self.assertFalse(field.status_action.isVisible())
        self.assertTrue(field.descriptor.isVisibleTo(field))


class ScreenshotToolTests(unittest.TestCase):
    def test_open_file_validate_and_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp) / "ShotMod"
            (mod / "decisions").mkdir(parents=True)
            (mod / "localisation").mkdir()
            (mod / "decisions" / "broken.txt").write_bytes(b"political_decisions = {\n\ta = b\n")
            (mod / "localisation" / "00_shot.csv").write_bytes(b"KEY;Hello;;;;Hola;;;;;;;;;x\n")
            out = Path(tmp) / "shots"
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
            commands = [
                ["--page", "project", "--validate", "--open-file", "decisions/broken.txt", "--tab", "diagnostics"],
                ["--page", "localisation", "--open-file", "localisation/00_shot.csv", "--search", "key"],
            ]
            for extra in commands:
                result = subprocess.run(
                    [sys.executable, str(ROOT / "tools" / "screenshot.py"), "--out", str(out), "--lang", "en",
                     "--size", "1200x800", "--mod", str(mod), *extra],
                    env=env, capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sorted(p.name for p in out.glob("*.png")), ["en_1_project.png", "en_5_localisation.png"])
            for png in out.glob("*.png"):
                with Image.open(png) as image:
                    self.assertEqual(image.size, (1200, 800))


class ValidationTests(IntegrationCase):
    @needs(USER_MOD)
    def test_validate_user_mod_finds_both_unclosed_blocks(self):
        self.set_mod(USER_MOD)
        self.assertTrue(self.project.validate_button.isEnabled())
        progress = []
        self.project.validation._runner.progress.connect(progress.append)
        gaps = []
        clock = QElapsedTimer()
        heartbeat = QTimer()
        heartbeat.setInterval(10)
        heartbeat.timeout.connect(lambda: gaps.append(clock.restart()))
        started = time.perf_counter()
        clock.start()
        heartbeat.start()
        self.assertTrue(self.project.validate_mod())
        self.assertTrue(self.project.is_busy())
        self.assertIs(self.project.left_tabs.currentWidget(), self.project.validation)
        self.wait(lambda: self.project.validation_report() is not None, "la validación no terminó", 60000)
        elapsed = time.perf_counter() - started
        heartbeat.stop()
        gaps.sort()
        report = self.project.validation_report()
        print(f"\n[ui] Validar mod VSM: {report.files} archivos en {elapsed:.2f} s "
              f"({len(progress)} notificaciones de progreso); hilo de la interfaz: "
              f"p95 {gaps[int(len(gaps) * 0.95)]} ms, máximo {gaps[-1]} ms entre latidos de 10 ms", file=sys.stderr)
        self.assertLess(gaps[-1] / 1000, STALL_LIMIT_SECONDS, "la interfaz se congeló durante la validación")
        descriptor = USER_MOD.parent / "VSM.mod"
        self.assertEqual(report.files, len(collect_files(USER_MOD)) + int(descriptor.is_file()),
                         "se validan todos los archivos del mod y su descriptor")
        self.assertGreater(report.files, 3900)
        unclosed = [i for i in report.issues if i.code == "unclosed_block"]
        self.assertEqual(sorted((i.relative, i.line) for i in unclosed),
                         [("decisions/somaliland_shago.txt", 1), ("decisions/zulu_expancionshago.txt", 1)])
        self.assertTrue(all(i.severity is Severity.ERROR for i in unclosed))
        # El tercer archivo con errores es el diario de desarrollo en prosa de Paradox.
        self.assertEqual(report.files_with(Severity.ERROR),
                         ["decisions/somaliland_shago.txt", "decisions/zulu_expancionshago.txt",
                          "history/units/v2dd2.txt"])
        self.assertTrue(progress and progress[-1][0] == progress[-1][1] == report.files)

        panel = self.project.validation
        self.assertEqual(panel.model.rowCount(), len(report.issues))
        first = [panel.model.index(r, 1).data() for r in range(2)]
        self.assertEqual(first, ["decisions/somaliland_shago.txt", "decisions/zulu_expancionshago.txt"])
        self.assertIn("(3)", self.project.left_tabs.tabText(1))
        panel.severity_combo.setCurrentIndex(1)  # solo errores
        self.assertEqual(panel.model.rowCount(), 3)
        panel.filter_edit.setText("zulu")
        panel._apply_filter()
        self.assertEqual(panel.model.rowCount(), 1)
        panel.filter_edit.clear()
        panel._apply_filter()

        # Doble clic: abre el archivo en la vista previa, en esa línea.
        double_click(panel.view, panel.model.index(0, 3))
        viewer = self.project.clausewitz_viewer
        self.wait(lambda: viewer.current_load() is not None and viewer.current_load().path == SOMALILAND,
                  "el doble clic no abrió el archivo")
        self.wait(lambda: viewer.current_tab() == TAB_SOURCE and viewer.code.current_line() == 1,
                  "no saltó a la línea del error", 3000)
        self.assertIs(self.project.left_tabs.currentWidget(), panel, "el informe debe seguir a la vista")

        # Una fila de CSV abre el archivo en Localización, en esa fila.
        panel.severity_combo.setCurrentIndex(0)
        csv_row = next(r for r in range(panel.model.rowCount())
                       if panel.model.index(r, 1).data().endswith("00_VSM_decisions.csv"))
        row = panel.model.index(csv_row, 0).data(ROW_ROLE)
        panel.view.activated.emit(panel.model.index(csv_row, 0))
        self.wait(lambda: self.localisation.editor.current_load() is not None, "el CSV no se abrió")
        self.assertEqual(self.window.current_page_index(), PAGE_KEYS.index("localisation"))
        self.assertEqual(self.localisation.editor.selected_line(), row.line)

        set_language("en")
        self.assertIn("Files checked", panel.summary.text())
        set_language("es")

    def test_validate_needs_a_mod_and_never_the_game(self):
        self.assertFalse(self.project.validate_button.isEnabled())
        self.assertFalse(self.project.validate_mod())
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "Victoria 2"
            for name in ("common", "history", "localisation", "map", "events", "interface"):
                (game / name).mkdir(parents=True)
            (game / "v2game.exe").write_bytes(b"MZ")
            self.project.set_mod_path(game)
            self.assertFalse(self.project.validate_button.isEnabled())
            self.assertFalse(self.project.validate_mod())
            mod = Path(tmp) / "mod" / "Tiny"
            (mod / "events").mkdir(parents=True)
            (mod / "events" / "bad.txt").write_text("country_event = {\n\tid = 1\n", encoding="cp1252")
            (mod / "events" / "good.txt").write_text("a = b\n", encoding="cp1252")
            self.set_mod(mod)
            self.assertTrue(self.project.validate_mod())
            self.wait(lambda: self.project.validation_report() is not None, "la validación no terminó")
            report = self.project.validation_report()
            self.assertEqual(report.files, 2)
            self.assertEqual(report.files_with(), ["events/bad.txt"])
            # Cambiar de mod deja el informe anterior sin validez.
            self.project.set_mod_path(None)
            self.assertIsNone(self.project.validation_report())


class LocalisationIntegrationTests(IntegrationCase):
    @needs(TEXT_CSV)
    def test_text_csv_rows_timing_and_responsiveness(self):
        expected = read_csv_file(TEXT_CSV)
        data_rows = sum(1 for r in expected.rows if r.kind is RowKind.DATA)
        editor = self.localisation.editor
        gaps = []
        clock = QElapsedTimer()
        heartbeat = QTimer()
        heartbeat.setInterval(10)

        def beat():
            gaps.append(clock.restart())
        heartbeat.timeout.connect(beat)
        clock.start()
        heartbeat.start()
        started = time.perf_counter()
        self.window.open_in_localisation(TEXT_CSV)
        self.wait(lambda: editor.current_load() is not None and editor.table.isVisible(), "text.csv no cargó")
        editor.table.viewport().repaint()
        elapsed = time.perf_counter() - started
        _qt.process_events(50)
        heartbeat.stop()
        stall = max(gaps) / 1000 if gaps else 0.0
        print(f"\n[ui] text.csv ({TEXT_CSV.stat().st_size / 1e6:.1f} MB, {len(expected.rows)} filas): "
              f"visible en {elapsed:.2f} s; mayor bloqueo del hilo de la interfaz {stall * 1000:.0f} ms",
              file=sys.stderr)
        self.assertLess(elapsed, CSV_LIMIT_SECONDS)
        self.assertLess(stall, STALL_LIMIT_SECONDS, "la interfaz se congeló durante la carga")
        self.assertEqual(self.window.current_page_index(), PAGE_KEYS.index("localisation"))
        self.assertEqual(editor.model.rowCount(), len(expected.rows))
        self.assertEqual(editor.visible_rows(), data_rows, "comentarios y líneas vacías ocultos por defecto")
        self.assertIn(f"{len(expected.rows):,}".replace(",", "."), editor.count_label.text())
        self.assertEqual(editor.diagnostics_model.rowCount(), len(expected.diagnostics))
        self.assertTrue(editor.read_only.isVisible())
        self.assertTrue(self.localisation.search_edit.isEnabled())

        first = editor.proxy.index(0, 0)
        row = next(r for r in expected.rows if r.kind is RowKind.DATA)
        self.assertEqual(first.data(), row.key)
        self.assertEqual(editor.proxy.index(0, 1).data(), row.get("en"))
        self.assertEqual(editor.proxy.index(0, 2).data(), row.get("es"))
        headers = [editor.proxy.headerData(c, Qt.Orientation.Horizontal) for c in range(5)]
        self.assertEqual(headers, ["Clave", "English", "Español (Spanish)", "Français (French)", "Deutsch (German)"])
        self.assertTrue(editor.table.isColumnHidden(5))
        editor.columns_check.setChecked(True)
        self.assertFalse(editor.table.isColumnHidden(5))

        editor.comments_check.setChecked(True)
        self.assertEqual(editor.visible_rows(), len(expected.rows))
        editor.comments_check.setChecked(False)

        started = time.perf_counter()
        self.localisation.search_edit.setText("ledger_country")
        self.wait(lambda: editor.visible_rows() < data_rows, "la búsqueda no filtró")
        searched = time.perf_counter() - started
        wanted = sum(1 for r in expected.rows if r.kind is RowKind.DATA and "ledger_country" in
                     "\x00".join([r.key, *r.fields[:13]]).casefold())
        self.assertEqual(editor.visible_rows(), wanted)
        print(f"[ui] búsqueda en text.csv: {wanted} filas en {searched:.2f} s (con 150 ms de espera)",
              file=sys.stderr)
        # Seleccionar una línea oculta por el filtro vacía el buscador.
        hidden = next(r for r in expected.rows if r.kind is RowKind.DATA and "ledger" not in r.key.lower())
        self.assertTrue(editor.select_line(hidden.line))
        self.assertEqual(self.localisation.search_edit.text(), "")
        self.assertEqual(editor.selected_line(), hidden.line)

    @needs(VSM_DECISIONS_CSV)
    def test_user_csv_lint_and_language_switch(self):
        expected = read_csv_file(VSM_DECISIONS_CSV)
        self.window.open_in_localisation(VSM_DECISIONS_CSV)
        editor = self.localisation.editor
        self.wait(lambda: editor.current_load() is not None, "el CSV no cargó")
        codes = [r.code for r in editor.diagnostics_model.all_rows()]
        self.assertEqual(codes.count("semicolon_in_quotes"), 6)
        self.assertEqual(codes.count("header_row"), 1)
        self.assertEqual(len(codes), len(expected.diagnostics))
        quoted = next(r for r in editor.diagnostics_model.all_rows() if r.code == "semicolon_in_quotes")
        model = editor.diagnostics_model
        row_index = model.all_rows().index(quoted)
        editor.diagnostics_view.activated.emit(model.index(row_index, 2))
        self.assertEqual(editor.selected_line(), quoted.line)
        key_index = editor.table.currentIndex().siblingAtColumn(0)
        self.assertFalse(key_index.data(Qt.ItemDataRole.DecorationRole) is None)
        self.assertIn("•", key_index.data(Qt.ItemDataRole.ToolTipRole))

        spanish = model.data(model.index(row_index, 2))
        set_language("en")
        self.assertEqual(model.data(model.index(row_index, 2)), quoted.source.message("en"))
        self.assertNotEqual(model.data(model.index(row_index, 2)), spanish)
        self.assertEqual(editor.proxy.headerData(0, Qt.Orientation.Horizontal), "Key")
        self.assertIn("Read-only", editor.read_only.text())
        set_language("es")
        self.assertIn("Solo lectura", editor.read_only.text())

    def test_csv_click_opens_localisation_but_keyboard_only_previews(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp) / "CsvMod"
            (mod / "localisation").mkdir(parents=True)
            first = mod / "localisation" / "a.csv"
            second = mod / "localisation" / "b.csv"
            first.write_bytes(b"#comentario;;;;;;;;;;;;;;x\nKEY_A;Hello;;;;Hola;;;;;;;;;x\n")
            second.write_bytes(b"KEY_B;Bye;;;;Adios;;;;;;;;;x\n")
            self.set_mod(mod)
            self.assertTrue(self.project.reveal_file(first))
            self.wait(lambda: not self.project.is_busy(), "el explorador no terminó")
            _qt.process_events(50)
            # Selección (como con las flechas): solo la ficha con el botón «Abrir en Localización».
            self.assertEqual(self.window.current_page_index(), 0)
            self.assertIsNone(self.project.preview_widget())
            self.assertTrue(self.project.preview.csv_button.isVisibleTo(self.project.preview))
            # Clic con el ratón: se abre en Localización.
            index = self.project.tree.currentIndex()
            rect = self.project.tree.visualRect(index)
            QTest.mouseClick(self.project.tree.viewport(), Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier, rect.center())
            editor = self.localisation.editor
            self.wait(lambda: editor.current_load() is not None and editor.current_load().path == first,
                      "el clic no abrió el CSV")
            self.assertEqual(self.window.current_page_index(), PAGE_KEYS.index("localisation"))
            self.assertEqual(editor.visible_rows(), 1)
            self.assertEqual(editor.proxy.index(0, 2).data(), "Hola")
            # El botón de la ficha también lo abre.
            self.window.set_current_page(0)
            self.assertTrue(self.project.reveal_file(second))
            _qt.process_events(30)
            self.project.preview.csv_button.click()
            self.wait(lambda: editor.current_load() is not None and editor.current_load().path == second,
                      "el botón no abrió el CSV")
            self.assertEqual(self.window.current_page_index(), PAGE_KEYS.index("localisation"))
            self.localisation.close_file()
            self.assertIs(self.localisation.stack.currentWidget(), self.localisation.empty_card)
            self.assertFalse(self.localisation.search_edit.isEnabled())


if __name__ == "__main__":
    unittest.main()
