"""Coherencia del mapa (wizard §16.5, §14.14): un caso por cada uno de los 20 códigos nuevos de
``core/map/coherence.py`` sobre el minijuego del mapa, y el minijuego limpio con solo sus avisos conocidos."""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import isolate_appdirs  # noqa: E402
from _minigame import (  # noqa: E402
    ADJACENCIES_CSV, DEFAULT_MAP, MAP_SIZE, PROVINCE_COLORS, TERRAIN_OCEAN, _crlf, _definition_csv,
    build_map_minigame, indexed_bmp, province_at, terrain_index_at,
)
from vic2studio.core.clausewitz import Severity  # noqa: E402
from vic2studio.core.index import build_index  # noqa: E402
from vic2studio.core.map.coherence import CODES, NEW_CODES, check_map  # noqa: E402
from vic2studio.core.validate import build_context  # noqa: E402
from vic2studio.core.validate.registry import discover_rules  # noqa: E402


def _bmp24(pixel) -> bytes:
    """BMP de 24 bits del tamaño del mapa con ``pixel(x, y) -> (r, g, b)`` (``y`` = fila desde arriba)."""
    width, height = MAP_SIZE
    stride = (width * 3 + 3) & ~3
    rows = []
    for y in range(height - 1, -1, -1):
        row = bytearray()
        for x in range(width):
            r, g, b = pixel(x, y)
            row += bytes((b, g, r))
        row += b"\0" * (stride - len(row))
        rows.append(bytes(row))
    data = b"".join(rows)
    header = (b"BM" + (54 + len(data)).to_bytes(4, "little") + b"\0\0\0\0" + (54).to_bytes(4, "little")
              + (40).to_bytes(4, "little") + width.to_bytes(4, "little") + height.to_bytes(4, "little")
              + (1).to_bytes(2, "little") + (24).to_bytes(2, "little") + b"\0" * 4 + len(data).to_bytes(4, "little")
              + (2835).to_bytes(4, "little") * 2 + b"\0" * 8)
    return header + data


