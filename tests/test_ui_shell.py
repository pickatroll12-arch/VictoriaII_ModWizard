"""Armazón de la iteración 2 (offscreen): registro de salas, catálogos por fragmentos, insignias de capa, panel de
cambios pendientes y la ventana con un proyecto abierto (guardar según D13, deshacer, conflictos, cerrar con
cambios, recuperación), contra el ``Project`` falso de ``_fake_project``; ``test_ui_real_project`` repite las de
la ventana con un proyecto abierto contra el ``Project`` real (``make_opener``).
"""

import fnmatch
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
from _fake_project import FakeOpener, FakeSaveProblem, Rel, isolate_app_dirs  # noqa: E402
from _layers import build_layers  # noqa: E402
from PySide6.QtCore import QEvent, QObject, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QDialog, QStyleOptionViewItem, QWidget  # noqa: E402
from test_ui_smoke import UiTestCase  # noqa: E402

APP = _qt.application()
isolate_app_dirs()

from vic2studio import i18n  # noqa: E402
from vic2studio.core.clausewitz import to_source  # noqa: E402
from vic2studio.core.project import ChangeSet, PlannedWrite, WriteAction  # noqa: E402
from vic2studio.core.project.model import SAVE_CONFLICT, RecoveryResult, SaveProblem  # noqa: E402
from vic2studio.core.vfs import DESCRIPTOR_REL, VPath  # noqa: E402
from vic2studio.i18n import N_, set_language, tr, translator  # noqa: E402
from vic2studio.ui.dialogs import ConflictDialog, NewModDialog, RecoveryDialog, SaveReviewDialog  # noqa: E402
from vic2studio.ui.halls import HALL_KEYS, HallSpec, SectionSpec, discover_halls  # noqa: E402
from vic2studio.ui.halls import registry  # noqa: E402
from vic2studio.ui.main_window import UNSAVED_CANCEL, UNSAVED_DISCARD, UNSAVED_SAVE, MainWindow  # noqa: E402
from vic2studio.ui.session import Session  # noqa: E402
from vic2studio.ui.shell.pending_changes import (  # noqa: E402
    PendingChangesPanel,
    changed_lines,
    display_diff,
    write_label,
)
from vic2studio.ui.widgets import icon_names, icons_extra  # noqa: E402
from vic2studio.ui.widgets.layer_badge import (  # noqa: E402
    COLORS,
    LAYER_GAME,
    LAYER_MOD,
    LAYER_OVERRIDE,
    LayerResolver,
    layer_text,
    layer_tooltip,
)

ROOT = Path(__file__).resolve().parents[1]
I18N = ROOT / "src" / "vic2studio" / "i18n"
GAME = {
    "common/countries.txt": 'AAA = "countries/Aland.txt"\r\n',
    "common/cb_types.txt": "peace_order = { }\r\n",
    "map/Default.map": "max_provinces = 10\r\n",
    "mod/Other/common/goods.txt": "x = 1\r\n",       # otro mod dentro de <juego>/mod: no es del juego base
}
MOD = {
    "common/countries.txt": 'BBB = "countries/Borea.txt"\r\n',
    "common/vsm_new.txt": "y = 2\r\n",
    "MAP/default.MAP": "max_provinces = 12\r\n",     # sustituye a map/Default.map aunque cambien las mayúsculas
}


# --- registro de salas ---------------------------------------------------------------------------------------


class RegistryTests(unittest.TestCase):
    def test_discovers_the_seven_halls_in_order(self):
        halls = discover_halls()
        self.assertEqual([hall.key for hall, _ in halls], list(HALL_KEYS))
        self.assertEqual([hall.order for hall, _ in halls], list(range(1, 8)))
        for hall, sections in halls:
            with self.subTest(hall=hall.key):
                self.assertTrue(sections)
                self.assertEqual([s.order for s in sections], sorted(s.order for s in sections))
                self.assertEqual({s.hall for s in sections}, {hall.key})
        self.assertEqual([s.key for s in dict(halls_by_key(halls))["project"]],
                         ["home", "descriptor", "files", "validation", "pending"])
        self.assertEqual([s.key for s in dict(halls_by_key(halls))["localisation"]], ["all", "pending", "csv"])

    def test_every_text_key_and_icon_exists(self):
        icons_extra.load()
        icons = set(icon_names())
        for code in ("es", "en"):
            catalog = translator().catalog(code)
            for hall, sections in discover_halls():
                keys = [hall.plate_key, hall.title_key, hall.subtitle_key]
                for section in sections:
                    keys += [section.title_key, *section.planned_keys]
                missing = [key for key in keys if key not in catalog]
                self.assertEqual(missing, [], f"{code}:{hall.key}")
                self.assertIn(hall.icon, icons)
                self.assertEqual([s.icon for s in sections if s.icon not in icons], [], hall.key)

    def test_planned_means_no_factory_and_no_schema(self):
        ready = SectionSpec("a", "map", 1, "nav.map", "map", factory=lambda session: None)
        planned = SectionSpec("b", "map", 2, "nav.map", "map", iteration=5)
        schema = SectionSpec("c", "map", 3, "nav.map", "map", schema_kind="province")
        self.assertEqual((ready.planned, planned.planned, schema.planned), (False, True, False))

    def test_inconsistent_halls_are_rejected(self):
        hall = HallSpec("map", 2, "hall.map.plate", "nav.map", "hall.map.subtitle", "map")
        good = SectionSpec("world", "map", 1, "nav.map", "map", iteration=5)
        registry._check_hall(hall, [good])  # coherente: no lanza
        cases = {
            "desconocida": (HallSpec("nope", 9, "a.b", "a.b", "a.b", "map"), [good]),
            "misma clave u orden.*'world', 'world'": (
                hall, [good, SectionSpec("world", "map", 2, "nav.map", "map", iteration=5)]),
            r"misma clave u orden.*\[1, 1\]": (
                hall, [good, SectionSpec("other", "map", 1, "nav.map", "map", iteration=5)]),
            "dice ser de": (hall, [SectionSpec("world", "war", 1, "nav.map", "map", iteration=5)]),
            "iteración": (hall, [SectionSpec("world", "map", 1, "nav.map", "map")]),
        }
        for message, (spec, sections) in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                registry._check_hall(spec, sections)

    def test_two_halls_with_the_same_order_are_rejected(self):
        twin = SimpleNamespace(HALL=HallSpec("map", 1, "hall.map.plate", "nav.map", "hall.map.subtitle", "map"),
                               SECTIONS=[SectionSpec("world", "map", 1, "nav.map", "map", iteration=5)])
        modules = {"vic2studio.ui.halls.map": twin}
        real = registry.importlib.import_module
        with mock.patch.object(registry.importlib, "import_module",
                               side_effect=lambda name: modules.get(name) or real(name)):
            with self.assertRaisesRegex(ValueError, "orden"):
                discover_halls()


