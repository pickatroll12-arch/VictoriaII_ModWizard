"""Regresiones de la revisión adversarial del diario y la recuperación (iteración 2, hallazgos R1–R10).

Cada prueba reproduce un hallazgo confirmado: un guardado o una recuperación que mezclaba estados, perdía la
``.bak`` anterior, dejaba restos o no se podía repetir tras un corte. ``_diskfull`` simula el disco lleno.
"""
import errno
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))

import _diskfull  # noqa: E402
from _layers import build_layers, isolate_appdirs  # noqa: E402
from vic2studio.core import fileio  # noqa: E402
from vic2studio.core.modfile import DescriptorSpec, create_mod_skeleton  # noqa: E402
from vic2studio.core.project import Project, journal  # noqa: E402
from vic2studio.core.project.model import PlannedWrite, WriteAction  # noqa: E402
from vic2studio.core.project.recovery import (  # noqa: E402
    NOTE_INCOMPLETE, NOTE_UNREADABLE, OUTCOME_NOTHING, load_session, pending_journals, recover)
from vic2studio.core.vfs import Fingerprint, VPath, WriteGuard  # noqa: E402



def setUpModule():
    # Los fallos inyectados registran excepciones a propósito; solo mientras dura este módulo (apagarlo al
    # importar silenciaría también los avisos que comprueban otras pruebas con assertLogs).
    logging.disable(logging.CRITICAL)


def tearDownModule():
    logging.disable(logging.NOTSET)
A, B, T, N = "common/a.txt", "common/b.txt", "events/t.txt", "history/new0/sub/n.txt"


def child(code: str, env=None) -> int:
    prelude = f"import os, sys; sys.path[:0] = [{str(CODE / 'src')!r}]\nfrom pathlib import Path\n"
    return subprocess.run([sys.executable, "-c", prelude + code], env=env or os.environ).returncode


