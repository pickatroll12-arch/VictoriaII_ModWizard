import codecs
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.clausewitz import (  # noqa: E402
    Block,
    ClausewitzDate,
    Document,
    Entry,
    ParseResult,
    Scalar,
    Severity,
    parse,
    parse_file,
    to_source,
)
from vic2studio.core.clausewitz.diagnostics import MESSAGES  # noqa: E402


def shape(block):
    """Árbol compacto: asignaciones como (clave, op, valor); valores sueltos tal cual; bloques como listas."""
    items = []
    for entry in block.entries:
        value = shape(entry.value) if isinstance(entry.value, Block) else entry.value.text
        items.append(value if entry.key is None else (entry.key.text, entry.op, value))
    return items


class StructureTests(unittest.TestCase):
    def parse_ok(self, text):
        result = parse(text)
        self.assertEqual(result.diagnostics, [], [d.format() for d in result.diagnostics])
        self.assertEqual(to_source(result.document), text)
        return result.document

    def test_empty_file(self):
        self.assertEqual(shape(self.parse_ok("")), [])

    def test_only_comments(self):
        doc = self.parse_ok("# uno\n\n   # dos\n")
        self.assertEqual(shape(doc), [])
        self.assertEqual(doc.trailing_comments, ["# uno", "# dos"])

    def test_crlf_and_tabs(self):
        doc = self.parse_ok("a = {\r\n\tb = c\r\n\t\td = e\r\n}\r\n")
        self.assertEqual(shape(doc), [("a", "=", [("b", "=", "c"), ("d", "=", "e")])])
        self.assertEqual(doc.newline, "\r\n")
        self.assertEqual(self.parse_ok("a = b\n").newline, "\n")

    def test_bom_text(self):
        doc = self.parse_ok("﻿owner = GEL\n")
        self.assertEqual(shape(doc), [("owner", "=", "GEL")])

    def test_empty_blocks(self):
        doc = self.parse_ok("a = {}\nb = { }\nc = {\n}\n")
        self.assertEqual(shape(doc), [("a", "=", []), ("b", "=", []), ("c", "=", [])])

    def test_nested_anonymous_blocks(self):
        doc = self.parse_ok("x = { { a = b } { c = d } }")
        self.assertEqual(shape(doc), [("x", "=", [[("a", "=", "b")], [("c", "=", "d")]])])
        self.assertEqual(doc.get("x").values()[1].get_text("c"), "d")

    def test_lists(self):
        doc = self.parse_ok("color = { 97 209 251 }\nnames = { \"Rainha de Portugal\" Mindelo }\n")
        self.assertEqual(shape(doc), [("color", "=", ["97", "209", "251"]),
                                      ("names", "=", ["Rainha de Portugal", "Mindelo"])])
        self.assertEqual([v.as_int() for v in doc.get("color").values()], [97, 209, 251])
        self.assertTrue(doc.get("names").values()[0].quoted)

    def test_date_keys(self):
        doc = self.parse_ok("owner = MEX\n1861.1.1 = { owner = GEL }\n1836.1.1={controller=RUS}")
        self.assertEqual(doc.get("1861.1.1").get_text("owner"), "GEL")
        self.assertEqual(doc.entries[1].key.as_date(), ClausewitzDate(1861, 1, 1))
        self.assertEqual(shape(doc)[2], ("1836.1.1", "=", [("controller", "=", "RUS")]))

    def test_repeated_keys_keep_order(self):
        doc = self.parse_ok("add_core = GEL\nowner = GEL\nadd_core = RUS\nadd_core = TUR\n")
        self.assertEqual([v.text for v in doc.get_all("add_core")], ["GEL", "RUS", "TUR"])
        self.assertEqual(doc.keys(), ["add_core", "owner"])

    def test_comparison_operators(self):
        doc = self.parse_ok("t = { a < 1 b > 2 c <= 3 d >= 4 e != 5 f == 6 g = 7 }")
        self.assertEqual([e.op for e in doc.get("t")], ["<", ">", "<=", ">=", "!=", "==", "="])

    def test_strings_with_special_characters(self):
        doc = self.parse_ok('name = "a # no es comentario { } = "\nx = y')
        self.assertEqual(doc.get_text("name"), "a # no es comentario { } = ")
        self.assertEqual(doc.get_text("x"), "y")
        quoted_key = self.parse_ok('"clave con espacios" = 1')
        self.assertEqual(quoted_key.entries[0].key, Scalar("clave con espacios", quoted=True))

    def test_multiline_string_is_valid_but_warned(self):
        result = parse('desc = "uno\ndos" x = 1')
        self.assertTrue(result.ok)
        self.assertEqual(result.document.get_text("desc"), "uno\ndos")
        self.assertEqual([(d.code, d.severity, d.line, d.column) for d in result.diagnostics],
                         [("multiline_string", Severity.WARNING, 1, 8)])
        self.assertEqual(result.diagnostics[0].args, {"end_line": 2})

    def test_mixed_block(self):
        doc = self.parse_ok("x = { 1 2 a = b 3 }")
        self.assertEqual(shape(doc), [("x", "=", ["1", "2", ("a", "=", "b"), "3"])])

    def test_compact_syntax(self):
        doc = self.parse_ok("a={b=c}d=e f={1 2}")
        self.assertEqual(shape(doc), [("a", "=", [("b", "=", "c")]), ("d", "=", "e"), ("f", "=", ["1", "2"])])

    def test_iterative_deep_nesting(self):
        text = "a = {" * 5000 + "}" * 5000
        doc = self.parse_ok(text)
        depth = 0
        node = doc
        while node.entries:
            node = node.entries[0].value
            depth += 1
        self.assertEqual(depth, 5000)

    def test_positions_of_nodes(self):
        doc = self.parse_ok("a = 1\n  b = {\n\tc = 2 }")
        b = doc.find("b")
        self.assertEqual((b.line, b.column), (2, 3))
        self.assertEqual((b.value.line, b.value.column), (2, 7))
        c = b.value.find("c")
        self.assertEqual((c.line, c.column), (3, 2))
        self.assertIsNone(Entry("new", "=", 1).line)


