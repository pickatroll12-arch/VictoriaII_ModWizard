import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.clausewitz import lexer  # noqa: E402
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
    line_start,
    newline_split,
    position,
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
        # Un CR suelto es un salto de línea, como en los editores de texto (Notepad++, VS Code, Qt).
        lone_cr = tokenize("a\rb\nc\r\r\nd")
        self.assertEqual([(t.line, t.column) for t in lone_cr], [(1, 1), (2, 1), (3, 1), (5, 1), (5, 2)])
        self.assertEqual([(t.line, t.column) for t in tokenize('"x\ry" z')], [(1, 1), (2, 4), (2, 5)])

    def test_line_numbers_match_str_splitlines(self):
        text = "a = 1\r\n\rb = {\r\tc = 2 # x\r\n}\n\nd = \"e\rf\"\rg"
        lines = text.splitlines()
        for token in tokenize(text)[:-1]:
            self.assertEqual(lines[token.line - 1][token.column - 1:].split()[0][:1], token.raw[:1], token)
        self.assertEqual(position(text, text.index("g")), (len(lines), 1))
        self.assertEqual(position(text, text.index("c")), (4, 2))
        self.assertEqual(position("a\r\nb", 3), (2, 1))

    def test_line_start_looks_back_only_to_the_previous_line(self):
        cases = [("a\rb", 3), ("a\r\nb", 4), ("a\nb\rc", 5), ("abc", 2), ("a\n\rb", 4)]
        self.assertEqual([line_start(text, offset) for text, offset in cases], [2, 3, 4, 0, 3])
        # Buscar el CR suelto hasta el principio del archivo en cada llamada hacía cuadrático el análisis
        # de un bloque grande sin cerrar (archivo de 20 MB: de 7 a 38 s).
        text = "a" * 20_000_000 + "\nbc"
        started = time.perf_counter()
        for _ in range(1000):
            self.assertEqual(line_start(text, len(text)), len(text) - 2)
        self.assertLess(time.perf_counter() - started, 0.1)

    def test_comments_end_at_any_line_break(self):
        # Archivos solo con CR (11 del juego base, p. ej. map/region_sea.txt): el comentario no se traga el resto.
        tokens = self.assertLossless("a = 1 # c\rb = 2\r# d\r\nc = 3")
        self.assertEqual([t.raw for t in tokens], ["a", "=", "1", "b", "=", "2", "c", "=", "3", ""])
        self.assertEqual((tokens[3].trivia, tokens[3].line), (" # c\r", 2))
        self.assertEqual(trivia_comments(" # c\r# d\r\n\t"), ["# c", "# d"])

    def test_tokens_do_not_depend_on_where_the_text_is_cut(self):
        # El texto se analiza por tandas: palabras, operadores, cadenas y comentarios cortados por la mitad.
        text = ('a = "una cadena\nlarga" # comentario\r\nfecha=1861.1.1 b<=c x!=y !z\r' * 3
                + 'clave_muy_larga = { 1 2 } "sin cerrar\n final')

        def scan():
            return [(t.kind, t.raw, t.trivia, t.offset, t.line, t.column) for t in self.assertLossless(text)]

        expected = scan()
        self.assertEqual(expected[-2][0], OPEN_STRING)
        for chunk in (1, 2, 3, 5, 8, 13):
            with mock.patch.object(lexer, "_CHUNK", chunk):
                self.assertEqual(scan(), expected, chunk)

    def test_lossless_on_odd_inputs(self):
        for text in ["", " ", "\n\n", "{", "}", "=", "!", '"', "#", "a=", "=a", "{ { a = b } { c = d } }",
                     'x = "unterminated', "a\r\r\nb", "\t\t", "#\r\n#", "a = { } = b", "\x00\x01\x02"]:
            self.assertLossless(text)


class TriviaHelperTests(unittest.TestCase):
    def test_clean_trivia(self):
        self.assertTrue(is_clean_trivia(" \t\n# comentario\r\n  "))
        self.assertTrue(is_clean_trivia(""))
        self.assertTrue(is_clean_trivia("# a\r# b"))
        self.assertFalse(is_clean_trivia(" a =\n"))
        self.assertFalse(is_clean_trivia("}"))
        self.assertFalse(is_clean_trivia("# a\rb"))

    def test_clean_trivia_has_no_catastrophic_backtracking(self):
        # Antes: fullmatch con "(?:[ws]+|#...)*" probaba 2^n particiones de los blancos (cuelgue al editar);
        # estos tamaños tardaban de 5 a 25 s cada uno. Ahora el coste es lineal.
        cases = [" " * 26 + "a", "        # add_core = X0\r\n        # add_core = X1\r\n        controller =",
                 " " * 50000 + "a", ("\t# comentario\r\n" * 5000) + "}"]
        started = time.perf_counter()
        for trivia in cases:
            self.assertFalse(is_clean_trivia(trivia))
            self.assertTrue(is_clean_trivia(trivia[: trivia.rfind("\n") + 1]))
            self.assertLess(time.perf_counter() - started, 0.5, trivia[:30])

    def test_trivia_comments_skip_discarded_strings(self):
        self.assertEqual(trivia_comments(' # uno\r\n\t"a # b"\t# dos  \n'), ["# uno", "# dos"])
        self.assertEqual(trivia_comments("\n\t"), [])

    def test_newline_split(self):
        self.assertEqual(newline_split(" # c\r\n\t# d\n\t"), (" # c", "\r\n\t# d\n\t"))
        self.assertEqual(newline_split(" # c\r\n\t# d\n\t", last=True), (" # c\r\n\t# d", "\n\t"))
        self.assertEqual(newline_split(" # c\r\t# d\r\n\t", last=True), (" # c\r\t# d", "\r\n\t"))
        self.assertEqual(newline_split(" # c\r\t"), (" # c", "\r\t"))
        self.assertEqual(newline_split("\r", last=True), ("", "\r"))
        self.assertIsNone(newline_split("  "))
        self.assertIsNone(newline_split("  ", last=True))

    def test_last_line_indent(self):
        self.assertEqual(last_line_indent("\n\n\t\t"), "\t\t")
        self.assertEqual(last_line_indent("# x\n"), "")
        self.assertEqual(last_line_indent("# x\r  "), "  ")
        self.assertIsNone(last_line_indent(" "))
        self.assertIsNone(last_line_indent("\n\t} "))


if __name__ == "__main__":
    unittest.main()
