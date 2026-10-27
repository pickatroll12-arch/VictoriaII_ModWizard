import codecs
import gc
import sys
import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.cancel import Cancelled  # noqa: E402
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
    write_file,
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
        # El parser admite lo que Scalar() rechaza al editar (un salto de línea dentro del texto).
        value = result.document.get("name")
        self.assertEqual((value.text, value.quoted), ("abc\nnext = 1", True))

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
        emitted.update(("non_game_encoding", "unreadable_encoding", "stray_bom"))  # los de parse_file
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


class FileEncodingTests(unittest.TestCase):
    """Lo que hace ``parse_file`` con la codificación y el BOM del archivo."""

    TEXT = 'country_event = {\r\n\tid = 2\r\n\ttitle = "Le\u00f3n"\r\n}\r\n'

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def file(self, data: bytes, name: str = "a.txt") -> Path:
        path = self.dir / name
        path.write_bytes(data)
        return path

    def assert_saves_bytes(self, result, raw: bytes):
        path = self.file(b"", "out.txt")
        write_file(path, result, backup=False)
        self.assertEqual(path.read_bytes(), raw)

    def assert_saves(self, result, raw: bytes, label: str):
        """Guardar sin cambios da los mismos bytes y pasar a cp1252 da el texto sin ningún BOM."""
        path = self.file(b"", "out.txt")
        write_file(path, result, backup=False)
        self.assertEqual(path.read_bytes(), raw, label)
        write_file(path, result, encoding="cp1252", backup=False)
        self.assertEqual(path.read_bytes(), self.TEXT.encode("cp1252"), label)

    def test_encodings_the_game_cannot_read(self):
        """R1: la CLI, «Validar mod» y el visor reciben del parser que un UTF-16 es ilegible para el juego
        (antes, nada si era ASCII o un aviso falso, «lo lee como Windows-1252») y el BOM UTF-8 delante de
        cp1252 (antes, nada)."""
        ascii_text = self.TEXT.replace("\u00f3", "o")
        cases = [
            # El nombre para mostrar (encoding.display_name), igual que en la cabecera del visor: con el orden de
            # bytes y el BOM, no el nombre interno del codec («UTF-16-BE-BOM»).
            (ascii_text.encode("utf-16"), "UTF-16 LE BOM"),
            (ascii_text.encode("utf-16-le"), "UTF-16 LE"),
            (codecs.BOM_UTF16_BE + self.TEXT.encode("utf-16-be"), "UTF-16 BE BOM"),
            (self.TEXT.encode("utf-16-be"), "UTF-16 BE"),
        ]
        for raw, shown in cases:
            with self.subTest(shown=shown):
                result = parse_file(self.file(raw))
                self.assertEqual([(d.code, d.severity, d.line, d.column, d.args) for d in result.diagnostics],
                                 [("unreadable_encoding", Severity.ERROR, 1, 1, {"encoding": shown})])
                self.assertFalse(result.ok)
                self.assertIn("no puede leerlo", result.diagnostics[0].message("es"))
                self.assertIn("cannot read it", result.diagnostics[0].message("en"))
        stray = parse_file(self.file(codecs.BOM_UTF8 + self.TEXT.encode("cp1252")))
        self.assertEqual(stray.encoding, "cp1252")
        self.assertEqual([(d.code, d.severity, d.line, d.column) for d in stray.diagnostics],
                         [("stray_bom", Severity.WARNING, 1, 1)])
        self.assertIn("ï»¿", stray.diagnostics[0].message("en"))
        self.assertEqual(stray.document.entries[0].key.text, "ï»¿country_event", "lo que ve el juego")
        utf8_bom = parse_file(self.file(codecs.BOM_UTF8 + self.TEXT.encode("utf-8")))
        self.assertEqual([d.code for d in utf8_bom.diagnostics], ["non_game_encoding"], "un BOM de verdad no")

    def test_explicit_encoding_that_does_not_describe_the_file(self):
        """NF-6: con una codificación explícita el BOM quedaba en el texto (no se podía pasar a cp1252) o el
        BOM y el orden de bytes no hacían ida y vuelta."""
        utf16_native = "utf-16-le" if sys.byteorder == "little" else "utf-16-be"
        cases = [
            (codecs.BOM_UTF8 + self.TEXT.encode("utf-8"), "utf-8", "utf-8-sig"),
            (codecs.BOM_UTF16_LE + self.TEXT.encode("utf-16-le"), "utf-16-le", "utf-16"),
            (codecs.BOM_UTF16_BE + self.TEXT.encode("utf-16-be"), "utf-16-be", "utf-16-be-bom"),
            (codecs.BOM_UTF16_BE + self.TEXT.encode("utf-16-be"), "utf-16", "utf-16-be-bom"),
            (self.TEXT.encode(utf16_native), "utf-16", utf16_native),
            (self.TEXT.encode("utf-8"), "utf-8-sig", "utf-8"),
            (self.TEXT.encode("utf-16-be"), "utf-16-be-bom", "utf-16-be"),
            (codecs.BOM_UTF16_LE + self.TEXT.encode("utf-16-le"), "utf-16", "utf-16"),
        ]
        for raw, explicit, expected in cases:
            with self.subTest(explicit=explicit, bom=raw[:2]):
                result = parse_file(self.file(raw), encoding=explicit)
                self.assertEqual((result.encoding, result.document.extra_boms), (expected, 0))
                self.assertEqual(to_source(result.document), self.TEXT)
                self.assert_saves(result, raw, explicit)

    def test_repeated_bom(self):
        """NF-10: con el BOM repetido el U+FEFF sobrante quedaba al principio del texto y write_file(cp1252)
        lanzaba UnencodableTextError. Ahora lo cuenta Document.extra_boms y la ida y vuelta es exacta.

        Como el de la codificación, los repetidos no están en to_source: el texto y las posiciones del árbol
        coinciden (REG-VIEW-BOM-COL: el visor muestra to_source y señalaba un carácter antes en la línea 1)."""
        cases = [
            (codecs.BOM_UTF8, "utf-8", "utf-8-sig", 1, "utf-16"),
            (codecs.BOM_UTF8, "utf-8", "utf-8-sig", 2, "utf-16-be-bom"),
            (codecs.BOM_UTF16_LE, "utf-16-le", "utf-16", 1, "utf-8-sig"),
            (codecs.BOM_UTF16_BE, "utf-16-be", "utf-16-be-bom", 1, "utf-8-sig"),
        ]
        for mark, codec, encoding, extra, other in cases:
            with self.subTest(encoding=encoding, extra=extra):
                raw = mark * (extra + 1) + self.TEXT.encode(codec)
                result = parse_file(self.file(raw))
                doc = result.document
                self.assertEqual((result.encoding, doc.extra_boms), (encoding, extra))
                first = doc.entries[0]
                self.assertEqual((first.key.text, first.line, first.column), ("country_event", 1, 1))
                self.assertEqual(to_source(doc), self.TEXT)
                self.assertEqual(doc.get("country_event").close_position, (4, 1))
                self.assert_saves(result, raw, encoding)
                # Tras editar se conservan en su codificación, aunque se escriba de otra forma; en otra con
                # BOM se escribe solo el suyo, y sin BOM ninguno.
                doc.get("country_event").set("id", 3)
                path = self.file(raw, "edited.txt")
                edited = self.TEXT.replace("id = 2", "id = 3")
                for target, expected in ((None, mark * (extra + 1) + edited.encode(codec)),
                                         (encoding.upper(), mark * (extra + 1) + edited.encode(codec)),
                                         (other, edited.encode(other)),
                                         ("utf-8", edited.encode("utf-8"))):
                    write_file(path, result, encoding=target, backup=False)
                    self.assertEqual(path.read_bytes(), expected, target)
                result.encoding = "utf-8"
                write_file(path, result, backup=False)
                self.assertEqual(path.read_bytes(), edited.encode("utf-8"))
        only = parse_file(self.file(codecs.BOM_UTF8 * 2))
        self.assertEqual((only.document.entries, only.document.extra_boms, to_source(only.document)), ([], 1, ""))
        self.assert_saves_bytes(only, codecs.BOM_UTF8 * 2)
        # Un solo BOM, aunque se fuerce la codificación, es el suyo: no hay ninguno repetido.
        forced = parse_file(self.file(codecs.BOM_UTF8 + b"a = 1\n"), encoding="utf-8-sig")
        self.assertEqual((forced.encoding, forced.document.extra_boms, to_source(forced.document)),
                         ("utf-8-sig", 0, "a = 1\n"))
        # Sin archivo no hay codificación: un U+FEFF inicial es del texto (el lexer lo toma por espacio).
        loose = parse("\ufeffa = 1\n")
        self.assertEqual((loose.document.extra_boms, to_source(loose.document), loose.document.entries[0].column),
                         (0, "\ufeffa = 1\n", 2))

    def test_unknown_document_encoding_does_not_block_an_explicit_one(self):
        """REG-WRITE-ENC: write_file normalizaba document.encoding aunque se le diera otra codificación, y una
        que no existe (puesta a mano) lanzaba LookupError en vez de escribir con la pedida."""
        plain = parse("a = 1\n").document
        repeated = parse_file(self.file(codecs.BOM_UTF8 * 2 + b"a = 1\n")).document
        path = self.file(b"", "out.txt")
        for doc in (plain, repeated):
            for bad in ("bogus-codec", "base64"):
                with self.subTest(extra_boms=doc.extra_boms, encoding=bad):
                    doc.encoding = bad
                    write_file(path, doc, encoding="cp1252", backup=False)
                    self.assertEqual(path.read_bytes(), b"a = 1\n")
                    write_file(path, doc, encoding="utf-8-sig", backup=False)  # otra con BOM: solo el suyo
                    self.assertEqual(path.read_bytes(), codecs.BOM_UTF8 + b"a = 1\n")
                    write_file(path, doc, encoding="cp1252", backup=False)
                    with self.assertRaises(LookupError):
                        write_file(path, doc, backup=False)
                    self.assertEqual(path.read_bytes(), b"a = 1\n")


