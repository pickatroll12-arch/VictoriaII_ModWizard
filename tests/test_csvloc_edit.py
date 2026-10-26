import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.csvloc import (  # noqa: E402
    DuplicateKeyError,
    InvalidFieldError,
    LocalisationFile,
    LocRow,
    RowKind,
    parse_csv,
    read_csv_file,
    to_source,
    write_csv_file,
)
from vic2studio.core.csvloc.diagnostics import EDIT_MESSAGES  # noqa: E402
from vic2studio.core.csvloc.model import column_index, normalized_fields  # noqa: E402
from vic2studio.core.encoding import UnencodableTextError  # noqa: E402
from vic2studio.core.fileio import FileChangedError  # noqa: E402

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

    def test_x_texts_in_visible_columns_are_not_markers(self):
        """FC-11: una «X» en Spanish (un numeral romano) se tomaba por el marcador y se borraba al editar."""
        roman = row_of("ROMAN_10;X;X;X;;X")
        roman.set("en", "X.")
        self.assertEqual([roman.get(lang) for lang in ("en", "fr", "de", "es")], ["X.", "X", "X", "X"])
        self.assertEqual(roman.to_line(), "ROMAN_10;X.;X;X;;X" + ";" * 8 + ";x")
        french = row_of("K;en;x")
        french.set("es", "es")
        self.assertEqual((french.get("fr"), french.get("es"), french.has_end_marker), ("x", "es", True))
        # La «x» minúscula tras los idiomas visibles sí es el marcador temprano de vanilla.
        early = row_of("K;en;fr;de;;es;x")
        early.set("en", "EN")
        self.assertEqual(early.to_line(), "K;EN;fr;de;;es" + ";" * 8 + ";x")

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
        fields = ["a", "", "", "", "", "", "x", ""]
        self.assertEqual(normalized_fields(fields), ["a"] + [""] * 12 + ["x", ""])
        self.assertEqual(fields, ["a", "", "", "", "", "", "x", ""])


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
        with self.assertRaises(DuplicateKeyError) as ctx:
            file.add_row("C")
        self.assertIsInstance(ctx.exception, InvalidFieldError)
        self.assertEqual((ctx.exception.code, ctx.exception.params), ("duplicate_key", {"key": "C"}))

    def test_remove_row(self):
        file = parse_csv(self.SOURCE)
        self.assertEqual(file.remove_row("A"), 2)
        self.assertEqual(file.remove_row("A"), 0)
        self.assertEqual(to_source(file), "#comment;x\r\nB;b" + EMPTY_13 + "x\r\n")
        self.assertIsNone(file.get_row("A"))
        self.assertTrue(file.modified)

    def test_remove_a_single_duplicate(self):
        """FC-8: remove_row quitaba también la definición que usa el juego; rows.remove no marcaba el cambio."""
        file = parse_csv(self.SOURCE)
        duplicate = file.rows[3]
        file.remove(duplicate)
        self.assertTrue(file.modified)
        self.assertEqual(file.get("A", "en"), "a")
        self.assertEqual(to_source(file), self.SOURCE[:-len("A;dup\r\n")])
        with self.assertRaises(ValueError):
            file.remove(duplicate)
        first = file.get_row("A")
        self.assertEqual(file.remove_rows([first, LocRow(RowKind.BLANK)]), 1)
        self.assertIsNone(file.get_row("A"))

    def test_rename_key(self):
        """FC-8: renombrar con row.key dejaba el índice obsoleto y el archivo sin marcar."""
        file = parse_csv(self.SOURCE)
        self.assertEqual(file.rename_key("A", "EVT_1"), 1)
        self.assertTrue(file.modified)
        self.assertEqual(file.get("EVT_1", "en"), "a")
        self.assertEqual(file.get("A", "en"), "dup", "el duplicado pasa a ser la definición de A")
        self.assertEqual(file.rows[1].to_line(), "EVT_1;a" + EMPTY_13 + "x")
        with self.assertRaises(DuplicateKeyError):
            file.rename_key("A", "B")
        self.assertEqual(file.rename_key("missing", "B"), 0)
        self.assertEqual(file.rename_key("A", "B", allow_duplicate=True), 1)
        self.assertEqual(file.get("B", "en"), "b")
        every = parse_csv(self.SOURCE)
        self.assertEqual(every.rename_key("A", "Z", all=True), 2)
        self.assertEqual([r.key for r in every.data_rows()], ["Z", "B", "Z"])
        with self.assertRaises(InvalidFieldError):
            every.rename_key("Z", " Z")

    def test_add_rows_in_bulk(self):
        """FC-2/FC-8: altas en lote, todas o ninguna."""
        file = parse_csv(self.SOURCE)
        rows = file.add_rows([("PROV1", {"en": "One"}), ("PROV2", None)])
        self.assertEqual([file.get_row(k) for k in ("PROV1", "PROV2")], rows)
        for items in ([("OK", None), ("bad;key", None)], [("NEW", None), ("NEW", None)], [("B", None)]):
            with self.subTest(items=items):
                with self.assertRaises(InvalidFieldError):
                    file.add_rows(items)
        self.assertNotIn("OK", file)
        self.assertNotIn("NEW", file)
        middle = file.add_rows([("M1", None), ("M2", None)], index=1)
        self.assertEqual(file.rows[1:3], middle)
        self.assertIs(file.get_row("M2"), middle[1])

    def test_keys_keep_the_order_of_first_appearance(self):
        """R2: una clave nueva insertada en medio con index= quedaba la última en keys()."""
        file = parse_csv(self.SOURCE)
        self.assertEqual(file.keys(), ["A", "B"])
        file.add_row("C", index=0)
        self.assertEqual(file.keys(), ["C", "A", "B"])
        file.add_rows([("D", None), ("E", None)], index=3)
        file.add_comment("# sección", index=1)
        file.add_row("Z")
        file.add_row("B", index=0, allow_duplicate=True)
        self.assertEqual(file.keys(), list(dict.fromkeys(row.key for row in file.data_rows())))
        self.assertEqual(file.keys(), ["B", "C", "A", "D", "E", "Z"])

    def test_inserting_a_duplicate_before_the_first_updates_the_winner(self):
        file = parse_csv(self.SOURCE)
        file.get_row("A")
        new = file.add_row("A", {"en": "new first"}, index=0, allow_duplicate=True)
        self.assertIs(file.get_row("A"), new)
        later = file.add_row("A", {"en": "last"}, allow_duplicate=True)
        self.assertIs(file.get_row("A"), new)
        self.assertIs(file.rows[-1], later)

    def test_many_new_keys_are_fast(self):
        """FC-2: cada add_row reconstruía el índice de claves; 10 000 altas tardaban 6 s."""
        file = LocalisationFile()
        start = time.perf_counter()
        for i in range(10_000):
            file.add_row(f"PROV{i}", {"en": f"Prov {i}"})
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 0.5, f"{elapsed:.2f} s")
        self.assertEqual(file.get("PROV9999", "en"), "Prov 9999")
        self.assertEqual(len(file.keys()), 10_000)
        start = time.perf_counter()
        for i in range(10_000):
            file.set(f"PROV{i}", "es", f"Prov {i} ES")
        self.assertLess(time.perf_counter() - start, 0.5)

    def test_comments_and_blank_lines(self):
        """FC-10: un «comentario» sin '#' se guardaba como fila de datos y uno con salto inyectaba filas."""
        file = parse_csv(self.SOURCE)
        comment = file.add_comment("# Sección: países; con ';'", index=1)
        blank = file.add_blank("  ")
        self.assertEqual((file.rows[1], file.rows[-1]), (comment, blank))
        self.assertTrue(file.modified)
        self.assertEqual(to_source(file).splitlines()[1], "# Sección: países; con ';'")
        for text in ("Sección: países", "# uno\r\nB;inyectada", "#a\rb"):
            with self.subTest(text=text):
                with self.assertRaises(InvalidFieldError):
                    file.add_comment(text)
        for text in ("texto", "\r\n"):
            with self.assertRaises(InvalidFieldError):
                LocRow.blank(text)
        self.assertEqual(len(file.rows), 6)

    def test_lint_survives_rows_with_line_breaks(self):
        """FC-10: lint() lanzaba IndexError si una fila (editada a mano) tenía un salto y un carácter no cp1252."""
        file = parse_csv("A;a\r\n")
        file.rows.append(LocRow(RowKind.COMMENT, raw="# a\nB;b\nC;Ж"))
        codes = [(d.code, d.line) for d in file.lint()]
        self.assertIn(("unencodable_character", 4), codes)

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