class Base(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def layers(self, mod):
        layers = build_layers(game={"common/g.txt": "g = 1\r\n"}, mod=mod)
        self.addCleanup(layers.cleanup)
        return layers

    @staticmethod
    def disk(mod, rels):
        return {r: ((mod / r).read_bytes() if (mod / r).exists() else None) for r in rels}

    def failed_save_on_full_disk(self, ws):
        """El disco se llena tras el primer reemplazo de un guardado con MODIFY y TRASH."""
        with _diskfull.patched() as state:
            journal.FAULT_HOOK = lambda s, i: state.__setitem__("full", True) if (s, i) == ("replace", 0) else None
            try:
                return ws.save()
            finally:
                journal.FAULT_HOOK = None
                state["full"] = False


class StaleJournalTests(Base):
    MOD = {A: "a = 1\r\n", B: "b = 1\r\n", T: "t = 1\r\n"}

    def edit_three(self, ws):
        with ws.transaction("x"):
            ws.replace_text(ws.open(A), b"a = 2\r\n")
            ws.replace_text(ws.open(B), b"b = 2\r\n")
            ws.delete(T)

    def test_reopening_keeps_what_the_later_save_wrote(self):          # R1
        layers = self.layers(self.MOD)
        project = Project.open(layers.game_root, layers.mod_root)
        ws = project.ws
        self.edit_three(ws)
        self.failed_save_on_full_disk(ws)
        for change in ws.check_external_changes():
            ws.accept_external(change.rel)       # «Conservar mis cambios»
        with ws.transaction("y"):
            ws.replace_text(ws.open(A), b"a = 3\r\n")
        ws.save()
        saved = self.disk(layers.mod_root, (A, B, T))
        project.close()
        reopened = Project.open(layers.game_root, layers.mod_root)
        self.addCleanup(reopened.close)
        self.assertEqual(self.disk(layers.mod_root, (A, B, T)), saved, "reabrir pisó lo que había en disco")
        self.assertEqual(pending_journals(layers.mod_root / ".vic2studio" / "journal"), [])

    def test_a_later_save_does_not_stack_on_a_pending_journal(self):      # R1 (2), sin depender del disco lleno
        from vic2studio.core.project import recovery
        layers = self.layers(self.MOD)
        project = Project.open(layers.game_root, layers.mod_root)
        ws = project.ws
        self.edit_three(ws)

        def hook(step, index):
            if (step, index) == ("replace", 0):
                raise PermissionError(errno.EACCES, "abierto en otro programa")
        journal.FAULT_HOOK = hook
        try:
            # Falla la confirmación, la reversión y la recuperación inmediata: el diario queda en «committing».
            with mock.patch.object(journal.SaveTransaction, "_rollback", lambda *a: None), \
                    mock.patch.object(recovery, "recover", side_effect=OSError(errno.EACCES, "bloqueado")):
                ws.save()
        finally:
            journal.FAULT_HOOK = None
        self.assertEqual([j.state for j in pending_journals(layers.mod_root / ".vic2studio" / "journal")],
                         ["committing"])
        for change in ws.check_external_changes():
            ws.accept_external(change.rel)
        with ws.transaction("y"):
            ws.replace_text(ws.open(A), b"a = 3\r\n")
        ws.save()
        saved = self.disk(layers.mod_root, (A, B, T))
        project.close()
        reopened = Project.open(layers.game_root, layers.mod_root)
        self.addCleanup(reopened.close)
        self.assertEqual(self.disk(layers.mod_root, (A, B, T)), saved, "reabrir pisó lo que había en disco")

    def test_a_save_on_an_unresolvable_journal_says_why(self):          # R1 (3)
        """Si el diario pendiente sigue sin resolverse, el guardado no escribe nada y lo dice con su propio
        problema (``save_journal_pending``, que nombra el diario), no con un «guardado fallido» genérico."""
        from vic2studio.core.project import recovery
        layers = self.layers(self.MOD)
        project = Project.open(layers.game_root, layers.mod_root)
        self.addCleanup(project.close, discard=True)
        ws = project.ws
        self.edit_three(ws)

        def hook(step, index):
            if (step, index) == ("replace", 0):
                raise PermissionError(errno.EACCES, "abierto en otro programa")
        journal.FAULT_HOOK = hook
        try:
            with mock.patch.object(journal.SaveTransaction, "_rollback", lambda *a: None), \
                    mock.patch.object(recovery, "recover", side_effect=OSError(errno.EACCES, "bloqueado")):
                ws.save()
        finally:
            journal.FAULT_HOOK = None
        before = self.disk(layers.mod_root, (A, B, T))
        with mock.patch.object(recovery, "recover", side_effect=OSError(errno.EACCES, "bloqueado")):
            report = ws.save()
        self.assertEqual([p.code for p in report.problems], ["save_journal_pending"])
        self.assertIn(".vic2studio", report.problems[0].message("es"))
        self.assertIn("could not be resolved", report.problems[0].message("en"))
        self.assertEqual(self.disk(layers.mod_root, (A, B, T)), before, "no se escribe nada encima")

    def test_disk_full_during_commit_does_not_leave_the_mod_mixed(self):   # R2
        layers = self.layers(self.MOD)
        project = Project.open(layers.game_root, layers.mod_root)
        self.addCleanup(project.close)
        self.edit_three(project.ws)
        self.failed_save_on_full_disk(project.ws)
        before = {A: b"a = 1\r\n", B: b"b = 1\r\n", T: b"t = 1\r\n"}
        after = {A: b"a = 2\r\n", B: b"b = 2\r\n", T: None}
        self.assertIn(self.disk(layers.mod_root, (A, B, T)), (before, after), "mezcla con el disco lleno")


class IncompleteRecoveryTests(Base):
    def test_incomplete_recovery_writes_nothing(self):                    # R1 (1)
        layers = self.layers({A: "a = 1\r\n", "common/c.txt": "c = 1\r\n", B: "b = 1\r\n"})
        mod = layers.mod_root
        guard = WriteGuard(mod)
        jdir = mod / ".vic2studio" / "journal"
        tx = journal.SaveTransaction(guard, jdir, label="t")
        for rel, data in ((A, b"a = 2\r\n"), ("common/c.txt", b"c = 2\r\n"), (B, b"b = 2\r\n")):
            tx.add(PlannedWrite(VPath.of(rel), mod / rel, WriteAction.MODIFY, data, Fingerprint.of_path(mod / rel)))

        class Death(BaseException):
            pass

        def hook(step, index):
            if (step, index) == ("replace", 1):
                raise Death()
        journal.FAULT_HOOK = hook
        try:
            with mock.patch.object(journal.SaveTransaction, "_rollback", lambda *a: None), self.assertRaises(Death):
                tx.commit()
        finally:
            journal.FAULT_HOOK = None
        record = json.loads(tx.journal_path.read_text())
        Path(record["files"][2]["temp"]).unlink()                  # b: ni temporal (no puede avanzar)
        Path(record["files"][0]["bak"]).write_bytes(b"otra\r\n")    # a: ni .bak buena (no puede retroceder)
        result = recover(jdir, guard, tx.txid)
        self.assertEqual(self.disk(mod, (A, "common/c.txt", B)),
                         {A: b"a = 2\r\n", "common/c.txt": b"c = 2\r\n", B: b"b = 1\r\n"}, "no debe escribir nada")
        self.assertEqual((result.outcome, result.notes), (OUTCOME_NOTHING, (NOTE_INCOMPLETE,)))


class AutosaveCutTests(Base):
    def first(self):
        mod = Path(tempfile.mkdtemp()) / "Mod"
        mod.mkdir()
        guard, root = WriteGuard(mod), mod / ".vic2studio" / "recovery"
        journal.write_recovery(guard, root, "S", {VPath.of(A): b"a v1", VPath.of("common/c.txt"): b"c v1"})
        return mod, guard, root

    NEW = {VPath.of(A): b"a v2", VPath.of(B): b"b v1", VPath.of("common/c.txt"): b"c v2"}

    def test_disk_full_mid_autosave(self):                                # R3
        mod, guard, root = self.first()
        before = load_session(root, "S")
        real, calls = fileio.atomic_write_bytes, []

        def flaky(path, data, **kw):
            calls.append(path)
            if len(calls) == 2:
                raise OSError(errno.ENOSPC, "No space left on device")
            return real(path, data, **kw)
        with mock.patch.object(fileio, "atomic_write_bytes", flaky), self.assertRaises(OSError):
            journal.write_recovery(guard, root, "S", self.NEW)
        self.assertEqual(load_session(root, "S"), before, "el autoguardado anterior debe seguir entero")

    def test_killed_mid_autosave(self):                                   # R3
        for k in (1, 2):
            mod, guard, root = self.first()
            before = load_session(root, "S")
            rc = child(f"""
from vic2studio.core import fileio
from vic2studio.core.project import journal
from vic2studio.core.vfs import VPath, WriteGuard
real, n = fileio.atomic_write_bytes, [0]
def w(p, d, **kw):
    real(p, d, **kw); n[0] += 1
    if n[0] == {k}: os._exit(9)
fileio.atomic_write_bytes = w
journal.write_recovery(WriteGuard(Path({str(mod)!r})), Path({str(root)!r}), "S",
    {{VPath.of("common/a.txt"): b"a v2", VPath.of("common/b.txt"): b"b v1", VPath.of("common/c.txt"): b"c v2"}})
""")
            self.assertEqual(rc, 9)
            self.assertEqual(load_session(root, "S"), before, f"muere tras {k} archivo(s)")


class RecoveryDialogTests(Base):
    def test_dialog_explains_incomplete_and_unreadable_journals(self):    # R4
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication, QLabel
        app = QApplication.instance() or QApplication([])  # noqa: F841
        from vic2studio.core.project.model import RecoveryResult
        from vic2studio.i18n import set_language, tr
        from vic2studio.ui.dialogs.recovery import RecoveryDialog
        for lang in ("es", "en"):
            set_language(lang)
            dialog = RecoveryDialog([], [RecoveryResult("T1", "rolled_back", (VPath.of(B),), (), (NOTE_INCOMPLETE,)),
                                         RecoveryResult("T2", "nothing", notes=(NOTE_UNREADABLE,))])
            texts = " | ".join(w.text() for w in dialog.findChildren(QLabel))
            self.assertIn(tr(NOTE_INCOMPLETE), texts)
            self.assertIn(tr(NOTE_UNREADABLE), texts)
            self.assertEqual([b.level for b in dialog.recovered_badges], ["error", "error"])
            dialog.deleteLater()


class OpenWithBadJournalTests(Base):
    def test_structurally_invalid_journal_does_not_block_opening(self):  # R5
        layers = self.layers({A: "a = 1\r\n"})
        jdir = layers.mod_root / ".vic2studio" / "journal"
        jdir.mkdir(parents=True)
        (jdir / "20260101T000000-abcdef.json").write_text(json.dumps(
            {"format": 1, "txid": "20260101T000000-abcdef", "state": "committing", "files": [{"rel": A}]}))
        project = Project.open(layers.game_root, layers.mod_root)
        self.addCleanup(project.close)
        self.assertEqual([r.notes for r in project.recovered], [(NOTE_UNREADABLE,)])
        self.assertTrue((jdir / "20260101T000000-abcdef.json").exists(), "se conserva para revisarlo")


class NewModRecoveryTests(Base):
    def game(self):
        game = Path(tempfile.mkdtemp()) / "Victoria 2"
        (game / "mod").mkdir(parents=True)
        return game

    def crash_new_mod(self, game, step):
        rc = child(f"""
from vic2studio.core.modfile import DescriptorSpec, create_mod_skeleton
from vic2studio.core.project import journal
journal.FAULT_HOOK = lambda s, i: os._exit(9) if s == {step!r} else None
create_mod_skeleton(Path({str(game)!r}), DescriptorSpec("New", "NEW"))
""")
        self.assertEqual(rc, 9)

    def test_rolling_forward_creates_the_empty_skeleton_folders(self):    # R6
        game = self.game()
        self.crash_new_mod(game, "journal_backed_up")
        project = Project.open(game, game / "mod" / "NEW")
        self.addCleanup(project.close)
        self.assertTrue((game / "mod" / "NEW.mod").exists())
        for name in ("common", "history", "localisation"):
            self.assertTrue((game / "mod" / "NEW" / name).is_dir(), name)

    def test_new_mod_can_be_created_again_after_an_early_crash(self):     # R7
        game = self.game()
        self.crash_new_mod(game, "stage")
        create_mod_skeleton(game, DescriptorSpec("New", "NEW"))
        self.assertEqual([p.name for p in (game / "mod").iterdir() if p.name.endswith(".tmp")], [])


    def test_new_mod_dialog_allows_the_same_folder_after_an_early_crash(self):   # R7 (interfaz)
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])  # noqa: F841
        from vic2studio.ui.dialogs.new_mod import NewModDialog
        from vic2studio.ui.session import Session
        layers = build_layers(game={"common/countries.txt": "A = x\r\n"}, mod={"common/x.txt": "x = 1\r\n"},
                              mod_name="DAM")
        self.addCleanup(layers.cleanup)
        self.crash_new_mod(layers.game_root, "stage")
        dialog = NewModDialog(Session(), layers.game_root)
        self.addCleanup(dialog.deleteLater)
        dialog.name_edit.setText("New")
        dialog.folder_combo.setEditText("NEW")
        dialog.refresh()
        self.assertEqual([i.code for i in dialog.issues], [])
        self.assertTrue(dialog.create_button.isEnabled())


