"""Editor de texto de scripts (Proyecto › Archivos): criterios 1-10 contra un ``Project`` real.

Cada prueba abre el minijuego sintético con ``Project.open`` y usa una ``Session``
real: las transacciones, el deshacer y el guardado son los del proyecto, no un
doble. El editor se crea suelto; la integración con la ventana se prueba en
``test_ui_script_editor_window`` y en la fase de Archivos.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y preferencias aisladas)
from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from test_ui_smoke import UiTestCase  # noqa: E402

APP = _qt.application()

from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.vfs import VPath  # noqa: E402
from vic2studio.i18n import N_, load_catalog, set_language  # noqa: E402
from vic2studio.ui.main_window import UNSAVED_DISCARD  # noqa: E402
from vic2studio.ui.session import Session  # noqa: E402
from vic2studio.ui.tasks import wait_for_tasks  # noqa: E402
from vic2studio.ui.viewers.script_editor import ScriptEditor  # noqa: E402

CP1252_REL = VPath.of("common/editor_cp1252.txt")
MIXED_REL = VPath.of("common/editor_mixed.txt")
CP1252_BYTES = b"# Caf\xe9\r\nvalue = 1\r\nlabel = \"precio\xa0final\"\r\n"
MIXED_TEXT = "uno\r\ndos\ntres\r cuatro\r\ncinco"
EXTRA_MOD = {
    CP1252_REL: CP1252_BYTES,
    MIXED_REL: MIXED_TEXT,
}


class ScriptEditorCase(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)
        set_language("es")
        self.game = build_minigame(mod_files=EXTRA_MOD)
        self.addCleanup(self.game.cleanup)
        self.session = Session()
        self.session.open_project(self.game.game_root, self.game.mod_root)
        self.assertTrue(_qt.wait_until(lambda: self.session.project is not None and not self.session.is_busy(), 5000))
        self.addCleanup(self._close_session)
        self.editor = ScriptEditor(self.session)
        self.addCleanup(_qt.dispose, self.editor)

    def _close_session(self):
        self.session.close_project()
        wait_for_tasks(10000)
        _qt.process_events(20)

    @property
    def project(self):
        return self.session.project

    def open(self, rel=CP1252_REL):
        self.assertTrue(self.editor.open_document(rel), self.editor.status_label.text())
        return self.editor

    def snapshot(self, rel) -> bytes:
        handle = self.project.ws.peek(rel)
        self.assertIsNotNone(handle)
        return codec_for(handle.kind).snapshot(handle.model)

    def raw_view(self) -> str:
        return self.editor.editor.document().toRawText().replace("\u2029", "\n").replace("\u2028", "\n")

    def replace(self, old: str, new: str) -> None:
        text = self.raw_view()
        self.assertIn(old, text)
        self.editor.editor.setPlainText(text.replace(old, new, 1))
        self.assertTrue(self.editor.commit_pending(), self.editor.status_label.text())

    def type_at_end(self, text: str) -> None:
        cursor = self.editor.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.editor.editor.setTextCursor(cursor)
        QTest.keyClicks(self.editor.editor, text)


class OpenTests(ScriptEditorCase):
    def test_criterion1_opening_without_typing_writes_nothing(self):
        before = self.game.tree(self.game.mod_root)
        self.open()
        self.assertEqual(self.session.changeset().writes, ())
        self.assertEqual(self.session.dirty_count(), 0)
        self.assertEqual(self.game.tree(self.game.mod_root), before)
        self.assertFalse(self.project.ws.peek(CP1252_REL).dirty)

    def test_criterion8_commit_pending_applies_before_the_timer(self):
        self.open()
        self.type_at_end("abc")
        self.assertTrue(self.editor._timer.isActive())
        self.assertTrue(self.editor.commit_pending(), self.editor.status_label.text())
        self.assertFalse(self.editor._timer.isActive())
        self.assertTrue(self.project.ws.peek(CP1252_REL).dirty)
        self.assertTrue(self.snapshot(CP1252_REL).endswith(b"abc"))


class SaveTests(ScriptEditorCase):
    def test_criterion2_mod_file_changes_only_that_line_and_keeps_crlf_and_cp1252(self):
        original = self.game.mod(CP1252_REL).read_bytes()
        self.assertEqual(original, CP1252_BYTES)
        self.open()
        self.replace("value = 1", "value = 2")
        writes = self.session.changeset().writes
        self.assertEqual([str(write.rel) for write in writes], [str(CP1252_REL)])
        report = self.session.save()
        self.assertTrue(report.ok, report.problems)
        saved = self.game.mod(CP1252_REL).read_bytes()
        self.assertEqual(saved, original.replace(b"value = 1", b"value = 2"))
        self.assertIn(b"Caf\xe9", saved, "el texto sigue en cp1252")
        self.assertIn(b"\xa0", saved, "el espacio duro de una línea no tocada sigue ahí")
        self.assertNotIn(b"\n", saved.replace(b"\r\n", b""), "no aparecen LF sueltos")

    def test_criterion3_game_only_file_is_copied_to_the_mod_and_the_game_is_untouched(self):
        rel = VPath.of("common/countries.txt")
        game_before = self.game.game(rel).read_bytes()
        self.open(rel)
        self.replace('AAA = "countries/Aland.txt"', 'AAA = "countries/Aland2.txt"')
        self.assertFalse(self.game.mod(rel).exists())
        report = self.session.save()
        self.assertTrue(report.ok, report.problems)
        copied = self.game.mod(rel).read_bytes()
        self.assertIn(b'Aland2.txt', copied)
        self.assertEqual(self.game.game(rel).read_bytes(), game_before, "el juego no se toca")

    def test_criterion6_an_unclosed_brace_is_reported_and_saving_still_works(self):
        self.open()
        cursor = self.editor.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText("{")
        self.assertTrue(self.editor.commit_pending(), self.editor.status_label.text())
        self.assertIn("1 error", self.editor.syntax_label.text())
        self.assertIn("línea", self.editor.syntax_label.text())
        report = self.session.save()
        self.assertTrue(report.ok, report.problems)
        self.assertTrue(self.game.mod(CP1252_REL).read_bytes().endswith(b"{"))


class UndoTests(ScriptEditorCase):
    def test_criterion4_typing_is_one_undo_step_and_redo_puts_it_back(self):
        self.open()
        before = self.snapshot(CP1252_REL)
        self.type_at_end("abc")
        self.assertTrue(_qt.wait_until(lambda: self.session.dirty_count() == 1, 2000))
        self.assertEqual(self.snapshot(CP1252_REL), before + b"abc")
        steps = self.session.history()
        self.assertEqual(len(steps), 1, "las letras seguidas se funden en un paso")
        self.session.undo()
        _qt.process_events(20)
        self.assertFalse(self.project.ws.peek(CP1252_REL).dirty)
        self.assertEqual(self.snapshot(CP1252_REL), before)
        self.assertEqual(self.raw_view(), before.decode("cp1252").replace("\r\n", "\n"))
        self.session.redo()
        _qt.process_events(20)
        self.assertTrue(self.snapshot(CP1252_REL).endswith(b"abc"))
        self.assertTrue(self.raw_view().endswith("abc"))

    def test_two_quick_commits_merge_into_one_undo_step(self):
        self.open()
        before = self.snapshot(CP1252_REL)
        self.type_at_end("abc")
        self.assertTrue(self.editor.commit_pending())
        self.type_at_end("def")
        self.assertTrue(self.editor.commit_pending())
        self.assertEqual(len(self.session.history()), 1, "el merge_key funde dos confirmaciones seguidas")
        self.session.undo()
        _qt.process_events(20)
        self.assertEqual(self.snapshot(CP1252_REL), before)


class UnencodableTests(ScriptEditorCase):
    def test_criterion5_a_character_outside_cp1252_never_reaches_the_document(self):
        self.open()
        before = self.snapshot(CP1252_REL)
        cursor = self.editor.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText("ő")
        self.assertFalse(self.editor.commit_pending())
        self.assertEqual(self.snapshot(CP1252_REL), before)
        self.assertEqual(self.session.changeset().writes, ())
        status = self.editor.status_label.text()
        self.assertIn("línea", status)
        self.assertIn("columna", status)
        self.assertIn("Windows-1252", status)
        self.assertIn("ő", self.raw_view(), "el texto tecleado no se pierde")


class ExternalChangeTests(ScriptEditorCase):
    def test_criterion9_an_external_transaction_reloads_the_editor(self):
        self.open()
        self.assertEqual(self.raw_view(), CP1252_BYTES.decode("cp1252").replace("\r\n", "\n"))
        cursor = self.editor.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(QTextCursor.MoveOperation.Down)
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, 3)
        self.editor.editor.setTextCursor(cursor)
        with self.session.edit(N_("editor.undo_edit"), file=CP1252_REL.name):
            handle = self.project.ws.open(CP1252_REL)
            self.project.ws.replace_text(handle, CP1252_BYTES.replace(b"value = 1", b"value = 9"))
        _qt.process_events(20)
        self.assertIn("value = 9", self.raw_view())
        self.assertEqual(self.editor.editor.textCursor().blockNumber(), 1, "conserva la línea")
        self.assertEqual(self.editor.editor.textCursor().positionInBlock(), 3, "conserva la columna")


class NewlineTests(ScriptEditorCase):
    def test_criterion10_mixed_newlines_keep_the_untouched_lines(self):
        self.open(MIXED_REL)
        self.replace("dos", "DOS")
        self.assertEqual(self.snapshot(MIXED_REL), b"uno\r\nDOS\r\ntres\r cuatro\r\ncinco")
        self.assertIn(b"tres\r ", self.snapshot(MIXED_REL), "el CR suelto de una línea no tocada sigue ahí")


class WindowTests(UiTestCase):
    """Criterio 11 y la integración con Proyecto › Archivos y la ventana real."""

    def setUp(self):
        super().setUp()
        isolate_appdirs(self)
        self.game = build_minigame(mod_files=EXTRA_MOD)
        self.addCleanup(self.game.cleanup)
        self.window = self.make_window(session=Session())
        self.window.ask_unsaved = mock.Mock(return_value=UNSAVED_DISCARD)
        page = self.window.page("project")
        page.set_game_path(self.game.game_root)
        page.set_mod_path(self.game.mod_root)
        self.assertTrue(_qt.wait_until(lambda: self.window.session.project is not None and not self.window.is_busy(),
                                       5000))
        self.window.show_page("project:files")
        _qt.process_events(20)
        self.page = page
        self.editor = page.script_editor
        self.path = self.game.mod(CP1252_REL)

    @property
    def project(self):
        return self.window.session.project

    def raw_view(self) -> str:
        return self.editor.editor.document().toRawText().replace("\u2029", "\n").replace("\u2028", "\n")

    def open_with_the_button(self):
        self.assertTrue(self.page.open_file(self.path))
        _qt.process_events(20)
        self.assertTrue(self.page.edit_button.isVisibleTo(self.page))
        QTest.mouseClick(self.page.edit_button, Qt.MouseButton.LeftButton)
        _qt.process_events(20)
        self.assertIs(self.page.preview_stack.currentWidget(), self.editor)
        self.assertEqual(self.editor.current_rel(), CP1252_REL)

    def test_criterion11_ctrl_z_with_the_editor_focused_uses_the_application_undo(self):
        self.open_with_the_button()
        self.window.activateWindow()
        self.assertTrue(QTest.qWaitForWindowActive(self.window, 2000))
        self.editor.editor.setFocus()
        _qt.process_events(10)
        before = self.raw_view()
        QTest.keyClicks(self.editor.editor, "abc")
        # Sin esperar al temporizador: la ventana confirma lo tecleado y deshace ese mismo paso.
        QTest.keyClick(self.editor.editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        _qt.process_events(50)
        self.assertFalse(self.project.ws.peek(CP1252_REL).dirty)
        self.assertEqual(self.raw_view(), before)

    def test_saving_commits_pending_editor_text(self):
        self.open_with_the_button()
        QTest.keyClicks(self.editor.editor, "abc")
        self.assertTrue(self.window.save_project())
        self.assertIn(b"abc", self.path.read_bytes())

    def test_a_file_with_unsaved_changes_opens_directly_in_the_editor_from_the_explorer(self):
        with self.window.session.edit(N_("editor.undo_edit"), file=CP1252_REL.name):
            handle = self.project.ws.open(CP1252_REL)
            self.project.ws.replace_text(handle, CP1252_BYTES.replace(b"value = 1", b"value = 7"))
        self.assertTrue(self.page.open_file(self.path))
        _qt.process_events(20)
        self.assertIs(self.page.preview_stack.currentWidget(), self.editor)
        self.assertIn("value = 7", self.raw_view())

    def test_back_to_viewer_commits_pending_text(self):
        self.open_with_the_button()
        QTest.keyClicks(self.editor.editor, "abc")
        QTest.mouseClick(self.editor.back_button, Qt.MouseButton.LeftButton)
        _qt.process_events(30)
        self.assertIs(self.page.preview_stack.currentWidget(), self.page.clausewitz_viewer)
        self.assertTrue(self.project.ws.peek(CP1252_REL).dirty)
        self.assertIn(b"abc", codec_for(self.project.ws.peek(CP1252_REL).kind)
                      .snapshot(self.project.ws.peek(CP1252_REL).model))


class ReadOnlyProjectTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)
        set_language("es")
        self.game = build_minigame(mod_files=EXTRA_MOD)
        self.addCleanup(self.game.cleanup)
        self.holder = Project.open(self.game.game_root, self.game.mod_root)
        self.addCleanup(self.holder.close)
        self.session = Session()
        self.session.open_project(self.game.game_root, self.game.mod_root)
        self.assertTrue(_qt.wait_until(lambda: self.session.project is not None and not self.session.is_busy(), 5000))
        self.addCleanup(self._close_session)
        self.editor = ScriptEditor(self.session)
        self.addCleanup(_qt.dispose, self.editor)

    def _close_session(self):
        self.session.close_project()
        wait_for_tasks(10000)
        _qt.process_events(20)

    def test_criterion7_a_read_only_project_cannot_be_edited_and_says_why(self):
        self.assertTrue(self.session.is_read_only())
        self.open(CP1252_REL)
        self.assertFalse(self.editor.is_editable())
        self.assertTrue(self.editor.editor.isReadOnly())
        self.assertIn("solo lectura", self.editor.status_label.text())
        self.assertFalse(self.editor.commit_pending())

    def open(self, rel):
        self.assertTrue(self.editor.open_document(rel), self.editor.status_label.text())


class CatalogTests(unittest.TestCase):
    def test_criterion12_the_editor_keys_exist_in_spanish_and_english(self):
        es, en = load_catalog("es"), load_catalog("en")
        keys = {key for key in es if key.startswith("editor.")}
        self.assertGreaterEqual(len(keys), 20)
        self.assertEqual(keys, {key for key in en if key.startswith("editor.")})
        self.assertIn("editor.undo_edit", keys)
        self.assertIn("editor.unencodable", keys)


if __name__ == "__main__":
    unittest.main()
