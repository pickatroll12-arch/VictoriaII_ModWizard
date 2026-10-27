"""I1 y criterio 5: ``WriteGuard`` solo admite el subárbol real del mod y su descriptor (wizard §5.1, H24)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import build_layers  # noqa: E402
from vic2studio.core.project import journal  # noqa: E402
from vic2studio.core.project.model import SAVE_OUTSIDE_MOD, PlannedWrite, WriteAction  # noqa: E402
from vic2studio.core.vfs import VPath, WriteGuard, WriteOutsideModError  # noqa: E402

GAME = {"common/cb_types.txt": "a = 1\r\n", "events/e.txt": "x = 1\r\n"}
MOD = {"common/countries.txt": "AAA = \"countries/A.txt\"\r\n"}


def _can_symlink(folder: Path) -> bool:
    try:
        (folder / ".probe").symlink_to(folder)
    except (OSError, NotImplementedError):
        return False
    (folder / ".probe").unlink()
    return True


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.layers = build_layers(game=GAME, mod=MOD, mod_name="VSM")
        self.addCleanup(self.layers.cleanup)
        self.game = self.layers.game_root
        self.mod = self.layers.mod_root
        self.descriptor = self.layers.descriptor
        self.guard = WriteGuard(self.mod, extra_files=[self.descriptor])

    def assertRejected(self, path):
        with self.assertRaises(WriteOutsideModError, msg=str(path)):
            self.guard.check(path)
        self.assertFalse(self.guard.allows(path))

    def assertAllowed(self, path):
        self.assertEqual(self.guard.check(path), Path(os.path.realpath(path)))
        self.assertTrue(self.guard.allows(path))

    def test_acceptance_criterion_5(self):
        """Rechaza <juego>/common/x.txt, rutas con '..' y enlaces que salen; admite <juego>/mod/VSM/** y VSM.mod."""
        self.assertEqual(self.mod, self.game / "mod" / "VSM")
        self.assertEqual(self.descriptor, self.game / "mod" / "VSM.mod")
        self.assertRejected(self.game / "common" / "x.txt")
        self.assertRejected(self.game / "common" / "cb_types.txt")
        self.assertRejected(self.mod / ".." / ".." / "common" / "cb_types.txt")
        self.assertAllowed(self.mod / "common" / "countries.txt")
        self.assertAllowed(self.mod / "history" / "provinces" / "nueva" / "1 - Nueva.txt")
        self.assertAllowed(self.mod / ".vic2studio" / "journal" / "x.json")
        self.assertAllowed(self.mod)
        self.assertAllowed(self.descriptor)

    def test_mod_inside_game_does_not_open_the_rest_of_the_game(self):
        for path in (self.game / "v2game.exe", self.game / "mod" / "Other" / "x.txt", self.game / "mod" / "Other.mod",
                     self.game / "mod" / "VSM2" / "x.txt", self.game / "mod" / "VSMx.mod", self.game / "mod",
                     self.game, self.game.parent / "elsewhere.txt"):
            with self.subTest(path=path):
                self.assertRejected(path)

    def test_parent_components_are_always_rejected(self):
        self.assertRejected(self.mod / "common" / ".." / "events" / "e.txt")   # aunque quede dentro
        self.assertRejected(str(self.mod) + "/common/..\\..\\..\\common\\cb_types.txt")
        self.assertRejected("")
        self.assertRejected("a\0b")

    def test_backslashes_are_not_a_way_out(self):
        # En Linux «\» es un carácter más: la ruta sigue dentro del mod y se admite tal cual.
        self.assertAllowed(str(self.mod) + "/common\\x.txt")
        self.assertRejected(str(self.game) + "\\..\\mod\\VSM\\x.txt" if os.name != "nt" else
                            str(self.game / "common" / "x.txt"))

    def test_descriptor_companions(self):
        self.assertAllowed(self.descriptor.with_name("VSM.mod.bak"))
        self.assertAllowed(self.descriptor.with_name(".VSM.mod.20261026T000000-abcdef.tmp"))
        self.assertRejected(self.descriptor.with_name(".Other.mod.x.tmp"))
        self.assertRejected(self.descriptor.with_name("VSM.mod.old"))
        self.assertRejected(self.game / "VSM.mod")

    def test_symlinks_that_leave_the_mod(self):
        if not _can_symlink(self.mod):
            self.skipTest("este sistema no crea enlaces simbólicos")
        (self.mod / "linked_common").symlink_to(self.game / "common", target_is_directory=True)
        self.assertRejected(self.mod / "linked_common" / "cb_types.txt")
        self.assertRejected(self.mod / "linked_common" / "new.txt")
        (self.mod / "events").mkdir()
        (self.mod / "events" / "e.txt").symlink_to(self.game / "events" / "e.txt")
        self.assertRejected(self.mod / "events" / "e.txt")
        (self.mod / "events" / "dangling.txt").symlink_to(self.game / "events" / "nope.txt")
        self.assertRejected(self.mod / "events" / "dangling.txt")
        # Un enlace que se queda dentro del mod sí vale.
        (self.mod / "alias").symlink_to(self.mod / "common", target_is_directory=True)
        self.assertAllowed(self.mod / "alias" / "countries.txt")
        self.assertEqual(self.guard.check(self.mod / "alias" / "countries.txt"),
                         Path(os.path.realpath(self.mod / "common" / "countries.txt")))

    def test_mod_root_through_a_symlink(self):
        if not _can_symlink(self.mod):
            self.skipTest("este sistema no crea enlaces simbólicos")
        link = self.game / "mod" / "VSM_link"
        link.symlink_to(self.mod, target_is_directory=True)
        guard = WriteGuard(link)
        self.assertTrue(guard.allows(link / "common" / "x.txt"))
        self.assertTrue(guard.allows(self.mod / "common" / "x.txt"), "es la misma carpeta real")
        self.assertFalse(guard.allows(self.game / "common" / "x.txt"))

    def test_letter_case(self):
        other = self.game / "mod" / "vsm"
        try:
            same = os.path.samefile(self.mod, other)
        except OSError:
            same = False
        if same:
            self.skipTest("sistema de archivos sin mayúsculas: es la misma carpeta")
        # En un sistema que distingue mayúsculas «vsm» es otra carpeta (y Windows ya compara con normcase).
        self.assertRejected(other / "x.txt")
        self.assertRejected(self.game / "mod" / "vsm.mod")

    def test_extra_roots_for_a_read_only_mod(self):
        with tempfile.TemporaryDirectory() as tmp:
            detached = Path(tmp) / "projects" / "abc"
            guard = WriteGuard(self.mod, extra_roots=[detached])
            self.assertTrue(guard.allows(detached / "journal" / "x.json"))
            self.assertFalse(guard.allows(Path(tmp) / "projects" / "other" / "x.json"))
            self.assertFalse(guard.allows(self.descriptor), "sin extra_files el descriptor no se admite")

    def test_error_messages(self):
        with self.assertRaises(WriteOutsideModError) as ctx:
            self.guard.check(self.game / "common" / "x.txt")
        error = ctx.exception
        self.assertIsInstance(error, PermissionError)
        self.assertIn("x.txt", error.message("es"))
        self.assertIn("outside the mod", error.message("en"))
        self.assertEqual(str(error), error.message("es"))

    def test_journal_refuses_to_write_outside(self):
        """El diario comprueba el guard antes de escribir: un destino del juego no toca el disco."""
        target = self.game / "common" / "cb_types.txt"
        before = self.layers.tree(self.game)
        transaction = journal.SaveTransaction(self.guard, self.mod / ".vic2studio" / "journal", label="x")
        transaction.add(PlannedWrite(VPath.of("common/cb_types.txt"), target, WriteAction.MODIFY, b"b = 2\r\n", None))
        problems = transaction.prepare()
        self.assertEqual([p.code for p in problems if p.blocking], [SAVE_OUTSIDE_MOD])
        with self.assertRaises(WriteOutsideModError):
            transaction.commit()
        self.assertEqual(self.layers.tree(self.game), before)
        self.assertFalse((self.mod / ".vic2studio").exists())


if __name__ == "__main__":
    unittest.main()
