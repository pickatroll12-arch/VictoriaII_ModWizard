"""I4: abrir, leer y consultar el proyecto no escribe nada en el mod ni en el juego.

Fuera del mod solo aparece el bloqueo, en la carpeta de datos de la aplicación (I1).
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.vfs import DESCRIPTOR_REL  # noqa: E402


class ReadOnlyUseTests(unittest.TestCase):
    def test_reading_everything_writes_nothing(self):
        appdata = isolate_appdirs(self)
        game = build_minigame(mod_copies=["common/cb_types.txt"],
                              mod_files={"decisions/broken.txt": "political_decisions = {\r\n"})
        self.addCleanup(game.cleanup)
        mod_tree, game_tree = game.tree(), game.game_tree()
        descriptor = game.descriptor.read_bytes(), game.descriptor.stat().st_mtime_ns
        project = Project.open(game.game_root, game.mod_root)
        try:
            ws = project.ws
            for entry in project.vfs.list("", "*", recursive=True):
                handle = ws.open(entry.rel)
                codec_for(handle.kind).snapshot(handle.model)
                ws.external_diff(entry.rel)
            ws.open(DESCRIPTOR_REL)
            ws.open("events/nuevo.txt", create=True)
            self.assertEqual(ws.check_external_changes(), [])
            self.assertEqual(ws.changeset().writes, ())
            ws.write_recovery()                     # sin sucios: no crea nada
            project.vfs.snapshot()
            project.vfs.refresh()
            project.vfs.same_as_game("common/cb_types.txt")
            self.assertEqual(ws.dirty(), [])
        finally:
            project.close()
        self.assertEqual(game.tree(), mod_tree)
        self.assertEqual(game.game_tree(), game_tree)
        self.assertEqual((game.descriptor.read_bytes(), game.descriptor.stat().st_mtime_ns), descriptor)
        self.assertFalse(game.mod(".vic2studio").exists())
        written = sorted(str(p.relative_to(appdata)) for p in appdata.rglob("*") if p.is_file())
        self.assertEqual(written, [], "el bloqueo se suelta al cerrar")
        self.assertTrue((appdata / "data" / "locks").is_dir(), "y vivía fuera del mod")

    def test_opening_holds_only_the_lock_outside_the_mod(self):
        appdata = isolate_appdirs(self)
        game = build_minigame()
        self.addCleanup(game.cleanup)
        project = Project.open(game.game_root, game.mod_root)
        try:
            files = sorted(str(p.relative_to(appdata)) for p in appdata.rglob("*") if p.is_file())
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].startswith(os.path.join("data", "locks")))
            self.assertEqual(project.lock.path, appdata / files[0])
        finally:
            project.close()


if __name__ == "__main__":
    unittest.main()