class DiagnosticTests(unittest.TestCase):
    def single(self, text, code):
        result = parse(text)
        self.assertEqual(to_source(result.document), text)
        found = [d for d in result.diagnostics if d.code == code]
        self.assertEqual(len(found), 1, [d.format() for d in result.diagnostics])
        return result, found[0]

    def test_unclosed_block(self):
        text = "a = 1\npolitical_decisions = {\n\tx = {\n\t}\n"
        result, d = self.single(text, "unclosed_block")
        self.assertEqual((d.severity, d.line, d.column, d.offset), (Severity.ERROR, 2, 23, 28))
        self.assertEqual(d.args, {"key": "political_decisions", "open_line": 2})
        self.assertEqual(d.related, [(5, 1)])
        self.assertEqual(d.message("es"),
                         "El bloque 'political_decisions' abierto en la línea 2 no se cierra (falta '}')")
        self.assertEqual(d.message("en"), "Block 'political_decisions' opened on line 2 is never closed (missing '}')")
        self.assertFalse(result.ok)
        block = result.document.get("political_decisions")
        self.assertFalse(block.is_closed)
        self.assertEqual(shape(block), [("x", "=", [])])

    def test_unclosed_anonymous_block(self):
        _, d = self.single("x = 1\n{ a = b", "unclosed_block")
        self.assertEqual((d.line, d.column, d.args["key"]), (2, 1, None))
        self.assertEqual(d.message("es"), "El bloque abierto en la línea 2 no se cierra (falta '}')")
        self.assertEqual(d.message("en"), "Block opened on line 2 is never closed (missing '}')")

    def test_nested_unclosed_blocks_are_all_reported(self):
        result = parse("a = {\n\tb = {\n\t\tc = d\n")
        self.assertEqual([(d.code, d.line, d.args["key"]) for d in result.errors],
                         [("unclosed_block", 1, "a"), ("unclosed_block", 2, "b")])

    def test_unexpected_close_brace(self):
        result, d = self.single("a = 1\n}\nb = 2\n", "unexpected_close_brace")
        self.assertEqual((d.line, d.column), (2, 1))
        self.assertEqual(d.message("es"), "Llave de cierre '}' sobrante: no hay ningún bloque abierto")
        self.assertEqual(d.message("en"), "Stray closing brace '}': there is no open block")
        self.assertEqual(shape(result.document), [("a", "=", "1"), ("b", "=", "2")])

    def test_missing_value(self):
        result, d = self.single("x = {\n\ta =\n}\n", "missing_value")
        self.assertEqual((d.line, d.column, d.args, d.related), (2, 2, {"key": "a", "op": "="}, [(3, 1)]))
        self.assertEqual(d.message("es"), "Falta el valor de 'a' después de '='")
        self.assertEqual(d.message("en"), "Missing value for 'a' after '='")
        self.assertEqual(shape(result.document), [("x", "=", [])])
        _, at_eof = self.single("a = 1\nb >", "missing_value")
        self.assertEqual((at_eof.line, at_eof.column, at_eof.args["op"]), (2, 1, ">"))

    def test_missing_key(self):
        result, d = self.single("x = { = b }", "missing_key")
        self.assertEqual((d.line, d.column, d.args), (1, 7, {"op": "="}))
        self.assertEqual(d.message("es"), "El operador '=' no tiene clave")
        self.assertEqual(d.message("en"), "Operator '=' has no key")
        self.assertEqual(shape(result.document), [("x", "=", ["b"])])
        _, second = self.single("a = 1 = 2", "missing_key")
        self.assertEqual(second.column, 7)

    def test_unterminated_string(self):
        result, d = self.single('name = "abc\nnext = 1', "unterminated_string")
        self.assertEqual((d.line, d.column), (1, 8))
        self.assertEqual(d.message("es"), "Cadena sin cerrar: falta la comilla de cierre")
        self.assertEqual(d.message("en"), "Unterminated string: missing closing quote")
        self.assertEqual(result.document.get("name"), Scalar("abc\nnext = 1", quoted=True))

    def test_invalid_key(self):
        result, d = self.single("{ a } = b", "invalid_key")
        self.assertEqual((d.line, d.column, d.args, d.related), (1, 1, {"op": "="}, [(1, 7)]))
        self.assertEqual(d.message("es"), "Un bloque no puede usarse como clave (delante de '=')")
        self.assertEqual(d.message("en"), "A block cannot be used as a key (before '=')")
        self.assertEqual(shape(result.document), [["a"], "b"])
        self.assertEqual([d.code for d in result.diagnostics], ["invalid_key"])

    def test_unexpected_operator(self):
        result, d = self.single("x = 1\na = = b\n", "unexpected_operator")
        self.assertEqual((d.line, d.column, d.args), (2, 5, {"op": "=", "key": "a"}))
        self.assertEqual(d.message("es"), "Operador '=' inesperado: se esperaba el valor de 'a'")
        self.assertEqual(d.message("en"), "Unexpected operator '=': expected the value of 'a'")
        self.assertEqual(shape(result.document), [("x", "=", "1"), ("a", "=", "b")])

    def test_invalid_character(self):
        result, d = self.single("a = b ! c", "invalid_character")
        self.assertEqual((d.line, d.column, d.args), (1, 7, {"char": "!"}))
        self.assertEqual(d.message("es"), "Carácter no válido '!'")
        self.assertEqual(d.message("en"), "Invalid character '!'")
        self.assertEqual(shape(result.document), [("a", "=", "b"), "c"])

    def test_control_character_warning(self):
        result, d = self.single("a = b\nc\x01 = d\x02", "control_character")
        self.assertEqual((d.severity, d.line, d.column, d.args), (Severity.WARNING, 2, 2, {"count": 2, "codepoint": "0001"}))
        self.assertTrue(result.ok)
        self.assertIn("U+0001", d.message("es"))
        self.assertIn("U+0001", d.message("en"))

    def test_suspicious_close_brace_hint(self):
        text = (
            "political_decisions = {\n"
            "\tfirst = {\n"
            "\t\tallow = { war = no }\n"
            "\t}\n"
            "\tsecond = {\n"
            "\t\teffect = {\n"
            "\t\t\tprestige = 5\n"
            "\t\t}\n"
            "}\n"
        )
        result = parse(text)
        self.assertEqual([(d.code, d.line, d.column) for d in result.diagnostics],
                         [("unclosed_block", 1, 23), ("suspicious_close_brace", 9, 1)])
        hint = result.diagnostics[1]
        self.assertEqual((hint.severity, hint.args, hint.related), (Severity.INFO, {"key": "second", "open_line": 5}, [(5, 11)]))
        self.assertEqual(hint.message("es"), "Esta '}' cierra 'second' (línea 5) pero tiene menos sangría que esa línea: "
                                             "puede que falte una '}' antes")
        self.assertEqual(hint.message("en"), "This '}' closes 'second' (line 5) but is less indented than that line: "
                                             "a '}' may be missing before it")

    def test_messages_exist_for_every_code_in_both_languages(self):
        self.assertEqual(set(MESSAGES["es"]), set(MESSAGES["en"]))
        emitted = set()
        samples = ["{", "}", "a =", "= a", '"', "{ a } = b", "a = = b", "!", 'a = "x\ny"', "\x01",
                   "x = {\n\ty = {\n}\n"]
        for text in samples:
            emitted.update(d.code for d in parse(text).diagnostics)
        emitted.add("non_game_encoding")
        self.assertTrue(emitted <= set(MESSAGES["es"]), emitted - set(MESSAGES["es"]))
        for lang in ("es", "en"):
            for code, template in MESSAGES[lang].items():
                self.assertNotIn("{}", template.format_map(_Everything()), code)

    def test_format_and_unknown_language(self):
        d = parse("}").diagnostics[0]
        self.assertEqual(d.format("x.txt", "es"), "x.txt:1:1: error: Llave de cierre '}' sobrante: no hay ningún bloque abierto")
        self.assertEqual(d.format(lang="en"), "1:1: error: Stray closing brace '}': there is no open block")
        self.assertEqual(d.message("fr"), d.message("en"))
        warning = parse('a = "x\ny"').diagnostics[0]
        self.assertIn(": aviso: ", warning.format("f", "es"))
        self.assertIn(": warning: ", warning.format("f", "en"))

    def test_garbage_never_raises_and_is_preserved(self):
        for text in ["}}}{{{", "= = =", "!!!", '"""', "{ = } = { = }", "a = { b = } c", "#\n}\n{", "\x00{\x00"]:
            result = parse(text)
            self.assertEqual(to_source(result.document), text)
            self.assertFalse(result.ok, text)


