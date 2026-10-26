import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core.csvloc import InvalidFieldError, KeyOverride, LocalisationDB, parse_csv  # noqa: E402


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
        db.add_file(parse_csv(row("LAST", "last") + row("SHARED", "late"), filename=self.mod / "zz_late.csv"))
        self.assertEqual(db.lookup("LAST"), "last")
        self.assertEqual(db.lookup("SHARED"), "from mod")
        self.assertEqual(db.files[-1].path.name, "zz_late.csv")

    def test_add_file_follows_the_game_load_order(self):
        """FC-7: un 00_new.csv nuevo del mod quedaba el último y la base daba por ganadora otra definición."""
        db = LocalisationDB.from_dirs([self.mod, self.vanilla])
        new = parse_csv(row("SHARED", "new first") + row("A_KEY", "new a"), filename=self.mod / "000_new.csv")
        db.add_file(new)
        self.assertIs(db.files[0], new)
        self.assertEqual((db.lookup("SHARED"), db.lookup("A_KEY")), ("new first", "new a"))
        self.assertEqual(db.source_of("SHARED"), (self.mod / "000_new.csv", 1))
        self.assertEqual(db.overrides()[0].shadowed[0], (self.mod / "00_mod.csv", 1))
        # Mismo nombre que uno cargado: lo sustituye, como entre carpetas.
        replacement = parse_csv(row("Z_KEY", "z from mod"), filename=self.mod / "z.csv")
        db.add_file(replacement)
        self.assertEqual([f.path.name for f in db.files], ["000_new.csv", "00_mod.csv", "a.csv", "b.csv",
                                                           "Text.csv", "z.csv"])
        self.assertEqual(db.replaced_files[-1], (self.vanilla / "Z.CSV", self.mod / "z.csv"))
        self.assertEqual(db.lookup("Z_KEY"), "z from mod")
        memory = parse_csv(row("MEMORY", "m"))
        db.add_file(memory)
        self.assertIs(db.files[-1], memory)

    def test_add_file_keeps_the_folder_priority(self):
        """R3: añadir el text.csv de vanilla sustituía al del mod, y recargar un archivo anotaba (X, X)."""
        db = LocalisationDB.from_dirs([self.mod, self.vanilla])
        replaced = list(db.replaced_files)
        db.add_file(parse_csv(row("TEXT_KEY", "mod text, recargado"), filename=self.mod / "Text.csv"))
        self.assertEqual(db.lookup("TEXT_KEY"), "mod text, recargado")
        self.assertEqual(db.replaced_files, replaced, "recargar un archivo no es sustituirlo")
        db.add_file(parse_csv(row("TEXT_KEY", "vanilla text"), filename=self.vanilla / "text.csv"))
        self.assertEqual(db.lookup("TEXT_KEY"), "mod text, recargado", "el del mod sigue ganando")
        self.assertEqual([f.path for f in db.files if f.path.name.upper() == "TEXT.CSV"], [self.mod / "Text.csv"])
        self.assertEqual(db.replaced_files, replaced)
        # Uno del mod con el mismo nombre que uno de vanilla lo sustituye, y también a lo que este tapaba.
        db = LocalisationDB.from_dirs([self.vanilla])
        db.dirs, db.replaced_files = [self.mod, self.vanilla], [(Path("otro/text.csv"), self.vanilla / "text.csv")]
        db.add_file(parse_csv(row("TEXT_KEY", "mod text"), filename=self.mod / "Text.csv"))
        self.assertEqual(db.lookup("TEXT_KEY"), "mod text")
        self.assertEqual(db.replaced_files, [(Path("otro/text.csv"), self.mod / "Text.csv"),
                                             (self.vanilla / "text.csv", self.mod / "Text.csv")])

    def test_define_keeps_the_index_up_to_date(self):
        """FC-8: registrar claves exigía reconstruir la base entera después de cada una."""
        db = LocalisationDB.from_dirs([self.mod, self.vanilla])
        mod_file, a_file = db.files[0], db.files[1]
        db.define("BRAND_NEW", {"en": "brand", "es": "nueva"}, a_file)
        db.define("A_KEY", {"en": "mod a"}, mod_file)  # gana a la de a.csv
        db.define("SHARED", {"es": "compartida"}, mod_file)  # ya existía: cambia la fila
        db.define("TEXT_KEY", {"en": "late text"}, a_file)  # antes que Text.csv: gana
        self.assertEqual(db.lookup("A_KEY"), "mod a")
        self.assertEqual(db.lookup("SHARED", "es"), "compartida")
        expected = {key: (db.definitions(key), db.lookup(key)) for key in db.keys()}
        overrides = db.overrides()
        db.rebuild()
        self.assertEqual({key: (db.definitions(key), db.lookup(key)) for key in db.keys()}, expected)
        self.assertEqual(db.overrides(), overrides)
        with self.assertRaises(ValueError):
            db.define("X", {"en": "x"}, parse_csv(""))
        with self.assertRaises(InvalidFieldError):
            db.define("SHARED", {"en": "ok", "es": "a;b"}, mod_file)
        self.assertEqual(db.lookup("SHARED"), "from mod", "todo o nada")

    def test_define_keeps_the_load_order(self):
        """NF-2: tras define, keys() y overrides() ponían al final una clave nueva (y dejaban donde
        estaba una que pasaba a ganar en un archivo anterior) aunque su archivo se cargue antes."""
        a = parse_csv(row("A", "a"), filename=self.mod / "00_a.csv")
        t = parse_csv(row("T", "t") + row("T", "t2") + row("B", "b"), filename=self.mod / "text.csv")
        z = parse_csv(row("Z", "z"), filename=self.mod / "zz.csv")
        db = LocalisationDB([a, t, z])
        db.define("NEW", {"en": "new"}, a)  # clave nueva en el primer archivo
        db.define("B", {"en": "b en a"}, a)  # ya existía en text.csv: ahora gana la de 00_a.csv
        db.define("NEW", {"en": "tapada"}, z)  # y además se repite después
        expected_keys = ["A", "NEW", "B", "T", "Z"]
        self.assertEqual(db.keys(), expected_keys)
        self.assertEqual([o.key for o in db.overrides()], ["NEW", "B", "T"])
        rebuilt = LocalisationDB([a, t, z])
        self.assertEqual((rebuilt.keys(), rebuilt.overrides()), (expected_keys, db.overrides()))

    def test_define_matches_rebuild(self):
        """NF-2: tras cualquier serie de define, la base es la que daría rebuild(), orden incluido."""
        for seed in range(150):
            rnd = random.Random(seed)
            keys = [f"K{i}" for i in range(rnd.randrange(2, 9))]
            files = []
            names = ["00_a.csv", "01_b.csv", "a_c.csv", "text.csv", "zz.csv"]
            for name in sorted(rnd.sample(names, rnd.randrange(1, 5))):
                lines = (rnd.choice(["# c;x", "", f"{rnd.choice(keys)};{name}"]) for _ in range(rnd.randrange(6)))
                files.append(parse_csv("".join(line + "\r\n" for line in lines), filename=self.mod / name))
            if rnd.random() < 0.2:
                files.append(parse_csv(row(rnd.choice(keys), "en memoria")))
            db = LocalisationDB(files)
            for step in range(rnd.randrange(1, 25)):
                file, key = rnd.choice(db.files), rnd.choice(keys + [f"NEW{step}"])
                db.define(key, {"en": str(step)}, file)
                ref = LocalisationDB(list(db.files))
                where = f"semilla {seed}, paso {step}: define {key} en {file.path}"
                self.assertEqual(db.keys(), ref.keys(), where)
                self.assertEqual(db.overrides(), ref.overrides(), where)
                self.assertEqual([(db.definitions(k), db.file_of(k)) for k in keys],
                                 [(ref.definitions(k), ref.file_of(k)) for k in keys], where)

    def test_new_rows_report_their_current_line(self):
        """Una fila nueva (sin línea leída) da su posición actual, esté al final (define) o en medio."""
        file = parse_csv(row("A", "a") + row("B", "b"), filename=self.mod / "x.csv")
        file.add_row("C", {"en": "c"}, index=1)
        db = LocalisationDB([parse_csv(row("C", "first"), filename=self.mod / "00.csv"), file])
        db.define("D", {"en": "d"}, file)
        self.assertEqual(db.definitions("C"), [(self.mod / "00.csv", 1), (self.mod / "x.csv", 2)])
        self.assertEqual(db.source_of("D"), (self.mod / "x.csv", 4))
        empty = parse_csv("", filename=self.mod / "01.csv")
        db = LocalisationDB([empty])
        db.define("E", {"en": "e"}, empty)
        self.assertEqual(db.source_of("E"), (self.mod / "01.csv", 1), "la primera fila también")

    def test_origin_and_where_to_define(self):
        """FC-8: ninguna API decía si gana el mod o vanilla ni en qué archivo definir una clave para que gane."""
        db = LocalisationDB.from_dirs([self.mod, self.vanilla])
        self.assertEqual(db.dirs, [self.mod, self.vanilla])
        self.assertEqual((db.origin("SHARED"), db.origin("Z_KEY"), db.origin("missing")), (0, 1, None))
        self.assertTrue(db.would_win("000_new.csv", "SHARED"))
        self.assertFalse(db.would_win("00_new.csv", "SHARED"), "00_NEW.CSV va después de 00_MOD.CSV")
        self.assertTrue(db.would_win("00_MOD.csv", "SHARED"))
        self.assertFalse(db.would_win("zz_late.csv", "A_KEY"))
        self.assertTrue(db.would_win("anything.csv", "missing"))
        self.assertIsNone(LocalisationDB([parse_csv(row("K", "v"))]).origin("K"))

    def test_unreadable_files_do_not_stop_the_load(self):
        """FC-8: from_dirs abortaba entera ante el primer archivo ilegible."""
        self._write(self.mod, "00_bad.csv", row("BAD", "Canción"))
        db = LocalisationDB.from_dirs([self.mod, self.vanilla], encoding="utf-8")
        self.assertEqual([path.name for path, _ in db.errors], ["00_bad.csv"])
        self.assertIsInstance(db.errors[0][1], UnicodeDecodeError)
        self.assertEqual(db.lookup("SHARED"), "from mod")

    def test_in_memory_files(self):
        db = LocalisationDB([parse_csv(row("K", "one")), parse_csv(row("K", "two"))])
        self.assertEqual(db.lookup("K"), "one")
        self.assertEqual(db.source_of("K"), (None, 1))


if __name__ == "__main__":
    unittest.main()
