"""Regresión (ronda 2 de la revisión): «Nuevo mod» con una carpeta que no es un solo nombre y «Nuevo mod»
interrumpido por un corte y recuperado al abrirlo."""

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS.parent / "src"))

from _layers import isolate_appdirs  # noqa: E402

from vic2studio.core.clausewitz import Severity  # noqa: E402
from vic2studio.core.modfile import DescriptorProblemsError, DescriptorSpec, create_mod_skeleton  # noqa: E402
from vic2studio.core.modfile import descriptor_problems  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402


def tree(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


class FolderIsASingleNameTests(unittest.TestCase):
    """<juego>/mod/<carpeta> no puede salir de <juego>/mod (I1): "/x" (o "\\x" en Windows) es la raíz del disco."""

    def setUp(self):
        isolate_appdirs(self)
        self.base = Path(tempfile.mkdtemp())
        self.game = self.base / "game"
        (self.game / "mod").mkdir(parents=True)

    def test_an_absolute_or_dotted_folder_is_an_error_and_nothing_is_written(self):
        # Un solo componente absoluto: check_descriptor lo deja pasar porque PureWindowsPath("mod//x") son 2 partes.
        outside = Path(tempfile.mkdtemp(dir="/")) if os.access("/", os.W_OK) else None
        if outside is not None:
            self.addCleanup(shutil.rmtree, outside, True)
            self.addCleanup(lambda: Path(f"{outside}.mod").unlink(missing_ok=True))
        folders = ["./x"] + ([f"/{outside.name}"] if outside is not None else [])
        for folder in folders:
            with self.subTest(folder=folder):
                spec = DescriptorSpec("Evil Mod", folder, "EV")
                errors = [i.code for i in descriptor_problems(spec, self.game, creating=True)
                          if i.severity is Severity.ERROR]
                self.assertTrue(errors, "la carpeta tiene que ser un solo nombre")
                with self.assertRaises(DescriptorProblemsError):
                    create_mod_skeleton(self.game, spec)
        if outside is not None:
            self.assertEqual(tree(outside), [], "nada fuera de <juego>/mod")
            self.assertFalse(Path(f"{outside}.mod").exists())
        self.assertEqual(tree(self.game / "mod"), [])

    @unittest.skipUnless(os.access("/", os.W_OK), "hace falta poder crear una carpeta en la raíz del disco")
    def test_an_absolute_folder_does_not_recover_a_journal_there(self):
        # «/x» no es <juego>/mod/x: un diario «Nuevo mod» pendiente en /x es de otro sitio y no se resuelve (I1).
        outside = Path(tempfile.mkdtemp(dir="/"))
        self.addCleanup(shutil.rmtree, outside, True)
        script = self.base / "child.py"
        script.write_text(FOREIGN_JOURNAL_CHILD, encoding="utf-8")
        result = subprocess.run([sys.executable, str(script), str(TESTS), str(outside)], env=os.environ.copy(),
                                timeout=60)
        self.assertEqual(result.returncode, 9, "el corte llegó con el diario preparado")
        before = tree(outside)
        self.assertTrue(any(name.startswith(".vic2studio/journal/") for name in before))
        with self.assertRaises(DescriptorProblemsError):
            create_mod_skeleton(self.game, DescriptorSpec("Evil Mod", f"/{outside.name}", "EV"))
        self.assertEqual(tree(outside), before, "se tocó un diario fuera de <juego>/mod")


FOREIGN_JOURNAL_CHILD = textwrap.dedent("""
    import os, sys
    sys.path[:0] = [sys.argv[1], os.path.join(sys.argv[1], "..", "src")]
    from pathlib import Path
    from vic2studio.core.project import journal
    from vic2studio.core.project.model import PlannedWrite, WriteAction
    from vic2studio.core.vfs.guard import WriteGuard
    from vic2studio.core.vfs.paths import VPath
    root = Path(sys.argv[2])
    guard = WriteGuard(root)
    folder = journal.project_dir(root)
    transaction = journal.SaveTransaction(guard, folder / journal.JOURNAL_DIR, label="new_mod", backup_bak=False,
                                          trash_dir=folder / journal.TRASH_DIR, trash_creates=False)
    transaction.add(PlannedWrite(VPath.of("common/x.txt"), guard.check(root / "common" / "x.txt"),
                                 WriteAction.CREATE, b"x = 1\\r\\n", None))
    assert not [p for p in transaction.prepare() if p.blocking]
    journal.FAULT_HOOK = lambda s, i: os._exit(9) if s == "journal_prepared" else None
    transaction.commit()
    os._exit(0)
""")


CRASH_CHILD = textwrap.dedent("""
    import os, sys
    sys.path[:0] = [sys.argv[1], os.path.join(sys.argv[1], "..", "src")]
    from pathlib import Path
    from vic2studio.core.project import journal
    from vic2studio.core.modfile import DescriptorSpec, create_mod_skeleton
    step = sys.argv[2]
    journal.FAULT_HOOK = lambda s, i: os._exit(9) if s == step and i == 0 else None
    create_mod_skeleton(Path(sys.argv[3]), DescriptorSpec("Dark Age Mod", "DAM", "DAM"), template=Path(sys.argv[4]))
    os._exit(0)
""")


class InterruptedNewModTests(unittest.TestCase):
    """«Nuevo mod» cortado a mitad (os._exit) y recuperado al abrirlo: todo o nada (I2, §14.1)."""

    def setUp(self):
        isolate_appdirs(self)

    def crash(self, step: str) -> Path:
        base = Path(tempfile.mkdtemp())
        game = base / "game"
        (game / "mod").mkdir(parents=True)
        template = base / "Plantilla Mod"
        (template / "common").mkdir(parents=True)
        (template / "common" / "defines.lua").write_bytes(b"x = 1\r\n")
        script = base / "child.py"
        script.write_text(CRASH_CHILD, encoding="utf-8")
        result = subprocess.run([sys.executable, str(script), str(TESTS), step, str(game), str(template)],
                                env=os.environ.copy(), timeout=60)
        self.assertEqual(result.returncode, 9, "el corte llegó en ese paso")
        return game

    def test_rolled_forward_has_the_whole_skeleton(self):
        game = self.crash("journal_backed_up")
        mod = game / "mod" / "DAM"
        project = Project.open(game, mod)
        project.close()
        self.assertTrue((game / "mod" / "DAM.mod").is_file())
        for folder in ("common", "history", "localisation"):
            self.assertTrue((mod / folder).is_dir(), f"falta {folder}/: ni antes ni después")

    def test_rolled_back_is_not_opened_as_a_project(self):
        game = self.crash("journal_prepared")
        mod = game / "mod" / "DAM"
        with self.assertRaises(FileNotFoundError, msg="la recuperación deja el mod como antes: no existe"):
            Project.open(game, mod).close()
        self.assertEqual(tree(game / "mod"), [])


if __name__ == "__main__":
    unittest.main()
