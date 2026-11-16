"""Exportar el mod a un zip limpio (``core/export.py``, criterio 4 de la iteración 10).

El juego y el mod son carpetas inventadas en un temporal: nada de Paradox."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vic2studio.core import export  # noqa: E402


def _write(path: Path, data: bytes = b"x = 1\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class ExportFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.game = base / "game"
        self.out = base / "out"
        _write(self.game / "common" / "defines.txt", b"start = 1836\n")
        _write(self.game / "history" / "provinces" / "a" / "1 - Uno.txt", b"owner = AAA\n")
        _write(self.game / "Localisation" / "text.csv", b"KEY;Texto;\n")
        self.mod = self.game / "mod" / "Prueba"
        self.descriptor = _write(self.game / "mod" / "Prueba.mod",
                                 b'name = "Prueba"\npath = "mod/Prueba"\nreplace_path = "history/provinces"\n')
        _write(self.mod / "common" / "countries.txt", b"AAA = \"countries/A.txt\"\n")
        _write(self.mod / "common" / "defines.txt", b"start = 1836\n")                      # idéntico al juego
        _write(self.mod / "localisation" / "text.csv", b"KEY;Texto;\n")                    # idéntico, otra caja
        _write(self.mod / "history" / "provinces" / "a" / "1 - Uno.txt", b"owner = AAA\n")  # idéntico, reemplazado
        _write(self.mod / "common" / "countries.txt.bak", b"viejo\n")
        _write(self.mod / "common" / ".countries.txt.0a1b2c3d.tmp", b"a medias\n")
        _write(self.mod / ".vic2studio" / "project.json", b"{}\n")
        _write(self.mod / ".vic2studio" / "trash" / "x.txt", b"x\n")
        _write(self.mod / "gfx" / "flags" / "Thumbs.db", b"\0")
        _write(self.mod / ".git" / "HEAD", b"ref\n")
        _write(self.mod / "events" / "~$borrador.txt", b"lock\n")

    def tearDown(self):
        self._tmp.cleanup()

    def plan(self, **kw):
        return export.plan_zip(self.mod, descriptor=self.descriptor, game_root=self.game,
                               replace_paths=("history/provinces",), **kw)


class PlanTests(ExportFixture):
    def test_the_plan_leaves_the_studio_backups_and_temporaries_out(self):
        plan = self.plan()
        names = [m.arcname for m in plan.members]
        self.assertEqual(names[0], "Prueba.mod", "el descriptor va en la raíz")
        self.assertIn("Prueba/common/countries.txt", names)
        self.assertIn("Prueba/common/defines.txt", names, "sin limpieza, las copias idénticas se quedan")
        for name in names:
            self.assertNotIn(".vic2studio", name)
            self.assertFalse(name.endswith((".bak", ".tmp")), name)
            self.assertNotIn(".git/", name)
            self.assertNotIn("Thumbs.db", name)
            self.assertNotIn("~$", name)
        self.assertEqual(plan.counts(), {"studio": 2, "backup": 1, "temp": 2, "system": 1, "vcs": 1})

    def test_pruning_drops_identical_copies_but_not_in_replaced_folders(self):
        plan = self.plan(prune_identical=True)
        names = {m.arcname for m in plan.members}
        self.assertNotIn("Prueba/common/defines.txt", names)
        self.assertNotIn("Prueba/localisation/text.csv", names, "el juego no distingue mayúsculas")
        self.assertIn("Prueba/history/provinces/a/1 - Uno.txt", names,
                      "en una carpeta de replace_path la copia es la única que el juego ve")
        self.assertEqual(sorted(s.rel for s in plan.skipped_by("identical")),
                         ["common/defines.txt", "localisation/text.csv"])

    def test_a_descriptor_inside_the_folder_travels_with_it(self):
        inside = _write(self.mod / "descriptor.mod", b'name = "Prueba"\n')
        plan = export.plan_zip(self.mod, descriptor=inside)
        self.assertIsNone(plan.descriptor)
        self.assertIn("Prueba/descriptor.mod", [m.arcname for m in plan.members])
        self.assertFalse(any(m.arcname.endswith(".mod") and "/" not in m.arcname for m in plan.members))

    @unittest.skipIf(os.name == "nt", "los enlaces simbólicos piden permisos en Windows")
    def test_symlinks_are_not_followed(self):
        os.symlink(self.game / "common", self.mod / "enlace")
        plan = self.plan()
        self.assertFalse(any("enlace" in m.arcname for m in plan.members))
        self.assertEqual([s.rel for s in plan.skipped_by("link")], ["enlace"])

    def test_skip_reason(self):
        self.assertEqual(export.skip_reason((".VIC2STUDIO", "a")), "studio")
        self.assertEqual(export.skip_reason(("a", "b.txt~")), "temp")
        self.assertEqual(export.skip_reason(("a", "._b.txt")), "system")
        self.assertIsNone(export.skip_reason(("common", "bak.txt")))


class WriteTests(ExportFixture):
    def test_the_zip_has_exactly_the_planned_files_with_their_bytes(self):
        plan = self.plan(prune_identical=True)
        result = export.write_zip_export(plan, self.out / "Prueba.zip", game_root=self.game)
        with zipfile.ZipFile(result.path) as zf:
            self.assertEqual(zf.namelist(), [m.arcname for m in plan.members])
            self.assertIsNone(zf.testzip())
            self.assertEqual(zf.read("Prueba/common/countries.txt"), b"AAA = \"countries/A.txt\"\n")
            self.assertEqual(zf.read("Prueba.mod"), self.descriptor.read_bytes())
        self.assertEqual(result.files, len(plan.members))
        self.assertEqual(result.bytes_out, result.path.stat().st_size)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["Prueba.zip"], "sin temporales")

    def test_errors_block_the_export_and_write_nothing(self):
        with self.assertRaises(export.ExportBlocked) as caught:
            export.write_zip_export(self.plan(), self.out / "Prueba.zip", errors=3)
        self.assertEqual(caught.exception.count, 3)
        self.assertFalse(self.out.exists())

    def test_the_destination_cannot_be_in_the_mod_or_the_game(self):
        plan = self.plan()
        cases = {self.mod / "Prueba.zip": "dest_inside_mod", self.game / "Prueba.zip": "dest_inside_game",
                 self.out / "Prueba.rar": "dest_not_zip"}
        for dest, code in cases.items():
            with self.subTest(dest=dest):
                with self.assertRaises(export.ExportDestinationError) as caught:
                    export.write_zip_export(plan, dest, game_root=self.game)
                self.assertEqual(caught.exception.code, code)
                self.assertFalse(dest.exists())

    def test_cancelling_leaves_no_partial_zip(self):
        plan = self.plan()
        calls = []

        def cancelled():
            calls.append(1)
            return len(calls) > 2

        target = self.out / "Prueba.zip"
        _write(target, b"zip anterior")
        with self.assertRaises(InterruptedError):
            export.write_zip_export(plan, target, cancelled=cancelled)
        self.assertEqual(target.read_bytes(), b"zip anterior", "el zip anterior sigue intacto")
        self.assertEqual([p.name for p in self.out.iterdir()], ["Prueba.zip"])

    def test_default_name_is_safe(self):
        plan = self.plan()
        self.assertEqual(export.default_zip_name(plan, "1.0 beta"), "Prueba_1.0_beta.zip")


if __name__ == "__main__":
    unittest.main()