def halls_by_key(halls):
    return [(hall.key, sections) for hall, sections in halls]


# --- catálogos por fragmentos ----------------------------------------------------------------------------------


class CatalogFragmentTests(unittest.TestCase):
    def test_fragments_are_flat_utf8_json_without_bom(self):
        for code in ("es", "en"):
            paths = i18n.fragment_paths(code)
            self.assertEqual([p.name for p in paths],
                             ["countries.json", "entity.json", "events.json", "forms.json", "interface.json",
                              "localisation.json", "map.json", "palette.json", "pickers.json", "project.json",
                              "script.json", "shell.json", "validation.json", "war.json"],
                             # +3 de la it. 4, +2 de la 6, +2 de la 7 y +1 de la 8
                             code)
            for path in paths:
                raw = path.read_bytes()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), path)
                data = json.loads(raw.decode("utf-8"))
                self.assertTrue(data and all(isinstance(v, str) for v in data.values()), path)
                self.assertEqual(list(data), sorted(data), f"{path}: claves en orden alfabético")

    def test_each_fragment_has_the_same_keys_in_both_languages(self):
        for es_path, en_path in zip(i18n.fragment_paths("es"), i18n.fragment_paths("en")):
            self.assertEqual(es_path.name, en_path.name)
            es = json.loads(es_path.read_text(encoding="utf-8"))
            en = json.loads(en_path.read_text(encoding="utf-8"))
            self.assertEqual(sorted(set(es) ^ set(en)), [], es_path.name)

    def test_ui_catalog_is_the_base_file_plus_its_fragments(self):
        for code in ("es", "en"):
            base = json.loads(i18n.catalog_path(code).read_text(encoding="utf-8"))
            fragments = {}
            for path in i18n.fragment_paths(code):
                fragments.update(json.loads(path.read_text(encoding="utf-8")))
            catalog = i18n.ui_catalog(code)
            self.assertEqual(catalog, {**base, **fragments})
            self.assertEqual(len(catalog), len(base) + len(fragments), "ninguna clave en dos archivos")
            self.assertIn("hall.nations.plate", catalog)
            self.assertIn("descriptor.create", catalog)

    def test_a_key_in_two_files_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            again = Path(tmp) / "again.json"
            again.write_text(json.dumps({"nav.map": "Otra vez"}), encoding="utf-8")
            extra = Path(tmp) / "extra.json"
            extra.write_text(json.dumps({"extra.one": "Uno"}), encoding="utf-8")
            with mock.patch.object(i18n, "fragment_paths", return_value=[extra]):
                self.assertEqual(i18n.ui_catalog("es")["extra.one"], "Uno")
            with mock.patch.object(i18n, "fragment_paths", return_value=[extra, again]):
                with self.assertRaisesRegex(ValueError, r"'nav\.map'.*es\.json.*again\.json"):
                    i18n.ui_catalog("es")
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(["no", "es", "un", "objeto"]), encoding="utf-8")
            with mock.patch.object(i18n, "fragment_paths", return_value=[bad]):
                with self.assertRaisesRegex(ValueError, "mal formado"):
                    i18n.ui_catalog("es")

    def test_core_texts_are_merged_and_may_not_repeat_a_key(self):
        with mock.patch.object(i18n, "core_catalog", return_value={"save.sample": "Texto del núcleo"}):
            self.assertEqual(i18n.load_catalog("es")["save.sample"], "Texto del núcleo")
        with mock.patch.object(i18n, "core_catalog", return_value={"nav.map": "Repetida"}):
            with self.assertRaisesRegex(ValueError, r"'nav\.map'.*core"):
                i18n.load_catalog("es")

    def test_core_catalog_reads_core_texts(self):
        from vic2studio.core import texts

        with mock.patch.object(texts, "load_texts", return_value={"save.sample": "x"}) as load:
            self.assertEqual(i18n.core_catalog("en"), {"save.sample": "x"})
        load.assert_called_once_with("en")
        # Con el núcleo integrado, sus textos llegan al catálogo (y un fallo al leerlos no se calla).
        for code in ("es", "en"):
            core = i18n.core_catalog(code)
            self.assertIn("project.save_conflict", core, code)
            self.assertEqual(i18n.load_catalog(code)["project.save_conflict"], core["project.save_conflict"])
        with mock.patch.object(texts, "load_texts", side_effect=ValueError("JSON mal formado")):
            with self.assertRaises(ValueError):
                i18n.core_catalog("en")


