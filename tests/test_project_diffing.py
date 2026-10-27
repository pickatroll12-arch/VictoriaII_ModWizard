"""Diferencias para «Cambios pendientes» (``core.project.diffing``) y el almacén LRU (``documents``)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.project.diffing import (  # noqa: E402
    MAX_DIFF_LINES,
    changed_lines,
    counted_diff,
    split_truncation,
    unified_diff,
)
from vic2studio.core.project.documents import DocumentStore  # noqa: E402
from vic2studio.core.project.model import DocHandle  # noqa: E402
from vic2studio.core.vfs import DocKind, VPath  # noqa: E402

REL = VPath.of("common/cb_types.txt")


class DiffTests(unittest.TestCase):
    def test_one_line_change(self):
        before = b"a = {\r\n\tmonths = 12\r\n\tx = 1\r\n}\r\n"
        after = b"a = {\r\n\tmonths = 24\r\n\tx = 1\r\n}\r\n"
        diff = unified_diff(REL, before, after)
        self.assertTrue(diff.startswith("--- a/common/cb_types.txt\n+++ b/common/cb_types.txt\n@@"))
        self.assertIn("-\tmonths = 12", diff)
        self.assertIn("+\tmonths = 24", diff)
        self.assertNotIn("\r", diff)
        self.assertEqual(changed_lines(before, after), (1, 1))
        self.assertEqual(changed_lines(before, before), (0, 0))
        self.assertEqual(unified_diff(REL, before, before), "")

    def test_create_delete_cr_only_and_control_characters(self):
        self.assertEqual(changed_lines(None, b"a = 1\r\nb = 2\r\n"), (2, 0))
        self.assertEqual(changed_lines(b"a = 1\r\nb = 2", None), (0, 2))
        self.assertIn("+a = 1", unified_diff(REL, None, b"a = 1\r\n"))
        self.assertEqual(changed_lines(b"a = 1\rb = 2\r", b"a = 1\rb = 3\r"), (1, 1), "saltos solo CR")
        self.assertEqual(changed_lines(b"a\x0cb\n", b"a\x0cc\n"), (1, 1), "\\x0c no parte líneas")

    def test_encoding_and_binary(self):
        before, after = "n = España\n".encode("cp1252"), "n = Francia\n".encode("cp1252")
        self.assertIn("-n = España", unified_diff(REL, before, after))
        utf8 = unified_diff(REL, "n = é\n".encode("utf-8"), b"n = e\n", encoding="utf-8")
        self.assertIn("-n = é", utf8)
        binary = unified_diff(VPath.of("gfx/a.dds"), b"\0\1\2", b"\0\1\3")
        self.assertEqual(binary, "Binary files a/gfx/a.dds and b/gfx/a.dds differ (3 -> 3 bytes)")
        self.assertEqual(unified_diff(VPath.of("gfx/a.dds"), b"\0", b"\0"), "")

    def test_counts_are_of_the_whole_diff_not_of_the_shown_part(self):
        """Revisión it3: «Recuperar las filas» en VSM decía +134 −134 (las del diff recortado) y cambia 3 438."""
        before = b"".join(b"row %d;old\r\n" % i for i in range(2000))
        after = b"".join(b"row %d;%s\r\n" % (i, b"new" if i % 2 else b"old") for i in range(2000))
        diff, lines = counted_diff(VPath.of("localisation/text.csv"), before, after)
        self.assertEqual(lines, (1000, 1000))
        body, hidden = split_truncation(diff)
        self.assertEqual(len(body.splitlines()), MAX_DIFF_LINES)
        self.assertGreater(hidden, 0)
        self.assertEqual(split_truncation("@@ -1 +1 @@\n-a\n+b"), ("@@ -1 +1 @@\n-a\n+b", 0))
        self.assertEqual(counted_diff(VPath.of("x.dds"), b"\0\0", None)[1], None, "un binario no tiene líneas")
        content = b"a\r\n++b\r\n--c\r\n"
        self.assertEqual(counted_diff(VPath.of("x.txt"), None, content)[1], (3, 0), "«++» y «--» del texto cuentan")

    def test_long_diffs_are_summarised(self):
        before = b"".join(b"line %d\n" % i for i in range(MAX_DIFF_LINES))
        diff = unified_diff(REL, before, None)
        lines = diff.split("\n")
        self.assertEqual(len(lines), MAX_DIFF_LINES + 1)
        self.assertRegex(lines[-1], r"^\.\.\. \(\+\d+ lines\)$")


class DocumentStoreTests(unittest.TestCase):
    def handle(self, rel, dirty=False):
        handle = DocHandle(VPath.of(rel), DocKind.CLAUSEWITZ, None, version=1, saved_version=0 if dirty else 1)
        return handle

    def test_lru(self):
        store = DocumentStore(lru_bytes=12)
        a, b, c, d = (self.handle(r) for r in ("a.txt", "b.txt", "c.txt", "d.txt"))
        dirty = self.handle("e.txt", dirty=True)
        for handle in (a, b, dirty, c):
            store.add(handle, 4)
        self.assertEqual(store.total_bytes, 16)
        self.assertIs(store.get("A.TXT"), a)                 # a pasa a ser el más reciente
        self.assertEqual(store.evict(pinned=set()), [VPath.of("b.txt")], "el menos usado, hasta bajar del límite")
        self.assertEqual(store.total_bytes, 12)
        store.add(d, 4)
        self.assertEqual(store.evict(pinned={"C.TXT"}), [VPath.of("a.txt")], "se salta el sucio y el fijado")
        self.assertEqual({str(h.rel) for h in store}, {"e.txt", "c.txt", "d.txt"})
        store.resize("d.txt", 1)
        self.assertEqual(store.total_bytes, 9)
        self.assertEqual(store.evict(pinned=set()), [], "bajo el límite no se expulsa nada")
        store.discard("D.txt")
        self.assertEqual(len(store), 2)
        store.clear()
        self.assertEqual((len(store), store.total_bytes), (0, 0))


if __name__ == "__main__":
    unittest.main()
