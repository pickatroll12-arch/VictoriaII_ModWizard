"""Regresiones de la revisión adversarial de la interfaz (iteración 2, hallazgos UI-IT2-01 a UI-IT2-10).

Las sondas del verificador, convertidas en pruebas contra el ``Project`` real. UI-IT2-04 (las notas de la
recuperación en el diálogo) lo cubre ``test_review_journal``.
"""

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
import test_ui_descriptor as descriptor_tests  # noqa: E402
import test_ui_new_mod as new_mod_tests  # noqa: E402
import test_ui_shell as shell_tests  # noqa: E402
from _fake_project import FakeOpener  # noqa: E402
from _layers import build_layers  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QDialog, QHeaderView  # noqa: E402
from test_ui_real_project import RealProjectMixin  # noqa: E402
from test_ui_smoke import UiTestCase  # noqa: E402

APP = _qt.application()

from vic2studio.core.project import ChangeSet, PlannedWrite, Project, WriteAction  # noqa: E402
from vic2studio.core.vfs import VPath  # noqa: E402
from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.dialogs import ConflictDialog, NewModDialog, RecoveryDialog, SaveReviewDialog  # noqa: E402
from vic2studio.ui.main_window import UNSAVED_DISCARD, UNSAVED_SAVE  # noqa: E402
from vic2studio.ui.session import Session  # noqa: E402
from vic2studio.ui.shell.pending_changes import PendingChangesPanel  # noqa: E402
from vic2studio.ui.tasks import wait_for_tasks  # noqa: E402


class HalfTypedDescriptorTests(RealProjectMixin, descriptor_tests.DescriptorCase):
    """UI-IT2-01: Ctrl+S o cerrar con un campo a medio teclear (sin perder el foco) no pierden lo escrito."""

    def type_without_leaving(self):
        page = self.open_window()
        self.window.activateWindow()
        page.name_edit.setFocus()
        _qt.process_events(20)
        page.name_edit.selectAll()
        QTest.keyClicks(page.name_edit, "Nombre Nuevo")
        _qt.process_events()
        return page

    def test_ctrl_s_saves_what_was_being_typed(self):
        page = self.type_without_leaving()
        QTest.keyClick(page.name_edit, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
        _qt.process_events(20)
        self.assertIn(b'name = "Nombre Nuevo"', self.layers.descriptor.read_bytes())

    def test_closing_asks_about_what_was_being_typed(self):
        self.type_without_leaving()
        self.window.ask_unsaved.return_value = UNSAVED_SAVE
        self.window.close()
        _qt.process_events(20)
        self.assertEqual(self.window.ask_unsaved.call_count, 1)
        self.assertIn(b'name = "Nombre Nuevo"', self.layers.descriptor.read_bytes())

    def test_saving_without_typing_does_not_rewrite_an_odd_descriptor(self):
        """El arreglo solo confirma lo tecleado: guardar sin tocar nada no normaliza un descriptor «raro»."""
        cases = {
            "espacios": b'name = " Victorian Spirit "\r\npath = "mod/VSM"\r\nuser_dir = "VSM"\r\n',
            "orden de replace_path": (b'name = "VSM"\r\npath = "mod/VSM"\r\nuser_dir = "VSM"\r\n'
                                      b'replace_path = "history/countries"\r\nreplace_path = "common"\r\n'),
            "dependencias repetidas": (b'name = "VSM"\r\npath = "mod/VSM"\r\nuser_dir = "VSM"\r\n'
                                       b'dependencies = { "A" "A" "" }\r\n'),
            "sin user_dir": b'name = "VSM"\r\npath = "mod/VSM"\r\n',
        }
        for name, data in cases.items():
            with self.subTest(caso=name):
                self.layers.descriptor.write_bytes(data)
                self.open_window()
                self.window.save_project()
                _qt.process_events()
                self.assertEqual(self.layers.descriptor.read_bytes(), data)
                self.window.close()
                self.windows.remove(self.window)
                _qt.dispose(self.window)


class ExternalDeletionTests(RealProjectMixin, shell_tests.ProjectWindowCase):
    """UI-IT2-02: un archivo borrado fuera del Studio no se anuncia como «modificado»."""

    REL = "common/vsm_new.txt"

    def record(self):
        seen = []
        self.dialogs.handlers[ConflictDialog] = lambda dialog: seen.append(
            {"deleted": dialog.deleted, "text": dialog.text.text()})
        return seen

    def test_a_clean_deleted_file_does_not_ask(self):
        window = self.open_window()
        self.project.ws.open(VPath.of(self.REL))
        seen = self.record()
        self.layers.mod(self.REL).unlink()
        window._on_application_state(Qt.ApplicationState.ApplicationActive)
        self.assertEqual(seen, [], "el núcleo ya lo soltó")

    def test_a_dirty_deleted_file_says_it_was_deleted(self):
        window = self.open_window()
        self.edit(self.REL, "y = 3\r\n")
        seen = self.record()
        self.layers.mod(self.REL).unlink()
        window._on_application_state(Qt.ApplicationState.ApplicationActive)
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0]["deleted"])
        self.assertEqual(seen[0]["text"], tr("conflict.text_deleted", name=self.REL))


