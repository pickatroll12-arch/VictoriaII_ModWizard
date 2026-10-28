"""El resto del núcleo de la iteración 4: disposiciones, tipos ricos, compañeros, vista efectiva tras guardar,
restaurar desde vanilla, validación en segundo plano, docgen y la CLI (ENCARGO_IT4, fase 1).

Todo sobre el minijuego sintético (``SCHEMA_GAME_FILES``); nada del juego real.
"""

from __future__ import annotations

import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
if str(PROJECT_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from vic2studio.core.clausewitz import Severity  # noqa: E402
from vic2studio.core.clausewitz.nodes import ClausewitzDate, Scalar  # noqa: E402
from vic2studio.core.index.builder import build_index  # noqa: E402
from vic2studio.core.locsync import LocSync  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.project.codecs import codec_for, parse_bytes  # noqa: E402
from vic2studio.core.schema import (  # noqa: E402
    Color,
    Entities,
    EntityInUseError,
    InvalidIdentError,
    ListOf,
    RecordRef,
    Text,
)
from vic2studio.core.schema.companions import ActivateUnit, EditContext, UnitNamesSlot  # noqa: E402
from vic2studio.core.schema.record import ReadOnlySchemaError  # noqa: E402
from vic2studio.core.schema.validate import schema_problems  # noqa: E402
from vic2studio.core.validate import build_context  # noqa: E402
from vic2studio.core.vfs.paths import VPath  # noqa: E402

from _layers import isolate_appdirs  # noqa: E402
from _minigame import SCHEMA_GAME_FILES, UNIT_NAMES_COUNTRY, build_minigame  # noqa: E402


class Case(unittest.TestCase):
    mod_copies: tuple = ()
    extra_game: dict = {}
    extra_mod: dict = {}

    def setUp(self):
        isolate_appdirs(self)
        game_files = dict(SCHEMA_GAME_FILES)
        game_files.update(self.extra_game)
        game = build_minigame(mod=True, game_files=game_files, mod_copies=self.mod_copies,
                              mod_files=self.extra_mod)
        self.addCleanup(game.cleanup)
        self.game = game
        self.project = Project.open(game.game_root, game.mod_root)
        self.addCleanup(self.project.close, discard=True)
        self.ws = self.project.ws
        self.loc = LocSync(self.ws, self.project.vfs, prefix=self.project.settings.prefix)
        self.entities = Entities(self.ws, build_index(self.project.vfs.snapshot(), None, {}), self.loc)

    def idents(self, kind, **kwargs):
        return [item.ref.ident for item in self.entities.list(kind, **kwargs)]

    def text_of(self, rel) -> str:
        handle = self.ws.open(rel)
        return codec_for(handle.kind).snapshot(handle.model).decode("cp1252")


class RichTypesTests(unittest.TestCase):
    def test_list_edits_in_place(self):
        block = parse_bytes(b'n = {\r\n\t"Ana Mar" Luis\r\n\tPedro\r\n}\r\n').document
        entry = block.find("n")
        value = ListOf(Text(quoted=False))
        self.assertEqual(value.read(entry.value), ["Ana Mar", "Luis", "Pedro"])
        entry.value = value.write(["Ana Mar", "Luis", "Pedro", "Juan Luis"], entry.value)
        from vic2studio.core.clausewitz.serializer import to_source

        self.assertEqual(to_source(block).replace("\r\n", "\n"),
                         'n = {\n\t"Ana Mar" Luis\n\tPedro "Juan Luis"\n}\n',
                         "añadir un nombre no reescribe los demás y uno con espacio va entre comillas")
        entry.value = value.write(["Luis", "Pedro", "Juan Luis"], entry.value)
        self.assertNotIn("Ana", to_source(block))

    def test_list_unique_rejects_repeats(self):
        with self.assertRaises(ValueError):
            ListOf(Text(), unique=True).write(["a", "a"], None)

    def test_color(self):
        block = parse_bytes(b"c = { 10 20 30 }\n").document
        entry = block.find("c")
        self.assertEqual(Color().read(entry.value), (10, 20, 30))
        entry.value = Color().write((10, 99, 30), entry.value)
        from vic2studio.core.clausewitz.serializer import to_source

        self.assertEqual(to_source(block), "c = { 10 99 30 }\n")
        with self.assertRaises(ValueError):
            Color().write((10, 300, 0), None)
        with self.assertRaises(ValueError):
            Color().read(Scalar("x"))
        self.assertEqual(Color(scale=1.0).read(parse_bytes(b"c = { 0.5 0 1 }").document.find("c").value),
                         (0.5, 0.0, 1.0))

    def test_text_auto_quotes(self):
        self.assertTrue(Text(quoted=False).write("con espacio", None).quoted)
        self.assertFalse(Text(quoted=False).write("palabra", None).quoted)


class LayoutTests(Case):
    def test_lists_of_every_editable_schema(self):
        self.assertEqual(self.idents("casus_belli"), ["conquer_land", "free_people", "humble_rival"],
                         "peace_order no es un CB")
        self.assertEqual(self.idents("bookmark"), ["MG_LATE", "MG_START"])
        self.assertEqual(self.idents("culture_group"), ["north_folk", "south_folk"])
        self.assertEqual(self.idents("culture"), ["alander", "borlander", "corlander", "dominer"])
        self.assertEqual(self.idents("event_modifier"), ["bad_winter", "good_harvest"],
                         "los modificadores de otros archivos no son de evento")
        groups = {item.ref.ident: item.parent for item in self.entities.list("culture")}
        self.assertEqual(groups["dominer"], "south_folk")
        self.assertEqual(self.entities.parent(RecordRef("culture", "alander")), "north_folk")

    def test_children_of_a_group(self):
        group = self.entities.open(RecordRef("culture_group", "north_folk"))
        self.assertEqual([child.ref.ident for child in group.children()], ["alander", "borlander"])
        self.assertEqual(group.unknown(), [], "las culturas no son claves desconocidas del grupo")
        self.assertEqual(group.get("leader"), "european")

    def test_create_culture_goes_to_the_end_of_its_group(self):
        ref = self.entities.create("culture", "newfolk", {"group": "north_folk", "color": (1, 2, 3)})
        group = self.entities.open(RecordRef("culture_group", "north_folk"))
        self.assertEqual([child.ref.ident for child in group.children()], ["alander", "borlander", "newfolk"])
        self.assertEqual(self.entities.open(ref).get("color"), (1, 2, 3))
        self.assertIsNotNone(self.loc.entry("newfolk"))
        self.ws.undo()
        self.assertEqual(self.ws.dirty(), [])

    def test_create_culture_without_group_changes_nothing(self):
        for values in ({}, {"group": "nope"}):
            with self.subTest(values=values):
                with self.assertRaises(InvalidIdentError) as caught:
                    self.entities.create("culture", "newfolk", values)
                self.assertEqual(caught.exception.code, "no_group")
                self.assertEqual(self.ws.dirty(), [])
                self.assertEqual(self.ws.history(), [])

    def test_duplicate_culture_stays_in_its_group_with_its_format(self):
        self.entities.duplicate(RecordRef("culture", "dominer"), "dominer2")
        self.assertEqual(self.entities.parent(RecordRef("culture", "dominer2")), "south_folk")
        text = self.text_of("common/cultures.txt")
        self.assertIn("\tdominer2 = {\r\n\t\tcolor = { 90 90 90 }\r\n\t\tprimary = D01\r\n\t}", text)

    def test_bookmark_create_and_duplicate(self):
        ref = self.entities.create("bookmark", "MG_NEW", {"date": ClausewitzDate(1850, 1, 1)})
        text = self.text_of("common/bookmarks.txt")
        self.assertTrue(text.rstrip().endswith("}"))
        self.assertIn('name = "MG_NEW"', text)
        self.assertIn('desc = "MG_NEW_DESC"', text)
        self.assertEqual(self.entities.open(ref).get("date"), ClausewitzDate(1850, 1, 1))
        self.assertIsNotNone(self.loc.entry("MG_NEW"))
        self.entities.duplicate(RecordRef("bookmark", "MG_START"), "MG_COPY")
        self.assertIn('name = "MG_COPY"', self.text_of("common/bookmarks.txt"), "la copia lleva su nombre")
        self.assertIn("MG_COPY", self.idents("bookmark"))
        self.entities.delete(RecordRef("bookmark", "MG_COPY"))
        self.assertNotIn("MG_COPY", self.idents("bookmark"))
        self.assertIn("MG_START", self.idents("bookmark"))

    def test_event_modifier_open_catalog(self):
        record = self.entities.open(RecordRef("event_modifier", "bad_winter"))
        self.assertEqual(record.dynamic("effects"), {"pop_militancy_modifier": 0.02, "local_supply": -0.5})
        self.assertEqual(record.unknown(), [])
        with self.ws.transaction("test.undo_edit"):
            record.set_dynamic("effects", "prestige", 2.0)
        self.assertIn("\tprestige = 2\r\n}", self.text_of("common/event_modifiers.txt"))

    def test_read_only_schemas_refuse_changes(self):
        self.assertEqual(self.idents("technology"), ["musket_drill", "rifled_drill"])
        self.assertEqual(self.idents("ideology"), ["conservative", "liberal", "socialist"])
        self.assertEqual(self.idents("goods"), ["fish", "grain"])
        self.assertEqual(self.idents("building"), ["fort"])
        self.assertIn("economic_policy", self.idents("issue_group"))
        with self.assertRaises(ReadOnlySchemaError):
            self.entities.create("technology", "steam_drill")
        with self.assertRaises(ReadOnlySchemaError):
            self.entities.delete(RecordRef("goods", "fish"))
        self.assertEqual(self.ws.history(), [])


class EffectiveAfterSaveTests(Case):
    """Decisión 4: crear, guardar y volver a listar sigue mostrando la entidad aunque el índice no la tenga."""

    def test_create_save_list_with_a_stale_index(self):
        self.entities.create("casus_belli", "my_cb")
        self.entities.duplicate(RecordRef("unit", "infantry"), "my_unit")
        report = self.ws.save()
        self.assertTrue(report.ok)
        self.assertEqual(self.ws.dirty(), [])
        self.assertIsNone(self.entities.index.get("cb", "my_cb"), "el índice aún no lo sabe")
        self.assertIn("my_cb", self.idents("casus_belli"))
        self.assertIn("my_unit", self.idents("unit", view="land"))
        self.assertEqual(self.entities.open(RecordRef("unit", "my_unit")).get("type"), "land")

    def test_after_eviction_the_index_is_up_to_date(self):
        self.entities.create("casus_belli", "my_cb")
        self.ws.save()
        self.entities.index = build_index(self.project.vfs.snapshot(), None, {})
        self.assertIn("my_cb", self.idents("casus_belli"))


class RestoreVanillaTests(Case):
    """Límite de CONTINUAR §6: borrar la copia del mod de algo que también está en vanilla."""

    mod_copies = ("units/infantry.txt", "common/governments.txt")

    def test_deleting_the_mod_copy_shows_the_game_file(self):
        with self.ws.transaction("test.undo_edit"):
            record = self.entities.open(RecordRef("unit", "infantry"))
            record.set("attack", 9.0)
        self.ws.save()
        self.entities.restore_vanilla(RecordRef("unit", "infantry"))
        self.assertTrue(self.ws.peek(VPath("units/infantry.txt")).deleted)
        self.assertIn("infantry", self.idents("unit"), "lo borrado del mod deja ver el del juego")
        self.assertIn("infantry", self.idents("unit", view="land"))
        record = self.entities.open(RecordRef("unit", "infantry"))
        self.assertIsNone(record.get("attack", None), "se ve el del juego, sin el ataque del mod")
        self.assertEqual(self.entities.origin_of(RecordRef("unit", "infantry")), "game")
        # Editarlo revive el documento con el contenido del juego más el cambio.
        with self.ws.transaction("test.undo_edit"):
            record.set("attack", 3.0)
        handle = self.ws.peek(VPath("units/infantry.txt"))
        self.assertFalse(handle.deleted)
        self.assertIn("attack = 3", self.text_of("units/infantry.txt"))
        self.assertIn("sprite = Infantry", self.text_of("units/infantry.txt"))
        self.ws.undo()
        self.ws.undo()
        self.assertEqual(self.entities.open(RecordRef("unit", "infantry")).get("attack"), 9.0)

    def test_restore_a_block_of_a_single_file(self):
        with self.ws.transaction("test.undo_edit"):
            self.entities.open(RecordRef("government", "republic")).set("duration", 12)
            self.entities.open(RecordRef("government", "monarchy")).set("election", True)
        self.ws.save()
        self.assertTrue(self.entities.can_restore_vanilla(RecordRef("government", "republic")))
        self.entities.restore_vanilla(RecordRef("government", "republic"))
        self.assertEqual(self.entities.open(RecordRef("government", "republic")).get("duration"), 48)
        self.assertTrue(self.entities.open(RecordRef("government", "monarchy")).get("election"),
                        "solo cambia el bloque restaurado")
        self.assertEqual(len([s for s in self.ws.history() if s[0] == "undo.restore_vanilla"]), 1)
        self.ws.undo()
        self.assertEqual(self.entities.open(RecordRef("government", "republic")).get("duration"), 12)

    def test_unsaved_game_document_reverts_clean(self):
        with self.ws.transaction("test.undo_edit"):
            self.entities.open(RecordRef("unit", "frigate")).set("hull", 50)
        self.entities.restore_vanilla(RecordRef("unit", "frigate"))
        self.assertEqual(self.ws.dirty(), [] if not self.mod_copies else [h for h in self.ws.dirty()
                                                                         if h.rel.name != "frigate.txt"])
        self.assertFalse(self.entities.can_restore_vanilla(RecordRef("unit", "frigate")))
        with self.assertRaises(KeyError):
            self.entities.restore_vanilla(RecordRef("unit", "frigate"))


class CompanionTests(Case):
    extra_game = {"common/countries/Aland.txt": UNIT_NAMES_COUNTRY}

    def ctx(self):
        return EditContext(self.ws, self.entities.index, self.loc)

    def test_activate_unit_sources_and_never_active(self):
        infantry = self.entities.open(RecordRef("unit", "infantry"))
        self.assertEqual([use.name for use in ActivateUnit().sources(self.ctx(), infantry)], ["infantry"])
        self.assertEqual([p.code for p in infantry.issues(self.entities.check_context())
                          if p.code == "unit_never_active"], [])
        ref = self.entities.duplicate(RecordRef("unit", "infantry"), "my_unit")
        record = self.entities.open(ref)
        never = [p for p in record.issues(self.entities.check_context()) if p.code == "unit_never_active"]
        self.assertEqual(len(never), 1, "active = no y nada la activa")
        self.assertIs(never[0].severity, Severity.INFO)
        with self.ws.transaction("test.undo_edit"):
            ActivateUnit().activate_in(self.ctx(), record, "technology", "rifled_drill")
        self.assertIn("activate_unit = my_unit", self.text_of("technologies/army_tech.txt"))
        with self.ws.transaction("test.undo_edit"):
            ActivateUnit().activate_in(self.ctx(), record, "invention", "field_kitchens")
        self.assertIn("effect = { activate_unit = frigate activate_unit = my_unit }",
                      self.text_of("inventions/army_inventions.txt"))

    def test_unit_names_slot(self):
        frigate = self.entities.open(RecordRef("unit", "frigate"))
        slot = UnitNamesSlot()
        self.assertEqual(slot.candidates(self.ctx(), frigate), [], "Aland ya tiene frigate")
        ref = self.entities.duplicate(RecordRef("unit", "frigate"), "corvette")
        corvette = self.entities.open(ref)
        self.assertEqual(slot.candidates(self.ctx(), corvette), [VPath("common/countries/Aland.txt")])
        self.assertEqual(self.ws.history()[0][0], "undo.duplicate_unit", "crear no cambia unit_names solo")
        with self.ws.transaction("test.undo_edit"):
            self.assertEqual(slot.add_to(self.ctx(), corvette, slot.candidates(self.ctx(), corvette)), 1)
        self.assertIn("corvette = {", self.text_of("common/countries/Aland.txt"))
        self.assertEqual(slot.candidates(self.ctx(), self.entities.open(RecordRef("unit", "infantry"))), [],
                         "solo las navales")

    def test_rebel_matrix_rows_and_targets(self):
        from vic2studio.core.schema import MappingTable

        table = MappingTable("common/rebel_types.txt", table="government")
        self.assertEqual(table.rows(self.ctx(), "council"), [("free_rebels", "council"), ("loyal_rebels", None)])
        with self.ws.transaction("test.undo_edit"):
            table.set_target(self.ctx(), "council", "loyal_rebels", "monarchy")
        self.assertEqual(table.rows(self.ctx(), "council")[1], ("loyal_rebels", "monarchy"))

    def test_delete_ignores_own_references_but_not_real_uses(self):
        self.entities.create("government", "junta")
        self.entities.index = build_index(self.project.vfs.snapshot(), None,
                                          {h.rel: codec_for(h.kind).snapshot(h.model) for h in self.ws.dirty()})
        self.assertTrue(any(use.role == "rebel_government" for use in self.entities.index.refs_to("government",
                                                                                                    "junta")))
        self.assertEqual(self.entities.where_used(RecordRef("government", "junta")), [])
        self.entities.delete(RecordRef("government", "junta"))
        self.assertNotIn("junta", self.text_of("common/rebel_types.txt"))
        with self.assertRaises(EntityInUseError):
            self.entities.delete(RecordRef("government", "monarchy"))   # AAA lo usa en su historia


class BackgroundValidationTests(Case):
    """Decisión 3: los problemas de esquema se calculan sobre la instantánea, sin el Workspace (I12)."""

    def problems(self):
        snapshot = self.project.vfs.snapshot()
        overrides = {h.rel: (None if h.deleted else codec_for(h.kind).snapshot(h.model)) for h in self.ws.dirty()}
        index = build_index(snapshot, None, overrides)
        return schema_problems(build_context(snapshot, index, overrides))

    def test_schema_problems_on_unsaved_changes(self):
        before = self.problems()
        self.assertTrue(all(p.inherited for p in before), "lo del juego base es heredado (I11)")
        record = self.entities.open(RecordRef("unit", "infantry"))
        with self.ws.transaction("test.undo_edit"):
            self.ws.touch(record.handle)
            record.block.append("attack", "abc")
            record.block.append("mystery", "1")
        found = {(p.code, p.field) for p in self.problems() if not p.inherited}
        self.assertIn(("bad_type", ("attack",)), found)
        self.assertIn(("unknown_field", ("mystery",)), found)
        self.assertEqual(self.ws.history()[0][0], "test.undo_edit")
        self.assertEqual(len(self.ws.history()), 1, "validar no añade pasos ni toca documentos (I4)")

    def test_bookmark_outside_defines_in_background(self):
        self.entities.create("bookmark", "MG_FAR", {"date": ClausewitzDate(1990, 1, 1)})
        codes = [p.code for p in self.problems() if not p.inherited]
        self.assertIn("bookmark_date_outside_defines", codes)
        live = self.entities.open(RecordRef("bookmark", "MG_FAR")).issues(self.entities.check_context())
        self.assertIn("bookmark_date_outside_defines", [p.code for p in live])


class DefinesTests(Case):
    def test_set_end_date_only_touches_its_token(self):
        from vic2studio.core.schemas.bookmark import define_date, read_defines, set_define_date

        before = self.text_of("common/defines.lua")
        with self.ws.transaction("test.undo_edit"):
            set_define_date(self.ws, "end_date", ClausewitzDate(2000, 1, 1))
        after = self.text_of("common/defines.lua")
        self.assertEqual(after, before.replace("'1935.12.31'", "'2000.1.1'"))
        self.assertEqual(define_date(read_defines(self.ws), "end_date"), ClausewitzDate(2000, 1, 1))
        report = self.ws.save()
        self.assertTrue(report.ok)
        self.assertEqual((self.game.mod_root / "common" / "defines.lua").read_bytes().decode("cp1252"), after)
        self.ws.undo()
        self.assertEqual(define_date(read_defines(self.ws), "end_date"), ClausewitzDate(1935, 12, 31))


class CliTests(Case):
    def run_cli(self, *args) -> tuple[int, str]:
        from vic2studio.core.schema.__main__ import main

        out = io.StringIO()
        with redirect_stdout(out):
            code = main(list(args))
        return code, out.getvalue()

    def test_list_show_doc(self):
        code, out = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("casus_belli\tCasus belli\twar:cb", out)
        code, out = self.run_cli("show", "bookmark", "--lang", "en")
        self.assertIn("# Start dates (`bookmark`)", out)
        code, out = self.run_cli("doc", "--lang", "es")
        self.assertIn("# Referencia de esquemas", out)
        self.assertIn("(`culture`)", out)

    def test_check_writes_nothing(self):
        before = self.game.tree(self.game.mod_root)
        code, out = self.run_cli("check", str(self.game.game_root), str(self.game.mod_root), "--lang", "en")
        self.assertEqual(code, 0, out)
        self.assertIn("records from", out)
        self.assertEqual(self.game.tree(self.game.mod_root), before, "check no escribe nada (I4)")

    def test_module_runs(self):
        done = subprocess.run([sys.executable, "-m", "vic2studio.core.schema", "list"], capture_output=True,
                              text=True, timeout=120, env={"PYTHONPATH": str(PROJECT_ROOT / "src"),
                                                           "PATH": "", "SYSTEMROOT": ""})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("government", done.stdout)


if __name__ == "__main__":
    unittest.main()
