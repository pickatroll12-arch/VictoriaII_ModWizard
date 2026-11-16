"""Ficha nacional (sala Naciones › Países, wizard §14.2, iteración 6, criterio 5).

Se abre con doble clic en el mapa (el dueño de la provincia) o desde un problema; edita en la fecha de trabajo
tecnologías, reformas, cámara alta (que debe sumar 100), prestigio y pluralidad, cada gesto en un paso de
deshacer; y también el archivo de país (color, partidos), las culturas, las banderas y los textos.
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets)
from test_ui_entity import EntityWindowCase  # noqa: E402

APP = _qt.application()

from PIL import Image  # noqa: E402

from vic2studio.core.clausewitz.nodes import ClausewitzDate  # noqa: E402
from vic2studio.core.gfx.flags import FLAG_SIZE  # noqa: E402
from vic2studio.i18n import set_language  # noqa: E402
from vic2studio.ui.countries.sheet import TABS, NationalSheet  # noqa: E402
from vic2studio.ui.halls.nations.countries import CountriesPage  # noqa: E402

HISTORY = "history/countries/AAA - Aland.txt"


class SheetCase(EntityWindowCase):
    def open_sheet(self, tag: str = "AAA") -> tuple[CountriesPage, NationalSheet]:
        self.open_window()
        page = self.window.show_page("nations:countries")
        self.settle()
        self.assertIsInstance(page, CountriesPage)
        self.assertTrue(page.select_tag(tag))
        return page, page.sheet


class OpenTests(SheetCase):
    def test_double_click_on_the_map_opens_the_owner(self):
        self.open_window()
        world = self.window.show_page("map:world")
        self.settle()
        self.assertEqual(world.owner_of(1), "AAA")
        world.canvas.provinceDoubleClicked.emit(1)
        _qt.process_events(20)
        self.assertEqual(self.window.current_page_key(), "nations:countries")
        page = self.window.current_page()
        self.assertEqual(page.current_tag(), "AAA")
        self.assertEqual(page.sheet.tag, "AAA")
        self.assertFalse(world.open_owner(0), "fuera del mapa no abre nada")

    def test_every_hosted_schema_opens_the_sheet(self):
        self.open_window()
        self.assertTrue(self.window.open_entity("country_history", "BBB", ("prestige",)))
        page = self.window.current_page()
        self.assertEqual(page.current_tag(), "BBB")
        self.assertEqual(page.sheet.current_tab(), "politics")
        self.assertTrue(self.window.open_entity("country", "aland.txt"))
        self.assertEqual(page.current_tag(), "AAA")
        self.assertEqual(page.sheet.current_tab(), "identity")

    def test_list_filter_and_tabs(self):
        page, sheet = self.open_sheet()
        self.assertEqual(page.tags(), ["AAA", "BBB", "CCC", "D01"])
        page.filter_edit.setText("bor")
        visible = [page.list.item(i).data(256) for i in range(page.list.count()) if not page.list.item(i).isHidden()]
        self.assertEqual(visible, ["BBB"])
        self.assertEqual(sheet.tabs.count(), len(TABS))
        self.assertIn("AAA", sheet.title.text())
        self.assertEqual(sheet.capital_picker.value(), 1)
        self.assertEqual(sheet.culture_picker.value(), "alander")
        self.assertEqual(sheet.government_picker.value(), "monarchy")


class EditTests(SheetCase):
    def test_politics_at_the_working_date_one_step_each(self):
        _page, sheet = self.open_sheet()
        session = self.window.session
        self.assertTrue(sheet._commit_history("prestige", 25.0))
        self.assertTrue(sheet._commit_history("plurality", 12.5))
        self.settle()
        self.assertEqual(len(session.history()), 2)
        history = self.text_of(HISTORY)
        self.assertIn("prestige = 25", history)
        self.assertIn("plurality = 12.5", history)
        sheet.show_tab("politics")
        self.assertEqual(sheet.prestige_spin.value(), 25.0)
        self.window.undo()
        self.settle()
        self.assertNotIn("plurality", self.text_of(HISTORY))

    def test_a_later_working_date_writes_a_dated_block(self):
        _page, sheet = self.open_sheet()
        session = self.window.session
        session.set_working_date(ClausewitzDate(1861, 7, 1))
        self.settle()
        self.assertTrue(sheet._commit_history("prestige", 40.0))
        history = self.text_of(HISTORY)
        self.assertIn("1861.7.1 = {", history)
        self.assertEqual(sheet._countries().get("AAA", "prestige", ClausewitzDate(1836, 1, 1)), None)

    def test_upper_house_must_add_up_to_100(self):
        _page, sheet = self.open_sheet()
        spins = sheet.upper_house.spins
        if len(spins) < 1:
            self.skipTest("el minijuego no tiene ideologías")
        first = next(iter(spins))
        sheet.upper_house.set_value({first: 60})
        self.assertFalse(sheet.apply_upper_house(), "60 no suma 100")
        sheet.upper_house.set_value({first: 100})
        self.assertTrue(sheet.apply_upper_house())
        self.assertIn("upper_house = {", self.text_of(HISTORY))
        self.assertEqual(sheet._countries().upper_house("AAA", self.window.session.working_date), {first: 100.0})

    def test_technologies_and_reforms(self):
        _page, sheet = self.open_sheet()
        session = self.window.session
        from vic2studio.ui.pickers.tech_tree import technologies

        techs = [name for items in technologies(session.index).values() for name, _year in items]
        self.assertTrue(techs)
        sheet.tech_checklist.set_selected({techs[0]})
        self.assertTrue(sheet.apply_technologies())
        self.assertIn(f"{techs[0]} = 1", self.text_of(HISTORY))
        groups = sheet._countries().reform_groups()
        if groups:
            group, options = next(iter(groups.items()))
            sheet.issue_picker.set_value({group: options[-1]})
            self.assertTrue(sheet.apply_reforms())
            self.assertIn(f"{group} = {options[-1]}", self.text_of(HISTORY))
        self.assertEqual(len(session.history()), 2 if groups else 1)

    def test_country_file_cultures_parties_and_texts(self):
        _page, sheet = self.open_sheet()
        self.assertTrue(sheet._commit_file("color", (1, 2, 3)))
        self.assertIn("color = { 1 2 3 }", self.text_of("common/countries/Aland.txt"))
        sheet.cultures_picker.set_values(["borlander"])
        self.assertTrue(sheet.apply_cultures())
        self.assertIn("culture = borlander", self.text_of(HISTORY))
        sheet.party_name.setText("Partido del Estrecho")
        sheet.party_ideology.set_value("liberal")
        self.assertTrue(sheet.add_party_from_form())
        sheet.show_tab("parties")
        self.assertEqual(sheet.party_table.item(sheet.party_table.rowCount() - 1, 0).text(), "Partido del Estrecho")
        sheet.party_table.selectRow(sheet.party_table.rowCount() - 1)
        self.assertTrue(sheet.remove_selected_party())
        self.assertNotIn("Partido del Estrecho", self.text_of("common/countries/Aland.txt"))
        self.assertTrue(sheet.set_text("AAA_ADJ", "en", "Alandic"))
        self.assertEqual(self.window.session.locsync.text("AAA_ADJ", "en"), "Alandic")
        sheet.show_tab("texts")
        self.assertIn("AAA_ADJ", [sheet.text_table.item(r, 0).text() for r in range(sheet.text_table.rowCount())])

    def test_flags_are_replaced_in_one_step(self):
        _page, sheet = self.open_sheet()
        session = self.window.session
        sheet.flag_studio.set_image(Image.new("RGB", (200, 100), (0, 90, 200)))
        self.assertTrue(sheet.apply_flags())
        self.settle()
        self.assertEqual(len(session.history()), 1)
        handle = session.project.ws.peek("gfx/flags/AAA_monarchy.tga")
        image = Image.open(io.BytesIO(bytes(handle.model)))
        self.assertEqual(image.size, FLAG_SIZE)
        sheet.show_tab("flags")
        self.assertFalse(sheet.current_flags["_monarchy"].pixmap().isNull())

    def test_army_tab_adds_an_army_and_a_regiment(self):
        _page, sheet = self.open_sheet("BBB")
        editor = sheet.oob_editor
        self.assertTrue(editor.add_army("army", "Ejército del Norte", 3))
        self.assertEqual(len(editor.armies), 1)
        self.assertIn('oob = "BBB_oob.txt"', self.text_of("history/countries/BBB - Borland.txt"))
        editor.tree.setCurrentItem(editor.tree.topLevelItem(0))
        self.assertTrue(editor.add_unit(editor.armies[0].position, "1º de línea", "infantry", None))
        self.assertIn("regiment = {", self.text_of("history/units/BBB_oob.txt"))

    def test_texts_follow_the_language(self):
        _page, sheet = self.open_sheet()
        set_language("en")
        self.addCleanup(set_language, "es")
        self.assertEqual(sheet.tabs.tabText(0), "Identity")
        set_language("es")
        self.assertEqual(sheet.tabs.tabText(0), "Identidad")


if __name__ == "__main__":
    unittest.main()
