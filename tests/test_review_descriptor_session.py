"""Pruebas de regresión de la revisión adversarial (iteración 2): core/modfile.py y ui/session.py con el Project real."""

import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS.parent / "src"))

import _qt  # noqa: E402

APP = _qt.application()

from _layers import build_layers, isolate_appdirs  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402

from vic2studio.core.cancel import raise_if_cancelled  # noqa: E402
from vic2studio.core.clausewitz import Severity  # noqa: E402
from vic2studio.core.modfile import DescriptorSpec, create_mod_skeleton, descriptor_problems  # noqa: E402
from vic2studio.core.project import Project, journal  # noqa: E402
from vic2studio.core.vfs.vfs import VirtualFS  # noqa: E402
from vic2studio.i18n import N_, language, set_language  # noqa: E402
from vic2studio.ui.session import Session  # noqa: E402
from vic2studio.ui.tasks import wait_for_tasks  # noqa: E402


def wait_idle(session: Session, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while session.is_busy() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    wait_for_tasks()
    QCoreApplication.processEvents()


class _Boom(Exception):
    pass


class SkeletonAllOrNothingTests(unittest.TestCase):
    """create_mod_skeleton interrumpido al confirmar: no debe quedar nada en <juego>/mod (I2, §14.1)."""

    def setUp(self):
        isolate_appdirs(self)

    def game(self) -> Path:
        game = Path(tempfile.mkdtemp()) / "game"
        (game / "mod").mkdir(parents=True)
        (game / "v2game.exe").write_bytes(b"MZ")
        template = game.parent / "Plantilla"
        (template / "common").mkdir(parents=True)
        (template / "common" / "a.txt").write_bytes(b"a = 1\r\n")
        return game

    def test_a_failure_while_replacing_leaves_nothing(self):
        spec = DescriptorSpec("Dark Age Mod", "DAM", "DAM")
        for index in (0, 1):
            with self.subTest(index=index):
                game = self.game()

                def hook(step, i, index=index):
                    if step == "replace" and i == index:
                        raise _Boom()
                with mock.patch.object(journal, "FAULT_HOOK", hook), self.assertRaises(_Boom):
                    create_mod_skeleton(game, spec, template=game.parent / "Plantilla")
                self.assertEqual(sorted(p.name for p in (game / "mod").iterdir()), [])
                errors = [i.code for i in descriptor_problems(spec, game, creating=True)
                          if i.severity is Severity.ERROR]
                self.assertEqual(errors, [], "se puede volver a intentar con la misma carpeta")

    def test_a_failure_after_committing_is_not_reported_as_a_failure(self):
        game = self.game()
        real = journal._guarded_write

        def full_disk(guard, path, data):
            if b'"state": "committed"' in data:
                raise OSError(28, "No space left on device", str(path))
            return real(guard, path, data)

        with mock.patch.object(journal, "_guarded_write", full_disk):
            descriptor = create_mod_skeleton(game, DescriptorSpec("Dark Age Mod", "DAM", "DAM"))
        self.assertEqual(descriptor.name, "Dark Age Mod")
        self.assertTrue((game / "mod" / "DAM.mod").is_file())
        self.assertFalse((game / "mod" / "DAM" / ".vic2studio").exists(), "el diario ya se cerró")


class UnencodableDescriptorTests(unittest.TestCase):
    """Un valor que cp1252 no admite es un error del formulario, no un fallo tardío (I9)."""

    def test_descriptor_problems_reports_a_name_cp1252_cannot_write(self):
        base = Path(tempfile.mkdtemp())
        (base / "mod").mkdir()
        for spec in (DescriptorSpec("Mod 日本", "MJ", "MJ"), DescriptorSpec("Mod", "MJ", "MJ", (), ("Otro 日本",))):
            with self.subTest(spec=spec):
                errors = [i for i in descriptor_problems(spec, base, creating=True) if i.severity is Severity.ERROR]
                self.assertTrue(errors, "render_descriptor lanzaría UnencodableTextError")


class ListFieldsKeepTheFileTests(unittest.TestCase):
    """replace_path y dependencies: cambiar otra cosa (o una sola entrada) no mueve ni borra las demás (I3, §14.1)."""

    SRC = ('name = "Victorian Spirit"\r\npath = "mod/VSM"\r\nuser_dir = "VSM"\r\n'
           '# primero las pops\r\nreplace_path = "history/pops"\r\n'
           'replace_path = "history/countries" # los paises\r\n'
           'dependencies = {\r\n\t"Base Mod" # imprescindible\r\n\t"Otro" # opcional\r\n}\r\narchive = "vsm.zip"\r\n')

    def document(self):
        from vic2studio.core.clausewitz import parse
        return parse(self.SRC).document

    def test_renaming_with_the_form_order_only_changes_the_name(self):
        from vic2studio.core.clausewitz import to_source
        from vic2studio.core.modfile import apply_descriptor
        doc = self.document()
        # El formulario da las casillas en su orden (alfabético), no en el del archivo.
        spec = DescriptorSpec("Shago Mod", "VSM", "VSM", ("history/countries", "history/pops"), ("Base Mod", "Otro"))
        self.assertTrue(apply_descriptor(doc, spec))
        self.assertEqual(to_source(doc), self.SRC.replace("Victorian Spirit", "Shago Mod"))

    def test_removing_a_dependency_keeps_the_other_comment(self):
        from vic2studio.core.clausewitz import to_source
        from vic2studio.core.modfile import apply_descriptor
        doc = self.document()
        spec = DescriptorSpec("Victorian Spirit", "VSM", "VSM", ("history/pops", "history/countries"), ("Base Mod",))
        self.assertTrue(apply_descriptor(doc, spec))
        self.assertIn('"Base Mod" # imprescindible', to_source(doc))
        self.assertNotIn("Otro", to_source(doc))

    def test_adding_a_replace_path_goes_next_to_the_others(self):
        from vic2studio.core.clausewitz import to_source
        from vic2studio.core.modfile import apply_descriptor
        doc = self.document()
        spec = DescriptorSpec("Victorian Spirit", "VSM", "VSM", ("common", "history/countries", "history/pops"),
                              ("Base Mod", "Otro"))
        self.assertTrue(apply_descriptor(doc, spec))
        self.assertIn('replace_path = "history/countries" # los paises\r\nreplace_path = "common"\r\n',
                      to_source(doc))


class UserDirWindowsNameTests(unittest.TestCase):
    """user_dir es una carpeta de Documentos: la misma regla de Windows que la carpeta del mod."""

    def test_a_reserved_user_dir_is_an_error(self):
        base = Path(tempfile.mkdtemp())
        (base / "mod").mkdir()
        for user_dir in ("CON", "nul.txt", "Saves."):
            with self.subTest(user_dir=user_dir):
                errors = [i for i in descriptor_problems(DescriptorSpec("X", "DAM", user_dir), base, creating=True)
                          if i.severity is Severity.ERROR]
                self.assertTrue(errors)


class CreateFailedLanguageTests(unittest.TestCase):
    """El motivo de modCreateFailed sigue el idioma de la interfaz (P3)."""

    def setUp(self):
        isolate_appdirs(self)
        previous = language()
        self.addCleanup(set_language, previous)

    def test_the_reason_is_in_english_with_the_english_interface(self):
        base = Path(tempfile.mkdtemp())
        game = base / "game"
        (game / "mod").mkdir(parents=True)
        (game / "v2game.exe").write_bytes(b"MZ")
        template = base / "Plantilla"
        (template / "common").mkdir(parents=True)
        (template / "common" / "aux.txt").write_bytes(b"a = 1\r\n")
        set_language("en")
        session = Session()
        failed = []
        session.modCreateFailed.connect(lambda key, fmt: failed.append(dict(fmt)))
        session.create_mod(game, DescriptorSpec("Dark Age Mod", "DAM", "DAM"), template)
        wait_idle(session)
        self.assertEqual(len(failed), 1)
        self.assertNotIn("No se guarda", failed[0]["error"])
        self.assertNotIn("Error:", failed[0]["error"].split(" ", 1)[0], "sin el nombre de la clase")


class ReopenWhileOpeningTests(unittest.TestCase):
    """Reabrir el mismo mod (otra carpeta de juego) mientras la apertura anterior aún escanea."""

    def setUp(self):
        isolate_appdirs(self)
        self.layers = build_layers(game={"common/x.txt": "a = 1\r\n"}, mod={"common/x.txt": "a = 2\r\n"})
        self.other = build_layers(game={"common/x.txt": "a = 1\r\n"}, mod={}, mod_name="Other")
        self.addCleanup(self.layers.cleanup)
        self.addCleanup(self.other.cleanup)

    def test_the_new_project_is_writable(self):
        real_scan = VirtualFS.scan

        def slow_scan(vfs, *, progress=None, cancelled=None):
            for _ in range(40):          # disco lento: 0,4 s comprobando la cancelación
                raise_if_cancelled(cancelled)
                time.sleep(0.01)
            return real_scan(vfs, progress=progress, cancelled=cancelled)

        session = Session()
        self.addCleanup(session.close_project)
        with mock.patch.object(VirtualFS, "scan", slow_scan):
            session.open_project(self.layers.game_root, self.layers.mod_root)
            time.sleep(0.1)
            QCoreApplication.processEvents()
            session.open_project(self.other.game_root, self.layers.mod_root)
            wait_idle(session)
        self.assertIsNotNone(session.project)
        self.assertFalse(session.is_read_only(), "ninguna otra instancia tiene el mod")
        self.assertTrue(session.project.lock.held)


class CloseWhileOpeningTests(unittest.TestCase):
    """Cerrar la ventana (close_project + cancel_all) cuando Project.open ya pasó el escaneo: no queda bloqueo."""

    def setUp(self):
        isolate_appdirs(self)
        self.layers = build_layers(game={"common/x.txt": "a = 1\r\n"}, mod={})
        self.addCleanup(self.layers.cleanup)

    def test_no_lock_is_left_behind(self):
        import vic2studio.core.project.project as project_module
        from vic2studio.core.project.lock import ProjectLock
        from vic2studio.ui.tasks import cancel_all

        real_load = project_module.load_settings

        def slow_load(*args, **kwargs):
            time.sleep(0.3)      # ya no se consulta la cancelación
            return real_load(*args, **kwargs)

        session = Session()
        with mock.patch.object(project_module, "load_settings", slow_load):
            session.open_project(self.layers.game_root, self.layers.mod_root)
            time.sleep(0.1)
            session.close_project()
            cancel_all()
            wait_for_tasks()
            for _ in range(20):
                QCoreApplication.processEvents()
                time.sleep(0.005)
        self.assertFalse(ProjectLock(self.layers.mod_root).path.exists())


RESTORE_CHILD = textwrap.dedent("""
    import os, sys, time
    sys.path[:0] = [sys.argv[1], os.path.join(sys.argv[1], "..", "src")]
    import _qt
    app = _qt.application()
    from PySide6.QtCore import QCoreApplication
    from vic2studio.ui.session import Session
    session = Session()
    session.open_project(sys.argv[2], sys.argv[3])
    while session.is_busy():
        QCoreApplication.processEvents(); time.sleep(0.01)
    session.restore_session(session.project.orphan_sessions[0])
    os._exit(0)   # corte antes del siguiente autoguardado
""")


class RestoreThenCrashTests(unittest.TestCase):
    """Restaurar una sesión huérfana y morir enseguida no pierde lo restaurado (I8)."""

    def setUp(self):
        isolate_appdirs(self)
        self.layers = build_layers(game={"common/countries.txt": "AAA = 1\r\n"}, mod={})
        self.addCleanup(self.layers.cleanup)

    def test_the_restored_work_survives_a_crash(self):
        earlier = Project.open(self.layers.game_root, self.layers.mod_root)
        with earlier.edit(N_("pending.undo_revert"), name="x"):
            earlier.ws.replace_text(earlier.ws.open("common/countries.txt"), b"CCC = 1\r\n")
        earlier.close()
        script = Path(tempfile.mkdtemp()) / "child.py"
        script.write_text(RESTORE_CHILD, encoding="utf-8")
        subprocess.run([sys.executable, str(script), str(TESTS), str(self.layers.game_root),
                        str(self.layers.mod_root)], check=True, env=os.environ.copy(), timeout=60)
        project = Project.open(self.layers.game_root, self.layers.mod_root)
        self.addCleanup(project.close)
        self.assertTrue(project.orphan_sessions, "lo restaurado tiene que poder recuperarse otra vez")


if __name__ == "__main__":
    unittest.main()