class PackagingTests(unittest.TestCase):
    def test_wheel_ships_the_fragments_and_the_core_texts(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        block = re.search(r"\[tool\.setuptools\.package-data\]\s*vic2studio\s*=\s*\[(.*?)\]", text, re.S)
        self.assertIsNotNone(block)
        patterns = re.findall(r'"([^"]+)"', re.sub(r"#.*", "", block.group(1)))
        self.assertIn("i18n/*.json", patterns)
        self.assertIn("i18n/*/*.json", patterns)
        self.assertIn("core/**/texts/*.json", patterns)
        package = ROOT / "src" / "vic2studio"
        for code in ("es", "en"):
            for path in i18n.fragment_paths(code):
                rel = path.relative_to(package).as_posix()
                self.assertTrue(any(fnmatch.fnmatch(rel, p) for p in patterns), rel)


class HarnessTests(unittest.TestCase):
    def test_interface_tests_never_use_the_real_application_folders(self):
        """Una ventana que abre un mod usa el Project real, y su bloqueo va a la carpeta de datos."""
        from vic2studio.core import appdirs

        for folder in (appdirs.data_dir(), appdirs.cache_dir(), appdirs.locks_dir()):
            self.assertTrue(folder.is_relative_to(_qt.APP_DIRS), folder)

    @unittest.skipUnless(sys.platform.startswith("linux"), "XDG_RUNTIME_DIR solo existe en Linux")
    def test_runtime_dir_is_set_so_qt_6_5_0_does_not_warn(self):
        """Qt 6.5.0 avisa al crear la aplicación sin XDG_RUNTIME_DIR (contenedores y CI) y el aviso haría fallar
        la primera prueba que mira ``take_qt_messages``."""
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", ""))
        self.assertTrue(runtime.is_dir(), runtime)
        self.assertEqual(runtime.stat().st_mode & 0o777, 0o700)


class _ShownWindows(QObject):
    """Filtro de la aplicación que anota cada widget que se muestra como ventana."""

    def __init__(self):
        super().__init__()
        self.shown: list[str] = []

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            self.shown.append(f"{type(obj).__name__} {obj.objectName()!r}")
        return False


class StrayWindowTests(UiTestCase):
    """Construir la interfaz no muestra nada: un ``setVisible(True)`` antes de que el widget tenga padre lo
    convierte en una ventana suelta que se ve un instante (y Qt 6.5 offscreen avisa al meterla en su sitio)."""

    def test_building_the_window_pages_and_dialogs_shows_no_window(self):
        spy = _ShownWindows()
        APP.installEventFilter(spy)
        self.addCleanup(APP.removeEventFilter, spy)
        window = self.make_window(show=False)
        for hall, sections in discover_halls():
            for section in sections:
                window.page(f"{hall.key}:{section.key}")
        conflict = SaveProblem(SAVE_CONFLICT, VPath.of("common/a.txt"))
        dialogs = [
            RecoveryDialog(["s-1", "s-2"], [RecoveryResult("t", "rolled_back", restored=(VPath.of("a.txt"),))], window),
            SaveReviewDialog(ChangeSet(), (conflict,), window),
            SaveReviewDialog(ChangeSet(), (), window),
            ConflictDialog("common/a.txt", lambda: "", parent=window),
            NewModDialog(window.session, None, window),
            *self.iteration3_dialogs(window),
        ]
        _qt.process_events()
        self.assertEqual(spy.shown, [])
        for dialog in dialogs:
            dialog.deleteLater()

    @staticmethod
    def iteration3_dialogs(window) -> list:
        """«Añadir clave» y el plan de un arreglo (seguro y no seguro), sin proyecto: no deben mostrar nada."""
        from _fake_index import FakeValidationEngine, problem

        from vic2studio.core.validate.model import ChangePlan, PlannedChange
        from vic2studio.ui.dialogs.add_key import AddKeyDialog
        from vic2studio.ui.dialogs.fix_plan import FixPlanDialog

        locsync = SimpleNamespace(where=lambda key: None,
                                  target_file=lambda area: VPath.of(f"localisation/00_X_{area}.csv"))
        fixes = FakeValidationEngine().fixes
        sil = problem("tag_not_registered", "history/countries/SIL - Silesia.txt", 1, tag="SIL")
        copy = problem("mod_shadow_identical", "common/a.txt")
        plan = ChangePlan("x", (PlannedChange(VPath.of("common/a.txt"), "trash"),))
        return [AddKeyDialog(locsync, window), FixPlanDialog(fixes["register_tag"], sil, plan, window),
                FixPlanDialog(fixes["trash_identical_copies"], copy, plan, window)]


# --- insignias de capa ---------------------------------------------------------------------------------------


class LayerResolverTests(unittest.TestCase):
    def setUp(self):
        self.layers = build_layers(game=GAME, mod=MOD, mod_name="VSM")
        self.addCleanup(self.layers.cleanup)
        self.resolver = LayerResolver(self.layers.game_root, self.layers.mod_root)

    def test_layers_of_game_and_mod_files(self):
        layer_of = self.resolver.layer_of
        self.assertEqual(layer_of(self.layers.mod("common/countries.txt")), LAYER_OVERRIDE)
        self.assertEqual(layer_of(self.layers.game("common/countries.txt")), LAYER_OVERRIDE)
        self.assertEqual(layer_of(self.layers.mod("common/vsm_new.txt")), LAYER_MOD)
        self.assertEqual(layer_of(self.layers.game("common/cb_types.txt")), LAYER_GAME)
        # Sin distinguir mayúsculas, como Windows.
        self.assertEqual(layer_of(self.layers.mod("MAP/default.MAP")), LAYER_OVERRIDE)
        self.assertEqual(layer_of(self.layers.game("map/Default.map")), LAYER_OVERRIDE)
        # Las carpetas, los mods de <juego>/mod y lo que no está en ninguna de las dos no llevan insignia.
        self.assertIsNone(layer_of(self.layers.mod("common")))
        self.assertIsNone(layer_of(self.layers.game("mod/Other/common/goods.txt")))
        self.assertIsNone(layer_of(self.layers.descriptor))
        self.assertIsNone(layer_of(Path(tempfile.gettempdir()) / "nada.txt"))

    def test_without_game_everything_in_the_mod_is_mod(self):
        resolver = LayerResolver(None, self.layers.mod_root)
        self.assertEqual(resolver.layer_of(self.layers.mod("common/countries.txt")), LAYER_MOD)
        self.assertIsNone(resolver.layer_of(self.layers.game("common/cb_types.txt")))

    def test_answers_are_cached_until_invalidated(self):
        path = self.layers.game("common/cb_types.txt")
        self.assertEqual(self.resolver.layer_of(path), LAYER_GAME)
        copy = self.layers.mod("common/cb_types.txt")
        copy.write_bytes(path.read_bytes())
        self.assertEqual(self.resolver.layer_of(path), LAYER_GAME, "aún la respuesta guardada")
        self.resolver.invalidate()
        self.assertEqual(self.resolver.layer_of(path), LAYER_OVERRIDE)
        self.assertEqual(self.resolver.layer_of(copy), LAYER_OVERRIDE)
        self.resolver.set_roots(None, self.layers.mod_root)
        self.assertEqual(self.resolver.layer_of(copy), LAYER_MOD, "set_roots olvida lo guardado")

    def test_short_texts_and_tooltips_in_both_languages(self):
        self.addCleanup(set_language, "es")
        expected = {"es": ("J", "M", "M⊃J"), "en": ("G", "M", "M⊃G")}
        for code, texts in expected.items():
            set_language(code)
            self.assertEqual(tuple(layer_text(layer) for layer in (LAYER_GAME, LAYER_MOD, LAYER_OVERRIDE)), texts)
            tips = [layer_tooltip(layer) for layer in (LAYER_GAME, LAYER_MOD, LAYER_OVERRIDE)]
            self.assertEqual(len(set(tips)), 3)
            self.assertTrue(all(len(tip) > len(text) for tip, text in zip(tips, texts)), tips)


# --- panel de cambios pendientes ------------------------------------------------------------------------------


def _write(rel: str, action: WriteAction, target: Path, before: str | None, after: str | None) -> PlannedWrite:
    import difflib

    old = [] if before is None else before.splitlines(keepends=True)
    new = [] if after is None else after.splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(old, new, f"a/{rel}", f"b/{rel}")) if action is not WriteAction.TRASH else ""
    path_rel = DESCRIPTOR_REL if rel == str(DESCRIPTOR_REL) else Rel.of(rel)
    return PlannedWrite(path_rel, target, action, None if after is None else after.encode("cp1252"), None, diff)