class EndPositionTests(unittest.TestCase):
    """VIEW-NF-4: dónde acaban el valor de una entrada y un bloque, sin leer atributos privados."""

    def test_value_end_and_close_position(self):
        text = ('a = 1\nname = "Le\u00f3n"\nb = { c = yes }\n{ 1 2 }\nlong = "x\r\ny\rzz"\nlast = "a\nbc"\n'
                'open = { d = 1\n')
        doc = parse(text).document
        ends = {str(e.key) if e.key is not None else "[loose]": e.value_end for e in doc.entries}
        self.assertEqual(ends, {"a": (1, 5), "name": (2, 13), "b": (3, 15), "[loose]": (4, 7),
                                "long": (7, 3), "last": (9, 3), "open": None})
        block = doc.get("b")
        self.assertEqual((block.close_position, block.find("c").value_end), ((3, 15), (3, 13)))
        self.assertIsNone(doc.get("open").close_position, "bloque sin cerrar")
        self.assertIsNone(doc.close_position, "un documento no tiene «}»")
        doc.get("open").close()
        self.assertIsNone(doc.get("open").close_position, "la «}» que añade close() no se leyó")
        # Una cadena sin cerrar llega al final: un salto final cuenta en su línea, donde empieza.
        for tail, end in (("", (2, 11)), ("\n", (2, 12)), ("\r\n", (2, 12)), ("\r", (2, 12)), ("\nx\r\n", (3, 2))):
            with self.subTest(tail=tail):
                self.assertEqual(parse('a = 1\nname = "Mod' + tail).document.find("name").value_end, end)

    def test_values_set_by_code_have_no_end(self):
        doc = parse('a = 1\nb = { c = 2 }\nn = "x"\n').document
        a, b, n = doc.find("a"), doc.find("b"), doc.find("n")
        block = b.value
        a.value = 5
        b.value = {"z": 1}
        self.assertEqual((a.value_end, b.value_end, b.value.close_position), (None, None, None))
        self.assertIsNone(doc.append("new", 1).value_end)
        a.value = 1
        b.value = block
        self.assertEqual((a.value_end, b.value_end), ((1, 5), (2, 13)), "devolverle el valor leído")
        n.value = "x"  # mismo texto y comillas: el valor leído
        self.assertEqual(n.value_end, (3, 7))
        n.key = None  # pasa a valor suelto: su texto se regenera donde estaba la clave
        self.assertIsNone(n.value_end)
        block.find("c").value = 3
        self.assertEqual(block.close_position, (2, 13), "editar dentro no mueve la «}» leída")

    def test_read_blocks_moved_by_code_have_no_value_end(self):
        """REG-VALUE-END-MOVED: un bloque leído que el código pone en otra entrada sigue teniendo su «}» leída
        (close_position), pero no es el valor leído de esa entrada: value_end es None, como su line si es
        nueva. Antes, una entrada nueva devolvía la «}» de otro sitio."""
        doc = parse("a = { x = 1 }\nb = 2\nc = { y = 2 }\nd = { z = 3 }\n").document
        a, c, d = doc.get("a"), doc.get("c"), doc.get("d")
        doc.remove("a")
        new = doc.append("n", a)
        self.assertEqual((new.line, new.value_end, a.close_position), (None, None, (1, 13)))
        b = doc.find("b")
        b.value = c  # escalar leído -> bloque leído en otra entrada
        self.assertEqual((b.line, b.value_end, doc.find("c").value_end), (2, None, (3, 13)))
        e = doc.find("d")
        e.value = c  # bloque leído -> otro bloque leído
        self.assertEqual((e.line, e.value_end, c.close_position), (4, None, (3, 13)))
        e.value = d
        self.assertEqual(e.value_end, (4, 13), "devolverle su bloque")
        loose = parse("{ 1 2 }\n").document.entries[0]
        self.assertEqual((loose.line, loose.value_end), (1, (1, 7)), "valor suelto leído: la posición es del bloque")


