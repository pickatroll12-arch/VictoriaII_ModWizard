"""Sección «Descriptor .mod» (wizard §14.1) contra el ``Project`` falso: el formulario lee el descriptor, cada campo
confirmado es una transacción que se deshace, los problemas se ven al teclear y Guardar escribe los bytes.

``test_ui_real_project`` repite estas pruebas contra el ``Project`` real (``make_opener``)."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
from _fake_project import FakeOpener  # noqa: E402
from _layers import build_layers, descriptor_bytes  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QFocusEvent, QTextDocument  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from test_ui_shell import GAME, DialogLog  # noqa: E402
from test_ui_smoke import UiTestCase  # noqa: E402

APP = _qt.application()

from vic2studio.core.clausewitz import to_source  # noqa: E402
from vic2studio.core.modcheck import DESCRIPTOR_BAD_REPLACE_PATH, DESCRIPTOR_NO_PATH  # noqa: E402
from vic2studio.core.modfile import (  # noqa: E402
    FIELD_QUOTE,
    REPLACE_PATH_EMPTY,
    DescriptorSpec,
    render_descriptor,
)
from vic2studio.core.vfs import DESCRIPTOR_REL  # noqa: E402
from vic2studio.i18n import N_, set_language, tr  # noqa: E402
from vic2studio.ui.dialogs import NewModDialog  # noqa: E402
from vic2studio.ui.main_window import UNSAVED_DISCARD  # noqa: E402
from vic2studio.ui.session import Session  # noqa: E402

# Comentario y clave desconocida: el formulario no los toca y el guardado los conserva.
DESCRIPTOR = (b'# Mi mod\r\nname = "Victorian Spirit"\r\npath = "mod/VSM"\r\nuser_dir = "VSM"\r\n'
              b'replace_path = "history/countries"\r\narchive = "vsm.zip"\r\n')
GAME_WITH_HISTORY = {**GAME, "history/countries/AAA - Aland.txt": "capital = 1\r\n",
                     "history/countries/BBB - Borea.txt": "capital = 2\r\n", "history/pops/1836.1.1/x.txt": "x\r\n"}


def plain(text: str) -> str:
    """El texto que se lee de un rótulo enriquecido (``widgets.rich``): sin etiquetas ni los ` del catálogo."""
    document = QTextDocument()
    document.setHtml(text.replace("`", ""))
    return document.toPlainText().replace(" ", "\n")


class DescriptorCase(UiTestCase):
    descriptor = DESCRIPTOR

    def setUp(self):
        super().setUp()
        # El mod tiene archivos en history/countries: el replace_path del descriptor no deja el juego sin ellos.
        self.layers = build_layers(game=GAME_WITH_HISTORY, mod={"common/countries.txt": "BBB = x\r\n",
                                                                "history/countries/BBB - Borea.txt": "capital = 3\r\n"},
                                   mod_name="VSM", descriptor=self.descriptor)
        self.addCleanup(self.layers.cleanup)
        self.dialogs = DialogLog()

    def make_opener(self, **options):
        """El ``Project`` falso; ``test_ui_real_project`` repite estas pruebas con ``Project.open``."""
        return FakeOpener(**options)

    def open_window(self, **options):
        self.opener = self.make_opener(**options)
        window = self.make_window(session=Session(opener=self.opener))
        window.exec_dialog = self.dialogs
        window.ask_unsaved = mock.Mock(return_value=UNSAVED_DISCARD)
        project = window.page("project")
        project.set_game_path(self.layers.game_root)
        project.set_mod_path(self.layers.mod_root)
        self.assertTrue(_qt.wait_until(lambda: window.session.project is not None and not window.is_busy(), 5000))
        self.window = window
        self.page = window.show_page("descriptor")
        _qt.process_events(20)
        return self.page

    @property
    def project(self):
        return self.window.session.project

    def handle(self):
        return self.project.ws.peek(DESCRIPTOR_REL)

    def type_into(self, edit, text: str) -> None:
        """Como el usuario: borra, teclea (``textEdited``) y sale del campo (``editingFinished``)."""
        edit.selectAll()
        QTest.keyClick(edit, Qt.Key.Key_Backspace)
        QTest.keyClicks(edit, text)
        edit.editingFinished.emit()
        _qt.process_events()

    def problem_texts(self) -> list[str]:
        return [badge.label.text() for badge in self.page.problem_badges if badge.isVisibleTo(self.page)]


