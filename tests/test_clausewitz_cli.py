import codecs
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

    def test_encodings_the_game_cannot_read(self):
        """R1: la CLI no avisaba de un UTF-16 (ilegible para el juego) ni de un BOM UTF-8 delante de cp1252,
        y salía con 0; ahora da los mismos diagnósticos que «Validar mod»."""
        script = 'country_event = {\r\n\tid = 2\r\n}\r\n'
        files = {
            "le.txt": script.encode("utf-16"),
            "no_bom.txt": script.encode("utf-16-le"),
            "be.txt": codecs.BOM_UTF16_BE + script.encode("utf-16-be"),
            "stray.txt": codecs.BOM_UTF8 + script.replace("2", '"Le\u00f3n"').encode("cp1252"),  # no es UTF-8
        }
        for name, data in files.items():
            (self.root / name).write_bytes(data)
        unreadable = run_cli("check", *(self.root / n for n in ("le.txt", "no_bom.txt", "be.txt")), "--lang", "en")
        self.assertEqual(unreadable.returncode, 1)
        self.assertEqual(unreadable.stdout.splitlines(), [
            f"{self.root / name}:1:1: error: The file is encoded as {shown} (16-bit Unicode): Victoria II cannot "
            "read it at all. Save it as Windows-1252 (ANSI)."
            for name, shown in (("le.txt", "UTF-16"), ("no_bom.txt", "UTF-16-LE"), ("be.txt", "UTF-16-BE-BOM"))
        ])
        self.assertIn("3 file(s), 3 error(s), 0 warning(s)", unreadable.stderr)
        stray = run_cli("check", self.root / "stray.txt")
        self.assertEqual(stray.returncode, 0)
        self.assertEqual([line.split(": aviso: ")[0] for line in stray.stdout.splitlines()],
                         [f"{self.root / 'stray.txt'}:1:1"])
        self.assertIn("'ï»¿'", stray.stdout)
        self.assertIn("1 archivo(s), 0 error(es), 1 aviso(s)", stray.stderr)

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

    def test_tojson_deep_nesting(self):
        # json.dump es recursivo: antes, a partir de ~330 niveles, RecursionError y JSON a medias (P6).
        depth = 500
        deep = self.root / "deep.txt"
        deep.write_text("a = {\n" * depth + "b = c\n" + "}\n" * depth, encoding="cp1252")
        done = run_cli("tojson", deep)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertEqual(done.stdout.count('"type": "block"'), depth + 1)
        self.assertEqual(done.stdout.count("{"), done.stdout.count("}"))
        self.assertTrue(done.stdout.endswith("}\n"))

    def test_map_files_are_checked(self):
        # map/default.map es un script Clausewitz (P11).
        (self.root / "map").mkdir()
        default = self.root / "map" / "default.map"
        default.write_bytes(b"definitions = \"definition.csv\"\nsea_starts = {\n\t1 2\n")
        done = run_cli("check", self.root / "map")
        self.assertEqual(done.returncode, 1)
        self.assertEqual([line.split(": error: ")[0] for line in done.stdout.splitlines()], [f"{default}:2:14"])
        self.assertIn("1 archivo(s), 1 error(es)", done.stderr)


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