class RecoveryTests(unittest.TestCase):
    """'clave =' sin valor al final de una línea: el error va en su línea y la clave siguiente se conserva (P5)."""

    def test_key_without_value_before_the_next_assignment(self):
        cases = [
            ("capital = 1234\nruling_party =\nlast_election = 1830.1.1\nprimary_culture = zulu\n",
             ("missing_value", 2, 1, {"key": "ruling_party", "op": "="}, [(3, 1)]),
             [("capital", "=", "1234"), ("last_election", "=", "1830.1.1"), ("primary_culture", "=", "zulu")]),
            ("p = {\n\towner =\n\tcontroller = GEL\n}\n",
             ("missing_value", 2, 2, {"key": "owner", "op": "="}, [(3, 2)]), [("p", "=", [("controller", "=", "GEL")])]),
            ("a = \n# comentario\nb = c\n", ("missing_value", 1, 1, {"key": "a", "op": "="}, [(3, 1)]), [("b", "=", "c")]),
            ('x = { a =\n "b" = c }', ("missing_value", 1, 7, {"key": "a", "op": "="}, [(2, 2)]),
             [("x", "=", [("b", "=", "c")])]),
        ]
        for text, diagnostic, tree in cases:
            result = parse(text)
            self.assertEqual(to_source(result.document), text)
            self.assertEqual([(d.code, d.line, d.column, d.args, d.related) for d in result.diagnostics], [diagnostic])
            self.assertEqual(shape(result.document), tree, text)

    def test_valid_and_same_line_cases_do_not_change(self):
        valid = parse("x = { a =\n b }")
        self.assertEqual((valid.diagnostics, shape(valid.document)), ([], [("x", "=", [("a", "=", "b")])]))
        same_line = parse("a = b = c\n")
        self.assertEqual([(d.code, d.line, d.column) for d in same_line.diagnostics], [("missing_key", 1, 7)])
        self.assertEqual(shape(same_line.document), [("a", "=", "b"), "c"])


