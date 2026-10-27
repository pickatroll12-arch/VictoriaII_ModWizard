"""``Session``: el puente entre el proyecto y Qt (wizard §6.4, D2, I12), contra el ``Project`` falso.

Abrir va en segundo plano y entrega el proyecto atado al hilo de la interfaz; las ediciones, el guardado, el
deshacer y la recuperación emiten sus señales una vez por operación; una apertura que llega tarde (porque
se pidió otra o se cerró) no se adopta y se cierra para soltar el bloqueo.
"""

import sys
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
        fake = FakeOpener()

        def slow_opener(game, mod, **kwargs):
            release.wait(5)
            return fake(game, mod)

        session = Session(opener=slow_opener)
        self.addCleanup(lambda: (session.close_project(), wait_for_tasks(5000), _qt.dispose(session)))
        opened = []
        session.projectOpened.connect(opened.append)
        session.open_project(self.layers.game_root, self.layers.mod_root)
        session.close_project()
        release.set()
        self.assertTrue(wait_for_tasks(5000))
        self.assertTrue(_qt.wait_until(lambda: fake.projects and fake.projects[0].closed, 5000),
                        "el proyecto tardío no se cerró")
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

    def test_closing_keeps_the_recovery_unless_the_changes_are_discarded(self):
        for discard in (False, True):
            with self.subTest(discard=discard):
                project = self.open()
                with self.session.edit("descriptor.undo_edit", field="x"):
                    project.ws.touch(project.ws.open("common/countries.txt"))
                self.session.close_project(discard=discard)
                self.assertTrue(project.closed)
                self.assertIs(project.closed_with_discard, discard)
                self.assertEqual(project.ws.recovery_finals, 0 if discard else 1)


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
        with mock.patch.object(project.ws, "write_recovery", wraps=project.ws.write_recovery) as write:
            self.session.write_recovery()
        write.assert_called_once_with()   # sin cambios también: el núcleo borra entonces el autoguardado anterior
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
        self.session.discard_recovery("s-2")
        self.assertEqual(project.discarded_sessions, ["s-2"], "lo borra el núcleo (Project.discard_session)")
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


# --- iteración 3: índice, textos y validación (contra el Project real, con los motores falsos) ---------------


class ServicesCase(unittest.TestCase):
    """La sesión con el minijuego abierto con ``Project.open`` y los motores de ``_fake_index``."""

    def setUp(self):
        from _fake_index import fake_engines
        from _layers import isolate_appdirs
        from _minigame import build_minigame
        from test_locsync import only_minigame_csv

        from vic2studio.i18n import language, set_language

        _qt.take_qt_messages()
        isolate_appdirs(self)
        self.addCleanup(set_language, language())
        set_language("es")   # la columna de la localización que se busca es la del idioma de la interfaz
        self.game = build_minigame(game_files=only_minigame_csv(),
                                   mod_files={"history/countries/SIL - Silesia.txt": "capital = 1\r\n",
                                              "localisation/00_TESTMOD_countries.csv": "AAA;Åland;;;;Álandia;;;;;;;;x\r\n"})
        self.addCleanup(self.game.cleanup)
        self.engines = self.make_engines(fake_engines)
        self.session = Session(**self.engines)
        self.symbols: list[set] = []
        self.session.symbolsChanged.connect(lambda kinds: self.symbols.append(set(kinds)))

    def make_engines(self, fake_engines):
        return fake_engines()

    def tearDown(self):
        self.session.close_project()
        self.assertTrue(wait_for_tasks(10000))
        self.assertEqual(_qt.dispose(self.session), [])
        self.assertEqual(_qt.take_qt_messages(), [])

    def open(self, *, wait_index: bool = True):
        self.session.open_project(self.game.game_root, self.game.mod_root)
        self.assertTrue(_qt.wait_until(lambda: self.session.project is not None, 5000))
        if wait_index:
            self.assertTrue(_qt.wait_until(lambda: self.session.index is not None and self.session.texts_ready()
                                           and not self.session.is_working(), 5000))
        return self.session.project

    def edit_countries(self, text: bytes):
        project = self.session.project
        with self.session.edit("pending.undo_revert", name="common/countries.txt"):
            project.ws.replace_text(project.ws.open("common/countries.txt"), text)


