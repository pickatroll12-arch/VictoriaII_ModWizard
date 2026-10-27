"""``Workspace``: documentos, transacciones, deshacer exacto y guardado con diario (wizard §6.2–6.5).

Incluye los criterios de aceptación 3 (cambiar un CB crea solo ``<mod>/common/cb_types.txt``
con un diff de 1 línea, y sobre un mod con su copia la modifica con un diff de 1
línea; el juego no cambia) y 7 (deshacer y rehacer una transacción de 3 archivos
es exacto byte a byte; deshacer hasta el punto guardado deja el documento limpio).
"""

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import user_mod, vanilla_root  # noqa: E402
from _layers import isolate_appdirs  # noqa: E402
from _minigame import CB_MONTHS, build_minigame  # noqa: E402
from vic2studio.core.clausewitz.serializer import SourceMismatchError  # noqa: E402
from vic2studio.core.encoding import UnencodableTextError  # noqa: E402
from vic2studio.core.project import (  # noqa: E402
    DirtyChanged,
    DocChanged,
    DocCreated,
    DocDeleted,
    DocKind,
    DocReplaced,
    Project,
    ReadOnlyDocumentError,
    Saved,
    UndoApplied,
    Workspace,
    WriteAction,
)
from vic2studio.core.project import codecs  # noqa: E402
from vic2studio.core.project.diffing import changed_lines  # noqa: E402
from vic2studio.core.project.model import (  # noqa: E402
    READ_ONLY_LOCKED,
    READ_ONLY_PARSE_ERRORS,
    SAVE_READ_ONLY,
    SAVE_SOURCE_MISMATCH,
)
from vic2studio.core.project.settings import default_settings  # noqa: E402
from vic2studio.core.vfs import DESCRIPTOR_REL, LayerKind, VirtualFS, VPath  # noqa: E402

CB = "common/cb_types.txt"
DECISIONS = "decisions/tst_decisions.txt"
NEW = "events/tst_new_events.txt"


def set_months(ws, cb="conquer_land", months="24"):
    handle = ws.open(CB)
    ws.touch(handle)
    handle.model.document.get(cb).set("months", months)
    return handle


def snapshot(ws, rel):
    handle = ws.peek(rel)
    if handle is None or handle.deleted:
        return None
    return codecs.codec_for(handle.kind).snapshot(handle.model)


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def minigame(self, **kwargs):
        game = build_minigame(**kwargs)
        self.addCleanup(game.cleanup)
        return game

    def workspace(self, game, **kwargs):
        vfs = VirtualFS(game.game_root, game.mod_root, descriptor=game.descriptor)
        vfs.scan()
        ws = Workspace(vfs, settings=default_settings(game.mod_root), **kwargs)
        self.addCleanup(lambda: None if ws._closed else ws.close())
        return ws