class ErrorRunTests(unittest.TestCase):
    """Muchos errores seguidos (un archivo roto o mal pegado): el texto descartado cuesta memoria lineal (R2)."""

    @staticmethod
    def peak(text):
        tracemalloc.start()
        try:
            parse(text)
            return tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

    def test_discarded_text_costs_linear_memory(self):
        patterns = {
            "clave sin valor": lambda n: "".join(f"key{i} =\n" for i in range(n)),
            "llaves sobrantes": lambda n: "}\n" * n,
            "operadores sueltos": lambda n: "= " * n,
            "operadores repetidos": lambda n: "a " + "= " * n + "1\n",
        }
        self.peak("a = = 1\n} =\n")  # lo que se reserva una sola vez no cuenta
        for name, make in patterns.items():
            small, big = self.peak(make(2000)), self.peak(make(4000))
            # Lineal: el doble de texto, el doble de memoria. Con coste cuadrático, unas cuatro veces más.
            self.assertLess(big / small, 3, f"{name}: {small} -> {big} bytes")
            text = make(4000)
            self.assertEqual(to_source(parse(text).document), text)


class InvisibleCharacterTests(unittest.TestCase):
    """Un carácter invisible dentro de una palabra sin comillas cambia la clave o el valor: se avisa (P9)."""

    def test_warning_points_at_the_character(self):
        result = parse('owner\xa0= GER\ncontroller = GER​\n"x\xa0y" = 1\nz = a　b\n')
        self.assertEqual([(d.code, d.severity, d.line, d.column, d.args["codepoint"]) for d in result.diagnostics], [
            ("invisible_character", Severity.WARNING, 1, 6, "00A0"),
            ("invisible_character", Severity.WARNING, 2, 17, "200B"),
            ("invisible_character", Severity.WARNING, 4, 6, "3000"),
        ])
        self.assertTrue(result.ok)
        first = result.diagnostics[0]
        self.assertEqual(first.message("es"), "La palabra 'owner\\xa0' contiene un carácter invisible (U+00A0): "
                                              "no coincidirá con la palabra que aparenta")
        self.assertIn("U+00A0", first.message("en"))
        self.assertEqual(parse("owner = GER\n").diagnostics, [])


