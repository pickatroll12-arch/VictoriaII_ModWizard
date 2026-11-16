"""Núcleo del mapa de la iteración 5 (wizard §16): default.map, posiciones, estrechos, caché del ráster, geometría,
modos, hechos por fecha, grupos de provincias, historia fechada de provincias y POPs, sobre el minijuego del mapa.

Todo es inventado (``tests/_minigame.py``); el corpus de vanilla solo se usa en ``VanillaCriteriaTests``, que se
salta sin ``VIC2_GAME``.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import isolate_appdirs  # noqa: E402
import _minigame as mg  # noqa: E402
from vic2studio.core.clausewitz.nodes import ClausewitzDate  # noqa: E402
from vic2studio.core.clausewitz.serializer import to_source  # noqa: E402
from vic2studio.core.index import build_index  # noqa: E402
from vic2studio.core.locsync import LocSync  # noqa: E402
from vic2studio.core.map import cache  # noqa: E402
from vic2studio.core.map.adjacency import TYPE_CANAL, TYPE_SEA, AdjacencyTable  # noqa: E402
from vic2studio.core.map.bmp import read_bmp  # noqa: E402
from vic2studio.core.map.default_map import DefaultMap  # noqa: E402
from vic2studio.core.map.definition import DefinitionTable  # noqa: E402
from vic2studio.core.map.facts import ProvinceFacts, terrain_types  # noqa: E402
from vic2studio.core.map.geometry import distance_to, label_point, parts  # noqa: E402
from vic2studio.core.map.groups import GROUP_FILES, GroupError, ProvinceGroups  # noqa: E402
from vic2studio.core.map.modes import discover_modes  # noqa: E402
from vic2studio.core.map.positions import Point, Positions, unit_points  # noqa: E402
from vic2studio.core.map.raster import ProvinceRaster  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.project.codecs import codec_for, parse_bytes  # noqa: E402
from vic2studio.core.rules.game import GameRules  # noqa: E402
from vic2studio.core.schema import Entities  # noqa: E402

D = ClausewitzDate.parse
D1836, D1861 = D("1836.1.1"), D("1861.1.1")


def _raster(game) -> ProvinceRaster:
    image = read_bmp(game.game("map/provinces.bmp").read_bytes())
    table, _ = DefinitionTable.parse(game.game("map/definition.csv").read_bytes())
    return ProvinceRaster.build(image.pixels, table)


def _bytes(ws, rel) -> bytes:
    handle = ws.open(rel)
    return codec_for(handle.kind).snapshot(handle.model)


def _diff_lines(before: bytes, after: bytes) -> int:
    import difflib

    old = before.decode("cp1252").splitlines()
    new = after.decode("cp1252").splitlines()
    return sum(1 for line in difflib.ndiff(old, new) if line[:1] in "+-")


class DefaultMapTests(unittest.TestCase):
    def setUp(self):
        self.doc = parse_bytes(mg.DEFAULT_MAP.encode("cp1252")).document
        self.map = DefaultMap(self.doc)

    def test_reads_sea_starts_in_order_with_duplicates(self):
        self.assertEqual(self.map.sea_starts(), list(mg.SEA_STARTS))
        self.assertEqual(self.map.sea_start_duplicates(), {10: 2})
        self.assertEqual(self.map.max_provinces(), 13)
        self.assertTrue(self.map.is_sea(11))
        self.assertFalse(self.map.is_sea(3))
        self.assertEqual(self.map.files()["provinces"], "provinces.bmp")

    def test_edits_touch_only_their_tokens(self):
        before = to_source(self.doc)
        self.assertFalse(self.map.add_sea_start(9))
        self.assertTrue(self.map.add_sea_start(13))
        self.assertEqual(self.map.remove_sea_start(10, every=False), 1)
        self.assertEqual(self.map.sea_starts(), [9, 10, 11, 12, 13])
        self.map.set_max_provinces(20)
        self.assertEqual(self.map.max_provinces(), 20)
        after = to_source(self.doc)
        self.assertIn("border_cutoff = 90.0", after)
        self.assertEqual(before.count("\n"), after.count("\n"))


class PositionsTests(unittest.TestCase):
    def setUp(self):
        self.data = mg.MAP_GAME_FILES["map/positions.txt"].encode("cp1252")
        self.doc = parse_bytes(self.data).document
        self.positions = Positions(self.doc)

    def test_reads_units_buildings_and_rotations(self):
        self.assertEqual(self.positions.ids()[:3], [1, 2, 3])
        unit = self.positions.point(1, "unit")
        self.assertEqual((int(unit.x), int(unit.y)), mg.UNIT_POINTS[1])
        self.assertIsNotNone(self.positions.point(1, "city"))
        self.assertAlmostEqual(self.positions.rotation(4, "naval_base"), 1.57)
        self.assertEqual({p: (int(v.x), int(v.y)) for p, v in unit_points(self.data).items()}, mg.UNIT_POINTS)

    def test_a_point_change_is_a_minimal_diff_and_keeps_the_decimals(self):
        before = to_source(self.doc)
        self.positions.set_point(1, "unit", Point(12.5, 7.25))
        after = to_source(self.doc)
        self.assertEqual(_diff_lines(before.encode("cp1252"), after.encode("cp1252")), 4)
        self.assertIn("x = 12.500", after)
        self.positions.set_point(11, "unit", Point(50, 4))
        self.assertTrue(self.positions.has(11))


class AdjacencyTests(unittest.TestCase):
    def test_round_trip_and_rows(self):
        data = mg.ADJACENCIES_CSV.encode("cp1252")
        table, problems = AdjacencyTable.parse(data)
        self.assertEqual(problems, [])
        self.assertEqual(table.to_bytes(), data)
        rows = table.rows()
        self.assertEqual([(r.start, r.end, r.type) for r in rows],
                         [(1, 4, TYPE_SEA), (2, 6, "impassable"), (4, 8, TYPE_CANAL)])
        self.assertEqual(table.find(4, 1)[0].through, 9)

    def test_add_set_and_remove_keep_the_rest(self):
        data = mg.ADJACENCIES_CSV.encode("cp1252")
        table, _ = AdjacencyTable.parse(data)
        added = table.add(5, 8, TYPE_SEA, through=12, comment="Nuevo")
        self.assertEqual((added.start, added.end, added.through), (5, 8, 12))
        changed = table.set(added, through=11)
        self.assertEqual(changed.through, 11)
        table.remove(changed)
        self.assertEqual(table.to_bytes(), data)
        with self.assertRaises(ValueError):
            table.add(1, 2, "bridge")


class RasterCacheTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def test_store_load_and_refuse_inside_the_layers(self):
        with mg.build_map_minigame() as game, tempfile.TemporaryDirectory() as folder:
            bmp = game.game("map/provinces.bmp").read_bytes()
            csv = game.game("map/definition.csv").read_bytes()
            root = Path(folder) / "raster"
            raster, hit = cache.load_or_build(bmp, csv, root=root)
            self.assertFalse(hit)
            again, hit = cache.load_or_build(bmp, csv, root=root)
            self.assertTrue(hit)
            self.assertTrue((again.ids == raster.ids).all())
            self.assertEqual(again.unknown, raster.unknown)
            key = cache.raster_key(bmp, csv)
            self.assertFalse(cache.store(key, raster, root=game.game_root / "cache", forbidden=[game.game_root]))
            self.assertFalse((game.game_root / "cache").exists())
            self.assertNotEqual(key, cache.raster_key(bmp, csv + b"\r\n"))


class GeometryTests(unittest.TestCase):
    def test_label_points_lie_inside_and_parts_count(self):
        with mg.build_map_minigame() as game:
            raster = _raster(game)
        for pid in range(1, 13):
            x, y = label_point(raster, pid)
            self.assertEqual(raster.at(int(x), int(y)), pid, pid)
            self.assertEqual(distance_to(raster, pid, x, y), 0)
            self.assertEqual(parts(raster, pid), 1)
        self.assertEqual(raster.width, mg.MAP_SIZE[0])


class FactsAndModesTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def test_owners_population_and_every_mode(self):
        with mg.build_map_minigame(clean=True) as game:
            snapshot = game.snapshot()
            index = build_index(snapshot, None)
            rules = GameRules.from_snapshot(snapshot)
            raster = _raster(game)
            terrain = read_bmp(game.game("map/terrain.bmp").read_bytes())
            majority = raster.majority(terrain.pixels)
            types = terrain_types(game.game("map/terrain.txt").read_bytes())
            for date in mg.OWNERS:
                with self.subTest(date=date):
                    facts = ProvinceFacts.build(index, rules, D(date), size=raster.max_id + 1,
                                                terrain_majority=majority, terrain_types=types)
                    owners = {p: facts.name("tags", int(facts.owner[p])) for p in range(1, 9)}
                    self.assertEqual(owners, mg.OWNERS[date])
                    population = {p: int(facts.population[p]) for p in range(1, 13) if facts.population[p]}
                    self.assertEqual(population, mg.POPULATION[date])
                    terrains = {p: facts.name("terrains", int(facts.terrain[p])) for p in range(1, 13)}
                    self.assertEqual(terrains[5], "hills")              # la historia anula el mapa
                    self.assertEqual(terrains[8], "mountain")
                    modes = discover_modes()
                    self.assertEqual(len(modes), 13)
                    for mode in modes:
                        param = "AAA" if mode.param else None
                        lut = mode.lut(facts, index, param=param)
                        self.assertEqual(lut.shape, (facts.size,), mode.key)
                        self.assertTrue(mode.legend(facts, index, param=param), mode.key)

    def test_mode_change_is_fast(self):
        with mg.build_map_minigame(clean=True) as game:
            snapshot = game.snapshot()
            index = build_index(snapshot, None)
            facts = ProvinceFacts.build(index, GameRules.from_snapshot(snapshot), D1836, size=13)
        for mode in discover_modes():
            start = time.perf_counter()
            mode.lut(facts, index, param="AAA" if mode.param else None)
            self.assertLess(time.perf_counter() - start, 0.15, mode.key)


class ProjectCase(unittest.TestCase):
    clean = True
    drop: tuple[str, ...] = ()

    def setUp(self):
        isolate_appdirs(self)
        self._game = mg.build_map_minigame(clean=self.clean, drop=self.drop)
        game = self._game.__enter__()
        self.addCleanup(self._game.__exit__, None, None, None)
        self.project = Project.open(game.game_root, game.mod_root)
        self.addCleanup(self.project.close, discard=True)
        self.ws = self.project.ws
        self.index = build_index(self.project.vfs.snapshot(), None)
        self.entities = Entities(self.ws, self.index, LocSync(self.ws, self.project.vfs,
                                                               prefix=self.project.settings.prefix))
        from vic2studio.core.domain.province import Provinces

        self.provinces = Provinces(self.entities, GameRules.from_snapshot(self.project.vfs.snapshot()))


class GroupsTests(ProjectCase):
    def test_reads_the_four_layouts(self):
        expected = {"region": {"AAA_1": [1, 2, 3], "BBB_4": [4, 5, 6], "CCC_7": [7, 8]},
                    "region_sea": {"north_sea_region": [9, 10], "south_sea_region": [11, 12]}}
        for kind, groups in expected.items():
            rel, layout = GROUP_FILES[kind]
            self.assertEqual({g: ProvinceGroups(self.ws, rel, layout=layout).members(g) for g in groups}, groups)
        rel, layout = GROUP_FILES["continent"]
        self.assertIn(1, ProvinceGroups(self.ws, rel, layout=layout).members("west_land"))
        rel, layout = GROUP_FILES["climate"]
        self.assertEqual(ProvinceGroups(self.ws, rel, layout=layout).group_of(1), "mild_climate")

    def test_move_create_rename_delete(self):
        rel, layout = GROUP_FILES["region"]
        groups = ProvinceGroups(self.ws, rel, layout=layout)
        with self.ws.transaction("t"):
            groups.move(3, "BBB_4")
            groups.create("NEW_1")
            groups.rename("NEW_1", "NEW_2")
        self.assertEqual(groups.group_of(3), "BBB_4")
        self.assertIn("NEW_2", groups.groups())
        with self.assertRaises(GroupError) as raised:
            groups.delete("BBB_4")
        self.assertEqual(raised.exception.code, "group_not_empty")
        with self.assertRaises(GroupError):
            groups.create("1bad")
        with self.ws.transaction("t2"):
            groups.delete("NEW_2")
        text = _bytes(self.ws, rel).decode("cp1252")
        self.assertIn("AAA_1 = { 1 2 }", text)
        self.assertIn("BBB_4 = { 4 5 6 3 }", text)

    def test_property_every_land_province_stays_in_exactly_one_state(self):
        """Criterio 7: 200 movimientos al azar (semilla fija), y tras cada uno cada provincia de tierra está en
        exactamente un estado."""
        import random

        rng = random.Random(5)
        rel, layout = GROUP_FILES["region"]
        groups = ProvinceGroups(self.ws, rel, layout=layout)
        names = groups.groups()
        with self.ws.transaction("t"):
            for _ in range(200):
                groups.move(rng.choice(mg.LAND), rng.choice(names))
                for pid in mg.LAND:
                    self.assertEqual(len(groups.groups_of(pid)), 1, pid)
                    self.assertEqual(sum(groups.members(g).count(pid) for g in names), 1, pid)

    def test_paired_climates_keep_their_two_entries(self):
        rel, layout = GROUP_FILES["climate"]
        groups = ProvinceGroups(self.ws, rel, layout=layout)
        with self.ws.transaction("t"):
            groups.move(4, "harsh_climate")
            groups.create("cold_climate", [8])
        text = _bytes(self.ws, rel).decode("cp1252")
        self.assertEqual(text.count("cold_climate ="), 2)
        self.assertEqual(groups.group_of(8), "cold_climate")


class ProvinceHistoryTests(ProjectCase):
    drop = ("history/provinces/east/8 - Cumbre.txt",)

    def test_state_timeline_and_info(self):
        state = self.provinces.state(4, D1861)
        self.assertEqual(state.owner, "BBB")
        self.assertEqual(sorted(self.provinces.cores(5, D1861)), ["BBB", "CCC"])
        self.assertEqual(self.provinces.info(4).region, "BBB_4")
        self.assertTrue(self.provinces.is_sea(9))
        dates = [str(event.date) for event in self.provinces.timeline(5)]
        self.assertIn("1870.1.1", dates)

    def test_editing_at_a_bookmark_writes_into_the_block_of_its_interval(self):
        """Criterio 5: en 1861.1.1 la 4 ya tiene un bloque en (1836.1.1, 1861.1.1] (el de 1850.6.1): se escribe
        en él, con una sola línea de diferencia, y no se crea otro."""
        rel = "history/provinces/north/4 - Colina.txt"
        before = _bytes(self.ws, rel)
        with self.ws.transaction("t"):
            self.assertTrue(self.provinces.set(4, "fort", 2, D1861))
        after = _bytes(self.ws, rel).decode("cp1252")
        self.assertEqual(after.count(" = {"), 1)
        self.assertIn("1850.6.1 = {\r\n\towner = BBB\r\n\tcontroller = BBB\r\n\tfort = 2\r\n}", after)
        self.assertEqual(_diff_lines(before, after.encode("cp1252")), 1)
        self.assertEqual(self.provinces.state(4, D1861).fort, 2)
        self.assertEqual(self.provinces.state(4, D1836).fort, 0)

    def test_editing_after_the_last_bookmark_opens_a_block_on_that_date(self):
        rel = "history/provinces/north/4 - Colina.txt"
        with self.ws.transaction("t"):
            self.provinces.set(4, "fort", 2, D("1861.7.1"))
        after = _bytes(self.ws, rel).decode("cp1252")
        self.assertIn("1861.7.1 = {", after)
        self.assertEqual(self.provinces.state(4, D1861).fort, 0)

    def test_editing_a_province_without_history_creates_only_its_file(self):
        with self.ws.transaction("t"):
            self.provinces.set(8, "owner", "CCC", D1836)
        ref = self.provinces.record(8)
        self.assertIsNotNone(ref)
        text = _bytes(self.ws, ref.handle.rel).decode("cp1252")
        self.assertIn("owner = CCC", text)
        self.assertTrue(str(ref.handle.rel).startswith("history/provinces/east/"))
        self.assertEqual(text.strip().splitlines(), ["owner = CCC"])

    def test_paint_skips_the_sea_and_unchanged_provinces(self):
        with self.ws.transaction("t"):
            changed = self.provinces.paint([1, 2, 3, 9, 10], "owner", "CCC", D1836)
        self.assertEqual(sorted(changed), [1, 2])
        self.assertEqual(self.provinces.state(2, D1836).owner, "CCC")


class PopsTests(ProjectCase):
    def test_read_set_scale_and_new_block(self):
        pops = self.provinces.pops()
        index = pops.pops_index
        self.assertEqual([str(d) for d in index.folders()][:2], ["1836.1.1", "1861.1.1"])
        self.assertEqual(str(index.folder_for(D("1861.7.1"))), "1861.1.1")
        self.assertEqual(pops.total(7, D1861), 690)
        ref = index.blocks(4, D1836)[0]
        found = pops.read(ref)
        self.assertEqual([p.size for p in found], [700, 300, 50])
        with self.ws.transaction("t"):
            pops.set(ref, 0, size=701)
            pops.scale(ref, 2.0)
            block = pops.create_block(3, D1861)
            pops.copy_from(block, ref)
        self.assertEqual([p.size for p in pops.read(ref)], [1402, 600, 100])
        self.assertEqual(sum(p.size for p in pops.read(block)), 2102)
        self.assertEqual(pops.majority(4, D1836)[0], "alander")


@unittest.skipUnless(os.environ.get("VIC2_GAME"), "sin VIC2_GAME (corpus de vanilla)")
class VanillaCriteriaTests(unittest.TestCase):
    """Criterios 1–3 de la iteración 5 sobre vanilla: construir ≤ 4 s, caché ≤ 0,5 s, cambio de modo ≤ 150 ms y
    el centroide de Berlín (549) en la fila 1675,6."""

    def setUp(self):
        isolate_appdirs(self)
        self.game = Path(os.environ["VIC2_GAME"])

    def test_raster_build_cache_and_berlin(self):
        bmp = (self.game / "map/provinces.bmp").read_bytes()
        csv = (self.game / "map/definition.csv").read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            start = time.perf_counter()
            raster, hit = cache.load_or_build(bmp, csv, root=Path(folder))
            built = time.perf_counter() - start
            start = time.perf_counter()
            _again, hit2 = cache.load_or_build(bmp, csv, root=Path(folder))
            loaded = time.perf_counter() - start
        self.assertFalse(hit)
        self.assertTrue(hit2)
        self.assertLess(built, 8.0)          # 4 s en una máquina libre; margen para la batería en paralelo
        self.assertLess(loaded, 0.5)
        self.assertAlmostEqual(float(raster.centroid[549][1]), 1675.6, delta=0.5)

    def _project(self):
        mod = Path(tempfile.mkdtemp()) / "mod"
        mod.mkdir()
        project = Project.open(self.game, mod)
        self.addCleanup(project.close, discard=True)
        index = build_index(project.vfs.snapshot(), None)
        entities = Entities(project.ws, index, LocSync(project.ws, project.vfs, prefix=project.settings.prefix))
        from vic2studio.core.domain.province import Provinces

        return project, Provinces(entities, GameRules.from_snapshot(project.vfs.snapshot()))

    def test_criteria_4_5_and_6_on_berlin(self):
        project, provinces = self._project()
        rel = "history/provinces/germany/549 - Berlin.txt"
        before = _bytes(project.ws, rel)
        with project.ws.transaction("t"):
            self.assertTrue(provinces.set(549, "owner", "NGF", D1836))
        after = _bytes(project.ws, rel)
        self.assertEqual(_diff_lines(before, after), 2)                  # una línea cambiada: − y +
        with project.ws.transaction("t2"):
            provinces.set(549, "fort", 2, D("1861.7.1"))
        text = _bytes(project.ws, rel).decode("cp1252")
        self.assertEqual(text.count("1861.1.1 ="), 2, "vanilla ya trae dos bloques 1861.1.1; no se crea otro")
        self.assertNotIn("1861.7.1", text)
        changed = [line for line in text.splitlines() if "fort = 2" in line]
        self.assertEqual(len(changed), 1, "un solo sitio con el fuerte nuevo")
        self.assertLessEqual(_diff_lines(after, text.encode("cp1252")), 2)
        self.assertEqual(provinces.state(549, D("1861.7.1")).fort, 2)
        self.assertEqual(provinces.state(549, D1836).fort, 1)
        pops = provinces.pops()
        blocks = pops.pops_index.blocks(549, D1836)
        self.assertEqual({str(ref.rel) for ref in blocks}, {"history/pops/1836.1.1/Germany.txt"})
        late = pops.pops_index.blocks(2482, D("1861.4.14"))
        self.assertEqual(len(late), 2)
        self.assertEqual({str(ref.rel) for ref in late}, {"history/pops/1861.4.14/Australia.txt"})

    def test_criterion_8_check_map_baseline(self):
        from collections import Counter

        from vic2studio.core.map.coherence import check_map
        from vic2studio.core.validate import build_context

        project, _provinces = self._project()
        snapshot = project.vfs.snapshot()
        problems = check_map(build_context(snapshot, build_index(snapshot, None)))
        counts = Counter(p.code for p in problems)
        self.assertEqual(counts["bmp_color_unmapped"], 27)
        self.assertEqual([dict(p.args)["text"] for p in problems if p.code == "definition_bad_number"], ["223."])
        self.assertEqual([dict(p.args)["province"] for p in problems if p.code == "sea_start_duplicate"], ["2800"])
        duplicates = {str(p.rel) for p in problems if p.code == "province_history_duplicate"}
        self.assertTrue(any("1396" in rel or "1397" in rel for rel in duplicates), duplicates)


if __name__ == "__main__":
    unittest.main()
