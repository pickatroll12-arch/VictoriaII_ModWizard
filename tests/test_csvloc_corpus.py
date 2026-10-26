import json
import sys
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import corpus_files, corpus_roots  # noqa: E402
from vic2studio.core.csvloc import (  # noqa: E402
    LocalisationDB,
    from_json,
    read_csv_file,
    to_json,
    to_source,
    write_csv_file,
)
from vic2studio.core.encoding import encode_text  # noqa: E402

USER_PREFIX = "00_VSM_"


def csv_corpus() -> list[Path]:
    files = corpus_files({".csv"})
    files += [p for p in corpus_files({".bak"}) if p.name.lower().endswith(".csv.bak")]
    return sorted(files)


def find_dirs(name: str) -> list[Path]:
    """Carpetas ``localisation`` del corpus que contienen ``name``."""
    found = []
    for root in corpus_roots():
        found.extend(p.parent for p in root.rglob(name) if p.parent.name == "localisation")
    return sorted(set(found))


class CorpusRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.files = csv_corpus()
        if not self.files:
            self.skipTest("sin corpus disponible")

    def test_every_csv_round_trips_byte_for_byte(self):
        for path in self.files:
            with self.subTest(path=str(path)):
                file = read_csv_file(path)
                self.assertEqual(encode_text(to_source(file), file.encoding), path.read_bytes())

    def test_json_invariant(self):
        for path in self.files:
            with self.subTest(path=str(path)):
                file = read_csv_file(path)
                obj = json.loads(json.dumps(to_json(file), ensure_ascii=False))
                self.assertEqual(to_source(from_json(obj)), to_source(file))

    def test_bak_file_is_csv(self):
        baks = [p for p in self.files if p.name.endswith(".bak")]
        if not baks:
            self.skipTest("sin .csv.bak en el corpus")
        for path in baks:
            file = read_csv_file(path)
            self.assertGreater(len(file.keys()), 1000)

    def test_vanilla_has_no_semicolons_inside_quotes(self):
        counts = Counter()
        for path in self.files:
            if path.name.startswith(USER_PREFIX):
                continue
            counts.update(d.code for d in read_csv_file(path).diagnostics)
        self.assertEqual(counts["semicolon_in_quotes"], 0)
        self.assertEqual(counts["unencodable_character"], 0)
        self.assertEqual(counts["header_row"], 0)

    def test_single_edit_changes_single_line(self):
        source = max(self.files, key=lambda p: p.stat().st_size)
        file = read_csv_file(source)
        row = next(r for r in file.data_rows() if r.has_end_marker and r.get("es"))
        row.set("es", row.get("es") + " (editado)")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / source.name
            write_csv_file(target, file, backup=False)
            before = source.read_bytes().split(b"\n")
            after = target.read_bytes().split(b"\n")
        self.assertEqual(len(before), len(after))
        changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        self.assertEqual(changed, [row.line - 1])


class CorpusPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.dirs = find_dirs("text.csv")
        if not self.dirs:
            self.skipTest("sin text.csv en el corpus")

    def test_read_text_csv_fast(self):
        path = self.dirs[0] / "text.csv"
        start = time.perf_counter()
        file = read_csv_file(path)
        elapsed = time.perf_counter() - start
        self.assertGreater(len(file.rows), 15000)
        self.assertLess(elapsed, 1.5, f"{path}: {elapsed:.2f} s")

    def test_database_fast(self):
        for directory in self.dirs:
            start = time.perf_counter()
            db = LocalisationDB.from_dirs([directory])
            elapsed = time.perf_counter() - start
            self.assertGreater(len(db), 20000)
            self.assertLess(elapsed, 5.0, f"{directory}: {elapsed:.2f} s")


class UserModTests(unittest.TestCase):
    """Particularidades del mod del usuario (VSM) descritas en el docstring de csvloc."""

    def setUp(self):
        dirs = find_dirs(USER_PREFIX + "decisions.csv")
        if not dirs:
            self.skipTest("sin el corpus del mod VSM")
        self.mod_dir = dirs[0]

    def test_decisions_semicolons_inside_quotes(self):
        file = read_csv_file(self.mod_dir / (USER_PREFIX + "decisions.csv"))
        quoted = [d for d in file.diagnostics if d.code == "semicolon_in_quotes"]
        self.assertEqual([d.line for d in quoted], [35, 37, 39, 41, 43, 45])
        self.assertEqual({d.args["field"] for d in quoted}, {1})
        row = file.rows[34]
        self.assertTrue(row.get("en").startswith('"'))
        self.assertEqual(row.get("es"), "")
        self.assertTrue(row.get("it").startswith("Necesitamos"))

    def test_user_files_have_header_and_no_marker(self):
        for path in sorted(self.mod_dir.glob(USER_PREFIX + "*.csv")):
            with self.subTest(path=path.name):
                file = read_csv_file(path)
                codes = Counter(d.code for d in file.diagnostics)
                data_rows = sum(1 for _ in file.data_rows())
                self.assertEqual(file.diagnostics[0].code, "header_row")
                self.assertEqual(file.diagnostics[0].line, 1)
                self.assertEqual(codes["missing_end_marker"], data_rows - 1)
                self.assertFalse(any(r.has_end_marker for r in file.data_rows()))

    def test_mod_overrides_vanilla(self):
        vanilla = [d for d in find_dirs("text.csv") if not any(d.glob(USER_PREFIX + "*.csv"))]
        if not vanilla:
            self.skipTest("sin carpeta vanilla en el corpus")
        db = LocalisationDB.from_dirs([self.mod_dir, vanilla[0]])
        user_files = sorted(p.name for p in self.mod_dir.glob(USER_PREFIX + "*.csv"))
        self.assertEqual([f.path.name for f in db.files[:len(user_files)]], user_files)
        shared = {p.name for p in self.mod_dir.glob("*.csv")} & {p.name for p in vanilla[0].glob("*.csv")}
        self.assertEqual(len(db.replaced_files), len(shared))
        self.assertTrue(all(winner.parent == self.mod_dir for _, winner in db.replaced_files))
        countries = db.files[user_files.index(USER_PREFIX + "countries.csv")]
        for row in list(countries.data_rows())[1:]:
            self.assertEqual(db.source_of(row.key), (countries.path, row.line))
            self.assertEqual(db.lookup(row.key, "es"), row.get("es"))


if __name__ == "__main__":
    unittest.main()
