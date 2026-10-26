import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.clausewitz.lexer import (  # noqa: E402
    EOF,
    INVALID,
    LBRACE,
    OP,
    OPEN_STRING,
    RBRACE,
    STRING,
    WORD,
    is_clean_trivia,
    last_line_indent,
    newline_split,
    tokenize,
    trivia_comments,
)


def kinds(text):
    return [(t.kind, t.raw) for t in tokenize(text)[:-1]]


class LexerTests(unittest.TestCase):
    def assertLossless(self, text):
        tokens = tokenize(text)
        self.assertEqual(tokens[-1].kind, EOF)
        self.assertEqual("".join(t.trivia + t.raw for t in tokens), text)
        return tokens

    def test_compact_assignments(self):
        self.assertEqual(kinds("a=b"), [(WORD, "a"), (OP, "="), (WORD, "b")])
        self.assertEqual(
            kinds("a={b}"), [(WORD, "a"), (OP, "="), (LBRACE, "{"), (WORD, "b"), (RBRACE, "}")]
        )
        self.assertEqual(kinds("yes}"), [(WORD, "yes"), (RBRACE, "}")])
        self.assertEqual(kinds("}}"), [(RBRACE, "}"), (RBRACE, "}")])
        self.assertEqual(kinds("{{}"), [(LBRACE, "{"), (LBRACE, "{"), (RBRACE, "}")])

    def test_operators(self):
        self.assertEqual(kinds("= ="), [(OP, "="), (OP, "=")])
        self.assertEqual(kinds("=="), [(OP, "==")])
        self.assertEqual(
            kinds("a<=b>=c<d>e!=f"),
            [(WORD, "a"), (OP, "<="), (WORD, "b"), (OP, ">="), (WORD, "c"), (OP, "<"),
             (WORD, "d"), (OP, ">"), (WORD, "e"), (OP, "!="), (WORD, "f")],
        )
        self.assertEqual(kinds("=<"), [(OP, "="), (OP, "<")])
        self.assertEqual(kinds("!=="), [(OP, "!="), (OP, "=")])

    def test_lone_bang_is_invalid(self):
        self.assertEqual(kinds("a !b"), [(WORD, "a"), (INVALID, "!"), (WORD, "b")])

    def test_comments(self):
        tokens = self.assertLossless("x#c\ny # otro { } \"\n# final")
        self.assertEqual([(t.kind, t.raw) for t in tokens], [(WORD, "x"), (WORD, "y"), (EOF, "")])
        self.assertEqual(tokens[1].trivia, "#c\n")
        self.assertEqual(tokens[2].trivia, ' # otro { } "\n# final')

    def test_strings(self):
        tokens = self.assertLossless('name = "a # b { } = c"')
        self.assertEqual(tokens[2].kind, STRING)
        self.assertEqual(tokens[2].raw, '"a # b { } = c"')
        multi = self.assertLossless('desc = "line one\nline two" next')
        self.assertEqual(multi[2].raw, '"line one\nline two"')
        self.assertEqual((multi[3].raw, multi[3].line, multi[3].column), ("next", 2, 11))
        self.assertEqual(kinds('""'), [(STRING, '""')])
        self.assertEqual(kinds('"a"b'), [(STRING, '"a"'), (WORD, "b")])

    def test_unterminated_string_runs_to_end(self):
        tokens = self.assertLossless('a = "abc\nb = c')
        self.assertEqual((tokens[2].kind, tokens[2].raw), (OPEN_STRING, '"abc\nb = c'))
        self.assertEqual(kinds('"'), [(OPEN_STRING, '"')])

    def test_words(self):
        text = "1861.1.1 -0.5 +3 Málaga 's-Hertogenbosch gfx/flags/x.tga a:b Ã© 100% ;"
        self.assertEqual([raw for _, raw in kinds(text)], text.split(" "))
        self.assertTrue(all(kind == WORD for kind, _ in kinds(text)))

    def test_empty_and_comment_only(self):
        self.assertEqual([(t.kind, t.trivia) for t in tokenize("")], [(EOF, "")])
        tokens = self.assertLossless("# solo\n# comentarios\n")
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0].trivia, "# solo\n# comentarios\n")

    def test_bom_and_control_characters_are_whitespace(self):
        tokens = self.assertLossless("﻿key = 1")
        self.assertEqual((tokens[0].raw, tokens[0].trivia, tokens[0].column), ("key", "﻿", 2))
        self.assertEqual(kinds("a\x00b\x7fc"), [(WORD, "a"), (WORD, "b"), (WORD, "c")])

    def test_positions(self):
        tokens = self.assertLossless("a = {\r\n\tb = c\r\n}\r\n")
        self.assertEqual(
            [(t.raw, t.line, t.column, t.offset) for t in tokens],
            [("a", 1, 1, 0), ("=", 1, 3, 2), ("{", 1, 5, 4), ("b", 2, 2, 8), ("=", 2, 4, 10),
             ("c", 2, 6, 12), ("}", 3, 1, 15), ("", 4, 1, 18)],
        )
        # Un CR suelto no es salto de línea (igual que en encoding.find_unencodable).
        lone_cr = tokenize("a\rb\nc")
        self.assertEqual([(t.line, t.column) for t in lone_cr[:3]], [(1, 1), (1, 3), (2, 1)])

    def test_lossless_on_odd_inputs(self):
        for text in ["", " ", "\n\n", "{", "}", "=", "!", '"', "#", "a=", "=a", "{ { a = b } { c = d } }",
                     'x = "unterminated', "a\r\r\nb", "\t\t", "#\r\n#", "a = { } = b", "\x00\x01\x02"]:
            self.assertLossless(text)


class TriviaHelperTests(unittest.TestCase):
    def test_clean_trivia(self):
        self.assertTrue(is_clean_trivia(" \t\n# comentario\r\n  "))
        self.assertTrue(is_clean_trivia(""))
        self.assertFalse(is_clean_trivia(" a =\n"))
        self.assertFalse(is_clean_trivia("}"))

    def test_trivia_comments_skip_discarded_strings(self):
        self.assertEqual(trivia_comments(' # uno\r\n\t"a # b"\t# dos  \n'), ["# uno", "# dos"])
        self.assertEqual(trivia_comments("\n\t"), [])

    def test_newline_split(self):
        self.assertEqual(newline_split(" # c\r\n\t# d\n\t"), (" # c", "\r\n\t# d\n\t"))
        self.assertEqual(newline_split(" # c\r\n\t# d\n\t", last=True), (" # c\r\n\t# d", "\n\t"))
        self.assertIsNone(newline_split("  "))

    def test_last_line_indent(self):
        self.assertEqual(last_line_indent("\n\n\t\t"), "\t\t")
        self.assertEqual(last_line_indent("# x\n"), "")
        self.assertIsNone(last_line_indent(" "))
        self.assertIsNone(last_line_indent("\n\t} "))


if __name__ == "__main__":
    unittest.main()
