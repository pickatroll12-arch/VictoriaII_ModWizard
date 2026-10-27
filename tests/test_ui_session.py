"""``Session``: el puente entre el proyecto y Qt (wizard §6.4, D2, I12), contra el ``Project`` falso.

Abrir va en segundo plano y entrega el proyecto atado al hilo de la interfaz; las ediciones, el guardado, el
deshacer y la recuperación emiten sus señales una vez por operación; una apertura que llega tarde (porque
se pidió otra o se cerró) no se adopta y se cierra para soltar el bloqueo.
"""

import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
from _fake_project import FakeOpener, isolate_app_dirs, recovered_result  # noqa: E402
from _layers import build_layers  # noqa: E402

APP = _qt.application()
isolate_app_dirs()

from vic2studio.core.clausewitz import Scalar  # noqa: E402
from vic2studio.core.modfile import DescriptorSpec  # noqa: E402
from vic2studio.core.project import DocReplaced, Workspace  # noqa: E402
from vic2studio.core.vfs import DESCRIPTOR_REL  # noqa: E402
from vic2studio.ui.session import OPEN_FAILED, Session  # noqa: E402
from vic2studio.ui.tasks import wait_for_tasks  # noqa: E402

GAME = {"common/countries.txt": 'AAA = "countries/Aland.txt"\r\n', "common/cb_types.txt": "peace_order = { }\r\n"}


class Recorder:
    """Anota las emisiones de las señales de una sesión: ``events`` es una lista de (nombre, argumentos)."""

    NAMES = ("projectOpening", "projectOpened", "projectOpenFailed", "projectClosed", "documentsChanged",
             "dirtyChanged", "undoChanged", "saved", "saveBlocked", "recoveryAvailable", "externalChanges",
             "modCreated", "modCreateFailed", "workingDateChanged")

    def __init__(self, session: Session):
        self.events: list[tuple[str, tuple]] = []
        for name in self.NAMES:
            getattr(session, name).connect(lambda *args, n=name: self.events.append((n, args)))

    def names(self) -> list[str]:
        return [name for name, _ in self.events]

    def of(self, name: str) -> list[tuple]:
        return [args for event, args in self.events if event == name]

    def clear(self) -> None:
        self.events.clear()


class SessionCase(unittest.TestCase):
    def setUp(self):
        _qt.take_qt_messages()
        self.layers = build_layers(game=GAME, mod={"common/countries.txt": 'BBB = "countries/Borea.txt"\r\n'},
                                   mod_name="VSM")
        self.addCleanup(self.layers.cleanup)
        self.opener = FakeOpener()
        self.session = Session(opener=self.opener)
        self.events = Recorder(self.session)

    def tearDown(self):
        self.session.close_project()
        self.assertTrue(wait_for_tasks(10000))
        _qt.process_events()
        self.assertEqual(_qt.dispose(self.session), [])
        self.assertEqual(_qt.take_qt_messages(), [], "avisos de Qt durante la prueba")

    def open(self, session: Session | None = None):
        session = session or self.session
        session.open_project(self.layers.game_root, self.layers.mod_root)
        self.assertTrue(_qt.wait_until(lambda: not session.is_busy(), 5000), "la apertura no terminó")
        return session.project


