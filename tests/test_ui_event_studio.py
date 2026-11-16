"""Event Studio (sala Eventos › Eventos, wizard §13.7, iteración 7): constructor de condiciones, MTTH,
opciones, imagen, vista previa y evento nuevo, con la ventana real sobre el minijuego de guion inventado.

Cada gesto es una transacción con su paso de deshacer y cambia solo lo que toca en el texto del archivo.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets)
from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_script_minigame  # noqa: E402
from test_ui_shell import DialogLog  # noqa: E402
from test_ui_smoke import MARK_OPEN, PSEUDO, UiTestCase, collect_texts, pseudo_catalog  # noqa: E402

APP = _qt.application()

from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.schema.record import RecordRef  # noqa: E402
from vic2studio.core.script.tree import SCOPE_MISMATCH  # noqa: E402
from vic2studio.core.vfs import VPath  # noqa: E402
from vic2studio.i18n import set_language, translator  # noqa: E402
from vic2studio.ui.halls.events.studio import EventStudioPage  # noqa: E402
from vic2studio.ui.main_window import UNSAVED_DISCARD  # noqa: E402

WAIT_MS = 30000
FLAVOR = "events/mg_flavor.txt"


class ScriptWindowCase(UiTestCase):
    """La ventana con el minijuego de guion abierto (proyecto, índice y textos reales)."""

    def setUp(self):
        super().setUp()
        isolate_appdirs(self)
        set_language("es")
        self.dialogs = DialogLog()

    def open_window(self, **kwargs):
        self.game = build_script_minigame(mod=True, **kwargs)
        self.addCleanup(self.game.cleanup)
        window = self.make_window()
        window.exec_dialog = self.dialogs
        window.ask_unsaved = mock.Mock(return_value=UNSAVED_DISCARD)
        page = window.page("project")
        page.set_game_path(self.game.game_root)
        page.set_mod_path(self.game.mod_root)
        session = window.session
        self.assertTrue(_qt.wait_until(lambda: session.project is not None and session.index_state() == "ready"
                                       and session.texts_ready() and not window.is_busy(), WAIT_MS),
                        "el proyecto no llegó a abrirse")
        self.window = window
        return window

    def settle(self):
        _qt.wait_until(lambda: not self.window.is_busy(), WAIT_MS)
        _qt.process_events(30)

    def text_of(self, rel: str) -> str:
        project = self.window.session.project
        handle = project.ws.peek(VPath.of(rel)) or project.ws.open(VPath.of(rel))
        return codec_for(handle.kind).snapshot(handle.model).decode("cp1252")

    def changed_lines(self, before: str, after: str) -> list[tuple[str, str]]:
        self.assertEqual(len(before.splitlines()), len(after.splitlines()))
        return [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]


class EventStudioCase(ScriptWindowCase):
    def studio(self, ident: str = "2001") -> EventStudioPage:
        self.open_window()
        page = self.window.show_page("events:events")
        self.settle()
        self.assertIsInstance(page, EventStudioPage)
        if ident:
            page.show_record(RecordRef("event", ident))
            self.settle()
        return page


class OpenTests(EventStudioCase):
    def test_the_studio_shows_the_event_with_its_phrase_and_preview(self):
        page = self.studio()
        self.assertIn("Aland", page.trigger_phrase.text())
        self.assertIn("1842 o después", page.trigger_phrase.text())
        self.assertEqual(page.trigger.model().rowCount(), 5)
        self.assertEqual(page.picture.value(), "mg_harbour")
        data = page.preview.data()
        self.assertEqual(data.title, "La cuestión del puerto")
        self.assertIsNotNone(data.picture_image, "la imagen inventada del minijuego se lee")
        self.assertEqual(len(data.options), 2)
        self.assertEqual(page.options.count(), 2)
        self.assertIn("2001", page.kind_label.text())

    def test_preview_switches_language_and_renders(self):
        page = self.studio()
        page.preview.set_preview_language("en")
        self.assertEqual(page.preview.data().title, "The harbour question")
        image = page.preview.render_image()
        self.assertGreater(image.width(), 500)
        self.assertGreater(image.height(), 200)

    def test_open_entity_from_elsewhere_lands_in_the_studio(self):
        self.open_window()
        self.assertTrue(self.window.open_entity("event", "2002"))
        self.settle()
        page = self.window.current_page()
        self.assertIsInstance(page, EventStudioPage)
        self.assertIn("2002", page.kind_label.text())

    def test_filter_by_country_or_province(self):
        page = self.studio("")
        page.set_filter("province")
        self.settle()
        self.assertEqual(page.navigator.view, "province")
        page.set_filter(None)
        self.assertIsNone(page.navigator.view)


class BuilderTests(EventStudioCase):
    def test_changing_a_value_changes_only_its_line_with_one_undo(self):
        page = self.studio()
        before = self.text_of(FLAVOR)
        self.assertTrue(page.trigger.select((1,)))
        self.assertTrue(page.trigger.set_value(1843))
        self.settle()
        after = self.text_of(FLAVOR)
        self.assertEqual(self.changed_lines(before, after),
                         [("\t\tyear = 1842 # desde ese año", "\t\tyear = 1843 # desde ese año")])
        self.assertIn("1843 o después", page.trigger_phrase.text())
        self.window.session.undo()
        self.settle()
        self.assertEqual(self.text_of(FLAVOR), before)

    def test_add_wrap_unwrap_and_remove(self):
        page = self.studio()
        before = self.text_of(FLAVOR)
        page.trigger.select(())
        self.assertTrue(page.trigger.add("prestige", 20))
        self.settle()
        self.assertIn("prestige = 20", self.text_of(FLAVOR))
        self.assertEqual(page.trigger.model().rowCount(), 6)
        self.assertTrue(page.trigger.select((5,)))
        self.assertTrue(page.trigger.wrap("NOT"))
        self.settle()
        self.assertEqual(page.trigger.tree().root.children[5].key, "NOT")
        self.assertTrue(page.trigger.select((5,)))
        self.assertTrue(page.trigger.unwrap())
        self.settle()
        self.assertEqual(page.trigger.tree().root.children[5].key, "prestige")
        self.assertTrue(page.trigger.select((5,)))
        self.assertTrue(page.trigger.remove())
        self.settle()
        self.assertEqual(self.text_of(FLAVOR), before)

    def test_raw_nodes_are_kept_and_editable_as_text(self):
        page = self.studio()
        tree = page.trigger.tree()
        self.assertEqual(tree.raw_count(), 1)
        self.assertTrue(page.trigger.select((4,)))
        self.assertTrue(page.trigger.edit_as_text("mg_made_up_check = 4"))
        self.settle()
        self.assertIn("\t\tmg_made_up_check = 4", self.text_of(FLAVOR))

    def test_picker_lists_by_language_and_adds_the_pick(self):
        page = self.studio()
        page.trigger.select(())
        with mock.patch("vic2studio.ui.script.catalog_picker.CatalogPickerDialog.open"):  # sin ventana propia
            page.trigger.open_picker()
        dialog = page.trigger.picker_dialog
        dialog.picker.set_filter("gobierno")
        names = [d.name for d in dialog.picker.results()]
        self.assertIn("government", names)
        definition = next(d for d in dialog.picker.results() if d.name == "government")
        dialog.picker.pick(definition)
        self.settle()
        self.assertTrue(any(c.key == "government" for c in page.trigger.tree().root.children[5:]))

    def test_scope_warning_in_a_province_event(self):
        page = self.studio("2002")
        problems = [p.code for p in page.trigger.tree().issues(self.window.session.entities.check_context())]
        self.assertIn(SCOPE_MISMATCH, problems)
        self.assertGreater(page.trigger.problem_count(), 0)

    def test_read_only_session_disables_editing(self):
        page = self.studio()
        with mock.patch.object(self.window.session, "is_read_only", return_value=True):
            page.bind_studio(RecordRef("event", "2001"))
            self.assertTrue(page.trigger.is_read_only())
            page.trigger.select((1,))
            self.assertFalse(page.trigger.set_value(1900))


class MtthTests(EventStudioCase):
    def test_effective_time_and_simulation(self):
        page = self.studio()
        self.assertAlmostEqual(page.mtth.effective(), 6 * 0.75 * 0.95)
        self.assertIn("4,3 meses", page.mtth.result.text())
        page.mtth.set_satisfied(0, False)
        self.assertAlmostEqual(page.mtth.effective(), 6 * 0.95)
        self.assertIn("5,7 meses", page.mtth.result.text())

    def test_factor_base_and_modifiers_edit_the_file(self):
        page = self.studio()
        before = self.text_of(FLAVOR)
        self.assertTrue(page.mtth.set_factor(0, 0.5))
        self.settle()
        self.assertEqual(self.changed_lines(before, self.text_of(FLAVOR)),
                         [("\t\t\tfactor = 0.75", "\t\t\tfactor = 0.5")])
        self.assertTrue(page.mtth.set_base(12))
        self.settle()
        self.assertIn("\t\tmonths = 12", self.text_of(FLAVOR))
        self.assertTrue(page.mtth.add_modifier(2.0))
        self.settle()
        self.assertEqual(len(page.mtth.model().modifiers), 3)
        self.assertTrue(page.mtth.remove_modifier(2))
        self.settle()
        self.assertEqual(len(page.mtth.model().modifiers), 2)

    def test_modifier_conditions_open_in_their_builder(self):
        page = self.studio()
        page.open_modifier(1)
        self.settle()
        self.assertTrue(page.modifier_builder.isVisibleTo(page))
        self.assertEqual([c.key for c in page.modifier_builder.tree().root.children], ["is_greater_power"])


class OptionTests(EventStudioCase):
    def test_option_texts_in_both_languages(self):
        page = self.studio()
        card = page.options.card(0)
        self.assertEqual(card.name_key(), "EVTOPTA2001")
        self.assertEqual(card.text("es"), "Construirlo")
        self.assertEqual(card.text("en"), "Build it")
        self.assertTrue(card.set_text("es", "Construirlo ya"))
        self.settle()
        self.assertEqual(self.window.session.locsync.text("EVTOPTA2001", "es"), "Construirlo ya")

    def test_add_move_and_remove_options(self):
        page = self.studio()
        before = self.text_of(FLAVOR)
        self.assertEqual(page.options.next_key(), "EVTOPTC2001")
        self.assertTrue(page.options.add_option())
        self.settle()
        self.assertEqual(page.options.count(), 3)
        self.assertIn('name = "EVTOPTC2001"', self.text_of(FLAVOR))
        self.assertTrue(page.options.move_option(2, 0))
        self.settle()
        self.assertEqual(page.options.card(0).name_key(), "EVTOPTC2001")
        self.assertTrue(page.options.remove_option(0))
        self.settle()
        self.assertEqual(page.options.count(), 2)
        self.assertEqual(self.text_of(FLAVOR), before)

    def test_option_effects_and_ai_chance(self):
        page = self.studio()
        card = page.options.card(0)
        self.assertEqual([c.key for c in card.effects.tree().root.children], ["prestige", "any_owned"])
        self.assertEqual(card.ai_chance.model().base, 70.0)


class NewEventTests(EventStudioCase):
    def test_new_event_takes_the_first_free_id(self):
        page = self.studio("")
        self.assertEqual(page.next_free_id(), "200000000")
        self.assertTrue(page.ask_new())
        self.settle()
        self.assertEqual(page._current.ident, "200000000")
        source = self.text_of("events/TESTMOD_events.txt")
        self.assertIn("id = 200000000", source)
        csv = self.text_of("localisation/00_TESTMOD_events.csv")
        for key in ("EVTNAME", "EVTDESC", "EVTOPTA", "EVTOPTB"):
            self.assertIn(f"{key}200000000;", csv)
        self.assertEqual(page.next_free_id(), "200000001")

    def test_province_filter_creates_a_province_event(self):
        page = self.studio("")
        page.set_filter("province")
        self.settle()
        self.assertTrue(page.ask_new())
        self.settle()
        self.assertIn("province_event = {", self.text_of("events/TESTMOD_events.txt"))

    def test_taken_id_proposes_the_next_free(self):
        page = self.studio("")
        self.assertTrue(page.ask_new())
        self.settle()
        statuses = []
        page.status_requested.connect(lambda key, fmt: statuses.append((key, fmt)))
        self.assertFalse(page.create("200000000"))
        key, fmt = statuses[-1]
        self.assertEqual(key, "entity.create_failed")
        self.assertIn("200000001", fmt["reason"], "el mensaje propone el siguiente id libre")


class PictureTests(EventStudioCase):
    def test_import_converts_to_the_game_format(self):
        page = self.studio()
        from PIL import Image

        source = Path(self.game.mod_root).parent / "own.png"
        Image.new("RGB", (800, 400), (10, 200, 30)).save(source)
        self.assertTrue(page.picture.import_image(source, "own_picture"))
        self.settle()
        rel = VPath.of("gfx/pictures/events/own_picture.tga")
        handle = self.window.session.project.ws.peek(rel)
        self.assertIsNotNone(handle)
        with Image.open(__import__("io").BytesIO(bytes(handle.model))) as image:
            self.assertEqual(image.size, (521, 203))
        self.assertRegex(self.text_of(FLAVOR), r'\tpicture = "?own_picture"?\r?\n')
        self.assertEqual(page.picture.value(), "own_picture")
        self.window.session.undo()
        self.settle()
        self.assertIn('picture = "mg_harbour"', self.text_of(FLAVOR))
        handle = self.window.session.project.ws.peek(rel)
        self.assertTrue(handle is None or handle.deleted, "deshacer quita también la imagen importada")


class LanguageTests(EventStudioCase):
    def test_every_visible_text_is_translated(self):
        page = self.studio()
        translator().register_catalog(PSEUDO, pseudo_catalog())
        self.addCleanup(set_language, "es")
        set_language(PSEUDO)
        _qt.process_events(30)
        texts = collect_texts(page)
        untranslated = {k: v for k, v in texts.items() if MARK_OPEN not in v}
        self.assertEqual(untranslated, {}, "textos que no pasan por tr()")

    def test_english_labels(self):
        page = self.studio()
        set_language("en")
        self.addCleanup(set_language, "es")
        _qt.process_events(30)
        page.bind_studio(RecordRef("event", "2001"))
        self.assertIn("1842 or later", page.trigger_phrase.text())
        self.assertIn("4.3 months", page.mtth.result.text())


CB_WITH_SCRIPT = """\
peace_order = {
	conquer_land
}

