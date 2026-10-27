"""Regresiones de la revisión adversarial del Workspace (iteración 2): revivir una lápida y textos de guardado."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402
from vic2studio.core.project import DocKind, Project  # noqa: E402
from vic2studio.core.project.project import SETTINGS_REL  # noqa: E402
from vic2studio.core.vfs.model import LayerKind  # noqa: E402

CB = "common/cb_types.txt"


class Base(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def project(self, **kwargs):
        game = build_minigame(**kwargs)
        self.addCleanup(game.cleanup)
        project = Project.open(game.game_root, game.mod_root)
        self.addCleanup(project.close, discard=True)
        return game, project


class DeletedOverrideTests(Base):
    """R13 (I7): borrar la copia del mod de un archivo del juego deja una lápida hasta guardar (es lo que documenta
    ``open``: ``FileNotFoundError``), pero revivirla con ``open(create=True)`` no debe taparlo con uno vacío."""

    def test_the_tombstone_hides_the_file_until_saving(self):
        game, project = self.project(mod_copies=[CB])
        with project.edit("undo.del"):
            project.ws.delete(CB)
        with self.assertRaises(FileNotFoundError):
            project.ws.open(CB)
        self.assertTrue(project.save().ok)
        self.assertIs(project.ws.open(CB).origin.layer.kind, LayerKind.GAME, "guardado, se ve el del juego")

    def test_open_create_does_not_shadow_vanilla_with_empty_file(self):
        game, project = self.project(mod_copies=[CB])
        with project.edit("undo.del"):
            project.ws.delete(CB)
        with project.edit("undo.ensure"):
            project.ws.open(CB, create=True)
        self.assertTrue(project.save().ok)
        self.assertNotEqual(game.mod(CB).read_bytes() if game.mod(CB).exists() else None, b"")


class SaveProblemTextTests(Base):
    """R14: el motivo de save_not_writable es el texto crudo de la excepción de Python (en inglés)."""

    def test_not_writable_reason_is_translated(self):
        game, project = self.project()
        with project.edit("undo.t"):
            handle = project.ws.open(SETTINGS_REL, kind=DocKind.JSON, create=True)
            project.ws.replace_text(handle, b'{"prefix": "AB",')
        report = project.save()
        message = report.problems[0].message("es")
        self.assertNotIn("Expecting", message)


if __name__ == "__main__":
    unittest.main()