class OpenTests(WorkspaceCase):
    def test_single_instance_per_key_and_reading_writes_nothing(self):
        game = self.minigame()
        tree, game_tree = game.tree(), game.game_tree()
        ws = self.workspace(game)
        handle = ws.open(CB)
        self.assertIs(ws.open("COMMON\\CB_Types.txt"), handle)
        self.assertIs(ws.peek("common/CB_TYPES.TXT"), handle)
        self.assertEqual(handle.kind, DocKind.CLAUSEWITZ)
        self.assertIs(handle.origin.layer.kind, LayerKind.GAME)
        self.assertFalse(handle.dirty)
        self.assertIsNone(handle.read_only_reason)
        self.assertEqual(ws.open("localisation/minigame.csv").kind, DocKind.LOCALISATION)
        self.assertEqual(game.tree(), tree)
        self.assertEqual(game.game_tree(), game_tree)

    def test_missing_files(self):
        ws = self.workspace(self.minigame())
        with self.assertRaises(FileNotFoundError):
            ws.open(NEW)
        self.assertIsNone(ws.peek(NEW))
        virtual = ws.open(NEW, create=True)
        self.assertTrue(virtual.is_new)
        self.assertFalse(virtual.dirty, "un documento nuevo sin tocar no se guarda")
        self.assertEqual(ws.dirty(), [])
        self.assertIs(ws.open(NEW), virtual)

    def test_parse_errors_open_read_only_and_the_text_fix_reenables_editing(self):
        """D17: con errores de sintaxis solo se edita el texto; al arreglarlo vuelve la edición estructural."""
        game = self.minigame(mod_files={"decisions/broken.txt": "political_decisions = {\r\n\ta = { }\r\n"})
        ws = self.workspace(game)
        handle = ws.open("decisions/broken.txt")
        self.assertEqual(handle.read_only_reason, READ_ONLY_PARSE_ERRORS)
        with ws.transaction("undo.x"):
            with self.assertRaises(ReadOnlyDocumentError):
                ws.touch(handle)
        with ws.transaction("undo.fix"):
            ws.replace_text(handle, b"political_decisions = {\r\n\ta = { }\r\n}\r\n")
        self.assertIsNone(handle.read_only_reason)
        self.assertTrue(handle.dirty)
        with ws.transaction("undo.edit"):
            ws.touch(handle)
            handle.model.document.get("political_decisions").append("b", "yes")
        ws.undo()
        ws.undo()
        self.assertEqual(handle.read_only_reason, READ_ONLY_PARSE_ERRORS, "deshacer vuelve al texto roto")
        self.assertFalse(handle.dirty)

    def test_lru_evicts_only_clean_unreferenced_documents(self):
        ws = self.workspace(self.minigame(), lru_bytes=1)
        events = ws.open("events/minigame_events.txt")
        with ws.transaction("undo.edit"):
            set_months(ws)
        ws.open("localisation/minigame.csv")
        ws.open("common/countries.txt")
        open_keys = {h.rel.key for h in ws.documents()}
        self.assertIn(VPath.of(CB).key, open_keys, "sucio: fijado")
        self.assertNotIn(events.rel.key, open_keys, "limpio y sin instantáneas: expulsado")
        ws.save()
        ws.open("common/countries.txt")
        self.assertIsNotNone(ws.peek(CB), "lo nombra la pila de deshacer: fijado")