conquer_land = {
	sprite_index = 1
	months = 12
	can_use = {
		prestige = 5
		OR = { tag = AAA tag = BBB }
	}
	on_add = { prestige = 1 }
	war_name = CONQUER_LAND_WAR
}
"""


class CasusBelliScriptTests(ScriptWindowCase):
    """Los bloques de guion de los CB pasan del editor de código al constructor (§22, iteración 7)."""

    def test_can_use_shows_its_phrase_and_opens_the_builder(self):
        from vic2studio.ui.forms.editors import ScriptFieldEditor

        self.open_window(game_files={"common/cb_types.txt": CB_WITH_SCRIPT})
        page = self.window.show_page("war:cb")
        self.settle()
        page.show_record(RecordRef("casus_belli", "conquer_land"))
        self.settle()
        editor = page.form.editor("can_use")
        self.assertIsInstance(editor, ScriptFieldEditor)
        self.assertIn("Aland", editor.phrase.text())
        self.assertIsInstance(page.form.editor("on_add"), ScriptFieldEditor)
        with mock.patch("PySide6.QtWidgets.QDialog.open"):        # sin ventana propia en la prueba
            dialog = editor.open_builder()
        builder = dialog.builder
        self.assertEqual([c.key for c in builder.tree().root.children], ["prestige", "OR"])
        before = self.text_of("common/cb_types.txt")
        self.assertTrue(builder.select((0,)))
        self.assertTrue(builder.set_value(7))
        self.settle()
        self.assertEqual(self.changed_lines(before, self.text_of("common/cb_types.txt")),
                         [("\t\tprestige = 5", "\t\tprestige = 7")])
        self.window.session.undo()
        self.settle()
        self.assertEqual(self.text_of("common/cb_types.txt"), before)


if __name__ == "__main__":
    unittest.main()
