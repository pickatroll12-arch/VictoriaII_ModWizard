"""Guardado multiarchivo con diario: pasos, copias, papelera y comprobaciones previas (wizard §6.5, I2, I9, D4)."""

import errno
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import build_layers  # noqa: E402
from vic2studio.core import fileio  # noqa: E402
from vic2studio.core.fileio import FileChangedError  # noqa: E402
from vic2studio.core.project import journal  # noqa: E402
from vic2studio.core.project.model import (  # noqa: E402
    SAVE_CASE_COLLISION,
    SAVE_CONFLICT,
    SAVE_NO_SPACE,
    SAVE_OUTSIDE_MOD,
    SAVE_PATH_TOO_LONG,
    SAVE_WINDOWS_NAME,
    PlannedWrite,
    WriteAction,
)
from vic2studio.core.vfs import DESCRIPTOR_REL, Fingerprint, VPath, WriteGuard  # noqa: E402

GAME = {"common/cb_types.txt": "cb = 1\r\n", "common/buildings.txt": "b = 1\r\n"}
MOD = {"common/countries.txt": "AAA = x\r\n", "events/old.txt": "old = yes\r\n"}


class JournalCommitTests(unittest.TestCase):
    def setUp(self):
        self.layers = build_layers(game=GAME, mod=MOD)
        self.addCleanup(self.layers.cleanup)
        self.mod = self.layers.mod_root
        self.guard = WriteGuard(self.mod, extra_files=[self.layers.descriptor])
        self.project = self.mod / journal.PROJECT_DIR
        self.journal_dir = self.project / journal.JOURNAL_DIR

    def write(self, rel, action, data, *, expected="auto", target=None):
        target = target or self.mod / rel
        if expected == "auto":
            expected = Fingerprint.of_path(target) if target.exists() else None
        return PlannedWrite(VPath.of(rel) if not isinstance(rel, VPath) else rel, target, action, data, expected)

    def transaction(self, *writes, backup_bak=True):
        transaction = journal.SaveTransaction(self.guard, self.journal_dir, label="save.label", backup_bak=backup_bak)
        for write in writes:
            transaction.add(write)
        return transaction

    def three_writes(self):
        return [self.write("common/countries.txt", WriteAction.MODIFY, b"AAA = y\r\n"),
                self.write("history/countries/AAA - Aland.txt", WriteAction.CREATE, b"capital = 1\r\n"),
                self.write("common/cb_types.txt", WriteAction.COPY_FROM_GAME, b"cb = 2\r\n")]

    def leftovers(self):
        return sorted(str(p.relative_to(self.mod)) for p in self.mod.rglob("*") if p.name.endswith(".tmp"))

    def test_commit_three_files(self):
        transaction = self.three_writes()
        transaction = self.transaction(*transaction)
        self.assertEqual(transaction.prepare(), [])
        result = transaction.commit()
        self.assertRegex(result.txid, r"^\d{8}T\d{6}-[0-9a-f]{6}$")
        self.assertEqual(result.written, ("common/countries.txt", "history/countries/AAA - Aland.txt",
                                          "common/cb_types.txt"))
        self.assertEqual(self.layers.mod("common/countries.txt").read_bytes(), b"AAA = y\r\n")
        self.assertEqual(self.layers.mod("history/countries/AAA - Aland.txt").read_bytes(), b"capital = 1\r\n")
        self.assertEqual(self.layers.mod("common/cb_types.txt").read_bytes(), b"cb = 2\r\n")
        # .bak solo de lo que existía, y originals/ con lo que había antes de la primera escritura.
        self.assertEqual(result.backups, (self.layers.mod("common/countries.txt.bak"),))
        self.assertEqual(self.layers.mod("common/countries.txt.bak").read_bytes(), b"AAA = x\r\n")
        self.assertEqual((self.project / "originals" / "common" / "countries.txt").read_bytes(), b"AAA = x\r\n")
        self.assertFalse(self.journal_dir.exists(), "el diario se borra y journal/ también")
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(self.layers.game("common/cb_types.txt").read_bytes(), b"cb = 1\r\n")

    def test_second_save_moves_the_bak_but_never_the_original(self):
        self.transaction(self.write("common/countries.txt", WriteAction.MODIFY, b"v2\r\n")).commit()
        self.transaction(self.write("common/countries.txt", WriteAction.MODIFY, b"v3\r\n")).commit()
        self.assertEqual(self.layers.mod("common/countries.txt").read_bytes(), b"v3\r\n")
        self.assertEqual(self.layers.mod("common/countries.txt.bak").read_bytes(), b"v2\r\n")
        self.assertEqual((self.project / "originals" / "common" / "countries.txt").read_bytes(), b"AAA = x\r\n")

    def test_without_bak_the_rollback_copy_is_private(self):
        transaction = self.transaction(self.write("common/countries.txt", WriteAction.MODIFY, b"v2\r\n"),
                                       backup_bak=False)
        result = transaction.commit()
        self.assertEqual(result.backups, ())
        self.assertFalse(self.layers.mod("common/countries.txt.bak").exists())
        self.assertEqual(sorted(p.name for p in self.project.iterdir()), ["originals"])

    def test_creating_only_new_files_leaves_no_project_folder(self):
        """Criterio 3: copiar del juego crea solo el archivo (ni .vic2studio/ ni .bak)."""
        before = set(self.layers.tree())
        self.transaction(self.write("common/cb_types.txt", WriteAction.COPY_FROM_GAME, b"cb = 2\r\n")).commit()
        self.assertEqual(set(self.layers.tree()) - before, {"common/cb_types.txt"})
        self.assertFalse(self.project.exists())

    def test_trash(self):
        transaction = self.transaction(self.write("events/old.txt", WriteAction.TRASH, None))
        result = transaction.commit()
        self.assertEqual(result.trashed, ("events/old.txt",))
        self.assertFalse(self.layers.mod("events/old.txt").exists())
        trashed = self.project / "trash" / result.txid / "events" / "old.txt"
        self.assertEqual(trashed.read_bytes(), b"old = yes\r\n")
        self.assertFalse((self.project / "originals" / "events" / "old.txt").exists(),
                         "la papelera ya lo guarda entero: originals/ sería una segunda copia (revisión it3)")
        self.assertEqual(journal.trash_file(self.guard, self.project / "trash", "manual",
                                            VPath.of("common/countries.txt"), self.layers.mod("common/countries.txt")),
                         self.project / "trash" / "manual" / "common" / "countries.txt")

    def test_descriptor_is_saved_next_to_the_mod(self):
        descriptor = self.layers.descriptor
        original = descriptor.read_bytes()
        self.transaction(self.write(DESCRIPTOR_REL, WriteAction.MODIFY, b'name = "Otro"\r\n',
                                    target=descriptor)).commit()
        self.assertEqual(descriptor.read_bytes(), b'name = "Otro"\r\n')
        self.assertEqual(descriptor.with_name("TestMod.mod.bak").read_bytes(), original)
        self.assertEqual((self.project / "originals" / "@descriptor.mod").read_bytes(), original)
        self.assertEqual(sorted(p.name for p in descriptor.parent.iterdir() if p.name.endswith(".tmp")), [])

    def test_folders_of_a_new_skeleton(self):
        transaction = self.transaction(self.write("common/new.txt", WriteAction.CREATE, b"x\r\n"))
        for folder in ("history", "localisation"):
            transaction.add_folder(self.mod / folder)
        transaction.commit()
        self.assertTrue(self.layers.mod("history").is_dir())
        self.assertTrue(self.layers.mod("localisation").is_dir())

    def test_add_validates(self):
        transaction = self.transaction()
        with self.assertRaises(ValueError):
            transaction.add(self.write("events/old.txt", WriteAction.TRASH, b"x"))
        with self.assertRaises(ValueError):
            transaction.add(self.write("events/new.txt", WriteAction.CREATE, None))
        transaction.add(self.write("events/new.txt", WriteAction.CREATE, b"x"))
        with self.assertRaises(ValueError):
            transaction.add(self.write("events/new.txt", WriteAction.CREATE, b"y"))

    def test_prepare_reports_blocking_problems_first_without_writing(self):
        tree = self.layers.tree()
        writes = [
            self.write("common/countries.txt", WriteAction.MODIFY, b"x", expected=Fingerprint(1, 1, "0" * 64)),
            self.write("events/old.txt", WriteAction.CREATE, b"x", expected=None),
            self.write("events/CON.txt", WriteAction.CREATE, b"x"),
            self.write("events/Case.txt", WriteAction.CREATE, b"x"),
            self.write("events/CASE.txt", WriteAction.CREATE, b"x"),
            self.write("events/" + "d" * 120 + "/" + "n" * 120 + ".txt", WriteAction.CREATE, b"x"),
            PlannedWrite(VPath.of("common/cb_types.txt"), self.layers.game("common/cb_types.txt"),
                         WriteAction.MODIFY, b"x", None),
        ]
        problems = self.transaction(*writes).prepare()
        codes = [(p.code, str(p.rel)) for p in problems]
        self.assertIn((SAVE_CONFLICT, "common/countries.txt"), codes)
        self.assertIn((SAVE_CONFLICT, "events/old.txt"), codes, "CREATE sobre un archivo que ya existe")
        self.assertIn((SAVE_WINDOWS_NAME, "events/CON.txt"), codes)
        self.assertIn((SAVE_CASE_COLLISION, "events/CASE.txt"), codes)
        self.assertIn((SAVE_OUTSIDE_MOD, "common/cb_types.txt"), codes)
        long = [p for p in problems if p.code == SAVE_PATH_TOO_LONG]
        self.assertEqual(len(long), 1)
        self.assertFalse(long[0].blocking)
        self.assertEqual(problems[-1].code, SAVE_PATH_TOO_LONG, "los bloqueantes van primero")
        for problem in problems:
            self.assertTrue(problem.message("es"))
        self.assertEqual(self.layers.tree(), tree)

    def test_prepare_sees_a_case_twin_on_disk(self):
        twin = self.mod / "events" / "OLD.txt"
        twin.write_bytes(b"x")
        if twin.samefile(self.mod / "events" / "old.txt"):
            self.skipTest("sistema de archivos sin mayúsculas")
        problems = self.transaction(self.write("events/old.txt", WriteAction.MODIFY, b"y")).prepare()
        self.assertEqual([p.code for p in problems], [SAVE_CASE_COLLISION])

    def test_prepare_checks_free_space(self):
        fake = mock.Mock(return_value=mock.Mock(total=10, used=5, free=5))
        with mock.patch.object(journal.shutil, "disk_usage", fake):
            problems = self.transaction(self.write("events/new.txt", WriteAction.CREATE, b"x" * 100)).prepare()
        self.assertEqual([p.code for p in problems], [SAVE_NO_SPACE])
        self.assertTrue(problems[0].blocking)

    def test_unchanged_stat_or_same_content_is_not_a_conflict(self):
        target = self.layers.mod("common/countries.txt")
        expected = Fingerprint.of_path(target, with_hash=True)
        os.utime(target, ns=(1, 1))   # otro programa lo tocó sin cambiarlo
        problems = self.transaction(self.write("common/countries.txt", WriteAction.MODIFY, b"y",
                                               expected=expected)).prepare()
        self.assertEqual(problems, [])
        target.write_bytes(b"AAA = z\r\n")
        os.utime(target, ns=(1, 1))
        problems = self.transaction(self.write("common/countries.txt", WriteAction.MODIFY, b"y",
                                               expected=expected)).prepare()
        self.assertEqual([p.code for p in problems], [SAVE_CONFLICT])

    def test_commit_rechecks_external_changes(self):
        transaction = self.transaction(*self.three_writes())
        self.assertEqual(transaction.prepare(), [])
        self.layers.mod("common/countries.txt").write_bytes(b"cambiado en Notepad++ entre medias\r\n")
        tree = self.layers.tree()
        with self.assertRaises(FileChangedError):
            transaction.commit()
        self.assertEqual(self.layers.tree(), tree)
        self.assertFalse(self.project.exists())

    def test_transient_permission_errors_are_retried(self):
        real = os.replace
        failures = {"left": 2}

        def flaky(src, dst):
            if dst == os.fspath(self.layers.mod("common/cb_types.txt")) and failures["left"]:
                failures["left"] -= 1
                raise PermissionError(errno.EACCES, "antivirus")
            return real(src, dst)

        with mock.patch.object(fileio.os, "replace", flaky), mock.patch.object(fileio.time, "sleep"):
            self.transaction(*self.three_writes()).commit()
        self.assertEqual(failures["left"], 0)
        self.assertEqual(self.layers.mod("common/cb_types.txt").read_bytes(), b"cb = 2\r\n")

    def test_permission_error_on_the_third_replace_rolls_back(self):
        """I2: un PermissionError que no se va en el tercer os.replace deja todo como antes (en el proceso)."""
        before = self.layers.tree()
        real = os.replace
        third = os.fspath(self.layers.mod("common/cb_types.txt"))

        def locked(src, dst):
            if os.fspath(dst) == third and re.search(r"\.tmp$", os.fspath(src)):
                raise PermissionError(errno.EACCES, "abierto en otro programa")
            return real(src, dst)

        transaction = self.transaction(*self.three_writes())
        with mock.patch.object(fileio.os, "replace", locked), mock.patch.object(fileio.time, "sleep"):
            with self.assertRaises(PermissionError):
                transaction.commit()
        after = self.layers.tree()
        for rel in ("common/countries.txt", "events/old.txt"):
            self.assertEqual(after[rel][2], before[rel][2])
        self.assertNotIn("common/cb_types.txt", after)
        self.assertNotIn("history/countries/AAA - Aland.txt", after)
        self.assertFalse(self.layers.mod("history").exists(), "las carpetas que creó el guardado se quitan")
        trashed = self.project / "trash" / transaction.txid / "history" / "countries" / "AAA - Aland.txt"
        self.assertEqual(trashed.read_bytes(), b"capital = 1\r\n", "el CREATE ya confirmado va a la papelera")
        self.assertEqual(self.leftovers(), [])
        self.assertFalse(self.journal_dir.exists())


