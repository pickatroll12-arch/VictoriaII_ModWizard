"""La interfaz contra el ``Project`` real (wizard §6.4, §20), de punta a punta y offscreen.

Las pruebas del armazón (``test_ui_shell``) y del descriptor (``test_ui_descriptor``) se escribieron contra el
``Project`` falso de ``_fake_project``; aquí se repiten abriendo el mod con ``Project.open``: el escaneo de la
VFS, el bloqueo, el deshacer por instantáneas, el guardado con diario y la recuperación de verdad. Lo que solo
tiene sentido con el falso (sesiones huérfanas inventadas, ``journal.clear_recovery`` simulado) se sustituye
por su equivalente real, y se añade lo que el falso no puede imitar: cerrar descartando, el autoguardado cuando
ya no queda nada sin guardar y los textos de los pasos que crea el núcleo.
"""

import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
import test_ui_descriptor as descriptor_tests  # noqa: E402
import test_ui_shell as shell_tests  # noqa: E402

APP = _qt.application()

from vic2studio.core.clausewitz import to_source  # noqa: E402
from vic2studio.core.project import Project, Workspace  # noqa: E402
from vic2studio.core.project import journal  # noqa: E402
from vic2studio.core.vfs import VPath  # noqa: E402
from vic2studio.i18n import N_, tr  # noqa: E402
from vic2studio.ui.dialogs import RecoveryDialog  # noqa: E402
from vic2studio.ui.main_window import UNSAVED_DISCARD, UNSAVED_SAVE  # noqa: E402

COUNTRIES = "common/countries.txt"


class RealOpener:
    """``Project.open`` que anota, como ``FakeOpener``, las llamadas y los proyectos que abre.

    ``read_only=True``: otro ``Project`` del mismo proceso toma antes el bloqueo, como otra ventana del Studio
    con el mismo mod (el de la prueba se abre entonces en solo lectura). El resto de opciones del falso no
    tienen equivalente: cada prueba prepara de verdad lo que necesita.
    """

    def __init__(self, test, *, read_only: bool = False, **options):
        if options:
            raise TypeError(f"opciones del Project falso sin equivalente real: {sorted(options)}")
        self.calls: list[tuple[Path | None, Path]] = []
        self.projects: list[Project] = []
        if read_only:
            holder = Project.open(test.layers.game_root, test.layers.mod_root)
            test.addCleanup(holder.close)

    def __call__(self, game_root, mod_root, **kwargs) -> Project:
        self.calls.append((game_root, mod_root))
        project = Project.open(game_root, mod_root, **kwargs)
        self.projects.append(project)
        return project


class RealProjectMixin:
    """Sustituye el ``FakeOpener`` de ``open_window`` por ``Project.open``."""

    def make_opener(self, **options):
        return RealOpener(self, **options)

    def recovery_root(self) -> Path:
        return self.layers.mod_root / journal.PROJECT_DIR / journal.RECOVERY_DIR

    def autosaves(self) -> list[str]:
        """Sesiones con autoguardado en el mod (las carpetas de ``.vic2studio/recovery``)."""
        root = self.recovery_root()
        return sorted(p.name for p in root.iterdir()) if root.is_dir() else []

    def earlier_session(self, text: bytes = b"CCC = 1\r\n") -> str:
        """Una sesión anterior que terminó con ``COUNTRIES`` sin guardar: su autoguardado se ofrecerá al abrir."""
        earlier = Project.open(self.layers.game_root, self.layers.mod_root)
        with earlier.edit(N_("pending.undo_revert"), name=COUNTRIES):
            earlier.ws.replace_text(earlier.ws.open(COUNTRIES), text)
        session = earlier.ws.session_id
        earlier.close()
        self.assertEqual(self.autosaves(), [session])
        return session

    def reopen(self) -> Project:
        project = Project.open(self.layers.game_root, self.layers.mod_root)
        self.addCleanup(project.close)
        return project


# --- las pruebas del armazón y del descriptor, con el núcleo real ------------------------------------------