class LeftoverTests(Base):
    def run_save(self, layers, patch):
        return child(f"""
import shutil
from vic2studio.core import fileio
from vic2studio.core.project import Project, journal
p = Project.open(Path({str(layers.game_root)!r}), Path({str(layers.mod_root)!r}))
with p.ws.transaction("x"):
    p.ws.replace_text(p.ws.open("common/a.txt"), b"a = 2\\r\\n")
    h = p.ws.create({N!r}, p.ws.open("common/a.txt").kind); p.ws.replace_text(h, b"n = 1\\r\\n")
{patch}
p.ws.save()
""")

    def test_kill_while_copying_the_bak_leaves_no_temporary(self):        # R8
        layers = self.layers({A: "a = 1\r\n"})
        rc = self.run_save(layers, "real = shutil.copy2\n"
                                   "def die(s, d, **k):\n    real(s, d, **k); os._exit(9)\n"
                                   "fileio.shutil.copy2 = die")
        self.assertEqual(rc, 9)
        Project.open(layers.game_root, layers.mod_root).close()
        self.assertEqual(sorted(str(p.relative_to(layers.mod_root)) for p in layers.mod_root.rglob("*.tmp")), [])

    def test_cut_during_recovery_leaves_no_empty_folders(self):           # R8
        layers = self.layers({A: "a = 1\r\n"})
        rc = self.run_save(layers, "journal.FAULT_HOOK = lambda s, i: (_ for _ in ()).throw(RuntimeError()) "
                                   "if (s, i) == ('replace', 0) else None\n"
                                   "journal._remove_created_dirs = lambda *a, **k: os._exit(9)")
        self.assertEqual(rc, 9)
        Project.open(layers.game_root, layers.mod_root).close()
        self.assertFalse((layers.mod_root / "history").exists(), "la carpeta que creó el guardado se queda vacía")