class DescriptorFormTests(DescriptorCase):
    def test_empty_without_a_project(self):
        window = self.make_window()
        page = window.show_page("descriptor")
        self.assertIs(page.stack.currentWidget(), page.empty)
        page.home_button.click()
        self.assertEqual(window.current_page_key(), "project:home")

    def test_the_form_shows_the_descriptor(self):
        page = self.open_window()
        self.assertIs(page.stack.currentWidget(), page.view)
        self.assertEqual(page.name_edit.text(), "Victorian Spirit")
        self.assertEqual(page.folder_edit.text(), "VSM")
        self.assertEqual(page.user_dir_edit.text(), "VSM")
        checks = {check.property("folder"): check for check in page.replace_checks}
        self.assertTrue(checks["history/countries"].isChecked())
        self.assertFalse(checks["common"].isChecked())
        self.assertIn("history/pops", checks)
        self.assertEqual(page.form_spec(), DescriptorSpec("Victorian Spirit", "VSM", "VSM", ("history/countries",)))
        self.assertIn("# Mi mod", page.preview.toPlainText())
        self.assertIn('archive = "vsm.zip"', page.preview.toPlainText())
        self.assertEqual(page.file_label.text(), str(self.layers.descriptor))
        self.assertEqual(self.problem_texts(), [tr("descriptor.no_problems")])
        self.assertEqual(plain(page.replace_effect.text()),
                         "• " + plain(tr("descriptor.replace_effect", count=2, folder="history/countries")))
        self.assertFalse(page.missing_box.isVisibleTo(page))
        self.assertFalse(page.read_only_badge.isVisibleTo(page))
        self.assertIsNone(self.handle().read_only_reason)
        self.assertFalse(self.handle().dirty, "leer el descriptor no lo cambia")

    def test_a_committed_field_is_one_undoable_step_and_saving_keeps_the_rest(self):
        page = self.open_window()
        self.type_into(page.name_edit, "Victorian Spirit Ñ")
        handle = self.handle()
        self.assertTrue(handle.dirty)
        self.assertEqual(self.project.ws.history(), [(N_("descriptor.undo_edit"), {"field": "name"})])
        self.assertEqual(self.window.status_label.text(), tr("descriptor.status_edited", field="name"))
        self.assertIn('name = "Victorian Spirit Ñ"', page.preview.toPlainText())
        self.assertEqual(page.save_note.text().count(tr("descriptor.preview_dirty")[:12]), 1)
        # Confirmar otra vez lo mismo no añade pasos; otro campo, sí.
        page.name_edit.editingFinished.emit()
        self.assertEqual(len(self.project.ws.history()), 1)
        self.type_into(page.user_dir_edit, "VSM_saves")
        self.assertEqual(len(self.project.ws.history()), 2)
        self.assertTrue(self.window.save_project())
        self.assertEqual(self.dialogs.dialogs, [], "el descriptor del mod no se copia del juego: sin revisión")
        self.assertEqual(self.layers.descriptor.read_bytes(),
                         DESCRIPTOR.replace(b'"Victorian Spirit"', '"Victorian Spirit Ñ"'.encode("cp1252"))
                         .replace(b'user_dir = "VSM"', b'user_dir = "VSM_saves"'))
        # Deshacer vuelve a llenar el formulario.
        self.window.undo()
        self.assertEqual(page.user_dir_edit.text(), "VSM")
        self.window.undo()
        self.assertEqual(page.name_edit.text(), "Victorian Spirit")
        self.assertTrue(self.handle().dirty, "deshacer tras guardar deja cambios respecto al disco")

    def test_problems_follow_the_typing_before_committing(self):
        page = self.open_window()
        page.folder_edit.selectAll()
        QTest.keyClick(page.folder_edit, Qt.Key.Key_Backspace)
        _qt.process_events()
        self.assertIn(DESCRIPTOR_NO_PATH, [issue.code for issue in page.issues])
        self.assertIn(page.issues[0].message("es"), self.problem_texts())
        self.assertFalse(self.handle().dirty, "teclear no confirma")
        QTest.keyClicks(page.folder_edit, "VSM")
        _qt.process_events()
        self.assertEqual(self.problem_texts(), [tr("descriptor.no_problems")])

    def test_a_value_with_quotes_is_not_committed(self):
        page = self.open_window()
        self.type_into(page.name_edit, 'Mod "con comillas"')
        self.assertIn(FIELD_QUOTE, [issue.code for issue in page.issues])
        self.assertFalse(self.handle().dirty)
        self.assertEqual(self.project.ws.history(), [])
        self.assertEqual(self.layers.descriptor.read_bytes(), DESCRIPTOR)

    def test_replace_path_checkbox_commits_and_explains_the_effect(self):
        page = self.open_window()
        checks = {check.property("folder"): check for check in page.replace_checks}
        checks["common"].click()
        _qt.process_events()
        self.assertEqual(self.project.ws.history()[0], (N_("descriptor.undo_edit"), {"field": "replace_path"}))
        self.assertEqual(page.form_spec().replace_paths, ("common", "history/countries"), "en el orden de la lista")
        text = to_source(self.handle().model.document)
        self.assertIn('replace_path = "common"', text)
        self.assertIn('replace_path = "history/countries"', text)
        effect = plain(page.replace_effect.text()).split("\n")
        self.assertEqual(effect, ["• " + plain(tr("descriptor.replace_effect", count=2, folder="common")),
                                  "• " + plain(tr("descriptor.replace_effect", count=2, folder="history/countries"))])
        checks = {check.property("folder"): check for check in page.replace_checks}
        checks["history/countries"].click()
        checks["common"].click()
        _qt.process_events()
        self.assertNotIn("replace_path", to_source(self.handle().model.document))
        self.assertEqual(plain(page.replace_effect.text()), plain(tr("descriptor.replace_effect_none")))

    def test_folder_suggestions_and_same_user_dir(self):
        page = self.open_window()
        page.name_edit.setText("Dark Age Mod")
        page._fill_suggestions()
        options = [action.text() for action in page.suggest_menu.actions()]
        self.assertEqual(options[0], "VSM", "primero, la carpeta real del mod")
        self.assertIn("DAM", options)
        self.assertIn("Dark_Age_Mod", options)
        next(a for a in page.suggest_menu.actions() if a.text() == "DAM").trigger()
        self.assertEqual(page.folder_edit.text(), "DAM")
        self.assertIn('path = "mod/DAM"', to_source(self.handle().model.document))
        # La carpeta ya no es la del mod: se avisa.
        self.assertNotEqual(self.problem_texts(), [tr("descriptor.no_problems")])
        page.same_button.click()
        self.assertEqual(page.user_dir_edit.text(), "DAM")
        self.assertIn('user_dir = "DAM"', to_source(self.handle().model.document))

    def test_dependencies_are_committed_when_leaving_the_field(self):
        page = self.open_window()
        page.dependencies_edit.setPlainText("Base Mod\n\n  Otro Mod  ")
        self.assertFalse(self.handle().dirty)
        QApplication.sendEvent(page.dependencies_edit, QFocusEvent(QEvent.Type.FocusOut))
        _qt.process_events()
        self.assertEqual(page.form_spec().dependencies, ("Base Mod", "Otro Mod"))
        text = to_source(self.handle().model.document)
        self.assertIn('"Base Mod"', text)
        self.assertIn('"Otro Mod"', text)

    def test_new_mod_button_opens_the_dialog(self):
        page = self.open_window()
        page.new_button.click()
        self.assertEqual(self.dialogs.types(), [NewModDialog])
        self.assertEqual(self.dialogs.dialogs[0].game_root, self.layers.game_root)

    def test_language_switch_keeps_the_form(self):
        page = self.open_window()
        self.type_into(page.name_edit, "Otro nombre")
        set_language("en")
        self.assertTrue(page.name_label.text().startswith("Name"), page.name_label.text())
        self.assertEqual(page.name_edit.text(), "Otro nombre")
        self.assertEqual(page.create_button.text(), tr("descriptor.create"))