class SaveWarningTests(RealProjectMixin, shell_tests.ProjectWindowCase):
    """UI-IT2-03: los avisos no bloqueantes del guardado (una ruta de más de 260 caracteres) llegan al usuario."""

    def setUp(self):
        super().setUp()
        deep = Path(tempfile.mkdtemp(prefix="deep-")) / "carpeta_larga_"
        while len(str(deep / "Victoria 2/mod/VSM/common/.countries.txt.20261027T000000-abcdef.tmp")) < 245:
            deep = deep / "sub_carpeta_xx"
        deep.mkdir(parents=True)
        self.layers = build_layers(base=deep, game=shell_tests.GAME, mod=shell_tests.MOD, mod_name="VSM")

    def test_the_warning_is_shown(self):
        window = self.open_window()
        self.edit()
        reports = []
        window.session.saved.connect(reports.append)
        self.assertTrue(window.save_project())
        warnings = [p for p in reports[0].problems if not p.blocking]
        self.assertTrue(warnings, "la prueba necesita un aviso del núcleo")
        self.assertIn(warnings[0].message("es"), window.status_label.text())
        set_language("en")
        self.assertIn(warnings[0].message("en"), window.status_label.text(), "se retraduce")


class PendingHeaderTests(UiTestCase):
    """UI-IT2-05: con Qt 6.5 la flecha de orden de la hoja de estilo recortaba «Líneas»/«Lines» en Cambios
    pendientes (y en el diálogo de revisión). Solo falla sin el arreglo con PySide6 6.5."""

    def clipped(self, lang: str) -> bool:
        set_language(lang)
        window = self.make_window()
        panel = PendingChangesPanel(window)
        panel.resize(800, 300)
        panel.show()
        diff = "--- a/common/a.txt\n+++ b/common/a.txt\n@@ -1 +1 @@\n-a = 1\n+a = 2\n"
        panel.set_changeset(ChangeSet((PlannedWrite(VPath.of("common/a.txt"), Path("/tmp/x/common/a.txt"),
                                                    WriteAction.MODIFY, b"a = 2\r\n", None, diff),)))
        _qt.process_events(20)
        header = panel.tree.header()
        x, width = header.sectionViewportPosition(2), header.sectionSize(2)
        before = header.grab().toImage().copy(x, 0, width - 1, header.height())
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(2, width + 80)
        _qt.process_events(20)
        after = header.grab().toImage().copy(header.sectionViewportPosition(2), 0, width - 1, header.height())
        panel.deleteLater()
        return before != after

    def test_lines_header_is_painted_whole(self):
        for lang in ("es", "en"):
            with self.subTest(lang=lang):
                self.assertFalse(self.clipped(lang))