class RealShellProjectTests(RealProjectMixin, shell_tests.ShellProjectTests):
    def test_recovery_is_offered_when_the_project_opens(self):
        session = self.earlier_session()
        shown = []
        self.dialogs.handlers[RecoveryDialog] = lambda dialog: (shown.append(list(dialog.sessions)),
                                                                dialog.rows[0][1].click())
        window = self.open_window()
        self.assertEqual(self.dialogs.types(), [RecoveryDialog])
        self.assertEqual(shown, [[session]])
        handle = self.project.ws.peek(VPath.of(COUNTRIES))
        self.assertTrue(handle.dirty)
        self.assertIn("CCC", to_source(handle.model.document))
        self.assertEqual(window.status_label.text(), tr("status.recovery_restored", count=1))
        self.assertEqual(self.project.orphan_sessions, [])
        self.assertEqual(self.project.ws.history(), [("undo.restore_session", {"session": session})])
        self.assertTrue(window.windowTitle().startswith("* "), "lo restaurado queda sin guardar")
        # El paso lo nombra el núcleo; la ventana lo muestra traducido, nunca con la clave.
        self.assertIn(tr("undo.restore_session", session=session), window.undo_button.toolTip())
        self.assertNotIn("undo.", window.undo_button.toolTip())
        self.assertNotIn(session, self.autosaves(), "lo restaurado ya es de esta sesión")
        window.undo()
        self.assertFalse(self.project.ws.peek(VPath.of(COUNTRIES)).dirty, "restaurar se deshace en un paso")

    def test_recovery_can_be_discarded(self):
        self.earlier_session()
        self.dialogs.handlers[RecoveryDialog] = lambda dialog: dialog.rows[0][2].click()
        self.open_window()
        self.assertEqual(self.dialogs.types(), [RecoveryDialog])
        self.assertEqual(self.project.orphan_sessions, [])
        self.assertEqual(self.window.session.dirty_count(), 0)
        self.assertEqual(self.autosaves(), [], "«Descartar» borra el autoguardado")
        self.window.session.close_project()
        self.assertEqual(self.reopen().orphan_sessions, [], "y no se vuelve a ofrecer")


class RealPendingSectionTests(RealProjectMixin, shell_tests.PendingSectionTests):
    pass


class RealHomeTests(RealProjectMixin, shell_tests.HomeTests):
    pass


class RealLayerBadgeExplorerTests(RealProjectMixin, shell_tests.LayerBadgeExplorerTests):
    pass


class RealDescriptorFormTests(RealProjectMixin, descriptor_tests.DescriptorFormTests):
    pass


class RealMissingDescriptorTests(RealProjectMixin, descriptor_tests.MissingDescriptorTests):
    pass


class RealReadOnlyDescriptorTests(RealProjectMixin, descriptor_tests.ReadOnlyDescriptorTests):
    pass


class RealSyntaxErrorDescriptorTests(RealProjectMixin, descriptor_tests.SyntaxErrorDescriptorTests):
    pass


class RealReplacePathProblemTests(RealProjectMixin, descriptor_tests.ReplacePathProblemTests):
    pass


# --- lo que el falso no puede imitar ------------------------------------------------------------------------