class NewModTests(unittest.TestCase):
    """«Nuevo mod» (create_mod_skeleton, agente B): carpeta, esqueleto y .mod en una sola transacción."""

    def setUp(self):
        self.layers = build_layers(game=GAME, mod={}, mod_name="Existing")
        self.addCleanup(self.layers.cleanup)
        self.mods = self.layers.game_root / "mod"
        self.root = self.mods / "NewMod"
        self.descriptor = self.mods / "NewMod.mod"
        self.guard = WriteGuard(self.root, extra_files=[self.descriptor])
        self.before = sorted(p.name for p in self.mods.iterdir())

    def transaction(self, **kwargs):
        transaction = journal.SaveTransaction(self.guard, self.root / ".vic2studio" / "journal", label="new_mod",
                                              **kwargs)
        transaction.add(PlannedWrite(DESCRIPTOR_REL, self.descriptor, WriteAction.CREATE,
                                     b'name = "New"\r\npath = "mod/NewMod"\r\n', None))
        transaction.add(PlannedWrite(VPath.of("localisation/00_NEW.csv"), self.root / "localisation" / "00_NEW.csv",
                                     WriteAction.CREATE, b"k;v;;;;;;;;;;;;x\r\n", None))
        for folder in ("common", "history", "localisation"):
            transaction.add_folder(self.root / folder)
        return transaction

    def test_create(self):
        transaction = self.transaction(trash_creates=False)
        self.assertEqual(transaction.prepare(), [])
        transaction.commit()
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["common", "history", "localisation"])
        self.assertTrue(self.descriptor.is_file())
        self.assertEqual(sorted(p.name for p in self.mods.iterdir()), sorted(self.before + ["NewMod", "NewMod.mod"]))

    def test_failure_leaves_no_trace(self):
        real = os.replace
        csv = os.fspath(self.root / "localisation" / "00_NEW.csv")

        def locked(src, dst):
            if os.fspath(dst) == csv:
                raise PermissionError(errno.EACCES, "en uso")
            return real(src, dst)

        with mock.patch.object(fileio.os, "replace", locked), mock.patch.object(fileio.time, "sleep"):
            with self.assertRaises(PermissionError):
                self.transaction(trash_creates=False).commit()
        self.assertEqual(sorted(p.name for p in self.mods.iterdir()), self.before, "ni carpeta, ni .mod, ni temporales")

    def test_crash_then_recover(self):
        from test_journal_crash import PowerCut, SimulatedFault
        from vic2studio.core.project.recovery import recover_all
        from contextlib import ExitStack

        for point, created in ((("journal_prepared", 0), False), (("replace", 0), True)):
            with self.subTest(point=point):
                cut = PowerCut(point)
                with ExitStack() as stack:
                    cut.patches(stack)
                    with self.assertRaises(SimulatedFault):
                        self.transaction(trash_creates=False).commit()
                recover_all(self.root / ".vic2studio" / "journal", self.guard)
                if created:
                    self.assertTrue(self.descriptor.is_file())
                    self.assertTrue((self.root / "localisation" / "00_NEW.csv").is_file())
                    self.assertFalse((self.root / ".vic2studio").exists())
                else:
                    self.assertEqual(sorted(p.name for p in self.mods.iterdir()), self.before)


if __name__ == "__main__":
    unittest.main()
