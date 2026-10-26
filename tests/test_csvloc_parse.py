import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.csvloc import (  # noqa: E402
    END_MARKER,
    LANGUAGE_CODES,
    LANGUAGE_COLUMNS,
    LocalisationFile,
    RowKind,
    from_json,
    parse_csv,
    read_csv_file,
    to_json,
    to_source,
)
from vic2studio.core.encoding import encode_text  # noqa: E402

FULL = "KEY;English;French;German;;Spanish;;;;;;;;;x;;;;"

EDGE_TEXTS = {
    "crlf": f"{FULL}\r\nB;b;;;;;;;;;;;;;x\r\n",
    "lf": "A;a;;;;;;;;;;;;;x\nB;b;;;;;;;;;;;;;x\n",
    "no_final_newline": "A;a;;;;;;;;;;;;;x\r\nB;b;;;;;;;;;;;;;x",
    "mixed_newlines": "A;1\r\nB;2\nC;3\r\nD;4",
    "only_semicolon": ";\r\n",
    "only_semicolons": ";;;;;;;;;;;;;;x\r\n",
    "empty_key": ";Hello;;;;;;;;;;;;;x\r\n",
    "short_rows": "A;a\r\nB\r\nC;;\r\n",
    "comments": "#;;;;;;;;;;;;;;x;;;;\r\n# Header; with; semicolons\r\nK;v;;;;;;;;;;;;;x\r\n",
    "blank_lines": "\r\n\r\nK;v\r\n   \r\n\t\r\n",
    "x_in_middle": "K;Max x Min;x marks;;;;;;;;;;;;x\r\n",
    "lone_cr": "K;a\rb;c\r\nL;d\r",
    "empty": "",
    "only_newline": "\r\n",
    "header": "key;English;French;German;Polish;Spanish;Italian;Swedish;Czech;Hugarian;Dutch;Portuguese;Russian;Finish\r\n",
    "quotes": 'K;"Text; with semicolon";;;;Spanish;;;;;;;;\r\nL;"Plain";;;;;;;;;;;;;x\r\n',
}


class ParseTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(len(LANGUAGE_COLUMNS), 13)
        self.assertEqual(LANGUAGE_COLUMNS[LANGUAGE_CODES["es"] - 1], "Spanish")
        self.assertEqual(LANGUAGE_CODES["fi"], 13)
        self.assertEqual(END_MARKER, "x")

    def test_data_row_structure(self):
        file = parse_csv(FULL + "\r\n")
        row = file.rows[0]
        self.assertIs(row.kind, RowKind.DATA)
        self.assertEqual(row.key, "KEY")
        self.assertEqual(len(row.fields), 18)
        self.assertEqual(row.fields[13:], ["x", "", "", "", ""])
        self.assertEqual((row.line, row.raw, row.modified), (1, FULL, False))
        self.assertTrue(row.has_end_marker)
        self.assertEqual(row.get("es"), "Spanish")
        self.assertEqual(row.get("Spanish"), "Spanish")
        self.assertEqual(row.get("SPANISH"), "Spanish")
        self.assertEqual(row.get(5), "Spanish")
        self.assertEqual(row.get(0), "KEY")
        self.assertEqual(row.get("pl"), "")
        self.assertEqual(row.get(99), "")
        with self.assertRaises(ValueError):
            row.get("klingon")
        self.assertEqual((file.encoding, file.newline, file.trailing_newline), ("cp1252", "\r\n", True))

    def test_every_edge_case_round_trips(self):
        for name, text in EDGE_TEXTS.items():
            with self.subTest(name):
                file = parse_csv(text)
                self.assertEqual(to_source(file), text)
                self.assertEqual(to_source(from_json(to_json(file))), text)
                self.assertEqual(to_source(from_json(json.loads(json.dumps(to_json(file))))), text)

    def test_line_kinds(self):
        file = parse_csv(EDGE_TEXTS["comments"] + EDGE_TEXTS["blank_lines"])
        kinds = [row.kind for row in file.rows]
        self.assertEqual(kinds, [RowKind.COMMENT, RowKind.COMMENT, RowKind.DATA, RowKind.BLANK,
                                 RowKind.BLANK, RowKind.DATA, RowKind.BLANK, RowKind.BLANK])
        self.assertEqual(file.rows[1].raw, "# Header; with; semicolons")
        self.assertEqual((file.rows[1].key, file.rows[1].fields), ("", []))
        self.assertEqual(file.rows[6].raw, "   ")
        self.assertEqual([row.line for row in file.rows], list(range(1, 9)))

    def test_only_semicolon_line(self):
        row = parse_csv(";").rows[0]
        self.assertEqual((row.kind, row.key, row.fields), (RowKind.DATA, "", [""]))
        self.assertEqual(to_source(parse_csv(";")), ";")

    def test_short_rows(self):
        file = parse_csv(EDGE_TEXTS["short_rows"])
        self.assertEqual([(r.key, r.fields) for r in file.rows], [("A", ["a"]), ("B", []), ("C", ["", ""])])
        self.assertEqual(file.get("A", "es"), "")
        self.assertFalse(file.rows[0].has_end_marker)

    def test_x_inside_text_is_not_a_marker(self):
        row = parse_csv(EDGE_TEXTS["x_in_middle"]).rows[0]
        self.assertEqual(row.get("en"), "Max x Min")
        self.assertEqual(row.get("fr"), "x marks")
        self.assertTrue(row.has_end_marker)
        literal = parse_csv("K;a;b;x;;;;;;;;;;;x").rows[0]
        self.assertEqual(literal.get("de"), "x")
        self.assertTrue(literal.has_end_marker)

    def test_newlines(self):
        self.assertEqual(parse_csv(EDGE_TEXTS["lf"]).newline, "\n")
        mixed = parse_csv(EDGE_TEXTS["mixed_newlines"])
        self.assertEqual(mixed.newline, "\r\n")
        self.assertEqual([row.newline for row in mixed.rows], [None, "\n", None, None])
        self.assertFalse(mixed.trailing_newline)
        # Sin saltos se asume CRLF, el estilo de vanilla.
        self.assertEqual(parse_csv("K;v").newline, "\r\n")

    def test_lone_cr_is_content(self):
        file = parse_csv(EDGE_TEXTS["lone_cr"])
        self.assertEqual(file.rows[0].fields, ["a\rb", "c"])
        self.assertEqual(file.rows[1].fields, ["d\r"])
        self.assertFalse(file.trailing_newline)

    def test_empty_inputs(self):
        empty = parse_csv("")
        self.assertEqual((empty.rows, empty.diagnostics, to_source(empty)), ([], [], ""))
        only = parse_csv("\r\n")
        self.assertEqual([row.kind for row in only.rows], [RowKind.BLANK])

    def test_bom_in_text(self):
        file = parse_csv("﻿K;v;;;;;;;;;;;;;x\r\n")
        self.assertEqual((file.encoding, file.rows[0].key), ("utf-8-sig", "K"))
        self.assertEqual(encode_text(to_source(file), file.encoding), b"\xef\xbb\xbfK;v;;;;;;;;;;;;;x\r\n")

    def test_filename_sets_path(self):
        self.assertEqual(parse_csv("K;v", filename="loc/a.csv").path, Path("loc/a.csv"))
        self.assertIsNone(parse_csv("K;v").path)

    def test_keys_and_get_row(self):
        file = parse_csv("A;first\r\nB;b\r\nA;second\r\n")
        self.assertEqual(file.keys(), ["A", "B"])
        self.assertEqual(file.get_row("A").get("en"), "first")
        self.assertIsNone(file.get_row("missing"))
        self.assertIsNone(file.get("missing", "en"))
        self.assertIn("B", file)
        self.assertNotIn("C", file)

    def test_new_file_defaults(self):
        file = LocalisationFile()
        self.assertEqual((file.encoding, file.newline, file.trailing_newline), ("cp1252", "\r\n", True))
        self.assertEqual(to_source(file), "")


