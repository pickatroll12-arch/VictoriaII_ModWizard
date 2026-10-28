"""Iteración 4 de punta a punta: la ventana, la ``Session`` y el ``Project`` reales sobre el minijuego (wizard §22).

Los criterios 2, 3, 4 y 5 se recorren desde la interfaz, como el usuario: el diálogo «Nuevo», el formulario,
Ctrl+Z, Ctrl+S y F7. También la decisión 4 (crear, guardar y volver a listar) y que guardar sin cambios no
escribe nada. Con ``VIC2_CORPUS``, el criterio 2 sobre una copia de vanilla (nunca el juego real).
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402
from _corpus import vanilla_root  # noqa: E402
from test_ui_entity import WAIT_MS, EntityWindowCase  # noqa: E402

APP = _qt.application()

from vic2studio.core.project import WriteAction  # noqa: E402
from vic2studio.core.project.diffing import changed_lines  # noqa: E402
from vic2studio.core.schema import RecordRef  # noqa: E402
from vic2studio.core.vfs import VPath  # noqa: E402
from vic2studio.ui.entity import NewEntityDialog, UsesDialog  # noqa: E402

FUTURE_WAR = ('name = "Future War"\r\n1835.1.1 = {\r\n\tadd_attacker = AAA\r\n\tadd_defender = BBB\r\n'
              '\twar_goal = {\r\n\t\tcasus_belli = my_cb\r\n\t\tactor = AAA\r\n\t\treceiver = BBB\r\n\t}\r\n}\r\n')


class EndToEndCase(EntityWindowCase):
    def new_from_dialog(self, page, ident: str, *, base: str | None = None) -> None:
        def answer(dialog: NewEntityDialog):
            dialog.ident_edit.setText(ident)
            if base is not None:
                dialog.base_radio.setChecked(True)
                dialog.base_combo.setCurrentIndex(dialog.base_combo.findText(base))
            dialog.accept()

        self.dialogs.handlers[NewEntityDialog] = answer
        page.navigator.new_button.click()
        self.settle()

    def save(self) -> None:
        from vic2studio.ui.dialogs import SaveReviewDialog

        self.dialogs.handlers[SaveReviewDialog] = lambda dialog: dialog.accept()   # copias del juego: revisar
        self.assertTrue(self.window.save_project())
        self.settle()

    def mod_text(self, rel: str) -> str:
        return (self.game.mod_root / rel).read_bytes().decode("cp1252")

    def keys_in(self, rel: str) -> list[str]:
        return [line.split(";")[0] for line in self.mod_text(rel).splitlines() if line]


class CriteriaFromTheWindowTests(EndToEndCase):
    def test_criterion3_my_cb(self):
        window = self.open_window(game_files={"history/wars/Future War.txt": FUTURE_WAR})
        session = window.session
        page = self.section("war:cb")
        self.new_from_dialog(page, "my_cb")
        self.assertEqual(page.current_ref().ident, "my_cb")
        self.assertEqual(len(session.history()), 1)
        order = self.text_of("common/cb_types.txt").split("}", 1)[0]
        self.assertTrue(order.rstrip().endswith("annex\r\n\tmy_cb"), "my_cb al final de peace_order")
        texts = page.texts.table
        self.assertEqual([texts.item(r, 0).text() for r in range(texts.rowCount())],
                         ["my_cb", "my_cb_desc", "my_cb_setup", "my_cb_short"])
        # Borrar mientras se usa: se bloquea, enseña el uso y no cambia nada.
        shown = []
        self.dialogs.handlers[UsesDialog] = lambda dialog: (shown.append([dialog.list.item(i).text() for i in
                                                                          range(dialog.list.count())]),
                                                            dialog.reject())
        page.navigator.delete_button.click()
        self.assertEqual(len(shown), 1)
        self.assertEqual(len(shown[0]), 1)
        self.assertIn("Future War.txt", shown[0][0])
        self.assertEqual(len(session.history()), 1)
        # Un solo Ctrl+Z quita la creación entera.
        window.undo()
        self.settle()
        self.assertEqual(session.dirty_count(), 0)
        self.assertNotIn("my_cb", page.navigator.idents())
        self.assertIsNone(session.locsync.entry("my_cb"))
        window.redo()
        self.settle()
        self.save()
        prefix = session.project.settings.prefix
        self.assertEqual(self.keys_in(f"localisation/00_{prefix}_cb.csv"),
                         ["my_cb", "my_cb_desc", "my_cb_setup", "my_cb_short"])
        self.assertIn("\tmy_cb\r\n}", self.mod_text("common/cb_types.txt"))
        self.assertIn("my_cb", page.navigator.idents(), "guardado, sigue en la lista (decisión 4)")

    def test_criterion4_junta(self):
        window = self.open_window()
        session = window.session
        page = self.section("nations:governments")
        self.new_from_dialog(page, "junta")
        self.assertEqual(page.rebels.table.rowCount(), 2)
        self.assertEqual(page.rebels.missing(), [])
        writes = {str(w.rel): w.action for w in session.changeset().writes}
        self.assertEqual(writes.get("common/governments.txt"), WriteAction.COPY_FROM_GAME)
        self.assertEqual(writes.get("common/rebel_types.txt"), WriteAction.COPY_FROM_GAME)
        self.assertEqual([page.texts.table.item(r, 0).text() for r in range(page.texts.table.rowCount())],
                         ["junta", "junta_ruler"])
        # election = yes sin duration: el aviso, en el formulario y en F7.
        page.show_tab("form")
        page.form.editor("election").check.setCheckState(page.form.editor("election").check.checkState().Checked)
        self.settle()
        messages = [page.problems_list.item(i).text() for i in range(page.problems_list.count())]
        self.assertTrue(any("duration" in message for message in messages), messages)
        self.assertTrue(window.validate_mod())
        self.assertTrue(_qt.wait_until(lambda: session.validation_state() == "ready" and not window.is_busy(),
                                       WAIT_MS))
        found = [p for p in session.problems() if p.code == "government_election_without_duration"
                 and p.entity and p.entity[1] == "junta"]
        self.assertEqual(len(found), 1, "una vez, aunque lo den el esquema y la validación global")
        self.assertTrue(window.open_problem(found[0]))
        self.assertEqual(window.current_page_key(), "nations:governments")
        self.save()
        rebels = self.mod_text("common/rebel_types.txt")
        self.assertEqual(rebels.count("junta = junta"), 2, "junta en las 2 tablas del minijuego")
        self.assertTrue(self.mod_text("common/governments.txt").rstrip().endswith("}"))

    def test_criterion5_unit_based_on_infantry(self):
        window = self.open_window()
        session = window.session
        page = self.section("war:land")
        self.new_from_dialog(page, "guard", base="infantry")
        self.assertEqual(page.navigator.idents(), ["guard", "infantry"])
        self.assertNotIn("guard", self.section("war:naval").navigator.idents(), "dos secciones, un esquema")
        handle = session.project.ws.peek(VPath("units/guard.txt"))
        self.assertTrue(handle is not None and handle.is_new)
        self.save()
        self.assertTrue((self.game.mod_root / "units" / "guard.txt").is_file())
        prefix = session.project.settings.prefix
        self.assertEqual(self.keys_in(f"localisation/00_{prefix}_units.csv"), ["guard", "guard_short"])
        self.assertEqual(window.current_page().navigator.idents(), ["frigate"])

    def test_criterion2_attack_from_the_form_changes_one_line(self):
        window = self.open_window()
        page = self.section("war:land")
        editor = page.form.editor("attack")
        editor.edit.setText("5")
        editor.edit.editingFinished.emit()
        self.settle()
        self.save()
        game = self.game.game("units/infantry.txt").read_bytes()
        mod = (self.game.mod_root / "units" / "infantry.txt").read_bytes()
        self.assertEqual(changed_lines(game, mod), (1, 0), "una línea añadida (attack no estaba)")
        window.close()

    def test_open_and_save_without_changes_writes_nothing(self):
        window = self.open_window()
        before = self.game.tree(self.game.mod_root)
        for key in ("war:cb", "war:land", "war:naval", "war:bookmarks", "nations:cultures", "nations:governments",
                    "events:modifiers"):
            page = self.section(key)
            for tab in range(page.tabs.count()):
                page.tabs.setCurrentIndex(tab)
                _qt.process_events(5)
        self.assertEqual(window.session.dirty_count(), 0, "mirar no ensucia nada (I4)")
        self.assertTrue(window.save_project())
        self.assertEqual(self.game.tree(self.game.mod_root), before)
        self.assertFalse((self.game.mod_root / ".vic2studio").exists())

    def test_ctrl_z_after_typing_in_a_form_undoes_the_field(self):
        window = self.open_window()
        session = window.session
        page = self.section("war:cb")
        page.navigator.select(RecordRef("casus_belli", "free_people"))
        editor = page.form.editor("months")
        editor.edit.setText("30")
        # Sin confirmar todavía: Ctrl+Z confirma lo tecleado y lo deshace (commit_edits).
        window.undo()
        self.settle()
        self.assertEqual(session.dirty_count(), 0)
        self.assertEqual(page.form.editor("months").value(), 6)


@unittest.skipUnless(vanilla_root(), "sin corpus")
class VanillaWindowTests(EntityWindowCase):
    """Con corpus: la ventana sobre una copia temporal de las carpetas de vanilla que usan los esquemas."""

    def test_criterion2_on_a_copy_of_vanilla(self):
        from unittest import mock

        root = Path(tempfile.mkdtemp(prefix="vic2studio-it4-vanilla-"))
        self.addCleanup(shutil.rmtree, root, True)
        game = root / "Victoria 2"
        for folder in ("common", "units", "technologies", "inventions", "localisation", "map", "interface"):
            shutil.copytree(vanilla_root() / folder, game / folder)
        mod = game / "mod" / "IT4"
        mod.mkdir(parents=True)
        window = self.make_window()
        window.exec_dialog = self.dialogs
        window.ask_unsaved = mock.Mock(return_value="discard")
        files = window.page("project")
        files.set_game_path(game)
        files.set_mod_path(mod)
        session = window.session
        self.assertTrue(_qt.wait_until(lambda: session.project is not None and session.index_state() == "ready"
                                       and session.texts_ready() and not window.is_busy(), 120000))
        self.window = window
        land = self.section("war:land")
        self.assertEqual(len(land.navigator.idents()), 11)
        self.assertEqual(len(self.section("war:naval").navigator.idents()), 10)
        self.assertEqual(len(self.section("war:cb").navigator.idents()), 31)
        self.assertEqual(len(self.section("nations:cultures").navigator.idents()), 226)
        land = self.section("war:land")
        land.navigator.select(RecordRef("unit", "infantry"))
        editor = land.form.editor("attack")
        editor.edit.setText("5")
        editor.edit.editingFinished.emit()
        self.settle()
        from vic2studio.ui.dialogs import SaveReviewDialog

        self.dialogs.handlers[SaveReviewDialog] = lambda dialog: dialog.accept()
        self.assertTrue(window.save_project())
        before = (game / "units" / "infantry.txt").read_bytes()
        after = (mod / "units" / "infantry.txt").read_bytes()
        self.assertEqual(changed_lines(before, after), (1, 1), "cambia una sola línea: la de attack")


if __name__ == "__main__":
    unittest.main()