class IndexSessionTests(ServicesCase):
    def test_the_index_is_built_in_the_background_on_open_with_the_snapshot(self):
        self.open()
        session = self.session
        self.assertEqual(session.index_state(), "ready")
        ((snapshot, overrides),) = self.engines["index"].builds
        self.assertIn("COMMON/COUNTRIES.TXT", snapshot.entries)
        self.assertEqual(overrides, {})
        self.assertTrue({"tag", "loc_key", "country_history"} <= self.symbols[-1], self.symbols)
        self.assertEqual(session.index.names("tag"), ["AAA", "BBB", "CCC", "D01"])

    def test_a_change_is_reextracted_300_ms_later_and_applied_in_the_interface_thread(self):
        import time

        from vic2studio.core.vfs import LayerKind, VPath

        self.open()
        session, index = self.session, self.session.index
        self.symbols.clear()
        started = time.monotonic()
        self.edit_countries(b'AAA = "countries/Aland.txt"\r\nZZZ = "countries/Z.txt"\r\ndynamic_tags = yes\r\n')
        self.edit_countries(b'AAA = "countries/Aland.txt"\r\nZZZ = "countries/Z.txt"\r\nYYY = "c/Y.txt"\r\n')
        self.assertEqual(self.engines["index"].extracted, [], "nada antes de la espera")
        self.assertTrue(_qt.wait_until(lambda: index.applied, 3000), "no se reextrajo")
        # 300 ms tras la última edición; los temporizadores «coarse» de Qt pueden adelantarse un 5 %.
        self.assertGreaterEqual(time.monotonic() - started, 0.28)
        self.assertEqual(self.engines["index"].extracted, [(VPath.of("common/countries.txt"), LayerKind.MOD)],
                         "las dos ediciones seguidas se reextraen una sola vez")
        self.assertIs(session.index, index, "incremental: el mismo índice")
        self.assertEqual(index.names("tag"), ["AAA", "ZZZ", "YYY"])
        self.assertIn("tag", self.symbols[-1])
        session.undo()
        session.undo()
        self.assertTrue(_qt.wait_until(lambda: len(index.applied) == 2, 3000))
        self.assertEqual(index.applied[-1][1], [(VPath.of("common/countries.txt"), LayerKind.MOD)],
                         "deshecho, vuelve a contar el del juego")
        self.assertEqual(index.names("tag"), ["AAA", "BBB", "CCC", "D01"])

    def test_changes_made_while_building_are_reextracted_afterwards(self):
        import threading as _threading

        from _fake_index import fake_engines

        gate = _threading.Event()
        self.addCleanup(gate.set)
        self.session.close_project()
        self.engines = fake_engines(index={"gate": gate})
        self.session = Session(**self.engines)
        self.open(wait_index=False)
        self.assertTrue(_qt.wait_until(lambda: self.engines["index"].started.is_set(), 3000))
        self.edit_countries(b'AAA = "countries/Aland.txt"\r\nNEW = "countries/New.txt"\r\n')
        _qt.process_events(400)
        self.assertEqual(self.engines["index"].extracted, [], "con el índice a medias no se reextrae todavía")
        gate.set()
        self.assertTrue(_qt.wait_until(lambda: self.session.index is not None
                                       and "NEW" in self.session.index.names("tag"), 5000))

    def test_search_and_display_use_the_effective_localisation(self):
        self.open()
        found = [(s.kind, s.name) for s in self.session.search("alandia")]
        self.assertIn(("tag", "AAA"), found)
        tag = next(s for s in self.session.search("AAA") if s.kind == "tag")
        self.assertEqual(self.session.display(tag), "Álandia (AAA)")
        self.assertEqual(self.session.search("   "), [])

    def test_closing_forgets_the_index_the_texts_and_the_report(self):
        self.open()
        self.session.validate()
        self.assertTrue(_qt.wait_until(lambda: self.session.report is not None, 5000))
        changed = []
        self.session.problemsChanged.connect(lambda: changed.append("problems"))
        self.session.textsChanged.connect(lambda: changed.append("texts"))
        self.session.close_project()
        self.assertIsNone(self.session.index)
        self.assertIsNone(self.session.locsync)
        self.assertIsNone(self.session.report)
        self.assertEqual(self.session.index_state(), "idle")
        self.assertEqual(changed, ["problems", "texts"])
        self.assertEqual(self.symbols[-1], set())