class TransactionTests(WorkspaceCase):
    def test_touch_needs_a_transaction(self):
        ws = self.workspace(self.minigame())
        with self.assertRaises(RuntimeError):
            ws.touch(ws.open(CB))
        with self.assertRaises(RuntimeError):
            ws.create(NEW, DocKind.CLAUSEWITZ)

    def test_edit_marks_dirty_and_notifies_at_the_end(self):
        ws = self.workspace(self.minigame())
        seen = []
        unsubscribe = ws.subscribe(seen.append)
        with ws.transaction("undo.edit_cb", merge_key=None, cb="conquer_land") as txn:
            handle = set_months(ws)
            self.assertEqual(seen, [], "los eventos llegan al cerrar")
            self.assertEqual(txn.touched(), [CB])
        self.assertTrue(handle.dirty)
        self.assertEqual(seen, [DocChanged(VPath.of(CB), handle.version), DirtyChanged(1)])
        self.assertEqual(ws.history(), [("undo.edit_cb", {"cb": "conquer_land"})])
        unsubscribe()
        with ws.transaction("undo.again"):
            set_months(ws, months="25")
        self.assertEqual(len(seen), 2)

    def test_touch_without_changes_is_not_dirty_and_stacks_nothing(self):
        ws = self.workspace(self.minigame())
        handle = ws.open(CB)
        version = handle.version
        with ws.transaction("undo.nothing"):
            ws.touch(handle)
        self.assertFalse(handle.dirty)
        self.assertEqual(handle.version, version)
        self.assertFalse(ws.can_undo())

    def test_nested_transactions_merge_into_the_outer_one(self):
        ws = self.workspace(self.minigame())
        with ws.transaction("undo.outer"):
            set_months(ws)
            with ws.transaction("undo.inner"):
                handle = ws.open(DECISIONS)
                ws.touch(handle)
                handle.model.document.get("political_decisions").append("x", "yes")
        self.assertEqual(ws.history(), [("undo.outer", {})])
        ws.undo()
        self.assertEqual(ws.dirty(), [])

    def test_exception_reverts_and_stacks_nothing(self):
        ws = self.workspace(self.minigame())
        original = snapshot(ws, CB) if ws.open(CB) else None
        with self.assertRaises(KeyError):
            with ws.transaction("undo.fails"):
                set_months(ws)
                ws.create(NEW, DocKind.CLAUSEWITZ)
                raise KeyError("fallo del asistente")
        self.assertEqual(snapshot(ws, CB), original)
        self.assertFalse(ws.peek(CB).dirty)
        self.assertIsNone(ws.peek(NEW))
        self.assertFalse(ws.can_undo())

    def test_inner_exception_reverts_only_the_inner_changes(self):
        ws = self.workspace(self.minigame())
        with ws.transaction("undo.outer"):
            set_months(ws, months="30")
            after_outer = snapshot(ws, CB)
            try:
                with ws.transaction("undo.inner"):
                    set_months(ws, cb="free_people", months="99")
                    handle = ws.open(DECISIONS)
                    ws.touch(handle)
                    handle.model.document.get("political_decisions").append("x", "yes")
                    raise ValueError("el paso interior falla")
            except ValueError:
                pass
            self.assertEqual(snapshot(ws, CB), after_outer)
            self.assertFalse(ws.peek(DECISIONS).dirty)
        self.assertEqual(ws.history(), [("undo.outer", {})])
        self.assertEqual([h.rel for h in ws.dirty()], [CB])
        ws.undo()
        self.assertEqual(ws.dirty(), [])

    def test_unencodable_text_is_rejected_when_the_transaction_closes(self):
        """I9: un carácter que no cabe en cp1252 se rechaza al editar; el documento vuelve a como estaba."""
        ws = self.workspace(self.minigame())
        handle = ws.open(CB)
        original = snapshot(ws, CB)
        with self.assertRaises(UnencodableTextError):
            with ws.transaction("undo.edit"):
                ws.touch(handle)
                handle.model.document.get("conquer_land").set("war_name", "中文")
        self.assertEqual(snapshot(ws, CB), original)
        self.assertFalse(ws.peek(CB).dirty)
        self.assertFalse(ws.can_undo())

    def test_merge_key_merges_quick_edits(self):
        ws = self.workspace(self.minigame())
        clock = iter([100.0, 100.5, 103.0])
        with mock.patch("vic2studio.core.project.undo.time.monotonic", lambda: next(clock)):
            for months in ("13", "14", "15"):
                with ws.transaction("undo.months", merge_key="cb:conquer_land:months"):
                    set_months(ws, months=months)
        self.assertEqual(len(ws.history()), 2, "las dos primeras en menos de 1 s se funden")
        ws.undo()
        self.assertIn(b"months = 14", snapshot(ws, CB))
        ws.undo()
        self.assertIn(b"months = 12", snapshot(ws, CB))
        self.assertFalse(ws.peek(CB).dirty)

    def test_read_only_workspace(self):
        game = self.minigame()
        ws = self.workspace(game, read_only=True)
        handle = ws.open(CB)
        self.assertEqual(handle.read_only_reason, READ_ONLY_LOCKED)
        with ws.transaction("undo.x"):
            with self.assertRaises(ReadOnlyDocumentError):
                ws.touch(handle)
            with self.assertRaises(ReadOnlyDocumentError):
                ws.create(NEW, DocKind.CLAUSEWITZ)
        report = ws.save()
        self.assertEqual([p.code for p in report.problems], [SAVE_READ_ONLY])
        self.assertFalse(report.ok)


