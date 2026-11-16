"""Taller de mapas, interfaz (wizard §18.2, iteración 9a): el asistente de punta a punta sobre el minijuego del
mapa (inventado), con los comandos en el mismo proceso (``inline``) para no depender de procesos ni de tiempos."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets)
from test_ui_entity import EntityWindowCase, WAIT_MS  # noqa: E402

from _minigame import build_map_minigame  # noqa: E402
from _mapforge_fixtures import tiny_world  # noqa: E402
from vic2studio.core.mapforge import export as ex  # noqa: E402
from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.halls.map.forge import ForgePage  # noqa: E402
from vic2studio.ui.main_window import UNSAVED_DISCARD  # noqa: E402
from vic2studio.ui.mapforge.preview import MODES, render  # noqa: E402
from vic2studio.ui.mapforge.wizard import SCREEN_KEYS, SIZES  # noqa: E402


class ForgeCase(EntityWindowCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"VIC2STUDIO_FORGE_INLINE": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        set_language("es")
        self.addCleanup(set_language, "es")

    def open_forge(self) -> ForgePage:
        self.game = build_map_minigame(clean=True)
        self.addCleanup(self.game.cleanup)
        window = self.make_window()
        window.exec_dialog = self.dialogs
        window.ask_unsaved = mock.Mock(return_value=UNSAVED_DISCARD)
        page = window.page("project")
        page.set_game_path(self.game.game_root)
        page.set_mod_path(self.game.mod_root)
        s = window.session
        self.assertTrue(_qt.wait_until(lambda: s.project is not None and s.index_state() == "ready"
                                       and s.texts_ready() and not window.is_busy(), WAIT_MS))
        self.window = window
        forge = window.show_page("forge")
        self.assertIsInstance(forge, ForgePage)
        self.wiz = forge.wizard
        self.idle()
        return forge

    def idle(self):
        self.assertTrue(_qt.wait_until(lambda: not self.wiz.client.busy and not self.wiz._debounce.isActive(),
                                       WAIT_MS))
        _qt.process_events(20)

    def small_world(self):
        self.wiz.go("canvas")
        self.wiz.size_combo.setCurrentIndex(SIZES.index((1404, 540)))
        self.idle()
        self.assertIsNotNone(self.wiz.world)
        self.assertIsNotNone(self.wiz.world.raster)


class WizardFlowTests(ForgeCase):
    def test_learns_the_installation_when_shown(self):
        self.open_forge()
        prof = self.wiz.install
        self.assertIsNotNone(prof)
        self.assertFalse(prof.synthetic)
        self.assertIn("TAG", self.wiz.install_label.text())

    def test_generate_edit_undo_and_export(self):
        self.open_forge()
        self.small_world()
        w = self.wiz.world
        self.assertEqual(w.raster.scale, 2)          # 1404 de ancho: vista previa a W/2
        self.assertTrue(w.entities.get("owners"))    # repartido entre los TAG del minijuego
        # Pincel de relieve: una edición, el paso queda «editado» y se puede deshacer y rehacer.
        self.wiz.go("relief")
        self.wiz.tool_buttons["raise"].setChecked(True)
        self.wiz.preview.stroke.emit(0.5, 0.5, True)
        self.wiz.preview.stroke.emit(0.55, 0.5, False)
        self.wiz.preview.strokeFinished.emit()
        self.idle()
        self.assertEqual(len(self.wiz.world.edits), 1)
        self.assertEqual(self.wiz.world.steps["relief"].status, "edited")
        self.assertIn(tr("forge.status.edited"), self.wiz.steps.item(SCREEN_KEYS.index("relief")).text())
        self.wiz.undo()
        self.idle()
        self.assertEqual(len(self.wiz.world.edits), 0)
        self.wiz.redo()
        self.idle()
        self.assertEqual(len(self.wiz.world.edits), 1)
        # Renombrar desde la tabla de nombres.
        self.wiz.go("names")
        item = self.wiz.names_table.item(0, 2)
        item.setText("Villaprueba")
        self.idle()
        self.assertIn("Villaprueba", self.wiz.world.entities["province_names"])
        # Revisión: render final, plan y problemas; exportar es una transacción que se deshace entera.
        self.wiz.go("review")
        self.idle()
        self.assertIsNotNone(self.wiz.final)
        self.assertEqual(self.wiz.final.raster.scale, 1)
        self.assertGreater(len(self.wiz.review.plan), 100)
        # La revisión cabe a lo ancho en su columna (el resumen del plan se parte en líneas).
        self.window.resize(1560, 980)
        _qt.process_events(20)
        area = self.wiz.panels.currentWidget()
        self.assertLessEqual(area.widget().minimumSizeHint().width(), area.viewport().width())
        self.assertTrue(self.wiz.review.export_button.isEnabled(), [i.code for i in self.wiz.review.blocking()])
        touched = self.wiz.export()
        self.assertIn("map/provinces.bmp", touched)
        self.assertEqual(self.wiz.current(), "done")
        session = self.window.session
        self.assertTrue(session.project.ws.can_undo())
        step = session.undo()
        self.assertEqual(step.label, ex.UNDO_EXPORT)
        self.assertFalse(session.project.ws.can_undo())

    def test_world_level_creates_countries_on_export(self):
        """Iteración 9b: «Mundo» enseña sus campos, reparte la tierra entre países nuevos y la exportación los crea
        en la misma transacción que el mapa."""
        self.open_forge()
        wiz = self.wiz
        countries = wiz._widgets[("owners", "countries")]
        existing = wiz._widgets[("owners", "existing_tags")]
        self.assertTrue(countries.isHidden(), "en «Solo mapa» no se piden países nuevos")
        self.assertFalse(existing.isHidden())
        self.assertTrue(wiz._widgets[("owners", "colonized_fraction")].isHidden(), "avanzado, oculto al empezar")
        self.assertTrue(wiz.level_buttons["world"].isEnabled())
        self.assertFalse(wiz.level_buttons["overlay"].isEnabled())
        wiz.level_buttons["world"].setChecked(True)
        self.assertFalse(countries.isHidden())
        self.assertTrue(existing.isHidden())
        self.assertTrue(wiz.owners_buttons["existing_tags"].isHidden())
        countries.setValue(4)
        wiz._widgets[("owners", "culture_groups")].setValue(2)
        self.small_world()
        data = wiz.world.entities["world"]
        self.assertEqual(len(data["countries"]), 4)
        self.assertIn(data["countries"][0]["tag"], wiz.owners_stats.text())
        gallery = wiz.flag_gallery
        self.assertEqual([gallery.item(i).text() for i in range(gallery.count())],
                         [c["tag"] for c in data["countries"]])
        self.assertFalse(gallery.item(0).icon().isNull())
        wiz.go("owners")
        self.window.resize(1560, 980)
        _qt.process_events(20)
        area = wiz.panels.currentWidget()
        self.assertLessEqual(area.widget().minimumSizeHint().width(), area.viewport().width(), "cabe a lo ancho")
        wiz.go("review")
        self.idle()
        planned = {f.rel for f in wiz.review.plan}
        self.assertIn("common/cultures.txt", planned)
        touched = wiz.export()
        tags = [c["tag"] for c in data["countries"]]
        for tag in tags:
            self.assertIn(f"gfx/flags/{tag}.tga", touched)
        self.assertIn("common/countries.txt", touched)
        step = self.window.session.undo()
        self.assertEqual(step.label, ex.UNDO_EXPORT)
        self.assertFalse(self.window.session.project.ws.can_undo())

    def test_save_and_reopen_a_workshop_project(self):
        self.open_forge()
        self.small_world()
        self.wiz.name_edit.setText("prueba")
        self.wiz.save_project()
        self.assertEqual([self.wiz.saved_list.item(i).text() for i in range(self.wiz.saved_list.count())], [])
        self.window.session.save()
        self.wiz._refresh_saved()
        self.assertEqual(self.wiz.saved_list.item(0).text(), "prueba")
        digest = self.wiz.world.cells_digest()
        self.wiz.world = None
        self.wiz.saved_list.setCurrentRow(0)
        self.wiz.open_saved()
        self.idle()
        self.assertEqual(self.wiz.world.cells_digest(), digest)
        self.assertIsNotNone(self.wiz.world.raster)

    def test_size_fix_is_only_offered_when_it_works(self):
        self.open_forge()
        self.small_world()
        self.wiz.go("review")
        self.idle()
        codes = [i.code for i in self.wiz.review.issues]
        self.assertIn("forge_size", codes)
        row = codes.index("forge_size")
        self.wiz.review.tree.setCurrentItem(self.wiz.review.tree.topLevelItem(row))
        self.assertFalse(self.wiz.review.fix_button.isEnabled())   # «Rellenar con mar»: todavía no
        self.wiz.review.why_button.click()
        self.assertTrue(self.wiz.review.why_title.text())

    def test_import_bitmaps_screen(self):
        self.open_forge()
        files, _ = ex.render_files(tiny_world(3), ex.ExportInputs(prefix="FRG"))
        self.wiz.origin_buttons["bitmaps"].setChecked(True)
        self.assertTrue(self.wiz.steps.item(SCREEN_KEYS.index("relief")).isHidden())
        self.assertFalse(self.wiz.steps.item(SCREEN_KEYS.index("import")).isHidden())
        self.wiz.go("import")
        panel = self.wiz.import_panel
        for slot, rel in (("provinces", "map/provinces.bmp"), ("definition", "map/definition.csv"),
                          ("default_map", "map/default.map"), ("terrain", "map/terrain.bmp")):
            panel.set_file(slot, files[rel])
        panel.inspect_button.click()
        self.idle()
        self.assertIsNotNone(panel.report)
        self.assertTrue(panel.build_button.isEnabled())
        panel.build_button.click()
        self.idle()
        r = self.wiz.world.raster
        self.assertEqual(r.count, tiny_world(3).raster.count)
        self.assertIn(tr("forge.status.imported"), self.wiz.steps.item(SCREEN_KEYS.index("import")).text())

    def test_import_an_fmg_json_into_the_world_level(self):
        """Iteración 9b: el origen «JSON de FMG» solo enseña su ranura, y construir da los países de FMG."""
        from _mapforge_fixtures import fmg_json_full

        self.open_forge()
        wiz = self.wiz
        wiz.level_buttons["world"].setChecked(True)
        wiz.origin_buttons["fmg_json"].setChecked(True)
        panel = wiz.import_panel
        visible = [s for r, s in enumerate(panel.slots) if not panel.slot_table.isRowHidden(r)]
        self.assertEqual(visible, ["fmg_json"])
        wiz.go("canvas")
        wiz.size_combo.setCurrentIndex(SIZES.index((1404, 540)))
        self.idle()
        self.assertIsNone(wiz.world, "con un origen importado no se genera nada")
        wiz.go("import")
        panel.set_file("fmg_json", fmg_json_full())
        panel.inspect_button.click()
        self.idle()
        self.assertIsNotNone(panel.report)
        panel.build_button.click()
        self.idle()
        names = [c["name"] for c in wiz.world.entities["world"]["countries"]]
        self.assertEqual(names, ["Velmora", "Ostrand", "Kaldun"])
        self.assertIn(tr("forge.status.imported"), wiz.steps.item(SCREEN_KEYS.index("provinces")).text())
        wiz.origin_buttons["bitmaps"].setChecked(True)
        visible = [s for r, s in enumerate(panel.slots) if not panel.slot_table.isRowHidden(r)]
        self.assertNotIn("fmg_json", visible)

    def test_english_texts(self):
        self.open_forge()
        set_language("en")
        _qt.process_events(20)
        self.assertIn("Canvas", self.wiz.steps.item(SCREEN_KEYS.index("canvas")).text())
        self.assertEqual(self.wiz.quick_button.text(), "Quick generation")


class PreviewTests(unittest.TestCase):
    def test_every_mode_renders(self):
        w = tiny_world(3)
        for mode in MODES:
            with self.subTest(mode=mode):
                img = render(w, mode, problems={1, 2})
                self.assertEqual(img.shape, w.raster.ids.shape + (3,))
                self.assertGreater(len({tuple(px) for px in img[::17, ::17].reshape(-1, 3).tolist()}), 1)


if __name__ == "__main__":
    unittest.main()