class TextsSessionTests(ServicesCase):
    def test_texts_are_read_in_the_background_and_announced(self):
        ready = []
        self.session.textsReady.connect(lambda: ready.append(True))
        self.open()
        self.assertEqual(ready, [True])
        locsync = self.session.locsync
        self.assertEqual(locsync.prefix, "TESTMOD")
        self.assertEqual(locsync.disk_entries(), [], "ya está todo leído")
        self.assertEqual(locsync.text("AAA", "es"), "Álandia")

    def test_a_text_edit_announces_texts_changed_and_settings_reach_locsync(self):
        import dataclasses

        project = self.open()
        changed = []
        self.session.textsChanged.connect(lambda: changed.append(True))
        with self.session.edit("pending.undo_revert", name="x"):
            self.session.locsync.set_text("AAA", "es", "Alandia")
        self.assertEqual(changed, [True])
        project.set_settings(dataclasses.replace(project.settings, prefix="NEWP", copy_en_to=("fr",)))
        self.session._flush()
        self.assertEqual((self.session.locsync.prefix, self.session.locsync.copy_en_to), ("NEWP", ("fr",)))


class ValidationSessionTests(ServicesCase):
    def test_validation_gets_a_copy_of_the_index_the_overrides_and_the_baseline(self):
        from vic2studio.core.vfs import VPath

        project = self.open()
        sil = "history/countries/SIL - Silesia.txt"
        with self.session.edit("pending.undo_revert", name=sil):
            project.ws.replace_text(project.ws.open(sil), b"capital = 2\r\n")
        self.assertTrue(self.session.validate())
        self.assertTrue(_qt.wait_until(lambda: self.session.validation_state() == "ready", 5000))
        context = self.session.validation_context
        self.assertIsNot(context.index, self.session.index, "el hilo de la validación trabaja con una copia")
        self.assertEqual(sorted(f.rel for f in context.index.facts()), sorted(f.rel for f in self.session.index.facts()))
        self.assertEqual(list(context.overrides), [VPath.of(sil)], "los bytes de lo que está sin guardar")
        self.assertTrue(self.session.report.baseline_ready)
        self.assertEqual(self.engines["baseline"].computed, 1)
        self.assertEqual([p.code for p in self.session.problems()], ["tag_not_registered"])
        self.assertEqual(len(self.session.problems(inherited=True)), 3, "más los nombres que ya faltan en el juego")

    def test_the_baseline_follows_the_working_date_and_the_context_gets_the_languages(self):
        """Integración de la revisión it3: la línea base mira las historias a la fecha de trabajo (baseline_for con
        date=) y loc_untranslated, los idiomas del proyecto; la sesión seguía con la base sin fecha ni dependencias."""
        import dataclasses

        from vic2studio.core.clausewitz.nodes import ClausewitzDate

        project = self.open()
        project.set_settings(dataclasses.replace(project.settings, languages=("en", "es", "fr")))
        self.session._flush()
        baseline = self.engines["baseline"]

        def validate():
            runs = self.engines["validation"].validations
            self.assertTrue(self.session.validate())
            self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].validations == runs + 1
                                           and self.session.validation_state() == "ready", 5000))

        validate()
        start = self.session.working_date
        self.assertEqual(baseline.dates, [start])
        self.assertEqual(self.engines["validation"].languages, ("en", "es", "fr"))
        validate()
        self.assertEqual(baseline.dates, [start], "la misma fecha: la de antes vale")
        self.session.set_working_date(ClausewitzDate(1861, 1, 1))
        validate()
        self.assertEqual(baseline.dates, [start, ClausewitzDate(1861, 1, 1)], "otra fecha: otra línea base")
        self.assertTrue(self.session.report.baseline_ready)

    def test_the_real_engines_pass_the_date_and_the_languages_to_the_core(self):
        from unittest import mock

        from vic2studio.core.clausewitz.nodes import ClausewitzDate
        from vic2studio.core.index import build_index
        from vic2studio.ui.session import BaselineEngine, ValidationEngine

        project = self.open()
        snapshot = project.vfs.snapshot()
        context = ValidationEngine().context(snapshot, build_index(snapshot, None), {}, languages=["en", "fr"])
        self.assertEqual(context.languages, ("en", "fr"))
        date = ClausewitzDate(1861, 1, 1)
        with mock.patch("vic2studio.core.validate.baseline_for", return_value=frozenset({"x"})) as baseline_for:
            self.assertEqual(BaselineEngine().compute(snapshot, date=date), frozenset({"x"}))
        baseline_for.assert_called_once_with(snapshot, date=date, cancelled=None)

    def test_apply_fix_revalidates_once_the_index_is_up_to_date(self):
        self.open()
        self.session.validate()
        self.assertTrue(_qt.wait_until(lambda: self.session.validation_state() == "ready", 5000))
        sil = self.session.problems()[0]
        plan = self.session.plan_fix("register_tag", sil)
        self.assertEqual(self.session.history(), [], "el plan no deja nada en la pila de deshacer")
        self.assertEqual([str(c.rel) for c in plan.changes], ["common/countries.txt"])
        self.session.apply_fix("register_tag", sil)
        self.assertEqual(self.session.validation_state(), "ready", "espera al índice antes de revalidar")
        self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].validations == 2
                                       and self.session.validation_state() == "ready", 5000))
        self.assertIn("SIL", self.session.index.names("tag"))
        self.assertEqual([p.code for p in self.session.problems()], ["loc_key_missing"],
                         "SIL ya está registrado (y ahora le falta su nombre)")

    def test_validating_right_after_ctrl_z_waits_for_the_index(self):
        """Regresión de la integración: F7 justo tras deshacer validaba con el índice de antes (SIL seguía
        registrado y salían los problemas del arreglo deshecho)."""
        self.open()
        self.session.validate()
        self.assertTrue(_qt.wait_until(lambda: self.session.validation_state() == "ready", 5000))
        sil = self.session.problems()[0]
        self.session.apply_fix("register_tag", sil)
        self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].validations == 2
                                       and self.session.validation_state() == "ready", 5000))
        self.assertIn("SIL", self.session.index.names("tag"))
        self.session.undo()
        self.assertTrue(self.session.validate())
        self.assertEqual(self.session.validation_state(), "waiting", "el índice aún no tiene el Ctrl+Z")
        self.assertFalse(self.session._reindex_timer.isActive(), "reindexa ya, sin esperar REINDEX_DELAY_MS")
        self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].validations == 3
                                       and self.session.validation_state() == "ready", 5000))
        self.assertNotIn("SIL", self.session.index.names("tag"))
        self.assertEqual([p.code for p in self.session.problems()], ["tag_not_registered"])

    def test_an_edit_made_outside_the_session_is_indexed_before_validating(self):
        """Una transacción del Workspace sin ``Session.edit`` (sus eventos esperan al temporizador de aviso): F7 los
        recoge antes de decidir si el índice está al día."""
        project = self.open()
        self.session.validate()
        self.assertTrue(_qt.wait_until(lambda: self.session.validation_state() == "ready", 5000))
        self.assertEqual([p.code for p in self.session.problems()], ["tag_not_registered"])
        with project.ws.transaction("undo.fix_register_tag"):
            handle = project.ws.open("common/countries.txt")
            project.ws.replace_text(handle, project.ws.vfs.resolve("common/countries.txt").path.read_bytes()
                                    + b'SIL = "countries/Silesia.txt"\r\n')
        self.assertTrue(self.session.validate())
        self.assertEqual(self.session.validation_state(), "waiting")
        self.assertTrue(_qt.wait_until(lambda: self.engines["validation"].validations == 2
                                       and self.session.validation_state() == "ready", 5000))
        self.assertIn("SIL", self.session.index.names("tag"))
        self.assertNotIn("tag_not_registered", [p.code for p in self.session.problems()])

    def test_an_unsaved_deletion_reaches_the_index_and_the_validator_as_none(self):
        from vic2studio.core.vfs import VPath
        from vic2studio.ui.session import document_overrides

        project = self.open()
        sil = "history/countries/SIL - Silesia.txt"
        with self.session.edit("pending.undo_revert", name=sil):
            project.ws.delete(sil)
        self.assertEqual(document_overrides(project), {VPath.of(sil): None})
        self.assertTrue(self.session.validate())
        self.assertTrue(_qt.wait_until(lambda: self.session.validation_state() == "ready", 5000))
        self.assertEqual(dict(self.session.validation_context.overrides), {VPath.of(sil): None})
        self.assertNotIn("tag_not_registered", [p.code for p in self.session.problems()], "ya no hay historia")

    def test_explain_and_fixes_need_a_report(self):
        self.open()
        from _fake_index import problem

        sil = problem("tag_not_registered", "history/countries/SIL - Silesia.txt", 1, tag="SIL")
        self.assertIsNone(self.session.explain(sil))
        self.assertEqual([f.key for f in self.session.fixes_for(sil)], ["register_tag"])


if __name__ == "__main__":
    unittest.main()