class UndoTests(WorkspaceCase):
    def three_file_transaction(self, ws):
        with ws.transaction("undo.three"):
            set_months(ws)                                       # del juego (se copiará)
            decisions = ws.open(DECISIONS)                       # del mod
            ws.touch(decisions)
            decisions.model.document.get("political_decisions").append("tst_more", "yes")
            new = ws.create(NEW, DocKind.CLAUSEWITZ)             # nuevo
            new.model.document.append("country_event", "{ }")

    def test_acceptance_criterion_7_exact_undo_redo_of_three_files(self):
        ws = self.workspace(self.minigame())
        before = {rel: snapshot(ws, rel) for rel in (CB, DECISIONS) if ws.open(rel)}
        before[NEW] = None
        self.three_file_transaction(ws)
        after = {rel: snapshot(ws, rel) for rel in (CB, DECISIONS, NEW)}
        self.assertTrue(all(after[rel] != before[rel] for rel in after))
        seen = []
        ws.subscribe(seen.append)
        ws.undo()
        self.assertEqual({rel: snapshot(ws, rel) for rel in after}, before)
        self.assertIsNone(ws.peek(NEW))
        with self.assertRaises(FileNotFoundError):
            ws.open(NEW)
        self.assertEqual(ws.dirty(), [])
        self.assertIn(UndoApplied("undo.three", {}, False, (VPath.of(CB), VPath.of(DECISIONS), VPath.of(NEW))), seen)
        self.assertIn(DocDeleted(VPath.of(NEW)), seen)
        self.assertIn(DocReplaced(VPath.of(CB)), seen)
        ws.redo()
        self.assertEqual({rel: snapshot(ws, rel) for rel in after}, after)
        self.assertEqual(len(ws.dirty()), 3)
        self.assertFalse(ws.can_redo())

    def test_acceptance_criterion_7_undo_to_the_save_point_is_clean(self):
        game = self.minigame()
        ws = self.workspace(game)
        with ws.transaction("undo.a"):
            set_months(ws, months="20")
        self.assertTrue(ws.save().ok)
        handle = ws.peek(CB)
        self.assertFalse(handle.dirty)
        with ws.transaction("undo.b"):
            set_months(ws, months="21")
        self.assertTrue(handle.dirty)
        ws.undo()
        self.assertFalse(handle.dirty, "deshacer hasta el punto guardado deja el documento limpio")
        self.assertEqual(snapshot(ws, CB), game.mod(CB).read_bytes())
        ws.undo()
        self.assertTrue(handle.dirty, "deshacer más allá de lo guardado vuelve a ensuciarlo")
        self.assertEqual(snapshot(ws, CB), game.game(CB).read_bytes())
        ws.redo()
        self.assertFalse(handle.dirty)
        ws.redo()
        self.assertTrue(handle.dirty)

    def test_undo_inside_a_transaction_is_refused(self):
        ws = self.workspace(self.minigame())
        with ws.transaction("undo.x"):
            with self.assertRaises(RuntimeError):
                ws.undo()

    def test_create_delete_and_undo(self):
        game = self.minigame()
        ws = self.workspace(game)
        seen = []
        ws.subscribe(seen.append)
        with ws.transaction("undo.create"):
            ws.create(NEW, DocKind.CLAUSEWITZ).model.document.append("a", "1")
        self.assertIn(DocCreated(VPath.of(NEW)), seen)
        with ws.transaction("undo.create"):
            with self.assertRaises(FileExistsError):
                ws.create(NEW, DocKind.CLAUSEWITZ)
            with self.assertRaises(FileExistsError):
                ws.create(DECISIONS, DocKind.CLAUSEWITZ)
        with ws.transaction("undo.delete"):
            ws.delete(NEW)
        self.assertIsNone(ws.peek(NEW), "un documento nuevo borrado desaparece")
        ws.undo()
        self.assertEqual(snapshot(ws, NEW), b"a = 1\r\n")
        with ws.transaction("undo.delete"):
            with self.assertRaises(PermissionError):
                ws.delete(CB)                                    # del juego base
            ws.delete(DECISIONS)
        self.assertTrue(ws.peek(DECISIONS).deleted)
        with self.assertRaises(FileNotFoundError):
            ws.open(DECISIONS)
        ws.undo()
        self.assertIsNone(ws.peek(DECISIONS), "no estaba abierto: deshacer lo deja como estaba")
        self.assertFalse(ws.open(DECISIONS).dirty)

    def test_trash_on_save_and_undo_after_saving(self):
        game = self.minigame()
        ws = self.workspace(game)
        original = game.mod(DECISIONS).read_bytes()
        with ws.transaction("undo.delete"):
            ws.delete(DECISIONS)
        changes = ws.changeset()
        self.assertEqual([w.action for w in changes.writes], [WriteAction.TRASH])
        self.assertTrue(changes.needs_review)
        report = ws.save()
        self.assertEqual(report.result.trashed, (VPath.of(DECISIONS),))
        self.assertFalse(game.mod(DECISIONS).exists())
        trashed = game.mod(f".vic2studio/trash/{report.result.txid}/{DECISIONS}")
        self.assertEqual(trashed.read_bytes(), original)
        self.assertEqual(ws.dirty(), [])
        ws.undo()
        handle = ws.peek(DECISIONS)
        self.assertTrue(handle.dirty)
        self.assertEqual([w.action for w in ws.changeset().writes], [WriteAction.CREATE])
        ws.save()
        self.assertEqual(game.mod(DECISIONS).read_bytes(), original)

    def test_undo_create_after_saving_is_a_pending_deletion(self):
        """Regresión: deshacer la creación de un archivo ya guardado lo daba por existente (se releía del disco)."""
        game = self.minigame()
        ws = self.workspace(game)
        with ws.transaction("undo.create"):
            ws.create(NEW, DocKind.CLAUSEWITZ).model.document.append("a", "1")
        self.assertTrue(ws.save().ok)
        ws.undo()
        with self.assertRaises(FileNotFoundError):
            ws.open(NEW)
        self.assertTrue(ws.peek(NEW).deleted)
        self.assertEqual([w.action for w in ws.changeset().writes], [WriteAction.TRASH])
        ws.redo()
        self.assertFalse(ws.peek(NEW).dirty, "rehacer vuelve al punto guardado")
        ws.undo()
        self.assertTrue(ws.save().ok)
        self.assertFalse(game.mod(NEW).exists())

    def test_revert(self):
        game = self.minigame(mod_copies=[CB])
        ws = self.workspace(game)
        with ws.transaction("undo.a"):
            set_months(ws, months="40")
        handle = ws.peek(CB)
        ws.revert(CB)
        self.assertFalse(handle.dirty)
        self.assertEqual(snapshot(ws, CB), game.mod(CB).read_bytes())
        self.assertEqual(ws.history()[0], ("undo.revert_file", {"rel": CB}))
        ws.undo()
        self.assertTrue(handle.dirty)
        self.assertIn(b"months = 40", snapshot(ws, CB))
        ws.redo()
        self.assertFalse(handle.dirty)


