import codecs
import difflib
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import CLAUSEWITZ_SUFFIXES, corpus_files  # noqa: E402
from vic2studio.core.clausewitz import (  # noqa: E402
    Block,
    ClausewitzDate,
    Document,
    Entry,
    Scalar,
    SourceMismatchError,
    parse,
    parse_file,
    to_json,
    to_source,
    walk,
    write_file,
)
from vic2studio.core.encoding import UnencodableTextError  # noqa: E402

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
        for path in rng.sample(files, min(400, len(files))):
            result = parse_file(path)
            original = to_source(result.document)
            candidates = [e for _, e in walk(result.document) if e.key is not None and isinstance(e.value, Scalar)]
            if not candidates:
                continue
            entry = rng.choice(candidates)
            token = entry._vtok
            entry.value = "zz_new_value"
            new = to_source(result.document)
            start = token.offset
            self.assertEqual(new, original[:start] + "zz_new_value" + original[start + len(token.raw):], path)
            checked += 1
        self.assertGreater(checked, 100)


if __name__ == "__main__":
    unittest.main()
