"""Revisión adversarial de la iteración 4 (fase 6): casos que intentan romper las garantías del motor.

Sin pérdidas (I3), leer no escribe (I4), una transacción por operación (I5), vista efectiva (I7), errores sin
efectos y vistas. Cada prueba se escribió antes de creerse el comportamiento; las que encontraron un fallo lo dicen.
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
if str(PROJECT_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.schema import InvalidIdentError, RecordRef  # noqa: E402
from vic2studio.core.vfs.paths import VPath  # noqa: E402

from _corpus import vanilla_root  # noqa: E402
from test_schema_criteria import CriteriaCase  # noqa: E402
from test_schema_it4 import Case  # noqa: E402

LF_CB = ("peace_order = {\n\tconquer_land\n\tannex\n}\n\nconquer_land = {\n\tsprite_index = 1\n\tmonths = 12\n}\n")
CR_CB = LF_CB.replace("\n", "\r")
ONE_LINE_CB = "peace_order = { conquer_land annex }\nconquer_land = {\n\tsprite_index = 1\n}\n"
# Gobiernos con el formato «nombre =\r\n{» (como los de vanilla) y un comentario en línea (VSM).
OPEN_BRACE_GOVS = ("monarchy =\r\n{\r\n\tconservative = yes\r\n\telection = yes  # election = no\r\n"
                   "\tappoint_ruling_party = yes\r\n\tflagType = monarchy\r\n}\r\n")


class _Snap:
    def snap(self, rel) -> bytes:
        handle = self.ws.open(rel)
        return codec_for(handle.kind).snapshot(handle.model)


class LineEndingTests(Case, _Snap):
    def _create_in(self, text: str) -> bytes:
        with self.ws.transaction("test.undo_edit"):
            handle = self.ws.open("common/cb_types.txt")
            self.ws.replace_text(handle, text.encode("cp1252"))
        self.entities.create("casus_belli", "my_cb")
        return self.snap("common/cb_types.txt")

    def test_peace_order_keeps_lf(self):
        data = self._create_in(LF_CB)
        self.assertTrue(data.startswith(b"peace_order = {\n\tconquer_land\n\tannex\n\tmy_cb\n}\n"), data[:80])
        self.assertNotIn(b"\r", data)

    def test_peace_order_keeps_lone_cr(self):
        data = self._create_in(CR_CB)
        self.assertTrue(data.startswith(b"peace_order = {\r\tconquer_land\r\tannex\r\tmy_cb\r}\r"), data[:80])
        self.assertNotIn(b"\n", data)

    def test_peace_order_on_one_line_stays_on_one_line(self):
        data = self._create_in(ONE_LINE_CB)
        self.assertTrue(data.startswith(b"peace_order = { conquer_land annex my_cb }"), data[:80])

    def test_open_brace_on_its_own_line_and_inline_comment(self):
        with self.ws.transaction("test.undo_edit"):
            handle = self.ws.open("common/governments.txt")
            self.ws.replace_text(handle, OPEN_BRACE_GOVS.encode("cp1252"))
        self.entities.duplicate(RecordRef("government", "monarchy"), "monarchy2")
        data = self.snap("common/governments.txt").decode("cp1252")
        self.assertIn("monarchy2 =\r\n{\r\n\tconservative = yes\r\n\telection = yes  # election = no\r\n", data,
                      "la copia conserva «nombre =\\r\\n{» y el comentario en línea")
        record = self.entities.open(RecordRef("government", "monarchy2"))
        with self.ws.transaction("test.undo_edit"):
            record.set("duration", 24)
        data = self.snap("common/governments.txt").decode("cp1252")
        self.assertIn("\telection = yes  # election = no\r\n\tduration = 24\r\n", data)
        self.assertTrue(data.startswith(OPEN_BRACE_GOVS), "el original no cambia ni un byte")


class ErrorsWithoutEffectsTests(Case, _Snap):
    def test_bad_values_and_ids_change_nothing(self):
        record = self.entities.open(RecordRef("culture", "alander"))
        before = self.snap("common/cultures.txt")
        for key, value in (("color", (1, 2, 300)), ("radicalism", "mucho"), ("first_names", "Ana")):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    with self.ws.transaction("test.undo_edit"):
                        record.set(key, value)
        for ident in ("", "1x", "con espacio", "alander"):
            with self.subTest(ident=ident):
                with self.assertRaises(InvalidIdentError):
                    self.entities.create("culture", ident, {"group": "north_folk"})
                with self.assertRaises(InvalidIdentError):
                    self.entities.duplicate(RecordRef("culture", "alander"), ident)
        self.assertEqual(self.snap("common/cultures.txt"), before)
        self.assertEqual(self.ws.dirty(), [])
        self.assertEqual(self.ws.history(), [])

    def test_a_bad_value_is_refused_before_touching_the_document(self):
        """El tipo se comprueba antes de ``touch``: en un documento que no se puede tocar (solo lectura), el error es
        el del valor, no el del documento."""
        from unittest import mock

        record = self.entities.open(RecordRef("culture", "alander"))
        with mock.patch.object(self.ws, "touch", side_effect=PermissionError("solo lectura")):
            with self.assertRaises(ValueError):
                with self.ws.transaction("test.undo_edit"):
                    record.set("color", (1, 2, 300))
            with self.assertRaises(ValueError):
                with self.ws.transaction("test.undo_edit"):
                    self.entities.open(RecordRef("event_modifier", "bad_winter")).set_dynamic("effects", "x", "mucho")

    def test_restore_without_vanilla_version_changes_nothing(self):
        self.entities.create("casus_belli", "my_cb")
        self.ws.save()
        history = len(self.ws.history())
        self.assertFalse(self.entities.can_restore_vanilla(RecordRef("casus_belli", "my_cb")))
        with self.assertRaises(KeyError):
            self.entities.restore_vanilla(RecordRef("casus_belli", "my_cb"))
        self.assertEqual(len(self.ws.history()), history)
        self.assertEqual(self.ws.dirty(), [])

    def test_failing_companion_rolls_back_the_whole_creation(self):
        from unittest import mock

        from vic2studio.core.schema import AppendToList

        before = self.snap("common/cb_types.txt")
        with mock.patch.object(AppendToList, "on_create", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.entities.create("casus_belli", "my_cb")
        self.assertEqual(self.snap("common/cb_types.txt"), before)
        self.assertIsNone(self.loc.entry("my_cb"), "las claves también se deshacen")
        self.assertEqual(self.ws.history(), [])


class EffectiveViewTests(Case, _Snap):
    def test_delete_culture_removes_only_its_block_and_undo_returns_it(self):
        before = self.snap("common/cultures.txt")
        self.entities.delete(RecordRef("culture", "dominer"))
        data = self.snap("common/cultures.txt").decode("cp1252")
        self.assertNotIn("dominer", data)
        self.assertIn("\tcorlander = {\r\n\t\tcolor = { 20 20 100 }\r\n\t}\r\n}\r\n", data,
                      "el grupo se cierra igual y la otra cultura no cambia")
        self.assertNotIn("dominer", [s.ref.ident for s in self.entities.list("culture")])
        self.ws.undo()
        self.assertEqual(self.snap("common/cultures.txt"), before)
        self.assertIn("dominer", [s.ref.ident for s in self.entities.list("culture")])

    def test_view_follows_a_type_change(self):
        record = self.entities.open(RecordRef("unit", "infantry"))
        with self.ws.transaction("test.undo_edit"):
            record.set("type", "naval")
        self.assertEqual([s.ref.ident for s in self.entities.list("unit", view="land")], [])
        self.assertEqual([s.ref.ident for s in self.entities.list("unit", view="naval")], ["frigate", "infantry"])
        self.ws.undo()
        self.assertEqual([s.ref.ident for s in self.entities.list("unit", view="land")], ["infantry"])

    def test_read_only_catalogues_do_not_warn_about_their_keys(self):
        """Los catálogos de solo lectura conservan sus claves sin avisar (``unknown="keep"``): si avisaran, F7 se
        llenaría de ``unknown_field`` de tecnologías e invenciones del juego."""
        for kind in ("technology", "invention", "ideology", "issue_group", "goods", "building"):
            for summary in self.entities.list(kind):
                with self.subTest(kind=kind, ident=summary.ref.ident):
                    record = self.entities.open(summary.ref)
                    self.assertEqual([p.code for p in record.issues(self.entities.check_context())], [])
        self.assertTrue(self.entities.open(RecordRef("technology", "musket_drill")).unknown(),
                        "sí tiene claves fuera del esquema (activate_unit): se conservan")

    def test_reading_every_list_writes_nothing(self):
        from vic2studio.core.schema import registry

        for schema in registry.all_schemas():
            for summary in self.entities.list(schema.kind):
                record = self.entities.open(summary.ref)
                record.issues(self.entities.check_context())
                record.unknown()
                record.children()
                self.entities.where_used(summary.ref)
                self.entities.can_restore_vanilla(summary.ref)
                self.entities.origin_of(summary.ref)
        self.assertEqual(self.ws.dirty(), [])
        self.assertTrue(self.ws.save().nothing_to_save)
        self.assertFalse((self.game.mod_root / ".vic2studio").exists())


class TombstoneTests(Case, _Snap):
    mod_copies = ("common/governments.txt",)

    def test_duplicate_through_a_tombstone(self):
        with self.ws.transaction("test.undo_delete"):
            self.ws.delete(VPath("common/governments.txt"))
        self.assertEqual(self.entities.origin_of(RecordRef("government", "republic")), "game")
        self.entities.duplicate(RecordRef("government", "republic"), "republic2")
        handle = self.ws.peek(VPath("common/governments.txt"))
        self.assertFalse(handle.deleted, "crear revive el documento con el contenido del juego")
        idents = [s.ref.ident for s in self.entities.list("government")]
        self.assertEqual(idents, ["council", "monarchy", "republic", "republic2"])
        data = self.snap("common/governments.txt").decode("cp1252")
        self.assertIn("republic2 = {\r\n\tliberal = yes", data)


@unittest.skipUnless(vanilla_root(), "sin corpus")
class CorpusLatencyTests(CriteriaCase):
    """Rendimiento en el hilo de la interfaz (nada por encima de 0,5 s sin cursor de espera)."""

    def test_list_and_open_of_the_largest_layouts_are_fast(self):
        project, entities, _, _ = self.open_vanilla()
        for kind, view in (("culture", None), ("casus_belli", None), ("unit", "land"), ("government", None)):
            with self.subTest(kind=kind):
                entities.list(kind, view=view)   # primera lectura (abre los documentos)
                start = time.perf_counter()
                summaries = entities.list(kind, view=view)
                for summary in summaries[:50]:
                    record = entities.open(summary.ref)
                    record.issues(self._ctx(entities))
                elapsed = time.perf_counter() - start
                self.assertLess(elapsed, 0.5, f"{kind}: {elapsed:.2f} s")
        self.assertEqual(project.ws.dirty(), [])


if __name__ == "__main__":
    unittest.main()
