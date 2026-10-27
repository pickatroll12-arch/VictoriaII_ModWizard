"""I7: la VFS resuelve lo que cargaría el juego (wizard §5.1–5.3).

WHOLE_FILE, UNION_BY_PATH, KEYED_UNION, ``replace_path`` recursivo y no,
mayúsculas, dependencias y el descriptor como archivo de la capa MOD.
"""

import builtins
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import build_layers, descriptor_bytes  # noqa: E402
from vic2studio.core.cancel import Cancelled  # noqa: E402
from vic2studio.core.modfile import read_descriptor  # noqa: E402
from vic2studio.core.vfs import DESCRIPTOR_REL, LayerKind, VirtualFS, VPath, rule_for  # noqa: E402

GAME = {
    "common/cb_types.txt": "cb = 1\r\n",
    "common/countries.txt": "AAA = \"countries/A.txt\"\r\n",
    "events/a.txt": "game a\r\n",
    "events/b.txt": "game b\r\n",
    "history/provinces/1 - Top.txt": "owner = AAA\r\n",
    "history/provinces/north/2 - Norte.txt": "owner = AAA\r\n",
    "history/provinces/east/3 - Costa.txt": "owner = CCC\r\n",
    "history/provinces/west/3 - Costa.txt": "owner = CCC\r\n",
    "history/countries/AAA - Aland.txt": "capital = 1\r\n",
}


def _can_have_case_twins(folder: Path) -> bool:
    (folder / "probe").write_bytes(b"")
    twin = not (folder / "PROBE").exists()
    (folder / "probe").unlink()
    return twin


