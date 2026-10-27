"""Sala Textos (wizard §8, criterio 6): la tabla editable de la localización efectiva, contra el ``Project`` real.

Editar una celda (con el delegado de la tabla, como el usuario) escribe según la política de ``LocSync`` y se
deshace con Ctrl+Z; los filtros, el buscador, «Pendientes de traducir», «Añadir clave», el guardado (solo el
archivo de sobrescrituras), el proyecto de solo lectura y el cambio de idioma. El índice y la validación son los
falsos de ``_fake_index`` (la tabla no los necesita).
"""

import hashlib
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
from _fake_index import fake_engines  # noqa: E402
from _layers import isolate_appdirs  # noqa: E402
from _minigame import CRLF, build_minigame  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QDialog, QLineEdit  # noqa: E402
from test_ui_shell import DialogLog  # noqa: E402
from test_ui_smoke import UiTestCase  # noqa: E402

APP = _qt.application()

from vic2studio.core.project import Project, WriteAction  # noqa: E402
from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.dialogs.add_key import AddKeyDialog  # noqa: E402
from vic2studio.ui.halls.localisation.texts import (  # noqa: E402
    COLUMNS,
    FILTER_DEGRADED,
    FILTER_OVERRIDES,
    FILTER_STUDIO,
    FILTER_UNTRANSLATED,
    FILTERS,
)
from vic2studio.ui.main_window import UNSAVED_DISCARD  # noqa: E402
from vic2studio.ui.session import Session  # noqa: E402

OVERRIDES = "localisation/00_TESTMOD_overrides.csv"
MOD_TEXTS = {
    "localisation/00_TESTMOD_countries.csv": "AAA;Aland;;;;Alandia;;;;;;;;x\r\nBBB;Borland;;;;;;;;;;;;x\r\n",
}


class TextsWindowCase(UiTestCase):
    def setUp(self):
        super().setUp()
        isolate_appdirs(self)
        self.dialogs = DialogLog()

    def open_window(self, *, read_only: bool = False, **minigame):
        self.game = build_minigame(**minigame)
        self.addCleanup(self.game.cleanup)
        if read_only:
            holder = Project.open(self.game.game_root, self.game.mod_root)   # otra ventana con el mismo mod
            self.addCleanup(holder.close)
        self.engines = fake_engines()
        window = self.make_window(session=Session(**self.engines))
        window.exec_dialog = self.dialogs
        window.ask_unsaved = mock.Mock(return_value=UNSAVED_DISCARD)
        page = window.page("project")
        page.set_game_path(self.game.game_root)
        page.set_mod_path(self.game.mod_root)
        session = window.session
        self.assertTrue(_qt.wait_until(lambda: session.project is not None and session.texts_ready()
                                       and not window.is_busy(), 8000), "el proyecto no llegó a abrirse")
        self.window = window
        return window

    def texts(self, section: str = "all"):
        page = self.window.show_page(f"localisation:{section}")
        _qt.process_events(20)
        return page

    def cell(self, page, key: str, lang: str) -> str:
        self.assertTrue(page.select_key(key, lang), key)
        return page.table.currentIndex().data()

    def edit_cell(self, page, key: str, lang: str, text: str) -> None:
        """Como el usuario: seleccionar la celda, F2, escribir e Intro (el delegado de la tabla confirma)."""
        self.assertTrue(page.select_key(key, lang), key)
        page.table.setFocus()
        QTest.keyClick(page.table, Qt.Key.Key_F2)
        editor = page.table.viewport().findChild(QLineEdit)
        self.assertIsNotNone(editor, "la celda no se abrió para editar")
        editor.selectAll()
        editor.setText(text)
        QTest.keyClick(editor, Qt.Key.Key_Return)
        _qt.process_events(30)
        self.assertTrue(_qt.wait_until(lambda: not self.window.is_busy(), 3000))

    def writes(self) -> dict:
        return {str(w.rel): w for w in self.window.session.changeset().writes}