class ManyConflictsTests(RealProjectMixin, shell_tests.ProjectWindowCase):
    """UI-IT2-06: con muchos conflictos, la revisión de guardado sigue mostrando la lista y los botones."""

    COUNT = 25

    def setUp(self):
        super().setUp()
        mod = dict(shell_tests.MOD)
        mod.update({f"common/f{i:02d}.txt": f"x{i} = 1\r\n" for i in range(self.COUNT)})
        self.layers = build_layers(game=shell_tests.GAME, mod=mod, mod_name="VSM")
        self.addCleanup(self.layers.cleanup)

    def test_the_dialog_keeps_the_list_and_the_buttons(self):
        window = self.open_window()
        for i in range(self.COUNT):
            self.edit(f"common/f{i:02d}.txt", f"x{i} = 2\r\n")
        for i in range(self.COUNT):
            self.layers.mod(f"common/f{i:02d}.txt").write_bytes(f"x{i} = 99\r\n".encode())
        measures = []

        def handler(dialog):
            dialog.show()
            _qt.process_events(50)
            measures.append((dialog.panel.tree.height(),
                             all(b.height() >= b.sizeHint().height() for b in (dialog.save_button,
                                                                               dialog.cancel_button)),
                             dialog.minimumSizeHint().height(), dialog.screen().availableGeometry().height()))
            dialog.reject()

        self.dialogs.handlers[SaveReviewDialog] = handler
        self.assertFalse(window.save_project())
        (tree_height, buttons_whole, minimum, screen), = measures
        self.assertGreaterEqual(tree_height, 80, "la lista de archivos no se puede leer")
        self.assertTrue(buttons_whole, "botones aplastados")
        self.assertLessEqual(minimum, screen, "el diálogo no cabe en la pantalla: los problemas no se desplazan")


class LateProjectTests(shell_tests.ProjectWindowCase):
    """UI-IT2-07: cerrar la ventana mientras el proyecto se abre no deja el Project tardío abierto (ni su bloqueo)."""

    def window_with(self, opener):
        window = self.make_window(session=Session(opener=opener))
        window.exec_dialog = self.dialogs
        page = window.page("project")
        page.set_game_path(self.layers.game_root)
        page.set_mod_path(self.layers.mod_root)
        return window

    def assert_released(self, late: Project) -> None:
        was_closed = late.closed
        if not late.closed:
            late.ws.bind_to_current_thread()
            late.close()
        self.assertTrue(was_closed, "el proyecto que llegó tarde no se cerró: su bloqueo queda tomado")
        again = Project.open(self.layers.game_root, self.layers.mod_root)
        again.close()
        self.assertFalse(again.read_only)

    def test_a_project_opened_while_the_window_closes(self):
        opened, past_checks = [], threading.Event()

        def opener(game, mod, **kwargs):
            project = Project.open(game, mod, **kwargs)   # ya pasó la última comprobación de cancelación
            opened.append(project)
            past_checks.set()
            time.sleep(0.3)
            return project

        window = self.window_with(opener)
        self.assertTrue(_qt.wait_until(past_checks.is_set, 5000))
        window.close()
        self.assertTrue(wait_for_tasks(5000))
        _qt.process_events(100)
        self.assert_released(opened[0])

    def test_a_result_already_queued_when_the_window_closes(self):
        opened, started, release = [], threading.Event(), threading.Event()

        def opener(game, mod, **kwargs):
            started.set()
            release.wait(5)
            project = Project.open(game, mod, **kwargs)
            opened.append(project)
            return project

        window = self.window_with(opener)
        self.assertTrue(_qt.wait_until(started.is_set, 5000))
        release.set()
        self.assertTrue(wait_for_tasks(5000))     # el resultado ya está en la cola de eventos, sin entregar
        window.close()
        _qt.process_events(100)
        self.assert_released(opened[0])


