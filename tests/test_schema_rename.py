"""Renombrado seguro (wizard §15), mover una cultura de grupo y crear un grupo (§14.13).

Sobre el minijuego sintético: un CB con un uso en una guerra, un gobierno con sus 14 tablas de rebeldes, una
unidad con ``activate_unit`` y sus claves ``<id>`` e ``<id>_short``, una cultura con ``primary`` y ``union`` y un
bookmark, cuyo id es el campo ``name``. Con corpus, un CB y un gobierno de vanilla sobre un mod vacío. Cada
prueba compara bytes: renombrar cambia solo el token del id en cada sitio (I3) y un deshacer lo devuelve todo (I5).
"""

from __future__ import annotations

import dataclasses
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
if str(PROJECT_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from vic2studio.core.index.builder import build_index  # noqa: E402
from vic2studio.core.index.model import SymbolRef  # noqa: E402
from vic2studio.core.locsync import LocSync  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.schema import (  # noqa: E402
    AppendToList,
    Entities,
    InvalidIdentError,
    LocSpec,
    MappingTable,
    RecordRef,
    RenameBlockedError,
    registry,
)
from vic2studio.core.schema.companions import ActivateUnit, EditContext, UnitNamesSlot  # noqa: E402
from vic2studio.core.schema.record import ReadOnlySchemaError  # noqa: E402
from vic2studio.core.schema.rename import LOC_COPY, LOC_KEPT, LOC_RENAME, ROLE_DEFINITION  # noqa: E402
from vic2studio.core.texts import load_texts  # noqa: E402
from vic2studio.core.vfs.paths import VPath  # noqa: E402

from _corpus import vanilla_root  # noqa: E402
from _layers import isolate_appdirs  # noqa: E402
from _minigame import CB_TYPES, SCHEMA_GAME_FILES, UNIT_NAMES_COUNTRY, _crlf, _loc, build_minigame  # noqa: E402

CB_FILE = "common/cb_types.txt"
WAR_FILE = "history/wars/Old War.txt"
GOVERNMENTS = "common/governments.txt"
REBELS = "common/rebel_types.txt"
CULTURES = "common/cultures.txt"
BOOKMARKS = "common/bookmarks.txt"


def changed_lines(before: bytes, after: bytes) -> list[int]:
    """Números (desde 1) de las líneas que difieren; los dos textos deben tener las mismas líneas."""
    old, new = before.split(b"\n"), after.split(b"\n")
    assert len(old) == len(new), f"cambia el número de líneas: {len(old)} → {len(new)}"
    return [number for number, (a, b) in enumerate(zip(old, new), 1) if a != b]


def swap_token(line: bytes, old: str, new: str) -> bytes:
    """``line`` con ``old`` sustituido por ``new`` solo donde es una palabra entera."""
    return re.sub(rb"(?<![A-Za-z0-9_])" + re.escape(old.encode()) + rb"(?![A-Za-z0-9_])", new.encode(), line)


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

    def data(self, rel) -> bytes:
        """Los bytes actuales del documento (con lo sin guardar)."""
        handle = self.ws.open(rel)
        return codec_for(handle.kind).snapshot(handle.model)

    def game_data(self, rel) -> bytes:
        return self.game.game(rel).read_bytes()

    def rename(self, kind, old, new):
        return self.entities.rename(RecordRef(kind, old), new)

    def plan(self, kind, old, new):
        return self.entities.rename_plan(RecordRef(kind, old), new)

    def put(self, rel, text: str) -> None:
        """Deja un documento nuevo o cambiado sin guardar, que el índice de la prueba no conoce."""
        with self.ws.transaction("undo.test_put"):
            self.ws.replace_text(self.ws.open(rel, create=True), _crlf(text).encode("cp1252"))

    def dirty(self) -> list[str]:
        return sorted(str(handle.rel) for handle in self.ws.dirty())

    def assert_untouched(self, tree_before=None):
        """Nada cambió: ni documentos sucios, ni pasos de deshacer, ni el disco del mod."""
        self.assertEqual(self.dirty(), [])
        self.assertEqual(self.ws.history(), [])
        if tree_before is not None:
            self.assertEqual(self.game.tree(), tree_before)

    def assert_translated(self, error):
        """El motivo tiene texto propio en ES y EN (no la clave ni el mismo texto)."""
        spanish, english = error.message("es"), error.message("en")
        self.assertNotEqual(spanish, english)
        for message in (spanish, english):
            self.assertNotIn("schema.", message)
            self.assertNotIn("{", message)


class CasusBelliRenameTests(Case):
    def test_it_changes_only_the_id_tokens_of_the_definition_and_its_uses(self):
        ref = self.rename("casus_belli", "conquer_land", "seize_land")
        self.assertEqual(ref, RecordRef("casus_belli", "seize_land", VPath.of(CB_FILE)))
        before, after = self.game_data(CB_FILE), self.data(CB_FILE)
        self.assertEqual(changed_lines(before, after), [3, 9], "peace_order y la clave del bloque")
        # war_name = CONQUER_LAND_WAR no es el id: sigue igual, como los comentarios y la sangría.
        self.assertEqual(after, before.replace(b"conquer_land", b"seize_land"))
        self.assertIn(b"war_name = CONQUER_LAND_WAR", after)
        war_before, war_after = self.game_data(WAR_FILE), self.data(WAR_FILE)
        self.assertEqual(changed_lines(war_before, war_after), [6])
        self.assertEqual(war_after, war_before.replace(b"casus_belli = conquer_land", b"casus_belli = seize_land"))
        self.assertEqual(self.idents("casus_belli"), ["free_people", "humble_rival", "seize_land"])
        self.assertEqual(self.entities.open(ref).get("months"), 12, "el bloque es el mismo, con otro id")

    def test_one_undo_step_returns_the_original_bytes(self):
        self.rename("casus_belli", "conquer_land", "seize_land")
        self.assertEqual(self.ws.history(), [("undo.rename_casus_belli", {
            "kind": "casus_belli", "ident": "conquer_land", "new": "seize_land"})], "una sola transacción (I5)")
        self.assertEqual(self.dirty(), [CB_FILE, WAR_FILE, "localisation/00_TESTMOD_cb.csv"])
        renamed = self.data(CB_FILE)
        self.ws.undo()
        self.assertEqual(self.dirty(), [], "un solo deshacer lo devuelve todo")
        self.assertEqual(self.data(CB_FILE), self.game_data(CB_FILE))
        self.assertEqual(self.data(WAR_FILE), self.game_data(WAR_FILE))
        self.assertIsNone(self.loc.entry("seize_land"))
        self.assertEqual(self.idents("casus_belli"), ["conquer_land", "free_people", "humble_rival"])
        self.ws.redo()
        self.assertEqual(self.data(CB_FILE), renamed)
        self.assertIsNotNone(self.loc.entry("seize_land"))

    def test_saving_copies_to_the_mod_only_the_files_it_changed(self):
        game_before = self.game.game_tree()
        mod_before = set(self.game.tree())
        self.rename("casus_belli", "conquer_land", "seize_land")
        self.project.save()
        created = {rel for rel in set(self.game.tree()) - mod_before if not rel.startswith(".vic2studio/")}
        self.assertEqual(created, {CB_FILE, WAR_FILE, "localisation/00_TESTMOD_cb.csv"})
        self.assertEqual(self.game.mod(CB_FILE).read_bytes(),
                         self.game_data(CB_FILE).replace(b"conquer_land", b"seize_land"))
        self.assertEqual(changed_lines(self.game_data(WAR_FILE), self.game.mod(WAR_FILE).read_bytes()), [6])
        self.assertEqual(self.game.game_tree(), game_before, "el juego base no se toca (I1)")

    def test_keys_of_the_game_are_copied_with_every_language(self):
        plan = self.plan("casus_belli", "conquer_land", "seize_land")
        self.assertEqual([(c.old, c.new, c.action, str(c.rel)) for c in plan.loc],
                         [("conquer_land", "seize_land", LOC_COPY, "localisation/minigame.csv")])
        self.rename("casus_belli", "conquer_land", "seize_land")
        self.assertEqual([self.loc.text("seize_land", lang) for lang in ("en", "fr", "de", "es")],
                         ["Conquer land", "Conquérir", "Erobern", "Conquistar"])
        self.assertEqual(str(self.loc.where("seize_land")[0]), "localisation/00_TESTMOD_cb.csv")
        self.assertEqual(self.loc.text("conquer_land", "en"), "Conquer land", "la fila del juego no se toca")

    def test_keys_of_the_mod_are_renamed_in_place(self):
        keys = ("my_cb", "my_cb_desc", "my_cb_setup", "my_cb_short")
        self.entities.create("casus_belli", "my_cb", texts={key: {"en": f"EN {key}", "es": f"ES {key}"}
                                                            for key in keys})
        rows_before = self.data("localisation/00_TESTMOD_cb.csv").count(b"\n")
        plan = self.plan("casus_belli", "my_cb", "our_cb")
        self.assertEqual([(c.old, c.new, c.action) for c in plan.loc],
                         [(key, key.replace("my_cb", "our_cb"), LOC_RENAME) for key in keys])
        self.rename("casus_belli", "my_cb", "our_cb")
        for key in keys:
            self.assertIsNone(self.loc.entry(key), f"{key} se quedó atrás")
            new_key = key.replace("my_cb", "our_cb")
            self.assertEqual((self.loc.text(new_key, "en"), self.loc.text(new_key, "es")), (f"EN {key}", f"ES {key}"))
        self.assertEqual(self.data("localisation/00_TESTMOD_cb.csv").count(b"\n"), rows_before,
                         "las filas cambian de clave en su sitio, sin filas nuevas")
        self.assertEqual(len(self.ws.history()), 2, "crear y renombrar: un paso cada uno")
        self.ws.undo()
        self.assertEqual([self.loc.text(key, "en") for key in keys], [f"EN {key}" for key in keys])
        self.assertIn(b"\tmy_cb\r\n}", self.data(CB_FILE))

    def test_shared_keys_are_left_alone(self):
        schema = registry.get("casus_belli")
        shared = dataclasses.replace(schema, loc=schema.loc + (LocSpec("NORMAL_{id}", "cb", shared=True),))
        registry._schemas["casus_belli"] = shared
        self.addCleanup(registry._schemas.__setitem__, "casus_belli", schema)
        self.entities.create("casus_belli", "my_cb", texts={"NORMAL_my_cb": {"en": "The war"}})
        plan = self.plan("casus_belli", "my_cb", "our_cb")
        self.assertNotIn("NORMAL_my_cb", [change.old for change in plan.loc])
        self.rename("casus_belli", "my_cb", "our_cb")
        self.assertEqual(self.loc.text("NORMAL_my_cb", "en"), "The war", "una clave compartida no se renombra")
        self.assertIsNone(self.loc.entry("NORMAL_our_cb"))
        self.assertIsNotNone(self.loc.entry("our_cb"))

    def test_an_existing_new_key_is_kept_and_the_old_one_stays(self):
        self.entities.create("casus_belli", "my_cb", texts={"my_cb": {"en": "Mine"}})
        with self.ws.transaction("undo.test_put"):
            self.loc.ensure({"our_cb": {"en": "Already here"}}, area="cb")
        plan = self.plan("casus_belli", "my_cb", "our_cb")
        self.assertEqual([(c.old, c.action) for c in plan.loc if c.old == "my_cb"], [("my_cb", LOC_KEPT)])
        self.rename("casus_belli", "my_cb", "our_cb")
        self.assertEqual(self.loc.text("our_cb", "en"), "Already here", "no se pisa un texto que ya existía")
        self.assertEqual(self.loc.text("my_cb", "en"), "Mine")
        self.assertIsNotNone(self.loc.entry("our_cb_desc"), "las demás claves sí cambian")

    def test_uses_in_unsaved_documents_are_rewritten_though_the_index_is_stale(self):
        new_war = "history/wars/New War.txt"
        self.put(new_war, 'name = "New War"\n1840.1.1 = {\n\twar_goal = {\n\t\tcasus_belli = conquer_land\n\t}\n'
                          "\twar_goal = {\n\t\tcasus_belli = conquer_land   # otra vez\n\t}\n"
                          "\twar_goal = {\n\t\tcasus_belli = free_people\n\t}\n}\n")
        before = self.data(new_war)
        self.assertEqual(self.entities.index.refs_from(VPath.of(new_war)), [], "el índice no lo conoce")
        plan = self.plan("casus_belli", "conquer_land", "seize_land")
        new_file = next(item for item in plan.files if str(item.rel) == new_war)
        self.assertEqual(([use.line for use in new_file.uses], new_file.from_game), ([4, 7], False))
        self.rename("casus_belli", "conquer_land", "seize_land")
        after = self.data(new_war)
        self.assertEqual(changed_lines(before, after), [4, 7])
        self.assertEqual(after, before.replace(b"conquer_land", b"seize_land"))

    def test_renaming_through_a_tombstone_revives_the_file_of_the_game(self):
        game = build_minigame(mod=True, game_files=dict(SCHEMA_GAME_FILES), mod_copies=(CB_FILE,))
        self.addCleanup(game.cleanup)
        project = Project.open(game.game_root, game.mod_root)
        self.addCleanup(project.close, discard=True)
        loc = LocSync(project.ws, project.vfs, prefix=project.settings.prefix)
        entities = Entities(project.ws, build_index(project.vfs.snapshot(), None, {}), loc)
        with project.ws.transaction("undo.test_put"):
            project.ws.delete(CB_FILE)
        plan = entities.rename_plan(RecordRef("casus_belli", "conquer_land"), "seize_land")
        self.assertIn(VPath.of(CB_FILE), plan.copies, "lo que se ve es el archivo del juego")
        self.assertTrue(project.ws.peek(CB_FILE).deleted, "el plan no revive nada (I4)")
        entities.rename(RecordRef("casus_belli", "conquer_land"), "seize_land")
        handle = project.ws.open(CB_FILE)
        self.assertEqual(codec_for(handle.kind).snapshot(handle.model),
                         game.game(CB_FILE).read_bytes().replace(b"conquer_land", b"seize_land"))


class OwnKeyUsedElsewhereTests(Case):
    # Un CB del mod con sus claves en el mod, y un evento del mod que usa una de ellas como título.
    extra_mod = {
        CB_FILE: CB_TYPES.replace("\tannex\r\n", "\tannex\r\n\town_cb\r\n")
        + _crlf("\nown_cb = {\n\tsprite_index = 4\n\tmonths = 9\n}\n"),
        "localisation/mod_texts.csv": _loc([("own_cb", "Own war", "Guerra propia"),
                                           ("own_cb_desc", "Our cause", "Nuestra causa")]),
        "events/mod_events.txt": _crlf('country_event = {\n\tid = 2001\n\ttitle = "own_cb_desc"\n'
                                       '\tdesc = "own_cb_desc"\n\tis_triggered_only = yes\n}\n'),
    }

    def test_a_key_that_something_else_names_is_copied_not_moved(self):
        plan = self.plan("casus_belli", "own_cb", "new_cb")
        self.assertEqual([(c.old, c.action) for c in plan.loc], [("own_cb", LOC_RENAME), ("own_cb_desc", LOC_COPY)])
        self.rename("casus_belli", "own_cb", "new_cb")
        self.assertIsNone(self.loc.entry("own_cb"))
        self.assertEqual(self.loc.text("new_cb", "es"), "Guerra propia")
        self.assertEqual(self.loc.text("own_cb_desc", "es"), "Nuestra causa", "el título del evento sigue teniendo texto")
        self.assertEqual(self.loc.text("new_cb_desc", "es"), "Nuestra causa")
        self.assertEqual(self.data("events/mod_events.txt"), self.game.mod("events/mod_events.txt").read_bytes())


def rebel_tables(count: int = 14) -> str:
    """``count`` tipos de rebelde inventados, cada uno con su tabla ``government`` (H16)."""
    parts = []
    for number in range(count):
        target = "monarchy" if number % 2 else "republic"
        parts.append(f"rebels_{number:02d} = {{\n\ticon = {number}\n\tgovernment = {{\n"
                     f"\t\tmonarchy = {target}\n\t\trepublic = monarchy   # vuelve el rey\n"
                     f"\t\tcouncil = council\n\t}}\n}}\n")
    return _crlf("".join(parts))


class GovernmentRenameTests(Case):
    extra_game = {
        REBELS: rebel_tables(),
        "localisation/minigame_governments.csv": _loc([("monarchy", "Monarchy", "Monarquía"),
                                                       ("monarchy_ruler", "King", "Rey")]),
    }

    def test_the_fourteen_tables_the_history_and_the_definition_follow(self):
        ref = self.rename("government", "monarchy", "kingdom")
        self.assertEqual(ref.ident, "kingdom")
        before, after = self.game_data(GOVERNMENTS), self.data(GOVERNMENTS)
        self.assertEqual(changed_lines(before, after), [1])
        self.assertIn(b"flagType = monarchy", after, "el tipo de bandera no es un uso del gobierno")
        self.assertEqual(after, before.replace(b"monarchy = {", b"kingdom = {"))
        rebels_before, rebels_after = self.game_data(REBELS), self.data(REBELS)
        self.assertEqual(rebels_after, rebels_before.replace(b"monarchy", b"kingdom"),
                         "las filas y los destinos de las 14 tablas, con sus comentarios")
        self.assertEqual(rebels_after.count(b"kingdom"), 14 * 2 + 7)
        self.assertEqual(len(changed_lines(rebels_before, rebels_after)), 28)
        history = "history/countries/AAA - Aland.txt"
        self.assertEqual(self.data(history), self.game_data(history).replace(b"government = monarchy",
                                                                             b"government = kingdom"))
        self.assertEqual(self.idents("government"), ["council", "kingdom", "republic"])
        self.assertEqual([self.loc.text(key, "es") for key in ("kingdom", "kingdom_ruler")], ["Monarquía", "Rey"])
        self.assertEqual(len(self.ws.history()), 1)
        self.ws.undo()
        for rel in (GOVERNMENTS, REBELS, history):
            self.assertEqual(self.data(rel), self.game_data(rel), rel)
        self.assertEqual(self.dirty(), [])

    def test_the_plan_groups_the_uses_by_file(self):
        tree = self.game.tree()
        plan = self.plan("government", "monarchy", "kingdom")
        self.assertIsNone(plan.error)
        self.assertTrue(plan.allowed)
        self.assertEqual([str(item.rel) for item in plan.files],
                         [GOVERNMENTS, REBELS, "history/countries/AAA - Aland.txt"])
        definition, rebels, history = plan.files
        self.assertEqual([(use.line, use.role) for use in definition.uses], [(1, ROLE_DEFINITION)])
        self.assertEqual(len(rebels.uses), 14 * 2 + 7, "14 filas, 14 destinos de «republic» y 7 destinos propios")
        self.assertEqual({use.role for use in rebels.uses}, {"rebel_government", "rebel_government_target"})
        own = [use for use in rebels.uses if use.own]
        self.assertEqual(len(own), 14 + 7, "las filas propias (clave y, si apunta a sí misma, destino)")
        self.assertEqual([(use.line, use.role, use.own) for use in history.uses], [(3, "government", False)])
        self.assertEqual(len(plan.uses), 14 * 2 + 7 + 1, "sin contar la definición")
        self.assertEqual([str(rel) for rel in plan.copies],
                         [GOVERNMENTS, REBELS, "history/countries/AAA - Aland.txt"], "todo es del juego")
        self.assertEqual([(c.old, c.new, c.action) for c in plan.loc],
                         [("monarchy", "kingdom", LOC_COPY), ("monarchy_ruler", "kingdom_ruler", LOC_COPY)])
        self.assertIsNone(plan.moved)
        self.assert_untouched(tree)

    def test_the_plan_names_exactly_what_rename_touches(self):
        plan = self.plan("government", "monarchy", "kingdom")
        self.rename("government", "monarchy", "kingdom")
        self.assertEqual(self.dirty(), sorted([str(item.rel) for item in plan.files]
                                              + ["localisation/00_TESTMOD_governments.csv"]))

    def test_a_plan_with_a_bad_id_still_shows_the_uses(self):
        plan = self.plan("government", "monarchy", "")
        self.assertIsInstance(plan.error, InvalidIdentError)
        self.assertEqual(plan.error.code, "empty")
        self.assertFalse(plan.allowed)
        self.assertEqual(len(plan.uses), 14 * 2 + 7 + 1)
        self.assertEqual(plan.loc, ())


class CompanionRenameTests(Case):
    """Cada ``on_rename`` se basta solo: sin ``Entities.rename`` delante."""

    extra_game = {"common/countries/Aland.txt": UNIT_NAMES_COUNTRY, REBELS: rebel_tables(3)}

    def ctx(self):
        return EditContext(self.ws, self.entities.index, self.loc)

    def test_append_to_list_renames_the_value_in_its_line(self):
        record = self.entities.open(RecordRef("casus_belli", "conquer_land"))
        companion = next(c for c in record.schema.companions if isinstance(c, AppendToList))
        with self.ws.transaction("undo.test_put"):
            companion.on_rename(self.ctx(), record, "conquer_land", "seize_land")
        before, after = self.game_data(CB_FILE), self.data(CB_FILE)
        self.assertEqual(changed_lines(before, after), [3], "solo la línea de peace_order")
        self.assertEqual(after, before.replace(b"\tconquer_land\r\n", b"\tseize_land\r\n"))

    def test_mapping_table_renames_rows_and_targets(self):
        record = self.entities.open(RecordRef("government", "monarchy"))
        companion = next(c for c in record.schema.companions if isinstance(c, MappingTable))
        with self.ws.transaction("undo.test_put"):
            companion.on_rename(self.ctx(), record, "monarchy", "kingdom")
        self.assertEqual(self.data(REBELS), self.game_data(REBELS).replace(b"monarchy", b"kingdom"))
        self.assertEqual(self.dirty(), [REBELS], "la definición no es cosa del compañero")

    def test_activate_unit_renames_technologies_and_inventions(self):
        for unit, rel in (("infantry", "technologies/army_tech.txt"), ("frigate", "inventions/army_inventions.txt")):
            record = self.entities.open(RecordRef("unit", unit))
            companion = next(c for c in record.schema.companions if isinstance(c, ActivateUnit))
            with self.ws.transaction("undo.test_put"):
                companion.on_rename(self.ctx(), record, unit, "renamed_unit")
            self.assertEqual(self.data(rel), self.game_data(rel).replace(f"activate_unit = {unit}".encode(),
                                                                         b"activate_unit = renamed_unit"))
        self.assertEqual(self.dirty(), ["inventions/army_inventions.txt", "technologies/army_tech.txt"])

    def test_unit_names_slot_renames_the_list_and_keeps_the_names(self):
        country = "common/countries/Aland.txt"
        record = self.entities.open(RecordRef("unit", "frigate"))
        companion = next(c for c in record.schema.companions if isinstance(c, UnitNamesSlot))
        uses = companion.rename_uses(self.ctx(), record, "frigate")
        self.assertEqual(uses, [SymbolRef("unit_type", "frigate", VPath.of(country), 5, 2, "unit_names")])
        self.assert_untouched()
        self.assertEqual(companion.rename_uses(self.ctx(), record, "infantry"), [])
        with self.ws.transaction("undo.test_put"):
            companion.on_rename(self.ctx(), record, "frigate", "corvette")
        before, after = self.game_data(country), self.data(country)
        self.assertEqual(changed_lines(before, after), [5])
        self.assertEqual(after, before.replace(b"\tfrigate = {", b"\tcorvette = {"))
        self.assertIn(b'"Aland Star" "Northern Wind"', after)


LANCER = _crlf("# caballería del mod\nlancer = {\n\ttype = land\n\tactive = no\n\tsprite = Lancer   # jinete\n}\n")
GALLEY = _crlf("galley = {\n\ttype = naval\n\tactive = no\n}\n")


class UnitRenameTests(Case):
    extra_mod = {
        "units/lancer.txt": LANCER,
        "units/galley.txt": GALLEY,
        "technologies/mod_tech.txt": _crlf("lance_drill = {\n\tarea = army_doctrine\n\tyear = 1840\n"
                                           "\tactivate_unit = lancer\n}\n"),
        "common/countries/Modland.txt": UNIT_NAMES_COUNTRY.replace("frigate", "galley"),
        "localisation/mod_units.csv": _loc([("lancer", "Lancer", "Lancero"), ("lancer_short", "Lanc.", "Lanc."),
                                            ("other", "Other", "Otro")]),
    }

    def test_the_file_the_keys_and_the_technology_follow_the_id(self):
        ref = self.rename("unit", "lancer", "uhlan")
        self.assertEqual(ref, RecordRef("unit", "uhlan", VPath.of("units/uhlan.txt")))
        self.assertEqual(self.data("units/uhlan.txt"), LANCER.encode("cp1252").replace(b"lancer = {", b"uhlan = {"),
                         "el archivo nuevo es el viejo con otro id: comentarios y sangría intactos")
        self.assertTrue(self.ws.peek("units/lancer.txt").deleted, "el archivo viejo irá a la papelera")
        self.assertEqual(self.idents("unit"), ["frigate", "galley", "infantry", "uhlan"])
        tech = "technologies/mod_tech.txt"
        self.assertEqual(self.data(tech), self.game.mod(tech).read_bytes().replace(b"activate_unit = lancer",
                                                                                 b"activate_unit = uhlan"))
        self.assertEqual([self.loc.text(key, "es") for key in ("uhlan", "uhlan_short")], ["Lancero", "Lanc."])
        self.assertIsNone(self.loc.entry("lancer"))
        self.assertIsNone(self.loc.entry("lancer_short"))
        self.assertEqual(self.data("localisation/mod_units.csv"),
                         self.game.mod("localisation/mod_units.csv").read_bytes()
                         .replace(b"lancer;", b"uhlan;").replace(b"lancer_short;", b"uhlan_short;"))
        self.assertEqual(self.ws.history(), [("undo.rename_unit", {"kind": "unit", "ident": "lancer", "new": "uhlan"})])

    def test_undo_brings_the_old_file_back(self):
        self.rename("unit", "lancer", "uhlan")
        self.ws.undo()
        self.assertEqual(self.dirty(), [])
        self.assertEqual(self.idents("unit"), ["frigate", "galley", "infantry", "lancer"])
        self.assertEqual(self.data("units/lancer.txt"), LANCER.encode("cp1252"))
        self.assertIsNone(self.project.vfs.resolve("units/uhlan.txt"))
        with self.assertRaises(FileNotFoundError):
            self.ws.open("units/uhlan.txt")

    def test_saving_writes_the_new_file_and_trashes_the_old_one(self):
        game_before = self.game.game_tree()
        self.rename("unit", "lancer", "uhlan")
        self.project.save()
        self.assertFalse(self.game.mod("units/lancer.txt").exists())
        self.assertEqual(self.game.mod("units/uhlan.txt").read_bytes(),
                         LANCER.encode("cp1252").replace(b"lancer = {", b"uhlan = {"))
        trashed = [rel for rel in self.game.tree() if rel.startswith(".vic2studio/trash/") and rel.endswith("lancer.txt")]
        self.assertEqual(len(trashed), 1, "el archivo viejo va a la papelera (I6)")
        self.assertEqual(self.game.game_tree(), game_before)

    def test_the_plan_tells_the_move_and_the_ship_names(self):
        tree = self.game.tree()
        plan = self.plan("unit", "galley", "trireme")
        self.assertIsNone(plan.error)
        self.assertEqual(plan.moved, (VPath.of("units/galley.txt"), VPath.of("units/trireme.txt")))
        self.assertEqual([(str(item.rel), [(use.line, use.role, use.own) for use in item.uses]) for item in plan.files],
                         [("common/countries/Modland.txt", [(5, "unit_names", True)]),
                          ("units/galley.txt", [(1, ROLE_DEFINITION, False)])])
        self.assertEqual(plan.copies, ())
        self.assert_untouched(tree)
        self.rename("unit", "galley", "trireme")
        country = "common/countries/Modland.txt"
        self.assertEqual(self.data(country), self.game.mod(country).read_bytes().replace(b"\tgalley = {",
                                                                                       b"\ttrireme = {"))

    def test_a_unit_of_the_base_game_is_blocked_with_a_translated_reason(self):
        tree = self.game.tree()
        plan = self.plan("unit", "infantry", "footmen")
        self.assertIsInstance(plan.error, RenameBlockedError)
        self.assertEqual((plan.error.code, plan.error.params), ("game_file", {"rel": "units/infantry.txt"}))
        with self.assertRaises(RenameBlockedError) as caught:
            self.rename("unit", "infantry", "footmen")
        self.assertEqual(caught.exception.code, "game_file")
        self.assert_translated(caught.exception)
        self.assertIn("units/infantry.txt", caught.exception.message("es"))
        self.assert_untouched(tree)
        self.assertEqual(self.data("technologies/army_tech.txt"), self.game_data("technologies/army_tech.txt"))

    def test_a_new_unit_can_be_renamed_before_saving(self):
        self.entities.duplicate(RecordRef("unit", "infantry"), "militia")
        ref = self.rename("unit", "militia", "levy")
        self.assertEqual(str(ref.rel), "units/levy.txt")
        self.assertEqual(self.data("units/levy.txt"),
                         self.game_data("units/infantry.txt").replace(b"infantry = {", b"levy = {"))
        self.assertIsNone(self.ws.peek("units/militia.txt"), "nunca llegó al disco: no deja lápida")
        self.project.save()
        self.assertFalse(self.game.mod("units/militia.txt").exists())
        self.assertTrue(self.game.mod("units/levy.txt").exists())

    def test_ids_the_layout_would_not_recognise_or_whose_file_exists_are_refused(self):
        with self.assertRaises(InvalidIdentError) as caught:
            self.rename("unit", "lancer", "Uhlan")
        self.assertEqual(caught.exception.code, "bad_chars", "units/Uhlan.txt no se leería como unidad")
        self.put("units/hussar.txt", "something_else = {\n}\n")
        with self.assertRaises(InvalidIdentError) as caught:
            self.rename("unit", "lancer", "hussar")
        self.assertEqual(caught.exception.code, "taken", "el archivo ya existe aunque no defina la unidad")
        self.assertEqual(self.idents("unit"), ["frigate", "galley", "infantry", "lancer"])


class ShadowedUnitTests(Case):
    mod_copies = ("units/infantry.txt",)

    def test_a_mod_copy_of_a_game_unit_is_blocked_too(self):
        """Quitar la copia del mod dejaría a la vista el archivo del juego: la unidad vieja seguiría existiendo."""
        with self.assertRaises(RenameBlockedError) as caught:
            self.rename("unit", "infantry", "footmen")
        self.assertEqual(caught.exception.code, "game_file")
        self.assert_untouched()


CULTURES_TEXT = _crlf("""\
# Culturas del minijuego (inventadas)
north_folk = {
	leader = european
	unit = NorthGC
	union = AAA

	# la cultura de la capital
	alander = {
		color = { 100 20 20 }   # granate
		first_names = { Ana Luis }
		last_names = { Mar "De la Vega" }
		primary = AAA
	}
	borlander = { color = { 20 100 20 } }
}
south_folk = {
	leader = european
	corlander = {
		color = { 20 20 100 }
	}
	dominer = {
		color = { 90 90 90 }
		primary = D01
	}
}
""")


class CultureRenameTests(Case):
    extra_game = {CULTURES: CULTURES_TEXT}

    def test_a_culture_with_primary_and_union_keeps_them(self):
        self.rename("culture", "alander", "alandic")
        before, after = self.game_data(CULTURES), self.data(CULTURES)
        self.assertEqual(changed_lines(before, after), [8])
        self.assertEqual(after, before.replace(b"\talander = {", b"\talandic = {"))
        for kept in (b"union = AAA", b"primary = AAA", b"# la cultura de la capital", b'Mar "De la Vega"'):
            self.assertIn(kept, after)
        history = "history/countries/AAA - Aland.txt"
        self.assertEqual(self.data(history), self.game_data(history).replace(b"primary_culture = alander",
                                                                             b"primary_culture = alandic"))
        self.assertEqual(self.entities.parent(RecordRef("culture", "alandic")), "north_folk")
        self.assertEqual(self.loc.text("alandic", "es"), "alandés")

    def test_every_pop_of_the_culture_follows_not_only_the_first_of_each_file(self):
        """El índice guarda una referencia por cultura y archivo de POPs: las demás también cambian."""
        pops = "history/pops/1836.1.1/North.txt"
        self.assertEqual(len([use for use in self.entities.index.refs_to("culture", "alander")
                              if str(use.rel) == pops]), 1)
        plan = self.plan("culture", "alander", "alandic")
        self.assertEqual([use.line for item in plan.files if str(item.rel) == pops for use in item.uses], [3, 17])
        self.rename("culture", "alander", "alandic")
        before, after = self.game_data(pops), self.data(pops)
        self.assertEqual(changed_lines(before, after), [3, 17])
        self.assertEqual(after, before.replace(b"culture = alander", b"culture = alandic"))
        self.assertIn(b"culture = borlander", after)
        later = "history/pops/1861.1.1/North.txt"
        self.assertEqual(self.data(later), self.game_data(later).replace(b"alander", b"alandic"))

    def test_a_group_is_renamed_by_its_key(self):
        ref = self.rename("culture_group", "north_folk", "boreal_folk")
        before, after = self.game_data(CULTURES), self.data(CULTURES)
        self.assertEqual(changed_lines(before, after), [2])
        self.assertEqual(after, before.replace(b"north_folk = {", b"boreal_folk = {"))
        self.assertEqual(self.idents("culture_group"), ["boreal_folk", "south_folk"])
        self.assertEqual(self.entities.parent(RecordRef("culture", "alander")), "boreal_folk")
        self.assertEqual([child.ref.ident for child in self.entities.open(ref).children()], ["alander", "borlander"])
        self.assertEqual(self.loc.text("boreal_folk", "es"), "norteño")


class BookmarkRenameTests(Case):
    def test_the_id_is_the_name_field_and_its_description_follows(self):
        ref = self.rename("bookmark", "MG_START", "MG_BEGIN")
        self.assertEqual(ref.ident, "MG_BEGIN")
        before, after = self.game_data(BOOKMARKS), self.data(BOOKMARKS)
        self.assertEqual(changed_lines(before, after), [2, 3])
        self.assertEqual(after, before.replace(b'"MG_START"', b'"MG_BEGIN"').replace(b'"MG_START_DESC"',
                                                                                     b'"MG_BEGIN_DESC"'),
                         "las comillas se conservan")
        self.assertEqual(self.idents("bookmark"), ["MG_BEGIN", "MG_LATE"])
        record = self.entities.open(ref)
        self.assertEqual((record.get("name"), record.get("desc")), ("MG_BEGIN", "MG_BEGIN_DESC"))
        self.ws.undo()
        self.assertEqual(self.data(BOOKMARKS), before)

    def test_its_keys_in_the_mod_are_renamed(self):
        self.entities.create("bookmark", "MG_MID", texts={"MG_MID": {"es": "Mitad"}, "MG_MID_DESC": {"es": "A medias"}})
        self.rename("bookmark", "MG_MID", "MG_HALF")
        self.assertEqual([self.loc.text(key, "es") for key in ("MG_HALF", "MG_HALF_DESC")], ["Mitad", "A medias"])
        self.assertIsNone(self.loc.entry("MG_MID"))
        self.assertIsNone(self.loc.entry("MG_MID_DESC"))
        self.assertIn(b'name = "MG_HALF"', self.data(BOOKMARKS))
        self.assertIn(b'desc = "MG_HALF_DESC"', self.data(BOOKMARKS))


class BookmarkOwnDescriptionTests(Case):
    extra_game = {BOOKMARKS: _crlf('bookmark = {\n\tname = "MG_START"\n\tdesc = "MG_ANY_TEXT"\n\tdate = 1836.1.1\n}\n')}

    def test_a_description_that_does_not_follow_the_template_stays(self):
        self.rename("bookmark", "MG_START", "MG_BEGIN")
        self.assertEqual(self.data(BOOKMARKS), self.game_data(BOOKMARKS).replace(b'"MG_START"', b'"MG_BEGIN"'))


class BrokenUseTests(Case):
    extra_mod = {"history/wars/Broken War.txt": _crlf('name = "Broken War"\n1850.1.1 = {\n\twar_goal = {\n'
                                                      "\t\tcasus_belli = conquer_land\n\t}\n")}

    def test_a_use_in_a_file_that_cannot_be_edited_blocks_the_rename(self):
        tree = self.game.tree()
        plan = self.plan("casus_belli", "conquer_land", "seize_land")
        self.assertIsInstance(plan.error, RenameBlockedError)
        with self.assertRaises(RenameBlockedError) as caught:
            self.rename("casus_belli", "conquer_land", "seize_land")
        self.assertEqual((caught.exception.code, caught.exception.params),
                         ("read_only_file", {"rel": "history/wars/Broken War.txt"}))
        self.assert_translated(caught.exception)
        self.assert_untouched(tree)
        self.assertEqual(self.data(CB_FILE), self.game_data(CB_FILE), "ni siquiera la definición")


class _IndexWithStrayUse:
    """El índice de verdad más un uso en un archivo que no es Clausewitz (un id que sale de una tabla)."""

    def __init__(self, index, stray: SymbolRef) -> None:
        self._index = index
        self._stray = stray

    def __getattr__(self, name):
        return getattr(self._index, name)

    def refs_to(self, kind, name):
        found = self._index.refs_to(kind, name)
        return [*found, self._stray] if (kind, name) == (self._stray.kind, self._stray.name) else found


class RejectionTests(Case):
    def test_bad_ids_are_refused_with_a_translated_reason_and_change_nothing(self):
        tree = self.game.tree()
        for new, code in (("", "empty"), ("two words", "bad_chars"), ("9lives", "bad_chars"),
                          ("conquer_land", "unchanged"), ("free_people", "taken")):
            with self.subTest(new=new):
                with self.assertRaises(InvalidIdentError) as caught:
                    self.rename("casus_belli", "conquer_land", new)
                self.assertEqual(caught.exception.code, code)
                self.assert_translated(caught.exception)
                self.assertEqual(self.plan("casus_belli", "conquer_land", new).error.code, code)
                self.assert_untouched(tree)
        self.assertEqual(self.data(CB_FILE), self.game_data(CB_FILE))

    def test_an_id_created_without_saving_counts_as_taken(self):
        self.entities.create("casus_belli", "my_cb")
        with self.assertRaises(InvalidIdentError) as caught:
            self.rename("casus_belli", "conquer_land", "my_cb")
        self.assertEqual(caught.exception.code, "taken", "la colisión se mira en la vista efectiva (I7)")

    def test_a_symbol_of_the_same_kind_in_another_file_counts_as_taken(self):
        """``mg_static`` es un modificador de ``static_modifiers.txt``: los usos de los dos se confundirían."""
        self.assertNotIn("mg_static", self.idents("event_modifier"))
        with self.assertRaises(InvalidIdentError) as caught:
            self.rename("event_modifier", "good_harvest", "mg_static")
        self.assertEqual(caught.exception.code, "taken")
        self.assertEqual(self.rename("event_modifier", "good_harvest", "great_harvest").ident, "great_harvest")

    def test_read_only_catalogues_are_not_renamed(self):
        with self.assertRaises(ReadOnlySchemaError):
            self.rename("ideology", "liberal", "whig")
        self.assertIsInstance(self.plan("ideology", "liberal", "whig").error, ReadOnlySchemaError)
        self.assert_untouched()

    def test_an_unknown_record_is_a_key_error(self):
        with self.assertRaises(KeyError):
            self.rename("casus_belli", "no_such_cb", "other")

    def test_a_use_that_is_not_a_token_blocks_the_rename(self):
        stray = SymbolRef("cb", "conquer_land", VPath.of("map/definition.csv"), 3, None, "table_row")
        self.entities.index = _IndexWithStrayUse(self.entities.index, stray)
        with self.assertRaises(RenameBlockedError) as caught:
            self.rename("casus_belli", "conquer_land", "seize_land")
        self.assertEqual((caught.exception.code, caught.exception.uses), ("unresolved_uses", (stray,)))
        self.assert_translated(caught.exception)
        self.assertIn("1", caught.exception.message("es"))
        self.assert_untouched()

    def test_a_failing_companion_rolls_back_the_whole_rename(self):
        class Failing:
            def on_rename(self, ctx, rec, old, new):
                raise RuntimeError("compañero roto")

        schema = registry.get("casus_belli")
        registry._schemas["casus_belli"] = dataclasses.replace(schema, companions=schema.companions + (Failing(),))
        self.addCleanup(registry._schemas.__setitem__, "casus_belli", schema)
        with self.assertRaises(RuntimeError):
            self.rename("casus_belli", "conquer_land", "seize_land")
        self.assert_untouched()
        self.assertEqual(self.data(CB_FILE), self.game_data(CB_FILE))
        self.assertEqual(self.data(WAR_FILE), self.game_data(WAR_FILE))

    def test_every_editable_schema_has_its_rename_label(self):
        for lang in ("es", "en"):
            texts = load_texts(lang)
            for schema in registry.all_schemas():
                if schema.editable:
                    self.assertIn(f"undo.rename_{schema.kind}", texts, lang)
                    self.assertEqual(set(re.findall(r"{(\w+)}", texts[f"undo.rename_{schema.kind}"])),
                                     {"ident", "new"})


class CultureMoveTests(Case):
    extra_game = {CULTURES: CULTURES_TEXT}

    BLOCK = _crlf("""\
	# la cultura de la capital
	alander = {
		color = { 100 20 20 }   # granate
		first_names = { Ana Luis }
		last_names = { Mar "De la Vega" }
		primary = AAA
	}
""").encode()

    def test_the_block_moves_with_its_text_intact(self):
        before = self.game_data(CULTURES)
        self.assertEqual(before.count(self.BLOCK), 1)
        ref = self.entities.move_to_group(RecordRef("culture", "alander"), "south_folk")
        self.assertEqual(ref, RecordRef("culture", "alander", VPath.of(CULTURES)))
        after = self.data(CULTURES)
        tail = _crlf("\tdominer = {\n\t\tcolor = { 90 90 90 }\n\t\tprimary = D01\n\t}\n").encode()
        expected = before.replace(self.BLOCK, b"").replace(tail + b"}", tail + self.BLOCK + b"}")
        self.assertEqual(after, expected, "el bloque sale de su grupo y entra al final del otro, con su comentario")
        self.assertEqual(self.entities.parent(ref), "south_folk")
        self.assertEqual({item.ref.ident: item.parent for item in self.entities.list("culture")},
                         {"alander": "south_folk", "borlander": "north_folk", "corlander": "south_folk",
                          "dominer": "south_folk"})
        record = self.entities.open(ref)
        self.assertEqual((record.get("color"), record.get("last_names")), ((100, 20, 20), ["Mar", "De la Vega"]))
        issues = self.entities.open(RecordRef("culture", "dominer")).issues(self.entities.check_context())
        self.assertEqual({(issue.code, issue.line) for issue in issues}, {("required_missing", 14)},
                         "las posiciones de los demás registros son las de después de mover")
        self.assertEqual(self.ws.history(), [("undo.move_culture", {
            "kind": "culture", "ident": "alander", "group": "south_folk"})], "una transacción")
        self.ws.undo()
        self.assertEqual(self.data(CULTURES), before)
        self.assertEqual(self.dirty(), [])

    def test_saving_writes_the_same_lines_in_another_place(self):
        from vic2studio.core.project.diffing import changed_lines as diff_lines

        self.entities.move_to_group(RecordRef("culture", "alander"), "south_folk")
        self.project.save()
        saved = self.game.mod(CULTURES).read_bytes()
        lines = self.BLOCK.count(b"\n")
        self.assertEqual(diff_lines(self.game_data(CULTURES), saved), (lines, lines))
        self.assertEqual(sorted(saved.split(b"\r\n")), sorted(self.game_data(CULTURES).split(b"\r\n")),
                         "las mismas líneas, en otro orden")

    def test_moving_to_its_own_group_does_nothing(self):
        ref = self.entities.move_to_group(RecordRef("culture", "alander"), "north_folk")
        self.assertEqual(ref.ident, "alander")
        self.assert_untouched()

    def test_an_unknown_group_or_a_schema_without_groups_is_refused(self):
        for group in ("no_such_folk", "borlander", ""):
            with self.assertRaises(InvalidIdentError) as caught:
                self.entities.move_to_group(RecordRef("culture", "alander"), group)
            self.assertEqual(caught.exception.code, "no_group")
        with self.assertRaises(ValueError):
            self.entities.move_to_group(RecordRef("government", "monarchy"), "south_folk")
        with self.assertRaises(ValueError):
            self.entities.move_to_group(RecordRef("culture_group", "north_folk"), "south_folk")
        self.assert_untouched()

    def test_the_move_label_has_its_text(self):
        for lang in ("es", "en"):
            self.assertEqual(set(re.findall(r"{(\w+)}", load_texts(lang)["undo.move_culture"])), {"ident", "group"})


class CultureGroupTests(Case):
    extra_game = {CULTURES: CULTURES_TEXT}

    def test_a_new_group_is_created_with_its_fields_and_its_key(self):
        before = self.game_data(CULTURES)
        ref = self.entities.create("culture_group", "east_folk",
                                   {"leader": "asian", "unit": "NorthGC", "union": "BBB", "is_overseas": True},
                                   texts={"east_folk": {"en": "Eastern", "es": "oriental"}})
        after = self.data(CULTURES)
        self.assertEqual(after, before + _crlf("east_folk = {\n\tleader = asian\n\tunit = NorthGC\n\tunion = BBB\n"
                                               "\tis_overseas = yes\n}\n").encode(),
                         "al final del archivo, con sus campos en el orden del esquema")
        record = self.entities.open(ref)
        self.assertEqual([record.get(key) for key in ("leader", "unit", "union", "is_overseas")],
                         ["asian", "NorthGC", "BBB", True])
        self.assertEqual((self.loc.text("east_folk", "en"), self.loc.text("east_folk", "es")), ("Eastern", "oriental"))
        self.assertEqual(str(self.loc.where("east_folk")[0]), "localisation/00_TESTMOD_cultures.csv")
        self.assertEqual(self.entities.groups("culture"), ["north_folk", "south_folk", "east_folk"],
                         "un grupo vacío también se ofrece")
        self.assertEqual(self.idents("culture_group"), ["east_folk", "north_folk", "south_folk"])
        self.assertEqual(len(self.ws.history()), 1)
        self.ws.undo()
        self.assertEqual(self.data(CULTURES), before)
        self.assertIsNone(self.loc.entry("east_folk"))

    def test_cultures_can_be_created_in_and_moved_to_the_new_group(self):
        self.entities.create("culture_group", "east_folk", {"leader": "asian"})
        created = self.entities.create("culture", "eastling", {"group": "east_folk"})
        self.assertEqual(self.entities.parent(created), "east_folk")
        self.entities.move_to_group(RecordRef("culture", "borlander"), "east_folk")
        group = self.entities.open(RecordRef("culture_group", "east_folk"))
        self.assertEqual([child.ref.ident for child in group.children()], ["eastling", "borlander"])
        self.assertIn(b"\tborlander = { color = { 20 100 20 } }\r\n}\r\n", self.data(CULTURES))

    def test_group_kind_and_groups(self):
        self.assertEqual(self.entities.group_kind("culture"), "culture_group")
        self.assertIsNone(self.entities.group_kind("culture_group"))
        self.assertIsNone(self.entities.group_kind("government"))
        self.assertEqual(self.entities.groups("culture"), ["north_folk", "south_folk"])
        self.assertEqual(self.entities.groups("government"), [])
        self.assert_untouched()


@unittest.skipUnless(vanilla_root(), "sin corpus")
class VanillaRenameTests(unittest.TestCase):
    """Sobre el juego real con un mod vacío en una carpeta temporal: los archivos que crea el mod difieren del
    juego solo en las líneas que citan el id, y deshacer deja los bytes originales."""

    def setUp(self):
        isolate_appdirs(self)
        self.game_root = vanilla_root()
        self.mod_root = Path(tempfile.mkdtemp(prefix="vic2studio-rename-mod-"))
        self.addCleanup(shutil.rmtree, self.mod_root, True)
        self.project = Project.open(self.game_root, self.mod_root)
        self.addCleanup(self.project.close, discard=True)
        self.ws = self.project.ws
        self.index = build_index(self.project.vfs.snapshot(), None, {})
        self.loc = LocSync(self.ws, self.project.vfs, prefix=self.project.settings.prefix)
        self.entities = Entities(self.ws, self.index, self.loc)

    def data(self, rel) -> bytes:
        handle = self.ws.open(rel)
        return codec_for(handle.kind).snapshot(handle.model)

    def game_file(self, rel) -> bytes:
        return self.project.vfs.resolve(rel).path.read_bytes()

    def pick(self, kind: str, symbol: str, role: str) -> str:
        """El primer registro de ``kind`` que tiene usos con ese papel."""
        for item in self.entities.list(kind):
            if any(use.role == role for use in self.index.refs_to(symbol, item.ref.ident)):
                return item.ref.ident
        self.fail(f"vanilla no tiene ningún {kind} con usos «{role}»")

    def check(self, kind: str, old: str, new: str, loc_file: str) -> None:
        plan = self.entities.rename_plan(RecordRef(kind, old), new)
        self.assertIsNone(plan.error)
        self.assertEqual(self.ws.dirty(), [], "el plan no cambia nada (I4)")
        self.assertEqual(set(plan.copies), {item.rel for item in plan.files}, "todo sale del juego")
        originals = {str(item.rel): self.game_file(item.rel) for item in plan.files}
        self.entities.rename(RecordRef(kind, old), new)
        for item in plan.files:
            before, after = originals[str(item.rel)], self.data(item.rel)
            lines = changed_lines(before, after)
            self.assertEqual(lines, sorted({use.line for use in item.uses}), f"{item.rel}: solo las líneas del plan")
            old_lines, new_lines = before.split(b"\n"), after.split(b"\n")
            for number in lines:
                changed = old_lines[number - 1]
                self.assertNotEqual(swap_token(changed, old, new), changed, f"{item.rel}:{number} no cita el id")
                self.assertIn(new.encode(), new_lines[number - 1])
                self.assertEqual(len(new_lines[number - 1]) - len(changed),
                                 (len(new) - len(old)) * sum(1 for use in item.uses if use.line == number),
                                 f"{item.rel}:{number}: solo cambia el token")
        self.assertEqual(sorted(str(handle.rel) for handle in self.ws.dirty()),
                         sorted([*originals, loc_file]))
        renamed = {rel: self.data(rel) for rel in originals}
        self.ws.undo()
        self.assertEqual(self.ws.dirty(), [])
        for rel, before in originals.items():
            self.assertEqual(self.data(rel), before, f"{rel}: deshacer deja los bytes originales")
        self.ws.redo()
        self.project.save()
        written = {path.relative_to(self.mod_root).as_posix() for path in self.mod_root.rglob("*")
                   if path.is_file() and ".vic2studio" not in path.parts}
        self.assertTrue(set(originals) <= {rel for rel in written}, written)
        for rel in originals:
            self.assertEqual((self.mod_root / rel).read_bytes(), renamed[rel], f"{rel}: se guarda lo renombrado")

    def test_rename_a_cb_and_a_government_of_vanilla_over_an_empty_mod(self):
        cb = self.pick("casus_belli", "cb", "casus_belli")
        self.check("casus_belli", cb, "studio_renamed_cb", f"localisation/00_{self.project.settings.prefix}_cb.csv")
        self.assertIn("studio_renamed_cb", [item.ref.ident for item in self.entities.list("casus_belli")])
        government = self.pick("government", "government", "government")
        self.check("government", government, "studio_renamed_gov",
                   f"localisation/00_{self.project.settings.prefix}_governments.csv")
        rebels = self.data(REBELS)
        self.assertEqual(rebels.count(b"studio_renamed_gov ="), 14, "las 14 tablas (H16)")
        self.assertNotIn(government.encode() + b" =", rebels.replace(b"studio_renamed_gov", b""))


if __name__ == "__main__":
    unittest.main()