PICTURE = "gfx/pictures/tst_picture.dds"
PICTURE_BYTES = b"DDS \x7c\x00\x00\x00" + bytes(range(256)) * 40


class UnopenedDeleteTests(WorkspaceCase):
    """Borrar un archivo que no estaba abierto no lo decodifica (``trash_identical_copies`` borra miles)."""

    def setUp(self):
        super().setUp()
        self.game = self.minigame(mod_files={PICTURE: PICTURE_BYTES})
        self.ws = self.workspace(self.game)

    def delete(self, *rels):
        with self.ws.transaction("undo.delete"):
            for rel in rels:
                self.ws.delete(rel)

    def test_nothing_is_decoded_and_undo_redo_stay_cheap(self):
        self.delete(DECISIONS, PICTURE)
        for rel in (DECISIONS, PICTURE):
            self.assertTrue(self.ws.peek(rel).deleted)
            self.assertTrue(self.ws.peek(rel).unread, rel)
        self.assertEqual(len(self.ws.dirty()), 2)
        self.ws.changeset()
        self.assertTrue(self.ws.peek(DECISIONS).unread, "el diff no decodifica")
        self.ws.undo()
        self.assertIsNone(self.ws.peek(DECISIONS))
        self.assertIsNone(self.ws.peek(PICTURE))
        self.assertEqual(self.ws.dirty(), [])
        # Memoria: tras deshacer la limpieza de VSM, sus 8462 instantáneas no deben quedarse en la caché.
        self.assertNotIn(VPath.of(DECISIONS).key, self.ws._snap)
        self.ws.redo()
        self.assertTrue(self.ws.peek(DECISIONS).deleted)
        self.assertTrue(self.ws.peek(DECISIONS).unread)
        self.assertTrue(self.ws.save().ok)
        self.assertFalse(self.game.mod(DECISIONS).exists())
        self.assertFalse(self.game.mod(PICTURE).exists())

    def test_the_diff_is_the_same_as_for_an_opened_file(self):
        opened = self.minigame(mod_files={PICTURE: PICTURE_BYTES})
        ws = self.workspace(opened)
        with ws.transaction("undo.delete"):
            for rel in (DECISIONS, PICTURE):
                ws.open(rel)
                ws.delete(rel)
        self.delete(DECISIONS, PICTURE)
        expected = {w.rel: w.diff for w in ws.changeset().writes}
        self.assertEqual({w.rel: w.diff for w in self.ws.changeset().writes}, expected)
        self.assertIn(f"({len(PICTURE_BYTES)} -> - bytes)", expected[VPath.of(PICTURE)])
        self.assertIn("-\ttst_reform = {", expected[VPath.of(DECISIONS)])

    def test_undo_after_an_external_change_restores_what_was_read(self):
        original = self.game.mod(DECISIONS).read_bytes()
        self.delete(DECISIONS)
        self.game.mod(DECISIONS).write_bytes(b"# cambiado fuera\r\n")
        self.ws.undo()
        self.assertFalse(self.ws.peek(DECISIONS).deleted)
        self.assertEqual(snapshot(self.ws, DECISIONS), original)

    def test_a_failed_transaction_leaves_it_unopened(self):
        with self.assertRaises(RuntimeError):
            with self.ws.transaction("undo.delete"):
                self.ws.delete(DECISIONS)
                raise RuntimeError("falla a mitad")
        self.assertIsNone(self.ws.peek(DECISIONS))
        self.assertEqual(self.ws.history(), [])

    def test_reviving_and_undoing_step_by_step(self):
        original = self.game.mod(DECISIONS).read_bytes()
        self.delete(DECISIONS)
        deletion = [w.diff for w in self.ws.changeset().writes]
        with self.ws.transaction("undo.create"):
            self.ws.open(DECISIONS, create=True).model.document.append("a", "1")
        self.assertEqual(snapshot(self.ws, DECISIONS), b"a = 1\r\n")
        self.ws.undo()
        self.assertTrue(self.ws.peek(DECISIONS).deleted)
        self.assertEqual([w.diff for w in self.ws.changeset().writes], deletion, "otra vez la lápida de antes")
        self.ws.undo()
        self.assertIsNone(self.ws.peek(DECISIONS))
        self.ws.redo()
        self.ws.redo()
        self.assertEqual(snapshot(self.ws, DECISIONS), b"a = 1\r\n")
        self.ws.undo()
        self.ws.undo()
        self.assertEqual(self.ws.open(DECISIONS) and snapshot(self.ws, DECISIONS), original)

    def test_undo_never_drops_unsaved_edits(self):
        """Volver a «sin abrir» solo vale para el estado guardado: un estado con ediciones se restaura entero."""
        self.delete(DECISIONS)
        with self.ws.transaction("undo.create"):
            self.ws.open(DECISIONS, create=True).model.document.append("a", "1")
        self.delete(DECISIONS)
        self.ws.undo()
        self.ws.redo()
        self.ws.undo()
        self.assertEqual(snapshot(self.ws, DECISIONS), b"a = 1\r\n")
        self.assertTrue(self.ws.peek(DECISIONS).dirty)

    def test_undoing_a_saved_deletion_of_a_binary_saves_it_back(self):
        """Regresión (bloqueante de la revisión): tras guardar la papelera y deshacer, la imagen volvía como un
        documento sin códec de escritura y ningún guardado funcionaba (ni el de otras ediciones)."""
        self.delete(PICTURE)
        self.assertTrue(self.ws.save().ok)
        self.assertFalse(self.game.mod(PICTURE).exists())
        self.ws.undo()
        with self.ws.transaction("undo.edit"):
            set_months(self.ws, months="30")                     # otra edición cualquiera
        writes = {str(w.rel): w.action for w in self.ws.changeset().writes}
        self.assertEqual(writes[PICTURE], WriteAction.CREATE)
        report = self.ws.save()
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(self.game.mod(PICTURE).read_bytes(), PICTURE_BYTES, "la imagen vuelve tal cual")
        self.assertIn(b"months = 30", self.game.mod(CB).read_bytes())

    def test_an_opened_file_keeps_its_instance(self):
        handle = self.ws.open(DECISIONS)
        self.delete(DECISIONS)
        self.ws.undo()
        self.assertIs(self.ws.peek(DECISIONS), handle)
        self.assertFalse(handle.deleted or handle.dirty)

    def test_game_files_and_missing_files_are_refused_without_opening_them(self):
        with self.ws.transaction("undo.delete"):
            with self.assertRaises(PermissionError):
                self.ws.delete(CB)
            with self.assertRaises(FileNotFoundError):
                self.ws.delete("decisions/no_existe.txt")
        self.assertIsNone(self.ws.peek(CB))