class _Everything(dict):
    def __missing__(self, key):
        return "X"


class ScalarTests(unittest.TestCase):
    def test_conversions(self):
        self.assertEqual(Scalar("-15").as_int(), -15)
        self.assertEqual(Scalar("+3").as_int(), 3)
        self.assertEqual(Scalar("0.125").as_float(), 0.125)
        self.assertEqual(Scalar("-.5").as_float(), -0.5)
        self.assertEqual(Scalar("7").as_float(), 7.0)
        self.assertIs(Scalar("yes").as_bool(), True)
        self.assertIs(Scalar("no").as_bool(), False)
        self.assertEqual(Scalar("1861.4.12").as_date(), ClausewitzDate(1861, 4, 12))
        for bad, method in [("1.5", "as_int"), ("abc", "as_float"), ("1e5", "as_float"), ("nan", "as_float"),
                            ("true", "as_bool"), ("1861.1", "as_date"), ("1861.13.1", "as_date")]:
            with self.assertRaises(ValueError, msg=(bad, method)):
                getattr(Scalar(bad), method)()

    def test_predicates(self):
        self.assertTrue(Scalar("-0.5").is_number())
        self.assertTrue(Scalar("12").is_number())
        self.assertFalse(Scalar("1.2.3").is_number())
        self.assertFalse(Scalar("inf").is_number())
        self.assertTrue(Scalar("1836.1.1").is_date())
        self.assertFalse(Scalar("1836.2.29").is_date())
        self.assertFalse(Scalar("GEL").is_date())

    def test_text_quotes_equality(self):
        plain = Scalar("GEL")
        self.assertEqual((str(plain), plain.text, plain.quoted), ("GEL", "GEL", False))
        self.assertEqual(plain, Scalar("GEL"))
        self.assertNotEqual(plain, Scalar("GEL", quoted=True))
        self.assertEqual(len({plain, Scalar("GEL"), Scalar("GEL", True)}), 2)
        self.assertEqual(repr(Scalar("a b", quoted=True)), "Scalar('a b', quoted=True)")

    def test_validation(self):
        with self.assertRaises(ValueError):
            Scalar("dos palabras")
        with self.assertRaises(ValueError):
            Scalar("")
        with self.assertRaises(ValueError):
            Scalar("a=b")
        with self.assertRaises(ValueError):
            Scalar('con "comillas"', quoted=True)
        with self.assertRaises(TypeError):
            Scalar(5)
        self.assertEqual(Scalar("", quoted=True).text, "")


