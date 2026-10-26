import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.clausewitz import (  # noqa: E402
    Block,
    Document,
    Entry,
    Scalar,
    format_canonical,
    from_json,
    parse,
    simplify,
    to_json,
    to_source,
    walk,
)

MESSY = (
    "# cabecera\n"
    "tag=GEL  color={97   209 251}\n"
    "1861.1.1 = {owner = GEL controller=GEL # fin de línea\n"
    "    add_core = GEL add_core = RUS }\n"
    "\"nombre con espacios\" = \"Nueva Georgia\"\n"
    "anon = { { a = b } { } }\n"
    "trigger = { literacy > 0.5 NOT = { tag = RUS } }\n"
    "empty = {}\n"
    "# comentario final\n"
)


def S(text, quoted=False):
    return {"type": "scalar", "text": text, "quoted": quoted}


def B(*entries):
    return {"type": "block", "entries": list(entries)}


def E(key, value, op="="):
    return {"key": None if key is None else S(key), "op": None if key is None else op, "value": value}


class ToJsonTests(unittest.TestCase):
    def test_exact_schema(self):
        doc = parse('a = { 1 "b c" }\nk > 2\n{ x = y }').document
        self.assertEqual(to_json(doc), B(
            E("a", B(E(None, S("1")), E(None, S("b c", True)))),
            E("k", S("2"), ">"),
            E(None, B(E("x", S("y")))),
        ))
        self.assertEqual(to_json(doc.entries[1]), E("k", S("2"), ">"))
        self.assertEqual(to_json(Scalar("x y", quoted=True)), S("x y", True))
        self.assertEqual(json.loads(json.dumps(to_json(doc))), to_json(doc))

    def test_errors_are_not_exported(self):
        doc = parse("a = 1\n}\nb = = 2\nc =\n").document
        self.assertEqual(to_json(doc), B(E("a", S("1")), E("b", S("2"))))

    def test_include_comments(self):
        doc = parse("# cabecera\na = 1 # sobre a\n# antes de b\nb = {\n\tc = 2\n\t# fin de b\n}\n# fin\n").document
        self.assertEqual(to_json(doc, include_comments=True), {
            "type": "block",
            "entries": [
                {**E("a", S("1")), "comments": ["# cabecera"]},
                {**E("b", {"type": "block", "entries": [E("c", S("2"))], "trailing_comments": ["# fin de b"]}),
                 "comments": ["# sobre a", "# antes de b"]},
            ],
            "trailing_comments": ["# fin"],
        })
        self.assertNotIn("comments", json.dumps(to_json(doc)))

    def test_rejects_other_objects(self):
        with self.assertRaises(TypeError):
            to_json("a = b")


class FromJsonTests(unittest.TestCase):
    def test_builds_canonical_document(self):
        doc = from_json(B(E("a", S("1")), E("b", B(E(None, S("x")), E(None, S("y z", True)))), E("c", S("2"), "<")))
        self.assertIsInstance(doc, Document)
        self.assertEqual((doc.newline, doc.encoding), ("\n", None))
        expected = 'a = 1\nb = { x "y z" }\nc < 2\n'
        self.assertEqual(format_canonical(doc), expected)
        self.assertEqual(to_source(doc), expected)

    def test_invariant(self):
        samples = [MESSY, "", "# solo comentario", "a = { b = { c = { d = e } } }", 'x = "abierta\ny = 1',
                   "{ a } = b", "}}} a = 1 {{{", "l = { 1 2 3 a = b 4 }", 'q = "a # b { }"', "a = b = c = d"]
        for text in samples:
            original = to_json(parse(text).document)
            rebuilt = to_json(parse(format_canonical(from_json(original))).document)
            self.assertEqual(rebuilt, original, text)

    def test_comments_round_trip(self):
        text = "# cabecera\na = 1 # sobre a\nb = {\n\tc = 2\n\t# fin de b\n}\n# fin\n"
        exported = to_json(parse(text).document, include_comments=True)
        doc = from_json(exported)
        self.assertEqual(to_source(doc), (
            "# cabecera\na = 1\n# sobre a\nb = {\n\tc = 2\n\t# fin de b\n}\n# fin\n"
        ))
        self.assertEqual(to_json(parse(to_source(doc)).document, include_comments=True), exported)
        entry = {**E("a", S("1")), "comments": ["sin almohadilla", "# dos\n# tres"]}
        self.assertEqual(to_source(from_json(B(entry))), "# sin almohadilla\n# dos\n# tres\na = 1\n")

    def test_validation_errors_report_path(self):
        cases = [
            ([], "$"),
            ({"type": "block"}, "$.entries"),
            (B("x"), "$.entries[0]"),
            (B({"key": S("a"), "op": None, "value": S("1")}), "$.entries[0]"),
            (B({"key": None, "op": "=", "value": S("1")}), "$.entries[0]"),
            (B({"key": S("a"), "op": "=>", "value": S("1")}), "$.entries[0].op"),
            (B(E("a", S("dos palabras"))), "$.entries[0].value"),
            (B(E("a", S('con "comillas"', True))), "$.entries[0].value"),
            (B(E("a", {"type": "scalar", "text": 5})), "$.entries[0].value"),
            (B(E("a", B(E("b", {"type": "other"})))), "$.entries[0].value.entries[0].value"),
            (B({**E("a", S("1")), "comments": "no es lista"}), "$.entries[0].comments"),
        ]
        for obj, where in cases:
            with self.assertRaises(ValueError, msg=where) as ctx:
                from_json(obj)
            self.assertTrue(str(ctx.exception).startswith(where + ":"), (where, str(ctx.exception)))