class MissingDescriptorTests(DescriptorCase):
    def setUp(self):
        super().setUp()
        self.layers.descriptor.unlink()

    def test_the_missing_descriptor_is_created_with_the_canonical_bytes(self):
        page = self.open_window()
        self.assertTrue(page.missing_box.isVisibleTo(page))
        self.assertTrue(page.create_button.isEnabled())
        self.assertEqual(page.form_spec(), DescriptorSpec("VSM", "VSM", "VSM"))
        expected = render_descriptor(DescriptorSpec("VSM", "VSM", "VSM"))
        self.assertEqual(expected, b'name = "VSM"\r\npath = "mod/VSM"\r\nuser_dir = "VSM"\r\n')
        self.assertEqual(page.preview.toPlainText().replace("\n", "\r\n"), expected.decode("cp1252"))
        self.assertIsNone(self.handle(), "nada se crea hasta que se pide")
        page.create_button.click()
        self.assertFalse(page.missing_box.isVisibleTo(page))
        self.assertTrue(self.handle().dirty)
        self.assertTrue(self.window.save_project())
        self.assertEqual(self.layers.descriptor.read_bytes(), expected)

    def test_editing_a_field_also_creates_it(self):
        page = self.open_window()
        self.type_into(page.name_edit, "Shago Mod")
        self.assertTrue(self.window.save_project())
        self.assertEqual(self.layers.descriptor.read_bytes(), render_descriptor(DescriptorSpec("Shago Mod", "VSM", "VSM")))