class DateTests(unittest.TestCase):
    def test_parse_str_order(self):
        date = ClausewitzDate.parse("1861.1.1")
        self.assertEqual((date.year, date.month, date.day, str(date)), (1861, 1, 1, "1861.1.1"))
        self.assertEqual(str(ClausewitzDate(1836)), "1836.1.1")
        self.assertEqual(str(ClausewitzDate.parse("1836.01.05")), "1836.1.5")
        self.assertLess(ClausewitzDate(1836, 12, 31), ClausewitzDate(1837, 1, 1))
        self.assertEqual(sorted([ClausewitzDate(1900, 2, 1), ClausewitzDate(1900, 1, 31)])[0], ClausewitzDate(1900, 1, 31))
        self.assertEqual(hash(ClausewitzDate(1, 2, 3)), hash(ClausewitzDate(1, 2, 3)))

    def test_validation(self):
        for args in [(1836, 0, 1), (1836, 13, 1), (1836, 2, 29), (1836, 4, 31), (1836, 1, 0)]:
            with self.assertRaises(ValueError, msg=args):
                ClausewitzDate(*args)
        with self.assertRaises(TypeError):
            ClausewitzDate("1836")
        for text in ["1836", "1836.1", "1836.1.1.1", "a.b.c", " 1836.1.1"]:
            with self.assertRaises(ValueError, msg=text):
                ClausewitzDate.parse(text)