class PendingPanelTests(UiTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="vic2studio-pending-"))
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        mod = self.tmp / "mod" / "VSM"
        self.writes = (
            _write("common/countries.txt", WriteAction.MODIFY, mod / "common/countries.txt",
                   "AAA = x\nBBB = y\n", "AAA = x\nBBB = z\nCCC = w\n"),
            _write("common/cb_types.txt", WriteAction.COPY_FROM_GAME, mod / "common/cb_types.txt",
                   "peace = { }\n", "peace = { badboy = 1 }\n"),
            _write("events/old.txt", WriteAction.TRASH, mod / "events/old.txt", "x = 1\n", None),
            _write(str(DESCRIPTOR_REL), WriteAction.MODIFY, self.tmp / "mod" / "VSM.mod",
                   'name = "VSM"\n', 'name = "VSM 2"\n'),
        )

    def test_labels_diffs_and_line_counts(self):
        modify, copy, trash, descriptor = self.writes
        self.assertEqual(write_label(modify), "common/countries.txt")
        self.assertEqual(write_label(descriptor), "VSM.mod")
        shown = display_diff(descriptor)
        self.assertNotIn(str(DESCRIPTOR_REL), shown)
        self.assertTrue(shown.startswith("--- a/VSM.mod\n+++ b/VSM.mod\n"), shown)
        self.assertEqual(display_diff(modify), modify.diff)
        self.assertEqual(changed_lines(modify.diff), (2, 1))
        self.assertEqual(changed_lines(trash.diff), (0, 0))

    def test_panel_lists_the_writes_and_shows_the_selected_diff(self):
        panel = PendingChangesPanel()
        self.addCleanup(_qt.dispose, panel)
        panel.resize(700, 500)
        panel.set_changeset(ChangeSet(self.writes))
        tree = panel.tree
        self.assertEqual(tree.topLevelItemCount(), 4)
        rows = [[tree.topLevelItem(i).text(c) for c in range(3)] for i in range(4)]
        self.assertEqual([row[0] for row in rows], ["common/countries.txt", "common/cb_types.txt", "events/old.txt",
                                                    "VSM.mod"])
        self.assertEqual([row[1] for row in rows], [tr("pending.action.modify"), tr("pending.action.copy"),
                                                    tr("pending.action.trash"), tr("pending.action.modify")])
        self.assertEqual(rows[0][2], tr("pending.lines", added=2, removed=1))
        self.assertEqual(rows[2][2], "")
        self.assertIn("4", panel.summary.text())
        self.assertIn(tr("pending.summary_copies_one", count=1), panel.summary.text())
        self.assertIn(tr("pending.summary_trash", count=1), panel.summary.text())
        # La primera queda seleccionada; seleccionar otra muestra su diff.
        self.assertIs(panel.current_write(), self.writes[0])
        self.assertEqual(panel.diff.toPlainText(), self.writes[0].diff)
        selected = []
        panel.selection_changed.connect(selected.append)
        self.assertTrue(panel.select(DESCRIPTOR_REL))
        self.assertEqual(selected, [self.writes[3]])
        self.assertIn("+++ b/VSM.mod", panel.diff.toPlainText())
        self.assertIn("VSM.mod", panel.diff_caption.text())
        self.assertTrue(panel.select("events/old.txt"))
        self.assertEqual(panel.diff.toPlainText(), "")
        self.assertEqual(panel.diff_caption.text(), tr("pending.diff_trash", name="events/old.txt"))
        self.assertFalse(panel.select("nope.txt"))
        # Volver a llenarlo conserva la selección; vaciarlo lo dice.
        panel.set_changeset(ChangeSet(self.writes[1:]))
        self.assertEqual(str(panel.current_write().rel), "events/old.txt")
        set_language("en")
        panel.retranslate()  # lo llama quien lo contiene (la sección o el diálogo) al cambiar de idioma
        self.assertEqual(tree.headerItem().text(1), "Action")
        self.assertEqual(tree.topLevelItem(0).text(1), tr("pending.action.copy"))
        self.assertEqual(panel.diff_caption.text(), tr("pending.diff_trash", name="events/old.txt"))
        panel.set_changeset(ChangeSet())
        self.assertEqual(panel.summary.text(), tr("pending.summary_none"))
        self.assertEqual(panel.diff_caption.text(), tr("pending.diff_none"))