class LifecycleTests(RealProjectMixin, shell_tests.ProjectWindowCase):
    def test_discarding_on_close_leaves_nothing_to_recover(self):
        window = self.open_window()
        self.edit()
        self.window.session.write_recovery()
        self.assertEqual(len(self.autosaves()), 1, "el autoguardado ya tenía el cambio")
        window.ask_unsaved.return_value = UNSAVED_DISCARD
        self.assertTrue(window.close())
        self.assertEqual(window.ask_unsaved.call_count, 1)
        self.assertEqual(self.autosaves(), [], "«Descartar» al cerrar no deja autoguardado")
        self.assertEqual(self.reopen().orphan_sessions, [], "al reabrir no se ofrece lo que se tiró")
        self.assertEqual(self.layers.mod(COUNTRIES).read_bytes(), shell_tests.MOD[COUNTRIES].encode())

    def test_discarding_when_switching_mod_leaves_nothing_to_recover(self):
        other = shell_tests.build_layers(base=self.layers.base, game=shell_tests.GAME, mod={"common/x.txt": "x\r\n"},
                                         mod_name="Otro")
        window = self.open_window()
        self.edit()
        first = self.project
        window.ask_unsaved.return_value = UNSAVED_DISCARD
        window.page("project").set_mod_path(other.mod_root)
        self.assertTrue(_qt.wait_until(lambda: self.project is not None and self.project is not first
                                       and not window.is_busy(), 5000))
        self.assertTrue(first.closed)
        self.assertEqual(self.autosaves(), [])
        window.page("project").set_mod_path(self.layers.mod_root)
        self.assertTrue(_qt.wait_until(lambda: self.project is not None and self.project.mod_root == self.layers.mod_root
                                       and not window.is_busy(), 5000))
        self.assertEqual(self.dialogs.types(), [], "volver al mod no ofrece recuperar lo descartado")

    def test_closing_without_asking_keeps_the_recovery(self):
        """Solo «Descartar» borra el autoguardado: cerrar el proyecto sin preguntar lo conserva para la próxima vez."""
        self.open_window()
        self.edit()
        session = self.project.ws.session_id
        self.window.session.close_project()
        self.assertEqual(self.autosaves(), [session])
        self.assertEqual(self.reopen().orphan_sessions, [session])

    def test_saving_on_close_writes_and_leaves_nothing_to_recover(self):
        window = self.open_window()
        self.edit()
        self.window.session.write_recovery()
        window.ask_unsaved.return_value = UNSAVED_SAVE
        self.assertTrue(window.close())
        self.assertEqual(self.layers.mod(COUNTRIES).read_bytes(), b'BBB = "countries/Bolivia.txt"\r\n')
        self.assertEqual(self.autosaves(), [])
        self.assertEqual(self.reopen().orphan_sessions, [])

    def test_undoing_everything_also_clears_the_autosave(self):
        """Si se deshace todo, el autoguardado anterior no puede quedarse: tras un cierre inesperado ofrecería
        recuperar cambios que el usuario ya había deshecho."""
        window = self.open_window()
        self.edit()
        self.window.session.write_recovery()
        self.assertEqual(len(self.autosaves()), 1)
        window.undo()
        self.assertEqual(self.window.session.dirty_count(), 0)
        self.window.session.write_recovery()
        self.assertEqual(self.autosaves(), [])

    def test_the_autosave_follows_the_core_every_n_transactions(self):
        self.open_window()
        for n in range(Workspace.AUTOSAVE_TRANSACTIONS - 1):
            self.edit(text=f"BBB = {n}\r\n")
        self.assertEqual(self.autosaves(), [])
        self.edit(text="BBB = final\r\n")
        self.assertEqual(self.autosaves(), [self.project.ws.session_id])
        self.assertFalse(self.project.ws.autosave_due())

    def test_reverting_a_file_from_the_core_is_named_in_the_history(self):
        window = self.open_window()
        self.edit()
        self.project.ws.revert(COUNTRIES)
        _qt.process_events()
        self.assertEqual(self.project.ws.history()[0], ("undo.revert_file", {"rel": COUNTRIES}))
        window.history_button.click()
        _qt.process_events(20)
        dock = window.history_dock
        self.assertEqual(dock.list.item(0).text(), tr("undo.revert_file", rel=COUNTRIES))

    def test_project_settings_step_is_named_in_the_history(self):
        window = self.open_window()
        self.project.set_settings(dataclasses.replace(self.project.settings, prefix="VSX"))
        _qt.process_events()
        self.assertEqual(self.project.ws.history()[0], ("undo.project_settings", {}))
        self.assertIn(tr("undo.project_settings"), window.undo_button.toolTip())


if __name__ == "__main__":
    unittest.main()