class BlockQueryTests(unittest.TestCase):
    def setUp(self):
        self.doc = parse(
            "owner = GEL\nPrestige = 5\nadd_core = GEL\nadd_core = RUS\n2087 = { owned_by = THIS }\n"
            "name = \"Nueva Georgia\"\nflags = { a b }\nflags = x\n"
        ).document

    def test_get_family(self):
        doc = self.doc
        self.assertEqual(doc.get("owner"), Scalar("GEL"))
        self.assertIsNone(doc.get("missing"))
        self.assertEqual(doc.get("missing", 0), 0)
        self.assertEqual(doc.get_text("name"), "Nueva Georgia")
        self.assertEqual(doc.get_text("flags"), "x")  # primer escalar, no el bloque
        self.assertEqual(doc.get_text("missing", "-"), "-")
        self.assertEqual([v.text for v in doc.get_all("add_core")], ["GEL", "RUS"])
        self.assertEqual(doc.get(2087).get_text("owned_by"), "THIS")
        self.assertEqual(doc.get(Scalar("owner")).text, "GEL")

    def test_case_sensitivity(self):
        doc = self.doc
        self.assertFalse(doc.has("prestige"))
        self.assertTrue(doc.has("prestige", ignore_case=True))
        self.assertEqual(doc.get("PRESTIGE", ignore_case=True).as_int(), 5)
        self.assertEqual(len(doc.find_all("ADD_CORE", ignore_case=True)), 2)
        self.assertIsNone(doc.find("Owner"))
        self.assertEqual(doc.find("Owner", ignore_case=True).value.text, "GEL")
        self.assertIn("owner", doc)
        self.assertNotIn("Owner", doc)

    def test_keys_values_iteration(self):
        doc = self.doc
        self.assertEqual(doc.keys(), ["owner", "Prestige", "add_core", "2087", "name", "flags"])
        self.assertEqual(len(doc), 8)
        self.assertEqual([e.key.text for e in doc][:2], ["owner", "Prestige"])
        self.assertEqual([v.text for v in doc.get("flags").values()], ["a", "b"])
        self.assertTrue(all(e.is_assignment for e in doc))
        self.assertFalse(doc.get("flags").entries[0].is_assignment)
        self.assertEqual(doc.values(), [])

    def test_invalid_key_type(self):
        with self.assertRaises(TypeError):
            self.doc.get(1.5)
        with self.assertRaises(TypeError):
            self.doc.get(None)