# --- la ventana con un proyecto abierto -------------------------------------------------------------------------


class DialogLog:
    """Sustituye a ``MainWindow.exec_dialog``: anota cada diálogo y lo resuelve con ``handler(dialog)``."""

    def __init__(self):
        self.dialogs: list[QDialog] = []
        self.handlers: dict[type, object] = {}

    def __call__(self, dialog: QDialog) -> int:
        self.dialogs.append(dialog)
        handler = self.handlers.get(type(dialog))
        try:
            if handler is None:
                return QDialog.DialogCode.Rejected
            handler(dialog)
            return dialog.result()
        finally:
            dialog.deleteLater()

    def types(self) -> list[type]:
        return [type(dialog) for dialog in self.dialogs]


class ProjectWindowCase(UiTestCase):
    """Ventana con ``Session(opener=FakeOpener)`` y un mod VSM dentro de un juego base sintético."""

    def setUp(self):
        super().setUp()
        self.layers = build_layers(game=GAME, mod=MOD, mod_name="VSM")
        self.addCleanup(self.layers.cleanup)
        self.dialogs = DialogLog()   # ningún diálogo se abre de verdad: se anotan y se resuelven con handlers

    def make_opener(self, **options):
        """El ``Project`` falso; ``test_ui_real_project`` repite estas pruebas con ``Project.open``."""
        return FakeOpener(**options)

    def open_window(self, **options) -> MainWindow:
        self.opener = self.make_opener(**options)
        window = self.make_window(session=Session(opener=self.opener))
        window.exec_dialog = self.dialogs
        window.ask_unsaved = mock.Mock(return_value=UNSAVED_DISCARD)
        page = window.page("project")
        page.set_game_path(self.layers.game_root)
        page.set_mod_path(self.layers.mod_root)
        self.assertTrue(_qt.wait_until(lambda: window.session.project is not None and not window.is_busy(), 5000),
                        "el proyecto no llegó a abrirse")
        self.window = window
        return window

    @property
    def project(self):
        return self.window.session.project

    def edit(self, rel: str = "common/countries.txt", text: str = 'BBB = "countries/Bolivia.txt"\r\n'):
        session = self.window.session
        with session.edit(N_("pending.undo_revert"), name=rel):
            handle = self.project.ws.open(Rel.of(rel))
            self.project.ws.replace_text(handle, text.encode("cp1252"))
        _qt.process_events()
        return handle

    def key(self, key: Qt.Key, modifiers=Qt.KeyboardModifier.ControlModifier) -> None:
        QTest.keyClick(self.window, key, modifiers)
        _qt.process_events()


