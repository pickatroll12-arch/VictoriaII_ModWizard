"""Línea base (wizard §11, I11): solo la capa del juego, huellas sin posición y caché fuera del mod."""

import os
import sys
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402
from vic2studio.core import appdirs  # noqa: E402
from vic2studio.core.cancel import Cancelled  # noqa: E402
from vic2studio.core.clausewitz import Severity  # noqa: E402
from vic2studio.core.index import build_index  # noqa: E402
from vic2studio.core.validate import (BaselineCache, Problem, Validator, build_context, compute_baseline,  # noqa: E402
                                      game_only_snapshot)
from vic2studio.core.validate import baseline as baseline_module  # noqa: E402
from vic2studio.core.vfs import LayerKind, VPath  # noqa: E402


def game_baseline(snap):
    game = game_only_snapshot(snap)
    return compute_baseline(build_context(game, build_index(game, None), game_only=True))


class GameOnlyTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)
        self.game = build_minigame(mod_copies=["common/cb_types.txt"])
        self.addCleanup(self.game.cleanup)

    def test_game_only_snapshot_drops_the_mod_and_replace_path(self):
        snap = self.game.snapshot(replace_paths=["history/provinces"])
        game = game_only_snapshot(snap)
        self.assertEqual([layer.kind for layer in game.layers], [LayerKind.GAME])
        self.assertEqual(game.hidden, frozenset())
        self.assertIsNone(game.resolve("decisions/tst_decisions.txt"))
        self.assertIs(game.resolve("common/cb_types.txt").layer.kind, LayerKind.GAME)
        self.assertIsNotNone(game.resolve("history/provinces/north/1 - Capital.txt"))

    def test_build_context_game_only_ignores_overrides(self):
        snap = self.game.snapshot()
        overrides = {VPath.of("events/x.txt"): b"country_event = { id = 9 }"}
        ctx = build_context(snap, None, overrides, game_only=True)
        self.assertTrue(ctx.game_only)
        self.assertEqual(dict(ctx.overrides), {})
        self.assertFalse(ctx.index.exists("event", "9"))
        self.assertTrue(ctx.index.exists("event", "1001"), "index=None: se construye el de esa vista")

    def test_game_only_context_never_uses_an_index_with_the_mod(self):
        snap = self.game.snapshot()
        full = build_index(snap, None)
        self.assertTrue(full.exists("decision", "tst_reform"))
        ctx = build_context(snap, full, game_only=True)
        self.assertFalse(ctx.index.exists("decision", "tst_reform"), "la línea base solo ve el juego")
        game = game_only_snapshot(snap)
        own = build_index(game, None)
        self.assertIs(build_context(snap, own, game_only=True).index, own)

    def test_fingerprint_ignores_positions(self):
        a = Problem("duplicate_field", Severity.WARNING, VPath.of("x.txt"), 3,
                    args=MappingProxyType({"name": "civilized", "first_line": 2}))
        b = Problem("duplicate_field", Severity.WARNING, VPath.of("X.TXT"), 30,
                    args=MappingProxyType({"name": "civilized", "first_line": 29}))
        c = Problem("duplicate_field", Severity.WARNING, VPath.of("x.txt"), 3,
                    args=MappingProxyType({"name": "capital", "first_line": 2}))
        self.assertEqual(a.fingerprint(), b.fingerprint())
        self.assertNotEqual(a.fingerprint(), c.fingerprint())

    def test_a_copied_vanilla_problem_stays_inherited_even_if_its_line_moves(self):
        cb = self.game.mod("common/cb_types.txt")
        cb.write_bytes(b"\r\n\r\n# dos lineas mas\r\n" + cb.read_bytes())
        snap = self.game.snapshot()
        report = Validator(build_context(snap, build_index(snap, None)), baseline=game_baseline(snap)).validate(
            codes={"peace_order_unknown"})
        [problem] = report.problems
        self.assertEqual(problem.line, 9)
        self.assertTrue(problem.inherited)

    def test_cancel(self):
        snap = self.game.snapshot()
        game = game_only_snapshot(snap)
        ctx = build_context(game, build_index(game, None), game_only=True)
        with self.assertRaises(Cancelled):
            compute_baseline(ctx, cancelled=lambda: True)


class BaselineCacheTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)
        self.game = build_minigame()
        self.addCleanup(self.game.cleanup)

    def test_store_and_load(self):
        snap = self.game.snapshot()
        cache = BaselineCache()
        self.assertIsNone(cache.load(snap))
        baseline = game_baseline(snap)
        self.assertTrue(baseline)
        cache.store(snap, baseline)
        self.assertEqual(cache.load(snap), baseline)
        self.assertEqual(cache.path(snap).parent, appdirs.cache_dir() / "baseline")
        self.assertTrue(cache.path(snap).name.startswith("game-" + appdirs.mod_key(self.game.game_root)))
        self.assertEqual(BaselineCache().load(self.game.snapshot()), baseline, "otra instancia la lee")

    def test_invalidated_by_game_files_and_rule_versions(self):
        snap = self.game.snapshot()
        cache = BaselineCache()
        cache.store(snap, game_baseline(snap))
        with mock.patch.object(baseline_module, "RULES_VERSION", baseline_module.RULES_VERSION + 1):
            self.assertIsNone(cache.load(snap))
        self.assertIsNotNone(cache.load(snap))
        events = self.game.game("events/minigame_events.txt")
        stat = events.stat()
        os.utime(events, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
        self.assertIsNone(cache.load(self.game.snapshot()))

    def test_mod_changes_do_not_invalidate_it(self):
        snap = self.game.snapshot()
        cache = BaselineCache()
        cache.store(snap, game_baseline(snap))
        self.game.mod("events/new.txt").parent.mkdir(parents=True, exist_ok=True)
        self.game.mod("events/new.txt").write_bytes(b"country_event = { id = 9 }")
        self.assertIsNotNone(cache.load(self.game.snapshot()), "la línea base es por instalación del juego")

    def test_broken_cache_is_ignored(self):
        snap = self.game.snapshot()
        cache = BaselineCache()
        cache.store(snap, game_baseline(snap))
        for broken in (b"{", b"[]", b'{"format": 1}', b'{"format": 99, "fingerprints": []}'):
            cache.path(snap).write_bytes(broken)
            self.assertIsNone(cache.load(snap))

    def test_without_game_nothing_is_inherited(self):
        from vic2studio.core.vfs import VirtualFS

        vfs = VirtualFS(None, self.game.mod_root)
        vfs.scan()
        self.assertEqual(BaselineCache().load(vfs.snapshot()), frozenset())

    def test_never_writes_in_the_game_or_the_mod(self):
        snap = self.game.snapshot()
        inside = BaselineCache(self.game.game_root / "cache")
        with self.assertLogs("vic2studio.core.validate.baseline", "WARNING"):
            inside.store(snap, frozenset())
        self.assertFalse((self.game.game_root / "cache").exists())
        mod_tree, game_tree = self.game.tree(), self.game.game_tree()
        BaselineCache().store(snap, game_baseline(snap))
        self.assertEqual((self.game.tree(), self.game.game_tree()), (mod_tree, game_tree))


if __name__ == "__main__":
    unittest.main()