class TextsTableTests(TextsWindowCase):
    def test_the_table_shows_the_effective_texts_with_their_file_and_origin(self):
        self.open_window(mod_files=MOD_TEXTS)
        page = self.texts()
        self.assertEqual(page.visible_keys(), ["AAA", "BBB", "tst_reform", "conquer_land", "free_people",
                                               "humble_rival"])
        headers = [page.proxy.headerData(i, Qt.Orientation.Horizontal) for i in range(len(COLUMNS))]
        self.assertEqual(headers, ["Clave", "English", "Español", "Français", "Deutsch", "Archivo", "Origen"])
        self.assertTrue(page.table.isColumnHidden(COLUMNS.index("fr")), "francés y alemán, a petición")
        page.extra_check.setChecked(True)
        self.assertFalse(page.table.isColumnHidden(COLUMNS.index("de")))
        self.assertEqual(self.cell(page, "conquer_land", "es"), "Conquistar")
        row = page.table.currentIndex().row()
        self.assertEqual(page.proxy.index(row, COLUMNS.index("file")).data(), "minigame.csv:1")
        self.assertEqual(page.proxy.index(row, COLUMNS.index("origin")).data(), tr("texts.origin.game"))
        self.assertEqual(page.filter_combo.itemText(0), tr("texts.filter.all", count="6"))
        self.assertEqual(page.count_label.text(), tr("texts.count", total="6"))

    def test_editing_a_game_text_writes_the_overrides_file_and_ctrl_z_undoes_it(self):
        """Criterio 6 desde la interfaz: la fila va a 00_<P>_overrides.csv; el CSV del juego no se copia."""
        window = self.open_window(mod=False)
        page = self.texts()
        self.edit_cell(page, "free_people", "es", "Liberar al pueblo")
        self.assertEqual(self.cell(page, "free_people", "es"), "Liberar al pueblo")
        writes = self.writes()
        self.assertEqual(list(writes), [OVERRIDES])
        self.assertIs(writes[OVERRIDES].action, WriteAction.CREATE)
        self.assertIn(tr("texts.status_written", name="free_people", file=OVERRIDES), window.status_label.text())
        self.assertEqual(window.session.history(), [("undo.texts_edit", {"key": "free_people", "lang": "Español"})])
        self.assertIn(tr("undo.texts_edit", key="free_people", lang="Español"), window.undo_button.toolTip())
        row = page.table.currentIndex().row()
        self.assertEqual(page.proxy.index(row, COLUMNS.index("origin")).data(), tr("texts.origin.override"))
        window.activateWindow()
        QTest.qWaitForWindowActive(window, 2000)
        QTest.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        _qt.process_events(30)
        self.assertEqual(window.session.dirty_count(), 0)
        self.assertEqual(self.cell(page, "free_people", "es"), "Liberar", "la tabla vuelve al texto del juego")

    def test_editing_a_mod_text_edits_it_in_place(self):
        self.open_window()
        page = self.texts()
        self.edit_cell(page, "tst_reform", "es", "Reformar")
        writes = self.writes()
        self.assertEqual(list(writes), ["localisation/00_TST_decisions.csv"])
        self.assertIs(writes["localisation/00_TST_decisions.csv"].action, WriteAction.MODIFY)

    def test_an_invalid_text_is_refused_with_its_reason(self):
        window = self.open_window()
        page = self.texts()
        self.edit_cell(page, "tst_reform", "es", "uno;dos")
        self.assertEqual(window.session.dirty_count(), 0)
        self.assertEqual(self.cell(page, "tst_reform", "es"), "Reforma")
        self.assertIn(tr("texts.status_invalid", error="")[:20], window.status_label.text())
        self.edit_cell(page, "tst_reform", "es", "Łódź")
        self.assertEqual(window.session.dirty_count(), 0, "un carácter fuera de cp1252 tampoco entra")
        self.assertEqual(window.status_label.text(), tr("texts.status_unencodable", char="Ł", code="U+0141"))

    def test_saving_writes_only_the_overrides_file_and_never_the_game(self):
        window = self.open_window(mod=False)
        game_before = {rel: hashlib.sha256(data).hexdigest() for rel, (_, _, data) in self.game.game_tree().items()}
        page = self.texts()
        self.edit_cell(page, "humble_rival", "en", "Humble them")
        self.assertTrue(window.save_project())
        self.assertEqual(sorted(self.game.tree()), [OVERRIDES])
        self.assertEqual({rel: hashlib.sha256(data).hexdigest()
                          for rel, (_, _, data) in self.game.game_tree().items()}, game_before)
        self.assertEqual(self.cell(page, "humble_rival", "en"), "Humble them")


