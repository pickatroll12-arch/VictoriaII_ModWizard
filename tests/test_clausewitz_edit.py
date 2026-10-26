import codecs
import difflib
import random
import re
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import CLAUSEWITZ_SUFFIXES, corpus_files  # noqa: E402
from vic2studio.core.clausewitz import (  # noqa: E402
    Block,
    ClausewitzDate,
    Document,
    EditError,
    Entry,
    Scalar,
    SourceMismatchError,
    format_canonical,
    iter_json,
    parse,
    parse_file,
    serializer,
    simplify,
    to_json,
    to_source,
    walk,
    write_file,
)
from vic2studio.core.clausewitz.lexer import RBRACE, STRING, WORD, tokenize  # noqa: E402
from vic2studio.core.encoding import UnencodableTextError  # noqa: E402
from vic2studio.core.fileio import FileChangedError  # noqa: E402

SAMPLE = (
    "# Cabecera del archivo\n"
    "country = {\n"
    "\towner = GEL # dueño\n"
    "\tcontroller = GEL\n"
    "\n"
    "\tadd_core = GEL\n"
    "\tadd_core = RUS\n"
    "\tcolor = { 1 2 3 }\n"
    "\t# comentario final\n"
    "}\n"
)


def edited(text, action):
    doc = parse(text).document
    action(doc)
    return to_source(doc)


def line_diff(old, new):
    return [line for line in difflib.ndiff(old.splitlines(True), new.splitlines(True)) if line[:1] in "+-"]


class ReparseMixin:
    def assertReparses(self, doc):
        """El texto generado se vuelve a leer sin diagnósticos y con el mismo árbol."""
        text = to_source(doc)
        result = parse(text)
        self.assertEqual([d.format() for d in result.diagnostics], [], text)
        self.assertEqual(to_json(result.document), to_json(doc), text)
        return text


class SetTests(ReparseMixin, unittest.TestCase):
    def test_set_existing_scalar_changes_only_that_token(self):
        doc = parse(SAMPLE).document
        country = doc.get("country")
        entry = country.find("controller")
        country.set("controller", "RUS")
        new = self.assertReparses(doc)
        start = SAMPLE.index("controller = GEL") + len("controller = ")
        self.assertEqual(new, SAMPLE[:start] + "RUS" + SAMPLE[start + 3:])
        self.assertEqual(line_diff(SAMPLE, new), ["- \tcontroller = GEL\n", "+ \tcontroller = RUS\n"])
        matcher = difflib.SequenceMatcher(None, SAMPLE, new, autojunk=False)
        changes = [op for op in matcher.get_opcodes() if op[0] != "equal"]
        self.assertEqual(len(changes), 1)
        tag, i1, i2, j1, j2 = changes[0]
        self.assertTrue(start <= i1 and i2 <= start + 3, changes)
        self.assertIs(country.find("controller"), entry)

    def test_set_keeps_trailing_comment_and_quotes(self):
        new = edited(SAMPLE, lambda d: d.get("country").set("owner", "TUR"))
        self.assertIn("\towner = TUR # dueño\n", new)
        quoted = edited('name = "Old Name"\r\n', lambda d: d.set("name", "Nuevo"))
        self.assertEqual(quoted, 'name = "Nuevo"\r\n')
        spaced = edited("name = Old\n", lambda d: d.set("name", "dos palabras"))
        self.assertEqual(spaced, 'name = "dos palabras"\n')
        explicit = edited('name = "Old"\n', lambda d: d.set("name", Scalar("Bare")))
        self.assertEqual(explicit, "name = Bare\n")

    def test_set_value_types(self):
        doc = parse("x = {\n\ta = 1\n}\n").document
        x = doc.get("x")
        x.set("a", {"flag": True, "start": ClausewitzDate(1861, 4, 12), "ratio": 0.25, "tiny": 1e-7})
        x.set("list", [1, 2, 3])
        x.set("empty", [])
        x.set("no", False)
        x.set("nested", {"inner": {"deep": ["dos palabras", -3]}})
        self.assertEqual(self.assertReparses(doc), (
            "x = {\n"
            "\ta = {\n"
            "\t\tflag = yes\n"
            "\t\tstart = 1861.4.12\n"
            "\t\tratio = 0.25\n"
            "\t\ttiny = 0.0000001\n"
            "\t}\n"
            "\tlist = { 1 2 3 }\n"
            "\tempty = { }\n"
            "\tno = no\n"
            "\tnested = {\n"
            "\t\tinner = {\n"
            "\t\t\tdeep = { \"dos palabras\" -3 }\n"
            "\t\t}\n"
            "\t}\n"
            "}\n"
        ))
        self.assertEqual(x.get("a").get("start").as_date(), ClausewitzDate(1861, 4, 12))
        self.assertEqual(x.get("list").values()[2].as_int(), 3)

    def test_replace_block_by_scalar_and_back(self):
        doc = parse("a = {\n\tb = { c = 1 }\n}\n").document
        a = doc.get("a")
        a.set("b", 5)
        self.assertEqual(self.assertReparses(doc), "a = {\n\tb = 5\n}\n")
        a.set("b", {"c": 2})
        self.assertEqual(self.assertReparses(doc), "a = {\n\tb = {\n\t\tc = 2\n\t}\n}\n")

    def test_set_appends_when_missing(self):
        doc = parse(SAMPLE).document
        entry = doc.get("country").set("capital", 1234)
        self.assertEqual(entry.value, Scalar("1234"))
        self.assertIn("\t# comentario final\n\tcapital = 1234\n}\n", self.assertReparses(doc))

    def test_set_ignore_case(self):
        doc = parse("Prestige = 5\n").document
        doc.set("prestige", 10, ignore_case=True)
        self.assertEqual(to_source(doc), "Prestige = 10\n")

    def test_set_rejects_unrepresentable_values(self):
        doc = parse("a = 1\n").document
        for bad in [None, object(), float("nan"), 'con "comillas"', {None: 1}]:
            with self.assertRaises((TypeError, ValueError), msg=repr(bad)):
                doc.set("a", bad)
        self.assertEqual(to_source(doc), "a = 1\n")


class AppendInsertTests(ReparseMixin, unittest.TestCase):
    def test_append_uses_sibling_indentation_before_closing_brace(self):
        text = "a = {\n    x = 1\n    b = {\n        y = 2\n    }\n}\n"
        doc = parse(text).document
        doc.get("a").get("b").append("z", 3)
        doc.get("a").append("w", {"k": "v"})
        self.assertEqual(self.assertReparses(doc), (
            "a = {\n    x = 1\n    b = {\n        y = 2\n        z = 3\n    }\n"
            "    w = {\n        k = v\n    }\n}\n"
        ))

    def test_append_goes_after_trailing_comments(self):
        new = edited(SAMPLE, lambda d: d.get("country").append("new", "yes"))
        self.assertTrue(new.endswith("\tcolor = { 1 2 3 }\n\t# comentario final\n\tnew = yes\n}\n"), new)
        same_line = edited("x = {\n\ta = 1 # nota\n}\n", lambda d: d.get("x").append("b", 2))
        self.assertEqual(same_line, "x = {\n\ta = 1 # nota\n\tb = 2\n}\n")

    def test_append_to_empty_and_inline_blocks(self):
        cases = {
            "x = {}": "x = { a = 1 }",
            "x = { }": "x = { a = 1 }",
            "x = {\n}": "x = {\n\ta = 1\n}",
            "\tx = {\n\t}": "\tx = {\n\t\ta = 1\n\t}",
            "x = { b = 2 }": "x = { b = 2 a = 1 }",
            "x = {b=2}": "x = {b=2 a = 1}",
            "x = { 1 2 }": "x = { 1 2 a = 1 }",
        }
        for text, expected in cases.items():
            doc = parse(text).document
            doc.get("x").append("a", 1)
            self.assertEqual(self.assertReparses(doc), expected, text)
        doc = parse("x = {}").document
        doc.get("x").append("n", {"m": [1, 2], "o": {"p": 1}})
        self.assertEqual(self.assertReparses(doc), "x = { n = { m = { 1 2 } o = { p = 1 } } }")

    def test_append_values_to_lists(self):
        doc = parse("l = {\n\t1 2 3\n}\nm = {}\n").document
        doc.get("l").append_value(4)
        doc.get("m").append_value("A")
        doc.get("m").append_value("dos palabras")
        self.assertEqual(self.assertReparses(doc), 'l = {\n\t1 2 3 4\n}\nm = { A "dos palabras" }\n')
        commented = parse("l = {\n\t1 2 # nota\n}\n").document
        commented.get("l").append_value(3)
        self.assertEqual(self.assertReparses(commented), "l = {\n\t1 2 # nota\n\t3\n}\n")

    def test_append_to_documents(self):
        cases = {
            "a = 1\n": "a = 1\nb = 2\n",
            "a = 1": "a = 1\nb = 2",
            "": "b = 2\n",
            "# solo comentario": "# solo comentario\nb = 2\n",
            "a = 1\n\n# fin\n": "a = 1\n\n# fin\nb = 2\n",
        }
        for text, expected in cases.items():
            doc = parse(text).document
            doc.append("b", 2)
            self.assertEqual(self.assertReparses(doc), expected, repr(text))

    def test_insert_positions(self):
        text = "x = {\n\t# sobre a\n\ta = 1 # de a\n\tb = 2\n}\n"
        doc = parse(text).document
        x = doc.get("x")
        x.insert(0, "first", 0)
        x.insert(2, "middle", "m")
        x.insert(-1, "before_last", "z")
        self.assertEqual(self.assertReparses(doc), (
            "x = {\n\tfirst = 0\n\t# sobre a\n\ta = 1 # de a\n\tmiddle = m\n\tbefore_last = z\n\tb = 2\n}\n"
        ))
        self.assertEqual([e.key.text for e in x], ["first", "a", "middle", "before_last", "b"])

    def test_insert_at_document_start_keeps_header(self):
        new = edited("# cabecera\nowner = MEX\n", lambda d: d.insert(0, "trade_goods", "cattle"))
        self.assertEqual(new, "# cabecera\ntrade_goods = cattle\nowner = MEX\n")

    def test_crlf_documents_generate_crlf(self):
        doc = parse(SAMPLE.replace("\n", "\r\n")).document
        country = doc.get("country")
        country.append("new", {"a": [1, 2], "b": {"c": 1}})
        country.insert(0, "first", 1)
        country.set("color", {"r": 1})
        text = self.assertReparses(doc)
        self.assertEqual(text.count("\n"), text.count("\r\n"))
        self.assertIn("\r\n\tnew = {\r\n\t\ta = { 1 2 }\r\n\t\tb = {\r\n\t\t\tc = 1\r\n\t\t}\r\n\t}\r\n}\r\n", text)

    def test_new_document_from_scratch(self):
        doc = Document()
        doc.append("tag", "GEL")
        doc.append("history", {"1861.1.1": {"owner": "RUS"}})
        doc.append_value("suelto")
        self.assertEqual(self.assertReparses(doc), (
            "tag = GEL\nhistory = {\n\t1861.1.1 = {\n\t\towner = RUS\n\t}\n}\nsuelto\n"
        ))
        doc.newline = "\r\n"
        self.assertEqual(to_source(doc).count("\r\n"), 7)

    def test_long_generated_lists_wrap(self):
        doc = Document()
        doc.append("provinces", list(range(1, 41)))
        text = self.assertReparses(doc)
        lines = text.splitlines()
        self.assertEqual(lines[0], "provinces = {")
        self.assertTrue(all(len(line) <= 81 for line in lines), text)
        self.assertEqual(lines[-1], "}")


