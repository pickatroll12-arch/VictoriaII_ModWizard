"""Regresiones de la revisión adversarial de VFS y arquitectura (iteración 2): I1 frente a raíces, descriptores,
diarios de un mod movido y huecos del detector de escrituras."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import isolate_appdirs  # noqa: E402
from test_arch_writes import scan_source  # noqa: E402
from vic2studio.core.modfile import find_descriptor, read_descriptor  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.vfs import DESCRIPTOR_REL, VirtualFS  # noqa: E402
from vic2studio.core.vfs.guard import evaluate_mod, inspect_folder  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src"


def _game(base: Path) -> Path:
    game = base / "Victoria 2"
    (game / "common").mkdir(parents=True)
    (game / "v2game.exe").write_bytes(b"MZ")
    (game / "common" / "cb_types.txt").write_bytes(b"x = 1\r\n")
    (game / "mod").mkdir()
    return game


def _mod(game: Path, name: str, path: str | None = None, extra: bytes = b"") -> Path:
    root = game / "mod" / name
    (root / "events").mkdir(parents=True, exist_ok=True)
    (game / "mod" / f"{name}.mod").write_bytes(
        f'name = "{name}"\r\npath = "{path or "mod/" + name}"\r\n'.encode() + extra)
    return root


class _Base(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)
        self.base = Path(tempfile.mkdtemp(prefix="verify-i1-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.game = _game(self.base)

    def open(self, mod_root, **kwargs):
        project = Project.open(self.game, mod_root, **kwargs)
        self.addCleanup(project.close)
        return project

    def edit(self, project, rel, data, create=False):
        with project.edit("x"):
            project.ws.replace_text(project.ws.open(rel, create=create), data)


class ModsFolderIsNotAModTests(_Base):
    def test_evaluate_mod_rejects_the_mods_folder(self):
        _mod(self.game, "Alpha")
        level, key, _ = evaluate_mod(inspect_folder(self.game / "mod"), self.game)
        self.assertEqual((level, key), ("error", "check.mod_is_mods_folder"))

    def test_the_core_refuses_bad_mod_roots(self):
        alpha = _mod(self.game, "Alpha")
        (alpha / "events" / "a.txt").write_bytes(b"a = 1\r\n")
        for root in (self.game / "mod", self.game, self.game / "common"):
            with self.subTest(root=root):
                with self.assertRaises(ValueError):
                    self.open(root)
        self.assertFalse((self.game / "mod.mod").exists())

    def test_from_descriptor_does_not_climb_out_of_mod(self):
        bad = self.game / "mod" / "Bad.mod"
        bad.write_bytes(b'name = "Bad"\r\npath = "mod/../common"\r\n')
        with self.assertRaises(ValueError):
            VirtualFS.from_descriptor(self.game, read_descriptor(bad))


class ForeignDescriptorTests(_Base):
    def layout(self):
        mod = _mod(self.game, "TestMod")
        (self.game / "mod" / "Archive" / "TestMod").mkdir(parents=True)
        (self.game / "mod" / "Archive.mod").write_bytes(
            b'name = "Copia vieja"\r\npath = "mod/Archive/TestMod"\r\nreplace_path = "history/provinces"\r\n')
        return mod

    def test_the_exact_descriptor_wins(self):
        mod = self.layout()
        self.assertEqual(find_descriptor(mod).file.name, "TestMod.mod")

    def test_editing_the_descriptor_never_writes_another_mod(self):
        mod = self.layout()
        archive = (self.game / "mod" / "Archive.mod").read_bytes()
        project = self.open(mod)
        self.assertFalse(project.vfs.guard.allows(self.game / "mod" / "Archive.mod"))
        self.assertEqual(project.descriptor.replace_paths, ())
        self.edit(project, DESCRIPTOR_REL, b'name = "Mi mod"\r\npath = "mod/TestMod"\r\n')
        self.assertTrue(project.save().ok)
        self.assertEqual((self.game / "mod" / "Archive.mod").read_bytes(), archive)
        self.assertEqual((self.game / "mod" / "TestMod.mod").read_bytes(), b'name = "Mi mod"\r\npath = "mod/TestMod"\r\n')


@unittest.skipUnless(hasattr(os, "symlink") and os.name != "nt", "enlaces simbólicos de POSIX")
class SymlinkTests(_Base):
    def test_saving_a_file_that_is_a_symlink_inside_the_mod(self):
        mod = _mod(self.game, "TestMod")
        (mod / "events" / "a.txt").write_bytes(b"a = 1\r\n")
        os.symlink("a.txt", mod / "events" / "b.txt")
        project = self.open(mod)
        self.edit(project, "events/b.txt", b"b = 2\r\n")
        report = project.save()
        self.assertTrue(report.ok, report.problems)
        self.assertTrue((mod / "events" / "b.txt").is_symlink(), "el enlace sigue siendo un enlace")
        self.assertEqual((mod / "events" / "a.txt").read_bytes(), b"b = 2\r\n")
        self.assertEqual(sorted(p.name for p in mod.rglob("*.tmp")), [], "sin temporales huérfanos")

    def test_saving_a_symlinked_descriptor(self):
        repo = self.base / "repo"
        (repo / "TestMod" / "events").mkdir(parents=True)
        (repo / "TestMod.mod").write_bytes(b'name = "TestMod"\r\npath = "mod/TestMod"\r\n')
        os.symlink(repo / "TestMod", self.game / "mod" / "TestMod")
        os.symlink(repo / "TestMod.mod", self.game / "mod" / "TestMod.mod")
        project = self.open(self.game / "mod" / "TestMod")
        self.edit(project, DESCRIPTOR_REL, b'name = "TestMod 2"\r\npath = "mod/TestMod"\r\n')
        report = project.save()
        self.assertTrue(report.ok, report.problems)
        self.assertTrue((self.game / "mod" / "TestMod.mod").is_symlink())
        self.assertEqual((repo / "TestMod.mod").read_bytes(), b'name = "TestMod 2"\r\npath = "mod/TestMod"\r\n')


CHILD = r'''
import os, sys
from pathlib import Path
from vic2studio.core.project import Project, journal
game, mod = Path(sys.argv[1]), Path(sys.argv[2])
p = Project.open(game, mod)
with p.edit("x"):
    for rel in ("events/a.txt", "events/b.txt"):
        p.ws.replace_text(p.ws.open(rel), b"cambiado = 1\r\n")
def hook(step, index):
    if step == "replace" and index == 0:
        os._exit(3)
journal.FAULT_HOOK = hook
p.save()
'''


class MovedModWithPendingJournalTests(_Base):
    def crashed_mod(self) -> Path:
        mod = _mod(self.game, "TestMod")
        (mod / "events" / "a.txt").write_bytes(b"a = 1\r\n")
        (mod / "events" / "b.txt").write_bytes(b"b = 1\r\n")
        env = {**os.environ, "PYTHONPATH": str(SRC)}
        result = subprocess.run([sys.executable, "-c", CHILD, str(self.game), str(mod)], env=env)
        self.assertEqual(result.returncode, 3)
        journal = next((mod / ".vic2studio" / "journal").glob("*.json"))
        self.assertEqual(json.loads(journal.read_text(encoding="utf-8"))["state"], "committing")
        return mod

    @staticmethod
    def tree(root: Path) -> dict:
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def test_a_copy_opens_and_the_original_is_untouched(self):
        mod = self.crashed_mod()
        copy = mod.with_name("TestMod2")
        shutil.copytree(mod, copy)
        before = self.tree(mod)
        project = self.open(copy)
        self.assertEqual([r.notes for r in project.recovered], [("project.recovery_foreign",)])
        self.assertEqual(self.tree(mod), before)

    def test_a_renamed_mod_opens_and_its_journal_is_kept(self):
        mod = self.crashed_mod()
        moved = mod.with_name("Renombrado")
        os.rename(mod, moved)
        project = self.open(moved)
        self.assertEqual([r.notes for r in project.recovered], [("project.recovery_foreign",)])
        self.assertEqual(len(list((moved / ".vic2studio" / "journal").glob("*.json"))), 1)

    def test_a_copy_can_still_be_saved(self):                              # segunda ronda (F4)
        # Su diario nombra la carpeta original: ningún guardado de la copia toca esas rutas, así que no lo bloquea.
        mod = self.crashed_mod()
        copy = mod.with_name("TestMod2")
        shutil.copytree(mod, copy)
        before = self.tree(mod)
        project = self.open(copy)
        with project.edit("y"):
            project.ws.replace_text(project.ws.open("events/a.txt"), b"a = 2\r\n")
        report = project.save()
        self.assertEqual([p.code for p in report.problems if p.blocking], [])
        self.assertIsNotNone(report.result)
        self.assertEqual((copy / "events" / "a.txt").read_bytes(), b"a = 2\r\n")
        self.assertEqual(self.tree(mod), before, "el guardado de la copia tocó el original")
        self.assertEqual(len(list((copy / ".vic2studio" / "journal").glob("*.json"))), 1, "el diario ajeno se queda")


class ArchDetectorHolesTests(unittest.TestCase):
    RAW = (
        "import os\nFLAGS = os.O_WRONLY | os.O_CREAT\nos.open(p, FLAGS)",
        "import os\nos.open(p, _TEMP_FLAGS, 0o666)",
        "import os\nos.open(p, flags=os.O_WRONLY | os.O_CREAT)",
        "import builtins\nbuiltins.open(p, 'w')",
        "from io import open as iopen\niopen(p, 'w')",
        "Path(p).touch(0o644)",
        "import gzip\ngzip.open(p, 'wb')",
        "import zipfile\nzipfile.ZipFile(p, 'w')",
        "import tarfile\ntarfile.open(p, 'w')",
        "import shutil\nshutil.unpack_archive(z, d)",
        "import os\nos.utime(p, None)",
        "import os\nos.chmod(p, 0o777)",
        "Path(p).chmod(0o777)",
        "import numpy as np\nnp.save(p, a)",
        "a.tofile(p)",
        "import logging\nlogging.FileHandler(p)",
    )
    READS = ("import os\nos.open(p, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))", "ws.touch(handle)",
             "import gzip\ngzip.open(p, 'rb')", "import zipfile\nzipfile.ZipFile(p)", "import os\nos.stat(p)")

    def test_detector_sees_every_raw_write(self):
        for code in self.RAW:
            with self.subTest(code=code):
                self.assertTrue(scan_source(textwrap.dedent(code), "core/x.py").raw)
        for code in self.READS:
            with self.subTest(code=code):
                self.assertEqual(scan_source(textwrap.dedent(code), "core/x.py").raw, [])

    def test_detector_sees_the_temp_creation_of_fileio(self):
        source = (SRC / "vic2studio" / "core" / "fileio.py").read_text(encoding="utf-8")
        lines = {line for line, _ in scan_source(source, "core/fileio.py").raw}
        flagged = [n for n, text in enumerate(source.splitlines(), 1) if "os.open(" in text and "_TEMP_FLAGS" in text]
        self.assertTrue(flagged)
        self.assertTrue(set(flagged) <= lines, f"líneas de os.open(_, _TEMP_FLAGS) sin ver: {set(flagged) - lines}")

    def test_detector_sees_fully_qualified_fileio_calls(self):
        code = "import vic2studio.core.fileio\nvic2studio.core.fileio.atomic_write_bytes(p, b'')"
        self.assertEqual([w for _, w, _ in scan_source(code, "core/x.py").writers], ["fileio.atomic_write_bytes"])


if __name__ == "__main__":
    unittest.main()
