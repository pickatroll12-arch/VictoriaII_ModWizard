"""``UndoStack`` (wizard §6.3): instantáneas zlib, fusión por ``merge_key`` y límites."""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.project.model import Snapshot, UndoStep  # noqa: E402
from vic2studio.core.project.undo import MERGE_SECONDS, UndoStack, compress, decompress, step_size  # noqa: E402
from vic2studio.core.vfs import VPath  # noqa: E402


def step(label, rel="a.txt", before=b"1", after=b"2", merge_key=None, versions=(1, 2)):
    return UndoStep(label, {}, [Snapshot(VPath.of(rel), compress(before), compress(after),
                                         before_version=versions[0], after_version=versions[1])],
                    merge_key=merge_key)


class UndoStackTests(unittest.TestCase):
    def test_compress(self):
        self.assertIsNone(compress(None))
        self.assertIsNone(decompress(None))
        data = b"months = 12\r\n" * 1000
        self.assertLess(len(compress(data)), len(data) // 10)
        self.assertEqual(decompress(compress(data)), data)

    def test_push_undo_redo(self):
        stack = UndoStack()
        self.assertFalse(stack.can_undo())
        self.assertIsNone(stack.undo())
        first, second = step("one"), step("two")
        stack.push(first, now=0)
        stack.push(second, now=10)
        self.assertEqual(stack.labels(), [("two", {}), ("one", {})])
        self.assertIs(stack.undo(), second)
        self.assertTrue(stack.can_redo())
        self.assertEqual(stack.redo_labels(), [("two", {})])
        self.assertIs(stack.redo(), second)
        self.assertIsNone(stack.redo())
        stack.undo()
        stack.push(step("three"), now=20)
        self.assertFalse(stack.can_redo(), "apilar vacía rehacer")
        self.assertEqual([label for label, _ in stack.labels()], ["three", "one"])

    def test_merge_key_within_merge_seconds(self):
        stack = UndoStack()
        stack.push(step("type", before=b"a", after=b"ab", merge_key="field", versions=(1, 2)), now=0)
        stack.push(step("type", before=b"ab", after=b"abc", merge_key="field", versions=(2, 3)), now=0.5)
        stack.push(step("type", rel="b.txt", before=b"x", after=b"y", merge_key="field", versions=(7, 8)), now=0.9)
        self.assertEqual(len(stack.labels()), 1)
        merged = stack.undo()
        by_rel = {str(s.rel): s for s in merged.snapshots}
        self.assertEqual(decompress(by_rel["a.txt"].before), b"a")
        self.assertEqual(decompress(by_rel["a.txt"].after), b"abc")
        self.assertEqual((by_rel["a.txt"].before_version, by_rel["a.txt"].after_version), (1, 3))
        self.assertIn("b.txt", by_rel)

    def test_no_merge_after_the_window_with_other_keys_or_after_undo(self):
        stack = UndoStack()
        stack.push(step("a", merge_key="k"), now=0)
        stack.push(step("b", merge_key="k"), now=MERGE_SECONDS + 0.01)
        stack.push(step("c", merge_key="other"), now=MERGE_SECONDS + 0.02)
        stack.push(step("d"), now=MERGE_SECONDS + 0.03)
        self.assertEqual(len(stack.labels()), 4)
        stack = UndoStack()
        stack.push(step("a", merge_key="k"), now=0)
        stack.push(step("b", merge_key="k"), now=0.1)
        stack.undo()
        stack.push(step("c", merge_key="x"), now=0.2)
        stack.push(step("d", merge_key="x"), now=0.25)
        stack.undo()
        stack.redo()
        stack.push(step("e", merge_key="x"), now=0.3)
        self.assertEqual(len(stack.labels()), 2, "tras deshacer o rehacer no se funde con el paso anterior")

    def test_limits_drop_the_oldest(self):
        stack = UndoStack(limit=3)
        for number in range(5):
            stack.push(step(f"s{number}"), now=number * 10)
        self.assertEqual([label for label, _ in stack.labels()], ["s4", "s3", "s2"])
        rng = random.Random(5)
        noise = [bytes(rng.getrandbits(8) for _ in range(1000)) for _ in range(4)]   # no se comprime
        size = step_size(step("x", before=noise[0], after=noise[0]))
        stack = UndoStack(max_bytes=size * 2 + 64)
        for number in range(4):
            stack.push(step(f"s{number}", before=noise[number], after=noise[number]), now=number * 10)
        self.assertEqual([label for label, _ in stack.labels()], ["s3", "s2"])
        self.assertLessEqual(stack.total_bytes, stack.max_bytes)
        big = noise[0]
        lone = UndoStack(max_bytes=1)
        lone.push(step("huge", before=big, after=big))
        self.assertEqual(len(lone.labels()), 1, "el último paso se conserva aunque pase del límite")

    def test_shared_snapshot_bytes_count_once(self):
        """Una lápida tiene el mismo objeto antes y después: cuenta una vez (revisión de la iteración 3)."""
        rng = random.Random(7)
        blob = compress(bytes(rng.getrandbits(8) for _ in range(4000)))
        tomb = UndoStep("trash", {}, [Snapshot(VPath.of("a.dds"), blob, blob, after_deleted=True,
                                               before_version=1, after_version=2)])
        self.assertEqual(step_size(tomb), len(blob))
        stack = UndoStack(max_bytes=len(blob) + 200)
        stack.push(tomb, now=0)
        stack.push(step("edit"), now=10)
        self.assertEqual([label for label, _ in stack.labels()], ["edit", "trash"], "la papelera sigue deshaciéndose")

    def test_referenced_and_clear(self):
        stack = UndoStack()
        stack.push(step("a", rel="Common/A.txt"), now=0)
        stack.push(step("b", rel="b.txt"), now=10)
        stack.undo()
        self.assertEqual(stack.referenced(), {"COMMON/A.TXT", "B.TXT"}, "también lo que se puede rehacer")
        stack.clear()
        self.assertEqual(stack.referenced(), set())
        self.assertEqual(stack.total_bytes, 0)


if __name__ == "__main__":
    unittest.main()