class SaveTests(WorkspaceCase):
    def test_acceptance_criterion_3_empty_mod(self):
        """Minijuego con mod vacío: cambiar months de un CB y guardar crea solo <mod>/common/cb_types.txt."""
        game = self.minigame(mod=False)
        game_tree = game.game_tree()
        self.assertEqual(game.tree(), {})
        project = Project.open(game.game_root, game.mod_root)
        self.addCleanup(project.close)
        with project.edit("undo.edit_cb", cb="conquer_land"):
            set_months(project.ws)
        changes = project.ws.changeset()
        self.assertEqual([(w.action, w.target) for w in changes.writes],
                         [(WriteAction.COPY_FROM_GAME, game.mod(CB))])
        self.assertEqual(changes.copies_from_game, 1)
        self.assertIn("-\tmonths = 12", changes.writes[0].diff)
        self.assertIn("+\tmonths = 24", changes.writes[0].diff)
        report = project.save()
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(sorted(game.tree()), [CB], "solo se crea <mod>/common/cb_types.txt")
        self.assertEqual(changed_lines(game.game(CB).read_bytes(), game.mod(CB).read_bytes()), (1, 1))
        self.assertEqual(game.game_tree(), game_tree, "los hashes del juego base no cambian")
        self.assertFalse(project.ws.peek(CB).dirty)
        self.assertIs(project.ws.peek(CB).origin.layer.kind, LayerKind.MOD)

    def test_acceptance_criterion_3_mod_with_its_own_copy(self):
        """Mod copia completa (como VSM): el mismo cambio modifica su copia con un diff de 1 línea."""
        game = self.minigame(mod_copies=[CB])
        game_tree = game.game_tree()
        before = game.tree()
        project = Project.open(game.game_root, game.mod_root)
        self.addCleanup(project.close)
        with project.edit("undo.edit_cb"):
            handle = set_months(project.ws, cb="humble_rival", months="4")
        self.assertIs(handle.origin.layer.kind, LayerKind.MOD)
        self.assertEqual([w.action for w in project.ws.changeset().writes], [WriteAction.MODIFY])
        self.assertTrue(project.save().ok)
        self.assertEqual(changed_lines(before[CB][2], game.mod(CB).read_bytes()), (1, 1))
        self.assertEqual(game.mod(CB + ".bak").read_bytes(), before[CB][2], ".bak junto al archivo (decisión 3)")
        self.assertEqual(game.mod(".vic2studio/originals/" + CB).read_bytes(), before[CB][2])
        changed = {rel for rel in game.tree() if game.tree()[rel][2] != before.get(rel, (0, 0, None))[2]}
        self.assertEqual(changed, {CB, CB + ".bak", ".vic2studio/originals/" + CB})
        self.assertEqual(game.game_tree(), game_tree)

    def test_acceptance_criterion_3_with_the_corpus(self):
        """Con corpus: vanilla real + la copia de cb_types.txt de VSM en un mod temporal fuera del juego."""
        game_root = vanilla_root()
        vsm = user_mod()
        if game_root is None or vsm is None or not (vsm / CB).is_file():
            self.skipTest("necesita VIC2_GAME o VIC2_CORPUS con vanilla y el VSM completo")
        with tempfile.TemporaryDirectory() as tmp:
            mod_root = Path(tmp) / "VSM"
            (mod_root / "common").mkdir(parents=True)
            shutil.copy2(vsm / CB, mod_root / CB)
            original = (mod_root / CB).read_bytes()
            game_common = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in (game_root / "common").iterdir() if p.is_file()}
            project = Project.open(game_root, mod_root)
            try:
                handle = project.ws.open(CB)
                self.assertIs(handle.origin.layer.kind, LayerKind.MOD)
                block = next(e.value for e in handle.model.document.entries
                             if e.key is not None and e.key.text != "peace_order" and hasattr(e.value, "get")
                             and e.value.get("months") is not None)
                with project.edit("undo.edit_cb"):
                    project.ws.touch(handle)
                    block.set("months", str(int(block.get("months").text) + 1))
                self.assertTrue(project.save().ok)
            finally:
                project.close()
            self.assertEqual(changed_lines(original, (mod_root / CB).read_bytes()), (1, 1))
            self.assertEqual({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (game_root / "common").iterdir() if p.is_file()}, game_common)

    def test_saving_twice_and_edits_back_to_the_original(self):
        game = self.minigame(mod=False)
        ws = self.workspace(game)
        with ws.transaction("undo.a"):
            set_months(ws, months="24")
        with ws.transaction("undo.b"):
            set_months(ws, months=str(CB_MONTHS["conquer_land"]))
        self.assertTrue(ws.peek(CB).dirty)
        report = ws.save()
        self.assertTrue(report.nothing_to_save, "igual que el juego: no se copia (I4)")
        self.assertEqual(game.tree(), {})
        self.assertEqual(ws.dirty(), [])

    def test_changeset_lists_every_action_with_its_diff(self):
        game = self.minigame()
        ws = self.workspace(game)
        with ws.transaction("undo.many"):
            set_months(ws)
            decisions = ws.open(DECISIONS)
            ws.touch(decisions)
            decisions.model.document.get("political_decisions").append("tst_more", "yes")
            ws.create(NEW, DocKind.CLAUSEWITZ).model.document.append("a", "1")
            ws.delete("localisation/00_TST_decisions.csv")
        writes = {str(w.rel): w for w in ws.changeset().writes}
        self.assertEqual({rel: w.action for rel, w in writes.items()}, {
            CB: WriteAction.COPY_FROM_GAME, DECISIONS: WriteAction.MODIFY, NEW: WriteAction.CREATE,
            "localisation/00_TST_decisions.csv": WriteAction.TRASH})
        self.assertIn("+\ttst_more = yes", writes[DECISIONS].diff)
        self.assertIn("+a = 1", writes[NEW].diff)
        self.assertIn("-tst_reform;", writes["localisation/00_TST_decisions.csv"].diff)
        self.assertEqual(writes[NEW].data, b"a = 1\r\n", "archivo nuevo en cp1252 con CRLF")
        self.assertIsNone(writes[NEW].expected)
        self.assertIsNotNone(writes[DECISIONS].expected)
        tree = game.tree()
        self.assertEqual(ws.changeset([VPath.of(NEW)]).writes, (writes[NEW],))
        self.assertEqual(game.tree(), tree, "changeset no escribe")
        seen = []
        ws.subscribe(seen.append)
        report = ws.save([VPath.of(NEW)])
        self.assertEqual(report.result.written, (VPath.of(NEW),))
        self.assertEqual(len(ws.dirty()), 3)
        self.assertIn(Saved((VPath.of(NEW),)), seen)

    def test_render_errors_never_touch_the_disk(self):
        game = self.minigame()
        ws = self.workspace(game)
        with ws.transaction("undo.a"):
            set_months(ws)
        tree = game.tree()
        error = SourceMismatchError(CB, "conquer_land > months", 10)
        with mock.patch.object(codecs.ClausewitzCodec, "render", side_effect=error):
            report = ws.save()
            with self.assertRaises(SourceMismatchError):
                ws.changeset()
        self.assertEqual([p.code for p in report.problems], [SAVE_SOURCE_MISMATCH])
        self.assertEqual(report.problems[0].args["entry"], "conquer_land > months")
        self.assertEqual(game.tree(), tree)
        self.assertTrue(ws.peek(CB).dirty)

    def test_text_that_reads_back_differently_is_not_saved(self):
        """I9 sin simulación: un modelo que no se relee igual (D17) da save_source_mismatch y no toca el disco."""
        broken = b"x = {\r\n\ta = 1\r\n\t= b\r\n}\r\n"
        game = self.minigame(mod_files={"events/broken.txt": broken})
        ws = self.workspace(game)
        handle = ws.open("events/broken.txt")
        self.assertEqual(handle.read_only_reason, READ_ONLY_PARSE_ERRORS)
        model, _ = codecs.ClausewitzCodec().load(broken, handle.rel)
        model.document.get("x").insert(1, None, 5)     # se releería como «5 = b»
        with ws.transaction("undo.text"):
            ws.replace_model(handle, model)
        self.assertTrue(handle.dirty)
        tree = game.tree()
        report = ws.save()
        self.assertEqual([p.code for p in report.problems], [SAVE_SOURCE_MISMATCH])
        self.assertEqual(game.tree(), tree)
        self.assertFalse(game.mod(".vic2studio").exists())

    def test_descriptor_is_a_document(self):
        game = self.minigame()
        ws = self.workspace(game)
        handle = ws.open(DESCRIPTOR_REL)
        self.assertIs(handle.origin.layer.kind, LayerKind.MOD)
        original = game.descriptor.read_bytes()
        with ws.transaction("undo.edit_descriptor"):
            ws.touch(handle)
            handle.model.document.set("name", "Mod de prueba")
        self.assertEqual([w.action for w in ws.changeset().writes], [WriteAction.MODIFY])
        self.assertTrue(ws.save().ok)
        self.assertIn(b'name = "Mod de prueba"', game.descriptor.read_bytes())
        self.assertEqual(game.descriptor.with_name("TestMod.mod.bak").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
