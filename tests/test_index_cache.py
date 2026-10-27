"""Caché de hechos e índice incremental (wizard §7, criterio 2 de la iteración 3, I1, I4)."""

import gzip
import os
import sys
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402
from vic2studio.core import appdirs  # noqa: E402
from vic2studio.core.cancel import Cancelled  # noqa: E402
from vic2studio.core.index import FactsCache, build_index, discover_extractors  # noqa: E402
from vic2studio.core.index import model as m  # noqa: E402
from vic2studio.core.vfs import LayerKind, VPath  # noqa: E402


def counting():
    seen: list[tuple[str, str]] = []
    return seen, (lambda rel, name: seen.append((str(rel), name)))


def touch_later(path: Path, data: bytes) -> None:
    """Reescribe ``path`` con otro mtime aunque el sistema de archivos tenga poca resolución."""
    stat = path.stat()
    path.write_bytes(data)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.folder = isolate_appdirs(self)
        self.game = build_minigame()
        self.addCleanup(self.game.cleanup)

    def test_round_trip_is_exact(self):
        snap = self.game.snapshot()
        cache = FactsCache()
        fresh = build_index(snap, cache)
        self.assertTrue(any(cache.root.rglob("facts.v*.jsonl.gz")))
        for layer in snap.layers:
            loaded = cache.load(layer)
            stored = {(f.rel.key, f.extractor): f for f in fresh.facts() if f.layer is layer.kind}
            self.assertEqual(loaded, stored)

    def test_warm_build_extracts_nothing_and_writes_nothing(self):
        snap = self.game.snapshot()
        cache = FactsCache()
        cold, on_cold = counting()
        build_index(snap, cache, on_extract=on_cold)
        self.assertTrue(cold)
        files = {p: p.stat().st_mtime_ns for p in cache.root.rglob("*") if p.is_file()}
        warm, on_warm = counting()
        index = build_index(snap, cache, on_extract=on_warm)
        self.assertEqual(warm, [])
        self.assertEqual({p: p.stat().st_mtime_ns for p in cache.root.rglob("*") if p.is_file()}, files,
                         "sin cambios no se reescribe la caché")
        self.assertEqual(index.names(m.KIND_TAG), ["AAA", "BBB", "CCC", "D01"])

    def test_changing_one_file_reprocesses_only_that_file(self):
        cache = FactsCache()
        build_index(self.game.snapshot(), cache)
        path = self.game.game("common/countries.txt")
        touch_later(path, path.read_bytes() + b'EEE = "countries/E.txt"\r\n')
        seen, on_extract = counting()
        index = build_index(self.game.snapshot(), cache, on_extract=on_extract)
        self.assertEqual(seen, [("common/countries.txt", "countries.tag_registry")])
        self.assertIn("EEE", index.names(m.KIND_TAG))

    def test_extractor_version_invalidates_only_its_cache(self):
        cache = FactsCache()
        build_index(self.game.snapshot(), cache)
        discover_extractors()
        position = next(i for i, s in enumerate(m.EXTRACTORS) if s.name == "map.regions")
        original = m.EXTRACTORS[position]
        m.EXTRACTORS[position] = replace(original, version=original.version + 1)
        self.addCleanup(m.EXTRACTORS.__setitem__, position, original)
        seen, on_extract = counting()
        build_index(self.game.snapshot(), cache, on_extract=on_extract)
        self.assertEqual(seen, [("map/region.txt", "map.regions")])

    def test_unsaved_documents_are_not_cached(self):
        cache = FactsCache()
        overrides = {VPath.of("events/new.txt"): b"country_event = { id = 4242 }\r\n"}
        index = build_index(self.game.snapshot(), cache, overrides)
        self.assertTrue(index.exists(m.KIND_EVENT, "4242"))
        for layer in self.game.snapshot().layers:
            self.assertNotIn(("EVENTS/NEW.TXT", "script.events"), cache.load(layer))

    def test_unreadable_or_foreign_cache_is_ignored(self):
        snap = self.game.snapshot()
        cache = FactsCache()
        build_index(snap, cache)
        game_layer = next(layer for layer in snap.layers if layer.kind is LayerKind.GAME)
        path = cache.path(game_layer)
        for broken in (b"not gzip", gzip.compress(b"{}\n[1,2]"), gzip.compress(b'{"format": 999, "layer": "game"}'),
                       gzip.compress(b'{"format": 1, "layer": "game"}\n["a", "b"]')):
            with self.subTest(broken=broken[:10]):
                path.write_bytes(broken)
                self.assertEqual(cache.load(game_layer), {})
                seen, on_extract = counting()
                index = build_index(snap, cache, on_extract=on_extract)
                self.assertTrue(seen, "se reconstruye")
                self.assertEqual(index.count(m.KIND_TAG), 4)

    def test_cache_folders_and_drop(self):
        snap = self.game.snapshot()
        cache = FactsCache()
        build_index(snap, cache)
        game_layer = next(layer for layer in snap.layers if layer.kind is LayerKind.GAME)
        mod_layer = next(layer for layer in snap.layers if layer.kind is LayerKind.MOD)
        self.assertEqual(cache.folder(game_layer).name, "game-" + appdirs.mod_key(game_layer.root))
        self.assertEqual(cache.folder(mod_layer).name, "mod-" + appdirs.mod_key(mod_layer.root))
        self.assertEqual(cache.root, appdirs.cache_dir() / "index")
        cache.drop(game_layer, [VPath.of("common/countries.txt")])
        self.assertNotIn(("COMMON/COUNTRIES.TXT", "countries.tag_registry"), cache.load(game_layer))
        self.assertIn(("COMMON/CB_TYPES.TXT", "war.cb_types"), cache.load(game_layer))
        cache.drop(game_layer)
        self.assertEqual(cache.load(game_layer), {})

    def test_never_writes_inside_a_layer(self):
        snap = self.game.snapshot()
        inside = FactsCache(self.game.mod_root / ".cache")
        with self.assertLogs("vic2studio.core.index.cache", "WARNING"):
            build_index(snap, inside)
        self.assertFalse((self.game.mod_root / ".cache").exists())

    def test_indexing_does_not_write_in_the_mod_or_the_game(self):
        mod_tree, game_tree = self.game.tree(), self.game.game_tree()
        build_index(self.game.snapshot(), FactsCache())
        build_index(self.game.snapshot(), FactsCache())
        self.assertEqual(self.game.tree(), mod_tree)
        self.assertEqual(self.game.game_tree(), game_tree)

    def test_progress_and_cancel(self):
        steps = []
        build_index(self.game.snapshot(), None, progress=lambda done, total: steps.append((done, total)))
        self.assertTrue(steps)
        self.assertEqual(steps[-1][0], steps[-1][1])
        calls = iter(range(1000))
        with self.assertRaises(Cancelled):
            build_index(self.game.snapshot(), FactsCache(), cancelled=lambda: next(calls) > 5)

    def test_store_failure_does_not_break_the_index(self):
        with mock.patch("vic2studio.core.fileio.atomic_write_bytes", side_effect=OSError(28, "No space left")):
            with self.assertLogs("vic2studio.core.index.builder", "WARNING"):
                index = build_index(self.game.snapshot(), FactsCache())
        self.assertEqual(index.count(m.KIND_TAG), 4)

    def test_build_in_a_background_thread(self):
        """I12: el índice se construye con la instantánea en otro hilo, sin tocar el Workspace."""
        import threading

        snap = self.game.snapshot()
        result = {}
        thread = threading.Thread(target=lambda: result.setdefault("index", build_index(snap, FactsCache())))
        thread.start()
        thread.join(60)
        self.assertEqual(result["index"].count(m.KIND_TAG), 4)

    def test_cold_build_is_fast_on_the_minigame(self):
        start = time.perf_counter()
        build_index(self.game.snapshot(), None)
        self.assertLess(time.perf_counter() - start, 2.0)


if __name__ == "__main__":
    unittest.main()
