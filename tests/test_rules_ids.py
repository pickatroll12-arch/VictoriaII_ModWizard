"""``core.rules``: identificadores, nombres de archivo y colores (wizard §9)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.rules import colors, ids, names  # noqa: E402


class TagTests(unittest.TestCase):
    def test_valid_and_invalid_tags(self):
        for tag in ("PRU", "A01", "SIL", "D01", "ZZZ"):
            with self.subTest(tag=tag):
                self.assertIsNone(ids.tag_problem(tag))
        for tag in ("pru", "PR", "PRUS", "1AB", "P-U", "REB", "AND", "NOT", "ALL", "ANY", "THIS", "FROM",
                    "CON", "PRN", "AUX", "NUL", "", None, "ÑAN"):
            with self.subTest(tag=tag):
                self.assertEqual(ids.tag_problem(tag), ids.TAG_INVALID)

    def test_dynamic_tags(self):
        self.assertTrue(ids.DYNAMIC_TAG_RE.fullmatch("D01"))
        self.assertIsNone(ids.DYNAMIC_TAG_RE.fullmatch("DAB"))

    def test_province_and_event_ids(self):
        self.assertIsNone(ids.province_id_problem(1, 3249))
        self.assertIsNone(ids.province_id_problem(3248, 3249))
        for value in (0, -1, 3249, 5000, True, "3"):
            with self.subTest(value=value):
                self.assertEqual(ids.province_id_problem(value, 3249), ids.PROVINCE_ID_INVALID)
        self.assertIsNone(ids.event_id_problem(111011928))
        self.assertIsNone(ids.event_id_problem(2**31 - 1))
        for value in (0, -5, 2**31, False):
            with self.subTest(value=value):
                self.assertEqual(ids.event_id_problem(value), ids.EVENT_ID_INVALID)


class NameTests(unittest.TestCase):
    def test_clean_file_name(self):
        self.assertEqual(names.clean_file_name('Gran: "Colombia"?'), "Gran Colombia")
        self.assertEqual(names.clean_file_name("Reino de Kongo. "), "Reino de Kongo")
        self.assertEqual(names.clean_file_name("a/b\\c|d*e<f>g"), "abcdefg")
        self.assertEqual(names.clean_file_name("tab\tcontrol\x01"), "tabcontrol")
        self.assertEqual(names.clean_file_name("CON"), "CON_")
        self.assertEqual(names.clean_file_name("nul.txt"), "nul_.txt")
        self.assertEqual(names.clean_file_name("...  "), names.FALLBACK_NAME)
        self.assertEqual(names.clean_file_name("Österreich"), "Österreich")

    def test_country_file_name(self):
        self.assertEqual(names.country_file_name("Prussia"), "Prussia.txt")
        self.assertEqual(names.country_file_name("United Baltic Provinces"), "United Baltic Provinces.txt")
        self.assertEqual(names.country_file_name("Silesia.txt"), "Silesia.txt")
        self.assertEqual(names.country_file_name("Aux"), "Aux_.txt")
        self.assertEqual(names.country_file_name("Bad?Name."), "BadName.txt")


class ColorTests(unittest.TestCase):
    def test_parse_color(self):
        self.assertEqual(colors.parse_color(["10", "20", "30"]), (10, 20, 30))
        self.assertEqual(colors.parse_color("1 2 3"), (1, 2, 3))
        self.assertEqual(colors.parse_color(["0.8", "0.8", "0"], unit=True), (204, 204, 0))
        self.assertEqual(colors.parse_color(["300", "-5", "1"]), (255, 0, 1))
        self.assertEqual(colors.parse_color(["90", "60", "60"], unit=True), (90, 60, 60), "religión ya en 0–255")
        self.assertIsNone(colors.parse_color(["1", "2"]))
        self.assertIsNone(colors.parse_color(["a", "b", "c"]))

    def test_color_problem(self):
        self.assertIsNone(colors.color_problem(["0", "128", "255"]))
        self.assertIsNone(colors.color_problem(["0", "0.5", "1"], unit=True))
        self.assertEqual(colors.color_problem(["0", "256", "1"]), colors.COLOR_OUT_OF_RANGE)
        self.assertEqual(colors.color_problem(["0", "2", "1"], unit=True), colors.COLOR_OUT_OF_RANGE)
        self.assertEqual(colors.color_problem(["0", "1"]), colors.COLOR_MALFORMED)
        self.assertEqual(colors.color_problem(["x", "1", "2"]), colors.COLOR_MALFORMED)
        self.assertEqual(colors.FORBIDDEN_PROVINCE_COLORS, {(0, 0, 0), (255, 255, 255)})


if __name__ == "__main__":
    unittest.main()
