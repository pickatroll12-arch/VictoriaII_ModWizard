"""Criterio 4 (I4): abrir el proyecto y guardar sin cambios no escribe nada ni crea ``.vic2studio/``.

Se comprueban el árbol del mod y las fechas de modificación, también cuando las
ediciones se deshicieron o dejaron los bytes como estaban, y con la muestra del
mod del usuario (copiada a una carpeta temporal).
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import FIXTURE_ROOT, USER_MOD_NAME  # noqa: E402
from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.vfs import DESCRIPTOR_REL  # noqa: E402

CB = "common/cb_types.txt"


def descriptor_state(path: Path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, path.read_bytes()


class NoopSaveTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def open(self, game_root, mod_root):
        project = Project.open(game_root, mod_root)
        self.addCleanup(project.close)
        return project

    def assertUntouched(self, game, tree, descriptor):
        self.assertEqual(game.tree(), tree, "árbol del mod y fechas idénticos")
        self.assertFalse(game.mod(".vic2studio").exists())
        self.assertEqual(descriptor_state(game.descriptor), descriptor)

    def test_acceptance_criterion_4(self):
        game = build_minigame(mod_copies=[CB])
        self.addCleanup(game.cleanup)
        tree, descriptor = game.tree(), descriptor_state(game.descriptor)
        project = self.open(game.game_root, game.mod_root)
        for entry in project.vfs.list("", "*", recursive=True):
            project.ws.open(entry.rel)
        project.ws.open(DESCRIPTOR_REL)
        report = project.save()
        self.assertTrue(report.nothing_to_save)
        self.assertTrue(report.ok)
        self.assertEqual(project.ws.changeset().writes, ())
        project.close()
        self.assertUntouched(game, tree, descriptor)

    def test_undone_and_byte_identical_edits_write_nothing(self):
        game = build_minigame(mod_copies=[CB])
        self.addCleanup(game.cleanup)
        tree, descriptor = game.tree(), descriptor_state(game.descriptor)
        project = self.open(game.game_root, game.mod_root)
        ws = project.ws
        handle = ws.open(CB)
        with project.edit("undo.a"):
            ws.touch(handle)
            handle.model.document.get("conquer_land").set("months", "99")
        ws.undo()
        with project.edit("undo.b"):
            ws.touch(handle)
            handle.model.document.get("free_people").set("months", "7")
        with project.edit("undo.c"):
            ws.touch(handle)
            handle.model.document.get("free_people").set("months", "6")   # vuelve a los bytes de disco
        self.assertTrue(handle.dirty)
        self.assertTrue(project.save().nothing_to_save)
        self.assertFalse(handle.dirty)
        project.close()
        self.assertUntouched(game, tree, descriptor)

    def test_user_mod_sample(self):
        """La muestra de VSM (con sus decisiones rotas, D17) se abre y se guarda sin escribir nada."""
        with tempfile.TemporaryDirectory() as tmp:
            game_root = Path(tmp) / "Victoria 2"
            (game_root / "mod").mkdir(parents=True)
            (game_root / "v2game.exe").write_bytes(b"MZ")
            shutil.copytree(FIXTURE_ROOT / USER_MOD_NAME, game_root / "mod" / USER_MOD_NAME)
            shutil.copy2(FIXTURE_ROOT / f"{USER_MOD_NAME}.mod", game_root / "mod" / f"{USER_MOD_NAME}.mod")
            mod_root = game_root / "mod" / USER_MOD_NAME

            def tree():
                return {str(p.relative_to(game_root)): (p.stat().st_mtime_ns, p.read_bytes())
                        for p in sorted(game_root.rglob("*")) if p.is_file()}

            before = tree()
            project = Project.open(game_root, mod_root)
            try:
                self.assertEqual(project.descriptor.name, "Shago Mod")
                for entry in project.vfs.list("", "*", recursive=True):
                    project.ws.open(entry.rel)
                self.assertTrue(project.save().nothing_to_save)
            finally:
                project.close()
            self.assertEqual(tree(), before)


if __name__ == "__main__":
    unittest.main()
