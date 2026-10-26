import string
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core import csvloc  # noqa: E402
from vic2studio.core.csvloc import CODES, CsvDiagnostic, Severity, parse_csv  # noqa: E402
from vic2studio.core.csvloc.diagnostics import MESSAGES, SEVERITIES, column_name, make  # noqa: E402
from vic2studio.core.csvloc.lint import quoted_semicolons  # noqa: E402

OK = "K;a;;;;;;;;;;;;;x"


def codes(text: str, **kwargs) -> list[tuple[str, int]]:
    return [(d.code, d.line) for d in parse_csv(text, **kwargs).diagnostics]


class LintTests(unittest.TestCase):
    def test_clean_rows(self):
        self.assertEqual(codes(OK + "\r\n#;;;;\r\n\r\nL;b;;;;;;;;;;;;;X;;;;\r\nM;c;;;;;;;;;;;;;x \r\n"), [])

    def test_missing_end_marker(self):
        file = parse_csv("K;a" + ";" * 12 + "\r\nL;a;b;;;;;;;;;;;;;;x\r\n")
        first, second = file.diagnostics
        self.assertEqual((first.code, first.line, first.args["found_column"]), ("missing_end_marker", 1, None))
        self.assertEqual((second.code, second.line, second.args["found_column"]), ("missing_end_marker", 2, 16))
        self.assertIn("16", second.message("en"))
        self.assertNotEqual(first.message("es"), second.message("es"))
        self.assertEqual((first.severity, second.severity), (Severity.INFO, Severity.WARNING))

    def test_too_few_columns(self):
        self.assertEqual(codes("K;a"), [("too_few_columns", 1), ("missing_end_marker", 1)])
        diags = parse_csv("K;en;fr;de\r\n").diagnostics
        self.assertEqual([(d.code, d.severity, d.args.get("count")) for d in diags],
                         [("too_few_columns", Severity.WARNING, 3), ("missing_end_marker", Severity.WARNING, None)])

    def test_rows_the_game_shows_whole_are_only_notes(self):
        """FC-3: el formato vanilla «clave;en;fr;de;;es;;;;;;x» daba 2 avisos por fila (el 92 % de los avisos)."""
        cases = {
            # x temprana tras los idiomas visibles (darkness_3_01.csv, text.csv): una nota, ".short".
            "K;en;fr;de;;es;;;;;;x": (10, 11, ".short"),
            # Sin x, con los 4 idiomas visibles; una «X» en Spanish es texto (FC-11), no el marcador.
            "K;en;fr;de;;es": (5, None, ".short"),
            "ROMAN_10;X;X;X;;X": (5, None, ".short"),
            # Los 13 idiomas sin x (el mod del usuario) y con campos vacíos detrás.
            "K;en" + ";" * 12: (13, None, ".unmarked"),
            "K;en" + ";" * 15: (13, None, ".unmarked"),
        }
        for line, (count, found_column, variant) in cases.items():
            with self.subTest(line=line):
                diags = parse_csv(line + "\r\n").diagnostics
                self.assertEqual([(d.code, d.severity) for d in diags], [("missing_end_marker", Severity.INFO)])
                self.assertEqual((diags[0].args["count"], diags[0].args["found_column"]), (count, found_column))
                self.assertEqual(diags[0]._variant(), "missing_end_marker" + variant)
                self.assertIn("inofensivo", diags[0].message("es"))
                self.assertIn("harmless", diags[0].message("en"))

    def test_shifted_or_incomplete_rows_still_warn(self):
        cases = {
            # Falta Spanish (o la «x» está donde iría): aviso de columnas y de marcador.
            "K;en;fr;de;x": ["too_few_columns", "missing_end_marker"],
            "K;en;fr;de;;x": ["too_few_columns", "missing_end_marker"],
            # Desplazadas: «x» después de la columna 14 o texto donde iría la «x».
            "K;a;b;;;;;;;;;;;;;;x": ["missing_end_marker"],
            "K" + ";t" * 14: ["missing_end_marker"],
            "K;en" + ";" * 13 + "extra": ["missing_end_marker"],
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                diags = parse_csv(line + "\r\n").diagnostics
                self.assertEqual([d.code for d in diags], expected)
                self.assertTrue(all(d.severity is Severity.WARNING for d in diags))

    def test_column_numbers_match_the_documented_convention(self):
        """LOC-4: las columnas de los mensajes cuentan desde 0 (la clave), como LANGUAGE_CODES y END_MARKER_COLUMN."""
        line = "K;a;b;;;;;;;;;;;;;;x"
        diag = parse_csv(line).diagnostics[0]
        self.assertEqual(diag.args["found_column"], line.split(";").index("x"))
        self.assertIn(f"columna {diag.args['found_column']}", diag.message("es"))
        self.assertIn(f"en vez de la {csvloc.END_MARKER_COLUMN}", diag.message("es"))
        self.assertIn(f"column {csvloc.END_MARKER_COLUMN} ", parse_csv("K;a").diagnostics[1].message("en"))
        quoted = parse_csv('K;a;b;c;d;"x;y"').diagnostics
        field = next(d for d in quoted if d.code == "semicolon_in_quotes").args["field"]
        self.assertEqual(field, csvloc.LANGUAGE_CODES["es"])

    def test_duplicate_key(self):
        diags = parse_csv(f"{OK}\r\nL;b\r\n{OK}\r\n").diagnostics
        duplicate = [d for d in diags if d.code == "duplicate_key"]
        self.assertEqual([(d.line, d.args["first_line"]) for d in duplicate], [(3, 1)])
        self.assertIn("1", duplicate[0].message("es"))

    def test_empty_key(self):
        self.assertEqual(codes(";\r\n;Hello;;;;;;;;;;;;;x\r\n;;;;;;;;;;;;;;x"),
                         [("empty_key", 1), ("empty_key", 2), ("empty_key", 3)])
        self.assertEqual(codes("  ;text"), [("empty_key", 1)])

    def test_key_whitespace(self):
        self.assertEqual(codes(" K ;a;;;;;;;;;;;;;x"), [("key_whitespace", 1)])

    def test_semicolon_in_quotes(self):
        text = 'K;"Text; with semicolon";;;;Spanish;;;;;;;;\r\n'
        diags = [d for d in parse_csv(text).diagnostics if d.code == "semicolon_in_quotes"]
        self.assertEqual(len(diags), 1)
        self.assertEqual((diags[0].line, diags[0].column, diags[0].args["field"]), (1, 3, 1))
        self.assertIn("English", diags[0].message("en"))
        self.assertIn("inglés", diags[0].message("es"))
        self.assertEqual(diags[0].severity, Severity.WARNING)

    def test_quotes_without_semicolon_are_fine(self):
        for line in ('K;"Plain";;;;;;;;;;;;;x',
                     'K;He said "go; now";;;;;;;;;;;;;x',
                     # Caso real de text.csv: comillas dobladas sin cerrar.
                     'K;The Act;"L\'acte ""de la propriét?"";Der Act;;El Acta;;;;;;;;;x;;;;',
                     'K;"unterminated; text;;;;;;;;;;;;;x'):
            with self.subTest(line=line):
                self.assertNotIn("semicolon_in_quotes", [c for c, _ in codes(line)])

    def test_quoted_semicolons_scanner(self):
        self.assertEqual(quoted_semicolons('K;"a;b";"c;d;e";f;"g"'), [(1, 2), (3, 8)])
        self.assertEqual(quoted_semicolons('K;"a;b"'), [(1, 2)])
        self.assertEqual(quoted_semicolons('"k;y";v'), [(0, 0)])
        self.assertEqual(quoted_semicolons('K;"a"";b"'), [(1, 2)])
        self.assertEqual(quoted_semicolons('K;"a""b";"c"x;d"'), [])

    def test_unencodable_character(self):
        file = parse_csv("K;Привет;;;;;;;;;;;;;x\r\n#注释\r\n")
        diags = [d for d in file.diagnostics if d.code == "unencodable_character"]
        self.assertEqual([(d.line, d.column, d.args["count"]) for d in diags], [(1, 3, 6), (2, 2, 2)])
        self.assertEqual(diags[0].severity, Severity.ERROR)
        self.assertEqual(diags[0].args["codepoint"], "041F")
        self.assertEqual(file.lint(encoding="utf-8"), [])

    def test_non_game_encoding(self):
        utf8 = parse_csv(OK, encoding="utf-8").diagnostics
        self.assertEqual([(d.code, d.args["bom"]) for d in utf8], [("non_game_encoding", False)])
        bom = parse_csv("\ufeff" + OK).diagnostics
        self.assertEqual([(d.code, d.args["bom"]) for d in bom], [("non_game_encoding", True)])
        self.assertIn("BOM", bom[0].message("es"))

    def test_utf16_is_an_error(self):
        """LOC-M3: un CSV en UTF-16 no daba ningún aviso de codificación (el juego no puede leerlo)."""
        for encoding in ("utf-16", "utf-16-le", "utf-16-be", "utf-16-be-bom"):
            with self.subTest(encoding=encoding):
                diags = parse_csv(OK, encoding=encoding).diagnostics
                self.assertEqual([(d.code, d.severity) for d in diags], [("non_game_encoding", Severity.ERROR)])
                self.assertEqual(diags[0]._variant(), "non_game_encoding.utf16")
                self.assertIn("no puede leerlo", diags[0].message("es"))

    def test_stray_bom_before_cp1252(self):
        """P2: un BOM UTF-8 delante de texto cp1252 se pega a la primera clave en el juego."""
        diags = parse_csv("\u00ef\u00bb\u00bf" + OK + "\r\n", encoding="cp1252").diagnostics
        self.assertEqual([(d.code, d.line, d.severity) for d in diags], [("non_game_encoding", 1, Severity.WARNING)])
        self.assertEqual(diags[0]._variant(), "non_game_encoding.stray_bom")
        self.assertIn("ï»¿", diags[0].message("en"))

    def test_header_row(self):
        header = "key;English;French;German;Polish;Spanish;Italian;Swedish;Czech;Hugarian;Dutch;Portuguese;Russian;Finish"
        diags = parse_csv(header + "\r\n" + OK).diagnostics
        self.assertEqual([(d.code, d.line, d.severity) for d in diags], [("header_row", 1, Severity.INFO)])

    def test_lint_uses_current_positions(self):
        file = parse_csv(f"A;a\r\n{OK}\r\n")
        self.assertEqual([d.line for d in file.diagnostics], [1, 1])
        file.remove_row("A")
        file.add_row("B", {"en": "b"}, index=0)
        self.assertEqual(file.lint(), [])
        file.add_row("C", {"ru": "Ж"}, index=1)
        self.assertEqual([(d.code, d.line) for d in file.lint()], [("unencodable_character", 2)])

    def test_path_in_diagnostics(self):
        diag = parse_csv("K;a", filename="loc/x.csv").diagnostics[0]
        self.assertEqual(diag.path, str(Path("loc/x.csv")))
        self.assertTrue(diag.format("en").startswith(f"{Path('loc/x.csv')}:1: warning: "))
        self.assertTrue(diag.format("en").endswith("[too_few_columns]"))
        self.assertIn(": aviso: ", diag.format("es"))


# Argumentos de ejemplo y fragmentos que el mensaje debe contener en ambos idiomas.
SAMPLE_ARGS = {
    "missing_end_marker": ({"key": "MY_KEY", "found_column": None}, ["MY_KEY", "14"]),
    "too_few_columns": ({"key": "MY_KEY", "count": 3, "expected": 13}, ["MY_KEY", "3", "13"]),
    "duplicate_key": ({"key": "MY_KEY", "first_line": 7}, ["MY_KEY", "7"]),
    "empty_key": ({"key": ""}, []),
    "key_whitespace": ({"key": " MY_KEY"}, [" MY_KEY"]),
    "semicolon_in_quotes": ({"key": "MY_KEY", "field": 5}, ["MY_KEY", "';'"]),
    "unencodable_character": ({"key": "MY_KEY", "char": "Ж", "codepoint": "0416", "count": 2,
                               "encoding": "cp1252"}, ["Ж", "0416", "2", "cp1252"]),
    "non_game_encoding": ({"encoding": "utf-8", "expected": "cp1252", "bom": False}, ["utf-8", "cp1252"]),
    "header_row": ({"key": "key"}, ["'key'"]),
}
VARIANTS = {
    "missing_end_marker.misplaced": ({"key": "MY_KEY", "found_column": 12}, ["MY_KEY", "12", "14"]),
    "missing_end_marker.short": ({"key": "MY_KEY", "found_column": 11, "count": 10, "expected": 13},
                                 ["MY_KEY", "10", "13"]),
    "missing_end_marker.unmarked": ({"key": "MY_KEY", "found_column": None, "count": 13, "expected": 13},
                                    ["MY_KEY", "13", "14"]),
    "non_game_encoding.bom": ({"encoding": "utf-8-sig", "expected": "cp1252", "bom": True},
                              ["utf-8-sig", "cp1252", "BOM"]),
    "non_game_encoding.stray_bom": ({"encoding": "cp1252", "expected": "cp1252", "stray_bom": True, "key": "MY_KEY"},
                                    ["cp1252", "BOM", "MY_KEY", "ï»¿"]),
    "non_game_encoding.utf16": ({"encoding": "utf-16", "expected": "cp1252", "utf16": True}, ["utf-16", "cp1252"]),
}


class MessageTests(unittest.TestCase):
    def test_severity_is_exported(self):
        self.assertIs(csvloc.Severity, Severity)
        self.assertEqual({s.name for s in Severity}, {"ERROR", "WARNING", "INFO"})
        self.assertEqual(set(SEVERITIES), set(CODES))

    def test_required_codes_exist(self):
        for code in ("missing_end_marker", "too_few_columns", "duplicate_key", "empty_key",
                     "semicolon_in_quotes", "unencodable_character", "header_row"):
            self.assertIn(code, CODES)

    def test_tables_cover_the_same_messages(self):
        self.assertEqual(set(MESSAGES["es"]), set(MESSAGES["en"]))
        self.assertTrue(set(CODES) <= set(MESSAGES["en"]))

    def test_every_code_has_complete_messages(self):
        self.assertEqual(set(SAMPLE_ARGS), set(CODES))
        self.assertEqual(set(SAMPLE_ARGS) | set(VARIANTS), set(MESSAGES["en"]))
        for name, (args, expected) in {**SAMPLE_ARGS, **VARIANTS}.items():
            diag = make(name.split(".")[0], 3, 1, **args)
            self.assertEqual(diag._variant(), name)
            texts = {lang: diag.message(lang) for lang in ("es", "en")}
            with self.subTest(name=name):
                self.assertNotEqual(texts["es"], texts["en"])
                for text in texts.values():
                    self.assertNotIn("{", text)
                    self.assertGreater(len(text), 30)
                    for fragment in expected:
                        self.assertIn(fragment, text)
        quoted = make("semicolon_in_quotes", 1, 1, key="K", field=5)
        self.assertIn("Spanish", quoted.message("en"))
        self.assertIn("español", quoted.message("es"))

    def test_diagnostics_are_hashable(self):
        diags = parse_csv("K;a\r\nK;b").diagnostics
        self.assertEqual(len(set(diags)), len(diags))

    def test_message_fallbacks(self):
        diag = make("duplicate_key", 2, 1, key="K", first_line=1)
        self.assertEqual(diag.message("fr"), diag.message("en"))
        self.assertEqual(CsvDiagnostic("custom_code", Severity.INFO).message("es"), "custom_code")
        self.assertIn("K", CsvDiagnostic("duplicate_key", Severity.WARNING, args={"key": "K"}).message())

    def test_column_names(self):
        self.assertEqual(column_name(0, "es"), "clave")
        self.assertEqual(column_name(5, "es"), "español")
        self.assertEqual(column_name(5, "en"), "Spanish")
        self.assertEqual(column_name(15, "es"), "columna 15")
        for lang in ("es", "en"):
            self.assertFalse(set(column_name(13, lang)) & set(string.digits))


if __name__ == "__main__":
    unittest.main()