class FileReadTests(unittest.TestCase):
    def _read(self, raw: bytes):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loc.csv"
            path.write_bytes(raw)
            file = read_csv_file(path)
            self.assertEqual(file.path, path)
            return file

    def test_bytes_round_trip(self):
        samples = [
            "K;País;Pays;Land;;España;;;;;;;;;x;;;;\r\n".encode("cp1252"),
            b"\xef\xbb\xbfK;Espa\xc3\xb1a;;;;;;;;;;;;;x\r\n",
            "K;España\n".encode("utf-8"),
            bytes([0x4B, 0x3B, 0x81, 0x8D, 0x8F, 0x90, 0x9D, 0xE9]),
        ]
        for raw in samples:
            with self.subTest(raw=raw[:20]):
                file = self._read(raw)
                self.assertEqual(encode_text(to_source(file), file.encoding), raw)

    def test_detected_encodings(self):
        self.assertEqual(self._read("K;é\r\n".encode("cp1252")).encoding, "cp1252")
        self.assertEqual(self._read("K;é\r\n".encode("utf-8")).encoding, "utf-8")
        bom = self._read(b"\xef\xbb\xbfK;v\r\n")
        self.assertEqual((bom.encoding, bom.rows[0].key), ("utf-8-sig", "K"))

    def test_explicit_utf8_keeps_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loc.csv"
            path.write_bytes(b"\xef\xbb\xbfK;v\r\n")
            file = read_csv_file(path, encoding="utf-8")
            self.assertEqual(file.encoding, "utf-8-sig")
            self.assertEqual(encode_text(to_source(file), file.encoding), path.read_bytes())


class JsonTests(unittest.TestCase):
    def test_shape(self):
        file = parse_csv("#c;x\r\nK;v;;;;;;;;;;;;;x;;\r\n\r\n  \n")
        obj = to_json(file)
        self.assertEqual(obj["encoding"], "cp1252")
        self.assertEqual(obj["newline"], "\r\n")
        self.assertIs(obj["trailing_newline"], True)
        self.assertEqual(obj["rows"], [
            {"kind": "comment", "text": "#c;x"},
            {"kind": "data", "key": "K", "fields": ["v"] + [""] * 12 + ["x", "", ""]},
            {"kind": "blank"},
            {"kind": "blank", "text": "  ", "newline": "\n"},
        ])

    def test_from_json_builds_usable_file(self):
        file = from_json({"encoding": "cp1252", "newline": "\n", "trailing_newline": False,
                          "rows": [{"kind": "data", "key": "K", "fields": ["Hi", "", "", "", "Hola"]}]})
        self.assertEqual(to_source(file), "K;Hi;;;;Hola")
        self.assertEqual(file.get("K", "es"), "Hola")
        self.assertEqual(file.rows[0].line, 1)
        self.assertFalse(file.modified)
        self.assertEqual({d.code for d in file.diagnostics}, {"too_few_columns", "missing_end_marker"})

    def test_from_json_defaults(self):
        file = from_json({"rows": []})
        self.assertEqual((file.encoding, file.newline, file.trailing_newline), ("cp1252", "\r\n", True))

    def test_from_json_rejects_invalid(self):
        bad_rows = [
            {"kind": "data", "key": "K", "fields": ["a;b"]},
            {"kind": "data", "key": "K;L", "fields": []},
            {"kind": "data", "key": "K", "fields": ["a\nb"]},
            {"kind": "data", "key": "K", "fields": [1]},
            {"kind": "data", "key": "#K", "fields": ["a"]},
            {"kind": "data", "key": "", "fields": []},
            {"kind": "data", "key": "K", "fields": ["a\r"]},
            {"kind": "comment", "text": "no hash"},
            {"kind": "blank", "text": "text"},
            {"kind": "other"},
            {"kind": "data", "key": "K", "fields": [], "newline": "\r"},
            "not an object",
        ]
        for row in bad_rows:
            with self.subTest(row=row):
                with self.assertRaises(ValueError):
                    from_json({"rows": [row, {"kind": "blank"}]})
        for obj in ({"newline": "\r"}, {"encoding": "no-such-codec"}, {"trailing_newline": "yes"},
                    {"rows": {}}, []):
            with self.subTest(obj=obj):
                with self.assertRaises(ValueError):
                    from_json(obj)

    def test_invariant_after_edits(self):
        file = parse_csv(EDGE_TEXTS["crlf"] + "C;c")
        file.set("KEY", "es", "Nuevo")
        file.add_row("NEW", {"en": "New"})
        file.remove_row("B")
        self.assertEqual(to_source(from_json(to_json(file))), to_source(file))


if __name__ == "__main__":
    unittest.main()