class RemoveTests(ReparseMixin, unittest.TestCase):
    def test_remove_whole_line_and_its_comment(self):
        new = edited(SAMPLE, lambda d: d.get("country").remove("owner"))
        self.assertEqual(line_diff(SAMPLE, new), ["- \towner = GEL # dueño\n"])

    def test_remove_repeated_keys_counts(self):
        doc = parse(SAMPLE).document
        self.assertEqual(doc.get("country").remove("add_core"), 2)
        self.assertEqual(doc.get("country").remove("add_core"), 0)
        self.assertEqual(self.assertReparses(doc), (
            "# Cabecera del archivo\ncountry = {\n\towner = GEL # dueño\n\tcontroller = GEL\n\n"
            "\tcolor = { 1 2 3 }\n\t# comentario final\n}\n"
        ))

    def test_remove_does_not_leave_blank_lines(self):
        cases = [
            # (texto, clave a eliminar, resultado)
            ("x = {\n\ta = 1\n\n\tb = 2\n\n\tc = 3\n}\n", "b", "x = {\n\ta = 1\n\n\tc = 3\n}\n"),
            ("x = {\n\ta = 1\n\n\tb = 2\n}\n", "b", "x = {\n\ta = 1\n}\n"),
            ("x = {\n\n\ta = 1\n}\n", "a", "x = {\n}\n"),
            ("x = {\n\ta = 1\n\tb = 2\n}\n", "a", "x = {\n\tb = 2\n}\n"),
            ("x = {\n\ta = 1\n\n\tb = 2\n}\n", "a", "x = {\n\tb = 2\n}\n"),
            ("x = {\n\n\ta = 1\n\tb = 2\n}\n", "a", "x = {\n\n\tb = 2\n}\n"),
            ("a = 1\n\nb = 2\n", "b", "a = 1\n"),
            ("a = 1\n\nb = 2\n", "a", "b = 2\n"),
            ("a = 1\nb = 2\n", "a", "b = 2\n"),
            ("# cabecera\na = 1\nb = 2\n", "a", "# cabecera\nb = 2\n"),
            ("a = 1 # c1\nb = 2 # c2\nc = 3\n", "b", "a = 1 # c1\nc = 3\n"),
            ("x = {\n\t# sobre b\n\tb = 2\n\tc = 3\n}\n", "b", "x = {\n\t# sobre b\n\tc = 3\n}\n"),
            ("x = { a = 1 b = 2 c = 3 }", "b", "x = { a = 1 c = 3 }"),
            ("x = { a = 1 }", "a", "x = { }"),
            ("x = {\n\ta = 1 b = 2\n}\n", "a", "x = {\n\tb = 2\n}\n"),
            ("x = {\r\n\ta = 1\r\n\r\n\tb = 2\r\n}\r\n", "b", "x = {\r\n\ta = 1\r\n}\r\n"),
        ]
        for text, key, expected in cases:
            doc = parse(text).document
            target = doc.get("x") if "x" in doc else doc
            self.assertEqual(target.remove(key), 1, text)
            self.assertEqual(self.assertReparses(doc), expected, text)

    def test_remove_everything(self):
        doc = parse(SAMPLE).document
        country = doc.get("country")
        for key in country.keys():
            country.remove(key)
        self.assertEqual(self.assertReparses(doc), "# Cabecera del archivo\ncountry = {\n\t# comentario final\n}\n")
        doc.remove("country")
        self.assertEqual(self.assertReparses(doc), "# Cabecera del archivo\n")

    def test_remove_entry(self):
        doc = parse("l = { 1 2 3 }").document
        values = doc.get("l")
        values.remove_entry(values.entries[1])
        self.assertEqual(to_source(doc), "l = { 1 3 }")
        with self.assertRaises(ValueError):
            values.remove_entry(Entry("a", "=", 1))

    def test_remove_with_generated_neighbours(self):
        doc = parse("x = {\n\ta = 1\n\tb = 2\n}\n").document
        x = doc.get("x")
        x.insert(1, "new", 0)
        x.remove("a")
        self.assertEqual(self.assertReparses(doc), "x = {\n\tnew = 0\n\tb = 2\n}\n")


class EntryEditTests(ReparseMixin, unittest.TestCase):
    def test_rename_key_and_change_operator(self):
        doc = parse("t = {\n\tliteracy = 0.5 # umbral\n}\n").document
        entry = doc.get("t").find("literacy")
        entry.key = "Literacy"
        entry.op = ">"
        self.assertEqual(self.assertReparses(doc), "t = {\n\tLiteracy > 0.5 # umbral\n}\n")
        entry.key = "dos palabras"
        self.assertIn('"dos palabras" > 0.5', to_source(doc))

    def test_loose_value_to_assignment_and_back(self):
        doc = parse("l = {\n\tA\n\tB\n}\n").document
        first = doc.get("l").entries[0]
        first.key = "tag"
        self.assertEqual(self.assertReparses(doc), "l = {\n\ttag = A\n\tB\n}\n")
        first.key = None
        self.assertEqual(self.assertReparses(doc), "l = {\n\tA\n\tB\n}\n")
        self.assertIsNone(first.op)
        with self.assertRaises(ValueError):
            first.op = "="

    def test_assign_same_value_is_noop(self):
        doc = parse('a = "abierta').document
        entry = doc.find("a")
        entry.value = entry.value
        self.assertEqual(to_source(doc), 'a = "abierta')

    def test_entry_constructor_validation(self):
        with self.assertRaises(TypeError):
            Entry("a", "=", None)
        with self.assertRaises(ValueError):
            Entry("a", "=>", 1)
        loose = Entry(None, "=", 1)
        self.assertIsNone(loose.op)
        self.assertEqual(Entry("a", None, 1).op, "=")
        with self.assertRaises(TypeError):
            Block([1, 2])

    def test_moved_entries_stay_valid(self):
        doc = parse("a = {\n\tx = 1\n\ty = { z = 2 }\n}\nb = {\n\tw = 3\n}\n").document
        moved = doc.get("a").entries.pop()
        doc.get("b").entries.append(moved)
        text = self.assertReparses(doc)
        self.assertEqual(doc.get("b").get("y").get_text("z"), "2")
        self.assertIn("y = { z = 2 }", text)

    def test_edits_next_to_discarded_text_keep_errors_as_they_were(self):
        text = "x = {\n\ta = 1 b =\n}\n"
        doc = parse(text).document
        doc.get("x").append("c", 2)
        new = to_source(doc)
        self.assertEqual(new, "x = {\n\ta = 1\n\tc = 2 b =\n}\n")
        reparsed = parse(new)
        self.assertEqual([(d.code, d.args.get("key")) for d in reparsed.errors], [("missing_value", "b")])
        self.assertEqual(to_json(reparsed.document), to_json(doc))
        stray = parse("a = 1 }\nb = 2\n").document
        stray.insert(1, "n", 0)
        self.assertEqual(to_source(stray), "a = 1 }\nn = 0\nb = 2\n")

    def test_unclosed_block_is_not_silently_fixed(self):
        text = "political_decisions = {\n\tdecision = {\n\t\tpotential = { tag = GEL }\n\t}\n"
        result = parse(text)
        result.document.get("political_decisions").append("other", {"a": 1})
        new = to_source(result.document)
        self.assertTrue(new.startswith(text), new)
        self.assertEqual(new.count("{"), new.count("}") + 1)
        reparsed = parse(new)
        self.assertEqual([d.code for d in reparsed.errors], ["unclosed_block"])
        self.assertEqual(to_json(reparsed.document), to_json(result.document))