class ResolutionTests(unittest.TestCase):
    def build(self, *, mod=None, game=GAME, **kwargs):
        layers = build_layers(game=game, mod=mod or {}, **{k: v for k, v in kwargs.items() if k == "dependencies"})
        self.addCleanup(layers.cleanup)
        vfs_kwargs = {k: v for k, v in kwargs.items() if k != "dependencies"}
        vfs = VirtualFS(layers.game_root, layers.mod_root, descriptor=layers.descriptor,
                        dependencies=layers.dependencies, **vfs_kwargs)
        vfs.scan()
        return layers, vfs

    def test_whole_file(self):
        layers, vfs = self.build(mod={"common/cb_types.txt": "cb = 2\r\n"})
        entry = vfs.resolve("common/cb_types.txt")
        self.assertIs(entry.layer.kind, LayerKind.MOD)
        self.assertEqual(vfs.read_bytes("common/cb_types.txt"), b"cb = 2\r\n")
        self.assertEqual([e.layer.kind for e in vfs.stack("common/cb_types.txt")], [LayerKind.MOD, LayerKind.GAME])
        self.assertIs(vfs.resolve("common/countries.txt").layer.kind, LayerKind.GAME)
        self.assertEqual(vfs.mod_target("common/countries.txt"), layers.mod("common/countries.txt"))

    def test_union_by_path(self):
        _, vfs = self.build(mod={"events/b.txt": "mod b\r\n", "events/c.txt": "mod c\r\n"})
        listed = vfs.list("events")
        self.assertEqual([e.rel for e in listed], ["events/a.txt", "events/b.txt", "events/c.txt"])
        self.assertEqual([e.layer.kind for e in listed], [LayerKind.GAME, LayerKind.MOD, LayerKind.MOD])
        self.assertEqual(vfs.list("events", "b*"), [listed[1]])

    def test_keyed_union_is_recursive_and_exposes_the_key(self):
        _, vfs = self.build(mod={"history/provinces/north/2 - Norte.txt": "owner = BBB\r\n"})
        listed = vfs.list("history/provinces")
        self.assertEqual([e.rel for e in listed], [
            "history/provinces/1 - Top.txt", "history/provinces/east/3 - Costa.txt",
            "history/provinces/north/2 - Norte.txt", "history/provinces/west/3 - Costa.txt"])
        self.assertIs(listed[2].layer.kind, LayerKind.MOD)
        keys = [rule_for(e.rel).key_of(e.rel) for e in listed]
        self.assertEqual(keys, ["1", "3", "2", "3"], "el id 3 está dos veces: conflicto de KEYED_UNION")
        self.assertEqual(len(vfs.list("history/provinces", recursive=False)), 1)
        self.assertEqual([e.rel for e in vfs.list("history/countries")], ["history/countries/AAA - Aland.txt"])

    def test_replace_path_recursive(self):
        layers, vfs = self.build(mod={"history/provinces/north/9 - Nueva.txt": "owner = AAA\r\n"},
                                 replace_paths=["history\\provinces/"])
        self.assertTrue(vfs.replace_recursive)
        for rel in ("history/provinces/1 - Top.txt", "history/provinces/north/2 - Norte.txt"):
            with self.subTest(rel=rel):
                self.assertIsNone(vfs.resolve(rel))
                stack = vfs.stack(rel)
                self.assertEqual([e.layer.kind for e in stack], [LayerKind.GAME], "sigue en stack para comparar")
                self.assertTrue(vfs.hidden_by_replace_path(stack[0]))
        mine = vfs.resolve("history/provinces/north/9 - Nueva.txt")
        self.assertIs(mine.layer.kind, LayerKind.MOD, "replace_path no oculta los archivos del propio mod")
        self.assertFalse(vfs.hidden_by_replace_path(mine))
        self.assertEqual([e.rel for e in vfs.list("history/provinces")], ["history/provinces/north/9 - Nueva.txt"])
        self.assertIsNotNone(vfs.resolve("history/countries/AAA - Aland.txt"))
        snapshot = vfs.snapshot()
        self.assertIsNone(snapshot.resolve("history/provinces/1 - Top.txt"))
        self.assertIn(VPath.of("history/provinces/1 - Top.txt").key, snapshot.hidden)

    def test_replace_path_not_recursive(self):
        _, vfs = self.build(replace_paths=["history/provinces"], replace_recursive=False)
        self.assertIsNone(vfs.resolve("history/provinces/1 - Top.txt"))
        self.assertIsNotNone(vfs.resolve("history/provinces/north/2 - Norte.txt"), "las subcarpetas siguen")

    def test_letter_case(self):
        layers, vfs = self.build(mod={"Common/CB_Types.txt": "cb = 3\r\n", "History/x.txt": "x\r\n"})
        entry = vfs.resolve("common/cb_types.txt")
        self.assertIs(entry.layer.kind, LayerKind.MOD)
        self.assertEqual(entry.rel, "Common/CB_Types.txt")
        self.assertEqual(vfs.resolve("COMMON/CB_TYPES.TXT"), entry)
        self.assertEqual([e.layer.kind for e in vfs.stack("common/CB_TYPES.txt")], [LayerKind.MOD, LayerKind.GAME])
        # mod_target: el archivo que ya tiene el mod, o la mayúscula de sus carpetas.
        self.assertEqual(vfs.mod_target("common/cb_types.txt"), layers.mod("Common/CB_Types.txt"))
        self.assertEqual(vfs.mod_target("common/countries.txt"), layers.mod("Common/countries.txt"))
        self.assertEqual(vfs.mod_target("history/provinces/north/2 - Norte.txt"),
                         layers.mod("History/provinces/north/2 - Norte.txt"))
        self.assertEqual(vfs.mod_target("events/a.txt"), layers.mod("events/a.txt"))

    def test_case_collisions(self):
        layers, vfs = self.build()
        if not _can_have_case_twins(layers.mod_root):
            self.skipTest("sistema de archivos sin mayúsculas")
        (layers.mod_root / "events").mkdir()
        (layers.mod_root / "events" / "A.txt").write_bytes(b"1")
        (layers.mod_root / "events" / "a.txt").write_bytes(b"2")
        vfs.scan()
        pairs = vfs.case_collisions()
        self.assertEqual([(a.rel, b.rel) for a, b in pairs], [("events/A.txt", "events/a.txt")])
        self.assertEqual(vfs.resolve("events/a.txt").rel, "events/A.txt", "elección determinista")

    def test_dependencies(self):
        layers, vfs = self.build(mod={"events/c.txt": "mod\r\n"}, dependencies={
            "DepOne": {"events/a.txt": "dep one\r\n", "events/c.txt": "dep one c\r\n", "common/x.txt": "x\r\n"},
            "DepTwo": {"events/a.txt": "dep two\r\n"},
        })
        kinds = [layer.kind for layer in vfs.layers]
        self.assertEqual(kinds, [LayerKind.MOD, LayerKind.DEPENDENCY, LayerKind.DEPENDENCY, LayerKind.GAME])
        self.assertEqual([layer.label for layer in vfs.layers[1:3]], ["DepTwo", "DepOne"], "la última declarada gana")
        self.assertEqual(vfs.read_bytes("events/a.txt"), b"dep two\r\n")
        self.assertEqual([e.layer.label for e in vfs.stack("events/a.txt")], ["DepTwo", "DepOne", "Victoria 2"])
        self.assertIs(vfs.resolve("events/c.txt").layer.kind, LayerKind.MOD)
        self.assertEqual(vfs.read_bytes("common/x.txt"), b"x\r\n")
        self.assertEqual(vfs.mod_target("events/a.txt"), layers.mod("events/a.txt"))

    def test_from_descriptor_resolves_dependencies_by_name(self):
        layers = build_layers(game=GAME, mod={}, mod_name="Main", dependencies={"DepOne": {"events/z.txt": "z\r\n"}})
        self.addCleanup(layers.cleanup)
        layers.descriptor.write_bytes(descriptor_bytes("Main", "Main", "Main", replace_paths=["history/provinces"])
                                      + b'dependencies = { "depone" "Missing Mod" }\r\n')
        vfs = VirtualFS.from_descriptor(layers.game_root, read_descriptor(layers.descriptor))
        vfs.scan()
        self.assertEqual(vfs.mod_root, layers.mod_root)
        self.assertEqual(vfs.dependencies, (layers.game_root / "mod" / "DepOne",))
        self.assertEqual(vfs.missing_dependencies, ("Missing Mod",))
        self.assertEqual(vfs.replace_paths, ("HISTORY/PROVINCES",))
        self.assertEqual(vfs.read_bytes("events/z.txt"), b"z\r\n")
        self.assertIsNone(vfs.resolve("history/provinces/1 - Top.txt"))
        self.assertEqual(vfs.descriptor_path, layers.descriptor)
        self.assertTrue(vfs.guard.allows(layers.descriptor))

    def test_descriptor_is_a_mod_file(self):
        layers, vfs = self.build()
        entry = vfs.resolve(DESCRIPTOR_REL)
        self.assertIs(entry.layer.kind, LayerKind.MOD)
        self.assertEqual(entry.path, layers.descriptor)
        self.assertEqual(vfs.read_bytes(DESCRIPTOR_REL), layers.descriptor.read_bytes())
        self.assertEqual(vfs.stack(DESCRIPTOR_REL), [entry])
        self.assertEqual(vfs.mod_target(DESCRIPTOR_REL), layers.descriptor)
        self.assertEqual(vfs.list("", "*.mod"), [])
        self.assertEqual(vfs.list("", "@*", recursive=True), [])
        self.assertNotIn(DESCRIPTOR_REL, [e.rel for e in vfs.snapshot().list("", "*", recursive=True)])
        no_descriptor = VirtualFS(layers.game_root, layers.mod_root)
        no_descriptor.scan()
        self.assertIsNone(no_descriptor.resolve(DESCRIPTOR_REL))
        with self.assertRaises(FileNotFoundError):
            no_descriptor.mod_target(DESCRIPTOR_REL)

    def test_scan_skips_project_folder_backups_temps_and_other_mods(self):
        layers, vfs = self.build(mod={".vic2studio/journal/x.json": "{}", ".git/config": "x",
                                      "common/cb_types.txt.bak": "old", "common/.cb_types.txt.abc.tmp": "tmp",
                                      "common/cb_types.txt": "cb = 2\r\n"})
        rels = {str(e.rel) for e in vfs.list("", "*", recursive=True)}
        self.assertIn("common/cb_types.txt", rels)
        self.assertFalse({r for r in rels if r.startswith((".vic2studio", ".git", "mod/"))})
        self.assertFalse({r for r in rels if r.endswith((".bak", ".tmp"))})
        self.assertIsNone(vfs.resolve("mod/TestMod/common/cb_types.txt"), "<juego>/mod/ no es del juego base")

    def test_scan_reads_no_contents_and_can_be_cancelled(self):
        layers, vfs = self.build()

        def no_open(*args, **kwargs):
            raise AssertionError(f"scan no debe abrir archivos: {args[:1]}")

        with mock.patch.object(builtins, "open", no_open), mock.patch.object(Path, "read_bytes", no_open):
            vfs.scan()
        before = vfs.resolve("events/a.txt")
        calls = []
        vfs.scan(progress=lambda done, total: calls.append((done, total)))
        self.assertTrue(calls)
        self.assertEqual(calls[-1][0], calls[-1][1])
        with self.assertRaises(Cancelled):
            vfs.scan(cancelled=lambda: True)
        self.assertEqual(vfs.resolve("events/a.txt"), before, "una cancelación deja la VFS como estaba")

    def test_snapshot_is_immutable_and_works_in_other_threads(self):
        layers, vfs = self.build(mod={"events/b.txt": "mod b\r\n"})
        snapshot = vfs.snapshot()
        results = {}

        def worker():
            results["b"] = snapshot.resolve("events/b.txt")
            results["list"] = [e.rel for e in snapshot.list("events")]
            results["rels"] = sorted(str(r) for r in snapshot.rels())

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertIs(results["b"].layer.kind, LayerKind.MOD)
        self.assertEqual(results["list"], ["events/a.txt", "events/b.txt"])
        self.assertIn("@descriptor.mod", results["rels"])
        with self.assertRaises(TypeError):
            snapshot.entries["X"] = ()
        layers.mod("events/b.txt").unlink()
        vfs.refresh()
        self.assertIs(vfs.resolve("events/b.txt").layer.kind, LayerKind.GAME)
        self.assertIs(snapshot.resolve("events/b.txt").layer.kind, LayerKind.MOD, "la instantánea no cambia")

    def test_refresh(self):
        layers, vfs = self.build(mod={"events/b.txt": "mod b\r\n"})
        self.assertEqual(vfs.refresh([VPath.of("events/b.txt")]), set())
        layers.mod("events/b.txt").write_bytes(b"mod b changed, longer\r\n")
        self.assertEqual(vfs.refresh([VPath.of("events/B.txt")]), {"events/B.txt"})
        self.assertEqual(vfs.resolve("events/b.txt").fingerprint.size, len(b"mod b changed, longer\r\n"))
        layers.mod("events/a.txt").write_bytes(b"mod a\r\n")
        self.assertEqual(vfs.refresh([VPath.of("events/a.txt")]), {"events/a.txt"})
        self.assertIs(vfs.resolve("events/a.txt").layer.kind, LayerKind.MOD)
        layers.mod("events/a.txt").unlink()
        vfs.refresh([VPath.of("events/a.txt")])
        self.assertIs(vfs.resolve("events/a.txt").layer.kind, LayerKind.GAME)
        # Sin rutas, se vuelve a escanear todo.
        layers.mod("common").mkdir()
        layers.mod("common/new.txt").write_bytes(b"n\r\n")
        layers.mod("events/b.txt").unlink()
        self.assertEqual(vfs.refresh(), {"common/new.txt", "events/b.txt"})
        # El descriptor también.
        layers.descriptor.write_bytes(descriptor_bytes("Otro nombre largo", "TestMod", "TestMod"))
        self.assertEqual(vfs.refresh([DESCRIPTOR_REL]), {DESCRIPTOR_REL})

    def test_same_as_game(self):
        layers, vfs = self.build(mod={"common/cb_types.txt": GAME["common/cb_types.txt"],
                                      "events/a.txt": "distinto\r\n"})
        self.assertTrue(vfs.same_as_game("common/cb_types.txt"))
        self.assertFalse(vfs.same_as_game("events/a.txt"))
        self.assertFalse(vfs.same_as_game("events/b.txt"), "solo en el juego")

    def test_missing_files(self):
        _, vfs = self.build()
        self.assertIsNone(vfs.resolve("events/zzz.txt"))
        self.assertEqual(vfs.stack("events/zzz.txt"), [])
        with self.assertRaises(FileNotFoundError):
            vfs.read_bytes("events/zzz.txt")

    def test_mod_only_without_game(self):
        layers = build_layers(game=None, mod={"events/x.txt": "x\r\n"}, mod_inside_game=False)
        self.addCleanup(layers.cleanup)
        vfs = VirtualFS(None, layers.mod_root)
        vfs.scan()
        self.assertEqual([layer.kind for layer in vfs.layers], [LayerKind.MOD])
        self.assertEqual(vfs.read_bytes("events/x.txt"), b"x\r\n")
        self.assertFalse(vfs.same_as_game("events/x.txt"))
        self.assertTrue(str(layers.mod_root).startswith(str(layers.base / "mods")))
        self.assertTrue(os.path.isdir(layers.mod_root))


if __name__ == "__main__":
    unittest.main()