class CreateDescriptorLabelTests(RealProjectMixin, descriptor_tests.DescriptorCase):
    """UI-IT2-08: «Crear el descriptor» no muestra el token interno «all» en el historial ni en la barra."""

    def test_no_internal_token_in_the_texts(self):
        self.layers.descriptor.unlink()
        page = self.open_window()
        page.create_button.click()
        _qt.process_events(20)
        label, fmt = self.window.session.history()[0]
        texts = {"historial": tr(label, **fmt), "estado": self.window.status_label.text(),
                 "deshacer": self.window.undo_button.toolTip()}
        set_language("en")
        _qt.process_events()
        texts["history"] = tr(label, **fmt)
        texts["status"] = self.window.status_label.text()
        for name, text in texts.items():
            with self.subTest(texto=name):
                self.assertNotIn("all", text.replace("All", ""))


class SlowCreator(new_mod_tests.FakeCreator):
    def __call__(self, *args, **kwargs):
        time.sleep(0.4)
        return super().__call__(*args, **kwargs)


class NewModCancelTests(UiTestCase):
    """UI-IT2-09: mientras se crea el mod no se puede cancelar (ni con el botón ni con Esc): antes el diálogo se
    cerraba como cancelado y el mod se creaba igual."""

    def setUp(self):
        super().setUp()
        self.layers = build_layers(game=new_mod_tests.GAME, mod={"common/countries.txt": "VSM = x\r\n"},
                                   mod_name="VSM")
        self.addCleanup(self.layers.cleanup)

    def run_cancelling(self, how: str) -> dict:
        window = self.make_window(session=Session(opener=FakeOpener(), creator=SlowCreator()))
        window.ask_unsaved = mock.Mock(return_value=UNSAVED_DISCARD)
        dialogs = shell_tests.DialogLog()
        seen = {"rejected": False}

        def create(dialog):
            dialog.rejected.connect(lambda: seen.__setitem__("rejected", True))
            dialog.show()
            dialog.name_edit.setText("Dark Age Mod")
            dialog.create_button.click()
            seen["cancel_enabled"] = dialog.cancel_button.isEnabled()
            if how == "button":
                dialog.cancel_button.click()
            else:
                QTest.keyClick(dialog, Qt.Key.Key_Escape)
            _qt.wait_until(lambda: dialog.result() == QDialog.DialogCode.Accepted, 3000)
            seen["final"] = dialog.result()

        dialogs.handlers[NewModDialog] = create
        window.exec_dialog = dialogs
        window.page("project").set_game_path(self.layers.game_root)
        window.show_page("home").new_tile.click()
        self.assertTrue(wait_for_tasks(5000))
        _qt.process_events(100)
        _qt.wait_until(lambda: not window.is_busy(), 3000)
        return seen

    def test_the_cancel_button_is_disabled_while_creating(self):
        seen = self.run_cancelling("button")
        self.assertFalse(seen["cancel_enabled"])
        self.assertFalse(seen["rejected"])
        self.assertEqual(seen["final"], QDialog.DialogCode.Accepted)

    def test_escape_does_not_cancel_while_creating(self):
        seen = self.run_cancelling("escape")
        self.assertFalse(seen["rejected"])
        self.assertEqual(seen["final"], QDialog.DialogCode.Accepted)


class RecoveryPluralTests(RealProjectMixin, shell_tests.ProjectWindowCase):
    """UI-IT2-10: «Hay un autoguardado», no «Hay 1 autoguardados de una sesión»."""

    def test_one_orphan_session(self):
        self.earlier_session()
        texts = {}

        def handler(dialog):
            texts["es"] = dialog.sessions_intro.text()
            set_language("en")
            dialog.retranslate()
            texts["en"] = dialog.sessions_intro.text()
            set_language("es")

        self.dialogs.handlers[RecoveryDialog] = handler
        self.open_window()
        self.assertEqual(texts["es"], tr("recovery.sessions_intro_one"))
        self.assertNotIn("1 autoguardados", texts["es"])
        self.assertNotIn("1 autosaves", texts["en"])

    def test_several_sessions_are_not_one_session(self):
        dialog = RecoveryDialog(["s1", "s2"])
        self.addCleanup(dialog.deleteLater)
        self.assertNotIn("de una sesión", dialog.sessions_intro.text())


if __name__ == "__main__":
    unittest.main()