class OpenTests(SessionCase):
    def test_opens_in_the_background_and_binds_to_the_interface_thread(self):
        self.session.open_project(self.layers.game_root, self.layers.mod_root)
        self.assertTrue(self.session.is_busy())
        self.assertIsNone(self.session.project)
        self.assertEqual(self.session.target, (self.layers.game_root, self.layers.mod_root))
        self.assertTrue(_qt.wait_until(lambda: self.session.project is not None, 5000))
        self.assertFalse(self.session.is_busy())
        self.assertNotEqual(self.opener.threads, [threading.get_ident()], "se abrió en el hilo de la interfaz")
        project = self.session.project
        self.assertEqual(self.opener.calls, [(self.layers.game_root, self.layers.mod_root)])
        # El falso, como el real, solo admite el hilo dueño: si la sesión no lo ata, esto lanza WrongThreadError.
        self.assertEqual(self.session.dirty_count(), 0)
        self.assertEqual(self.events.names()[:2], ["projectOpening", "projectOpened"])
        self.assertIs(self.events.of("projectOpened")[0][0], project)
        self.assertEqual(self.events.of("dirtyChanged"), [(0,)])

    def test_failure_is_reported_without_a_project(self):
        self.opener.error = OSError(13, "Permission denied", "/x/VSM")
        self.session.open_project(None, self.layers.mod_root)
        self.assertTrue(_qt.wait_until(lambda: not self.session.is_busy(), 5000))
        self.assertIsNone(self.session.project)
        self.assertIsNone(self.session.target)
        ((key, fmt),) = self.events.of("projectOpenFailed")
        self.assertEqual(key, OPEN_FAILED)
        self.assertEqual(fmt, {"error": "Permission denied: /x/VSM"})
        self.opener.error = NotImplementedError()
        self.session.open_project(None, self.layers.mod_root)
        self.assertTrue(_qt.wait_until(lambda: not self.session.is_busy(), 5000))
        self.assertEqual(self.events.of("projectOpenFailed")[-1][1], {"error": "NotImplementedError"})

    def test_a_superseded_opening_is_closed_and_not_adopted(self):
        gate = threading.Event()
        self.opener.gate = gate
        self.session.open_project(self.layers.game_root, self.layers.mod_root)
        first_target = self.session.target
        self.opener.gate = None
        other = build_layers(game=GAME, mod_name="Otro")
        self.addCleanup(other.cleanup)
        # Abrir otro mientras el primero espera: el primero se cancela.
        self.session.open_project(other.game_root, other.mod_root)
        self.assertTrue(_qt.wait_until(lambda: self.session.project is not None, 5000))
        self.assertEqual(self.session.project.mod_root, other.mod_root)
        gate.set()
        self.assertTrue(wait_for_tasks(5000))
        _qt.process_events(50)
        self.assertEqual(len(self.events.of("projectOpened")), 1)
        self.assertEqual(self.session.project.mod_root, other.mod_root)
        self.assertNotEqual(first_target, self.session.target)

    def test_closing_cancels_the_opening(self):
        self.opener.gate = threading.Event()  # nunca se abre: la apertura espera hasta que la cancelen
        self.session.open_project(self.layers.game_root, self.layers.mod_root)
        self.session.close_project()
        self.assertIn("projectClosed", self.events.names())
        self.assertFalse(self.session.is_busy())
        self.assertIsNone(self.session.target)
        self.assertTrue(wait_for_tasks(5000), "la apertura no vio la cancelación")
        _qt.process_events(50)
        self.assertIsNone(self.session.project)
        self.assertEqual(self.events.of("projectOpened"), [])
        self.assertEqual(self.opener.projects, [])

    def test_late_project_is_disposed(self):
        """La apertura vieja que sí construye su proyecto lo entrega tarde: se cierra (suelta el bloqueo)."""
        release = threading.Event()

        def slow_opener(game, mod, **kwargs):
            release.wait(5)
            return FakeOpener()(game, mod)

        session = Session(opener=slow_opener)
        self.addCleanup(lambda: (session.close_project(), wait_for_tasks(5000), _qt.dispose(session)))
        opened = []
        session.projectOpened.connect(opened.append)
        session.open_project(self.layers.game_root, self.layers.mod_root)
        with mock.patch.object(Session, "_dispose", wraps=Session._dispose) as dispose:
            session.close_project()
            release.set()
            self.assertTrue(wait_for_tasks(5000))
            self.assertTrue(_qt.wait_until(lambda: dispose.called, 5000), "el proyecto tardío no se cerró")
            project = dispose.call_args.args[0]
        self.assertTrue(project.closed)
        self.assertEqual(opened, [])

    def test_orphan_sessions_are_offered(self):
        self.opener.options = {"orphan_sessions": ["s-1"], "recovered": [recovered_result()]}
        project = self.open()
        self.assertEqual(self.events.of("recoveryAvailable"), [(["s-1"],)])
        self.assertEqual(len(project.recovered), 1)

    def test_close_project_closes_and_reports(self):
        project = self.open()
        self.events.clear()
        self.session.close_project()
        self.assertTrue(project.closed)
        self.assertIsNone(self.session.project)
        self.assertEqual(self.events.names(), ["projectClosed", "dirtyChanged", "undoChanged"])
        self.events.clear()
        self.session.close_project()
        self.assertEqual(self.events.names(), [], "sin proyecto, cerrar no avisa")


