import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import corpus_roots  # noqa: E402
from vic2studio.core.clausewitz import parse_file, to_json  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src"
USER_BROKEN = ("somaliland_shago.txt", "zulu_expancionshago.txt")


def run_cli(*args):
    env = dict(os.environ, PYTHONPATH=str(SRC), PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "vic2studio.core.clausewitz", *map(str, args)],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=120,
    )


class CliCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "sub").mkdir()
        self.good = root / "good.txt"
        self.good.write_bytes(b"owner = GEL\r\n")
        self.broken = root / "sub" / "broken.txt"
        self.broken.write_bytes(b"political_decisions = {\n\tx = {\n\t}\n")
        (root / "sub" / "ignored.csv").write_bytes(b"KEY;texto;\n")
        self.root = root

    def test_clean_file_exits_zero(self):
        done = run_cli("check", self.good)
        self.assertEqual((done.returncode, done.stdout), (0, ""))
        self.assertIn("1 archivo(s), 0 error(es), 0 aviso(s)", done.stderr)

    def test_directory_with_errors(self):
        done = run_cli("check", self.root)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout.splitlines(), [
            f"{self.broken}:1:23: error: El bloque 'political_decisions' abierto en la línea 1 no se cierra (falta '}}')",
        ])
        self.assertIn("2 archivo(s), 1 error(es)", done.stderr)

    def test_english_and_missing_file(self):
        done = run_cli("check", self.broken, self.root / "missing.txt", "--lang", "en")
        self.assertEqual(done.returncode, 1)
        lines = done.stdout.splitlines()
        self.assertEqual(lines[0], f"{self.broken}:1:23: error: Block 'political_decisions' opened on line 1 "
                                   "is never closed (missing '}')")
        self.assertTrue(lines[1].startswith(f"{self.root / 'missing.txt'}: error: cannot read:"), lines[1])

    def test_tojson(self):
        commented = self.root / "commented.txt"
        commented.write_text("# cabecera\na = { 1 2 }\n", encoding="cp1252")
        done = run_cli("tojson", commented)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(json.loads(done.stdout), to_json(parse_file(commented).document))
        with_comments = run_cli("tojson", commented, "--comments")
        self.assertEqual(json.loads(with_comments.stdout)["entries"][0]["comments"], ["# cabecera"])
        broken = run_cli("tojson", self.broken)
        self.assertEqual(broken.returncode, 1)
        self.assertIn(":1:23: error:", broken.stderr)
        self.assertEqual(json.loads(broken.stdout)["entries"][0]["key"]["text"], "political_decisions")


class CliUserCorpusTests(unittest.TestCase):
    def test_user_broken_files(self):
        found = sorted(p for root in corpus_roots() for p in root.rglob("*.txt") if p.name in USER_BROKEN)
        if len(found) != 2:
            self.skipTest("el corpus del usuario no está disponible")
        done = run_cli("check", *found)
        self.assertEqual(done.returncode, 1)
        errors = [line for line in done.stdout.splitlines() if ": error: " in line]
        self.assertEqual(errors, [
            f"{path}:1:23: error: El bloque 'political_decisions' abierto en la línea 1 no se cierra (falta '}}')"
            for path in found
        ])
        hints = [line for line in done.stdout.splitlines() if ": info: " in line]
        self.assertEqual(len(hints), 1)
        self.assertIn("zulu_expancionshago.txt:155:1: info:", hints[0])


if __name__ == "__main__":
    unittest.main()