class ShellProjectTests(ProjectWindowCase):
    def test_title_save_button_status_and_badges_follow_unsaved_changes(self):
        window = self.open_window()
        self.assertEqual(self.opener.calls, [(self.layers.game_root, self.layers.mod_root)])
        self.assertFalse(window.windowTitle().startswith("*"))
        self.assertEqual(window.save_button.text(), "Guardar")
        self.assertFalse(window.save_button.isEnabled())
        self.assertEqual(window.project_label.text(), "Mod: VSM")
        self.edit()
        self.assertTrue(window.windowTitle().startswith("* "), window.windowTitle())
        self.assertEqual(window.save_button.text(), "Guardar (1)")
        self.assertTrue(window.save_button.isEnabled())
        self.assertEqual(window.project_label.text(), "Mod: VSM · 1 archivo sin guardar")
        hall = window.hall("project")
        self.assertEqual(hall.rail.buttons[hall.section_index("pending")].badge, 1)
        self.edit("common/cb_types.txt", "peace_order = { badboy = 1 }\r\n")
        self.assertEqual(window.save_button.text(), "Guardar (2)")
        self.assertEqual(window.project_label.text(),
                         "Mod: VSM · 2 archivos sin guardar · 1 se copiará del juego base")
        set_language("en")
        self.assertEqual(window.save_button.text(), "Save (2)")
        self.assertTrue(window.windowTitle().startswith("* "))

    def test_undo_and_redo_with_the_keyboard(self):
        window = self.open_window()
        window.activateWindow()
        self.assertTrue(QTest.qWaitForWindowActive(window, 2000))
        handle = self.edit()
        self.assertTrue(window.undo_button.isEnabled())
        self.assertIn(tr("pending.undo_revert", name="common/countries.txt"), window.undo_button.toolTip())
        self.key(Qt.Key.Key_Z)
        self.assertFalse(handle.dirty)
        self.assertEqual(window.status_label.text(),
                         "Deshecho: " + tr("pending.undo_revert", name="common/countries.txt"))
        self.assertFalse(window.windowTitle().startswith("*"))
        self.assertTrue(window.redo_button.isEnabled())
        self.key(Qt.Key.Key_Y)
        self.assertTrue(handle.dirty)
        self.assertTrue(window.status_label.text().startswith("Rehecho: "))
        self.key(Qt.Key.Key_Z)
        self.key(Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        self.assertTrue(handle.dirty, "Ctrl+Mayús+Z también rehace")

    def test_history_dock_lists_the_steps_and_undoes_them(self):
        window = self.open_window()
        self.edit()
        self.edit("common/vsm_new.txt", "y = 3\r\n")
        window.history_button.click()
        _qt.process_events(20)
        dock = window.history_dock
        self.assertTrue(dock.isVisible())
        texts = [dock.list.item(i).text() for i in range(dock.list.count())]
        self.assertEqual(texts, [tr("pending.undo_revert", name="common/vsm_new.txt"),
                                 tr("pending.undo_revert", name="common/countries.txt")])
        dock.undo_button.click()
        self.assertEqual(dock.list.count(), 1)
        self.assertEqual(self.project.ws.history(), [(N_("pending.undo_revert"), {"name": "common/countries.txt"})])
        window.history_button.click()
        _qt.process_events(20)
        self.assertFalse(dock.isVisible())

    def test_save_without_copies_writes_without_asking(self):
        window = self.open_window()
        self.edit()
        window.activateWindow()
        QTest.qWaitForWindowActive(window, 2000)
        self.key(Qt.Key.Key_S)
        self.assertEqual(self.dialogs.dialogs, [], "D13: sin copias del juego ni papelera no hay revisión")
        self.assertEqual(self.layers.mod("common/countries.txt").read_bytes(), b'BBB = "countries/Bolivia.txt"\r\n')
        self.assertEqual(window.status_label.text(), "Guardado: 1 archivo.")
        self.assertFalse(window.windowTitle().startswith("*"))
        self.assertEqual(window.save_button.text(), "Guardar")
        self.assertTrue(window.save_project(), "sin cambios: no hay nada que guardar")
        self.assertEqual(window.status_label.text(), tr("status.nothing_to_save"))

    def test_save_with_a_copy_from_the_game_is_reviewed_first(self):
        window = self.open_window()
        self.edit("common/cb_types.txt", "peace_order = { badboy = 1 }\r\n")
        target = self.layers.mod("common/cb_types.txt")
        self.assertFalse(window.save_project(), "cancelar la revisión no guarda")
        self.assertEqual(self.dialogs.types(), [SaveReviewDialog])
        self.assertFalse(target.exists())
        self.assertEqual(window.status_label.text(), tr("status.save_cancelled"))
        reviewed = []
        self.dialogs.handlers[SaveReviewDialog] = lambda dialog: (reviewed.append(
            [b.label.text() for b in dialog.reasons]), dialog.save_button.click())
        self.assertTrue(window.save_project())
        self.assertEqual(reviewed, [[tr("review.reason_copies_one", count=1)]])
        self.assertEqual(target.read_bytes(), b"peace_order = { badboy = 1 }\r\n")
        self.assertEqual(window.status_label.text(), "Guardado: 1 archivo.")

    def test_a_conflict_on_save_is_resolved_and_saved(self):
        window = self.open_window()
        self.edit()
        disk = self.layers.mod("common/countries.txt")
        disk.write_bytes(b'BBB = "countries/External.txt"\r\n')
        self.dialogs.handlers[SaveReviewDialog] = lambda dialog: dialog.resolve_button.click()
        compared = []
        self.dialogs.handlers[ConflictDialog] = lambda dialog: (dialog.compare_button.click(),
                                                                compared.append(dialog.diff_view.toPlainText()),
                                                                dialog.keep_button.click())
        self.assertTrue(window.save_project())
        self.assertEqual(self.dialogs.types(), [SaveReviewDialog, ConflictDialog])
        review = self.dialogs.dialogs[0]
        self.assertEqual([p.code for p in review.problems], [SAVE_CONFLICT])
        self.assertTrue(review.resolve_button.isVisibleTo(review))
        self.assertIn(review.resolve_button, review.buttons.buttons())
        self.assertIn("External", compared[0])
        self.assertEqual(disk.read_bytes(), b'BBB = "countries/Bolivia.txt"\r\n', "«Conservar mis cambios»")

    def test_a_conflict_left_unresolved_blocks_the_save(self):
        window = self.open_window()
        self.edit()
        self.layers.mod("common/countries.txt").write_bytes(b'BBB = "countries/External.txt"\r\n')
        self.assertFalse(window.save_project())
        self.assertEqual(self.dialogs.types(), [SaveReviewDialog])
        self.assertEqual(window.status_label.text(), tr("status.save_blocked", count=1))
        self.assertEqual(self.layers.mod("common/countries.txt").read_bytes(), b'BBB = "countries/External.txt"\r\n')

    def test_external_changes_reload_clean_files_and_ask_for_dirty_ones(self):
        window = self.open_window()
        clean = self.project.ws.open(Rel.of("common/vsm_new.txt"))
        dirty = self.edit()
        self.layers.mod("common/vsm_new.txt").write_bytes(b"y = 99\r\n")
        self.layers.mod("common/countries.txt").write_bytes(b'BBB = "countries/External.txt"\r\n')
        self.dialogs.handlers[ConflictDialog] = lambda dialog: dialog.reload_button.click()
        window._on_application_state(Qt.ApplicationState.ApplicationActive)
        self.assertEqual(self.dialogs.types(), [ConflictDialog], "solo pregunta por el que tiene cambios")
        self.assertEqual(self.dialogs.dialogs[0].name, "common/countries.txt")
        self.assertIn("y = 99", to_source(clean.model.document), "el que no tenía cambios se relee sin preguntar")
        self.assertFalse(clean.dirty)
        self.assertIn("External", to_source(dirty.model.document))
        self.assertFalse(dirty.dirty, "«Recargar del disco» descarta lo que había en memoria")
        self.assertFalse(window.windowTitle().startswith("*"))

    def test_closing_with_unsaved_changes_asks(self):
        window = self.open_window()
        self.edit()
        project = self.project
        window.ask_unsaved.return_value = UNSAVED_CANCEL
        self.assertFalse(window.close(), "«Cancelar» deja la ventana abierta")
        self.assertTrue(window.isVisible())
        self.assertIs(window.session.project, project)
        window.ask_unsaved.return_value = UNSAVED_SAVE
        self.assertTrue(window.close())
        self.assertEqual(self.layers.mod("common/countries.txt").read_bytes(), b'BBB = "countries/Bolivia.txt"\r\n')
        self.assertTrue(project.closed, "cerrar la ventana cierra el proyecto (y suelta el bloqueo)")
        self.assertIsNone(window.session.project)
        self.assertEqual(window.ask_unsaved.call_count, 2)

    def test_closing_without_changes_does_not_ask(self):
        window = self.open_window()
        project = self.project
        self.assertTrue(window.close())
        window.ask_unsaved.assert_not_called()
        self.assertTrue(project.closed)

    def test_switching_mod_with_unsaved_changes_asks(self):
        other = build_layers(base=self.layers.base, game=GAME, mod={"common/x.txt": "x = 1\r\n"}, mod_name="Otro")
        window = self.open_window()
        self.edit()
        first = self.project
        window.ask_unsaved.return_value = UNSAVED_CANCEL
        window.page("project").set_mod_path(other.mod_root)
        _qt.wait_until(lambda: not window.is_busy())
        _qt.process_events(20)
        self.assertEqual(window.ask_unsaved.call_count, 1)
        self.assertEqual(window.page("project").mod_path(), self.layers.mod_root, "«Cancelar» vuelve al mod abierto")
        self.assertIs(self.project, first)
        self.assertEqual(window.session.dirty_count(), 1)
        window.ask_unsaved.return_value = UNSAVED_DISCARD
        window.page("project").set_mod_path(other.mod_root)
        self.assertTrue(_qt.wait_until(lambda: self.project is not None and self.project is not first
                                       and not window.is_busy(), 5000))
        self.assertEqual(self.project.mod_root, other.mod_root)
        self.assertTrue(first.closed)
        self.assertEqual(self.layers.mod("common/countries.txt").read_bytes(), MOD["common/countries.txt"].encode())

    def test_recovery_is_offered_when_the_project_opens(self):
        shown = []
        self.dialogs.handlers[RecoveryDialog] = lambda dialog: (shown.append(list(dialog.sessions)),
                                                                dialog.rows[0][1].click())
        window = self.open_window(orphan_sessions=["20261026-old"],
                                  sessions={"20261026-old": {"common/countries.txt": b"CCC = 1\r\n"}})
        self.assertEqual(self.dialogs.types(), [RecoveryDialog])
        self.assertEqual(shown, [["20261026-old"]])
        handle = self.project.ws.peek(Rel.of("common/countries.txt"))
        self.assertTrue(handle.dirty)
        self.assertIn("CCC", to_source(handle.model.document))
        self.assertEqual(window.status_label.text(), tr("status.recovery_restored", count=1))
        self.assertEqual(self.project.orphan_sessions, [])
        self.assertEqual(self.project.ws.history()[0], ("undo.restore_session", {"session": "20261026-old"}))
        self.assertTrue(window.windowTitle().startswith("* "), "lo restaurado queda sin guardar")

    def test_recovery_can_be_discarded(self):
        self.dialogs.handlers[RecoveryDialog] = lambda dialog: dialog.rows[0][2].click()
        self.open_window(orphan_sessions=["20261026-old"], sessions={"20261026-old": {}})
        self.assertEqual(self.project.discarded_sessions, ["20261026-old"])
        self.assertEqual(self.project.orphan_sessions, [])
        self.assertEqual(self.window.session.dirty_count(), 0)

    def test_save_with_a_problem_from_the_core_shows_it(self):
        window = self.open_window()
        self.edit()
        problem = FakeSaveProblem("unencodable_text", Rel.of("common/countries.txt"))
        with mock.patch.object(self.project.ws, "save",
                               return_value=SimpleNamespace(ok=False, problems=(problem,), result=None)):
            self.assertFalse(window.save_project())
        (review,) = self.dialogs.dialogs
        self.assertIsInstance(review, SaveReviewDialog)
        self.assertEqual([b.label.text() for b in review.problem_badges], [problem.message("es")])
        self.assertFalse(review.resolve_button.isVisibleTo(review), "solo los conflictos se resuelven")
        # Fuera de la caja: hasta Qt 6.6, QDialogButtonBox vuelve a mostrar sus botones al recolocarlos.
        self.assertNotIn(review.resolve_button, review.buttons.buttons())
        review.buttons.setOrientation(Qt.Orientation.Vertical)    # lo recoloca, como un cambio de estilo
        self.assertFalse(review.resolve_button.isVisibleTo(review))


class PendingSectionTests(ProjectWindowCase):
    def test_lists_reverts_and_saves_the_pending_changes(self):
        window = self.open_window()
        page = window.show_page("pending")
        self.assertIs(page.stack.currentWidget(), page.empty)
        self.assertFalse(page.save_button.isEnabled())
        self.edit()
        self.edit("common/cb_types.txt", "peace_order = { badboy = 1 }\r\n")
        self.assertIs(page.stack.currentWidget(), page.panel, "con la sección a la vista se recalcula al editar")
        tree = page.panel.tree
        self.assertEqual(sorted(tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())),
                         ["common/cb_types.txt", "common/countries.txt"])
        self.assertTrue(page.save_button.isEnabled())
        self.assertTrue(page.panel.select("common/countries.txt"))
        self.assertTrue(page.revert_button.isEnabled())
        page.revert_button.click()
        _qt.process_events()
        self.assertFalse(self.project.ws.peek(Rel.of("common/countries.txt")).dirty)
        self.assertEqual(tree.topLevelItemCount(), 1)
        self.assertEqual(self.project.ws.history()[0], (N_("pending.undo_revert"), {"name": "common/countries.txt"}))
        self.assertEqual(window.status_label.text(), tr("pending.status_reverted", name="common/countries.txt"))
        window.undo()
        self.assertEqual(tree.topLevelItemCount(), 2, "descartar se deshace")
        # «Guardar» de la sección es el de la ventana: con una copia del juego base, revisión previa (D13).
        page.save_button.click()
        self.assertEqual(self.dialogs.types(), [SaveReviewDialog])

    def test_out_of_sight_it_waits_until_shown(self):
        window = self.open_window()
        page = window.page("pending")
        with mock.patch.object(window.session, "changeset", wraps=window.session.changeset) as changeset:
            self.edit()
            self.edit("common/vsm_new.txt", "y = 4\r\n")
            changeset.assert_not_called()
            window.show_page("pending")
            _qt.process_events()
            self.assertEqual(changeset.call_count, 1)
        self.assertEqual(page.panel.tree.topLevelItemCount(), 2)


