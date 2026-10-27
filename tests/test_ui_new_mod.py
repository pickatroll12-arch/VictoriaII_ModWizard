"""Diálogo «Nuevo mod» (wizard §14.1): carpeta sugerida, ``user_dir``, problemas al momento y la creación en segundo
plano a través de ``Session.create_mod`` (con un creador falso: el real, ``create_mod_skeleton``, se prueba en
``test_modfile_write``)."""

import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
from _fake_project import FakeOpener  # noqa: E402
from _layers import build_layers, descriptor_bytes  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402
from test_ui_shell import GAME, DialogLog  # noqa: E402
from test_ui_smoke import UiTestCase  # noqa: E402

APP = _qt.application()

from vic2studio.core.modfile import (  # noqa: E402
    DESCRIPTOR_FOLDER_RESERVED,
    DESCRIPTOR_FOLDER_TAKEN,
    DescriptorSpec,
    find_descriptor,
)
from vic2studio.i18n import tr  # noqa: E402
from vic2studio.ui.dialogs import NewModDialog  # noqa: E402
from vic2studio.ui.main_window import UNSAVED_DISCARD  # noqa: E402
from vic2studio.ui.session import Session  # noqa: E402
from vic2studio.ui.tasks import wait_for_tasks  # noqa: E402


class FakeCreator:
    """Sustituye a ``create_mod_skeleton``: escribe la carpeta y el descriptor (las pruebas pueden) o falla."""

    def __init__(self, error: BaseException | None = None):
        self.error = error
        self.calls: list[tuple] = []
        self.threads: list[int] = []

    def __call__(self, game_root, spec: DescriptorSpec, *, template=None):
        self.calls.append((game_root, spec, template))
        self.threads.append(threading.get_ident())
        if self.error is not None:
            raise self.error
        folder = Path(game_root) / "mod" / spec.folder
        (folder / "common").mkdir(parents=True)
        (folder.parent / f"{spec.folder}.mod").write_bytes(descriptor_bytes(spec.name, spec.folder, spec.user_dir))
        return find_descriptor(folder)


class NewModCase(UiTestCase):
    def setUp(self):
        super().setUp()
        # En <juego>/mod ya hay un mod «DAM»: su carpeta y su descriptor están ocupados.
        self.layers = build_layers(game=GAME, mod={"common/countries.txt": "DAM = x\r\n"}, mod_name="DAM")
        self.addCleanup(self.layers.cleanup)
        self.creator = FakeCreator()
        self.session = Session(creator=self.creator)
        self.addCleanup(_qt.dispose, self.session)

    def dialog(self, game_root=None, *, game: bool = True) -> NewModDialog:
        dialog = NewModDialog(self.session, self.layers.game_root if game else game_root)
        self.addCleanup(_qt.dispose, dialog)
        return dialog

    def badges(self, dialog) -> list[tuple[str, str]]:
        return [(badge.level, badge.label.text()) for badge in dialog.problem_badges if badge.isVisibleTo(dialog)]