class OrphanSessionTests(Base):
    def test_lock_holder_offers_a_dead_session_whose_pid_was_reused(self):  # R9
        layers = self.layers({A: "a = 1\r\n"})
        root = layers.mod_root / ".vic2studio" / "recovery"
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)          # las limpiezas van al revés: primero kill, luego wait
        journal.write_recovery(WriteGuard(layers.mod_root), root, "reused", {VPath.of(A): b"a = trabajo\r\n"})
        index = root / "reused" / "index.json"
        data = json.loads(index.read_text())
        data["pid"] = other.pid
        index.write_text(json.dumps(data))
        project = Project.open(layers.game_root, layers.mod_root)
        self.addCleanup(project.close)
        self.assertTrue(project.lock.held)
        self.assertEqual(project.orphan_sessions, ["reused"])


class BakTests(Base):
    def test_rolled_back_save_keeps_the_previous_bak(self):               # R10
        layers = self.layers({A: "a = v1\r\n", B: "b = 1\r\n", "common/c.txt": "c = 1\r\n"})
        mod = layers.mod_root
        project = Project.open(layers.game_root, mod)
        self.addCleanup(project.close)
        ws = project.ws
        with ws.transaction("x"):
            ws.replace_text(ws.open(A), b"a = v2\r\n")
        ws.save()
        self.assertEqual((mod / "common/a.txt.bak").read_bytes(), b"a = v1\r\n")
        with ws.transaction("y"):
            for rel, data in ((A, b"a = v3\r\n"), (B, b"b = 2\r\n"), ("common/c.txt", b"c = 2\r\n")):
                ws.replace_text(ws.open(rel), data)
        real, locked = os.replace, os.fspath(mod / "common/c.txt")

        def replace(src, dst):
            if os.fspath(dst) == locked and os.fspath(src).endswith(".tmp"):
                raise PermissionError(errno.EACCES, "abierto en otro programa")
            return real(src, dst)
        with mock.patch.object(fileio.os, "replace", replace), mock.patch.object(fileio.time, "sleep"):
            report = ws.save()
        self.assertEqual([p.code for p in report.problems], ["save_failed"])
        self.assertEqual((mod / A).read_bytes(), b"a = v2\r\n")
        self.assertEqual((mod / "common/a.txt.bak").read_bytes(), b"a = v1\r\n",
                         "un guardado que no cambió nada sustituyó el .bak anterior")

    def test_killed_while_backing_up_keeps_the_previous_bak(self):        # R10 (recuperación al abrir)
        layers = self.layers({A: "a = v1\r\n"})
        mod = layers.mod_root
        project = Project.open(layers.game_root, mod)
        with project.ws.transaction("x"):
            project.ws.replace_text(project.ws.open(A), b"a = v2\r\n")
        project.ws.save()
        project.close()
        # Muere tras apartar la .bak anterior y copiar la nueva: el diario sigue «prepared».
        rc = child(f"""
from vic2studio.core.project import Project, journal
p = Project.open(Path({str(layers.game_root)!r}), Path({str(mod)!r}))
with p.ws.transaction("y"):
    p.ws.replace_text(p.ws.open({A!r}), b"a = v3\\r\\n")
journal.FAULT_HOOK = lambda s, i: os._exit(9) if s == "backup" else None
p.ws.save()
""")
        self.assertEqual(rc, 9)
        Project.open(layers.game_root, mod).close()
        self.assertEqual((mod / A).read_bytes(), b"a = v2\r\n")
        self.assertEqual((mod / "common/a.txt.bak").read_bytes(), b"a = v1\r\n",
                         "la recuperación de un guardado cortado tiró el .bak anterior")


if __name__ == "__main__":
    unittest.main()
