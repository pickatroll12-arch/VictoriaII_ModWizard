"""``GameRules.from_snapshot``: defines.lua, bookmarks, default.map, cabecera del BMP, issues y governments (§9)."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import user_mod, vanilla_root  # noqa: E402
from _minigame import MAP_SIZE, SEA, build_minigame  # noqa: E402
from vic2studio.core.clausewitz import ClausewitzDate  # noqa: E402
from vic2studio.core.rules import DEFAULT_END, DEFAULT_START, GameRules  # noqa: E402
from vic2studio.core.vfs import VirtualFS, VPath  # noqa: E402


def snapshot(game):
    vfs = VirtualFS(game.game_root, game.mod_root, descriptor=game.descriptor)
    vfs.scan()
    return vfs.snapshot()


class MinigameRulesTests(unittest.TestCase):
    def setUp(self):
        self.game = build_minigame(mod=False)
        self.addCleanup(self.game.cleanup)

    def test_values(self):
        rules = GameRules.from_snapshot(snapshot(self.game))
        self.assertEqual(rules.start_date, ClausewitzDate(1836, 1, 1))
        self.assertEqual(rules.end_date, ClausewitzDate(1935, 12, 31))
        self.assertEqual(rules.bookmarks, (ClausewitzDate(1836, 1, 1), ClausewitzDate(1861, 1, 1)))
        self.assertEqual(rules.max_provinces, 13)
        self.assertEqual(rules.sea, frozenset(SEA))
        self.assertTrue(rules.is_sea(9))
        self.assertFalse(rules.is_sea(1))
        self.assertEqual(rules.map_size, MAP_SIZE)
        self.assertEqual(rules.party_policies["trade_policy"], ("protectionism", "free_trade"))
        self.assertEqual(set(rules.party_policies), {"economic_policy", "trade_policy", "religious_policy",
                                                      "citizenship_policy", "war_policy"})
        self.assertEqual(rules.reforms["slavery"], ("yes_slavery", "no_slavery"), "next_step_only no es opción")
        self.assertEqual(rules.government_ideologies["monarchy"], frozenset({"conservative", "liberal"}))
        self.assertEqual(rules.government_ideologies["council"], frozenset({"socialist"}))
        self.assertEqual(rules.map_files["provinces"], "provinces.bmp")

    def test_overrides_and_mod_win(self):
        snap = snapshot(self.game)
        overrides = {VPath.of("common/defines.lua"): b"defines = { start_date = '1840.2.3', end_date = \"1900.1.1\" }",
                     VPath.of("map/default.map"): b"max_provinces = 99\nsea_starts = { 1 }\nprovinces = \"x.bmp\"\n"}
        rules = GameRules.from_snapshot(snap, overrides)
        self.assertEqual(rules.start_date, ClausewitzDate(1840, 2, 3))
        self.assertEqual(rules.end_date, ClausewitzDate(1900, 1, 1))
        self.assertEqual((rules.max_provinces, rules.sea), (99, frozenset({1})))
        self.assertEqual(rules.map_size, (0, 0), "x.bmp no existe")

    def test_missing_or_broken_files_give_defaults(self):
        snap = snapshot(self.game)
        broken = {VPath.of(rel): b"{{{ ]] = = " for rel in ("common/defines.lua", "common/bookmarks.txt",
                                                             "map/default.map", "common/issues.txt",
                                                             "common/governments.txt", "map/provinces.bmp")}
        rules = GameRules.from_snapshot(snap, broken)
        self.assertEqual((rules.start_date, rules.end_date), (DEFAULT_START, DEFAULT_END))
        self.assertEqual((rules.bookmarks, rules.max_provinces, rules.map_size), ((), 0, (0, 0)))
        with build_minigame(mod=False, game_files={}) as empty:
            for rel in ("common/defines.lua", "map/default.map"):
                (empty.game_root / rel).unlink()
            rules = GameRules.from_snapshot(snapshot(empty))
            self.assertEqual(rules.start_date, DEFAULT_START)
            self.assertEqual(rules.max_provinces, 0)

    def test_reads_only_the_bmp_header(self):
        opened = []
        real_open = open

        def spy(path, mode="r", *args, **kwargs):
            opened.append((str(path), mode))
            return real_open(path, mode, *args, **kwargs)

        snap = snapshot(self.game)
        with mock.patch("builtins.open", spy):
            GameRules.from_snapshot(snap)
        self.assertTrue(any(path.endswith("provinces.bmp") and mode == "rb" for path, mode in opened))


@unittest.skipUnless(vanilla_root(), "requiere el corpus (VIC2_CORPUS)")
class CorpusRulesTests(unittest.TestCase):
    def test_vanilla_and_vsm(self):
        vfs = VirtualFS(vanilla_root(), user_mod())
        vfs.scan()
        rules = GameRules.from_vfs(vfs)
        self.assertEqual(rules.start_date, ClausewitzDate(1836, 1, 1))
        self.assertEqual(rules.end_date, ClausewitzDate(2300, 1, 1), "VSM cambia end_date (H20)")
        self.assertEqual(rules.bookmarks, (ClausewitzDate(1836, 1, 1), ClausewitzDate(1861, 7, 1)))
        self.assertEqual(rules.max_provinces, 3249)
        self.assertEqual(len(rules.sea), 545, "546 valores, 2800 repetido (H5)")
        self.assertNotIn(3246, rules.sea)
        self.assertEqual(rules.map_size, (5616, 2160))
        self.assertEqual(rules.government_ideologies["absolute_monarchy"],
                         frozenset({"liberal", "conservative", "reactionary"}))
        self.assertEqual(len(rules.party_policies) + len(rules.reforms), 35, "H19: 30 reformas y 5 de partido")


if __name__ == "__main__":
    unittest.main()
