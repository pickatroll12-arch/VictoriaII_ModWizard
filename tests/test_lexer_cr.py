"""Criterio 2 de la iteración 2: saltos de línea solo CR (H2), con comentario."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.clausewitz import parse, to_source  # noqa: E402
from vic2studio.core.encoding import detect_newline  # noqa: E402

CR_TEXT = "a = 1 # c\rb = 2\r"


class CrOnlyTests(unittest.TestCase):
    def test_acceptance_criterion_2(self):
        """``parse("a = 1 # c\\rb = 2\\r")`` da 2 entradas en las líneas 1 y 2; ``detect_newline`` da ``"\\r"``."""
        result = parse(CR_TEXT)
        entries = result.document.entries
        self.assertEqual([e.key.text for e in entries], ["a", "b"])
        self.assertEqual([e.value.text for e in entries], ["1", "2"])
        self.assertEqual([e.line for e in entries], [1, 2])
        self.assertEqual(detect_newline(CR_TEXT), "\r")
        self.assertEqual(result.document.newline, "\r")
        self.assertEqual(entries[0].line_comment, "# c")
        self.assertEqual(result.diagnostics, [])

    def test_round_trip_and_edit_keep_cr(self):
        """Releer sin cambios da el mismo texto, y una entrada nueva usa el CR del archivo."""
        result = parse(CR_TEXT)
        self.assertEqual(to_source(result.document), CR_TEXT)
        result.document.append("c", "3")
        text = to_source(result.document)
        self.assertNotIn("\n", text)
        reread = parse(text)
        self.assertEqual([e.key.text for e in reread.document.entries], ["a", "b", "c"])
        self.assertEqual([e.line for e in reread.document.entries], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
