"""Asistente «Nuevo país» en la interfaz (wizard §14.2, iteración 6, criterios 1 y 2).

La ventana real sobre el minijuego, como ``test_ui_entity``: los pasos se validan en vivo (TAG, nombre, cámara
alta), la revisión enseña el plan del núcleo y «Crear país» lo aplica en un paso de deshacer; la lista de países
elige el nuevo cuando el índice lo conoce.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets)
from test_ui_entity import WAIT_MS, EntityWindowCase  # noqa: E402

APP = _qt.application()

from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.countries.wizard import STEPS, NewCountryWizard  # noqa: E402
from vic2studio.ui.halls.nations.countries import CountriesPage  # noqa: E402


class WizardCase(EntityWindowCase):
    def open_wizard(self) -> tuple[CountriesPage, NewCountryWizard]:
        self.open_window()
        page = self.window.show_page("nations:countries")
        self.settle()
        self.assertIsInstance(page, CountriesPage)
        wizard = page.new_country_wizard()
        return page, wizard


class WizardTests(WizardCase):
    def test_identity_step_checks_the_tag_live_and_suggests_free_ones(self):
        _page, wizard = self.open_wizard()
        self.assertEqual(wizard.current_step(), 0)
        self.assertFalse(wizard.next_button.isEnabled(), "sin nombre no se avanza")
        wizard.name_en.setText("Somalia")
        self.assertEqual(wizard.suggested_tags(), ["SOM", "SOL", "SMA"])
        self.assertEqual(wizard.tag_edit.text(), "SOM")
        self.assertTrue(wizard.next_button.isEnabled())
        for tag, reason in (("AAA", "countries.tag.taken"), ("D07", "countries.tag.dynamic"),
                            ("CON", "countries.tag.windows_device"), ("AND", "countries.tag.script_word"),
                            ("REB", "countries.tag.reserved"), ("12A", "countries.tag.pattern")):
            with self.subTest(tag=tag):
                wizard.tag_edit.setText(tag)
                self.assertEqual(wizard.step_error(0), reason)
                self.assertEqual(wizard.tag_status.text(), tr(reason, tag=tag))
                self.assertFalse(wizard.next_button.isEnabled())
        wizard.tag_edit.setText("som")
        self.assertEqual(wizard.tag_edit.text(), "SOM", "se escribe en mayúsculas")
        wizard.go(5)
        self.assertEqual(wizard.current_step(), 5, "con todo válido se puede saltar")
        wizard.tag_edit.setText("AAA")
        wizard.go(0)
        wizard.go(7)
        self.assertEqual(wizard.current_step(), 0, "un paso con error para el salto")

    def test_base_on_fills_the_rest_and_parties_can_be_copied(self):
        _page, wizard = self.open_wizard()
        wizard.name_en.setText("Somalia")
        wizard.base_on("AAA")
        self.assertEqual(wizard.culture_picker.value(), "alander")
        self.assertEqual(wizard.government_picker.value(), "monarchy")
        self.assertEqual(wizard.color_field.value(), (10, 20, 30))
        wizard.party_copy.setChecked(True)
        names = [party.name for party in wizard.parties()]
        self.assertTrue(names and all(name.startswith("SOM_") for name in names), names)
        wizard.go(3)
        self.assertEqual(wizard.party_table.rowCount(), len(names))
        wizard.go(4)
        self.assertEqual(wizard.ruling_combo.currentData(), names[0])

    def test_upper_house_must_add_up_to_100(self):
        _page, wizard = self.open_wizard()
        wizard.name_en.setText("Somalia")
        wizard.go(4)
        if not wizard.upper_house.spins:
            self.skipTest("el minijuego no tiene ideologías")
        first = next(iter(wizard.upper_house.spins.values()))
        first.setValue(40)
        self.assertEqual(wizard.step_error(4), "countries.error.upper_house")
        wizard.upper_house.fill()
        self.assertIsNone(wizard.step_error(4))

    def test_review_shows_the_plan_and_create_is_one_undo_step(self):
        page, wizard = self.open_wizard()
        session = self.window.session
        wizard.name_en.setText("Somalia")
        wizard.name_es.setText("Somalia")
        wizard.adj_en.setText("Somali")
        wizard.base_on("AAA")
        wizard.save_check.setChecked(False)
        wizard.go(6)
        wizard.set_provinces([2])
        wizard.army_spin.setValue(2)
        wizard.go(len(STEPS) - 1)
        self.assertIsNotNone(wizard.plan)
        rels = [wizard.plan_table.item(row, 0).text() for row in range(wizard.plan_table.rowCount())]
        for rel in ("common/countries.txt", "common/countries/Somalia.txt", "history/countries/SOM - Somalia.txt",
                    "history/units/SOM_oob.txt", "gfx/flags/SOM.tga", "gfx/flags/SOM_republic.tga"):
            self.assertIn(rel, rels)
        self.assertTrue(any(rel.startswith("history/provinces/") for rel in rels))
        wizard.plan_table.selectRow(rels.index("common/countries.txt"))
        self.assertIn('+SOM = "countries/Somalia.txt"', wizard.diff_view.toPlainText())
        self.assertEqual(session.history(), [], "la revisión no cambia nada")
        self.assertTrue(wizard.create_button.isEnabled())
        self.assertTrue(wizard.create())
        self.settle()
        self.assertEqual(len(session.history()), 1, "un solo paso de deshacer")
        self.assertIn("SOM", self.text_of("history/units/SOM_oob.txt"))
        self.assertTrue(_qt.wait_until(lambda: page.current_tag() == "SOM", WAIT_MS), page.tags())
        self.assertEqual(page.sheet.tag, "SOM")
        self.window.undo()
        self.settle()
        self.assertEqual(session.history(), [])

    def test_texts_follow_the_language(self):
        _page, wizard = self.open_wizard()
        set_language("en")
        self.addCleanup(set_language, "es")
        self.assertEqual(wizard.windowTitle(), "New country")
        self.assertEqual(wizard.next_button.text(), "Next")
        set_language("es")
        self.assertEqual(wizard.windowTitle(), "Nuevo país")


if __name__ == "__main__":
    unittest.main()
