"""Editor genérico de entidades y secciones de la iteración 4 (wizard §13.5, ENCARGO_IT4 fase 4).

La ventana real con la ``Session`` real (índice, textos y validación del núcleo) sobre el minijuego con los
fragmentos de los esquemas (``SCHEMA_GAME_FILES``). Comprueba las secciones que salen del registro, el
navegador (lista, Nuevo, Duplicar, Borrar con usos, Restaurar), las pestañas, la matriz de rebeldes, el editor de
``end_date``, Ctrl+K hacia el editor de entidad y F7 hacia el campo.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets)
from _layers import isolate_appdirs  # noqa: E402
from _minigame import SCHEMA_GAME_FILES, build_minigame  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402
from test_ui_shell import DialogLog  # noqa: E402
from test_ui_smoke import MARK_OPEN, PSEUDO, UiTestCase, collect_texts, pseudo_catalog  # noqa: E402

APP = _qt.application()

from vic2studio.core.clausewitz.nodes import ClausewitzDate  # noqa: E402
from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.schema import EntitySchema, Field, Int, RecordRef, Section, SingleFile, registry  # noqa: E402
from vic2studio.core.vfs import VPath  # noqa: E402
from vic2studio.i18n import set_language, tr, translator  # noqa: E402
from vic2studio.ui.entity import EntityEditorPage, NewEntityDialog, UnitNamesDialog, UsesDialog  # noqa: E402
from vic2studio.ui.halls import discover_halls  # noqa: E402
from vic2studio.ui.halls.registry import SectionSpec, merge_schema_sections, schema_sections  # noqa: E402
from vic2studio.ui.main_window import UNSAVED_DISCARD  # noqa: E402
from vic2studio.ui.pages import PlannedSectionPage  # noqa: E402

SECTIONS = {"nations:cultures": ("culture", None), "nations:governments": ("government", None),
            "war:bookmarks": ("bookmark", None), "war:cb": ("casus_belli", None), "war:land": ("unit", "land"),
            "war:naval": ("unit", "naval"), "events:modifiers": ("event_modifier", None)}
WAIT_MS = 20000


class EntityWindowCase(UiTestCase):
    """La ventana con el minijuego abierto con todo real; ``self.dialogs`` contesta los diálogos."""

    def setUp(self):
        super().setUp()
        isolate_appdirs(self)
        self.dialogs = DialogLog()

    def open_window(self, *, game_files=None, mod_files=None, mod_copies=(), read_only=False):
        files = dict(SCHEMA_GAME_FILES)
        files.update(game_files or {})
        self.game = build_minigame(mod=True, game_files=files, mod_files=mod_files, mod_copies=mod_copies)
        self.addCleanup(self.game.cleanup)
        if read_only:
            from vic2studio.core.project import Project

            holder = Project.open(self.game.game_root, self.game.mod_root)
            self.addCleanup(holder.close)
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

    def section(self, key: str) -> EntityEditorPage:
        page = self.window.show_page(key)
        _qt.process_events(20)
        self.assertIsInstance(page, EntityEditorPage)
        return page

    def settle(self):
        session = self.window.session
        _qt.wait_until(lambda: not self.window.is_busy(), WAIT_MS)
        _qt.process_events(20)
        return session

    def text_of(self, rel) -> str:
        handle = self.window.session.project.ws.open(rel)
        return codec_for(handle.kind).snapshot(handle.model).decode("cp1252")


class RegistrySectionTests(unittest.TestCase):
    """Decisión 1: las secciones de entidades salen del registro de esquemas."""

    def test_every_editable_schema_with_a_section_is_in_its_hall(self):
        found = {}
        for hall, sections in discover_halls():
            for section in sections:
                found[f"{hall.key}:{section.key}"] = section
        for key, (kind, view) in SECTIONS.items():
            with self.subTest(section=key):
                spec = found[key]
                self.assertEqual((spec.schema_kind, spec.view), (kind, view))
                self.assertFalse(spec.planned)
                self.assertIsNotNone(spec.factory)
                self.assertIsNotNone(spec.badge)
        generated = {(s.schema_kind, s.view) for s in found.values() if s.schema_kind}
        self.assertEqual(generated, set(SECTIONS.values()), "ningún esquema de solo lectura tiene sección")

    def test_a_new_schema_appears_without_touching_ui(self):
        """Criterio 6: un esquema con ``hall`` y ``section`` da su sección; con una clave planificada, la sustituye."""
        fake = EntitySchema(kind="fake_thing", layout=SingleFile("common/fake.txt"),
                            fields=(Section("general", (Field("size", Int()),)),), hall="events", section="fake",
                            order=9, icon="gear")
        generated = schema_sections("events", [fake])
        self.assertEqual([(s.key, s.order, s.schema_kind) for s in generated], [("fake", 9, "fake_thing")])
        planned = SectionSpec("fake", "events", 9, "section.events.modifiers", "gear", iteration=7)
        merged = merge_schema_sections([planned], generated)
        self.assertEqual(len(merged), 1)
        self.assertFalse(merged[0].planned, "la del esquema sustituye a la planificada")
        self.assertEqual(schema_sections("map", [fake]), [], "solo en su sala")

    def test_without_the_schema_the_planned_card_comes_back(self):
        events = next(sections for hall, sections in discover_halls() if hall.key == "events")
        declared = [s for s in __import__("vic2studio.ui.halls.events", fromlist=["SECTIONS"]).SECTIONS]
        self.assertTrue(any(s.key == "modifiers" and s.planned for s in declared),
                        "la tarjeta planificada sigue como reserva en la sala")
        modifiers = next(s for s in events if s.key == "modifiers")
        self.assertEqual(modifiers.schema_kind, "event_modifier")
        self.assertEqual(merge_schema_sections(declared, [])[2].planned, True)


class SectionWindowTests(EntityWindowCase):
    def test_sections_are_entity_pages_with_their_lists(self):
        window = self.open_window()
        expected = {"war:cb": ["conquer_land", "free_people", "humble_rival"], "war:bookmarks": ["MG_LATE", "MG_START"],
                    "war:land": ["infantry"], "war:naval": ["frigate"],
                    "nations:governments": ["council", "monarchy", "republic"],
                    "nations:cultures": ["alander", "borlander", "corlander", "dominer"],
                    "events:modifiers": ["bad_winter", "good_harvest"]}
        for key, idents in expected.items():
            with self.subTest(section=key):
                page = self.section(key)
                self.assertEqual(page.navigator.idents(), idents)
                hall, section = key.split(":")
                rail = window.hall(hall)
                window.set_current_hall(hall)
                _qt.process_events(20)
                rail.refresh_badges()
                self.assertEqual(rail.rail.buttons[rail.section_index(section)].badge, len(idents))
        self.assertNotIsInstance(window.page("war:cb"), PlannedSectionPage)
        self.assertIsInstance(window.page("war:wars"), PlannedSectionPage)

    def test_without_a_project_the_page_says_so(self):
        window = self.make_window()
        page = window.show_page("war:cb")
        _qt.process_events(20)
        self.assertTrue(page.empty_label.isVisible())
        self.assertEqual(page.empty_label.text(), tr("entity.no_project"))
        self.assertFalse(page.navigator.new_button.isEnabled())

    def test_tabs_texts_uses_code_and_other_fields(self):
        self.open_window()
        page = self.section("war:land")
        self.assertEqual(page.current_ref().ident, "infantry")
        self.assertTrue(page.tabs.isVisible())
        self.assertEqual([page.tabs.tabText(i) for i in range(page.tabs.count())],
                         [tr("entity.tab.form"), tr("entity.tab.texts"), tr("entity.tab.uses"), tr("entity.tab.code"),
                          tr("entity.tab.other")])
        self.assertEqual(page.origin_badge.text(), tr("entity.origin.game"))
        uses = [page.uses.item(i).text() for i in range(page.uses.count())]
        self.assertTrue(any("activate_unit" in use for use in uses), uses)
        # Textos: las dos claves de la unidad; escribir el español crea la clave en el mod en una transacción.
        texts = page.texts.table
        self.assertEqual([texts.item(r, 0).text() for r in range(texts.rowCount())], ["infantry", "infantry_short"])
        texts.item(0, 1).setText("Infantería")
        session = self.settle()
        self.assertEqual(session.locsync.text("infantry", "es"), "Infantería")
        self.assertEqual(len(session.history()), 1)
        # Código: el archivo de la unidad, en la línea del bloque.
        page.show_code()
        _qt.process_events(20)
        self.assertEqual(page.code.current_rel().key, VPath("units/infantry.txt").key)
        self.assertEqual(page.code.editor.textCursor().blockNumber(), 0)
        # Otros campos: una clave que el esquema no conoce se conserva y se puede editar.
        with session.edit("forms.undo_edit", field="attack", ident="infantry"):
            record = session.entities.open(RecordRef("unit", "infantry"))
            record._touch()
            record.block.append("mystery", "1")
        self.settle()
        other = page.other.table
        self.assertEqual([other.item(r, 0).text() for r in range(other.rowCount())], ["mystery"])
        other.item(0, 1).setText("2")
        self.settle()
        self.assertIn("mystery = 2", self.text_of("units/infantry.txt"))

    def test_create_cb_and_undo_from_the_window(self):
        window = self.open_window()
        page = self.section("war:cb")

        def answer(dialog: NewEntityDialog):
            dialog.ident_edit.setText("my_cb")
            self.assertTrue(dialog.template_radio.isChecked())
            dialog.accept()

        self.dialogs.handlers[NewEntityDialog] = answer
        page.navigator.new_button.click()
        session = self.settle()
        self.assertEqual(page.current_ref().ident, "my_cb")
        self.assertIn("my_cb", page.navigator.idents())
        self.assertEqual(len(session.history()), 1, "crear es un solo paso")
        self.assertEqual(page.origin_badge.text(), tr("entity.origin.game"),
                         "cb_types.txt aún es el del juego: se copiará al guardar")
        window.undo()
        self.settle()
        self.assertNotIn("my_cb", page.navigator.idents())
        self.assertEqual(session.dirty_count(), 0)

    def test_new_dialog_validates_the_id(self):
        self.open_window()
        page = self.section("war:cb")
        seen = []

        def answer(dialog: NewEntityDialog):
            ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
            for text, enabled in (("", False), ("1bad", False), ("conquer_land", False), ("fine_cb", True)):
                dialog.ident_edit.setText(text)
                seen.append((text, ok.isEnabled()))
                self.assertEqual(ok.isEnabled(), enabled, text)
            self.assertEqual(dialog.message.text(), "")
            dialog.reject()

        self.dialogs.handlers[NewEntityDialog] = answer
        self.assertFalse(page.ask_new())
        self.assertEqual(len(seen), 4)
        self.assertEqual(self.window.session.history(), [])

    def test_delete_with_uses_is_blocked_and_shows_them(self):
        self.open_window()
        page = self.section("war:cb")
        shown = []
        self.dialogs.handlers[UsesDialog] = lambda dialog: (shown.append(dialog.list.count()), dialog.reject())
        page.navigator.select(RecordRef("casus_belli", "conquer_land"))
        page.navigator.delete_button.click()
        self.assertEqual(shown, [1], "la guerra de inicio usa conquer_land")
        self.assertIn("conquer_land", page.navigator.idents())
        self.assertEqual(self.window.session.history(), [])
        page.navigator.select(RecordRef("casus_belli", "humble_rival"))
        page.navigator.delete_button.click()
        self.settle()
        self.assertNotIn("humble_rival", page.navigator.idents())

    def test_government_matrix_of_rebels(self):
        self.open_window()
        page = self.section("nations:governments")
        self.assertTrue(page.create("junta"))
        self.settle()
        self.assertEqual(page.tabs.tabText(page.tabs.currentIndex()), tr("entity.tab.rebels"))
        matrix = page.rebels
        self.assertEqual(matrix.table.rowCount(), 2, "las 2 tablas del minijuego")
        self.assertEqual(matrix.missing(), [])
        combo = matrix.table.cellWidget(1, 1)
        combo.setCurrentIndex(combo.findData("monarchy"))
        combo.activated.emit(combo.currentIndex())
        self.settle()
        self.assertIn("junta = monarchy", self.text_of("common/rebel_types.txt"))
        self.assertEqual(len(self.window.session.history()), 2)

    def test_naval_unit_based_on_frigate_offers_unit_names(self):
        from _minigame import UNIT_NAMES_COUNTRY

        self.open_window(game_files={"common/countries/Aland.txt": UNIT_NAMES_COUNTRY})
        page = self.section("war:naval")
        offered = []

        def names(dialog: UnitNamesDialog):
            offered.append(dialog.chosen())
            dialog.accept()

        self.dialogs.handlers[UnitNamesDialog] = names
        self.assertTrue(page.create("corvette", base=RecordRef("unit", "frigate")))
        self.settle()
        self.assertEqual(offered, [[VPath("common/countries/Aland.txt")]])
        self.assertIn("corvette = {", self.text_of("common/countries/Aland.txt"))
        self.assertEqual(page.navigator.idents(), ["corvette", "frigate"])
        self.assertNotIn("corvette", self.section("war:land").navigator.idents())

    def test_culture_tree_and_group_form(self):
        self.open_window()
        page = self.section("nations:cultures")
        tree = page.navigator.tree
        self.assertEqual([tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())],
                         ["north_folk", "south_folk"])
        page.navigator.select(RecordRef("culture_group", "south_folk"))
        _qt.process_events(20)
        self.assertEqual(page.form.schema.kind, "culture_group")
        self.assertFalse(page.navigator.delete_button.isEnabled())
        self.assertTrue(page.create("newfolk", group="south_folk"))
        self.settle()
        self.assertEqual(page.form.schema.kind, "culture")
        self.assertEqual(self.window.session.entities.parent(RecordRef("culture", "newfolk")), "south_folk")

    def test_end_date_editor_and_late_bookmarks(self):
        self.open_window()
        page = self.section("war:bookmarks")
        panel = page.end_date_panel
        self.assertEqual(panel.end_date(), ClausewitzDate(1935, 12, 31))
        self.assertTrue(page.create("MG_FAR"))
        self.settle()
        form = page.form
        form.editor("date").picker.edit.setText("1950.1.1")
        form.editor("date").picker.edit.editingFinished.emit()
        self.settle()
        panel.refresh()
        self.assertEqual(panel.late_bookmarks(), [("MG_FAR", ClausewitzDate(1950, 1, 1))])
        self.assertTrue(panel.extend_button.isVisibleTo(page))
        self.assertTrue(panel.extend_to_bookmarks())
        self.settle()
        self.assertEqual(panel.end_date(), ClausewitzDate(1950, 1, 1))
        self.assertIn("end_date = '1950.1.1'", self.text_of("common/defines.lua"))
        self.assertEqual(panel.late_bookmarks(), [])

    def test_restore_vanilla_from_the_window(self):
        self.open_window(mod_copies=("units/infantry.txt",))
        page = self.section("war:land")
        self.assertEqual(page.origin_badge.text(), tr("entity.origin.mod_over_game"))
        self.assertTrue(page.navigator.restore_button.isEnabled(), "una copia del mod se puede quitar (I11)")
        with self.window.session.edit("forms.undo_edit", field="attack", ident="infantry"):
            self.window.session.entities.open(RecordRef("unit", "infantry")).set("attack", 7.0)
        self.window.session.save()
        self.settle()
        page.refresh()
        self.assertTrue(page.navigator.restore_button.isEnabled())
        page.navigator.restore_button.click()
        self.settle()
        self.assertIn("infantry", page.navigator.idents())
        self.assertEqual(page.origin_badge.text(), tr("entity.origin.game"))
        self.assertIsNone(self.window.session.entities.open(RecordRef("unit", "infantry")).get("attack", None))

    def test_read_only_project_disables_editing(self):
        self.open_window(read_only=True)
        page = self.section("war:cb")
        self.assertFalse(page.navigator.new_button.isEnabled())
        self.assertFalse(page.navigator.delete_button.isEnabled())
        editor = page.form.editor("months")
        self.assertFalse(editor.edit.isEnabled())
        from PySide6.QtCore import Qt

        texts = page.texts.table
        self.assertFalse(texts.item(0, 1).flags() & Qt.ItemFlag.ItemIsEditable, "los textos tampoco se editan")


class NavigationTests(EntityWindowCase):
    def test_ctrl_k_symbol_opens_the_entity_editor(self):
        window = self.open_window()
        session = window.session
        symbol = next(s for s in session.search("free_people") if s.kind == "cb")
        self.assertTrue(window.open_symbol(symbol))
        page = window.current_page()
        self.assertIsInstance(page, EntityEditorPage)
        self.assertEqual(window.current_page_key(), "war:cb")
        self.assertEqual(page.current_ref().ident, "free_people")
        frigate = next(s for s in session.search("frigate") if s.kind == "unit_type")
        self.assertTrue(window.open_symbol(frigate))
        self.assertEqual(window.current_page_key(), "war:naval", "cada unidad en la sección de su vista")
        group = next(s for s in session.search("south_folk") if s.kind == "culture_group")
        self.assertTrue(window.open_symbol(group))
        self.assertEqual(window.current_page_key(), "nations:cultures")
        self.assertEqual(window.current_page().form.schema.kind, "culture_group")

    def test_f7_problem_of_an_entity_leads_to_its_field(self):
        window = self.open_window()
        session = window.session
        with session.edit("forms.undo_edit", field="attack", ident="infantry"):
            record = session.entities.open(RecordRef("unit", "infantry"))
            record._touch()
            record.block.append("attack", "abc")
        self.settle()
        self.assertTrue(window.validate_mod())
        self.assertTrue(_qt.wait_until(lambda: session.validation_state() == "ready" and not window.is_busy(),
                                       WAIT_MS))
        problem = next(p for p in session.problems() if p.code == "bad_type")
        self.assertEqual((problem.entity, problem.field), (("unit", "infantry"), ("attack",)))
        self.assertIn(problem.message("es"), [p.message("es") for p in session.problems()])
        self.assertTrue(window.open_problem(problem))
        page = window.current_page()
        self.assertEqual(window.current_page_key(), "war:land")
        self.assertEqual(page.current_ref().ident, "infantry")
        editor = page.form.editor("attack")
        self.assertTrue(editor.edit.hasFocus() or editor.edit.isVisible())
        self.assertIs(APP.focusWidget(), editor.edit)


class TranslationTests(EntityWindowCase):
    def test_entity_pages_retranslate_and_pass_the_pseudo_locale(self):
        window = self.open_window()
        translator().register_catalog(PSEUDO, pseudo_catalog())
        for key in SECTIONS:
            with self.subTest(section=key):
                page = window.show_page(key)
                _qt.process_events(20)
                set_language("es")
                spanish = collect_texts(page)
                set_language("en")
                english = collect_texts(page)
                self.assertGreater(sum(1 for k in spanish if spanish[k] != english.get(k)), 20)
                set_language(PSEUDO)
                texts = collect_texts(page)
                untranslated = {k: v for k, v in texts.items() if MARK_OPEN not in v}
                self.assertEqual(untranslated, {}, f"{key}: textos que no pasan por tr()")
                set_language("es")


class NewDialogUnitTests(unittest.TestCase):
    def test_result_values(self):
        schema = registry.get("culture")
        dialog = NewEntityDialog(schema, [RecordRef("culture", "alander")], ["north_folk", "south_folk"],
                                 group="south_folk")
        dialog.ident_edit.setText("x_folk")
        self.assertEqual(dialog.result_values(), ("x_folk", None, "south_folk"))
        dialog.base_radio.setChecked(True)
        self.assertEqual(dialog.result_values()[1], RecordRef("culture", "alander"))
        dialog.deleteLater()
        self.assertEqual(QDialog.DialogCode.Accepted, QDialog.DialogCode.Accepted)


if __name__ == "__main__":
    unittest.main()
