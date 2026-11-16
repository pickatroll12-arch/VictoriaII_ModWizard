"""Decisiones (sala Eventos › Decisiones, wizard §13.8, iteración 7): requisitos, efecto e interés de la IA
con su vista previa, la imagen «la del id» y las decisiones rotas del usuario en modo texto con su arreglo.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets)
from test_ui_event_studio import ScriptWindowCase  # noqa: E402
from test_ui_smoke import MARK_OPEN, PSEUDO, collect_texts, pseudo_catalog  # noqa: E402

APP = _qt.application()

from vic2studio.core.schema.record import RecordRef  # noqa: E402
from vic2studio.i18n import set_language, translator  # noqa: E402
from vic2studio.ui.halls.events.studio import DecisionStudioPage  # noqa: E402


class DecisionCase(ScriptWindowCase):
    def decisions(self, ident: str = "mg_build_harbour") -> DecisionStudioPage:
        self.open_window()
        page = self.window.show_page("events:decisions")
        self.settle()
        self.assertIsInstance(page, DecisionStudioPage)
        if ident:
            page.show_record(RecordRef("decision", ident))
            self.settle()
        return page


class DecisionTests(DecisionCase):
    def test_decision_blocks_phrases_and_preview(self):
        page = self.decisions()
        self.assertIn("Aland", page.potential_phrase.text())
        self.assertEqual([c.key for c in page.allow.tree().root.children], ["prestige", "musket_drill"])
        self.assertEqual([c.key for c in page.effect.tree().root.children],
                         ["prestige", "set_country_flag", "capital_scope"])
        self.assertEqual(page.ai.model().base, 1.0)
        data = page.preview.data()
        self.assertEqual(data.title, "Construir el puerto")
        self.assertIsNotNone(data.picture_image)
        self.assertIn("Aland", data.potential)

    def test_missing_picture_field_uses_the_decision_id(self):
        page = self.decisions("mg_call_council")
        self.assertEqual(page.picture.value(), "mg_build_harbour")
        page.show_record(RecordRef("decision", "mg_build_harbour"))
        self.settle()
        self.assertIsNone(page.picture.value())
        self.assertEqual(page.picture.combo.lineEdit().placeholderText(), "mg_build_harbour")
        self.assertEqual(page.preview.data().picture_name, "mg_build_harbour")

    def test_editing_an_effect_changes_only_its_line(self):
        page = self.decisions()
        rel = "decisions/mg_decisions.txt"
        before = self.text_of(rel)
        self.assertTrue(page.effect.select((0,)))
        self.assertTrue(page.effect.set_value(-10))
        self.settle()
        self.assertEqual(self.changed_lines(before, self.text_of(rel)),
                         [("\t\t\tprestige = -5", "\t\t\tprestige = -10")])

    def test_broken_decisions_open_as_text_and_the_fix_enables_the_form(self):
        page = self.decisions("tst_broken_one")
        self.assertIsNotNone(page.text_only)
        self.assertTrue(page.banner.isVisibleTo(page))
        self.assertTrue(page.potential.is_read_only())
        self.assertIn("1", page.banner.details.text())
        self.assertTrue(page.apply_text_fix())
        self.settle()
        page.show_record(RecordRef("decision", "tst_broken_one"))
        self.settle()
        self.assertIsNone(page.text_only)
        self.assertFalse(page.banner.isVisibleTo(page))
        self.assertFalse(page.potential.is_read_only())
        self.assertTrue(self.text_of("decisions/tst_broken.txt").rstrip().endswith("}"))
        self.window.session.undo()
        self.settle()
        page.show_record(RecordRef("decision", "tst_broken_one"))
        self.settle()
        self.assertIsNotNone(page.text_only, "deshacer devuelve el archivo roto, en modo texto")

    def test_every_visible_text_is_translated(self):
        page = self.decisions()
        translator().register_catalog(PSEUDO, pseudo_catalog())
        self.addCleanup(set_language, "es")
        set_language(PSEUDO)
        _qt.process_events(30)
        untranslated = {k: v for k, v in collect_texts(page).items() if MARK_OPEN not in v}
        self.assertEqual(untranslated, {}, "textos que no pasan por tr()")

    def test_modifiers_section_lists_event_modifiers(self):
        self.open_window()
        page = self.window.show_page("events:modifiers")
        self.settle()
        self.assertNotEqual(type(page).__name__, "PlannedSectionPage")


if __name__ == "__main__":
    unittest.main()
