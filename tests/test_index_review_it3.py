"""Regresiones de la revisión adversarial del núcleo de la iteración 3: índice y caché de hechos (wizard §7).

- 2 dependencias con el mismo archivo: solo cuenta la ganadora, y coincide con la VFS, ``GameRules`` y la
  localización;
- ``apply(removed=...)`` admite una ruta suelta (el archivo del mod, wizard §7);
- la caché nunca escribe dentro de ninguna capa de la vista (juego, dependencias o mod);
- dos capas con la misma carpeta no comparten caché;
- la cabecera ``key;English;…`` de un CSV no es una clave.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame, build_minigame_with_deps, deps_snapshot  # noqa: E402
from vic2studio.core.index import FactsCache, build_index, extract_bytes  # noqa: E402
from vic2studio.core.index import model as m  # noqa: E402
from vic2studio.core.rules.game import GameRules  # noqa: E402
from vic2studio.core.validate import Validator, build_context  # noqa: E402
from vic2studio.core.vfs import LayerKind, VirtualFS, VPath  # noqa: E402

GOVERNMENTS = "common/governments.txt"
DEP_CSV = "localisation/deps.csv"
TWO_DEPS = {
    "DepA": {GOVERNMENTS: "gov_from_A = {\r\n\treactionary = yes\r\n\telection = yes\r\n}\r\n",
             DEP_CSV: "DEP_KEY;From A;;;;De A;;;;;;;;x\r\n"},
    "DepB": {GOVERNMENTS: "gov_from_B = {\r\n\treactionary = yes\r\n\telection = no\r\n}\r\n",
             DEP_CSV: "DEP_KEY;From B;;;;De B;;;;;;;;x\r\n"},
}


def counting():
    seen = []
    return seen, (lambda rel, name: seen.append((str(rel), name)))


class TwoDependenciesTests(unittest.TestCase):
    """Con 2+ dependencias todas eran ``LayerKind.DEPENDENCY`` y el índice las daba todas por ganadoras."""

    def setUp(self):
        isolate_appdirs(self)
        self.game = build_minigame_with_deps(TWO_DEPS)
        self.addCleanup(self.game.cleanup)
        self.dep_a, self.dep_b = self.game.layers.dependencies

    def test_only_the_winning_dependency_counts_and_everyone_agrees(self):
        snap = deps_snapshot(self.game)
        self.assertEqual(snap.resolve(GOVERNMENTS).layer.root, self.dep_b, "la última declarada gana (VFS)")
        index = build_index(snap, FactsCache())
        self.assertEqual(index.names(m.KIND_GOVERNMENT), ["gov_from_B"])
        [losing] = index.lookup(m.KIND_GOVERNMENT, "gov_from_A")
        self.assertFalse(index.is_effective(losing), "la de DepA pierde (queda para el explicador)")
        self.assertTrue(index.is_effective(index.get(m.KIND_GOVERNMENT, "gov_from_B")))
        self.assertEqual(sorted(GameRules.from_snapshot(snap).government_ideologies), ["gov_from_B"])
        ctx = build_context(snap, index)
        self.assertEqual(ctx.loc.lookup("DEP_KEY", "en"), "From B")
        self.assertEqual(len(index.effective(m.KIND_LOC_KEY, "DEP_KEY")), 1, "una sola definición cuenta")
        self.assertEqual(index.facts_of(VPath.of(GOVERNMENTS))[0].root, str(self.dep_b))
        report = Validator(ctx).validate(codes={"government_election_without_duration"})
        self.assertEqual([p.args["government"] for p in report.problems], [],
                         "gov_from_A no lo carga el juego: no se valida")

    def test_from_the_cache_too(self):
        cache = FactsCache()
        build_index(deps_snapshot(self.game), cache)
        seen, on_extract = counting()
        index = build_index(deps_snapshot(self.game), cache, on_extract=on_extract)
        self.assertEqual(seen, [])
        self.assertEqual(index.names(m.KIND_GOVERNMENT), ["gov_from_B"])

    def test_a_new_dependency_order_changes_the_winner(self):
        index = build_index(deps_snapshot(self.game), None)
        vfs = VirtualFS(self.game.game_root, self.game.mod_root, descriptor=self.game.descriptor,
                        dependencies=[self.dep_b, self.dep_a])
        vfs.scan()
        index.apply([], snapshot=vfs.snapshot())
        self.assertEqual(index.names(m.KIND_GOVERNMENT), ["gov_from_A"])

    def test_removing_by_layer_kind_drops_every_dependency(self):
        index = build_index(deps_snapshot(self.game), None)
        index.apply([], removed=[(VPath.of(GOVERNMENTS), LayerKind.DEPENDENCY)])
        self.assertEqual(index.names(m.KIND_GOVERNMENT), ["monarchy", "republic", "council"], "vuelve el juego")


class ApplyRemovedTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def test_a_bare_path_is_the_mod_file(self):
        rel = VPath.of("common/countries.txt")
        with build_minigame(mod=False) as game:
            index = build_index(game.snapshot(), None)
            data = game.game(str(rel)).read_bytes() + b'EEE = "countries/E.txt"\r\n'
            for removed in (rel, str(rel)):
                with self.subTest(removed=type(removed).__name__):
                    index.apply(extract_bytes(rel, data, LayerKind.MOD))
                    self.assertIn("EEE", index.names(m.KIND_TAG))
                    index.apply([], removed=[removed])
                    self.assertNotIn("EEE", index.names(m.KIND_TAG))
                    self.assertIs(index.get(m.KIND_TAG, "AAA").layer, LayerKind.GAME)


class CacheLayersTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)
        self.game = build_minigame()
        self.addCleanup(self.game.cleanup)

    def test_never_writes_inside_any_layer_of_the_view(self):
        """Con la caché dentro del juego se escribía allí la del mod (y al revés): I1, I4."""
        snap = self.game.snapshot()
        mod_tree, game_tree = self.game.tree(), self.game.game_tree()
        for root in (self.game.game_root / "studio_cache", self.game.mod_root / "studio_cache"):
            with self.subTest(root=root.parent.name):
                with self.assertLogs("vic2studio.core.index.cache", "WARNING"):
                    index = build_index(snap, FactsCache(root))
                self.assertEqual(index.count(m.KIND_TAG), 4)
                self.assertFalse(root.exists())
                self.assertEqual((self.game.tree(), self.game.game_tree()), (mod_tree, game_tree))

    def test_two_layers_with_the_same_folder_do_not_share_the_cache(self):
        """Un mod que se declara dependencia de sí mismo: las dos capas se pisaban ``mod-<sha1>`` y la caché no
        servía nunca."""
        vfs = VirtualFS(self.game.game_root, self.game.mod_root, descriptor=self.game.descriptor,
                        dependencies=[self.game.mod_root])
        vfs.scan()
        snap = vfs.snapshot()
        cache = FactsCache()
        build_index(snap, cache)
        seen, on_extract = counting()
        build_index(snap, cache, on_extract=on_extract)
        self.assertEqual(seen, [])
        mod_layer, dep_layer = snap.layers[0], snap.layers[1]
        self.assertEqual((mod_layer.kind, dep_layer.kind), (LayerKind.MOD, LayerKind.DEPENDENCY))
        self.assertNotEqual(cache.folder(mod_layer), cache.folder(dep_layer))
        self.assertTrue(cache.folder(dep_layer).name.startswith("dependency-"))


class LocalisationHeaderTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def test_the_spreadsheet_header_is_not_a_key(self):
        csv = ("key;English;French;German;;Spanish;;;;;;;;x\r\n"
               "hdr_unused;Text;;;;Texto;;;;;;;;x\r\n")
        with build_minigame(mod=False, mod_files={"localisation/00_hdr.csv": csv}) as game:
            snap = game.snapshot()
            index = build_index(snap, None)
            self.assertFalse(index.exists(m.KIND_LOC_KEY, "key"))
            self.assertTrue(index.exists(m.KIND_LOC_KEY, "hdr_unused"))
            report = Validator(build_context(snap, index)).validate(codes={"loc_key_orphan", "header_row"})
        self.assertEqual(sorted((p.code, p.args.get("key")) for p in report.problems),
                         [("header_row", "key"), ("loc_key_orphan", "hdr_unused")],
                         "la cabecera la señala el lint, no sale como clave huérfana")


if __name__ == "__main__":
    unittest.main()