class MessageArgumentTests(unittest.TestCase):
    """Los textos de los mensajes se escapan y se recortan: un diagnóstico, una línea (P10)."""

    def test_line_breaks_are_escaped(self):
        result = parse('leader = {\r\n\t"Rey\r\nde Prusia" = {\r\n\t\towner = PRU\r\n')
        lines = [d.format("f.txt", lang) for d in result.diagnostics for lang in ("es", "en")]
        self.assertIn("f.txt:3:14: error: El bloque 'Rey\\r\\nde Prusia' abierto en la línea 3 no se cierra (falta '}')",
                      lines)
        for line in lines:
            self.assertEqual(line.splitlines(), [line])

    def test_long_texts_are_truncated(self):
        diagnostic = parse('"' + "k" * 200 + '" = {\n').diagnostics[0]
        for lang in ("es", "en"):
            self.assertIn("'" + "k" * 59 + "…'", diagnostic.message(lang))
            self.assertNotIn("k" * 60, diagnostic.message(lang))


class LineBreakTests(unittest.TestCase):
    """CR suelto: los comentarios acaban en él (H2-CR) y las líneas cuentan como en los editores (P8)."""

    def test_cr_only_files(self):
        text = "a = 1 # c\rb = 2\r# d\rc = { d = 3 }\r"
        result = parse(text)
        self.assertEqual(shape(result.document), [("a", "=", "1"), ("b", "=", "2"), ("c", "=", [("d", "=", "3")])])
        self.assertEqual((result.newline, result.diagnostics), ("\r", []))
        self.assertEqual([entry.line for entry in result.document], [1, 2, 4])
        self.assertEqual(result.document.find("c").comments, ["# d"])
        result.document.get("c").append("e", 4)
        result.document.append("f", {"g": 1})
        self.assertEqual(to_source(result.document), "a = 1 # c\rb = 2\r# d\rc = { d = 3 e = 4 }\rf = {\r\tg = 1\r}\r")

    def test_diagnostic_lines_match_text_editors(self):
        text = "owner = MEX\r\n\rcontroller = MEX\r\n\r\rbroken = {\r\n"
        diagnostic = parse(text).diagnostics[0]
        self.assertEqual((diagnostic.code, diagnostic.line, diagnostic.column), ("unclosed_block", 6, 10))
        self.assertTrue(text.splitlines()[diagnostic.line - 1].startswith("broken"))


class CancelTests(unittest.TestCase):
    """Leer un archivo grande se puede parar a mitad: la cancelación se consulta en todas las fases."""

    TEXTS = {
        "lista en una línea": " ".join(str(i) for i in range(400_000)),
        "bloque sin cerrar": "a = {\n" + "\tb = { c = 1 }\n" * 100_000,  # incluye la pista de la "}" sospechosa
        "muchas líneas": "x = y\n" * 300_000,
    }

    def test_cancel_inside_a_big_file(self):
        text = self.TEXTS["bloque sin cerrar"]
        for limit in (1, 2, 10, 40):
            with self.subTest(limit=limit):
                calls = []
                with self.assertRaises(Cancelled):
                    parse(text, cancelled=lambda: calls.append(1) or len(calls) >= limit)
                self.assertEqual(len(calls), limit)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grande.txt"
            path.write_text(text, encoding="cp1252")
            with self.assertRaises(Cancelled):
                parse_file(path, cancelled=lambda: True)

    def test_checks_are_frequent(self):
        # Sin el recolector cíclico, cuyas pausas no dependen del núcleo (ui.tasks lo controla en las tareas).
        if gc.isenabled():
            gc.disable()
            self.addCleanup(gc.enable)
        for name, text in self.TEXTS.items():
            stamps = []
            start = time.perf_counter()
            result = parse(text, cancelled=lambda: stamps.append(time.perf_counter()) and False)
            stamps.append(time.perf_counter())
            del result
            gaps = [b - a for a, b in zip([start] + stamps, stamps)]
            self.assertLess(max(gaps), 0.2, f"{name}: {len(gaps)} consultas; hueco máximo {max(gaps):.3f} s")


if __name__ == "__main__":
    unittest.main()
