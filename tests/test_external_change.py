"""Cambios externos (wizard §6.5, I8): se detectan, son conflicto si hay cambios sin guardar y nunca se pisan
sin que el usuario elija «Conservar mis cambios», «Recargar del disco» o «Comparar»."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402
from vic2studio.core.project import DocReplaced, ExternalChange, Project, WriteAction  # noqa: E402
from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.project.model import SAVE_CONFLICT  # noqa: E402
from vic2studio.core.vfs import LayerKind, VPath  # noqa: E402

DECISIONS = "decisions/tst_decisions.txt"
CB = "common/cb_types.txt"
EXTERNAL = b"political_decisions = {\r\n\texternal = { }\r\n}\r\n"


class ExternalChangeTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)
        self.game = build_minigame()
        self.addCleanup(self.game.cleanup)
        self.project = Project.open(self.game.game_root, self.game.mod_root)
        self.addCleanup(self.project.close)
        self.ws = self.project.ws

    def edit_decisions(self):
        handle = self.ws.open(DECISIONS)
        with self.project.edit("undo.edit"):
            self.ws.touch(handle)
            handle.model.document.get("political_decisions").append("mine", "yes")
        return handle

    def text(self, rel):
        handle = self.ws.peek(rel)
        return codec_for(handle.kind).snapshot(handle.model)

    def test_clean_document_reloads_by_itself(self):
        handle = self.ws.open(DECISIONS)
        seen = []
        self.ws.subscribe(seen.append)
        self.game.mod(DECISIONS).write_bytes(EXTERNAL)
        changes = self.ws.check_external_changes()
        self.assertEqual(changes, [ExternalChange(VPath.of(DECISIONS), "modified", False)])
        self.assertEqual(self.text(DECISIONS), EXTERNAL)
        self.assertFalse(handle.dirty)
        self.assertIn(DocReplaced(VPath.of(DECISIONS)), seen)
        self.assertEqual(self.ws.check_external_changes(), [])

    def test_touch_without_change_is_not_a_change(self):
        self.ws.open(DECISIONS)
        path = self.game.mod(DECISIONS)
        data = path.read_bytes()
        path.write_bytes(data)          # mismo contenido, otra fecha
        self.assertEqual(self.ws.check_external_changes(), [])

    def test_dirty_document_is_a_conflict_and_save_does_not_overwrite(self):
        handle = self.edit_decisions()
        self.game.mod(DECISIONS).write_bytes(EXTERNAL)
        self.assertEqual(self.ws.check_external_changes(), [ExternalChange(VPath.of(DECISIONS), "modified", True)])
        self.assertIn(b"mine = yes", self.text(DECISIONS), "los cambios del usuario siguen en memoria")
        report = self.ws.save()
        self.assertEqual([p.code for p in report.problems], [SAVE_CONFLICT])
        self.assertEqual(self.game.mod(DECISIONS).read_bytes(), EXTERNAL, "el cambio externo no se pisa")
        self.assertTrue(handle.dirty)
        diff = self.ws.external_diff(DECISIONS)
        self.assertIn("-\texternal = { }", diff)
        self.assertIn("+\tmine = yes", diff)

    def test_keep_my_changes(self):
        self.edit_decisions()
        self.game.mod(DECISIONS).write_bytes(EXTERNAL)
        self.ws.accept_external(DECISIONS)
        report = self.ws.save()
        self.assertTrue(report.ok, report.problems)
        self.assertIn(b"mine = yes", self.game.mod(DECISIONS).read_bytes())
        self.assertEqual(self.game.mod(DECISIONS + ".bak").read_bytes(), EXTERNAL, "el .bak guarda lo externo")

    def test_reload_from_disk(self):
        handle = self.edit_decisions()
        self.game.mod(DECISIONS).write_bytes(EXTERNAL)
        self.ws.reload(DECISIONS)
        self.assertEqual(self.text(DECISIONS), EXTERNAL)
        self.assertFalse(handle.dirty)
        self.assertTrue(self.ws.save().nothing_to_save)

    def test_deleted_outside(self):
        self.edit_decisions()
        self.game.mod(DECISIONS).unlink()
        self.assertEqual(self.ws.check_external_changes(), [ExternalChange(VPath.of(DECISIONS), "deleted", True)])
        self.assertEqual([p.code for p in self.ws.save().problems], [SAVE_CONFLICT])
        self.ws.accept_external(DECISIONS)
        self.assertEqual([w.action for w in self.ws.changeset().writes], [WriteAction.CREATE])
        self.assertTrue(self.ws.save().ok)
        self.assertIn(b"mine = yes", self.game.mod(DECISIONS).read_bytes())

    def test_copy_created_in_the_mod_by_another_program(self):
        handle = self.ws.open(CB)
        with self.project.edit("undo.edit"):
            self.ws.touch(handle)
            handle.model.document.get("conquer_land").set("months", "50")
        self.game.mod(CB).parent.mkdir(parents=True, exist_ok=True)
        self.game.mod(CB).write_bytes(b"other = program\r\n")
        self.assertEqual(self.ws.check_external_changes(), [ExternalChange(VPath.of(CB), "created", True)])
        self.assertEqual([p.code for p in self.ws.save().problems], [SAVE_CONFLICT])
        self.assertEqual(self.game.mod(CB).read_bytes(), b"other = program\r\n")
        self.ws.accept_external(CB)
        self.assertIs(handle.origin.layer.kind, LayerKind.MOD)
        self.assertEqual([w.action for w in self.ws.changeset().writes], [WriteAction.MODIFY])
        self.assertTrue(self.ws.save().ok)
        self.assertIn(b"months = 50", self.game.mod(CB).read_bytes())

    def test_clean_game_document_follows_a_new_mod_copy(self):
        self.ws.open(CB)
        self.game.mod(CB).parent.mkdir(parents=True, exist_ok=True)
        self.game.mod(CB).write_bytes(b"cb = mod\r\n")
        self.assertEqual(self.ws.check_external_changes(), [ExternalChange(VPath.of(CB), "created", False)])
        self.assertIs(self.ws.peek(CB).origin.layer.kind, LayerKind.MOD)
        self.assertEqual(self.text(CB), b"cb = mod\r\n")


if __name__ == "__main__":
    unittest.main()
