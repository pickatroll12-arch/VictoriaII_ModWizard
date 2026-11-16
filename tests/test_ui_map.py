"""Sala Mapa de la iteración 5 en la interfaz (wizard §16): la página Mundo con el lienzo, los modos, la ficha de la
provincia, la brocha y los POPs; el selector de fecha; las páginas de grupos y de estrechos; y los selectores de
provincia. La ventana real con la ``Session`` real sobre el minijuego del mapa, como ``test_ui_entity``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets)
from _minigame import MAP_GAME_FILES  # noqa: E402
from test_ui_entity import WAIT_MS, EntityWindowCase  # noqa: E402

APP = _qt.application()

from vic2studio.core.clausewitz.nodes import ClausewitzDate  # noqa: E402
from vic2studio.core.map.modes import discover_modes  # noqa: E402
from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.halls.map.groups import ClimatesPage, RegionsPage  # noqa: E402
from vic2studio.ui.halls.map.straits import StraitsPage  # noqa: E402
from vic2studio.ui.halls.map.world import WorldPage  # noqa: E402
from vic2studio.ui.pickers.province_picker import LAND, SEA, MapPickDialog, ProvincePicker  # noqa: E402
from vic2studio.ui.session_map import RASTER_READY  # noqa: E402

D1836, D1861 = ClausewitzDate(1836, 1, 1), ClausewitzDate(1861, 1, 1)


class MapCase(EntityWindowCase):
    def open_map(self, key: str = "world"):
        self.open_window(game_files=MAP_GAME_FILES)
        page = self.window.show_page(key)
        session = self.window.session
        self.assertTrue(_qt.wait_until(lambda: session.map.raster_state == RASTER_READY
                                       and session.map.facts is not None, WAIT_MS), session.map.raster_error)
        self.settle()
        return page


class WorldPageTests(MapCase):
    def test_the_sheet_follows_the_working_date(self):
        page = self.open_map()
        self.assertIsInstance(page, WorldPage)
        page.select_province(4)
        _qt.process_events(20)
        self.assertEqual(page.editors["owner"].text(), "AAA")
        self.assertIn("4", page.province_title.text())
        self.assertEqual(page.date_selector.bookmark_dates(), [D1836, D1861])
        page.date_selector.combo.setEditText("1861.1.1")
        page.date_selector._on_typed()
        self.settle()
        self.assertEqual(self.window.session.working_date, D1861)
        self.assertEqual(page.editors["owner"].text(), "BBB")
        self.assertGreater(page.timeline.count(), 0)

    def test_a_field_is_one_undo_step_and_updates_the_map(self):
        page = self.open_map()
        session = self.window.session
        page.select_province(1)
        page.editors["owner"].setText("BBB")
        page._commit_text("owner")
        self.settle()
        self.assertEqual(len(session.history()), 1)
        self.assertIn("owner = BBB", self.text_of("history/provinces/north/1 - Capital.txt"))
        facts = session.map.facts
        self.assertEqual(facts.name("tags", int(facts.owner[1])), "BBB")
        self.window.undo()
        self.settle()
        self.assertEqual(session.history(), [])

    def test_a_brush_stroke_is_one_step_and_skips_the_sea(self):
        page = self.open_map()
        session = self.window.session
        page.brush_button.setChecked(True)
        page.brush_field.setCurrentIndex(page.brush_field.findData("owner"))
        page.brush_value.setText("ccc")
        page._on_stroke((1, 2, 9))
        self.settle()
        self.assertEqual(len(session.history()), 1)
        self.assertEqual(session.map.provinces.state(2, D1836).owner, "CCC")
        page.brush_value.setText("")
        page._on_stroke((3,))
        self.assertEqual(len(session.history()), 1, "sin valor no pinta")

    def test_every_mode_paints_and_has_a_legend(self):
        page = self.open_map()
        for mode in discover_modes():
            with self.subTest(mode=mode.key):
                page.set_mode(mode.key, "AAA" if mode.param else None)
                _qt.process_events(5)
                self.assertEqual(page.canvas.mode(), mode.key)
                self.assertGreater(page.legend.count(), 0)

    def test_pops_tab_edits_and_scales(self):
        page = self.open_map()
        session = self.window.session
        page.select_province(4)
        _qt.process_events(20)
        self.assertEqual(page.pops_table.rowCount(), 3)
        page.pops_table.item(0, 3).setText("710")
        self.settle()
        self.assertEqual(len(session.history()), 1)
        self.assertEqual(session.map.provinces.pops().total(4, D1836), 1060)
        page.scale_spin.setValue(200)
        page._scale_pops()
        self.settle()
        self.assertEqual(len(session.history()), 2)
        self.assertEqual(int(session.map.facts.population[4]), 2120)

    def test_canvas_coordinates_round_trip(self):
        page = self.open_map()
        canvas = page.canvas
        canvas.set_zoom(40)                     # el máximo (16): el mapa ya no cabe entero en la vista
        self.assertEqual(canvas.zoom(), 16.0)
        self.assertTrue(canvas.center_on_province(7))
        _qt.process_events(20)
        center = canvas.viewport().rect().center()
        self.assertEqual(canvas.province_at(center), 7)
        game = canvas.to_game(center)
        point = canvas.mapFromScene(canvas.from_game(*game))
        self.assertLessEqual((point - center).manhattanLength(), max(2, int(canvas.zoom()) * 2))
        canvas.set_lines([(1, 4, 0xFFFF0000, False)])
        self.assertEqual(len(canvas.lines()), 1)
        canvas.viewport().repaint()

    def test_focus_field_opens_the_province(self):
        page = self.open_map()
        self.assertTrue(page.focus_field("6"))
        self.assertEqual(self.window.session.map.selection, (6,))
        self.assertFalse(page.focus_field("abc"))

    def test_english_texts(self):
        page = self.open_map()
        set_language("en")
        self.addCleanup(set_language, "es")
        _qt.process_events(20)
        self.assertEqual(page.tabs.tabText(0), tr("map.tab.province"))
        self.assertEqual(page.mode_combo.itemText(0), "Political")


class GroupPagesTests(MapCase):
    def test_regions_members_and_group_edits(self):
        page = self.open_map("regions")
        self.assertIsInstance(page, RegionsPage)
        session = self.window.session
        self.assertTrue(page.select_group("AAA_1"))
        self.assertEqual(page.members.count(), 3)
        self.assertEqual(page.apply_members([1, 2, 4]), (1, 1))
        self.settle()
        self.assertIn("AAA_1 = { 1 2 4 }", self.text_of("map/region.txt"))
        self.assertEqual(len(session.history()), 1)
        facts = session.map.facts
        self.assertEqual(facts.name("regions", int(facts.region[4])), "AAA_1")
        self.assertTrue(page.edit_group("create", "DDD_9"))
        self.assertTrue(page.edit_group("rename", "DDD_9", "DDD_10"))
        self.assertFalse(page.edit_group("delete", "AAA_1"))
        self.assertIn("AAA_1", page.status_label.text())
        self.assertTrue(page.edit_group("delete", "DDD_10"))
        self.assertEqual(len(session.history()), 4)
        self.window.undo()
        self.window.undo()
        self.window.undo()
        self.window.undo()
        self.settle()
        self.assertEqual(facts.name("regions", int(session.map.facts.region[4])), "BBB_4")

    def test_climates_page_switches_files(self):
        page = self.open_map("climates")
        self.assertIsInstance(page, ClimatesPage)
        page.kind_combo.setCurrentIndex(page.kind_combo.findData("climate"))
        _qt.process_events(10)
        self.assertEqual(page.canvas.mode(), "climates")
        self.assertTrue(page.select_group("mild_climate"))
        page._on_stroke((5,))
        self.settle()
        self.assertEqual(self.window.session.map.groups("climate").group_of(5), "mild_climate")


class StraitsPageTests(MapCase):
    def test_add_and_remove_rows(self):
        page = self.open_map("straits")
        self.assertIsInstance(page, StraitsPage)
        session = self.window.session
        self.assertEqual(len(page.rows()), 3)
        self.assertEqual(len(page.canvas.lines()), 3)
        page.start_picker.set_value(5)
        page.end_picker.set_value(8)
        page.through_picker.set_value(12)
        added = page.add_from_form()
        self.assertIsNotNone(added)
        self.settle()
        self.assertEqual(len(page.rows()), 4)
        self.assertIn("5;8;sea;12;0;", self.text_of("map/adjacencies.csv"))
        self.assertIsNone(page.add_from_form(), "la misma fila otra vez no")
        self.assertEqual(page.status_label.text(), tr("map.straits.error.exists"))
        self.assertTrue(page.select_row(added.line))
        self.assertTrue(page.remove_selected())
        self.settle()
        self.assertEqual(len(page.rows()), 3)
        self.assertEqual(len(session.history()), 2)

    def test_drawing_fills_the_form_in_three_clicks(self):
        page = self.open_map("straits")
        page.draw_button.setChecked(True)
        page._on_picked(9)                       # mar en el primer paso: no vale
        self.assertIsNone(page.start_picker.value())
        for pid in (5, 8, 12):
            page._on_picked(pid)
        self.assertEqual((page.start_picker.value(), page.end_picker.value(), page.through_picker.value()),
                         (5, 8, 12))
        self.assertFalse(page.draw_button.isChecked())


class PickerTests(MapCase):
    def test_province_picker_parses_and_validates(self):
        self.open_map()
        session = self.window.session
        land = ProvincePicker(session, allow=LAND)
        self.addCleanup(land.deleteLater)
        committed = []
        land.value_committed.connect(committed.append)
        land.edit.setText("4")
        land._commit()
        self.assertEqual(committed, [4])
        land.edit.setText("9")
        land._commit()
        self.assertTrue(land.edit.property("invalid"))
        self.assertEqual(land.value(), 4)
        sea = ProvincePicker(session, allow=SEA)
        self.addCleanup(sea.deleteLater)
        self.assertEqual(sea.parse("10"), 10)
        self.assertIs(sea.parse("3"), False)
        self.assertIsNone(sea.parse(" "))

    def test_map_pick_dialog_multiple(self):
        self.open_map()
        dialog = MapPickDialog(self.window.session, multiple=True, initial=(1, 2), allow=LAND)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.provinces(), (1, 2))
        dialog._on_picked(3)
        dialog._on_picked(1)
        dialog._on_picked(9)                     # mar: rechazada
        self.assertEqual(dialog.provinces(), (2, 3))
        dialog.set_provinces((7, 10))
        self.assertEqual(dialog.provinces(), (7,))
        single = MapPickDialog(self.window.session, initial=(4,))
        self.addCleanup(single.deleteLater)
        single._on_picked(6)
        self.assertEqual(single.provinces(), (6,))

    def test_working_date_selector_rejects_dates_out_of_bounds(self):
        page = self.open_map()
        selector = page.date_selector
        chosen = []
        selector.dateChosen.connect(chosen.append)
        self.assertIsNone(selector.parse("1700.1.1"))
        self.assertIsNone(selector.parse("1836.13.1"))
        selector.combo.setEditText("1845.3.1")
        selector._on_typed()
        self.assertEqual(chosen, [ClausewitzDate(1845, 3, 1)])
        self.window.session.set_working_date(D1836)
        self.assertEqual(selector.combo.currentText(), "1836.1.1")


if __name__ == "__main__":
    unittest.main()