class NewModDialogTests(NewModCase):
    def test_folder_is_suggested_from_the_name_until_it_is_typed(self):
        dialog = self.dialog()
        self.assertFalse(dialog.create_button.isEnabled(), "sin nombre no se crea")
        dialog.name_edit.setText("Dark Age Mod")
        options = [dialog.folder_combo.itemText(i) for i in range(dialog.folder_combo.count())]
        self.assertEqual(options, ["DAM2", "Dark_Age_Mod"], "DAM está ocupada: se propone DAM2")
        self.assertEqual(dialog.folder_combo.currentText(), "DAM2")
        self.assertEqual(dialog.user_dir_edit.text(), "DAM2")
        self.assertTrue(dialog.user_dir_edit.isReadOnly())
        self.assertEqual(dialog.spec(), DescriptorSpec("Dark Age Mod", "DAM2", "DAM2"))
        self.assertEqual(dialog.preview.text(), 'name = "Dark Age Mod"\npath = "mod/DAM2"\nuser_dir = "DAM2"')
        self.assertTrue(dialog.create_button.isEnabled())
        self.assertIn(("ok", tr("newmod.ready", folder="DAM2")), self.badges(dialog))
        # El usuario escribe la carpeta: el nombre ya no la cambia.
        edit = dialog.folder_combo.lineEdit()
        edit.selectAll()
        QTest.keyClicks(edit, "MiCarpeta")
        dialog.name_edit.setText("Dark Age Mod II")
        self.assertEqual(dialog.folder_combo.currentText(), "MiCarpeta")
        self.assertEqual(dialog.spec(), DescriptorSpec("Dark Age Mod II", "MiCarpeta", "MiCarpeta"))

    def test_user_dir_follows_the_folder_unless_unchecked(self):
        dialog = self.dialog()
        dialog.name_edit.setText("Shago Mod")
        self.assertEqual(dialog.spec().user_dir, dialog.spec().folder)
        dialog.same_check.setChecked(False)
        self.assertFalse(dialog.user_dir_edit.isReadOnly())
        dialog.user_dir_edit.setText("Partidas")
        dialog.name_edit.setText("Shago Mod 2")
        self.assertEqual(dialog.spec().user_dir, "Partidas")
        dialog.same_check.setChecked(True)
        self.assertEqual(dialog.spec().user_dir, dialog.spec().folder)

    def test_a_taken_or_reserved_folder_cannot_be_created(self):
        dialog = self.dialog()
        dialog.name_edit.setText("Otro")
        for folder, code in (("dam", DESCRIPTOR_FOLDER_TAKEN), ("CON", DESCRIPTOR_FOLDER_RESERVED)):
            with self.subTest(folder=folder):
                dialog.folder_combo.setEditText(folder)
                self.assertIn(code, [issue.code for issue in dialog.issues])
                self.assertFalse(dialog.create_button.isEnabled())
                self.assertFalse(dialog.create())
                self.assertIn("error", [level for level, _ in self.badges(dialog)])
        self.assertEqual(self.creator.calls, [])

    def test_without_a_game_nothing_can_be_created(self):
        dialog = self.dialog(None, game=False)
        self.assertTrue(dialog.game_badge.isVisibleTo(dialog))
        self.assertEqual(dialog.game_badge.label.text(), tr("newmod.no_game"))
        dialog.name_edit.setText("Shago Mod")
        self.assertFalse(dialog.create_button.isEnabled())
        self.assertFalse(dialog.create())

    def test_a_template_must_be_an_existing_folder(self):
        dialog = self.dialog()
        dialog.name_edit.setText("Shago Mod")
        missing = self.layers.base / "no-existe"
        dialog.template_edit.setText(str(missing))
        self.assertFalse(dialog.create_button.isEnabled())
        self.assertIn(("error", tr("newmod.template_missing", folder=str(missing))), self.badges(dialog))
        dialog.template_edit.setText(str(self.layers.mod_root))
        self.assertTrue(dialog.create_button.isEnabled())
        self.assertEqual(dialog.template(), self.layers.mod_root)

    def test_create_runs_in_the_background_and_closes_the_dialog(self):
        dialog = self.dialog()
        dialog.name_edit.setText("Shago Mod")
        spec = dialog.spec()
        self.assertTrue(dialog.create())
        self.assertFalse(dialog.name_edit.isEnabled(), "mientras se crea, el formulario no se toca")
        self.assertTrue(_qt.wait_until(lambda: dialog.result() == QDialog.DialogCode.Accepted, 5000))
        self.assertEqual(self.creator.calls, [(self.layers.game_root, spec, None)])
        self.assertNotEqual(self.creator.threads, [threading.get_ident()])
        self.assertEqual(dialog.created.name, "Shago Mod")
        self.assertEqual(dialog.created.path, f"mod/{spec.folder}")
        self.assertTrue(dialog.name_edit.isEnabled())

    def test_a_failure_is_shown_and_the_form_unlocks(self):
        self.creator.error = OSError(28, "No space left on device")
        dialog = self.dialog()
        dialog.name_edit.setText("Shago Mod")
        self.assertTrue(dialog.create())
        self.assertTrue(_qt.wait_until(lambda: dialog.name_edit.isEnabled(), 5000))
        self.assertTrue(wait_for_tasks(5000))
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIsNone(dialog.created)
        (level, text), = [badge for badge in self.badges(dialog) if badge[0] == "error"]
        self.assertIn("No space left on device", text)
        self.assertTrue(dialog.create_button.isEnabled(), "se puede volver a intentar")


class NewModWindowTests(UiTestCase):
    def setUp(self):
        super().setUp()
        self.layers = build_layers(game=GAME, mod={"common/countries.txt": "VSM = x\r\n"}, mod_name="VSM")
        self.addCleanup(self.layers.cleanup)

    def test_home_creates_a_mod_and_opens_it_in_the_descriptor(self):
        creator = FakeCreator()
        window = self.make_window(session=Session(opener=FakeOpener(), creator=creator))
        window.ask_unsaved = mock.Mock(return_value=UNSAVED_DISCARD)
        dialogs = DialogLog()

        def create(dialog):
            dialog.name_edit.setText("Dark Age Mod")
            dialog.create_button.click()
            self.assertTrue(_qt.wait_until(lambda: dialog.result() == QDialog.DialogCode.Accepted, 5000))

        dialogs.handlers[NewModDialog] = create
        window.exec_dialog = dialogs
        window.page("project").set_game_path(self.layers.game_root)
        home = window.show_page("home")
        home.new_tile.click()
        self.assertEqual(dialogs.types(), [NewModDialog])
        new_root = self.layers.game_root / "mod" / "DAM"
        self.assertTrue(_qt.wait_until(lambda: window.session.project is not None and not window.is_busy(), 5000))
        self.assertEqual(window.session.project.mod_root, new_root)
        self.assertEqual(window.page("project").mod_path(), new_root)
        self.assertEqual(window.current_page_key(), "project:descriptor")
        self.assertEqual(window.status_label.text(), tr("status.mod_created", name="Dark Age Mod"))
        self.assertIn("DAM", [tile.folder.name for tile in home.mod_tiles])
        self.assertEqual(window.page("descriptor").name_edit.text(), "Dark Age Mod")


if __name__ == "__main__":
    unittest.main()
