"""Sala Guerra de la iteración 6 (wizard §14.8, §14.12): guerras de inicio con su línea temporal y el diálogo
«Nueva guerra», y la diplomacia de inicio. La ventana real sobre el minijuego, como ``test_ui_entity``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets)
from test_ui_entity import EntityWindowCase  # noqa: E402

APP = _qt.application()

from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.halls.war.diplomacy import DiplomacyPage  # noqa: E402
from vic2studio.ui.halls.war.wars import WarsPage  # noqa: E402

NEW_WAR = "history/wars/TESTMOD_Guerra del Estrecho.txt"


class WarsPageTests(EntityWindowCase):
    def open_wars(self) -> WarsPage:
        self.open_window()
        page = self.window.show_page("war:wars")
        self.settle()
        self.assertIsInstance(page, WarsPage)
        return page

    def test_list_timeline_and_detail(self):
        page = self.open_wars()
        self.assertEqual([model.name for _rel, model in page.items], ["Old War"])
        self.assertEqual(len(page.timeline.wars), 1)
        self.assertEqual(page.detail_title.text(), "Old War")
        self.assertGreater(page.events.rowCount(), 0)
        self.assertIn("AAA", page.detail_info.text())
        page.timeline.resize(600, 120)
        self.assertEqual(page.timeline.row_at(30), 0)
        self.assertEqual(page.timeline.row_at(5), -1)
        self.assertTrue(page.timeline.grab().width() > 0, "pinta sin fallar")

    def test_new_war_dialog_validates_previews_and_creates_in_one_step(self):
        page = self.open_wars()
        session = self.window.session
        dialog = page.new_war_dialog()
        self.assertIsNotNone(dialog.problem(), "sin nombre ni bandos no se puede")
        self.assertFalse(dialog.buttons.button(dialog.buttons.StandardButton.Ok).isEnabled())
        dialog.name_edit.setText("Guerra del Estrecho")
        dialog.attackers.set_values(["AAA", "CCC"])
        dialog.defenders.set_values(["BBB"])
        _qt.process_events(10)
        self.assertIsNone(dialog.problem())
        self.assertEqual((dialog.actor_combo.currentData(), dialog.receiver_combo.currentData()), ("AAA", "BBB"))
        dialog.cb_picker.set_value("conquer_land")
        dialog._on_cb("conquer_land")
        self.assertTrue(dialog.state_picker.isEnabled(), "conquer_land cede provincias: pide estado")
        dialog._on_cb("humble_rival")
        self.assertFalse(dialog.state_picker.isEnabled())
        self.assertFalse(dialog.country_picker.isEnabled())
        dialog.add_goal("conquer_land", "AAA", "BBB", 3)
        self.assertEqual(dialog.goal_table.rowCount(), 1)
        preview = dialog.preview.toPlainText()
        self.assertTrue(preview.startswith(f"# {NEW_WAR}"))
        self.assertIn("state_province_id = 3", preview)
        dialog.defenders.set_values(["BBB", "AAA"])
        _qt.process_events(10)
        self.assertEqual(dialog.problem(), tr("war.error.same_side", detail="AAA"))
        dialog.defenders.set_values(["BBB"])
        _qt.process_events(10)
        self.assertTrue(dialog.create())
        self.settle()
        self.assertEqual(len(session.history()), 1)
        self.assertIn("add_attacker = CCC", self.text_of(NEW_WAR))
        self.assertEqual(page.detail_title.text(), "Guerra del Estrecho")
        self.assertEqual(len(page.timeline.wars), 2)
        self.window.undo()
        self.settle()
        self.assertEqual(len(page.items), 1)

    def test_problems_open_the_war(self):
        page = self.open_wars()
        self.assertTrue(self.window.open_entity("war", "Old War"))
        self.assertIs(self.window.current_page(), page)
        self.assertEqual(page.detail_title.text(), "Old War")

    def test_texts_follow_the_language(self):
        page = self.open_wars()
        set_language("en")
        self.addCleanup(set_language, "es")
        self.assertEqual(page.new_button.text(), "New war…")
        set_language("es")
        self.assertEqual(page.new_button.text(), "Nueva guerra…")


class DiplomacyPageTests(EntityWindowCase):
    def open_diplomacy(self) -> DiplomacyPage:
        self.open_window()
        page = self.window.show_page("war:diplomacy")
        self.settle()
        self.assertIsInstance(page, DiplomacyPage)
        return page

    def test_add_filter_and_remove_one_step_each(self):
        page = self.open_diplomacy()
        session = self.window.session
        self.assertEqual(page.table.rowCount(), 1)
        before = self.text_of("history/diplomacy/Alliances.txt")
        self.assertFalse(page.add_relation("alliance", "AAA", "CCC", "1836.1.1"), "ya existe")
        self.assertEqual(page.status_label.text(), tr("war.error.relation_exists", detail="alliance AAA CCC"))
        self.assertFalse(page.add_relation("alliance", "AAA", "BBB", "1836.13.1"), "fecha mala")
        self.assertTrue(page.add_relation("guarantee", "BBB", "CCC", "1836.1.1"))
        self.settle()
        self.assertEqual(len(session.history()), 1)
        self.assertIn("guarantee = {", self.text_of("history/diplomacy/Guarantees.txt"))
        self.assertEqual(page.table.rowCount(), 2)
        page.type_filter.setCurrentIndex(page.type_filter.findData("guarantee"))
        self.assertEqual(page.table.rowCount(), 1)
        page.type_filter.setCurrentIndex(0)
        page.tag_filter.setText("aaa")
        self.assertEqual(page.table.rowCount(), 1)
        page.table.selectRow(0)
        self.assertTrue(page.remove_selected())
        self.settle()
        self.assertEqual(len(session.history()), 2)
        self.assertNotIn("AAA", self.text_of("history/diplomacy/Alliances.txt").replace(before, "") or "")
        self.assertEqual([r.type for r in page.relations], ["guarantee"])

    def test_the_sheet_lists_relations_and_wars(self):
        self.open_window()
        page = self.window.show_page("nations:countries")
        self.settle()
        page.select_tag("AAA")
        page.sheet.show_tab("diplomacy")
        self.assertEqual(page.sheet.relation_table.rowCount(), 1)
        self.assertEqual(page.sheet.relation_table.item(0, 1).text(), "CCC")
        self.assertEqual(page.sheet.war_list.count(), 1)
        page.sheet.war_list.itemDoubleClicked.emit(page.sheet.war_list.item(0))
        _qt.process_events(20)
        self.assertEqual(self.window.current_page_key(), "war:wars")


if __name__ == "__main__":
    unittest.main()
