"""Cierre de la iteración 4 en la interfaz: renombrar con su plan (wizard §15), mover culturas de grupo y crear
grupos (§14.13) y la ficha de unidad (§14.4: estadísticas comparadas, dónde se desbloquea y el modelo).

La ventana real con la ``Session`` real sobre el minijuego, como ``test_ui_entity``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets)
from _minigame import _crlf  # noqa: E402
from PySide6.QtWidgets import QDialogButtonBox  # noqa: E402
from test_ui_entity import EntityWindowCase  # noqa: E402

APP = _qt.application()

from vic2studio.core.schema import RecordRef  # noqa: E402
from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.entity import MoveGroupDialog, NewEntityDialog, RenameEntityDialog  # noqa: E402
from vic2studio.ui.entity.editor_page import TAB_UNIT  # noqa: E402

ACTORS_GFX = _crlf('objectTypes = {\n\tEMFXActorType = {\n\t\tname = "NorthGCInfantry"\n\t}\n'
                   '\tEMFXActorType = {\n\t\tname = "GenericInfantry"\n\t}\n'
                   '\tEMFXActorType = {\n\t\tname = "GenericGuard"\n\t}\n'
                   '\tEMFXActorType = {\n\t\tname = "GenericFrigate"\n\t}\n}\n')
UNITS = {
    "units/infantry.txt": _crlf("infantry = {\n\ttype = land\n\tunit_type = infantry\n\tactive = no\n"
                                "\tsprite = Infantry\n\tmax_strength = 3\n\tattack = 2\n\tdefence = 3\n}\n"),
    "units/guard.txt": _crlf("guard = {\n\ttype = land\n\tunit_type = infantry\n\tactive = no\n\tsprite = Guard\n"
                             "\tmax_strength = 3\n\tattack = 5\n\tdefence = 2\n\tsiege = 1\n}\n"),
    "interface/actors.gfx": ACTORS_GFX,
}
OK = QDialogButtonBox.StandardButton.Ok


class RenameWindowTests(EntityWindowCase):
    def test_the_dialog_shows_the_plan_and_blocks_a_bad_id(self):
        self.open_window()
        entities = self.window.session.entities
        dialog = RenameEntityDialog(entities, RecordRef("government", "monarchy"))
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.buttons.button(OK).isEnabled(), "el id sin cambiar no se puede aceptar")
        self.assertEqual(dialog.message.text(), "", "sin escribir nada no hay error que enseñar")
        self.assertGreater(dialog.files.count(), 1, "la definición y los archivos con usos")
        listed = "\n".join(dialog.files.item(i).text() for i in range(dialog.files.count()))
        self.assertIn("common/governments.txt", listed)
        self.assertIn("history/countries/AAA - Aland.txt", listed)
        dialog.ident_edit.setText("republic")
        dialog.update_plan()
        self.assertFalse(dialog.buttons.button(OK).isEnabled())
        self.assertEqual(dialog.message.text(), tr("entity.ident.taken", ident="republic"))
        dialog.ident_edit.setText("bad id")
        dialog.update_plan()
        self.assertFalse(dialog.buttons.button(OK).isEnabled())
        dialog.ident_edit.setText("kingdom")
        self.assertFalse(dialog.buttons.button(OK).isEnabled(), "hasta que haya plan para el texto nuevo")
        dialog.update_plan()
        self.assertTrue(dialog.buttons.button(OK).isEnabled())
        self.assertEqual(dialog.message.text(), "")
        self.assertIn(str(len(dialog.plan.files)), dialog.summary.text())
        self.assertFalse(self.window.session.dirty_count(), "el plan no cambia nada")
        self.assertEqual(self.window.session.history(), [])

    def test_rename_from_the_window_is_one_undo_step(self):
        self.open_window()
        page = self.section("nations:governments")
        before = {rel: self.text_of(rel) for rel in ("common/governments.txt", "history/countries/AAA - Aland.txt",
                                                     "common/rebel_types.txt")}
        self.assertTrue(page.navigator.rename_button.isEnabled())

        def accept(dialog: RenameEntityDialog):
            dialog.ident_edit.setText("kingdom")
            dialog.accept()      # calcula el plan pendiente antes de aceptar

        self.dialogs.handlers[RenameEntityDialog] = accept
        page.navigator.select(RecordRef("government", "monarchy"))
        page.navigator.rename_button.click()
        self.settle()
        self.assertIn("kingdom", page.navigator.idents())
        self.assertNotIn("monarchy", page.navigator.idents())
        self.assertEqual(page.current_ref().ident, "kingdom")
        self.assertIn("government = kingdom", self.text_of("history/countries/AAA - Aland.txt"))
        self.assertIn("kingdom = republic", self.text_of("common/rebel_types.txt"))
        self.assertEqual(len(self.window.session.history()), 1, "un solo paso de deshacer")
        self.window.session.undo()
        self.settle()
        for rel, text in before.items():
            self.assertEqual(self.text_of(rel), text, rel)
        self.assertIn("monarchy", page.navigator.idents())

    def test_a_rejected_rename_changes_nothing_and_says_why(self):
        self.open_window()
        page = self.section("nations:governments")
        statuses = []
        page.status_requested.connect(lambda key, params: statuses.append((key, params)))
        self.assertFalse(page.rename(RecordRef("government", "monarchy"), "republic"))
        self.assertEqual(statuses[-1][0], "entity.rename.failed")
        self.assertEqual(statuses[-1][1]["reason"], tr("entity.ident.taken", ident="republic"))
        self.assertEqual(self.window.session.history(), [])
        self.assertFalse(self.window.session.dirty_count())

    def test_a_unit_of_the_base_game_says_it_cannot_be_renamed(self):
        self.open_window()
        entities = self.window.session.entities
        dialog = RenameEntityDialog(entities, RecordRef("unit", "infantry"))
        self.addCleanup(dialog.deleteLater)
        dialog.ident_edit.setText("line_infantry")
        dialog.update_plan()
        self.assertFalse(dialog.buttons.button(OK).isEnabled())
        self.assertIn("units/infantry.txt", dialog.message.text())

    def test_read_only_project_disables_rename_and_groups(self):
        self.open_window(read_only=True)
        page = self.section("nations:cultures")
        for button in (page.navigator.rename_button, page.navigator.move_button, page.navigator.new_group_button):
            self.assertFalse(button.isEnabled())
        self.assertFalse(page.rename(RecordRef("culture", "alander"), "alandic"))


class CultureGroupWindowTests(EntityWindowCase):
    def test_move_a_culture_to_another_group_and_undo(self):
        self.open_window()
        page = self.section("nations:cultures")
        before = self.text_of("common/cultures.txt")
        entities = self.window.session.entities
        self.assertEqual(entities.parent(RecordRef("culture", "alander")), "north_folk")
        shown = []

        def choose(dialog: MoveGroupDialog):
            shown.append([dialog.combo.itemData(i) for i in range(dialog.combo.count())])
            dialog.combo.setCurrentIndex(dialog.combo.findData("south_folk"))
            dialog.accept()

        self.dialogs.handlers[MoveGroupDialog] = choose
        page.navigator.select(RecordRef("culture", "alander"))
        self.assertTrue(page.navigator.move_button.isEnabled())
        page.navigator.move_button.click()
        self.settle()
        self.assertEqual(shown, [["south_folk"]], "el grupo donde ya está no se ofrece")
        self.assertEqual(entities.parent(RecordRef("culture", "alander")), "south_folk")
        self.assertEqual(page.current_ref().ident, "alander")
        self.assertEqual(len(self.window.session.history()), 1)
        self.window.session.undo()
        self.settle()
        self.assertEqual(self.text_of("common/cultures.txt"), before)

    def test_the_move_button_is_for_cultures_not_for_groups(self):
        self.open_window()
        page = self.section("nations:cultures")
        page.navigator.select(RecordRef("culture_group", "south_folk"))
        _qt.process_events(20)
        self.assertFalse(page.navigator.move_button.isEnabled())
        self.assertTrue(page.navigator.rename_button.isEnabled(), "un grupo también se renombra")
        self.assertFalse(self.section("nations:governments").navigator.move_button.isVisible())

    def test_new_group_appears_empty_and_takes_a_culture(self):
        self.open_window()
        page = self.section("nations:cultures")

        def name(dialog: NewEntityDialog):
            self.assertEqual(dialog.schema.kind, "culture_group")
            dialog.ident_edit.setText("east_folk")
            dialog.accept()

        self.dialogs.handlers[NewEntityDialog] = name
        page.navigator.new_group_button.click()
        self.settle()
        tree = page.navigator.tree
        self.assertEqual([tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())],
                         ["north_folk", "south_folk", "east_folk"], "el grupo vacío también sale")
        self.assertEqual(page.current_ref(), RecordRef("culture_group", "east_folk", page.current_ref().rel))
        self.assertEqual(page.form.schema.kind, "culture_group")
        self.assertTrue(page.move_to_group(RecordRef("culture", "alander"), "east_folk"))
        self.settle()
        self.assertEqual(self.window.session.entities.parent(RecordRef("culture", "alander")), "east_folk")
        self.assertEqual(len(self.window.session.history()), 2)

    def test_renaming_a_group_keeps_its_cultures(self):
        self.open_window()
        page = self.section("nations:cultures")
        self.assertTrue(page.rename(RecordRef("culture_group", "south_folk"), "southern_folk"))
        self.settle()
        tree = page.navigator.tree
        self.assertEqual([tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())],
                         ["north_folk", "southern_folk"])
        self.assertEqual(page.current_ref().ident, "southern_folk")


class UnitPanelTests(EntityWindowCase):
    def open_units(self, **extra):
        files = dict(UNITS)
        files.update(extra)
        self.open_window(game_files=files)
        page = self.section("war:land")
        page.navigator.select(RecordRef("unit", "guard"))
        _qt.process_events(20)
        return page

    def test_only_unit_sections_have_the_tab(self):
        page = self.open_units()
        self.assertIn(TAB_UNIT, page._tab_keys)
        self.assertIsNotNone(page.unit)
        self.assertIsNone(self.section("nations:governments").unit)

    def test_stats_are_compared_with_another_unit(self):
        page = self.open_units()
        panel = page.unit
        self.assertEqual(panel.compare_combo.currentData(), "infantry", "por defecto, otra del mismo unit_type")
        rows = {key: (mine, base) for key, mine, base in panel.rows()}
        self.assertEqual(rows["attack"], (5.0, 2.0))
        self.assertEqual(rows["defence"], (2.0, 3.0))
        self.assertEqual(rows["siege"], (1.0, None), "un campo que la otra no tiene")
        self.assertNotIn("build_time", rows, "lo que ninguna de las dos tiene no sale")
        cells = {panel.stats.item(r, 0).text().rpartition("(")[2].rstrip(")") if "(" in panel.stats.item(r, 0).text()
                 else panel.stats.item(r, 0).text(): panel.stats.item(r, 3).text() for r in range(panel.stats.rowCount())}
        self.assertEqual(cells["attack"], "+3")
        self.assertEqual(cells["defence"], "−1")
        self.assertEqual(cells["max_strength"], "", "iguales: sin diferencia")
        self.assertFalse(self.window.session.dirty_count(), "comparar solo lee")

    def test_unlock_list_activate_and_remove(self):
        page = self.open_units()
        panel = page.unit
        self.assertEqual(panel.unlock_list.count(), 0)
        self.assertEqual(panel.unlock_note.text(), tr("entity.unit.unlock_never"))
        self.assertFalse(panel.deactivate_button.isEnabled())
        names = [panel.target_combo.itemData(i) for i in range(panel.target_combo.count())]
        self.assertIn("musket_drill", names)
        before = self.text_of("technologies/army_tech.txt")
        self.assertTrue(panel.activate("technology", "musket_drill"))
        session = self.settle()
        self.assertIn("activate_unit = guard", self.text_of("technologies/army_tech.txt"))
        self.assertTrue(_qt.wait_until(lambda: page.unit.unlock_list.count() == 1, 20000),
                        "la lista sigue al índice cuando se reindexa")
        self.assertIn("technologies/army_tech.txt", page.unit.unlock_list.item(0).text())
        self.assertEqual(len(session.history()), 1)
        page.unit.unlock_list.setCurrentRow(0)
        self.assertTrue(page.unit.deactivate_button.isEnabled())
        page.unit.deactivate_button.click()
        self.settle()
        self.assertEqual(self.text_of("technologies/army_tech.txt"), before, "quitar deja el archivo como estaba")
        self.assertTrue(_qt.wait_until(lambda: page.unit.unlock_list.count() == 0, 20000))

    def test_activate_in_an_invention_goes_into_its_effect(self):
        page = self.open_units()
        page.unit.kind_combo.setCurrentIndex(page.unit.kind_combo.findData("invention"))
        page.unit._fill_targets()
        self.assertEqual([page.unit.target_combo.itemData(i) for i in range(page.unit.target_combo.count())],
                         ["field_kitchens"])
        page.unit.activate_button.click()
        self.settle()
        text = self.text_of("inventions/army_inventions.txt")
        self.assertIn("activate_unit = guard", text)
        self.assertLess(text.index("effect"), text.index("activate_unit = guard"))

    def test_model_picker_lists_actors_and_changes_only_the_sprite(self):
        page = self.open_units()
        panel = page.unit
        models = [panel.model_combo.itemData(i) for i in range(panel.model_combo.count())]
        self.assertEqual(models, ["Frigate", "Guard", "Infantry"])
        self.assertEqual(panel.model_combo.currentData(), "Guard")
        self.assertIn("2", panel.model_combo.itemText(models.index("Infantry")), "dos culturas gráficas lo tienen")
        before = self.text_of("units/guard.txt")
        panel.model_combo.setCurrentIndex(models.index("Infantry"))
        panel.model_combo.activated.emit(models.index("Infantry"))
        self.settle()
        self.assertEqual(self.text_of("units/guard.txt"), before.replace("sprite = Guard", "sprite = Infantry"))
        self.assertEqual(len(self.window.session.history()), 1)

    def test_an_unknown_sprite_is_said_and_no_actors_too(self):
        page = self.open_units(**{"units/guard.txt": UNITS["units/guard.txt"].replace("sprite = Guard",
                                                                                   "sprite = Dragon")})
        self.assertEqual(page.unit.model_combo.currentIndex(), -1)
        self.assertEqual(page.unit.model_note.text(), tr("entity.unit.model_unknown", sprite="Dragon"))

    def test_retranslates(self):
        page = self.open_units()
        set_language("en")
        self.addCleanup(set_language, "es")
        _qt.process_events(20)
        self.assertEqual(page.tabs.tabText(page._tab_keys.index(TAB_UNIT)), "Unit")
        self.assertEqual(page.unit.activate_button.text(), "Activate here")
        self.assertEqual(page.navigator.rename_button.text(), "Rename")


if __name__ == "__main__":
    unittest.main()
