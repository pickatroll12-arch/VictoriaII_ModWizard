import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vic2studio.core.csvloc import from_json, read_csv_file, to_source  # noqa: E402
from vic2studio.core.csvloc.cli import main  # noqa: E402

GOOD = "K;Hello;;;;Hola;;;;;;;;;x\r\n"
WARN = "K;Hello\r\n"


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _file(self, name: str, data: bytes) -> Path:
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def _run(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_check_clean_file(self):
        path = self._file("good.csv", GOOD.encode("cp1252"))
        code, out, _ = self._run("check", str(path))
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "1 file(s): 0 error(s), 0 warning(s), 0 info")

    def test_check_warnings_and_languages(self):
        path = self._file("warn.csv", WARN.encode("cp1252"))
        code, out, _ = self._run("check", str(path))
        self.assertEqual(code, 0)
        self.assertIn(f"{path}:1: warning: Row 'K' has only 1 of the 13 language columns. [too_few_columns]", out)
        code, out, _ = self._run("check", str(path), "--lang", "es")
        self.assertIn(f"{path}:1: aviso: La fila 'K' solo tiene 1 de las 13 columnas de idioma.", out)
        self.assertIn("1 archivo(s): 0 error(es), 2 aviso(s), 0 info", out)
        self.assertEqual(self._run("check", str(path), "--strict")[0], 1)

    def test_check_errors_and_missing_paths(self):
        path = self._file("bad.csv", "K;Привет;;;;;;;;;;;;;x\r\n".encode("utf-8"))
        code, out, _ = self._run("check", str(path))
        self.assertEqual(code, 1)
        self.assertIn("[unencodable_character]", out)
        self.assertIn("[non_game_encoding]", out)
        code, _, err = self._run("check", str(self.dir / "nope.csv"))
        self.assertEqual(code, 2)
        self.assertIn("nope.csv", err)

    def test_check_directory_and_summary(self):
        self._file("loc/a.csv", WARN.encode("cp1252"))
        self._file("loc/sub/b.CSV", (GOOD + GOOD).encode("cp1252"))
        self._file("loc/c.txt", WARN.encode("cp1252"))
        code, out, _ = self._run("check", str(self.dir / "loc"), "--summary")
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertEqual([line.split() for line in lines[:3]],
                         [["1", "duplicate_key"], ["1", "missing_end_marker"], ["1", "too_few_columns"]])
        self.assertEqual(lines[-1], "2 file(s): 0 error(s), 3 warning(s), 0 info")

    def test_tojson_and_fromjson(self):
        raw = "#c;x\r\nK;País;;;;España;;;;;;;;;x;;;;\nL;l".encode("cp1252")
        source = self._file("in.csv", raw)
        output = self.dir / "out.json"
        self.assertEqual(self._run("tojson", str(source), "-o", str(output))[0], 0)
        obj = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(obj["rows"][1]["fields"][4], "España")
        self.assertEqual(to_source(from_json(obj)), to_source(read_csv_file(source)))
        code, out, _ = self._run("tojson", str(source))
        self.assertEqual((code, json.loads(out)), (0, obj))
        back = self.dir / "back.csv"
        self.assertEqual(self._run("fromjson", str(output), "-o", str(back))[0], 0)
        self.assertEqual(back.read_bytes(), raw)

    def test_module_entry_point(self):
        path = self._file("warn.csv", WARN.encode("cp1252"))
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        result = subprocess.run([sys.executable, "-m", "vic2studio.core.csvloc", "check", str(path), "--lang", "es"],
                                capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(self.dir))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[missing_end_marker]", result.stdout)
        self.assertIn("aviso", result.stdout)
        result = subprocess.run([sys.executable, "-m", "vic2studio.core.csvloc", "tojson", str(path)],
                                capture_output=True, env=env, cwd=str(self.dir))
        self.assertEqual(json.loads(result.stdout.decode("utf-8"))["rows"][0]["key"], "K")
        usage = subprocess.run([sys.executable, "-m", "vic2studio.core.csvloc"], capture_output=True, env=env)
        self.assertEqual(usage.returncode, 2)


if __name__ == "__main__":
    unittest.main()
