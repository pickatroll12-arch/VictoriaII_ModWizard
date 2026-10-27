"""Pruebas de regresión de la revisión adversarial de la iteración 2 (Workspace, deshacer, ajustes, Project).

Cada clase reproduce un hallazgo: falla con el commit 59e8847 y pasa con el arreglo.
"""

import dataclasses
import logging
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402
from vic2studio.core.project import DocKind, Project  # noqa: E402
from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.project.project import SETTINGS_REL  # noqa: E402
from vic2studio.core.project.workspace import WrongThreadError  # noqa: E402

CB = "common/cb_types.txt"
DEC = "decisions/tst_decisions.txt"
NEW = "events/tst_new.txt"


def snap(handle):
    return codec_for(handle.kind).snapshot(handle.model)


class Base(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def project(self, **kwargs):
        game = build_minigame(**kwargs)
        self.addCleanup(game.cleanup)
        project = Project.open(game.game_root, game.mod_root)
        self.addCleanup(project.close, discard=True)
        return game, project


class LongNameTests(Base):
    """R1: un nombre válido (≤ 255) cuyo temporal pasa de 255 deja un diario que impide reabrir el mod."""

    def test_long_name_is_blocked_before_disk_and_project_reopens(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        game, project = self.project()
        rel = "events/" + "x" * 240 + ".txt"          # 244 caracteres: el sistema lo admite como nombre
        with project.edit("undo.t"):
            handle = project.ws.create(rel, DocKind.CLAUSEWITZ)
            handle.model.document.append("a", "1")
        tree = game.tree()
        report = project.save()
        self.assertFalse(report.ok)
        self.assertTrue(any(p.blocking for p in report.problems))
        self.assertEqual(game.tree(), tree, "I9: se detecta antes de tocar el disco")
        self.assertFalse(game.mod(".vic2studio").exists())
        project.close(discard=True)
        reopened = Project.open(game.game_root, game.mod_root)     # hoy: OSError ENAMETOOLONG
        reopened.close()


class RevertThenDeleteTests(Base):
    """R2: revertir y borrar en la misma transacción deja una lápida limpia: el borrado no se guarda."""

    def test_tombstone_after_revert_is_dirty_and_saved(self):
        game, project = self.project()
        ws = project.ws
        handle = ws.open(DEC)
        with project.edit("undo.edit"):
            ws.touch(handle)
            handle.model.document.get("political_decisions").append("x", "yes")
        with project.edit("undo.cleanup"):
            ws.revert(DEC)
            ws.delete(DEC)
        self.assertTrue(handle.dirty)
        self.assertTrue(project.save().ok)
        self.assertFalse(game.mod(DEC).exists(), "el archivo va a la papelera")


class ReopenInSameTransactionTests(Base):
    """R3: quitar un documento y volver a abrirlo con create=True en la misma transacción lo deja limpio."""

    def test_reopened_document_is_dirty(self):
        game, project = self.project()
        ws = project.ws
        with project.edit("undo.wizard"):
            first = ws.create(NEW, DocKind.CLAUSEWITZ)
            first.model.document.append("a", "1")
            ws.delete(NEW)
            second = ws.open(NEW, create=True)
            ws.touch(second)
            second.model.document.append("b", "2")
        self.assertTrue(second.dirty)
        self.assertTrue(project.save().ok)
        self.assertEqual(game.mod(NEW).read_bytes(), b"b = 2\r\n")

    def test_settings_after_revert_are_saved(self):
        game, project = self.project()
        with project.edit("undo.wizard"):
            project.set_settings(dataclasses.replace(project.settings, prefix="AAA"))
            project.ws.revert(SETTINGS_REL)
            project.set_settings(dataclasses.replace(project.settings, prefix="BBB"))
        self.assertEqual(project.settings.prefix, "BBB")
        self.assertTrue(project.save().ok)
        self.assertIn(b'"BBB"', game.mod(".vic2studio/project.json").read_bytes())


class AcceptExternalTests(Base):
    """R4: tras «Conservar mis cambios», deshacer hasta la versión leída deja el documento limpio aunque el disco
    ya tiene otro contenido."""

    def test_undo_after_accept_external_stays_dirty(self):
        game, project = self.project()
        ws = project.ws
        handle = ws.open(DEC)
        original = snap(handle)
        with project.edit("undo.a"):
            ws.touch(handle)
            handle.model.document.get("political_decisions").append("mine", "yes")
        game.mod(DEC).write_bytes(original + b"# otro programa\r\n")
        ws.check_external_changes()
        ws.accept_external(DEC)
        ws.undo()
        self.assertNotEqual(snap(handle), game.mod(DEC).read_bytes())
        self.assertTrue(handle.dirty, "memoria distinta del disco: sucio")
        self.assertTrue(project.save().ok)
        self.assertEqual(game.mod(DEC).read_bytes(), original)


class RevertUndoTests(Base):
    """R5: revertir, deshacer el revert y deshacer la edición deja el documento sucio con los bytes del disco."""

    def test_undo_to_saved_point_after_revert_is_clean(self):
        game, project = self.project()
        ws = project.ws
        handle = ws.open(DEC)
        with project.edit("undo.a"):
            ws.touch(handle)
            handle.model.document.get("political_decisions").append("x", "yes")
        ws.revert(DEC)
        ws.undo()
        ws.undo()
        self.assertEqual(snap(handle), game.mod(DEC).read_bytes())
        self.assertFalse(handle.dirty)
        self.assertEqual(ws.dirty(), [])


class CreatedByOpenTests(Base):
    """R6: deshacer lo que se creó con open(create=True) (set_settings, restore_session) no vuelve a «no existía»."""

    def test_undo_restored_new_file_after_save_trashes_it(self):
        game, project = self.project()
        with project.edit("undo.create"):
            handle = project.ws.create(NEW, DocKind.CLAUSEWITZ)
            handle.model.document.append("a", "1")
        project.close()                                  # sucio: autoguardado de cierre
        project = Project.open(game.game_root, game.mod_root)
        self.addCleanup(project.close, discard=True)
        project.restore_session(project.orphan_sessions[0])
        self.assertTrue(project.save().ok)
        project.ws.undo()
        self.assertTrue(project.save().ok)
        self.assertFalse(game.mod(NEW).exists(), "hoy queda un archivo vacío en el mod")

    def test_undo_restored_new_file_before_save_removes_it(self):
        game, project = self.project()
        with project.edit("undo.create"):
            handle = project.ws.create(NEW, DocKind.CLAUSEWITZ)
            handle.model.document.append("a", "1")
        project.close()
        project = Project.open(game.game_root, game.mod_root)
        self.addCleanup(project.close, discard=True)
        project.restore_session(project.orphan_sessions[0])
        project.ws.undo()
        with self.assertRaises(FileNotFoundError):
            project.ws.open(NEW)

    def test_undo_settings_after_save_trashes_project_json(self):
        game, project = self.project()
        project.set_settings(dataclasses.replace(project.settings, prefix="ABC"))
        self.assertTrue(project.save().ok)
        project.ws.undo()
        self.assertNotEqual(project.settings.prefix, "ABC")
        self.assertTrue(project.save().ok)
        self.assertFalse(game.mod(".vic2studio/project.json").exists(), "hoy se reescribe como «{}»")


class PhantomTombstoneTests(Base):
    """R7: una lápida sin archivo debajo, restaurada sobre otro objeto, cuenta como cambio sin guardar."""

    def test_no_phantom_dirty_document(self):
        game, project = self.project()
        ws = project.ws
        with project.edit("undo.s1"):
            ws.create(NEW, DocKind.CLAUSEWITZ).model.document.append("a", "1")
        project.save()
        with project.edit("undo.s2"):
            ws.delete(NEW)
        project.save()
        ws.undo()
        ws.redo()
        with project.edit("undo.s3"):
            ws.create(NEW, DocKind.CLAUSEWITZ).model.document.append("b", "2")
            ws.delete(NEW)
        with project.edit("undo.s4"):
            ws.create(NEW, DocKind.CLAUSEWITZ).model.document.append("c", "3")
        ws.undo()
        ws.undo()
        self.assertFalse(game.mod(NEW).exists())
        dirty = ws.dirty()
        plan = ws.changeset().writes
        self.assertFalse(dirty and not plan, f"sucio sin nada que escribir: {dirty}")


class SettingsTests(Base):
    """R8 y R9: ajustes dentro de una transacción y ajustes iguales."""

    def test_settings_visible_inside_outer_transaction(self):
        game, project = self.project()
        with project.edit("undo.wizard"):
            project.set_settings(dataclasses.replace(project.settings, prefix="NEW"))
            self.assertEqual(project.settings.prefix, "NEW")

    def test_same_settings_write_nothing(self):
        game, project = self.project()
        tree = game.tree()
        project.set_settings(project.settings)
        self.assertEqual(project.ws.dirty(), [])
        self.assertTrue(project.save().nothing_to_save)
        self.assertEqual(game.tree(), tree)
        self.assertFalse(game.mod(".vic2studio").exists())


class MergeAcrossSaveTests(Base):
    """R10: teclear justo después de guardar se funde con el paso anterior y el punto guardado queda inalcanzable."""

    def test_saved_point_reachable(self):
        game, project = self.project()
        ws = project.ws
        handle = ws.open(DEC)

        def typed(value):
            with project.edit("undo.field", merge_key="dec.effect"):
                ws.touch(handle)
                handle.model.document.get("political_decisions").get("tst_reform").set("effect", value)

        typed("a")
        project.save()
        typed("ab")
        ws.undo()
        self.assertFalse(handle.dirty, "un deshacer vuelve a lo guardado")


class FinishFailureTests(Base):
    """R11: si una transacción con «Revertir» falla al cerrarse, saved_version queda apuntando a un estado que no
    existe y deshacer hasta lo leído deja el documento sucio."""

    def test_saved_version_untouched_when_finish_raises(self):
        game, project = self.project()
        ws = project.ws
        dec, cb = ws.open(DEC), ws.open(CB)
        with project.edit("undo.edit"):
            ws.touch(dec)
            dec.model.document.get("political_decisions").append("x", "yes")
        with self.assertRaises(Exception):
            with project.edit("undo.mix"):
                ws.revert(DEC)
                ws.touch(cb)
                cb.model.document.get("conquer_land").set("war_name", "中")   # no cabe en cp1252
        ws.undo()
        self.assertEqual(snap(dec), game.mod(DEC).read_bytes())
        self.assertFalse(dec.dirty)


class CloseFromOtherThreadTests(Base):
    """R12: Project.close desde otro hilo suelta el bloqueo y deja el Workspace vivo y sin autoguardado."""

    def test_close_from_other_thread_keeps_project_open(self):
        game, project = self.project()
        ws = project.ws
        handle = ws.open(DEC)
        with project.edit("undo.a"):
            ws.touch(handle)
            handle.model.document.get("political_decisions").append("x", "yes")
        errors = []

        def other():
            try:
                project.close()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        thread = threading.Thread(target=other)
        thread.start()
        thread.join()
        self.assertTrue(errors and isinstance(errors[0], WrongThreadError))
        self.assertFalse(project.closed, "sigue abierto: el bloqueo no se suelta")
        second = Project.open(game.game_root, game.mod_root)
        self.addCleanup(second.close)
        self.assertTrue(second.read_only, "otra instancia no debe poder escribir")
        project.close()
        self.assertTrue(project.closed)
        self.assertTrue(any(game.mod(".vic2studio/recovery").rglob("*.dat")), "el cierre escribe la recuperación")


if __name__ == "__main__":
    unittest.main()
