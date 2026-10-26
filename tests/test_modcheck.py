"""Descriptor ``.mod`` (core.modfile) y validación de un mod completo (core.modcheck), sin Qt."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import DEV_DIARY, corpus_roots, user_mod, user_mod_error_files  # noqa: E402
from vic2studio.core.clausewitz import Severity  # noqa: E402
from vic2studio.core.modcheck import (  # noqa: E402
    CHECK_FAILED,
    KIND_CSV,
    READ_ERROR,
    check_file,
    check_mod,
    collect_files,
    file_kind,
)
from vic2studio.core.modfile import INSIDE, SIBLING, find_descriptor, read_descriptor  # noqa: E402


def write(path: Path, text: str, encoding: str = "cp1252") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode(encoding))
    return path


class DescriptorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_fields_lists_and_errors(self):
        file = write(self.root / "Big.mod", '# comentario\r\nname = "Gran Mod"\r\npath = "mod\\BigMod"\r\n'
                                            'user_dir = "Big"\r\nreplace_path = "history/pops"\r\n'
                                            'replace_path = "history/units"\r\ndependencies = { "A" "B" }\r\n')
        d = read_descriptor(file)
        self.assertEqual((d.name, d.path, d.user_dir), ("Gran Mod", "mod\\BigMod", "Big"))
        self.assertEqual(d.folder_name, "BigMod")
        self.assertEqual(d.replace_paths, ("history/pops", "history/units"))
        self.assertEqual(d.dependencies, ("A", "B"))
        self.assertEqual(d.errors, [])
        broken = read_descriptor(write(self.root / "Broken.mod", 'name = "Roto"\ndependencies = { "A"\n'))
        self.assertEqual(broken.name, "Roto")
        self.assertEqual([e.code for e in broken.errors], ["unclosed_block"])
        self.assertIsNone(read_descriptor(self.root / "missing.mod"))

    def test_find_sibling_by_path_then_by_name_then_inside(self):
        mod = self.root / "mod" / "MiMod"
        mod.mkdir(parents=True)
        self.assertIsNone(find_descriptor(mod))
        write(mod / "copia.mod", 'name = "Dentro"\n')
        inside = find_descriptor(mod)
        self.assertEqual((inside.name, inside.location), ("Dentro", INSIDE))
        write(self.root / "mod" / "mimod.mod", 'name = "Por nombre"\n')
        self.assertEqual(find_descriptor(mod).name, "Por nombre", "los nombres no distinguen mayúsculas")
        write(self.root / "mod" / "zz.mod", 'name = "Por ruta"\npath = "mod/MIMOD"\n')
        found = find_descriptor(mod)
        self.assertEqual((found.name, found.location), ("Por ruta", SIBLING))

    def test_user_descriptor(self):
        for root in corpus_roots():
            if (root / "VSM.mod").is_file() and (root / "VSM").is_dir():
                d = find_descriptor(root / "VSM")
                self.assertEqual((d.name, d.path, d.user_dir, d.location), ("Shago Mod", "mod/VSM", "VSM", SIBLING))
                return
        self.skipTest("sin el mod del usuario en VIC2_CORPUS")


class ModCheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Mod"
        self.addCleanup(self._tmp.cleanup)
        write(self.root / "events" / "good.txt", "country_event = {\n\tid = 1\n}\n")
        write(self.root / "decisions" / "bad.txt", "political_decisions = {\n\ta = {\n\t\tb = c\n\t}\n")
        write(self.root / "localisation" / "00_mod.csv", "KEY;Hello;;;;Hola;;;;;;;;;x\nKEY;Again;;;;Otra;;;;;;;;;x\n")
        write(self.root / "interface" / "x.gui", "guiTypes = { }\n")
        write(self.root / "notes.lua", "print('no se valida')\n")
        write(self.root / ".git" / "config.txt", "{{{ no se recorre\n")

    def test_collect_files_order_kinds_and_extras(self):
        descriptor = write(self.root.parent / "Mod.mod", 'name = "Mod"\npath = "mod/Mod"\n')
        files = [p.relative_to(self.root.parent).as_posix() for p in collect_files(self.root, [descriptor])]
        self.assertEqual(files, ["Mod.mod", "Mod/decisions/bad.txt", "Mod/events/good.txt",
                                 "Mod/interface/x.gui", "Mod/localisation/00_mod.csv"])
        self.assertEqual(len(collect_files(self.root, [descriptor, descriptor, self.root / "events" / "good.txt"])), 5)
        self.assertEqual(file_kind("a/B.CSV"), KIND_CSV)
        self.assertIsNone(file_kind("x.lua"))

    def test_report_counts_order_and_messages(self):
        progress = []
        report = check_mod(self.root, progress=lambda done, total, rel: progress.append((done, total, rel)))
        self.assertFalse(report.cancelled)
        self.assertEqual((report.files, report.clausewitz_files, report.csv_files), (4, 3, 1))
        self.assertEqual([p[0] for p in progress], [1, 2, 3, 4])
        self.assertEqual({p[1] for p in progress}, {4})
        self.assertEqual(report.files_with(Severity.ERROR), ["decisions/bad.txt"])
        first = report.issues[0]
        self.assertEqual((first.relative, first.code, first.line, first.severity),
                         ("decisions/bad.txt", "unclosed_block", 1, Severity.ERROR))
        self.assertIn("political_decisions", first.message("es"))
        self.assertIn("never closed", first.message("en"))
        duplicate = next(i for i in report.issues if i.code == "duplicate_key")
        self.assertEqual((duplicate.kind, duplicate.line, duplicate.severity), (KIND_CSV, 2, Severity.WARNING))
        ranks = [{Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}[i.severity] for i in report.issues]
        self.assertEqual(ranks, sorted(ranks), "los errores van primero")
        self.assertGreaterEqual(report.elapsed, 0)

    def test_cancel_and_failures_never_raise(self):
        calls = []
        report = check_mod(self.root, progress=lambda *a: calls.append(a), cancelled=lambda: len(calls) >= 2)
        self.assertTrue(report.cancelled)
        self.assertEqual(report.files, 2)
        missing = check_file(self.root / "nope.txt", self.root)
        self.assertEqual([(i.code, i.severity) for i in missing], [(READ_ERROR, Severity.ERROR)])
        self.assertIn("No se pudo leer", missing[0].message("es"))
        self.assertEqual(missing[0].relative, "nope.txt")
        outside = check_file(self.root.parent / "elsewhere.txt", self.root)
        self.assertEqual(outside[0].relative, "../elsewhere.txt")

    def test_unexpected_failure_is_reported(self):
        from vic2studio.core import modcheck

        original = modcheck.parse_file
        modcheck.parse_file = lambda path: (_ for _ in ()).throw(RuntimeError("fallo simulado"))
        try:
            issues = check_file(self.root / "events" / "good.txt", self.root)
        finally:
            modcheck.parse_file = original
        self.assertEqual(issues[0].code, CHECK_FAILED)
        self.assertIn("fallo simulado", issues[0].message("en"))


class UserModTests(unittest.TestCase):
    def test_user_mod_has_exactly_the_known_errors(self):
        mod = user_mod()
        if mod is None:
            self.skipTest("sin el mod del usuario (VIC2_CORPUS o tests/fixtures/shago_mod_min)")
        report = check_mod(mod, extra_files=[mod.parent / "VSM.mod"])
        unclosed = sorted((i.relative, i.line, i.column) for i in report.issues if i.code == "unclosed_block")
        self.assertEqual(unclosed, [("decisions/somaliland_shago.txt", 1, 23),
                                    ("decisions/zulu_expancionshago.txt", 1, 23)])
        # En el mod completo, v2dd2.txt (un diario de desarrollo en prosa de Paradox, no un script)
        # es el tercer archivo con errores; la muestra mínima no lo incluye.
        self.assertEqual(report.files_with(Severity.ERROR), user_mod_error_files(mod))
        if (mod / DEV_DIARY).is_file():
            diary = [(i.code, i.line) for i in report.issues if i.relative == DEV_DIARY and i.severity is Severity.ERROR]
            self.assertEqual(diary, [("missing_key", 4)])


if __name__ == "__main__":
    unittest.main()
