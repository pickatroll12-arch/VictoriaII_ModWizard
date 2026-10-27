"""Recuento de líneas y columnas con saltos solo CR (\\r), CRLF (\\r\\n) y LF (\\n)."""

from __future__ import annotations

import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402, F401  (antes de vic2studio.ui: plataforma offscreen y ajustes aislados)

from vic2studio.core.clausewitz import parse  # noqa: E402
from vic2studio.core.encoding import (  # noqa: E402
    GAME_ENCODING,
    UnencodableTextError,
    _encoder,
    encode_text,
    find_unencodable,
    normalize_encoding,
)
from vic2studio.ui.pages.project_page import gather_facts  # noqa: E402


def _reference_find_unencodable(
    text: str, encoding: str = GAME_ENCODING
) -> list[tuple[int, int, int, str]]:
    """Implementación de referencia carácter a carácter con saltos \\r\\n, \\n y \\r suelto."""
    encode = _encoder(normalize_encoding(encoding))
    problems: list[tuple[int, int, int, str]] = []
    line, line_start = 1, 0
    size = len(text)
    for index, char in enumerate(text):
        if char == "\n":
            line, line_start = line + 1, index + 1
            continue
        if char == "\r":
            if index + 1 < size and text[index + 1] == "\n":
                continue
            line, line_start = line + 1, index + 1
            continue
        if char.isascii():
            continue
        try:
            encode(char)
        except UnicodeEncodeError:
            problems.append((index, line, index - line_start + 1, char))
    return problems


class CrLineCountTests(unittest.TestCase):
    def test_find_unencodable_line_breaks(self):
        self.assertEqual(find_unencodable("a = 1\nb = 2\nc = Ω"), [(16, 3, 5, "Ω")])
        self.assertEqual(find_unencodable("a = 1\r\nb = 2\r\nc = Ω"), [(18, 3, 5, "Ω")])
        self.assertEqual(find_unencodable("a = 1\rb = 2\rc = Ω"), [(16, 3, 5, "Ω")])
        self.assertEqual(
            find_unencodable("a = 1\rb = 2\r\nc = 3\nd = Ω\re = Δ"),
            [(23, 4, 5, "Ω"), (29, 5, 5, "Δ")],
        )
        self.assertEqual(find_unencodable("a = 1\r\rc = Ω"), [(11, 3, 5, "Ω")])
        self.assertEqual(find_unencodable("\r\rΩ"), [(2, 3, 1, "Ω")])
        self.assertEqual(find_unencodable("\r\r\nΩ"), [(3, 3, 1, "Ω")])
        # Los cinco bytes indefinidos de cp1252 siguen siendo codificables en GAME_ENCODING.
        self.assertEqual(find_unencodable("\x81\x8d\r\x8f\x90\x9dΩ"), [(6, 2, 4, "Ω")])

    def test_find_unencodable_matches_parser_line_numbers(self):
        text = "first = 1\rsecond = Ω\r\nthird = 3\nfourth = Δ\r\rsixth = Ψ\r"
        entries = {entry.key.text: entry for entry in parse(text).document.entries}
        problems = find_unencodable(text)
        self.assertEqual(len(problems), 3)
        self.assertEqual(
            [line for _, line, _, _ in problems],
            [entries["second"].line, entries["fourth"].line, entries["sixth"].line],
        )
        self.assertEqual(
            [(line, col, ch) for _, line, col, ch in problems],
            [(2, 10, "Ω"), (4, 10, "Δ"), (6, 9, "Ψ")],
        )

    def test_find_unencodable_matches_reference_on_random_texts(self):
        rng = random.Random(1836)
        alphabet = ("a", "b", "é", "\x81", "\x9d", "Ω", "中", "\r", "\n", "\r\n", "\r\r")
        for i in range(2000):
            sample = "".join(rng.choices(alphabet, k=rng.randint(0, 60)))
            for encoding in (GAME_ENCODING, "ascii", "latin-1"):
                self.assertEqual(
                    find_unencodable(sample, encoding),
                    _reference_find_unencodable(sample, encoding),
                    f"i={i}, encoding={encoding}, sample={sample!r}",
                )

    def test_encode_text_raises_unencodable_with_cr_position(self):
        with self.assertRaises(UnencodableTextError) as ctx:
            encode_text("a = 1\rb = 2\rc = Ω")
        self.assertEqual(ctx.exception.problems, [(16, 3, 5, "Ω")])
        self.assertIn("línea 3, columna 5", str(ctx.exception))

    def test_gather_facts_line_counts(self):
        folder = Path(tempfile.mkdtemp(prefix="vic2studio-cr-lines-"))
        self.addCleanup(shutil.rmtree, folder, True)
        cases = (
            ("cr_no_end.txt", b"a = 1\rb = 2\rc = 3", 3),
            ("cr_end.txt", b"a = 1\rb = 2\rc = 3\r", 3),
            ("crlf_end.txt", b"a = 1\r\nb = 2\r\nc = 3\r\n", 3),
            ("crlf_no_end.txt", b"a = 1\r\nb = 2\r\nc = 3", 3),
            ("lf_end.txt", b"a = 1\nb = 2\nc = 3\n", 3),
            ("lf_no_end.txt", b"a = 1\nb = 2\nc = 3", 3),
            ("empty.txt", b"", 0),
            ("double_cr.txt", b"a = 1\r\rb = 2", 3),
            ("only_double_cr.txt", b"\r\r", 2),
            ("mixed.txt", b"a = 1\rb = 2\r\nc = 3\nd = 4", 4),
        )
        for name, data, expected_lines in cases:
            with self.subTest(name=name):
                path = folder / name
                path.write_bytes(data)
                facts = gather_facts(path, folder)
                self.assertEqual(facts.lines, expected_lines)


if __name__ == "__main__":
    unittest.main()