class ReadOnlyDescriptorTests(DescriptorCase):
    def test_a_read_only_project_disables_the_form(self):
        page = self.open_window(read_only=True)
        self.assertFalse(page.name_edit.isEnabled())
        self.assertFalse(all(check.isEnabled() for check in page.replace_checks))
        self.assertTrue(page.read_only_badge.isVisibleTo(page))
        self.assertEqual(page.read_only_badge.label.text(), tr("descriptor.read_only"))
        self.assertFalse(page.commit(force=True))
        self.assertEqual(self.project.ws.history(), [])


class SyntaxErrorDescriptorTests(DescriptorCase):
    descriptor = descriptor_bytes("VSM", "VSM", "VSM") + b"}\r\n"

    def test_a_descriptor_with_syntax_errors_is_only_shown(self):
        page = self.open_window()
        self.assertEqual(self.handle().read_only_reason, "parse_errors")
        self.assertFalse(page.name_edit.isEnabled())
        self.assertEqual(page.read_only_badge.label.text(), tr("descriptor.read_only_syntax"))
        page.name_edit.setText("Otro")
        self.assertFalse(page.commit())
        self.assertFalse(self.handle().dirty)


class ReplacePathProblemTests(DescriptorCase):
    # history/pops existe en el juego base, pero el mod no tiene nada ahí; y un replace_path vacío.
    descriptor = descriptor_bytes("VSM", "VSM", "VSM", replace_paths=("history/pops", ""))

    def test_replace_path_problems_are_reported(self):
        page = self.open_window()
        codes = [issue.code for issue in page.issues]
        self.assertIn(REPLACE_PATH_EMPTY, codes)
        self.assertIn(DESCRIPTOR_BAD_REPLACE_PATH, codes)
        empty = next(issue for issue in page.issues if issue.code == REPLACE_PATH_EMPTY)
        self.assertIn("history/pops", empty.message("es"))
        badges = [badge for badge in page.problem_badges if badge.isVisibleTo(page)]
        self.assertEqual(len(badges), len(page.issues))
        self.assertIn(empty.message("es"), [badge.label.text() for badge in badges])
        self.assertIn("error", [badge.level for badge in badges])
        # Con un archivo del mod en esa carpeta deja de ser un problema.
        self.layers.mod("history/pops/1836.1.1/vsm.txt").parent.mkdir(parents=True)
        self.layers.mod("history/pops/1836.1.1/vsm.txt").write_bytes(b"x\r\n")
        page.name_edit.textEdited.emit("VSM")
        self.assertNotIn(REPLACE_PATH_EMPTY, [issue.code for issue in page.issues])


if __name__ == "__main__":
    unittest.main()