class WriteFileTests(unittest.TestCase):
    def test_round_trip_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Málaga.txt"
            original = "nombre = \"Málaga\"\r\nowner = SPA\r\n".encode("cp1252")
            path.write_bytes(original)
            result = parse_file(path)
            self.assertIsNone(write_file(path, result, backup=False))
            self.assertEqual(path.read_bytes(), original)
            result.document.set("owner", "GEL")
            backup = write_file(path, result)
            self.assertEqual(backup.read_bytes(), original)
            self.assertEqual(path.read_bytes(), "nombre = \"Málaga\"\r\nowner = GEL\r\n".encode("cp1252"))

    def test_encoding_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            bom = Path(tmp) / "bom.txt"
            bom.write_bytes(codecs.BOM_UTF8 + "a = ñ\n".encode("utf-8"))
            doc = parse_file(bom).document
            doc.set("a", "ü")
            write_file(bom, doc, backup=False)
            self.assertEqual(bom.read_bytes(), codecs.BOM_UTF8 + "a = ü\n".encode("utf-8"))

            fresh = Path(tmp) / "nuevo" / "fresh.txt"
            new_doc = Document()
            new_doc.append("nombre", "Córdoba")
            write_file(fresh, new_doc)
            self.assertEqual(fresh.read_bytes(), "nombre = Córdoba\n".encode("cp1252"))
            write_file(fresh, new_doc, encoding="utf-8", backup=False)
            self.assertEqual(fresh.read_bytes(), "nombre = Córdoba\n".encode("utf-8"))

    def test_verify_refuses_text_that_reads_back_differently(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            original = b"x = {\n\ta = 1\n\t= b\n}\n"
            path.write_bytes(original)
            result = parse_file(path)
            # Un valor suelto justo antes del "=" sin clave se leería como "5 = b".
            result.document.get("x").insert(1, None, 5)
            with self.assertRaises(SourceMismatchError):
                write_file(path, result)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["a.txt"])
            write_file(path, result, verify=False, backup=False)
            self.assertEqual(path.read_bytes(), b"x = {\n\ta = 1\n\t5\n\t= b\n}\n")

    def test_verify_refuses_unclosed_blocks_and_new_errors(self):
        # R1: un comentario que se traga la "}" del final deja el mismo árbol, pero con el bloque sin cerrar;
        # una llave o un operador de más dan errores nuevos aunque el árbol sea el mismo.
        bad_texts = [
            ("army = { leader = none # }\n", ("army", 1)),
            ("army = { leader = none }\n}\n", ("army > leader", 2)),
            ("army = { leader = = none }\n", ("army > leader", 1)),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_bytes(b"army = { leader = none }\n")
            result = parse_file(path)
            fresh = Document()
            fresh.set("army", {"leader": "none"})
            for document in (result, fresh):
                for text, (entry, line) in bad_texts:
                    with mock.patch("vic2studio.core.clausewitz.serializer.to_source", return_value=text), \
                            self.assertRaises(SourceMismatchError, msg=text) as ctx:
                        write_file(path, document, backup=False)
                    self.assertEqual((ctx.exception.params["entry"], ctx.exception.params["line"]), (entry, line))
            self.assertEqual(path.read_bytes(), b"army = { leader = none }\n")
            # Los errores que ya tenía el archivo no impiden guardar.
            path.write_bytes(b"army = { leader = none }\n}\n")
            result = parse_file(path)
            result.document.get("army").set("leader", "Moltke")
            write_file(path, result, backup=False)
            self.assertEqual(path.read_bytes(), b"army = { leader = Moltke }\n}\n")

    def test_verify_handles_extreme_nesting(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deep.txt"
            doc = parse("a = {" * 20000 + "}" * 20000).document
            doc.append("b", 1)
            write_file(path, doc)
            self.assertTrue(path.read_bytes().endswith(b"}\nb = 1"))

    def test_unencodable_text_is_rejected_without_touching_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_bytes(b"name = x\n")
            result = parse_file(path)
            result.document.set("name", "中文")
            with self.assertRaises(UnencodableTextError) as ctx:
                write_file(path, result)
            self.assertEqual(ctx.exception.problems[0][1:3], (1, 8))
            self.assertEqual(path.read_bytes(), b"name = x\n")
            with self.assertRaises(TypeError):
                write_file(path, Block())


class RandomEditTests(ReparseMixin, unittest.TestCase):
    """Ediciones aleatorias deterministas: el texto resultante siempre se relee igual."""

    VALUES = [1, -2, 0.5, 1e-7, True, False, "GEL", "con espacios", "", "ñandú", ClausewitzDate(1861, 4, 12),
              [1, 2, 3], [], {}, {"a": 1, "b": [4, 5]}, {"n": {"d": {"x": "y"}}}, Scalar("q", quoted=True),
              ["x y", "z"], list(range(40))]

    def _sources(self):
        files = corpus_files(CLAUSEWITZ_SUFFIXES)
        if files:
            rng = random.Random(7)
            return [parse_file(p) for p in rng.sample(files, min(300, len(files)))]
        return [parse(SAMPLE), parse("a = { b = { c = 1 } d = { 1 2 } }\n"), parse("x = 1")]

    def _edit(self, rng, doc):
        blocks = [doc] + [e.value for _, e in walk(doc) if isinstance(e.value, Block)]
        block = rng.choice(blocks)
        entries = block.entries
        roll = rng.random()
        if roll < 0.2 and entries:
            entry = rng.choice(entries)
            if entry.key is None:
                entry.value = rng.choice(self.VALUES)
            else:
                block.set(entry.key, rng.choice(self.VALUES))
        elif roll < 0.35:
            block.append(rng.choice(["new_key", "1861.1.1", "add_core"]), rng.choice(self.VALUES))
        elif roll < 0.45:
            block.insert(rng.randint(0, len(entries)), "ins", rng.choice(self.VALUES))
        elif roll < 0.55:
            block.append_value(rng.choice([1, "x", "two w", [1, 2], {"a": 1}]))
        elif roll < 0.75 and entries:
            block.remove_entry(rng.choice(entries))
        elif roll < 0.85 and entries:
            entry = rng.choice(entries)
            if entry.key is not None:
                entry.key = rng.choice(["renamed", "Prestige", "two words"])
                entry.op = rng.choice(["<", ">", "=", ">=", "!="])
        elif entries:
            entry = rng.choice(entries)
            entry.key = None if entry.key is not None else "made_key"

    def test_random_edits_reparse_identically(self):
        rng = random.Random(1234)
        operations = 0
        for result in self._sources():
            doc = result.document
            for _ in range(rng.randint(1, 12)):
                self._edit(rng, doc)
                operations += 1
            text = to_source(doc)
            reparsed = parse(text)
            self.assertEqual(to_json(reparsed.document), to_json(doc), result.path)
            if result.ok:
                self.assertTrue(reparsed.ok, (result.path, [d.format() for d in reparsed.errors]))
        self.assertGreater(operations, 0)

    def test_set_on_corpus_changes_only_the_token(self):
        files = corpus_files(CLAUSEWITZ_SUFFIXES)
        if not files:
            self.skipTest("sin corpus disponible")
        rng = random.Random(99)
        checked = 0
        sample = rng.sample(files, min(400, len(files)))
        for path in sample:
            result = parse_file(path)
            original = to_source(result.document)
            candidates = [e for _, e in walk(result.document) if e.key is not None and isinstance(e.value, Scalar)]
            if not candidates:
                continue
            entry = rng.choice(candidates)
            token = entry._vtok
            # Un valor entre comillas conserva sus comillas (como con Block.set).
            replacement = '"zz_new_value"' if entry.value.quoted else "zz_new_value"
            entry.value = "zz_new_value"
            new = to_source(result.document)
            start = token.offset
            self.assertEqual(new, original[:start] + replacement + original[start + len(token.raw):], path)
            checked += 1
        # Con el corpus completo (400 archivos de muestra) al menos 100; con uno pequeño, la mitad.
        self.assertGreaterEqual(checked, min(100, len(sample) // 2))


def sort_by_key(block):
    block.entries.sort(key=lambda entry: entry.key.text)


def blocks_of(doc):
    return [doc] + [entry.value for _, entry in walk(doc) if isinstance(entry.value, Block)]


class MoveTests(ReparseMixin, unittest.TestCase):
    """Mover o reordenar entradas leídas (con ``move`` o sobre ``entries``) no pega tokens (PE-02)."""

    def test_move_first_entry_of_a_file(self):
        text = "owner = FRA\r\ncontroller = FRA\r\nadd_core = FRA\r\n"
        doc = parse(text).document
        doc.entries.insert(1, doc.entries.pop(0))
        self.assertEqual(self.assertReparses(doc), "controller = FRA\r\nowner = FRA\r\nadd_core = FRA\r\n")
        doc.move(doc.find("owner"), 0)
        self.assertEqual(to_source(doc), text)

    def test_reorders_never_glue_tokens(self):
        cases = [
            ("a = 1\nx = { y = 2 }\n", lambda d: d.move(d.entries[0], to=d.get("x"))),
            ("x = {b=2 a=1}", lambda d: sort_by_key(d.get("x"))),
            ("x = { b = 2 a = 1 }", lambda d: sort_by_key(d.get("x"))),
            ("a=1 b=2 c=3", lambda d: d.entries.reverse()),
            ("a = 1\nb = 2\nc = 3\n", lambda d: d.entries.reverse()),
            ("x = {\n\ta = 1 # uno\n\tb = 2\n\tc = 3\n}\n", lambda d: d.get("x").move(d.get("x").entries[0], 2)),
            ("l = {1 2 3}", lambda d: d.get("l").entries.reverse()),
        ]
        for text, action in cases:
            doc = parse(text).document
            action(doc)
            new = self.assertReparses(doc)
            self.assertEqual(len(tokenize(new)), len(tokenize(text)), (text, new))

    def test_moved_entry_takes_its_comments(self):
        text = "x = {\n\ta = 0\n\t# sobre b\n\tb = 1\n}\nw = {\n\tq = 1\n}\n"
        expected = "x = {\n\ta = 0\n}\nw = {\n\tq = 1\n\t# sobre b\n\tb = 1\n}\n"
        doc = parse(text).document
        doc.get("x").move(doc.get("x").find("b"), to=doc.get("w"))
        self.assertEqual(self.assertReparses(doc), expected)
        # Quitarla y meterla en la lista de otro bloque es lo mismo: el comentario no se duplica.
        doc = parse(text).document
        moved = doc.get("x").find("b")
        doc.get("x").remove_entry(moved)
        doc.get("w").entries.append(moved)
        self.assertEqual(self.assertReparses(doc), expected)

    def test_sort_keeps_each_comment_with_its_entry(self):
        doc = parse("x = {\n\tc = 3 # tres\n\t# sobre a\n\ta = 1\n\tb = 2\n}\n").document
        sort_by_key(doc.get("x"))
        self.assertEqual(self.assertReparses(doc), "x = {\n\t# sobre a\n\ta = 1\n\tb = 2\n\tc = 3 # tres\n}\n")

    def test_moved_blocks_are_reindented(self):
        doc = parse("a = {\n\tb = {\n\t\tc = 1\n\t}\n}\nd = 1\n").document
        doc.get("a").move(doc.get("a").find("b"), to=doc)
        self.assertEqual(self.assertReparses(doc), "a = {\n}\nd = 1\nb = {\n\tc = 1\n}\n")
        doc = parse("a = {\n\tx = 1\n}\nb = {\n\tc = {\n\t\td = 1\n\t}\n}\n").document
        doc.move(doc.find("b"), to=doc.get("a"))
        self.assertEqual(self.assertReparses(doc), "a = {\n\tx = 1\n\tb = {\n\t\tc = {\n\t\t\td = 1\n\t\t}\n\t}\n}\n")

    def test_move_into_empty_blocks(self):
        cases = [
            ("w = { }\nb = 1\n", "w = { b = 1 }\n"),
            ("w = {}\nb = 1\n", "w = { b = 1 }\n"),
            ("w = {\n}\nb = 1\n", "w = {\n\tb = 1\n}\n"),
        ]
        for text, expected in cases:
            doc = parse(text).document
            doc.move(doc.find("b"), to=doc.get("w"))
            self.assertEqual(self.assertReparses(doc), expected, text)

    def test_move_validation(self):
        doc = parse("a = { b = 1 }\nc = 2\n").document
        with self.assertRaises(EditError) as ctx:
            doc.get("a").move(doc.find("c"))
        self.assertEqual(ctx.exception.code, "entry_not_in_block")
        with self.assertRaises(TypeError):
            doc.move(doc.find("c"), to="a")
        self.assertEqual(to_source(doc), "a = { b = 1 }\nc = 2\n")


class GluedTokenTests(ReparseMixin, unittest.TestCase):
    """Editar o borrar junto a un token pegado (``}1861.1.1``, ``"Mindelo";``) no funde palabras (PE-03, P4)."""

    def test_replacing_a_self_delimited_value(self):
        def set_value(path, value):
            return lambda d: setattr(d.find_path(path), "value", value)

        cases = [
            ("a = {\r\n\tb = 1\r\n}c = {\r\n\td = 2\r\n}\r\n", set_value(("a",), "GEL"), "a = GEL c = {\r\n\td = 2\r\n}\r\n"),
            # Con un str se conservan las comillas del valor anterior, también en los valores sueltos.
            ('l = { "Rainha de Portugal" "Mindelo"; }', set_value(("l", "[1]"), "Lisboa"),
             'l = { "Rainha de Portugal" "Lisboa"; }'),
            ('l = { "Rainha de Portugal" "Mindelo"; }', set_value(("l", "[1]"), Scalar("Lisboa")),
             'l = { "Rainha de Portugal" Lisboa ; }'),
            ('s = { effectFile = "gfx\\FX\\buttonstate.fx";\n}\n', lambda d: d.get("s").set("effectFile", Scalar("plain")),
             "s = { effectFile = plain ;\n}\n"),
            ("l = { x{ y } z }", set_value(("l", "[1]"), "w"), "l = { x w z }"),
        ]
        for text, action, expected in cases:
            doc = parse(text).document
            action(doc)
            self.assertEqual(self.assertReparses(doc), expected, text)

    def test_removing_an_entry_glued_to_the_next(self):
        cases = [
            ("a = 1 b = { c = 2 }d = 3\n", lambda d: d.remove("b"), "a = 1 d = 3\n"),
            ('x = { a = 1 b = "q"d = 3 }', lambda d: d.get("x").remove("b"), "x = { a = 1 d = 3 }"),
            ("owner = GEL NOT={tag=RUS}controller = GEL", lambda d: d.remove("NOT"), "owner = GEL controller = GEL"),
            ('l = { A "B"C }', lambda d: d.get("l").remove_entry(d.get("l").entries[1]), "l = { A C }"),
            ('names = { Mindelo "Rainha de Portugal"Lisboa }',
             lambda d: d.get("names").remove_entry(d.get("names").entries[1]), "names = { Mindelo Lisboa }"),
            ("color = { 10 {1 2}20 }", lambda d: d.get("color").remove_entry(d.get("color").entries[1]),
             "color = { 10 20 }"),
            ('l = { x"b"y }', lambda d: d.get("l").remove_entry(d.get("l").entries[1]), "l = { x y }"),
        ]
        for text, action, expected in cases:
            doc = parse(text).document
            action(doc)
            self.assertEqual(self.assertReparses(doc), expected, text)

    def test_glued_values_in_corpus(self):
        """Cada valor de los archivos reales que va pegado a lo siguiente se puede sustituir y borrar."""
        prefilter = re.compile(rb'\}[^\s{}"=<>!#]|"[^"\r\n]*"[^\s{}"=<>!#]')
        checked = 0
        for path in corpus_files(CLAUSEWITZ_SUFFIXES):
            if prefilter.search(path.read_bytes()) is None:
                continue
            result = parse_file(path)
            text = to_source(result.document)
            tokens = tokenize(text)
            glued = {tokens[i].offset for i in range(len(tokens) - 1)
                     if tokens[i].kind in (RBRACE, STRING) and not tokens[i + 1].trivia
                     and tokens[i + 1].kind in (WORD, STRING)}
            if not glued:
                continue
            for edit in ("replace", "remove"):
                doc = parse(text).document
                targets = []
                for block in blocks_of(doc):
                    for entry in block.entries:
                        value = entry.value
                        last = value._close if isinstance(value, Block) else entry._vtok
                        if last is not None and last.offset in glued:
                            targets.append((block, entry))
                for block, entry in targets:
                    if edit == "replace":
                        entry.value = Scalar("zz_word")
                    elif entry in block.entries:
                        block.remove_entry(entry)
                    checked += 1
                reparsed = parse(to_source(doc))
                self.assertEqual(to_json(reparsed.document), to_json(doc), (path, edit))
                self.assertEqual(len(reparsed.errors), len(result.errors), (path, edit))
        if not checked:
            self.skipTest("el corpus no tiene valores pegados al token siguiente")


class UndoTests(unittest.TestCase):
    """Deshacer una edición (reinsertar, devolver a su sitio, restaurar) da el texto original exacto (PE-04)."""

    TEXTS = [
        SAMPLE,
        "owner = AUS\r\ncontroller = AUS\r\nadd_core = AUS\r\n",
        "x = {\n\ta = 1\n\t# sobre b\n\tb = 2\n\n\tc = 3\n}\n",
        "a=1 b={c=2}d=3",
        'l = { A "B"C }',
        "# c\na = 1 # x\n\nb = { # y\n\tc = 2\n}\n# fin",
        "x = {\n\ta = 1 b =\n}\n",
    ]

    def _sources(self):
        files = corpus_files(CLAUSEWITZ_SUFFIXES)
        rng = random.Random(11)
        sample = rng.sample(files, min(60, len(files)))
        return self.TEXTS + [to_source(parse_file(path).document) for path in sample]

    def test_remove_and_reinsert_every_entry(self):
        rng = random.Random(5)
        checked = 0
        for text in self._sources():
            doc = parse(text).document
            pairs = [(block, entry) for block in blocks_of(doc) for entry in block.entries]
            for block, entry in rng.sample(pairs, min(25, len(pairs))):
                index = block.remove_entry(entry)
                block.insert_entry(index, entry)
                self.assertEqual(to_source(doc), text, entry)
                # La inversa sobre la lista (Block.entries es una lista normal) también vale.
                block.entries.remove(entry)
                block.entries.insert(index, entry)
                self.assertEqual(to_source(doc), text, entry)
                checked += 1
        self.assertGreater(checked, 40)

    def test_move_reorder_set_and_rename_back(self):
        text = 'a = { b = 1 } # c\nz = "q"\nw = {\n\tk = 1 # d\n}\n'
        doc = parse(text).document
        a, z, w = doc.entries
        steps = [
            (lambda: doc.move(a, 2), lambda: doc.move(a, 0)),
            (lambda: doc.move(a, to=w.value), lambda: w.value.move(a, 0, to=doc)),
            (lambda: doc.entries.reverse(), lambda: doc.entries.reverse()),
            (lambda: setattr(a, "value", 5), lambda value=a.value: setattr(a, "value", value)),
            (lambda: setattr(z, "value", "x"), lambda value=z.value: setattr(z, "value", value)),
            (lambda: setattr(z, "key", "y"), lambda: setattr(z, "key", "z")),
            (lambda: setattr(z, "op", ">"), lambda: setattr(z, "op", "=")),
        ]
        for do, undo in steps:
            do()
            self.assertNotEqual(to_source(doc), text)
            undo()
            self.assertEqual(to_source(doc), text)

    def test_restoring_the_read_value_after_several_changes(self):
        # Un bloque con su "}" más sangrada que su clave y una cadena sin cerrar al final del archivo:
        # al regenerarlos, el bloque se volvía a sangrar y la cadena se cerraba.
        text = 'a = {\n\tb = {\n\t\tlevel = 1\n\t\t}\n}\nname = "VSM'
        doc = parse(text).document
        b = doc.entries[0].value.entries[0]
        name = doc.entries[1]
        for entry, values in ((b, [5, [1, 2], Block()]), (name, ["x", 3, [4]])):
            read = entry.value
            for value in values:
                entry.value = value
                self.assertNotEqual(to_source(doc), text)
            entry.value = read
            self.assertEqual(to_source(doc), text, entry)
        name.value = 3
        name.value = Scalar("VSM", quoted=True)  # igual al leído, aunque sea otro objeto
        self.assertEqual(to_source(doc), text)


class CycleTests(unittest.TestCase):
    """Un bloque no puede quedar dentro de sí mismo; los recorridos lo detectan en vez de colgarse (PE-05)."""

    def fresh(self):
        doc = parse("country = {\n\tregiment = { type = infantry }\n}\n").document
        return doc, doc.get("country")

    def test_edits_that_would_create_a_cycle_are_rejected(self):
        selfish = {}
        selfish["x"] = selfish
        nested = []
        nested.append(nested)
        attempts = [
            lambda d, c: c.get("regiment").append("moved", c),
            lambda d, c: c.set("self", c),
            lambda d, c: c.get("regiment").insert(0, "x", c),
            lambda d, c: setattr(c.find("regiment"), "value", c),
            lambda d, c: c.get("regiment").set("x", {"y": c}),
            lambda d, c: c.set("x", Block.from_pairs([("a", c)])),
            lambda d, c: c.set("x", selfish),
            lambda d, c: c.set("x", nested),
            lambda d, c: c.get("regiment").insert_entry(0, d.find("country")),
            lambda d, c: d.move(d.find("country"), to=c.get("regiment")),
        ]
        for attempt in attempts:
            doc, country = self.fresh()
            with self.assertRaises(EditError) as ctx:
                attempt(doc, country)
            self.assertEqual(ctx.exception.code, "cycle")
            self.assertEqual(to_source(doc), "country = {\n\tregiment = { type = infantry }\n}\n")

    def test_traversals_detect_cycles_made_through_the_list(self):
        doc, country = self.fresh()
        country.get("regiment").entries.append(Entry("loop", "=", country))
        checks = [
            to_source, format_canonical, to_json, simplify, lambda d: list(walk(d)), lambda d: d.clone(),
            lambda d: d.path_of(Entry("x", "=", 1)), lambda d: write_file(Path("nunca.txt"), d),
        ]
        for check in checks:
            with self.assertRaises(EditError) as ctx:
                check(doc)
            self.assertEqual(ctx.exception.code, "cycle")
        self.assertEqual(doc.unclosed_blocks(), [])
        loop = {"a": []}
        loop["a"].append(loop)
        with self.assertRaises(EditError):
            list(iter_json(loop))


class UnclosedBlockTests(ReparseMixin, unittest.TestCase):
    """Bloques sin "}" en archivos del usuario: borrar no pierde comentarios (PE-06) y se pueden cerrar (PE-13).

    Una cadena sin cerrar se cierra cuando lo editado la deja de ser lo último del archivo.
    """

    TEXT = ("political_decisions = {\n\ta = { x = 1 }\n\t# Decisión de unificación: no borrar este comentario\n"
            "\tb = { y = 2 }\n")

    def test_removing_the_last_entry_keeps_the_comments_above(self):
        doc = parse(self.TEXT).document
        doc.get("political_decisions").remove("b")
        new = to_source(doc)
        self.assertEqual(new, self.TEXT[: self.TEXT.index("\tb = ")])
        self.assertEqual(to_json(parse(new).document), to_json(doc))

    def test_close_adds_the_missing_brace(self):
        doc = parse(self.TEXT).document
        decisions = doc.get("political_decisions")
        self.assertFalse(decisions.is_closed)
        self.assertEqual(doc.unclosed_blocks(), [decisions])
        decisions.close()
        self.assertTrue(decisions.is_closed)
        self.assertEqual(doc.unclosed_blocks(), [])
        doc.append("country_event", {"id": 1})
        self.assertEqual(self.assertReparses(doc), self.TEXT + "}\ncountry_event = {\n\tid = 1\n}\n")

    def test_close_nested_blocks(self):
        doc = parse("a = {\n\tb = {\n\t\tc = 1\n\t\t# fin c\n").document
        a = doc.get("a")
        b = a.get("b")
        self.assertEqual(doc.unclosed_blocks(), [a, b])
        b.close()
        self.assertEqual(to_source(doc), "a = {\n\tb = {\n\t\tc = 1\n\t\t# fin c\n\t}\n")
        self.assertEqual(doc.unclosed_blocks(), [a])
        a.close()
        self.assertEqual(self.assertReparses(doc), "a = {\n\tb = {\n\t\tc = 1\n\t\t# fin c\n\t}\n}\n")
        doc = parse("a = {\n    b = 1").document
        doc.get("a").close()
        self.assertEqual(self.assertReparses(doc), "a = {\n    b = 1\n}")

    def test_text_after_an_unterminated_string_closes_it(self):
        # La cadena sin cerrar llega hasta el final del archivo: lo escrito detrás quedaba dentro de ella.
        cases = [
            ('a = 1\nname = "Mod', lambda doc: doc.append("b", 2), 'a = 1\nname = "Mod"\nb = 2'),
            ('name = "Mod', lambda doc: setattr(doc.entries[0], "line_comment", "nota"), 'name = "Mod" # nota'),
            ('x = {\n\tname = "Mod', lambda doc: doc.get("x").close(), 'x = {\n\tname = "Mod"\n}'),
            ('b = 2\n"Mod', lambda doc: doc.move(doc.entries[1], 0), '"Mod"\nb = 2'),
        ]
        for text, edit, expected in cases:
            doc = parse(text).document
            self.assertEqual(to_source(doc), text)
            edit(doc)
            self.assertEqual(self.assertReparses(doc), expected)

    def test_save_after_closing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "decisiones.txt"
            path.write_bytes(self.TEXT.encode("cp1252"))
            result = parse_file(path)
            result.document.append("country_event", {"id": 1})
            # Sin cerrar, lo añadido a la raíz quedaría dentro del bloque abierto: no se guarda.
            with self.assertRaises(SourceMismatchError) as ctx:
                write_file(path, result)
            self.assertEqual((ctx.exception.params["entry"], ctx.exception.params["line"]),
                             ("political_decisions > country_event", 5))
            for block in result.document.unclosed_blocks():
                block.close()
            write_file(path, result, backup=False)
            saved = parse_file(path)
            self.assertTrue(saved.ok)
            self.assertEqual(saved.document.keys(), ["political_decisions", "country_event"])


class ValueTests(ReparseMixin, unittest.TestCase):
    """Valores de Python: por su valor numérico (PE-01), validados (PE-09) y decimales exactos (PE-10)."""

    def test_numbers_are_written_by_value_not_by_repr(self):
        class LoudInt(int):
            def __str__(self):
                return "LoudInt!"

            __repr__ = __str__

        class LoudFloat(float):
            def __repr__(self):
                return "LoudFloat!"

            __str__ = __repr__

        cases = [
            (np.float64(3092.0), "3092.0"), (np.array([3090.5, 3093.5]).mean(), "3092.0"), (np.int64(5), "5"),
            (np.uint8(200), "200"), (np.float32(0.1), "0.1"), (np.bool_(False), "no"), (LoudInt(5), "5"),
            (LoudFloat(0.25), "0.25"), (Fraction(1, 4), "0.25"),
        ]
        for value, expected in cases:
            doc = parse("x = 1\n").document
            doc.set("x", value)
            self.assertEqual(to_source(doc), f"x = {expected}\n", repr(value))
        doc = Document()
        doc.set(np.int64(7), 1)
        doc.set(LoudInt(9), [np.int32(1), np.float64(0.5)])
        self.assertEqual(self.assertReparses(doc), "7 = 1\n9 = { 1 0.5 }\n")
        self.assertIs(doc.find(np.int64(9)), doc.entries[1])
        for bad in (np.array([1, 2]), np.float64("nan")):
            with self.assertRaises(EditError):
                doc.set("x", bad)

    def test_numpy_value_saved_through_write_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "positions.txt"
            path.write_bytes(b"1 = {\r\n\tunit = {\r\n\t\tx = 3091.000000\r\n\t\ty = 1790.000000\r\n\t}\r\n}\r\n")
            result = parse_file(path)
            result.document.get("1").get("unit").set("x", np.array([3090.5, 3093.5]).mean())
            write_file(path, result, backup=False)
            self.assertEqual(path.read_bytes(), b"1 = {\r\n\tunit = {\r\n\t\tx = 3092.0\r\n\t\ty = 1790.000000\r\n\t}\r\n}\r\n")

    def test_floats_are_exact(self):
        cases = [
            (1.23456789012345e-5, "0.0000123456789012345"), (4e-13, "0.0000000000004"), (-4e-13, "-0.0000000000004"),
            (-0.0, "0.0"), (0.1 + 0.2, "0.30000000000000004"), (1e22, "10000000000000000000000.0"), (3092.0, "3092.0"),
        ]
        doc = parse("a = 1\n").document
        for value, text in cases:
            doc.set("a", value)
            self.assertEqual(to_source(doc), f"a = {text}\n")
            self.assertEqual(parse(to_source(doc)).document.get("a").as_float(), value)

    def test_values_the_game_cannot_read_are_rejected(self):
        doc = parse("name = Old\n").document
        for bad, code in [("Nueva\nGranada", "line_break"), ("a\rb", "line_break"), ("x\x01y", "control_character")]:
            with self.assertRaises(EditError) as ctx:
                doc.set("name", bad)
            self.assertEqual(ctx.exception.code, code, repr(bad))
        for key, code in [("", "empty_key"), ("a\nb", "line_break"), ("a\xa0b", "invisible_character"),
                          ('a"b', "quote_in_string")]:
            with self.assertRaises(EditError) as ctx:
                doc.append(key, 5)
            self.assertEqual(ctx.exception.code, code, repr(key))
        self.assertEqual(to_source(doc), "name = Old\n")
        # Un tab o un carácter invisible sí caben en un valor, entre comillas.
        doc.set("name", "x\xa0y")
        self.assertEqual(to_source(doc), 'name = "x\xa0y"\n')
        doc.set("name", "x\ty")
        self.assertEqual(self.assertReparses(doc), 'name = "x\ty"\n')

    def test_check_text_for_forms(self):
        doc = Document()
        error = doc.check_text("中文")
        self.assertEqual((error.code, error.params["char"], error.params["encoding"]), ("unencodable_character", "中", "cp1252"))
        self.assertNotEqual(error.message("es"), error.message("en"))
        self.assertIsNone(doc.check_text("Córdoba"))
        self.assertEqual(doc.check_text("a\nb").code, "line_break")
        self.assertEqual(doc.check_text("", key=True).code, "empty_key")
        self.assertIsNone(doc.check_text("dos palabras", key=True))
        doc.encoding = "utf-8"
        self.assertIsNone(doc.check_text("中文"))
        with self.assertRaises(TypeError):
            doc.check_text(5)


class ErrorMessageTests(unittest.TestCase):
    """Errores de la API con código estable y mensaje en español e inglés (PE-17)."""

    def test_codes_and_languages(self):
        doc = parse("a = 1\n").document
        # (acción, código, tipo de excepción estándar que también es)
        cases = [
            (lambda: doc.set("a", 'con "comillas"'), "quote_in_string", ValueError),
            (lambda: Scalar("dos palabras"), "needs_quotes", ValueError),
            (lambda: doc.set("a", object()), "unsupported_value", TypeError),
            (lambda: doc.set("a", float("inf")), "not_finite", ValueError),
            (lambda: doc.set(None, 1), "invalid_key_type", TypeError),
            (lambda: Entry("a", "=>", 1), "invalid_operator", ValueError),
            (lambda: doc.remove_entry(Entry("a", "=", 1)), "entry_not_in_block", ValueError),
            (lambda: ClausewitzDate(1861, 2, 30), "date_day_range", ValueError),
            (lambda: Scalar("x").as_int(), "not_an_integer", ValueError),
            (lambda: Block([1]), "not_an_entry", TypeError),
            (lambda: write_file("x.txt", Block()), "not_a_document", TypeError),
        ]
        for action, code, kind in cases:
            with self.assertRaises(EditError, msg=code) as ctx:
                action()
            error = ctx.exception
            self.assertIsInstance(error, kind)
            self.assertEqual(error.code, code)
            spanish, english = error.message("es"), error.message("en")
            self.assertNotEqual(spanish, english, code)
            self.assertEqual(str(error), spanish)
            self.assertNotIn("{", spanish + english)

    def test_source_mismatch_says_where(self):
        with tempfile.TemporaryDirectory() as tmp:
            # El mensaje lleva la ruta entera: en una ruta larga, lo que importa (el archivo) está al final (R3).
            folder = Path(tmp, "Paradox Interactive", "Victoria II", "mod", "VSM", "history", "provinces",
                          "south america")
            folder.mkdir(parents=True)
            path = folder / "2393 - Telen.txt"
            path.write_bytes(b"x = {\n\ta = 1\n\t= b\n}\n")
            result = parse_file(path)
            result.document.get("x").insert(1, None, 5)
            with self.assertRaises(SourceMismatchError) as ctx:
                write_file(path, result)
            error = ctx.exception
            self.assertEqual((error.code, error.params["entry"], error.params["line"]), ("source_mismatch", "x > [1]", 3))
            for lang in ("es", "en"):
                self.assertIn("'x > [1]'", error.message(lang))
                self.assertTrue(error.message(lang).startswith(str(path) + ": "))


class CloneTests(ReparseMixin, unittest.TestCase):
    """``clone()`` copia nodos a otro archivo con el formato del destino (PE-11)."""

    SOURCE = "# cabecera del archivo vanilla\nowner = FRA\nx = {\n\t# sobre b\n\tb = { c = 1 }\n}\n"

    def test_clone_takes_the_target_format(self):
        source = parse(self.SOURCE).document
        target = parse("w = {\n    q = 1\n}\n").document
        target.get("w").entries.append(source.find("owner").clone())
        target.get("w").entries.append(source.get("x").find("b").clone())
        self.assertEqual(self.assertReparses(target), (
            "w = {\n    q = 1\n    # cabecera del archivo vanilla\n    owner = FRA\n    # sobre b\n"
            "    b = {\n        c = 1\n    }\n}\n"
        ))
        bare = parse("w = {\n    q = 1\n}\n").document
        bare.get("w").append("owner", source.find("owner").clone(comments=False).value)
        bare.get("w").insert_entry(2, source.get("x").find("b").clone(comments=False))
        self.assertEqual(self.assertReparses(bare), "w = {\n    q = 1\n    owner = FRA\n    b = {\n        c = 1\n    }\n}\n")
        self.assertEqual(to_source(source), self.SOURCE)

    def test_clone_is_deep_and_keeps_quotes_and_line_comments(self):
        oob = parse('army = {\n\tname = "A"\n\tregiment = { name = "1st" type = infantry home = 1854 } # primero\n}\n')
        mod = parse('army = {\n    name = "A"\n}\n').document
        copy = oob.document.get("army").find("regiment").clone()
        mod.get("army").insert_entry(1, copy)
        self.assertEqual(self.assertReparses(mod), (
            'army = {\n    name = "A"\n    regiment = {\n        name = "1st"\n        type = infantry\n'
            "        home = 1854\n    } # primero\n}\n"
        ))
        copy.value.set("home", 1)
        self.assertEqual(oob.document.get("army").get("regiment").get_text("home"), "1854")
        whole = oob.document.get("army").clone(comments=False)
        self.assertEqual(format_canonical(whole), format_canonical(oob.document.get("army")))

    def test_clone_with_comments_into_a_one_line_block(self):
        # R1: el comentario de línea de lo copiado se tragaba la "}" del bloque de una línea, y se guardaba así.
        vanilla = parse('leader = {\n\tname = "Moltke"\n\ttype = land # tierra\n}\n').document
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "PRU_oob.txt"
            path.write_bytes(b"army = { leader = none }\r\n")
            result = parse_file(path)
            result.document.get("army").find("leader").value = vanilla.get("leader").clone()
            write_file(path, result, backup=False)
            self.assertEqual(path.read_bytes(), (b'army = {\r\n\tleader = {\r\n\t\tname = "Moltke"\r\n'
                                                 b'\t\ttype = land # tierra\r\n\t}\r\n}\r\n'))
            self.assertEqual(parse_file(path).diagnostics, [])
        doc = parse("army = { leader = none }\nname = x\n").document
        doc.get("army").find("leader").value = vanilla.get("leader").clone()
        self.assertEqual(self.assertReparses(doc), (
            'army = {\n\tleader = {\n\t\tname = "Moltke"\n\t\ttype = land # tierra\n\t}\n}\nname = x\n'))
        # Lo mismo con los setters de comentarios.
        doc = parse("x = { a = 1 }\n").document
        doc.get("x").trailing_comments = ["fin"]
        doc.get("x").append("b", {"c": 1}).value.find("c").line_comment = "nota"
        self.assertEqual(self.assertReparses(doc), "x = {\n\ta = 1\n\t# fin\n\tb = {\n\t\tc = 1 # nota\n\t}\n}\n")


class EditorApiTests(ReparseMixin, unittest.TestCase):
    """Utilidades para los editores: pares, rutas, búsqueda por valor, operadores y comentarios (PE-12, PE-14)."""

    def test_from_pairs_builds_repeated_keys_and_operators(self):
        block = Block.from_pairs([("tag", "GEL"), ("tag", "MAJ"), ("literacy", ">", 0.5), (None, "suelto")])
        doc = Document()
        doc.set("OR", block)
        self.assertEqual(self.assertReparses(doc), "OR = {\n\ttag = GEL\n\ttag = MAJ\n\tliteracy > 0.5\n\tsuelto\n}\n")
        for bad in [("a",), ("a", "=", 1, 2), "ab", 5]:
            with self.assertRaises(TypeError, msg=repr(bad)):
                Block.from_pairs([bad])
        with self.assertRaises(EditError):
            Block.from_pairs([("a", "=>", 1)])

    def test_paths(self):
        doc = parse("country_event = {\n\tid = 1\n\toption = {\n\t\tname = A\n\t}\n\toption = {\n\t\tname = B\n\t}\n}\n"
                    "l = { 1 2 3 }\n").document
        self.assertEqual(doc.find_path(("country_event", "option", "name")).value, Scalar("A"))
        self.assertEqual(doc.get_path(("country_event", "[2]", "name")), Scalar("B"))
        self.assertEqual(doc.get_path(["l", "[2]"]), Scalar("3"))
        self.assertEqual(doc.get_path(("x", "y"), "nada"), "nada")
        self.assertIsNone(doc.find_path(("country_event", "id", "z")))
        self.assertIs(doc.find_path(("COUNTRY_EVENT", "ID"), ignore_case=True), doc.get("country_event").entries[0])
        second = doc.get("country_event").find_all("option")[1].value.find("name")
        self.assertEqual(doc.path_of(second), ("country_event", "[2]", "name"))
        for _, entry in walk(doc):
            self.assertIs(doc.find_path(doc.path_of(entry)), entry)
        self.assertIsNone(doc.path_of(Entry("z", "=", 1)))
        with self.assertRaises(TypeError):
            doc.find_path("country_event")

    def test_find_and_remove_by_value(self):
        doc = parse("c = {\n\tadd_core = GEL\n\tadd_core = RUS\n\tprestige = 5.000\n\tstart = 1861.01.01\n}\n").document
        c = doc.get("c")
        self.assertIs(c.find("add_core", "RUS"), c.entries[1])
        self.assertIs(c.find("prestige", 5), c.entries[2])
        self.assertIs(c.find("start", ClausewitzDate(1861, 1, 1)), c.entries[3])
        self.assertIsNone(c.find("add_core", "MAJ"))
        self.assertEqual(c.find_all("add_core", Scalar("GEL")), [c.entries[0]])
        self.assertEqual(c.remove("add_core", "RUS"), 1)
        self.assertEqual(to_source(doc), "c = {\n\tadd_core = GEL\n\tprestige = 5.000\n\tstart = 1861.01.01\n}\n")

    def test_set_with_operator_and_inserts_next_to_an_entry(self):
        doc = parse("c = {\n\tadd_core = GEL\n\tprestige = 5\n}\n").document
        c = doc.get("c")
        c.set("literacy", 0.5, op=">")
        c.set("prestige", 6, op=">=")
        c.insert_before(c.find("prestige"), "first", 1)
        c.insert_after(c.find("prestige"), "after", 2)
        self.assertEqual(self.assertReparses(doc), (
            "c = {\n\tadd_core = GEL\n\tfirst = 1\n\tprestige >= 6\n\tafter = 2\n\tliteracy > 0.5\n}\n"
        ))
        with self.assertRaises(EditError):
            c.set("x", 1, op="=>")
        with self.assertRaises(EditError):
            c.insert_after(Entry("z", "=", 1), "k", 1)

    def test_comment_setters(self):
        doc = parse("c = {\n\t# viejo\n\tprestige = 5 # nota vieja\n\tb = 1\n\t# fin viejo\n}\n").document
        c = doc.get("c")
        prestige = c.find("prestige")
        self.assertEqual((prestige.comments, prestige.line_comment), (["# viejo"], "# nota vieja"))
        self.assertEqual((c.open_comment, c.trailing_comments), (None, ["# fin viejo"]))
        prestige.comments = ["sobre prestige", "# segunda"]
        prestige.line_comment = "nota"
        c.open_comment = "abre"
        c.trailing_comments = "fin"
        self.assertEqual(to_source(doc), "c = { # abre\n\t# sobre prestige\n\t# segunda\n\tprestige = 5 # nota\n\tb = 1\n\t# fin\n}\n")
        self.assertEqual(to_json(parse(to_source(doc)).document, include_comments=True),
                         to_json(doc, include_comments=True))
        prestige.comments = []
        prestige.line_comment = None
        c.open_comment = None
        c.trailing_comments = []
        self.assertEqual(to_source(doc), "c = {\n\tprestige = 5\n\tb = 1\n}\n")
        with self.assertRaises(EditError):
            prestige.line_comment = "uno\ndos"
        with self.assertRaises(EditError):
            prestige.comments = ["x\x01"]

    def test_index_by_key(self):
        c = parse("c = { a = 1 A = 2 b = 3 a = 4 }").document.get("c")
        self.assertEqual({key: [e.value.text for e in found] for key, found in c.index_by_key().items()},
                         {"a": ["1", "4"], "A": ["2"], "b": ["3"]})
        self.assertEqual([e.value.text for e in c.index_by_key(ignore_case=True)["a"]], ["1", "2", "4"])


class LayoutTests(ReparseMixin, unittest.TestCase):
    """Forma de lo añadido o quitado: bloques de una línea (PE-15), detalles (PE-16) y sangría (PE-07)."""

    EVENT = "country_event = {\n\tid = 1\n\timmediate = { clr_country_flag = the_slavery_debate }\n}\n"

    def test_one_line_block_grows_to_several_lines_when_needed(self):
        doc = parse(self.EVENT).document
        doc.get("country_event").get("immediate").append(
            "any_owned", {"limit": {"is_core": "CSA", "NOT": {"owned_by": "CSA"}}, "secede_province": "CSA"})
        self.assertEqual(self.assertReparses(doc), (
            "country_event = {\n\tid = 1\n\timmediate = {\n\t\tclr_country_flag = the_slavery_debate\n"
            "\t\tany_owned = {\n\t\t\tlimit = {\n\t\t\t\tis_core = CSA\n\t\t\t\tNOT = {\n\t\t\t\t\towned_by = CSA\n"
            "\t\t\t\t}\n\t\t\t}\n\t\t\tsecede_province = CSA\n\t\t}\n\t}\n}\n"
        ))
        small = parse(self.EVENT).document
        small.get("country_event").get("immediate").append("set_country_flag", "x")
        self.assertIn("\timmediate = { clr_country_flag = the_slavery_debate set_country_flag = x }\n",
                      self.assertReparses(small))
        values = parse("l = { 1 2 3 }\n").document
        for number in range(100, 130):
            values.get("l").append_value(number)
        self.assertEqual(self.assertReparses(values), (
            "l = {\n\t1 2 3 100 101 102 103 104 105 106 107 108 109 110 111 112 113 114 115 116\n"
            "\t117 118 119 120 121 122 123 124 125 126 127 128 129\n}\n"
        ))

    def test_replaced_values_unfold_one_line_blocks(self):
        # PE-15: también al sustituir el valor de una entrada (set de una clave que ya existe o Entry.value).
        flag = {"limit": {"is_core": "CSA", "NOT": {"owned_by": "CSA"}}, "secede_province": "CSA"}
        expected = (
            "country_event = {\n\tid = 1\n\timmediate = {\n\t\tclr_country_flag = {\n\t\t\tlimit = {\n"
            "\t\t\t\tis_core = CSA\n\t\t\t\tNOT = {\n\t\t\t\t\towned_by = CSA\n\t\t\t\t}\n\t\t\t}\n"
            "\t\t\tsecede_province = CSA\n\t\t}\n\t}\n}\n"
        )
        by_set = parse(self.EVENT).document
        by_set.get("country_event").get("immediate").set("clr_country_flag", flag)
        self.assertEqual(self.assertReparses(by_set), expected)
        by_value = parse(self.EVENT).document
        by_value.get("country_event").get("immediate").find("clr_country_flag").value = flag
        self.assertEqual(self.assertReparses(by_value), expected)
        small = parse(self.EVENT).document
        small.get("country_event").get("immediate").set("clr_country_flag", {"a": 1})
        self.assertIn("\timmediate = { clr_country_flag = { a = 1 } }\n", self.assertReparses(small))
        # Un bloque leído de varias líneas que pasa a un bloque de una línea también lo despliega.
        moved = parse("x = { a = 1 }\ny = {\n\tb = 2\n}\n").document
        moved.get("x").find("a").value = moved.get("y")
        moved.remove("y")
        self.assertEqual(self.assertReparses(moved), "x = {\n\ta = {\n\t\tb = 2\n\t}\n}\n")

    def test_comments_unfold_one_line_blocks(self):
        # R5: la "}" del bloque desplegado va con la sangría de su línea, no con la de las entradas.
        cases = [
            ("x = { }\n", lambda d: setattr(d.get("x"), "trailing_comments", ["fin"]), "x = {\n\t# fin\n}\n"),
            ("y = {\n    x = { b = 1 }\n}\n", lambda d: setattr(d.get("y").get("x"), "trailing_comments", ["fin"]),
             "y = {\n    x = {\n        b = 1\n        # fin\n    }\n}\n"),
            ("x = { a = 1 }\n", lambda d: setattr(d.get("x"), "open_comment", "abre"), "x = { # abre\n\ta = 1\n}\n"),
            ("x = { a = 1 b = 2 }\n", lambda d: setattr(d.get("x").find("b"), "comments", ["sobre b"]),
             "x = {\n\ta = 1\n\t# sobre b\n\tb = 2\n}\n"),
            ("x = { a = 1 b = 2 }\n", lambda d: setattr(d.get("x").find("a"), "line_comment", "nota"),
             "x = {\n\ta = 1 # nota\n\tb = 2\n}\n"),
            ("l = { 1 2 3 }\n", lambda d: setattr(d.get("l").entries[1], "comments", ["dos"]),
             "l = {\n\t1\n\t# dos\n\t2 3\n}\n"),
            ("a = { b = { c = { d = 1 } } }\n",
             lambda d: setattr(d.get_path(("a", "b", "c")).find("d"), "comments", "x"),
             "a = {\n\tb = {\n\t\tc = {\n\t\t\t# x\n\t\t\td = 1\n\t\t}\n\t}\n}\n"),
        ]
        for text, action, expected in cases:
            doc = parse(text).document
            action(doc)
            self.assertEqual(self.assertReparses(doc), expected, text)
        # Quitar los comentarios devuelve el texto original.
        doc = parse("x = { a = 1 b = 2 }\n").document
        x = doc.get("x")
        x.find("a").line_comment, x.find("b").comments, x.trailing_comments = "nota", ["sobre b"], ["fin"]
        x.find("a").line_comment, x.find("b").comments, x.trailing_comments = None, [], []
        self.assertEqual(to_source(doc), "x = { a = 1 b = 2 }\n")

    def test_nested_one_line_blocks_unfold_together(self):
        flag = {"limit": {"is_core": "CSA"}}
        doc = parse("trigger = { NOT = { tag = FRA } other = { a = 1 } }\n").document
        doc.get("trigger").get("NOT").append("any_owned_province", flag)
        self.assertEqual(self.assertReparses(doc), (
            "trigger = {\n\tNOT = {\n\t\ttag = FRA\n\t\tany_owned_province = {\n\t\t\tlimit = {\n"
            "\t\t\t\tis_core = CSA\n\t\t\t}\n\t\t}\n\t}\n\tother = { a = 1 }\n}\n"))
        small = parse("trigger = { NOT = { tag = FRA } }\n").document
        small.get("trigger").get("NOT").append("x", "yes")
        self.assertEqual(self.assertReparses(small), "trigger = { NOT = { tag = FRA x = yes } }\n")

    def test_commented_values_next_to_discarded_text_stay_valid(self):
        # Con texto descartado entre los tokens el bloque no se despliega (se perdería): lo comentado va en
        # varias líneas dentro de él y el archivo se relee igual, con los mismos errores.
        doc = parse("x = { a = 1 = 2 }\ny = 3\n").document
        doc.get("x").append("b", {"c": 1}).value.find("c").line_comment = "nota"
        text = to_source(doc)
        self.assertEqual(text, "x = { a = 1 = 2 b = {\n\tc = 1 # nota\n} }\ny = 3\n")
        result = parse(text)
        self.assertEqual([d.code for d in result.diagnostics], ["missing_key"])
        self.assertEqual(to_json(result.document), to_json(doc))

    def test_edits_next_to_braces_and_the_end_of_file(self):
        cases = [
            ("a={b=1 c=2}\n", lambda d: d.get("a").remove("b"), "a={c=2}\n"),
            ("x = {\n\ta = 1 }\n", lambda d: d.get("x").remove("a"), "x = { }\n"),
            ("a = 1\n# fin", lambda d: d.append("z", 1), "a = 1\n# fin\nz = 1"),
            ("a = 1\n# fin\n", lambda d: d.append("z", 1), "a = 1\n# fin\nz = 1\n"),
            ("a = 1\nb = 2", lambda d: d.remove("b"), "a = 1"),
            ("add_core = GEL\nadd_core = RUS\n", lambda d: d.remove("add_core"), ""),
        ]
        for text, action, expected in cases:
            doc = parse(text).document
            action(doc)
            self.assertEqual(self.assertReparses(doc), expected, text)

    def test_generated_indentation_follows_the_majority(self):
        # Archivo con un primer bloque sangrado con espacios y el resto con tabs (history/units).
        oob = parse('leader = {\r\n   name = "A"\r\n   type = land\r\n}\r\n\r\narmy = {\r\n\tname = "B"\r\n\tregiment = {\r\n'
                    '\t\tname = "1st"\r\n\t\ttype = irregular\r\n\t}\r\n}\r\n').document
        oob.get("army").append("regiment", {"name": "2nd", "type": "infantry"})
        self.assertTrue(self.assertReparses(oob).endswith(
            "\t}\r\n\tregiment = {\r\n\t\tname = 2nd\r\n\t\ttype = infantry\r\n\t}\r\n}\r\n"))
        # El primer hermano está mal sangrado; los demás usan 8 espacios.
        decisions = parse(
            "political_decisions = {\n    unite = {\n    picture = x\n        potential = { a = 1 }\n"
            "        allow = { b = 1 }\n        effect = { c = 1 }\n        ai_will_do = {\n            factor = 1\n"
            "        }\n    }\n}\n").document
        decisions.get("political_decisions").get("unite").append("ai_will_do_extra", {"factor": 2})
        self.assertTrue(self.assertReparses(decisions).endswith(
            "        }\n        ai_will_do_extra = {\n            factor = 2\n        }\n    }\n}\n"))


class SerializerCostTests(unittest.TestCase):
    """Lo no editado se escribe sin trabajo de más (R4: to_source y format_canonical eran un 45-70 % más lentos)."""

    TEXT = 'a = {\n\tb = { c = 1 d = { 1 2 } } # nota\n\te = "f"\n}\ng = { h = 1 }\ni = 2\n'

    @staticmethod
    def calls(method, action):
        """(resultado de ``action``, veces que ha llamado a ``_Writer.<method>``)."""
        original = getattr(serializer._Writer, method)
        with mock.patch.object(serializer._Writer, method, autospec=True, side_effect=original) as spy:
            return action(), spy.call_count

    def test_unedited_blocks_are_copied_without_frames(self):
        doc = parse(self.TEXT).document
        self.assertEqual(self.calls("_open_frame", lambda: to_source(doc)), (self.TEXT, 0))
        # Solo pasan por el recorrido con marcos los bloques que contienen el cambio: a, b y d.
        inner = doc.get("a").get("b").get("d")
        added = inner.append_value(3)
        self.assertEqual(self.calls("_open_frame", lambda: to_source(doc)),
                         (self.TEXT.replace("{ 1 2 }", "{ 1 2 3 }"), 3))
        inner.remove_entry(added)
        self.assertEqual(self.calls("_open_frame", lambda: to_source(doc)), (self.TEXT, 0))
        # Un cambio al final de "a" deshace lo que se había copiado de él; "b" se vuelve a copiar entero.
        doc.get("a").set("e", "x")
        self.assertEqual(self.calls("_open_frame", lambda: to_source(doc)), (self.TEXT.replace('"f"', '"x"'), 1))

    def test_canonical_indents_without_rescanning_lines(self):
        doc = parse(self.TEXT).document
        expected = 'a = {\n\tb = {\n\t\tc = 1\n\t\td = { 1 2 }\n\t} # nota\n\te = "f"\n}\ng = {\n\th = 1\n}\ni = 2\n'
        self.assertEqual(self.calls("_line_text_at", lambda: format_canonical(doc, comments=True)), (expected, 0))


class WriteFileSessionTests(unittest.TestCase):
    """Una sola codificación (la del documento), .bak original y huella al día tras guardar (PE-18)."""

    def test_encoding_has_a_single_source_and_backup_stays_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "HAI_oob.txt"
            original = 'name = "Armée"\n'.encode("utf-8")
            path.write_bytes(original)
            result = parse_file(path)
            self.assertEqual((result.encoding, result.document.encoding), ("utf-8", "utf-8"))
            result.document.encoding = "cp1252"
            self.assertEqual(result.encoding, "cp1252")
            backup = write_file(path, result)
            self.assertEqual(path.read_bytes(), 'name = "Armée"\n'.encode("cp1252"))
            self.assertEqual(backup.read_bytes(), original)
            result.document.set("name", "Otra")
            self.assertEqual(write_file(path, result), backup)
            self.assertEqual(backup.read_bytes(), original)
            result.encoding = "utf-8"
            write_file(path, result)
            self.assertEqual(path.read_bytes(), b'name = "Otra"\n')
            self.assertEqual(backup.read_bytes(), original)

    def test_expected_stamp_follows_own_saves(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_bytes(b"a = 1\n")
            result = parse_file(path)
            for value in (2, 3):
                result.document.set("a", value)
                write_file(path, result, expected=result.stamp, backup=False)
            self.assertEqual(path.read_bytes(), b"a = 3\n")
            path.write_bytes(b"a = 9\n")  # cambio hecho fuera de la aplicación
            result.document.set("a", 4)
            with self.assertRaises(FileChangedError):
                write_file(path, result, expected=result.stamp, backup=False)
            self.assertEqual(path.read_bytes(), b"a = 9\n")


if __name__ == "__main__":
    unittest.main()
