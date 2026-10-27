"""``map/definition.csv`` sin pérdidas (``core/map/definition.py``, wizard §16.1 y H4)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import vanilla_root  # noqa: E402

from vic2studio.core.map.definition import (  # noqa: E402
    DEFINITION_BAD_ROW,
    DEFINITION_DUPLICATE_COLOR,
    DEFINITION_DUPLICATE_ID,
    DefinitionTable,
)

# Inventado, con la forma del de vanilla: cabecera, un «223.», y filas sin id al final.
SAMPLE = ("province;red;green;blue;x;x\r\n"
          "1;10;20;30;Capital;x\r\n"
          "2;40;50;60.;Llanura;x\r\n"
          "3;70;80;90;Costa;x\r\n"
          ";54;14;244;x;\r\n"
          ";55;14;248;x\r\n").encode("cp1252")


class DefinitionTests(unittest.TestCase):
    def test_parse_tolerates_header_dot_and_rows_without_id(self):
        table, problems = DefinitionTable.parse(SAMPLE)
        self.assertEqual(problems, [])
        self.assertEqual(table.header.raw, "province;red;green;blue;x;x")
        self.assertEqual(table.ids(), [1, 2, 3])
        self.assertEqual(table.rgb_of(2), (40, 50, 60))
        self.assertEqual(table.id_of((70, 80, 90)), 3)
        self.assertIsNone(table.id_of((54, 14, 244)), "una fila sin id no da id")
        rows = table.rows()
        self.assertEqual([r.id for r in rows], [1, 2, 3, None, None])
        self.assertEqual(rows[3].rgb, (54, 14, 244))
        self.assertEqual(rows[1].line, 3)
        with self.assertRaises(KeyError):
            table.rgb_of(99)
        self.assertEqual(table.to_bytes(), SAMPLE)

    def test_problems(self):
        source = ("province;red;green;blue;x;x\n1;1;2;3;A;x\n1;4;5;6;B;x\n2;1;2;3;C;x\n3;a;b;c;D;x\n4;7;8\n")
        _, problems = DefinitionTable.parse(source)
        self.assertEqual([(p.code, p.line, dict(p.args).get("id")) for p in problems],
                         [(DEFINITION_DUPLICATE_ID, 3, 1), (DEFINITION_DUPLICATE_COLOR, 4, 2),
                          (DEFINITION_BAD_ROW, 5, 3), (DEFINITION_BAD_ROW, 6, 4)])
        for problem in problems:
            for lang in ("es", "en"):
                message = problem.message(lang)
                self.assertNotIn("issue.", message)
                self.assertIn(str(problem.args["id"]), message)

    def test_without_header(self):
        table, _ = DefinitionTable.parse("1;10;20;30;A;x\n")
        self.assertIsNone(table.header)
        self.assertEqual(table.ids(), [1])

    def test_add_goes_before_the_rows_without_id(self):
        table, _ = DefinitionTable.parse(SAMPLE)
        self.assertIsNone(table.id_of((1, 2, 3)))
        table.add(4, (1, 2, 3), "Isla")
        lines = table.to_bytes().decode("cp1252").split("\r\n")
        self.assertEqual(lines[4], "4;1;2;3;Isla;x")
        self.assertEqual(lines[5], ";54;14;244;x;")
        self.assertEqual(table.rgb_of(4), (1, 2, 3))
        self.assertEqual(table.id_of((1, 2, 3)), 4)

    def test_add_after_the_header_in_an_empty_table(self):
        table, _ = DefinitionTable.parse("province;red;green;blue;x;x\r\n")
        table.add(1, (9, 9, 9), "A")
        self.assertEqual(table.to_bytes(), b"province;red;green;blue;x;x\r\n1;9;9;9;A;x\r\n")

    def test_set_rgb_changes_only_that_row(self):
        table, _ = DefinitionTable.parse(SAMPLE)
        self.assertEqual(table.rgb_of(2), (40, 50, 60))   # el índice ya existe: editar tiene que renovarlo
        table.set_rgb(2, (1, 1, 1))
        before = SAMPLE.decode("cp1252").split("\r\n")
        after = table.to_bytes().decode("cp1252").split("\r\n")
        self.assertEqual([i for i, (a, b) in enumerate(zip(before, after)) if a != b], [2])
        self.assertEqual(after[2], "2;1;1;1;Llanura;x")
        self.assertEqual(table.rgb_of(2), (1, 1, 1))
        self.assertIsNone(table.id_of((40, 50, 60)))


class CorpusTests(unittest.TestCase):
    def test_vanilla_definition(self):
        game = vanilla_root()
        if game is None:
            self.skipTest("sin el juego base (VIC2_CORPUS)")
        data = (game / "map/definition.csv").read_bytes()
        table, problems = DefinitionTable.parse(data)
        self.assertEqual(table.to_bytes(), data)
        self.assertEqual(problems, [])
        self.assertEqual(table.ids(), list(range(1, 3249)))
        self.assertEqual(sum(1 for r in table.rows() if r.id is None), 56)
        self.assertEqual(table.rgb_of(1825), (208, 17, 223))   # «223.» al estilo atoi (H4)
        self.assertEqual(len({r.rgb for r in table.rows() if r.id is not None}), 3248)


if __name__ == "__main__":
    unittest.main()