def _small_indexed_bmp() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("P", (MAP_SIZE[0] // 2, MAP_SIZE[1] // 2)).save(buffer, "BMP")
    return buffer.getvalue()


class Case(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def problems(self, *, clean=True, game_files=None, drop=()):
        with build_map_minigame(clean=clean, game_files=game_files, drop=drop) as game:
            snapshot = game.snapshot()
            return check_map(build_context(snapshot, build_index(snapshot, None)))

    def found(self, code, **kwargs):
        problems = [p for p in self.problems(**kwargs) if p.code == code]
        self.assertTrue(problems, f"no salió {code}")
        for problem in problems:
            self.assertEqual(problem.severity, CODES[code], code)
        return [dict(p.args) for p in problems]


class CleanMapTests(Case):
    def test_the_clean_minigame_only_has_its_known_warnings(self):
        found = {(p.code, str(p.rel)) for p in self.problems()}
        self.assertEqual(found, {
            ("province_file_name", "history/provinces/south/2  Llanura.txt"),
            ("sea_start_duplicate", "map/default.map"),
            ("definition_bad_number", "map/definition.csv"),
            ("bmp_color_unmapped", "map/provinces.bmp"),
            ("region_not_contiguous", "map/region.txt"),
        })

    def test_every_new_code_is_a_registered_rule_with_texts(self):
        rules = discover_rules()
        for code in NEW_CODES:
            with self.subTest(code=code):
                self.assertIn(code, rules)
                self.assertIn(code, CODES)


class DefinitionTests(Case):
    def test_bad_number(self):
        args = self.found("definition_bad_number")
        self.assertEqual(args, [{"province": "5", "text": "50.", "value": 50}])

    def test_duplicate_color_id_and_bad_row(self):
        extra = "13;200;10;10;Copia;x\r\n2;1;2;3;Otra dos;x\r\n14;rojo;verde;azul;x;x\r\n"
        files = {"map/definition.csv": _definition_csv() + extra}
        problems = self.problems(game_files=files)
        codes = {p.code for p in problems}
        self.assertTrue({"definition_duplicate_color", "definition_duplicate_id", "definition_bad_row"} <= codes,
                        codes)


class RasterTests(Case):
    def test_bmp_size_mismatch(self):
        args = self.found("bmp_size_mismatch", game_files={"map/rivers.bmp": _small_indexed_bmp()})
        self.assertEqual(args[0]["file"], "rivers.bmp")
        self.assertEqual((args[0]["expected_width"], args[0]["expected_height"]), MAP_SIZE)

    def test_province_without_pixels(self):
        files = {"map/definition.csv": _definition_csv() + "13;1;250;250;Sin pixeles;x\r\n",
                 "map/default.map": DEFAULT_MAP.replace("max_provinces = 13", "max_provinces = 14")}
        self.assertIn({"province": "13"}, self.found("province_without_pixels", game_files=files))

    def test_province_fragmented(self):
        def pixel(x, y):
            if (x, y) == (60, 4):                  # un píxel de la 1 dentro del mar 9
                return PROVINCE_COLORS[1]
            province = province_at(x, y)
            return (7, 7, 7) if province is None else PROVINCE_COLORS[province]
        args = self.found("province_fragmented", game_files={"map/provinces.bmp": _bmp24(pixel)})
        self.assertIn("1", [a["province"] for a in args])

    def test_terrain_sea_mismatch(self):
        def index_at(x, y):                         # la provincia 6, toda de agua en terrain.bmp
            return TERRAIN_OCEAN if province_at(x, y) == 6 else terrain_index_at(x, y)
        args = self.found("terrain_sea_mismatch", game_files={"map/terrain.bmp": indexed_bmp(index_at)})
        self.assertEqual([a["province"] for a in args], ["6"])
        self.assertEqual(args[0]["terrain"], "ocean")


class DefaultMapTests(Case):
    def test_max_provinces_too_small(self):
        files = {"map/default.map": DEFAULT_MAP.replace("max_provinces = 13", "max_provinces = 6")}
        args = self.found("max_provinces_too_small", game_files=files)
        self.assertEqual(args[0]["max"], 6)

    def test_sea_start_unknown_and_duplicate(self):
        files = {"map/default.map": DEFAULT_MAP.replace("9 10 10 11 12", "9 10 10 11 12 99")}
        self.assertIn({"province": "99"}, self.found("sea_start_unknown", game_files=files))
        self.assertIn({"province": "10", "count": 2}, self.found("sea_start_duplicate"))


class GroupTests(Case):
    def test_region_empty(self):
        files = {"map/region.txt": _crlf("AAA_1 = { 1 2 3 }\nBBB_4 = { 4 5 6 }\nCCC_7 = { 7 8 }\nVACIO_9 = { }\n")}
        self.assertIn({"region": "VACIO_9"}, self.found("region_empty", game_files=files))

    def test_region_not_contiguous(self):
        self.assertIn({"region": "BBB_4", "apart": "5 6"}, self.found("region_not_contiguous"))

    def test_climate_layout(self):
        files = {"map/climate.txt": _crlf("mild_climate = {\n\tfarm_rgo_size = 0.0\n}\nmild_climate = { 1 2 3 4 }\n"
                                          "harsh_climate = {\n\tfarm_rgo_size = -0.1\n}\n"
                                          "harsh_climate = { 5 6 7 8 }\nlost_climate = {\n\tfarm_rgo_size = 0\n}\n")}
        args = self.found("climate_layout", game_files=files)
        self.assertEqual(args[0]["climate"], "lost_climate")


class FileTests(Case):
    def test_positions_missing(self):
        files = {"map/positions.txt": _crlf("1 = {\n\tunit = {\n\t\tx = 5.000\n\t\ty = 5.000\n\t}\n}\n")}
        missing = {a["province"] for a in self.found("positions_missing", game_files=files)}
        self.assertTrue({"2", "8"} <= missing, missing)
        self.assertNotIn("1", missing)

    def test_missing_history(self):
        args = self.found("missing_history", drop=("history/provinces/east/8 - Cumbre.txt",))
        self.assertIn({"province": "8"}, args)

    def test_province_file_name(self):
        args = self.found("province_file_name")
        self.assertEqual(args, [{"province": "2", "file": "2  Llanura.txt"}])


class AdjacencyTests(Case):
    def test_unknown_province_bad_type_and_through_not_sea(self):
        extra = "1;99;sea;9;0;Al vacío\r\n3;7;puente;0;0;Tipo raro\r\n1;4;sea;2;0;Por tierra\r\n"
        problems = self.problems(game_files={"map/adjacencies.csv": ADJACENCIES_CSV + extra})
        by_code = {}
        for problem in problems:
            by_code.setdefault(problem.code, []).append(dict(problem.args))
        self.assertIn({"province": "99"}, by_code.get("adjacency_unknown_province", []))
        self.assertIn("puente", [a.get("type") for a in by_code.get("adjacency_bad_type", [])])
        through = by_code.get("adjacency_through_not_sea", [])
        self.assertTrue(any(str(a["province"]) == "2" for a in through), through)

    def test_canals_are_not_checked_for_a_sea_through(self):
        problems = self.problems()
        self.assertNotIn("adjacency_through_not_sea", {p.code for p in problems})


class SeverityTests(unittest.TestCase):
    def test_the_twenty_codes_and_their_severities(self):
        self.assertEqual(len(NEW_CODES), 20)
        self.assertEqual(CODES["province_fragmented"], Severity.INFO)
        self.assertEqual(CODES["region_not_contiguous"], Severity.INFO)
        self.assertNotIn("missing_prov_localisation", CODES)


if __name__ == "__main__":
    unittest.main()