class EditTests(SessionCase):
    def test_edit_emits_once_at_the_end(self):
        project = self.open()
        self.events.clear()
        with self.session.edit("descriptor.undo_edit", field="name"):
            handle = project.ws.open("common/countries.txt")
            project.ws.touch(handle)
            handle.model.document.append("CCC", Scalar("countries/Cimbria.txt", quoted=True))
            with self.session.edit("descriptor.undo_edit", field="nested"):
                project.ws.touch(handle)
            self.assertEqual(self.events.names(), [], "nada se emite a mitad de la operación")
        self.assertEqual(self.events.names(), ["documentsChanged", "dirtyChanged", "undoChanged"])
        self.assertEqual({str(r) for r in self.events.of("documentsChanged")[0][0]}, {"common/countries.txt"})
        self.assertEqual(self.events.of("dirtyChanged"), [(1,)])
        self.assertEqual(self.session.history(), [("descriptor.undo_edit", {"field": "name"})])

    def test_a_failed_edit_rolls_back_and_still_reports(self):
        project = self.open()
        self.events.clear()
        with self.assertRaises(ValueError):
            with self.session.edit("descriptor.undo_edit", field="x"):
                handle = project.ws.open("common/countries.txt")
                project.ws.touch(handle)
                raise ValueError("fallo")
        self.assertEqual(self.session.dirty_count(), 0)
        self.assertEqual(self.events.of("dirtyChanged"), [])
        self.assertIn("undoChanged", self.events.names())

    def test_undo_and_redo(self):
        project = self.open()
        with self.session.edit("descriptor.undo_edit", field="name"):
            handle = project.ws.open("common/countries.txt")
            project.ws.touch(handle)
        self.events.clear()
        step = self.session.undo()
        self.assertEqual(step.label, "descriptor.undo_edit")
        self.assertEqual(self.session.dirty_count(), 0)
        self.assertEqual(self.events.of("dirtyChanged"), [(0,)])
        self.assertTrue(self.session.can_redo())
        self.assertFalse(self.session.can_undo())
        self.session.redo()
        self.assertEqual(self.session.dirty_count(), 1)
        self.assertIsNone(Session(opener=self.opener).undo(), "sin proyecto no hay nada que deshacer")

    def test_edit_without_a_project_raises(self):
        with self.assertRaises(RuntimeError):
            with self.session.edit("descriptor.undo_edit", field="x"):
                pass

    def test_events_outside_an_operation_arrive_on_the_next_loop(self):
        project = self.open()
        handle = project.ws.open(DESCRIPTOR_REL)
        self.events.clear()
        project.ws._emit(DocReplaced(handle.rel))  # p. ej. un autoguardado o una recarga que no pasa por la sesión
        self.assertEqual(self.events.names(), [])
        _qt.process_events(20)
        self.assertEqual(self.events.names()[0], "documentsChanged")


class SaveTests(SessionCase):
    def test_save_writes_and_reports(self):
        project = self.open()
        with self.session.edit("descriptor.undo_edit", field="cb"):
            handle = project.ws.open("common/cb_types.txt")
            project.ws.touch(handle)
            handle.model.document.append("my_cb", Scalar("1"))
        self.assertEqual(self.session.changeset().copies_from_game, 1)
        self.events.clear()
        report = self.session.save()
        self.assertTrue(report.ok)
        self.assertEqual(self.events.names(), ["documentsChanged", "dirtyChanged", "undoChanged", "saved"])
        self.assertTrue((self.layers.mod_root / "common" / "cb_types.txt").is_file())
        self.assertEqual(self.layers.game("common/cb_types.txt").read_bytes(), b"peace_order = { }\r\n")

    def test_a_conflict_blocks_the_save(self):
        project = self.open()
        with self.session.edit("descriptor.undo_edit", field="countries"):
            handle = project.ws.open("common/countries.txt")
            project.ws.touch(handle)
            handle.model.document.append("CCC", Scalar("x"))
        self.layers.mod("common/countries.txt").write_bytes(b"CAMBIADO = 1\r\n")
        self.events.clear()
        report = self.session.save()
        self.assertFalse(report.ok)
        self.assertEqual(self.events.of("saveBlocked"), [(report,)])
        self.assertEqual(self.layers.mod("common/countries.txt").read_bytes(), b"CAMBIADO = 1\r\n")
        self.session.check_external_changes()
        ((changes,),) = self.events.of("externalChanges")
        self.assertEqual([(str(c.rel), c.kind, c.dirty) for c in changes], [("common/countries.txt", "modified", True)])
        self.assertIn("CAMBIADO", self.session.external_diff(changes[0].rel))
        self.session.accept_external(changes[0].rel)
        self.assertTrue(self.session.save().ok, "«Conservar mis cambios» permite sobrescribir")

    def test_reload_discards_memory(self):
        project = self.open()
        with self.session.edit("descriptor.undo_edit", field="countries"):
            handle = project.ws.open("common/countries.txt")
            project.ws.touch(handle)
        self.session.reload(handle.rel)
        self.assertEqual(self.session.dirty_count(), 0)


