"""Tablas ``;`` sin pérdidas (``core/tablecsv.py``, wizard §4.1 y H4)."""

import codecs
import difflib
import pickle
import random
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import vanilla_root  # noqa: E402

from vic2studio.core.encoding import UnencodableTextError  # noqa: E402
from vic2studio.core.tablecsv import (  # noqa: E402
    TABLE_VALUE_NEWLINE,
    TABLE_VALUE_SEPARATOR,
    RowKind,
    Table,
    TableValueError,
    cell_int,
)

SAMPLE = (b"#From;To;Type;Through;Data;Comment\r\n#\r\n# Estrechos de prueba\r\n"
          b"1;2;sea;10;0;Paso del norte\r\n\r\n3;4;canal;11;1;Canal\r\n")


def roundtrip(data: bytes) -> bytes:
    return Table.from_bytes(data).to_bytes()


def changed_lines(before: bytes, after: bytes) -> list[str]:
    a = before.decode("cp1252").splitlines(keepends=True)
    b = after.decode("cp1252").splitlines(keepends=True)
    return [line for line in difflib.ndiff(a, b) if line[:1] in "+-"]


class RoundTripTests(unittest.TestCase):
    def test_exact_bytes_for_awkward_inputs(self):
        cases = {
            "crlf": SAMPLE,
            "lf": SAMPLE.replace(b"\r\n", b"\n"),
            "mezcla": b"a;1\r\nb;2\nc;3\r\n",
            "sin salto final": b"a;1\r\nb;2",
            "cr suelto dentro": b"a;1\rb;2\r\nc;3\r\n",
            "solo cr": b"a;1\rb;2\r",
            "vacío": b"",
            "en blanco": b"\r\n\r\n   \r\n",
            "bom utf-8": codecs.BOM_UTF8 + b"province;red\r\n1;2\r\n",
            "bom repetido": codecs.BOM_UTF8 * 2 + b"a;1\r\n",
            "cp1252": "1;2;3;4;Mérida;x\r\n".encode("cp1252"),
            "bytes indefinidos": b"1;\x81\x8d\x8f\x90\x9d;x\r\n",
            "punto y coma al final": b"1;2;3;\r\n;;;\r\n",
        }
        for name, data in cases.items():
            with self.subTest(caso=name):
                self.assertEqual(roundtrip(data), data)

    def test_random_inputs(self):
        rng = random.Random(1861)
        alphabet = [b"a", b"1", b";", b"\r", b"\n", b"\r\n", b"#", b" ", b"\xe9", b"."]
        for _ in range(2000):
            data = b"".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
            self.assertEqual(roundtrip(data), data, data)

    def test_rows_split_only_on_lf(self):
        table = Table.from_bytes(b"a;1\rb;2\r\nc;3")
        self.assertEqual([r.raw for r in table.rows], ["a;1\rb;2", "c;3"])
        self.assertEqual([r.newline for r in table.rows], ["\r\n", ""])
        self.assertEqual([r.line for r in table.rows], [1, 2])

    def test_kinds(self):
        table = Table.from_bytes(SAMPLE)
        self.assertEqual([r.kind for r in table.rows], [RowKind.COMMENT, RowKind.COMMENT, RowKind.COMMENT,
                                                        RowKind.DATA, RowKind.BLANK, RowKind.DATA])
        self.assertEqual([r.fields[0] for r in table.data_rows()], ["1", "3"])


class EditTests(unittest.TestCase):
    def test_set_changes_one_line_only(self):
        table = Table.from_bytes(SAMPLE)
        row = list(table.data_rows())[1]
        row.set(4, "7")
        after = table.to_bytes()
        self.assertEqual(changed_lines(SAMPLE, after), ["- 3;4;canal;11;1;Canal\r\n", "+ 3;4;canal;11;7;Canal\r\n"])

    def test_set_beyond_the_last_column_adds_empty_cells(self):
        table = Table.from_bytes(b"1;2\r\n")
        table.rows[0].set(4, "x")
        self.assertEqual(table.to_bytes(), b"1;2;;;x\r\n")

    def test_bad_values_change_nothing(self):
        table = Table.from_bytes(SAMPLE)
        row = list(table.data_rows())[0]
        for value, code in ((";", TABLE_VALUE_SEPARATOR), ("a\nb", TABLE_VALUE_NEWLINE),
                            ("a\rb", TABLE_VALUE_NEWLINE)):
            with self.subTest(valor=value):
                with self.assertRaises(TableValueError) as caught:
                    row.set(1, value)
                self.assertEqual(caught.exception.code, code)
                with self.assertRaises(TableValueError):
                    table.append(["1", value])
        self.assertEqual(table.to_bytes(), SAMPLE)
        error = TableValueError(TABLE_VALUE_SEPARATOR, "a;b")
        copy = pickle.loads(pickle.dumps(error))
        self.assertEqual((copy.code, copy.value, str(copy)), (error.code, error.value, str(error)))

    def test_append_and_insert_use_the_predominant_newline(self):
        table = Table.from_bytes(b"a;1\nb;2\r\nc;3\r\n")
        table.append(["d", "4"])
        table.insert(0, ["z", "0"])
        self.assertEqual(table.to_bytes(), b"z;0\r\na;1\nb;2\r\nc;3\r\nd;4\r\n")
        self.assertEqual([r.line for r in table.rows], [1, 2, 3, 4, 5])

    def test_append_keeps_a_missing_final_newline(self):
        table = Table.from_bytes(b"a;1\nb;2")
        table.append(["c", "3"])
        self.assertEqual(table.to_bytes(), b"a;1\nb;2\nc;3")
        table.remove(table.rows[-1])
        self.assertEqual(table.to_bytes(), b"a;1\nb;2")

    def test_unencodable_value_is_reported_when_rendering(self):
        table = Table.from_bytes(b"1;2\r\n")
        table.rows[0].set(1, "Ω")
        with self.assertRaises(UnencodableTextError):
            table.to_bytes()


class CellIntTests(unittest.TestCase):
    def test_atoi_style(self):
        cases = {"223.": 223, "223": 223, " 12abc": 12, "+5": 5, "-7x": -7, "\t3": 3, "": None, "abc": None,
                 "-": None, ". 3": None, "0": 0, "007": 7}
        for text, expected in cases.items():
            with self.subTest(texto=text):
                self.assertEqual(cell_int(text), expected)


class CorpusTests(unittest.TestCase):
    def test_vanilla_tables_round_trip(self):
        game = vanilla_root()
        if game is None:
            self.skipTest("sin el juego base (VIC2_CORPUS)")
        for rel in ("map/definition.csv", "map/adjacencies.csv"):
            with self.subTest(archivo=rel):
                data = (game / rel).read_bytes()
                start = time.perf_counter()
                self.assertEqual(roundtrip(data), data)
                print(f"\n[tablecsv] {rel}: {(time.perf_counter() - start) * 1000:.1f} ms", end="")


if __name__ == "__main__":
    unittest.main()
