import codecs
import gc
import json
import sys
import tempfile
import time
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
    write_csv_file,
)
from vic2studio.core.cancel import Cancelled  # noqa: E402
from vic2studio.core.encoding import UnencodableTextError, encode_text  # noqa: E402
from vic2studio.core.fileio import FileStamp  # noqa: E402

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
    # Doble conversión a CRLF (git autocrlf sobre un CRLF): contenido "x\r" + CRLF.
    "cr_crlf": "A;uno;;;;;;;;;;;;;x\r\r\nB;dos;;;;;;;;;;;;;x\r\r\n",
    "cr_crlf_in_lf_file": "A;1\nB;2\r\r\nC;3\nD;4\n",
    # Solo CR (Mac clásico) o casi: el CSV solo parte filas en LF, el CR es contenido.
    "cr_only": "A;a;;;;;;;;;;;;;x\rB;b;;;;;;;;;;;;;x\r",
    "cr_mostly": "A;1\rB;2\rC;3\nD;4\n",
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
        # H2-CR: aunque predominen los CR sueltos, el salto del archivo es LF o CRLF (el que admite el JSON).
        self.assertEqual(parse_csv(EDGE_TEXTS["cr_mostly"]).newline, "\n")
        self.assertEqual(len(parse_csv(EDGE_TEXTS["cr_only"]).rows), 1)

    def test_content_ending_in_cr_before_crlf(self):
        """FC-1: from_json rechazaba la salida de to_json para las líneas «x\\r\\r\\n»."""
        file = parse_csv(EDGE_TEXTS["cr_crlf"])
        self.assertEqual([(r.fields[-1], r.newline) for r in file.rows], [("x\r", None), ("x\r", None)])
        lf_file = parse_csv(EDGE_TEXTS["cr_crlf_in_lf_file"])
        self.assertEqual((lf_file.newline, lf_file.rows[1].fields, lf_file.rows[1].newline), ("\n", ["2\r"], "\r\n"))

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

    def test_utf16_and_stray_bom(self):
        """P2, LOC-M3: un UTF-16 se leía como cp1252 (claves con NUL) y un BOM delante de cp1252 hacía fallar."""
        utf16 = self._read(codecs.BOM_UTF16_LE + "KEY_A;Hola España;;;;;;;;;;;;;x\r\n".encode("utf-16-le"))
        self.assertEqual((utf16.encoding, utf16.rows[0].key, utf16.rows[0].get("en")), ("utf-16", "KEY_A", "Hola España"))
        self.assertEqual([(d.code, d.severity.value) for d in utf16.diagnostics], [("non_game_encoding", "error")])
        raw = b"\xef\xbb\xbfK;Le\xf3n;;;;;;;;;;;;;x\r\n"
        stray = self._read(raw)
        self.assertEqual((stray.encoding, stray.rows[0].key), ("cp1252", "\u00ef\u00bb\u00bfK"))
        self.assertEqual(encode_text(to_source(stray), stray.encoding), raw)
        self.assertEqual([d.args.get("stray_bom") for d in stray.diagnostics], [True])

    def test_read_keeps_the_file_stamp(self):
        raw = "K;é\r\n".encode("cp1252")
        self.assertEqual(self._read(raw).stamp, FileStamp.of(raw))
        self.assertIsNone(parse_csv("K;v").stamp)

    def test_four_encodings_keep_their_bytes_and_convert_cleanly(self):
        """NF-1: un CSV UTF-16 BE con BOM daba la clave '\\ufeffKEY_A' (get('KEY_A') era None) y no se
        podía convertir a cp1252 (U+FEFF en 1:1). Las cuatro variantes: claves limpias, mismos bytes al
        guardar sin cambiar de codificación y bytes cp1252 exactos al convertir."""
        text = "KEY_A;Hola Espa\u00f1a;;;;Hola;;;;;;;;;x\r\nKEY_B;b;;;;;;;;;;;;;x\r\n"
        variants = {
            "cp1252": text.encode("cp1252"),
            "utf-8-sig": codecs.BOM_UTF8 + text.encode("utf-8"),
            "utf-16": codecs.BOM_UTF16_LE + text.encode("utf-16-le"),
            "utf-16-be-bom": codecs.BOM_UTF16_BE + text.encode("utf-16-be"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for encoding, raw in variants.items():
                with self.subTest(encoding=encoding):
                    path = Path(tmp) / f"{encoding}.csv"
                    path.write_bytes(raw)
                    file = read_csv_file(path)
                    self.assertEqual((file.encoding, file.keys()), (encoding, ["KEY_A", "KEY_B"]))
                    self.assertEqual(file.get("KEY_A", "en"), "Hola Espa\u00f1a")
                    self.assertEqual(to_source(file), text)
                    write_csv_file(path, file, backup=False)
                    self.assertEqual(path.read_bytes(), raw)
                    ansi = Path(tmp) / f"{encoding}-ansi.csv"
                    write_csv_file(ansi, read_csv_file(path), encoding="cp1252", backup=False)
                    self.assertEqual(ansi.read_bytes(), text.encode("cp1252"))
                    # Y al revés: de cp1252 a esta codificación, con su BOM delante.
                    back = Path(tmp) / f"{encoding}-back.csv"
                    write_csv_file(back, read_csv_file(ansi), encoding=encoding, backup=False)
                    self.assertEqual(back.read_bytes(), raw)

    def test_bom_left_by_an_explicit_codec(self):
        """NF-1: con utf-16-le/utf-16-be explícitas el BOM quedaba en la primera clave, como antes con utf-8.
        Un segundo BOM UTF-8 se quitaba también y la ida y vuelta perdía 3 bytes (ver test_repeated_bom)."""
        text = "KEY_A;a;;;;;;;;;;;;;x\r\n"
        explicit = {
            "utf-8": ("utf-8-sig", codecs.BOM_UTF8 + text.encode("utf-8")),
            "utf-16-le": ("utf-16", codecs.BOM_UTF16_LE + text.encode("utf-16-le")),
            "utf-16-be": ("utf-16-be-bom", codecs.BOM_UTF16_BE + text.encode("utf-16-be")),
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loc.csv"
            for asked, (encoding, raw) in explicit.items():
                with self.subTest(asked=asked):
                    path.write_bytes(raw)
                    file = read_csv_file(path, encoding=asked)
                    self.assertEqual((file.encoding, file.rows[0].key), (encoding, "KEY_A"))
                    self.assertEqual(encode_text(to_source(file), file.encoding), raw)
            double = codecs.BOM_UTF8 * 2 + text.encode("utf-8")
            path.write_bytes(double)
            for asked in (None, "utf-8", "utf-8-sig"):
                with self.subTest(double=asked):
                    file = read_csv_file(path, encoding=asked)
                    self.assertEqual((file.encoding, file.extra_boms, file.rows[0].key), ("utf-8-sig", 1, "KEY_A"))
                    write_csv_file(path, file, backup=False)
                    self.assertEqual(path.read_bytes(), double)

    def test_repeated_bom(self):
        """R1: el U+FEFF de un BOM repetido quedaba en la primera clave ('\\ufeffKEY_A': get('KEY_A') era
        None, el lint daba unencodable_character y convertir a cp1252 fallaba) o se perdía al guardar sin
        cambios. Ahora va a ``extra_boms``: clave limpia, mismos bytes al guardar en la misma codificación
        (también tras editar) y, al convertir, se descarta."""
        text = "KEY_A;Hola Espa\u00f1a;;;;Hola;;;;;;;;;x\r\nKEY_B;b;;;;;;;;;;;;;x\r\n"
        edited = text.replace("KEY_B;b;", "KEY_B;c;")
        variants = {
            ("utf-8-sig", 1): codecs.BOM_UTF8 * 2 + text.encode("utf-8"),
            ("utf-8-sig", 2): codecs.BOM_UTF8 * 3 + text.encode("utf-8"),
            ("utf-16", 1): codecs.BOM_UTF16_LE * 2 + text.encode("utf-16-le"),
            ("utf-16-be-bom", 1): codecs.BOM_UTF16_BE * 2 + text.encode("utf-16-be"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            path, out = Path(tmp) / "loc.csv", Path(tmp) / "out.csv"
            for (encoding, extra), raw in variants.items():
                with self.subTest(encoding=encoding, extra=extra):
                    path.write_bytes(raw)
                    file = read_csv_file(path)
                    self.assertEqual((file.encoding, file.extra_boms), (encoding, extra))
                    self.assertEqual(file.keys(), ["KEY_A", "KEY_B"])
                    self.assertEqual(file.get("KEY_A", "en"), "Hola Espa\u00f1a")
                    self.assertEqual({d.code for d in file.diagnostics}, {"non_game_encoding"})
                    self.assertEqual(to_source(file), "\ufeff" * extra + text)
                    self.assertEqual(to_source(from_json(json.loads(json.dumps(to_json(file))))), to_source(file))
                    write_csv_file(path, file, backup=False)
                    self.assertEqual(path.read_bytes(), raw)
                    file.set("KEY_B", "en", "c")
                    write_csv_file(path, file, backup=False)
                    self.assertEqual(path.read_bytes(), encode_text("\ufeff" * extra + edited, encoding))
                    # Si la conversión falla por otro carácter no cambia nada.
                    file.set("KEY_B", "fr", "\u2192")
                    with self.assertRaises(UnencodableTextError):
                        write_csv_file(out, file, encoding="cp1252", backup=False)
                    self.assertEqual((file.encoding, file.extra_boms), (encoding, extra))
                    for target in ("cp1252", "utf-8", "utf-8-sig" if encoding != "utf-8-sig" else "utf-16"):
                        converted = read_csv_file(path)
                        write_csv_file(out, converted, encoding=target, backup=False)
                        self.assertEqual(out.read_bytes(), encode_text(edited, target), target)
                        self.assertEqual((converted.encoding, converted.extra_boms), (target, 0))
            # Con la codificación cambiada a mano (no con ``encoding=``) tampoco los arrastra.
            for target in ("cp1252", "utf-8"):
                with self.subTest(by_hand=target):
                    path.write_bytes(variants[("utf-16", 1)])
                    file = read_csv_file(path)
                    file.encoding = target
                    write_csv_file(out, file, backup=False)
                    self.assertEqual((out.read_bytes(), file.extra_boms), (text.encode(target), 0))
            # Solo BOM: ninguna fila (no una fila de datos con la clave '\ufeff').
            path.write_bytes(codecs.BOM_UTF8 * 2)
            file = read_csv_file(path)
            self.assertEqual((file.rows, file.extra_boms, file.diagnostics[0].code), ([], 1, "non_game_encoding"))
            write_csv_file(path, file, backup=False)
            self.assertEqual(path.read_bytes(), codecs.BOM_UTF8 * 2)

    def test_explicit_utf8_keeps_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loc.csv"
            path.write_bytes(b"\xef\xbb\xbfK;v\r\n")
            file = read_csv_file(path, encoding="utf-8")
            self.assertEqual(file.encoding, "utf-8-sig")
            self.assertEqual(encode_text(to_source(file), file.encoding), path.read_bytes())


class CancelTests(unittest.TestCase):
    """VAL-4: la lectura de un CSV grande debe poder pararse a mitad, también durante el lint."""

    TEXT = "".join(f"K{i};text {i};;;;texto {i};;;;;;x\r\n" for i in range(200_000))

    def test_cancel_inside_a_big_file(self):
        for limit in (1, 3, 49, 60, 120):  # las 49 primeras consultas son de la lectura; las demás, del lint
            with self.subTest(limit=limit):
                calls = []
                with self.assertRaises(Cancelled):
                    parse_csv(self.TEXT, cancelled=lambda: calls.append(1) or len(calls) >= limit)
                self.assertEqual(len(calls), limit)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.csv"
            path.write_bytes(self.TEXT.encode("cp1252"))
            with self.assertRaises(Cancelled):
                read_csv_file(path, cancelled=lambda: True)

    def test_checks_are_frequent(self):
        # Sin el recolector cíclico, cuyas pausas no dependen del núcleo (ui.tasks lo controla en las tareas).
        stamps = []
        if gc.isenabled():
            gc.disable()
            self.addCleanup(gc.enable)
        start = time.perf_counter()
        parse_csv(self.TEXT, cancelled=lambda: stamps.append(time.perf_counter()) and False)
        stamps.append(time.perf_counter())
        gaps = [b - a for a, b in zip([start] + stamps, stamps)]
        self.assertLess(max(gaps), 0.2, f"{len(gaps)} consultas; hueco máximo {max(gaps):.3f} s")


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
        self.assertEqual({d.code for d in file.diagnostics}, {"missing_end_marker"})

    def test_from_json_defaults(self):
        file = from_json({"rows": []})
        self.assertEqual((file.encoding, file.newline, file.trailing_newline), ("cp1252", "\r\n", True))
        self.assertEqual(file.extra_boms, 0)
        self.assertNotIn("extra_boms", to_json(parse_csv("\ufeffK;v")), "solo con BOM repetidos")

    def test_extra_boms(self):
        """R1: los BOM repetidos pasan por el JSON; solo valen con una codificación que lleve BOM."""
        file = from_json({"encoding": "UTF-16", "extra_boms": 2, "rows": [{"kind": "data", "key": "K", "fields": []}]})
        self.assertEqual((file.encoding, file.extra_boms, to_source(file)), ("utf-16", 2, "\ufeff\ufeffK\r\n"))
        self.assertEqual(to_json(file)["extra_boms"], 2)
        for obj in ({"encoding": "utf-8-sig", "extra_boms": -1}, {"encoding": "utf-8-sig", "extra_boms": True},
                    {"encoding": "utf-8-sig", "extra_boms": 1.0}, {"encoding": "utf-8-sig", "extra_boms": "1"},
                    {"encoding": "cp1252", "extra_boms": 1}, {"encoding": "utf-8", "extra_boms": 1}):
            with self.subTest(obj=obj):
                with self.assertRaises(ValueError):
                    from_json(obj)

    def test_from_json_rejects_invalid(self):
        bad_rows = [
            {"kind": "data", "key": "K", "fields": ["a;b"]},
            {"kind": "data", "key": "K;L", "fields": []},
            {"kind": "data", "key": "K", "fields": ["a\nb"]},
            {"kind": "data", "key": "K", "fields": [1]},
            {"kind": "data", "key": "#K", "fields": ["a"]},
            {"kind": "data", "key": "", "fields": []},
            {"kind": "data", "key": "K", "fields": ["a\r"], "newline": "\n"},
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
                    {"rows": {}}, [], {"encoding": "base64"}, {"encoding": "rot13"},
                    {"newline": "\n", "rows": [{"kind": "data", "key": "K", "fields": ["a\r"]}]}):
            with self.subTest(obj=obj):
                with self.assertRaises(ValueError):
                    from_json(obj)
        # Con salto CRLF el "\r" final es contenido legítimo; sin salto (última línea), también.
        for obj in ({"rows": [{"kind": "data", "key": "K", "fields": ["a\r"]}]},
                    {"newline": "\n", "rows": [{"kind": "data", "key": "K", "fields": ["a\r"], "newline": "\r\n"}]},
                    {"newline": "\n", "trailing_newline": False, "rows": [{"kind": "data", "key": "K", "fields": ["a\r"]}]}):
            with self.subTest(obj=obj):
                text = to_source(from_json(obj))
                self.assertEqual(to_source(parse_csv(text)), text)
                self.assertEqual(parse_csv(text).rows[0].fields, ["a\r"])

    def test_invariant_after_edits(self):
        file = parse_csv(EDGE_TEXTS["crlf"] + "C;c")
        file.set("KEY", "es", "Nuevo")
        file.add_row("NEW", {"en": "New"})
        file.remove_row("B")
        self.assertEqual(to_source(from_json(to_json(file))), to_source(file))


if __name__ == "__main__":
    unittest.main()
