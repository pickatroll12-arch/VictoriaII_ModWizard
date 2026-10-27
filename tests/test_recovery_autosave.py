"""Autoguardado de recuperación (wizard §6.5, I8): una sesión que muere deja sus documentos sucios en
``recovery/<sesión>/`` y la siguiente apertura la ofrece; restaurarla es una transacción deshacible."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.project import journal  # noqa: E402
from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.project.recovery import load_session, orphan_sessions  # noqa: E402
from vic2studio.core.vfs import DESCRIPTOR_REL, VPath  # noqa: E402

CB = "common/cb_types.txt"
DECISIONS = "decisions/tst_decisions.txt"


def dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


class AutosaveTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)
        self.game = build_minigame()
        self.addCleanup(self.game.cleanup)

    def open(self):
        project = Project.open(self.game.game_root, self.game.mod_root)
        self.addCleanup(project.close)
        return project

    def edit(self, project):
        ws = project.ws
        with project.edit("undo.edit"):
            cb = ws.open(CB)
            ws.touch(cb)
            cb.model.document.get("conquer_land").set("months", "77")
            descriptor = ws.open(DESCRIPTOR_REL)
            ws.touch(descriptor)
            descriptor.model.document.set("name", "Recuperado")
        return {VPath.of(CB): codec_for(cb.kind).snapshot(cb.model),
                DESCRIPTOR_REL: codec_for(descriptor.kind).snapshot(descriptor.model)}

    def recovery_root(self, project):
        return project.project_dir / journal.RECOVERY_DIR

    def kill(self, project):
        """Simula que la sesión murió: su índice pasa a nombrar un pid que ya no existe."""
        index_path = self.recovery_root(project) / project.ws.session_id / journal.RECOVERY_INDEX
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["pid"] = dead_pid()
        index_path.write_text(json.dumps(index), encoding="utf-8")
        project.lock.release()
        project.ws.close()
        project._closed = True

    def test_nothing_is_written_without_dirty_documents(self):
        project = self.open()
        project.ws.open(CB)
        project.ws.write_recovery()
        project.ws.write_recovery(final=True)
        self.assertFalse(project.project_dir.exists())

    def test_write_and_load(self):
        project = self.open()
        expected = self.edit(project)
        project.ws.write_recovery()
        root = self.recovery_root(project)
        session = project.ws.session_id
        self.assertEqual(load_session(root, session), expected)
        self.assertEqual(orphan_sessions(root), [], "la sesión vive (este proceso)")
        index = root / session / journal.RECOVERY_INDEX
        mtime = index.stat().st_mtime_ns
        project.ws.write_recovery()
        self.assertEqual(index.stat().st_mtime_ns, mtime, "sin cambios desde el último autoguardado: no reescribe")
        project.ws.undo()
        project.ws.write_recovery()
        self.assertFalse((root / session).exists(), "sin sucios se borra el de la sesión")
        self.assertFalse(project.project_dir.exists(), "y las carpetas que quedan vacías")

    def test_autosave_cadence(self):
        project = self.open()
        ws = project.ws
        self.assertFalse(ws.autosave_due(now=ws._autosave_time + 1))
        self.assertTrue(ws.autosave_due(now=ws._autosave_time + ws.AUTOSAVE_SECONDS))
        handle = ws.open(CB)
        for months in range(ws.AUTOSAVE_TRANSACTIONS):
            with project.edit("undo.edit"):
                ws.touch(handle)
                handle.model.document.get("conquer_land").set("months", str(100 + months))
        self.assertTrue(ws.autosave_due(now=ws._autosave_time + 1))
        ws.write_recovery()
        self.assertFalse(ws.autosave_due(now=ws._autosave_time + 1))

    def test_orphan_session_is_offered_and_restored(self):
        project = self.open()
        expected = self.edit(project)
        project.ws.write_recovery()
        session = project.ws.session_id
        self.kill(project)
        reopened = self.open()
        self.assertEqual(reopened.orphan_sessions, [session])
        self.assertEqual(self.game.mod(CB).exists(), False, "nada se guardó")
        restored = reopened.restore_session(session)
        self.assertEqual(sorted(restored, key=lambda r: r.key), sorted(expected, key=lambda r: r.key))
        for rel, data in expected.items():
            handle = reopened.ws.peek(rel)
            self.assertTrue(handle.dirty)
            self.assertEqual(codec_for(handle.kind).snapshot(handle.model), data)
        self.assertEqual(reopened.orphan_sessions, [])
        self.assertFalse((self.recovery_root(reopened) / session).exists())
        self.assertEqual(reopened.ws.history()[0], ("undo.restore_session", {"session": session}))
        reopened.ws.undo()
        self.assertEqual(reopened.ws.dirty(), [], "restaurar se deshace en un paso")

    def test_deletions_and_binaries_survive_a_crash(self):
        """Un borrado sin guardar y una imagen devuelta por deshacer (tras guardar la papelera) se recuperan: antes
        el autoguardado se saltaba los borrados y la recuperación descartaba los binarios sin avisar."""
        from vic2studio.core.project import WriteAction

        picture = "gfx/pictures/tst_picture.dds"
        data = b"DDS \x7c\x00\x00\x00" + bytes(range(256)) * 8
        self.game.mod(picture).parent.mkdir(parents=True, exist_ok=True)
        self.game.mod(picture).write_bytes(data)
        project = self.open()
        with project.edit("undo.delete"):
            project.ws.delete(picture)
        self.assertTrue(project.save().ok)
        project.ws.undo()                                       # la imagen vuelve, sin guardar
        with project.edit("undo.delete"):
            project.ws.delete(DECISIONS)
        project.ws.write_recovery()
        session = project.ws.session_id
        self.kill(project)
        self.assertEqual(load_session(self.recovery_root(project), session),
                         {VPath.of(DECISIONS): None, VPath.of(picture): data})
        reopened = self.open()
        self.assertEqual(reopened.orphan_sessions, [session])
        restored = reopened.restore_session(session)
        self.assertEqual(sorted(str(r) for r in restored), sorted([DECISIONS, picture]))
        self.assertTrue(reopened.ws.peek(DECISIONS).deleted)
        writes = {str(w.rel): w.action for w in reopened.ws.changeset().writes}
        self.assertEqual(writes, {DECISIONS: WriteAction.TRASH, picture: WriteAction.CREATE})
        self.assertTrue(reopened.save().ok)
        self.assertEqual(self.game.mod(picture).read_bytes(), data)
        self.assertFalse(self.game.mod(DECISIONS).exists())

    def test_a_session_with_only_deletions_is_offered(self):
        project = self.open()
        with project.edit("undo.delete"):
            project.ws.delete(DECISIONS)
        project.ws.write_recovery()
        session = project.ws.session_id
        self.kill(project)
        reopened = self.open()
        self.assertEqual(reopened.orphan_sessions, [session])
        self.assertEqual(reopened.restore_session(session), [VPath.of(DECISIONS)])
        self.assertTrue(reopened.ws.peek(DECISIONS).deleted)

    def test_discard_orphan_session(self):
        project = self.open()
        self.edit(project)
        project.ws.write_recovery()
        session = project.ws.session_id
        self.kill(project)
        reopened = self.open()
        reopened.discard_session(session)
        self.assertEqual(reopened.orphan_sessions, [])
        self.assertFalse(reopened.project_dir.exists())

    def test_close_writes_recovery_only_with_dirty_documents(self):
        project = Project.open(self.game.game_root, self.game.mod_root)
        self.edit(project)
        session = project.ws.session_id
        project.close()
        self.assertTrue((self.recovery_root(project) / session / journal.RECOVERY_INDEX).is_file())
        reopened = Project.open(self.game.game_root, self.game.mod_root)
        self.assertEqual(reopened.orphan_sessions, [session], "una sesión cerrada con sucios se ofrece")
        reopened.discard_session(session)
        self.edit(reopened)
        reopened.close(discard=True)
        self.assertFalse(reopened.project_dir.exists(), "cerrar descartando no deja autoguardado")

    def test_save_clears_the_session_recovery(self):
        project = self.open()
        self.edit(project)
        project.ws.write_recovery()
        self.assertTrue(project.save().ok)
        self.assertFalse(self.recovery_root(project).exists())


if __name__ == "__main__":
    unittest.main()
