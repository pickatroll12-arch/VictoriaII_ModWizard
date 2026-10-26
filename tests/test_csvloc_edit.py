import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.csvloc import (  # noqa: E402
    InvalidFieldError,
    LocalisationFile,
    LocRow,
    RowKind,
    parse_csv,
    read_csv_file,
    to_source,
    write_csv_file,
)
from vic2studio.core.csvloc.model import normalized_fields  # noqa: E402
from vic2studio.core.encoding import UnencodableTextError  # noqa: E402

EMPTY_13 = ";" * 13


def row_of(line: str) -> LocRow:
    return parse_csv(line).rows[0]


class RowEditTests(unittest.TestCase):
    def test_set_keeps_extras_after_marker(self):
        row = row_of("K;Hello;Bonjour;Hallo;;Hola;;;;;;;;;x;;;;")
        row.set("es", "Buenas")
        self.assertEqual(row.to_line(), "K;Hello;Bonjour;Hallo;;Buenas;;;;;;;;;x;;;;")
        self.assertTrue(row.modified)

    def test_set_adds_missing_marker(self):
        # Filas del mod del usuario: 13 idiomas sin "x".
        row = row_of("AGC;Angoche" + ";" * 12)
        row.set("es", "Angoche ES")
        self.assertEqual(row.to_line(), "AGC;Angoche;;;;Angoche ES;;;;;;;;;x")
        self.assertTrue(row.has_end_marker)

    def test_set_fills_short_rows(self):
        row = row_of("K;a")
        row.set("fi", "suomi")
        self.assertEqual(row.fields, ["a"] + [""] * 11 + ["suomi", "x"])
        self.assertEqual(row.to_line(), "K;a" + ";" * 12 + "suomi;x")

    def test_set_moves_early_marker(self):
        row = row_of("K;en;fr;de;;es;;;;;;x;;;;")
        row.set("de", "DE")
        self.assertEqual(row.to_line(), "K;en;fr;DE;;es;;;;;;;;;x;;;;")

    def test_set_drops_blank_columns_before_late_marker(self):
        row = row_of("K;OK;D'accord;OK;OK;OK;Aceptar;OK;Rendben;OK;;;;;;x;;;")
        row.set("en", "Okay")
        self.assertEqual(row.to_line(), "K;Okay;D'accord;OK;OK;OK;Aceptar;OK;Rendben;OK;;;;;x;;;")

    def test_set_never_drops_text(self):
        row = row_of("K" + ";t" * 15 + ";x")
        row.set("en", "new")
        self.assertEqual(row.fields[:13], ["new"] + ["t"] * 12)
        self.assertEqual(row.fields[13:], ["x", "t", "t"])

    def test_set_same_value_is_not_a_modification(self):
        row = row_of("K;a" + EMPTY_13[:-1] + ";x")
        self.assertTrue(row.has_end_marker)
        row.set("en", "a")
        self.assertFalse(row.modified)

    def test_set_validation(self):
        row = row_of("K;a")
        for text in ("a;b", "line\nbreak", "cr\r"):
            with self.assertRaises(InvalidFieldError):
                row.set("en", text)
        for lang in (0, 14, "xx"):
            with self.assertRaises(ValueError):
                row.set(lang, "t")
        with self.assertRaises(TypeError):
            row.set("en", 5)
        with self.assertRaises(ValueError):
            parse_csv("# comment").rows[0].set("en", "t")
        self.assertEqual(row.to_line(), "K;a")

    def test_normalized_fields_is_pure(self):
        fields = ["a", "x", ""]
        self.assertEqual(normalized_fields(fields), ["a"] + [""] * 12 + ["x", ""])
        self.assertEqual(fields, ["a", "x", ""])