class RecoveryTests(SessionCase):
    def test_write_recovery_only_with_changes(self):
        project = self.open()
        self.session.write_recovery()
        self.assertEqual(project.ws.recovery_writes, 0, "sin cambios no se escribe nada")
        with self.session.edit("descriptor.undo_edit", field="x"):
            handle = project.ws.open("common/countries.txt")
            project.ws.touch(handle)
        self.session.write_recovery()
        self.assertEqual(project.ws.recovery_writes, 1)
        self.assertEqual(self.session._autosave.interval(), Workspace.AUTOSAVE_SECONDS * 1000)
        self.assertTrue(self.session._autosave.isActive())

    def test_every_n_transactions_writes_the_recovery(self):
        project = self.open()
        handle = project.ws.open("common/countries.txt")
        for _ in range(Workspace.AUTOSAVE_TRANSACTIONS - 1):
            with self.session.edit("descriptor.undo_edit", field="x"):
                project.ws.touch(handle)
        self.assertEqual(project.ws.recovery_writes, 0)
        with self.session.edit("descriptor.undo_edit", field="x"):
            project.ws.touch(handle)
        self.assertEqual(project.ws.recovery_writes, 1)

    def test_restore_and_discard_sessions(self):
        self.opener.options = {"orphan_sessions": ["s-1", "s-2"],
                               "sessions": {"s-1": {"common/countries.txt": b"RESTAURADO = 1\r\n"}}}
        project = self.open()
        restored = self.session.restore_session("s-1")
        self.assertEqual([str(r) for r in restored], ["common/countries.txt"])
        self.assertEqual(self.session.dirty_count(), 1)
        with mock.patch("vic2studio.core.project.journal.clear_recovery") as clear:
            self.session.discard_recovery("s-2")
        clear.assert_called_once()
        self.assertEqual(clear.call_args.args[2], "s-2")
        self.assertEqual(project.orphan_sessions, [])


class CreateModTests(SessionCase):
    def test_create_mod_in_the_background(self):
        calls = []

        def creator(game, spec, template=None):
            calls.append((game, spec, template, threading.get_ident()))
            return spec.fields(game / "mod" / f"{spec.folder}.mod")

        session = Session(opener=self.opener, creator=creator)
        self.addCleanup(lambda: (wait_for_tasks(5000), _qt.dispose(session)))
        created, failed = [], []
        session.modCreated.connect(created.append)
        session.modCreateFailed.connect(lambda key, fmt: failed.append((key, fmt)))
        session.create_mod(self.layers.game_root, DescriptorSpec("Dark Age Mod", "DAM", "DAM"))
        self.assertTrue(session.is_creating())
        self.assertTrue(_qt.wait_until(lambda: created, 5000))
        self.assertEqual(created[0].path, "mod/DAM")
        self.assertNotEqual(calls[0][3], threading.get_ident())
        session._creator = mock.Mock(side_effect=ValueError("carpeta ocupada"))
        session.create_mod(self.layers.game_root, DescriptorSpec("Dark Age Mod", "DAM", "DAM"))
        self.assertTrue(_qt.wait_until(lambda: failed, 5000))
        self.assertEqual(failed[0][1], {"error": "ValueError: carpeta ocupada"})

    def test_working_date(self):
        from vic2studio.core.clausewitz import ClausewitzDate

        self.session.set_working_date(ClausewitzDate(1861, 1, 1))
        self.session.set_working_date(ClausewitzDate(1861, 1, 1))
        self.assertEqual(self.events.of("workingDateChanged"), [(ClausewitzDate(1861, 1, 1),)])


if __name__ == "__main__":
    unittest.main()
