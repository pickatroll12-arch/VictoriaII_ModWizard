import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.csvloc import KeyOverride, LocalisationDB, parse_csv  # noqa: E402


def row(key: str, en: str, es: str = "") -> str:
    return f"{key};{en};;;;{es};;;;;;;;;x\r\n"


class LocalisationDBTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.mod = base / "mod" / "localisation"
        self.vanilla = base / "vanilla" / "localisation"
        self.mod.mkdir(parents=True)
        self.vanilla.mkdir(parents=True)
        self._write(self.mod, "00_mod.csv", row("SHARED", "from mod", "del mod") + row("MOD_ONLY", "mod"))
        self._write(self.mod, "Text.csv", row("TEXT_KEY", "mod text"))
        self._write(self.mod, "notes.txt", row("IGNORED", "txt"))
        self._write(self.mod, "text.csv.bak", row("IGNORED", "bak"))
        (self.mod / "sub").mkdir()
        self._write(self.mod / "sub", "aaa.csv", row("IGNORED", "sub"))
        self._write(self.vanilla, "text.csv", row("TEXT_KEY", "vanilla text") + row("VANILLA_TEXT", "lost"))
        self._write(self.vanilla, "a.csv", row("SHARED", "from a") + row("A_KEY", "a", "a es")
                    + row("A_KEY", "a duplicate"))
        self._write(self.vanilla, "Z.CSV", row("Z_KEY", "z") + row("SHARED", "from z"))
        self._write(self.vanilla, "b.csv", row("EMPTY_ES", "only english"))

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _write(directory: Path, name: str, text: str) -> None:
        (directory / name).write_bytes(text.encode("cp1252"))

    def test_load_order(self):
        db = LocalisationDB.from_dirs([self.mod, self.vanilla])
        self.assertEqual([f.path.name for f in db.files], ["00_mod.csv", "a.csv", "b.csv", "Text.csv", "Z.CSV"])
        self.assertEqual(db.files[3].path.parent, self.mod)
        self.assertEqual(db.replaced_files, [(self.vanilla / "text.csv", self.mod / "Text.csv")])

    def test_first_definition_wins(self):
        db = LocalisationDB.from_dirs([self.mod, self.vanilla])
        self.assertEqual(db.lookup("SHARED"), "from mod")
        self.assertEqual(db.lookup("SHARED", "es"), "del mod")
        self.assertEqual(db.lookup("SHARED", "Spanish"), "del mod")
        self.assertEqual(db.lookup("A_KEY"), "a")
        self.assertEqual(db.lookup("TEXT_KEY"), "mod text")
        self.assertIsNone(db.lookup("VANILLA_TEXT"))
        self.assertIsNone(db.lookup("IGNORED"))
        self.assertIsNone(db.lookup("missing"))
        self.assertEqual(db.source_of("SHARED"), (self.mod / "00_mod.csv", 1))
        self.assertEqual(db.source_of("Z_KEY"), (self.vanilla / "Z.CSV", 1))
        self.assertIsNone(db.source_of("missing"))
        self.assertEqual(db.file_of("A_KEY").path.name, "a.csv")
        self.assertEqual(db.entry("A_KEY").get("es"), "a es")

    def test_vanilla_alone(self):
        db = LocalisationDB.from_dirs(self.vanilla)
        self.assertEqual(db.lookup("SHARED"), "from a")
        self.assertEqual(db.lookup("TEXT_KEY"), "vanilla text")
        self.assertEqual(db.replaced_files, [])

    def test_mod_first_matters(self):
        db = LocalisationDB.from_dirs([self.vanilla, self.mod])
        self.assertEqual(db.lookup("TEXT_KEY"), "vanilla text")
        self.assertEqual(db.lookup("SHARED"), "from mod")  # 00_mod.csv sigue cargando antes por nombre

    def test_overrides(self):
        db = LocalisationDB.from_dirs([self.mod, self.vanilla])
        overrides = db.overrides()
        self.assertEqual([o.key for o in overrides], ["SHARED", "A_KEY"])
        shared = overrides[0]
        self.assertIsInstance(shared, KeyOverride)
        self.assertEqual(shared.winner, (self.mod / "00_mod.csv", 1))
        self.assertEqual(shared.shadowed, ((self.vanilla / "a.csv", 1), (self.vanilla / "Z.CSV", 2)))
        self.assertEqual(overrides[1].shadowed, ((self.vanilla / "a.csv", 3),))
        self.assertEqual(db.definitions("SHARED")[0], shared.winner)
        self.assertEqual(db.definitions("missing"), [])

    def test_fallback_and_keys(self):
        db = LocalisationDB.from_dirs([self.mod, self.vanilla])
        self.assertEqual(db.lookup("EMPTY_ES", "es"), "")
        self.assertEqual(db.lookup("EMPTY_ES", "es", fallback="en"), "only english")
        self.assertEqual(db.keys()[:2], ["SHARED", "MOD_ONLY"])
        self.assertIn("Z_KEY", db)
        self.assertEqual(len(db), len(set(db.keys())))

    def test_missing_dirs_are_skipped(self):
        db = LocalisationDB.from_dirs([self.mod.parent / "nope", str(self.vanilla)])
        self.assertEqual(len(db.files), 4)
        self.assertEqual(len(LocalisationDB.from_dirs([]).files), 0)

    def test_rebuild_and_add_file(self):
        db = LocalisationDB.from_dirs([self.mod, self.vanilla])
        db.files[0].set("NEW_KEY", "en", "new")
        self.assertIsNone(db.lookup("NEW_KEY"))
        db.rebuild()
        self.assertEqual(db.lookup("NEW_KEY"), "new")
        self.assertEqual(db.source_of("NEW_KEY"), (self.mod / "00_mod.csv", 3))
        db.add_file(parse_csv(row("LAST", "last") + row("SHARED", "late"), filename="late.csv"))
        self.assertEqual(db.lookup("LAST"), "last")
        self.assertEqual(db.lookup("SHARED"), "from mod")

    def test_in_memory_files(self):
        db = LocalisationDB([parse_csv(row("K", "one")), parse_csv(row("K", "two"))])
        self.assertEqual(db.lookup("K"), "one")
        self.assertEqual(db.source_of("K"), (None, 1))


if __name__ == "__main__":
    unittest.main()