class SimplifyTests(unittest.TestCase):
    def test_shapes_and_scalars(self):
        doc = parse(MESSY).document
        self.assertEqual(simplify(doc), {
            "tag": "GEL",
            "color": [97, 209, 251],
            "1861.1.1": {"owner": "GEL", "controller": "GEL", "add_core": ["GEL", "RUS"]},
            "nombre con espacios": "Nueva Georgia",
            "anon": [{"a": "b"}, {}],
            "trigger": {"literacy": 0.5, "NOT": {"tag": "RUS"}},
            "empty": {},
        })

    def test_values(self):
        doc = parse('l = { yes no Yes 1 -2 0.5 1. "15" 1861.1.1 -0.5x }\nmix = { 1 a = b 2 }').document
        self.assertEqual(simplify(doc.get("l")), [True, False, True, 1, -2, 0.5, 1.0, "15", "1861.1.1", "-0.5x"])
        self.assertEqual(simplify(doc.get("mix")), [1, {"a": "b"}, 2])
        self.assertEqual(simplify(doc.find("mix")), [1, {"a": "b"}, 2])
        self.assertIs(simplify(Scalar("yes")), True)
        self.assertEqual(simplify(Block()), {})

    def test_deep_nesting_is_iterative(self):
        doc = parse("a = {" * 3000 + "b = 1" + "}" * 3000).document
        node = simplify(doc)
        for _ in range(3000):
            node = node["a"]
        self.assertEqual(node, {"b": 1})


class WalkTests(unittest.TestCase):
    def test_paths_in_depth_first_order(self):
        doc = parse("a = { b = 1 c = { 7 8 } }\nd = 2\n{ e = 3 }").document
        self.assertEqual([path for path, _ in walk(doc)], [
            ("a",), ("a", "b"), ("a", "c"), ("a", "c", "[0]"), ("a", "c", "[1]"), ("d",), ("[2]",), ("[2]", "e"),
        ])
        entries = dict((path, entry) for path, entry in walk(doc))
        self.assertEqual(entries[("a", "c", "[1]")].value.text, "8")

    def test_walk_from_entry_and_block(self):
        doc = parse("a = { b = { c = 1 } }").document
        self.assertEqual([p for p, _ in walk(doc.find("a"))], [("a",), ("a", "b"), ("a", "b", "c")])
        self.assertEqual([p for p, _ in walk(doc.get("a"))], [("b",), ("b", "c")])
        with self.assertRaises(TypeError):
            list(walk(Scalar("x")))

    def test_walk_scalar_entry(self):
        entry = Entry("x", "=", 1)
        self.assertEqual([(p, e) for p, e in walk(entry)], [(("x",), entry)])


class CanonicalTests(unittest.TestCase):
    def test_normalized_output(self):
        doc = parse(MESSY).document
        self.assertEqual(format_canonical(doc), (
            "tag = GEL\n"
            "color = { 97 209 251 }\n"
            "1861.1.1 = {\n"
            "\towner = GEL\n"
            "\tcontroller = GEL\n"
            "\tadd_core = GEL\n"
            "\tadd_core = RUS\n"
            "}\n"
            '"nombre con espacios" = "Nueva Georgia"\n'
            "anon = {\n"
            "\t{\n"
            "\t\ta = b\n"
            "\t}\n"
            "\t{ }\n"
            "}\n"
            "trigger = {\n"
            "\tliteracy > 0.5\n"
            "\tNOT = {\n"
            "\t\ttag = RUS\n"
            "\t}\n"
            "}\n"
            "empty = { }\n"
        ))

    def test_options(self):
        doc = parse("a = { b = { c = 1 } }").document
        self.assertEqual(format_canonical(doc, indent="  ", newline="\r\n"),
                         "a = {\r\n  b = {\r\n    c = 1\r\n  }\r\n}\r\n")
        commented = parse("# uno\na = 1 # dos\nb = { # tres\n\tc = 2\n\t# cuatro\n}\n# cinco").document
        self.assertEqual(format_canonical(commented, comments=True),
                         "# uno\na = 1\n# dos\nb = {\n\t# tres\n\tc = 2\n\t# cuatro\n}\n# cinco\n")
        self.assertEqual(format_canonical(commented), "a = 1\nb = {\n\tc = 2\n}\n")

    def test_lists_inline_or_wrapped(self):
        doc = Document()
        doc.append("short", [1, 2, 3])
        doc.append("long", list(range(100, 140)))
        doc.append("mixed", [1, {"a": 1}])
        text = format_canonical(doc)
        self.assertTrue(text.startswith("short = { 1 2 3 }\nlong = {\n\t100 101 "), text)
        long_lines = text.split("long = {\n")[1].split("}\n")[0].splitlines()
        self.assertGreater(len(long_lines), 1)
        self.assertTrue(all(len(line.expandtabs(4)) <= 84 for line in long_lines))
        self.assertTrue(text.endswith("mixed = {\n\t1\n\t{\n\t\ta = 1\n\t}\n}\n"), text)
        self.assertEqual(to_json(parse(text).document), to_json(doc))

    def test_other_nodes(self):
        doc = parse("a = { b = 1 }").document
        self.assertEqual(format_canonical(doc.find("a")), "a = {\n\tb = 1\n}")
        self.assertEqual(format_canonical(doc.get("a")), "{\n\tb = 1\n}")
        self.assertEqual(format_canonical(Scalar("x y", quoted=True)), '"x y"')
        self.assertEqual(format_canonical(Document()), "")
        self.assertEqual(to_source(doc.find("a")), "a = { b = 1 }")
        self.assertEqual(to_source(doc.get("a")), "{ b = 1 }")


if __name__ == "__main__":
    unittest.main()