class FileEditTests(unittest.TestCase):
    SOURCE = "#comment;x\r\nA;a" + EMPTY_13 + "x\r\nB;b" + EMPTY_13 + "x\r\nA;dup\r\n"

    def test_set_existing_and_new(self):
        file = parse_csv(self.SOURCE)
        file.set("A", "es", "a es")
        self.assertEqual(file.get("A", "es"), "a es")
        self.assertEqual(file.rows[3].to_line(), "A;dup")  # solo la primera
        row = file.set("NEW", "Spanish", "nuevo")
        self.assertIs(row, file.rows[-1])
        self.assertEqual(row.to_line(), "NEW;;;;;nuevo;;;;;;;;;x")
        self.assertEqual(len(row.fields), 14)
        self.assertIsNone(row.line)
        self.assertTrue(file.modified)
        self.assertTrue(to_source(file).endswith("A;dup\r\nNEW;;;;;nuevo;;;;;;;;;x\r\n"))

    def test_add_row(self):
        file = parse_csv(self.SOURCE)
        row = file.add_row("C", {"en": "c", "French": "c fr", 3: "c de"})
        self.assertEqual(row.to_line(), "C;c;c fr;c de;;;;;;;;;;;x")
        self.assertIs(file.get_row("C"), row)
        with self.assertRaises(KeyError):
            file.add_row("C")
        file.add_row("C", allow_duplicate=True)
        self.assertEqual(sum(1 for r in file.data_rows() if r.key == "C"), 2)
        first = file.add_row("FIRST", {"en": "f"}, index=0)
        self.assertIs(file.rows[0], first)
        for key in ("", " K", "K;L", "#K", "K\n"):
            with self.subTest(key=key):
                with self.assertRaises(InvalidFieldError):
                    file.add_row(key)
        with self.assertRaises(InvalidFieldError):
            file.add_row("D", {"en": "a;b"})
        with self.assertRaises(ValueError):
            file.add_row("D", {"zz": "a"})
        self.assertNotIn("D", file)

    def test_remove_row(self):
        file = parse_csv(self.SOURCE)
        self.assertEqual(file.remove_row("A"), 2)
        self.assertEqual(file.remove_row("A"), 0)
        self.assertEqual(to_source(file), "#comment;x\r\nB;b" + EMPTY_13 + "x\r\n")
        self.assertIsNone(file.get_row("A"))
        self.assertTrue(file.modified)

    def test_append_to_file_without_final_newline(self):
        file = parse_csv("A;a\nB;b")
        file.set("C", "en", "c")
        self.assertEqual(to_source(file), "A;a\nB;b\nC;c;;;;;;;;;;;;;x")

    def test_new_file(self):
        file = LocalisationFile()
        file.add_row("K", {"en": "Hello", "es": "Hola"})
        self.assertEqual(to_source(file), "K;Hello;;;;Hola;;;;;;;;;x\r\n")

    def test_lint_flags_unencodable_text(self):
        file = parse_csv("A;a" + EMPTY_13 + "x\r\n")
        file.set("A", "ru", "Привет")
        diags = [d for d in file.lint() if d.code == "unencodable_character"]
        self.assertEqual(len(diags), 1)
        self.assertEqual((diags[0].line, diags[0].args["count"], diags[0].args["char"]), (1, 6, "П"))
        self.assertEqual(diags[0].column, len("A;a;;;;;;;;;;;") + 1)


class WriteTests(unittest.TestCase):
    def test_write_round_trip_with_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loc.csv"
            original = "A;País;;;;España;;;;;;;;;x;;;;\r\nB;b".encode("cp1252")
            path.write_bytes(original)
            file = read_csv_file(path)
            file.set("A", "es", "Españita")
            backup = write_csv_file(path, file)
            self.assertEqual(backup.read_bytes(), original)
            self.assertEqual(path.read_bytes(), "A;País;;;;Españita;;;;;;;;;x;;;;\r\nB;b".encode("cp1252"))
            self.assertFalse(file.modified)
            self.assertEqual([row.line for row in file.rows], [1, 2])
            self.assertEqual(file.rows[0].raw, "A;País;;;;Españita;;;;;;;;;x;;;;")
            self.assertEqual(to_source(read_csv_file(path)), to_source(file))

    def test_unencodable_text_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loc.csv"
            path.write_bytes(b"A;a\r\n")
            file = read_csv_file(path)
            file.set("A", "en", "Ωmega")
            with self.assertRaises(UnencodableTextError) as ctx:
                write_csv_file(path, file)
            self.assertEqual(ctx.exception.problems[0][1:], (1, 3, "Ω"))
            self.assertEqual(path.read_bytes(), b"A;a\r\n")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["loc.csv"])
            self.assertTrue(file.modified)

    def test_write_new_file_and_convert_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            utf8 = Path(tmp) / "utf8.csv"
            utf8.write_bytes("K;Canción\n".encode("utf-8"))
            file = read_csv_file(utf8)
            self.assertEqual(file.encoding, "utf-8")
            target = Path(tmp) / "sub" / "game.csv"
            self.assertIsNone(write_csv_file(target, file, encoding="cp1252"))
            self.assertEqual(target.read_bytes(), "K;Canción\n".encode("cp1252"))
            self.assertEqual((file.path, file.encoding), (target, "cp1252"))
            self.assertNotIn("non_game_encoding", {d.code for d in file.diagnostics})

    def test_comment_and_blank_factories(self):
        file = parse_csv("A;a\r\n")
        file.rows.append(LocRow.comment("# added"))
        file.rows.append(LocRow.blank())
        self.assertEqual([r.kind for r in file.rows], [RowKind.DATA, RowKind.COMMENT, RowKind.BLANK])
        self.assertEqual(to_source(file), "A;a\r\n# added\r\n\r\n")
        self.assertTrue(file.modified)


if __name__ == "__main__":
    unittest.main()