class ParseResultTests(unittest.TestCase):
    def test_result_properties(self):
        result = parse('a = "x\ny"\n}', filename="dummy/file.txt")
        self.assertIsInstance(result, ParseResult)
        self.assertFalse(result.ok)
        self.assertEqual([d.code for d in result.errors], ["unexpected_close_brace"])
        self.assertEqual([d.code for d in result.warnings], ["multiline_string"])
        self.assertEqual(result.path, Path("dummy/file.txt"))
        self.assertEqual((result.encoding, result.newline), ("cp1252", "\n"))
        self.assertIsInstance(result.document, Document)
        self.assertIsNone(parse("a = b").path)

    def test_rejects_non_text(self):
        with self.assertRaises(TypeError):
            parse(b"a = b")

    def test_parse_file_encodings(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp = Path(tmp) / "cp.txt"
            cp.write_bytes("nombre = \"Málaga\"\r\nx = 1\r\n".encode("cp1252"))
            result = parse_file(cp)
            self.assertEqual((result.encoding, result.newline, result.path), ("cp1252", "\r\n", cp))
            self.assertEqual(result.document.encoding, "cp1252")
            self.assertEqual(result.document.get_text("nombre"), "Málaga")
            self.assertEqual(result.diagnostics, [])

            bom = Path(tmp) / "bom.txt"
            bom.write_bytes(codecs.BOM_UTF8 + "owner = GEL\n".encode("utf-8"))
            result = parse_file(bom)
            self.assertEqual(result.encoding, "utf-8-sig")
            self.assertEqual(result.document.get_text("owner"), "GEL")
            self.assertEqual([(d.code, d.severity, d.line, d.column) for d in result.diagnostics],
                             [("non_game_encoding", Severity.WARNING, 1, 1)])

            utf8 = Path(tmp) / "utf8.txt"
            utf8.write_bytes("a = 1\nname = \"Rivière\"\n".encode("utf-8"))
            result = parse_file(utf8)
            self.assertEqual(result.encoding, "utf-8")
            d = result.diagnostics[0]
            self.assertEqual((d.code, d.line, d.column, d.args), ("non_game_encoding", 2, 13, {"encoding": "UTF-8"}))
            self.assertIn("Windows-1252", d.message("es"))
            self.assertIn("Windows-1252", d.message("en"))

            forced = parse_file(cp, encoding="latin-1")
            self.assertEqual(forced.encoding, "iso8859-1")


if __name__ == "__main__":
    unittest.main()