class HomeTests(ProjectWindowCase):
    def test_lists_the_mods_of_the_game_and_opens_the_one_clicked(self):
        other = build_layers(base=self.layers.base, game=GAME, mod={"common/x.txt": "x = 1\r\n"}, mod_name="Otro")
        window = self.open_window()
        home = window.show_page("home")
        self.assertEqual([tile.name.text() for tile in home.mod_tiles], ["Otro", "VSM"])
        current = home.current_mod_tile()
        self.assertEqual(current.folder, self.layers.mod_root)
        self.assertTrue(current.state.isVisibleTo(home))
        self.assertEqual(current.state.text(), tr("home.mod_open"))
        self.assertIn(home.game_badge.level, ("ok", "warning"))
        self.assertEqual(home.project_badge.label.text(), tr("home.project_open", name="VSM"))
        self.assertFalse(home.pending_button.isVisibleTo(home))
        self.edit()
        self.assertEqual(home.project_badge.label.text(), tr("home.project_dirty_one", name="VSM", count=1))
        self.assertTrue(home.pending_button.isVisibleTo(home))
        home.pending_button.click()
        self.assertEqual(window.current_page_key(), "project:pending")
        window.show_page("home")
        next(tile for tile in home.mod_tiles if tile.name.text() == "Otro").click()
        self.assertTrue(_qt.wait_until(lambda: self.project is not None and self.project.mod_root == other.mod_root
                                       and not window.is_busy(), 5000))
        window.ask_unsaved.assert_called_once()
        self.assertEqual(home.current_mod_tile().name.text(), "Otro")
        self.assertEqual(window.page("project").mod_path(), other.mod_root)

    def test_flows_lead_to_their_section_and_say_when_they_arrive(self):
        window = self.make_window()
        home = window.page("home")
        self.assertEqual(len(home.flow_tiles), 13)
        for tile in home.flow_tiles:
            with self.subTest(flow=tile.title_key):
                window.show_page("home")
                if tile.iteration is None:
                    self.assertEqual(tile.state.text(), tr("home.flow_ready"))
                else:
                    self.assertEqual(tile.state.text(), tr("home.flow_planned", n=tile.iteration))
                tile.click()
                target = window.page(tile.target)
                self.assertIs(window.current_page(), target)
                self.assertEqual(getattr(target, "iteration", None), tile.iteration,
                                 "la tarjeta y la sección dicen la misma iteración")


