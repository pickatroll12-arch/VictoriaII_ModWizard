"""``textsplice``: recomponer lo tecleado sin cambiar las líneas que no se tocaron (I3)."""

import random
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.textsplice import normalize_newlines, splice_text  # noqa: E402


def view(text: str) -> str:
    return normalize_newlines(text)


def splice(original: str, new_view: str, newline: str = "\n") -> str:
    return splice_text(original, view(original), new_view, newline)


class NormalizeTests(unittest.TestCase):
    def test_normalizes_crlf_and_lone_cr(self):
        self.assertEqual(normalize_newlines("a\r\nb\rc\nd"), "a\nb\nc\nd")

    def test_does_not_touch_other_separators(self):
        text = "a\x0cb\x1cc\x85d\u2028e"
        self.assertEqual(normalize_newlines(text), text)


class IdentityTests(unittest.TestCase):
    """Sin cambios, el texto es exactamente el original, incluido su salto final."""

    def test_identity(self):
        cases = (
            "",
            "sin salto final",
            "una línea\r\n",
            "una línea\n",
            "dos\r\nlíneas\r\n",
            "dos\r\nlíneas",
            "mezcla\r\nde\nsaltos\rfinal",
            "solo\rsaltos\r",
            "varias\r\nlíneas\ncon\rmezcla\n",
        )
        for original in cases:
            with self.subTest(original=original):
                self.assertEqual(splice_text(original, view(original), view(original), "\r\n"), original)
                self.assertEqual(splice_text(original, view(original), view(original), "\n"), original)


class ChangeTests(unittest.TestCase):
    def test_changing_one_line_in_crlf_only_changes_that_line(self):
        original = "capital = 1\r\nprimary_culture = alander\r\ngovernment = monarchy\r\n"
        result = splice(original, "capital = 2\nprimary_culture = alander\ngovernment = monarchy\n", "\r\n")
        self.assertEqual(result, "capital = 2\r\nprimary_culture = alander\r\ngovernment = monarchy\r\n")
        self.assertEqual(result.replace("capital = 2", "capital = 1"), original)

    def test_append_line_at_the_end(self):
        self.assertEqual(splice("a\r\nb", "a\nb\nc", "\r\n"), "a\r\nb\r\nc")

    def test_append_with_trailing_newline(self):
        self.assertEqual(splice("a\r\nb", "a\nb\nc\n", "\r\n"), "a\r\nb\r\nc\r\n")

    def test_delete_lines(self):
        self.assertEqual(splice("a\r\nb\r\nc\r\n", "a\nc\n", "\r\n"), "a\r\nc\r\n")

    def test_insert_in_the_middle(self):
        self.assertEqual(splice("a\r\nc", "a\nb\nc", "\r\n"), "a\r\nb\r\nc")

    def test_remove_the_final_newline(self):
        self.assertEqual(splice("a\r\nb\r\n", "a\nb", "\r\n"), "a\r\nb")

    def test_add_a_final_newline(self):
        self.assertEqual(splice("a\r\nb", "a\nb\n", "\r\n"), "a\r\nb\r\n")

    def test_insert_into_an_empty_file(self):
        self.assertEqual(splice("", "a\nb", "\r\n"), "a\r\nb")

    def test_mixed_endings_keep_the_untouched_lines(self):
        original = "uno\r\ndos\ntres\r cuatro"
        result = splice(original, "uno\nDOS\ntres\rcuatro", "\n")
        self.assertEqual(result, "uno\r\nDOS\ntres\rcuatro")
        self.assertTrue(result.startswith("uno\r\n"), "la primera línea conserva CRLF")
        self.assertIn("tres\r", result, "la tercera conserva el CR suelto")

    def test_mixed_endings_append_uses_the_requested_newline(self):
        original = "uno\r\ndos\n"
        result = splice(original, "uno\ndos\nnuevo", "\n")
        self.assertEqual(result, "uno\r\ndos\nnuevo")

    def test_a_changed_line_uses_the_requested_newline(self):
        original = "uno\r\ndos\n"
        result = splice(original, "uno\nDOS\n", "\r\n")
        self.assertEqual(result, "uno\r\nDOS\r\n")


class CorrectionTests(unittest.TestCase):
    """B1/B2 de la revisión: prefijo/sufijo, línea tras CR suelto y coste lineal en líneas repetidas."""

    def test_a_lone_cr_before_a_new_empty_line_does_not_lose_the_line(self):
        result = splice_text("a\rb\nc\n", "a\nb\nc\n", "a\n\nb\nc\n", "\n")
        self.assertEqual(normalize_newlines(result), "a\n\nb\nc\n")

    def test_random_edits_keep_the_view_and_do_not_touch_an_unchanged_text(self):
        rng = random.Random(20261028)
        contents = ("a", "b", "}", "", "x = 1")
        endings = ("\r\n", "\n", "\r")
        for _ in range(20_000):
            count = rng.randrange(10)
            pieces = []
            for index in range(count):
                content = rng.choice(contents)
                if index == count - 1 and rng.random() < 0.5:
                    pieces.append(content)
                else:
                    pieces.append(content + rng.choice(endings))
            original = "".join(pieces)
            old_view = normalize_newlines(original)
            new_lines = old_view.split("\n")
            for _ in range(rng.randrange(5)):
                operation = rng.choice(("insert", "delete", "replace"))
                if operation == "insert":
                    new_lines.insert(rng.randrange(len(new_lines) + 1), rng.choice(contents))
                elif operation == "delete" and len(new_lines) > 1:
                    new_lines.pop(rng.randrange(len(new_lines)))
                else:
                    new_lines[rng.randrange(len(new_lines))] = rng.choice(contents)
            new_view = "\n".join(new_lines)
            newline = rng.choice(endings)
            result = splice_text(original, old_view, new_view, newline)
            self.assertEqual(normalize_newlines(result), new_view, (original, new_view, newline))
            if new_view == old_view:
                self.assertEqual(result, original)

    def test_many_repeated_lines_are_cheap_with_one_change_in_the_middle(self):
        lines = ["}"] * 150_000
        original = "".join(line + "\r\n" for line in lines)
        old_view = "\n".join(lines) + "\n"
        changed = list(lines)
        changed[75_000] = "cambio = 1"
        new_view = "\n".join(changed) + "\n"
        started = time.perf_counter()
        result = splice_text(original, old_view, new_view, "\r\n")
        elapsed = time.perf_counter() - started
        self.assertEqual(normalize_newlines(result), new_view)
        self.assertLess(elapsed, 1.0, f"{elapsed:.3f} s con 150 000 líneas")


class PreconditionTests(unittest.TestCase):
    def test_old_view_must_be_the_normalized_original(self):
        with self.assertRaises(ValueError):
            splice_text("a\r\nb", "a\r\nb", "a\nB", "\n")


if __name__ == "__main__":
    unittest.main()