class FilterTests(TextsWindowCase):
    def test_filters_and_search(self):
        degraded_game = "PRESTIGE;Prestige;;;;Prestigio;;;;;;;;x\r\nEASY;Facilité;;;;;;;;;;;;x\r\n"
        degraded_mod = "PRESTIGE;Prestige;;;;Prestigio;;;;;;;;x\r\nEASY;Facilit?;;;;;;;;;;;;x\r\n"
        self.open_window(mod=False, game_files={"localisation/text.csv": degraded_game},
                         mod_files={**MOD_TEXTS, "localisation/text.csv": degraded_mod})
        page = self.texts()
        expected = {FILTER_STUDIO: ["AAA", "BBB"], FILTER_UNTRANSLATED: ["BBB", "EASY"],
                    FILTER_OVERRIDES: ["PRESTIGE", "EASY"], FILTER_DEGRADED: ["EASY"]}
        for kind, keys in expected.items():
            with self.subTest(filter=kind):
                page.filter_combo.setCurrentIndex([data for data, _ in FILTERS].index(kind))
                self.assertEqual(page.visible_keys(), keys)
                key = dict(FILTERS)[kind]
                self.assertEqual(page.filter_combo.currentText(), tr(key, count=str(len(keys))))
        page.filter_combo.setCurrentIndex(0)
        page.search_edit.setText("ALANDIÁ")   # sin mayúsculas ni acentos
        _qt.wait_until(lambda: not page.is_busy(), 2000)
        self.assertEqual(page.visible_keys(), ["AAA"])
        self.assertEqual(page.count_label.text(), tr("texts.count", total="7") + " " + tr("texts.shown", shown="1"))
        self.assertTrue(page.select_key("conquer_land"), "seleccionar una clave oculta vacía la búsqueda")
        self.assertEqual(page.search_edit.text(), "")

    def test_pending_section_is_the_untranslated_filter_and_counts_in_the_rail(self):
        window = self.open_window(mod_files=MOD_TEXTS)
        page = self.texts("pending")
        self.assertEqual(page.proxy.filter(), FILTER_UNTRANSLATED)
        self.assertEqual(page.visible_keys(), ["BBB"])
        hall = window.hall("localisation")
        self.assertEqual(hall.rail.buttons[hall.section_index("pending")].badge, 1)
        self.edit_cell(page, "BBB", "es", "Borlandia")
        self.assertTrue(_qt.wait_until(lambda: page.visible_keys() == [], 2000), "ya está traducida")
        self.assertIsNone(hall.rail.buttons[hall.section_index("pending")].badge)


