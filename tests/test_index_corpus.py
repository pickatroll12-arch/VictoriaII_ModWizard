"""Criterios 1 y 2 de la iteración 3 con el corpus real (``VIC2_CORPUS``): recuentos y tiempos del índice.

Las medidas de tiempo son con el recolector cíclico activo (más estricto que en la
aplicación, donde ``ui/tasks`` lo para mientras corre la tarea). En una máquina
cargada (otra batería a la vez) pueden fallar: repítelas solas antes de darlas por
rotas.
"""

import shutil
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import vanilla_root  # noqa: E402
from _layers import isolate_appdirs  # noqa: E402
from vic2studio.core.index import FactsCache, build_index, discover_extractors  # noqa: E402
from vic2studio.core.index import model as m  # noqa: E402
from vic2studio.core.vfs import VirtualFS  # noqa: E402

COLD_LIMIT = 6.0
WARM_LIMIT = 1.0


def vanilla_snapshot(mod_root: Path):
    vfs = VirtualFS(vanilla_root(), mod_root)
    vfs.scan()
    return vfs.snapshot()


@unittest.skipUnless(vanilla_root(), "requiere el corpus (VIC2_CORPUS)")
class CorpusIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="vic2studio-index-corpus-"))
        cls.mod = cls.base / "EmptyMod"
        cls.mod.mkdir()
        cls.cache = FactsCache(cls.base / "cache")
        cls.snapshot = vanilla_snapshot(cls.mod)
        start = time.perf_counter()
        cls.index = build_index(cls.snapshot, cls.cache)
        cls.cold = time.perf_counter() - start

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def setUp(self):
        isolate_appdirs(self)

    def test_criterion_1_counts(self):
        index = self.index
        tags = index.symbols(m.KIND_TAG)
        # «271 TAG + 50 dinámicos»: countries.txt registra 271 TAG en total, de los que 50 (D01–D50) van tras
        # dynamic_tags (221 + 50). Lo mismo dan los 271 archivos de país y las 271 historias.
        self.assertEqual(len(tags), 271)
        self.assertEqual(sum(1 for t in tags if t.attrs["dynamic"]), 50)
        self.assertEqual(index.count(m.KIND_COUNTRY_HISTORY), 271)
        self.assertEqual(index.count(m.KIND_PROVINCE), 2703)
        self.assertTrue(index.exists(m.KIND_PROVINCE, "3246"), "Jan Mayen es de tierra (H5)")
        self.assertEqual(index.count(m.KIND_SEA_PROVINCE), 545)
        self.assertEqual(index.count(m.KIND_REGION), 549)
        self.assertEqual(index.count(m.KIND_CONTINENT), 6)
        self.assertEqual(index.count(m.KIND_CULTURE_GROUP), 34)
        self.assertEqual(index.count(m.KIND_CULTURE), 226)
        self.assertEqual(index.count(m.KIND_GOVERNMENT), 8)
        self.assertEqual(index.count(m.KIND_CB), 31)
        units = index.symbols(m.KIND_UNIT_TYPE)
        self.assertEqual((len(units), sum(u.attrs["type"] == "land" for u in units),
                          sum(u.attrs["type"] == "naval" for u in units)), (21, 11, 10))
        self.assertEqual(index.count(m.KIND_TECHNOLOGY), 150)
        self.assertEqual(index.count(m.KIND_INVENTION), 387)
        events = index.symbols(m.KIND_EVENT)
        self.assertEqual(len(events), 1064)
        self.assertEqual(sum(e.attrs["type"] == "country_event" for e in events), 882)
        self.assertEqual(index.count(m.KIND_DECISION), 151)
        self.assertEqual(index.count(m.KIND_BOOKMARK), 2)
        self.assertEqual(index.attrs(m.KIND_REGION, "PRU_549", "provinces"), [549, 550, 551, 552, 681])

    def test_criterion_7_search_targets(self):
        """Lo que buscará Ctrl+K (criterio 7, de B): el índice ya lo encuentra."""
        from vic2studio.core.validate.context import effective_localisation

        loc = effective_localisation(self.snapshot)
        self.assertEqual(self.index.search("549")[0].name, "549")
        self.assertEqual((self.index.search("PRU")[0].kind, self.index.search("PRU")[0].name), (m.KIND_TAG, "PRU"))
        self.assertEqual(self.index.search("north_german")[0].name, "north_german")
        berlin = self.index.search("Berlín", loc=loc, lang="es")[0]
        self.assertEqual((berlin.kind, berlin.name), (m.KIND_PROVINCE, "549"))
        self.assertEqual(self.index.display(m.KIND_PROVINCE, "549", loc, "en"), "549 Berlin")

    def test_criterion_2_cold_and_warm(self):
        self.assertLess(self.cold, COLD_LIMIT, f"en frío: {self.cold:.2f} s")
        seen = []
        start = time.perf_counter()
        warm = build_index(self.snapshot, self.cache, on_extract=lambda rel, name: seen.append(rel))
        elapsed = time.perf_counter() - start
        self.assertEqual(seen, [], "todo desde la caché")
        self.assertLess(elapsed, WARM_LIMIT, f"desde la caché: {elapsed:.2f} s")
        self.assertEqual(warm.count(m.KIND_PROVINCE), 2703)

    def test_criterion_2_incremental_and_extractor_version(self):
        # El corpus no se toca: el archivo cambiado es la copia del mod (una capa más del mismo índice).
        mod = self.base / "OneFileMod"
        (mod / "common").mkdir(parents=True, exist_ok=True)
        target = mod / "common" / "countries.txt"
        target.write_bytes((vanilla_root() / "common" / "countries.txt").read_bytes())
        build_index(vanilla_snapshot(mod), self.cache)
        target.write_bytes(target.read_bytes() + b'\r\nSIL = "countries/Silesia.txt"\r\n')
        seen = []
        index = build_index(vanilla_snapshot(mod), self.cache, on_extract=lambda rel, name: seen.append((rel, name)))
        self.assertEqual(seen, [("common/countries.txt", "countries.tag_registry")])
        self.assertTrue(index.exists(m.KIND_TAG, "SIL"))
        discover_extractors()
        position = next(i for i, s in enumerate(m.EXTRACTORS) if s.name == "map.regions")
        original = m.EXTRACTORS[position]
        m.EXTRACTORS[position] = replace(original, version=original.version + 1)
        try:
            seen.clear()
            build_index(vanilla_snapshot(mod), self.cache, on_extract=lambda rel, name: seen.append((rel, name)))
        finally:
            m.EXTRACTORS[position] = original
        self.assertEqual(seen, [("map/region.txt", "map.regions")])


if __name__ == "__main__":
    unittest.main()