class LayerBadgeExplorerTests(ProjectWindowCase):
    def test_explorer_paints_the_layer_of_each_file(self):
        window = self.open_window()
        page = window.show_page("project")
        self.assertIs(page.layers, page.layer_badges.resolver)
        self.assertEqual((page.layers.game_root, page.layers.mod_root), (self.layers.game_root, self.layers.mod_root))
        self.assertTrue(page.reveal_file(self.layers.mod("common/countries.txt")))
        self.assertTrue(_qt.wait_until(lambda: not page.is_busy(), 5000))
        self.assertTrue(page.reveal_file(self.layers.mod("common/vsm_new.txt")))
        self.assertTrue(_qt.wait_until(lambda: not page.is_busy(), 5000))
        _qt.process_events(50)
        tree = page.tree
        delegate = tree.itemDelegateForColumn(0)
        self.assertIs(delegate, page.layer_badges.delegate)
        image = tree.viewport().grab().toImage()
        for name, layer in (("countries.txt", LAYER_OVERRIDE), ("vsm_new.txt", LAYER_MOD)):
            index = page.model.mapFromSource(page.fs.index(str(self.layers.mod(f"common/{name}"))))
            self.assertEqual(page.layer_badges.layer_for(index), layer)
            rect = tree.visualRect(index)
            self.assertTrue(tree.viewport().rect().intersects(rect), name)
            wanted = QColor(COLORS[layer])
            found = any(_close(image.pixelColor(x, rect.center().y()), wanted)
                        for x in range(max(rect.right() - 60, rect.left()), rect.right()))
            self.assertTrue(found, f"{name}: no se pintó la insignia {layer}")
            option = QStyleOptionViewItem()
            option.rect = rect
            plain = super(type(delegate), delegate).sizeHint(option, index).width()
            self.assertGreater(delegate.sizeHint(option, index).width(), plain)
        folder = page.model.mapFromSource(page.fs.index(str(self.layers.mod("common"))))
        self.assertIsNone(page.layer_badges.layer_for(folder))
        # Cambiar el juego base cambia las insignias: sin juego, todo el mod es «M».
        page.set_game_path(None)
        index = page.model.mapFromSource(page.fs.index(str(self.layers.mod("common/countries.txt"))))
        self.assertEqual(page.layer_badges.layer_for(index), LAYER_MOD)


def _close(color: QColor, wanted: QColor, tolerance: int = 3) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(color.getRgb()[:3], wanted.getRgb()[:3]))


if __name__ == "__main__":
    unittest.main()