class AddKeyTests(TextsWindowCase):
    def test_add_key_creates_it_in_the_area_file_and_selects_it(self):
        window = self.open_window()
        page = self.texts()
        seen = []

        def fill(dialog: AddKeyDialog):
            dialog.key_edit.setText("tst_reform")
            seen.append((dialog.ok_button.isEnabled(), dialog.problem_text()))
            dialog.key_edit.setText("NEW_KEY")
            dialog.area_combo.setCurrentIndex(dialog.area_combo.findData("events"))
            dialog.text_edits["en"].setText("New")
            dialog.text_edits["es"].setText("Nuevo")
            seen.append((dialog.ok_button.isEnabled(), dialog.target.text()))
            dialog.ok_button.click()

        self.dialogs.handlers[AddKeyDialog] = fill
        page.add_button.click()
        self.assertEqual(self.dialogs.types(), [AddKeyDialog])
        self.assertFalse(seen[0][0], "una clave que ya existe no se puede añadir")
        self.assertIn("00_TST_decisions.csv", seen[0][1])
        self.assertTrue(seen[1][0])
        self.assertEqual(seen[1][1], tr("texts.add.target", file="localisation/00_TESTMOD_events.csv"))
        self.assertEqual(self.cell(page, "NEW_KEY", "es"), "Nuevo")
        self.assertEqual(list(self.writes()), ["localisation/00_TESTMOD_events.csv"])
        self.assertEqual(window.session.history()[0], ("undo.texts_add_key", {"key": "NEW_KEY"}))
        window.undo()
        _qt.process_events(30)
        self.assertNotIn("NEW_KEY", page.visible_keys())

    def test_cancelling_add_key_changes_nothing(self):
        window = self.open_window()
        page = self.texts()
        self.dialogs.handlers[AddKeyDialog] = lambda dialog: dialog.reject()
        page.add_button.click()
        self.assertEqual(window.session.dirty_count(), 0)

    def test_the_dialog_checks_keys_and_texts(self):
        self.open_window()
        dialog = AddKeyDialog(self.window.session.locsync, self.window)   # la ventana lo destruye con ella
        self.assertEqual(dialog.problem_text(), tr("texts.add.need_key"))
        dialog.key_edit.setText(" spaced")
        self.assertFalse(dialog.ok_button.isEnabled())
        dialog.key_edit.setText("GOOD")
        self.assertEqual(dialog.problem_text(), tr("texts.add.need_text"))
        dialog.text_edits["es"].setText("a;b")
        self.assertFalse(dialog.ok_button.isEnabled())
        dialog.text_edits["es"].setText("Bien")
        self.assertTrue(dialog.ok_button.isEnabled())
        self.assertEqual(dialog.values(), ("GOOD", "misc", {"es": "Bien"}))


class ReadOnlyAndLanguageTests(TextsWindowCase):
    def test_a_read_only_project_shows_the_texts_but_cannot_edit_them(self):
        window = self.open_window(read_only=True)
        page = self.texts()
        self.assertTrue(window.session.is_read_only())
        index = page.proxy.index(0, COLUMNS.index("es"))
        self.assertFalse(page.proxy.flags(index) & Qt.ItemFlag.ItemIsEditable)
        self.assertFalse(page.add_button.isEnabled())
        self.assertIn(tr("texts.read_only"), page.count_label.text())

    def test_the_page_follows_the_language(self):
        self.open_window()
        page = self.texts()
        set_language("en")
        self.assertEqual(page.proxy.headerData(0, Qt.Orientation.Horizontal), "Key")
        self.assertEqual(page.add_button.text(), "Add key")
        self.assertTrue(page.filter_combo.itemText(2).startswith("Untranslated"))
        set_language("es")
        self.assertEqual(page.add_button.text(), "Añadir clave")

    def test_without_a_project_the_page_says_so(self):
        window = self.make_window(session=Session(**fake_engines()))
        page = window.show_page("localisation:all")
        self.assertIs(page.stack.currentWidget(), page.empty)
        self.assertEqual(page.empty.title.text(), tr("texts.empty_no_project_title"))
        self.assertFalse(page.add_button.isEnabled())


class CrossCheckTests(TextsWindowCase):
    def test_the_dialog_outcome_is_honoured(self):
        """``exec_dialog`` devuelve el resultado del diálogo: rechazar no crea nada (prueba del arnés)."""
        self.open_window()
        self.assertEqual(self.dialogs(QDialog()), QDialog.DialogCode.Rejected)

    def test_a_crlf_new_file(self):
        self.open_window(mod=False)
        page = self.texts()
        self.edit_cell(page, "conquer_land", "en", "Take")
        self.assertTrue(self.writes()[OVERRIDES].data.endswith(CRLF.encode()))


if __name__ == "__main__":
    unittest.main()
