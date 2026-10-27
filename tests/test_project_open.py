"""``Project.open`` y la fachada (wizard §6.4): descriptor, VFS, escaneo, bloqueo, recuperación y ajustes."""

import json
import os
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import descriptor_bytes, isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402
from test_journal_crash import PowerCut, Scenario, SimulatedFault  # noqa: E402
from vic2studio.core import appdirs  # noqa: E402
from vic2studio.core.cancel import Cancelled  # noqa: E402
from vic2studio.core.clausewitz import ClausewitzDate  # noqa: E402
from vic2studio.core.project import Project, ProjectSettings  # noqa: E402
from vic2studio.core.project import project as project_module  # noqa: E402
from vic2studio.core.project.lock import ProjectLock  # noqa: E402
from vic2studio.core.vfs import LayerKind  # noqa: E402

CB = "common/cb_types.txt"


class ProjectOpenTests(unittest.TestCase):
    def setUp(self):
        self.appdata = isolate_appdirs(self)

    def minigame(self, **kwargs):
        game = build_minigame(**kwargs)
        self.addCleanup(game.cleanup)
        return game

    def open(self, game, **kwargs):
        project = Project.open(game.game_root, game.mod_root, **kwargs)
        self.addCleanup(project.close)
        return project

    def test_open(self):
        game = self.minigame()
        calls = []
        project = self.open(game, progress=lambda done, total: calls.append((done, total)))
        self.assertEqual(project.descriptor.name, "TestMod")
        self.assertEqual(project.game_root, game.game_root)
        self.assertEqual(project.mod_root, game.mod_root)
        self.assertEqual(project.project_dir, game.mod(".vic2studio"))
        self.assertFalse(project.project_dir.exists(), "abrir no crea .vic2studio/")
        self.assertFalse(project.read_only)
        self.assertTrue(project.lock.held)
        self.assertEqual(project.recovered, [])
        self.assertEqual(project.orphan_sessions, [])
        self.assertIsNone(project.index)
        self.assertEqual(project.settings.prefix, "TESTMOD")
        self.assertIs(project.vfs.resolve(CB).layer.kind, LayerKind.GAME)
        self.assertIs(project.vfs.resolve("decisions/tst_decisions.txt").layer.kind, LayerKind.MOD)
        self.assertTrue(project.vfs.guard.allows(game.descriptor))
        self.assertTrue(calls)
        self.assertEqual(project.ws.session_id.split("-")[1], str(os.getpid()))

    def test_descriptor_replace_path_and_dependencies(self):
        game = self.minigame()
        dep = game.game_root / "mod" / "DepMod"
        (dep / "events").mkdir(parents=True)
        (dep / "events" / "dep.txt").write_bytes(b"x = 1\r\n")
        (game.game_root / "mod" / "DepMod.mod").write_bytes(descriptor_bytes("Dep Mod", "DepMod"))
        game.descriptor.write_bytes(descriptor_bytes("Test", "TestMod", "TestMod", replace_paths=["history/provinces"])
                                    + b'dependencies = { "Dep Mod" "Falta" }\r\n')
        project = self.open(game)
        self.assertEqual(project.vfs.dependencies, (dep,))
        self.assertEqual(project.vfs.missing_dependencies, ("Falta",))
        self.assertEqual(project.vfs.read_bytes("events/dep.txt"), b"x = 1\r\n")
        self.assertIsNone(project.vfs.resolve("history/provinces/north/1 - Capital.txt"))
        explicit = Project.open(game.game_root, game.mod_root, descriptor=game.descriptor,
                                replace_recursive=False)
        self.addCleanup(explicit.close)
        self.assertTrue(explicit.read_only, "el primero tiene el bloqueo")
        self.assertIsNotNone(explicit.vfs.resolve("history/provinces/north/1 - Capital.txt"))

    def test_missing_mod_and_mod_without_game(self):
        game = self.minigame()
        with self.assertRaises(FileNotFoundError):
            Project.open(game.game_root, game.game_root / "mod" / "NoExiste")
        project = Project.open(None, game.mod_root)
        self.addCleanup(project.close)
        self.assertEqual([layer.kind for layer in project.vfs.layers], [LayerKind.MOD])

    def test_cancel_releases_the_lock(self):
        game = self.minigame()
        with self.assertRaises(Cancelled):
            Project.open(game.game_root, game.mod_root, cancelled=lambda: True)
        lock = ProjectLock(game.mod_root)
        self.assertTrue(lock.acquire(), "un escaneo cancelado no deja el bloqueo puesto")
        lock.release()

    def test_pending_journal_is_recovered_on_open(self):
        scenario = Scenario(self)
        cut = PowerCut(("replace", 1))
        with ExitStack() as stack:
            cut.patches(stack)
            with self.assertRaises(SimulatedFault):
                scenario.transaction().commit()
        project = Project.open(None, scenario.mod)
        self.addCleanup(project.close)
        self.assertEqual([r.outcome for r in project.recovered], ["rolled_forward"])
        self.assertEqual(scenario.state(), scenario.after)
        self.assertEqual(project.vfs.read_bytes("common/countries.txt"), b"AAA = y\r\n", "se escanea tras recuperar")

    def test_read_only_instance_does_not_recover(self):
        scenario = Scenario(self)
        cut = PowerCut(("replace", 1))
        with ExitStack() as stack:
            cut.patches(stack)
            with self.assertRaises(SimulatedFault):
                scenario.transaction().commit()
        lock = ProjectLock(scenario.mod)
        self.assertTrue(lock.acquire())
        try:
            project = Project.open(None, scenario.mod)
            project.close()
            self.assertTrue(project.read_only)
            self.assertEqual(project.recovered, [])
            self.assertNotIn(scenario.state(), (scenario.before, scenario.after), "otra instancia guarda: no se toca")
        finally:
            lock.release()

    def test_settings_live_in_project_json(self):
        game = self.minigame()
        project = self.open(game)
        settings = ProjectSettings(prefix="TST", languages=("en", "es"), copy_en_to=("fr", "de"),
                                   working_date=ClausewitzDate(1861, 1, 1), mode="advanced")
        project.set_settings(settings)
        self.assertEqual(project.settings, settings)
        self.assertFalse(game.mod(".vic2studio").exists(), "se escribe con el próximo guardado")
        project.ws.undo()
        self.assertEqual(project.settings.prefix, "TESTMOD")
        project.ws.redo()
        self.assertTrue(project.save().ok)
        stored = json.loads(game.mod(".vic2studio/project.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["prefix"], "TST")
        self.assertEqual(stored["copy_en_to"], ["fr", "de"])
        self.assertEqual(stored["working_date"], "1861.1.1")
        stored["custom"] = {"keep": True}
        game.mod(".vic2studio/project.json").write_text(json.dumps(stored), encoding="utf-8")
        project.close()
        again = self.open(game)
        self.assertEqual(again.settings, settings)
        again.set_settings(ProjectSettings(prefix="TST2"))
        self.assertTrue(again.save().ok)
        stored = json.loads(game.mod(".vic2studio/project.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["prefix"], "TST2")
        self.assertEqual(stored["custom"], {"keep": True}, "las claves desconocidas se conservan")

    def test_read_only_mod_folder_uses_the_data_dir(self):
        game = self.minigame()
        real_access = os.access

        def access(path, mode, *args, **kwargs):
            if Path(path) == game.mod_root and mode == os.W_OK:
                return False
            return real_access(path, mode, *args, **kwargs)

        with mock.patch.object(project_module.os, "access", access):
            project = self.open(game)
        detached = appdirs.detached_project_dir(game.mod_root)
        self.assertEqual(project.project_dir, detached)
        self.assertTrue(project.vfs.guard.allows(detached / "project.json"))
        project.set_settings(ProjectSettings(prefix="RO"))
        self.assertTrue(project.save().ok)
        self.assertTrue((detached / "project.json").is_file())
        self.assertFalse(game.mod(".vic2studio").exists())

    def test_close_releases_and_is_idempotent(self):
        game = self.minigame()
        project = Project.open(game.game_root, game.mod_root)
        project.close()
        project.close()
        with self.assertRaises(RuntimeError):
            project.ws.open(CB)
        with Project.open(game.game_root, game.mod_root) as again:
            self.assertFalse(again.read_only)


if __name__ == "__main__":
    unittest.main()