class EditErrorTests(unittest.TestCase):
    """FC-9: los errores de edición solo tenían un texto en español, sin código para traducirlos."""

    CASES = {
        "separator_in_text": lambda: parse_csv("K;a").rows[0].set("en", "a;b"),
        "newline_in_text": lambda: parse_csv("K;a").rows[0].set("en", "a\nb"),
        "empty_key": lambda: LocalisationFile().add_row(""),
        "key_whitespace": lambda: LocalisationFile().add_row(" B"),
        "comment_key": lambda: LocalisationFile().add_row("#c"),
        "duplicate_key": lambda: parse_csv("A;a").add_row("A"),
        "unknown_language": lambda: column_index("xx"),
        "invalid_column": lambda: column_index(-1),
        "not_a_language_column": lambda: parse_csv("K;a").rows[0].set(14, "t"),
        "not_a_data_row": lambda: parse_csv("#c").rows[0].set("en", "t"),
        "invalid_comment": lambda: LocRow.comment("sin almohadilla"),
        "invalid_blank": lambda: LocRow.blank("texto"),
    }

    def test_every_error_has_a_code_and_both_languages(self):
        self.assertEqual(set(self.CASES), set(EDIT_MESSAGES["en"]))
        self.assertEqual(set(EDIT_MESSAGES["es"]), set(EDIT_MESSAGES["en"]))
        for code, action in self.CASES.items():
            with self.subTest(code=code):
                with self.assertRaises(InvalidFieldError) as ctx:
                    action()
                error = ctx.exception
                self.assertIsInstance(error, ValueError)
                self.assertEqual(error.code, code)
                texts = {lang: error.message(lang) for lang in ("es", "en")}
                self.assertNotEqual(texts["es"], texts["en"])
                for text in texts.values():
                    self.assertNotIn("{", text)
                    self.assertGreater(len(text), 15)
                self.assertEqual(str(error), texts["es"])
                self.assertEqual(error.message("fr"), texts["en"])
        with self.assertRaises(KeyError):
            self.CASES["duplicate_key"]()


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

    def test_external_changes_are_detected(self):
        """FC-13: guardar pisaba los cambios hechos fuera (Excel, Notepad++) y, al segundo guardado, también el .bak."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loc.csv"
            path.write_bytes(b"A;uno\r\n")
            file = read_csv_file(path)
            path.write_bytes(b"A;uno\r\nB;de Excel\r\n")
            file.set("A", "es", "Uno")
            with self.assertRaises(FileChangedError):
                write_csv_file(path, file)
            self.assertEqual(path.read_bytes(), b"A;uno\r\nB;de Excel\r\n")
            self.assertTrue(file.modified)
            # Guardar como otro archivo no comprueba nada; sobrescribir hay que pedirlo.
            write_csv_file(Path(tmp) / "copia.csv", file)
            file.path = path
            self.assertEqual(write_csv_file(path, file, force=True).read_bytes(), b"A;uno\r\nB;de Excel\r\n")
            # Tras guardar, la huella es la nueva: se puede seguir guardando.
            file.set("A", "fr", "Un")
            write_csv_file(path, file)
            self.assertEqual(path.read_bytes(), b"A;uno;Un;;;Uno;;;;;;;;;x\r\n")

    def test_comment_and_blank_factories(self):
        file = parse_csv("A;a\r\n")
        file.rows.append(LocRow.comment("# added"))
        file.rows.append(LocRow.blank())
        self.assertEqual([r.kind for r in file.rows], [RowKind.DATA, RowKind.COMMENT, RowKind.BLANK])
        self.assertEqual(to_source(file), "A;a\r\n# added\r\n\r\n")
        self.assertTrue(file.modified)


if __name__ == "__main__":
    unittest.main()
