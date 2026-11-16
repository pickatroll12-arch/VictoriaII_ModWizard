"""Las seis validaciones del cierre de la iteración 4 (etapa Y1; wizard §14.4, §14.10–§14.13).

``sprite_missing``, ``unit_port_level_too_high``, ``government_flagtype_unknown``,
``culture_name_duplicate``, ``bookmark_without_pops`` y ``bookmark_camera_outside_map``:
cada una con el caso que da el problema, los que no deben darlo (el borde de la
condición), la línea base y lo sin guardar; los dos arreglos (plan = aplicación) y el
extractor de actores del índice. Con corpus: vanilla y el mod del usuario no dan
ninguno, y un fallo plantado sobre vanilla sí sale.

Todo inventado: los actores, unidades y gobiernos de aquí solo imitan la forma.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import user_mod, vanilla_root  # noqa: E402
from _layers import build_layers, isolate_appdirs  # noqa: E402
from _minigame import GAME_FILES, MiniGame, build_minigame  # noqa: E402
from vic2studio.core.clausewitz import Severity  # noqa: E402
from vic2studio.core.index import FactsCache, build_index, extract_bytes  # noqa: E402
from vic2studio.core.index import model as m  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.validate import (FIXES, RULES, Validator, apply_fix, build_context,  # noqa: E402
                                      compute_baseline, explain, fixes_for, game_only_snapshot, plan_fix)
from vic2studio.core.validate.fixes import FixError  # noqa: E402
from vic2studio.core.validate.model import (ACTION_COPY_FROM_GAME, ACTION_MODIFY, LAYER_GAME,  # noqa: E402
                                            LAYER_MOD, VERDICT_LOSES, VERDICT_MISSING, VERDICT_WINS)
from vic2studio.core.vfs import LayerKind, VirtualFS, VPath  # noqa: E402

NEW_CODES = ("sprite_missing", "unit_port_level_too_high", "government_flagtype_unknown", "culture_name_duplicate",
             "bookmark_without_pops", "bookmark_camera_outside_map")
BOOKMARKS = "common/bookmarks.txt"
BUILDINGS = "common/buildings.txt"
CULTURES = "common/cultures.txt"
GOVERNMENTS = "common/governments.txt"
FLAG = b"\x00\x00\x02flag"


def crlf(text: str) -> str:
    return text.replace("\n", "\r\n")


def actors_gfx(*names: str, kind: str = "EMFXActorType") -> str:
    """Un .gfx inventado con un actor por nombre (``objectTypes`` → ``EMFXActorType``)."""
    body = "".join(f'\t{kind} = {{\n\t\tname = "{name}"\n\t\tactorfile = "gfx/anims/mg_{name.lower()}.xac"\n\t}}\n'
                   for name in names)
    return crlf("objectTypes = {\n" + body + "}\n")


def unit(name: str, *lines: str, kind: str = "land") -> str:
    return crlf(f"{name} = {{\n\ttype = {kind}\n" + "".join(f"\t{line}\n" for line in lines) + "}\n")


def bookmark(name: str, *lines: str) -> str:
    return crlf(f'bookmark = {{\n\tname = "{name}"\n' + "".join(f"\t{line}\n" for line in lines) + "}\n")


def naval_base(level: int, name: str = "naval_base", kind: str | None = "naval_base") -> str:
    kind_line = f"\ttype = {kind}\n" if kind else ""
    return crlf(f"{name} = {{\n{kind_line}\tmax_level = {level}\n}}\n")


# Los actores del juego de estas pruebas: los de las dos unidades del minijuego (``Generic`` y ``NorthGC`` son sus
# culturas gráficas) y una montura con el nombre entero.
GAME_ACTORS = {"interface/mg_actors.gfx": actors_gfx("GenericInfantry", "GenericFrigate", "NorthGCLancer", "MgMount")}


def run(game, codes, *, overrides=None, baseline=False):
    snap = game.snapshot()
    ctx = build_context(snap, build_index(snap, None, overrides), overrides)
    base = None
    if baseline:
        game_snap = game_only_snapshot(snap)
        base = compute_baseline(build_context(game_snap, build_index(game_snap, None), game_only=True))
    return list(Validator(ctx, baseline=base).validate(codes=set(codes)).problems), ctx


def found(game, code, **kwargs):
    return run(game, {code}, **kwargs)[0]


class RuleTestCase(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def game(self, mod_files=None, game_files=None):
        game = build_minigame(mod=False, mod_files=mod_files, game_files=game_files)
        self.addCleanup(game.cleanup)
        return game

    def problems(self, code, mod_files=None, game_files=None, **kwargs):
        return found(self.game(mod_files, game_files), code, **kwargs)


# --- el índice: actores de los .gfx ------------------------------------------------------------------------


class ActorExtractorTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def test_only_the_animated_actors_of_object_types_are_catalogued(self):
        data = crlf('spriteTypes = {\n\tspriteType = {\n\t\tname = "GFX_mg_thing"\n\t}\n'
                    '\tEMFXActorType = {\n\t\tname = "NotInObjectTypes"\n\t}\n}\n'
                    'objectTypes = {\n\tEMFXActorType = {\n\t\tname = "GenericLancer"\n\t}\n'
                    '\tmeshType = {\n\t\tname = "mg_mesh"\n\t}\n'
                    '\temfxactortype = {\n\t\tNAME = "NorthGCLancer"\n\t}\n'
                    '\tEMFXActorType = {\n\t\tscale = 1\n\t}\n}\n').encode("cp1252")
        facts = {f.extractor: f for f in extract_bytes(VPath.of("interface/mg.gfx"), data, LayerKind.MOD)}
        self.assertEqual(set(facts), {"interface.sprites", "interface.actors"})
        actors = facts["interface.actors"].defs
        self.assertEqual([(s.kind, s.name, s.line) for s in actors],
                         [(m.ACTOR_KIND, "GenericLancer", 10), (m.ACTOR_KIND, "NorthGCLancer", 16)],
                         "sin el meshType, el que está fuera de objectTypes ni el que no tiene nombre")
        self.assertEqual(actors[0].attrs["type"], "EMFXActorType")
        self.assertEqual([s.name for s in facts["interface.sprites"].defs], ["GFX_mg_thing", "NotInObjectTypes"],
                         "el extractor de sprites no cambia: todo bloque con nombre de spriteTypes")

    def test_a_cache_written_before_the_extractor_existed_keeps_the_rest(self):
        """«Sin romper la caché»: con una caché sin hechos de actores (la de antes de este extractor), solo se
        extrae eso, y solo de los .gfx."""
        game = build_minigame(mod=False, game_files=GAME_ACTORS)
        self.addCleanup(game.cleanup)
        snap = game.snapshot()
        cache = FactsCache()
        build_index(snap, cache)
        [layer] = [layer for layer in snap.layers if layer.kind is LayerKind.GAME]
        old = [f for f in cache.load(layer).values() if f.extractor != "interface.actors"]
        cache.store(layer, old, roots=[item.root for item in snap.layers])
        extracted = []
        index = build_index(snap, cache, on_extract=lambda rel, name: extracted.append((str(rel), name)))
        self.assertEqual(sorted(extracted), [("interface/mg_actors.gfx", "interface.actors"),
                                             ("interface/minigame.gfx", "interface.actors")])
        self.assertEqual(index.count(m.ACTOR_KIND), 4)
        again = []
        build_index(snap, cache, on_extract=lambda rel, name: again.append(name))
        self.assertEqual(again, [], "y quedan guardados")

    def test_actors_are_not_offered_by_the_search_unless_asked(self):
        """Ctrl+K aún no tiene etiqueta para ellos (``kind.actor`` sería de ``ui/``): no salen con su tipo en crudo."""
        game = build_minigame(mod=False, game_files=GAME_ACTORS)
        self.addCleanup(game.cleanup)
        index = build_index(game.snapshot(), None)
        self.assertIn(m.ACTOR_KIND, index.kinds())
        self.assertEqual(index.search("GenericFrigate"), [])
        self.assertEqual([s.name for s in index.search("GenericFrigate", kinds=[m.ACTOR_KIND])], ["GenericFrigate"])
        self.assertNotIn(m.ACTOR_KIND, {s.kind for s in index.search("infantry")})
        self.assertIn(m.KIND_UNIT_TYPE, {s.kind for s in index.search("infantry")})

    def test_a_text_named_like_an_actor_is_still_an_orphan(self):
        files = {"localisation/00_new.csv": "MgMount;Mount;;;;Montura;;;;;;;;;x\r\n"}
        game = build_minigame(mod=False, mod_files=files, game_files=GAME_ACTORS)
        self.addCleanup(game.cleanup)
        self.assertEqual([p.args["key"] for p in found(game, "loc_key_orphan")], ["MgMount"])


# --- sprite_missing ----------------------------------------------------------------------------------------


class SpriteMissingTests(RuleTestCase):
    def sprites(self, mod_files, game_files=GAME_ACTORS, **kwargs):
        return [(p.args["unit"], p.args["attr"], p.args["sprite"])
                for p in self.problems("sprite_missing", mod_files, game_files, **kwargs)]

    def test_a_model_that_is_no_actor_is_reported_on_its_line(self):
        files = {"units/lancer.txt": unit("lancer", "active = no", "sprite = Uhlan")}
        [problem] = self.problems("sprite_missing", files, GAME_ACTORS)
        self.assertEqual((str(problem.rel), problem.line, problem.column), ("units/lancer.txt", 4, 2))
        self.assertEqual(problem.entity, (m.KIND_UNIT_TYPE, "lancer"))
        self.assertEqual(problem.field, ("sprite",))
        self.assertEqual(dict(problem.args), {"unit": "lancer", "sprite": "Uhlan", "attr": "sprite"})
        self.assertIs(problem.severity, Severity.WARNING)
        self.assertEqual(problem.fixes, ())
        self.assertIn("«Uhlan»", problem.message("es"))
        self.assertIn("“Uhlan”", problem.message("en"))

    def test_one_graphical_culture_with_the_actor_is_enough(self):
        """Como en vanilla: casi ninguna unidad tiene actor en todas las culturas gráficas."""
        self.assertEqual(self.sprites({"units/lancer.txt": unit("lancer", "sprite = Lancer")}), [],
                         "NorthGCLancer, aunque no haya GenericLancer")
        self.assertEqual(self.sprites({}), [], "Infantry y Frigate, con Generic")

    def test_the_name_alone_also_counts_and_case_does_not(self):
        files = {"units/lancer.txt": unit("lancer", "sprite = lancer", "sprite_mount = mgmount")}
        self.assertEqual(self.sprites(files), [])

    def test_a_culture_prefix_that_is_not_a_graphical_culture_does_not_count(self):
        game_files = {"interface/mg_actors.gfx": actors_gfx("GenericInfantry", "GenericFrigate", "SouthGCLancer")}
        files = {"units/lancer.txt": unit("lancer", "sprite = Lancer")}
        self.assertEqual(self.sprites(files, game_files), [("lancer", "sprite", "Lancer")])

    def test_with_an_override_the_override_is_the_model(self):
        """Como cuirassier, dragoon y hussar de vanilla: su ``sprite`` no es ningún actor y su override, sí."""
        ok = {"units/lancer.txt": unit("lancer", "sprite = Uhlan", "sprite_override = Lancer")}
        self.assertEqual(self.sprites(ok), [])
        bad = {"units/lancer.txt": unit("lancer", "sprite = Lancer", "sprite_override = Uhlan")}
        self.assertEqual(self.sprites(bad), [("lancer", "sprite_override", "Uhlan")])

    def test_the_mount_is_checked_and_its_attach_node_is_not(self):
        files = {"units/lancer.txt": unit("lancer", "sprite = Lancer", "sprite_mount = MgPony",
                                          "sprite_mount_attach_node = Saddle")}
        [problem] = self.problems("sprite_missing", files, GAME_ACTORS)
        self.assertEqual((problem.args["attr"], problem.args["sprite"], problem.line), ("sprite_mount", "MgPony", 4))
        self.assertEqual(problem.field, ("sprite_mount",))

    def test_other_object_types_are_not_actors(self):
        game_files = {"interface/mg_actors.gfx": actors_gfx("GenericInfantry", "GenericFrigate"),
                      "interface/mg_meshes.gfx": actors_gfx("GenericLancer", kind="meshType")}
        files = {"units/lancer.txt": unit("lancer", "sprite = Lancer")}
        self.assertEqual(self.sprites(files, game_files), [("lancer", "sprite", "Lancer")])

    def test_without_any_actor_in_the_view_the_rule_is_silent(self):
        """El minijuego tal cual no tiene ``objectTypes``: no hay con qué comparar."""
        self.assertEqual(self.sprites({"units/lancer.txt": unit("lancer", "sprite = Uhlan")}, None), [])

    def test_a_unit_without_sprite_gives_nothing(self):
        self.assertEqual(self.sprites({"units/lancer.txt": unit("lancer", "active = no")}), [])

    def test_the_unsaved_document_is_what_counts(self):
        files = {"units/lancer.txt": unit("lancer", "sprite = Uhlan")}
        fixed = {VPath.of("units/lancer.txt"): unit("lancer", "sprite = Lancer").encode("cp1252")}
        self.assertEqual(self.sprites(files, overrides=fixed), [])
        broken = {VPath.of("units/infantry.txt"): unit("infantry", "sprite = Uhlan").encode("cp1252")}
        self.assertEqual(self.sprites({}, overrides=broken), [("infantry", "sprite", "Uhlan")])

    def test_what_the_game_already_has_is_inherited(self):
        game_files = {"interface/mg_actors.gfx": actors_gfx("GenericInfantry")}       # Frigate, sin actor
        files = {"units/lancer.txt": unit("lancer", "sprite = Uhlan")}
        problems = self.problems("sprite_missing", files, game_files, baseline=True)
        self.assertEqual(sorted((p.args["unit"], p.inherited) for p in problems), [("frigate", True),
                                                                                   ("lancer", False)])

    def test_the_explanation_shows_the_line_and_where_actors_live(self):
        game = self.game({"units/lancer.txt": unit("lancer", "sprite = Uhlan")}, GAME_ACTORS)
        [problem], ctx = run(game, {"sprite_missing"})
        explanation = explain(problem, ctx)
        self.assertEqual([(s.rel, s.line, s.excerpt, s.verdict) for s in explanation.steps],
                         [("units/lancer.txt", 3, "sprite = Uhlan", VERDICT_WINS),
                          (None, None, "interface/*.gfx", VERDICT_MISSING)])
        self.assertIn("sin comprobar en el juego", explanation.outcome("es"))
        self.assertIn("not been checked in game", explanation.outcome("en"))


# --- unit_port_level_too_high -------------------------------------------------------------------------------


class PortLevelTests(RuleTestCase):
    BASE = {BUILDINGS: GAME_FILES[BUILDINGS] + naval_base(4)}

    def levels(self, mod_files, **kwargs):
        return [(p.args["unit"], p.args["level"], p.args["max"], p.args["building"])
                for p in self.problems("unit_port_level_too_high", mod_files, **kwargs)]

    def test_a_port_level_above_the_maximum_is_an_error_on_its_line(self):
        files = {**self.BASE, "units/galleon.txt": unit("galleon", "active = no", "min_port_level = 5", kind="naval")}
        [problem] = self.problems("unit_port_level_too_high", files)
        self.assertEqual((str(problem.rel), problem.line, problem.column), ("units/galleon.txt", 4, 2))
        self.assertEqual(problem.entity, (m.KIND_UNIT_TYPE, "galleon"))
        self.assertEqual(problem.field, ("min_port_level",))
        self.assertEqual(dict(problem.args), {"unit": "galleon", "level": 5, "max": 4, "building": "naval_base"})
        self.assertIs(problem.severity, Severity.ERROR)
        self.assertEqual(problem.fixes, ("lower_min_port_level",))
        self.assertEqual(problem.message("es"),
                         "La unidad galleon pide un puerto de nivel 5, pero naval_base solo llega al nivel 4.")

    def test_the_maximum_itself_and_lower_levels_are_fine(self):
        files = {**self.BASE, "units/galleon.txt": unit("galleon", "min_port_level = 4", kind="naval"),
                 "units/sloop.txt": unit("sloop", "min_port_level = 0", kind="naval"),
                 "units/raft.txt": unit("raft", kind="naval")}
        self.assertEqual(self.levels(files), [])

    def test_without_a_naval_base_there_is_nothing_to_compare(self):
        """El minijuego solo trae ``fort``: su ``max_level = 6`` no es el de un puerto."""
        self.assertEqual(self.levels({"units/galleon.txt": unit("galleon", "min_port_level = 9", kind="naval")}), [])

    def test_the_port_is_the_building_of_type_naval_base(self):
        galleon = {"units/galleon.txt": unit("galleon", "min_port_level = 5", kind="naval")}
        by_type = {BUILDINGS: GAME_FILES[BUILDINGS] + naval_base(3, "harbour")}
        self.assertEqual(self.levels({**by_type, **galleon}), [("galleon", 5, 3, "harbour")])
        by_name = {BUILDINGS: GAME_FILES[BUILDINGS] + naval_base(3, kind=None)}
        self.assertEqual(self.levels({**by_name, **galleon}), [("galleon", 5, 3, "naval_base")])
        other = {BUILDINGS: GAME_FILES[BUILDINGS] + naval_base(3, "naval_base", "factory")}
        self.assertEqual(self.levels({**other, **galleon}), [], "se llama naval_base, pero es otro tipo de edificio")

    def test_with_two_ports_the_highest_counts(self):
        files = {BUILDINGS: GAME_FILES[BUILDINGS] + naval_base(3) + naval_base(7, "great_harbour"),
                 "units/galleon.txt": unit("galleon", "min_port_level = 5", kind="naval"),
                 "units/ark.txt": unit("ark", "min_port_level = 8", kind="naval")}
        self.assertEqual(self.levels(files), [("ark", 8, 7, "great_harbour")])

    def test_the_unsaved_document_is_what_counts(self):
        files = {**self.BASE, "units/galleon.txt": unit("galleon", "min_port_level = 5", kind="naval")}
        fixed = {VPath.of("units/galleon.txt"): unit("galleon", "min_port_level = 2", kind="naval").encode("cp1252")}
        self.assertEqual(self.levels(files, overrides=fixed), [])

    def test_the_explanation_shows_the_unit_and_the_building(self):
        files = {**self.BASE, "units/galleon.txt": unit("galleon", "min_port_level = 5", kind="naval")}
        [problem], ctx = run(self.game(files), {"unit_port_level_too_high"})
        explanation = explain(problem, ctx)
        self.assertEqual([(s.rel, s.line, s.excerpt, s.verdict) for s in explanation.steps],
                         [("units/galleon.txt", 3, "min_port_level = 5", VERDICT_LOSES),
                          (BUILDINGS, 5, "naval_base = {", VERDICT_WINS)])
        self.assertEqual(explanation.outcome("es"),
                         "Ningún puerto alcanza el nivel 5: la unidad galleon no se podrá construir en toda la partida.")


# --- government_flagtype_unknown ----------------------------------------------------------------------------


def junta(flag_type: str = "theocracy") -> str:
    return GAME_FILES[GOVERNMENTS] + crlf(f"junta = {{\n\tconservative = yes\n\tflagType = {flag_type}\n}}\n")


class FlagTypeTests(RuleTestCase):
    def types(self, mod_files, **kwargs):
        return sorted((p.args["government"], p.args["flag_type"], p.inherited)
                      for p in self.problems("government_flagtype_unknown", mod_files, baseline=True, **kwargs))

    def test_a_flag_type_no_country_has_is_reported_on_its_line(self):
        game = self.game({GOVERNMENTS: junta()})
        [problem] = [p for p in found(game, "government_flagtype_unknown") if p.args["government"] == "junta"]
        self.assertEqual((str(problem.rel), problem.line, problem.column), (GOVERNMENTS, 24, 2))
        self.assertEqual(problem.entity, (m.KIND_GOVERNMENT, "junta"))
        self.assertEqual(problem.field, ("flagType",))
        self.assertEqual(dict(problem.args), {"government": "junta", "flag_type": "theocracy"})
        self.assertIs(problem.severity, Severity.WARNING)
        self.assertIn("gfx/flags/<TAG>_theocracy.tga", problem.message("es"))

    def test_the_minigame_types_are_inherited_and_the_new_one_is_not(self):
        """El minijuego solo trae ``gfx/flags/AAA.tga``: ``monarchy`` y ``communist`` ya fallan sin el mod."""
        self.assertEqual(self.types({GOVERNMENTS: junta()}),
                         [("council", "communist", True), ("junta", "theocracy", False),
                          ("monarchy", "monarchy", True)])

    def test_one_country_with_that_flag_is_enough(self):
        files = {GOVERNMENTS: junta(), "gfx/flags/BBB_theocracy.tga": FLAG, "gfx/flags/AAA_monarchy.tga": FLAG}
        self.assertEqual(self.types(files), [("council", "communist", True)])

    def test_case_does_not_matter(self):
        files = {GOVERNMENTS: junta("Theocracy"), "gfx/flags/bbb_THEOCRACY.TGA": FLAG}
        self.assertNotIn("junta", [government for government, _, _ in self.types(files)])

    def test_only_tag_flags_count(self):
        files = {GOVERNMENTS: junta(), "gfx/flags/theocracy.tga": FLAG, "gfx/flags/x_theocracy.tga": FLAG,
                 "gfx/flags/BBBB_theocracy.tga": FLAG, "gfx/flags/BBB_theocracy.dds": FLAG,
                 "gfx/flags/1BB_theocracy.tga": FLAG,
                 "gfx/flags/old/BBB_theocracy.tga": FLAG, "gfx/pictures/BBB_theocracy.tga": FLAG}
        self.assertIn(("junta", "theocracy", False), self.types(files))

    def test_a_government_without_flag_type_uses_the_plain_flag(self):
        plain = GAME_FILES[GOVERNMENTS] + crlf("junta = {\n\tconservative = yes\n}\n")
        self.assertNotIn("junta", [government for government, _, _ in self.types({GOVERNMENTS: plain})])

    def test_without_any_country_flag_the_rule_is_silent(self):
        files = {rel: data for rel, data in GAME_FILES.items() if not rel.startswith("gfx/flags/")}
        files[GOVERNMENTS] = junta()
        files["gfx/flags/old/BBB_monarchy.tga"] = FLAG      # en una subcarpeta no es la bandera de ningún país
        game = MiniGame(build_layers(game=files, mod={}, mod_name="TestMod"))
        self.addCleanup(game.cleanup)
        self.assertEqual(found(game, "government_flagtype_unknown"), [])

    def test_the_explanation_names_the_flag_that_is_missing(self):
        [problem, *_], ctx = run(self.game({GOVERNMENTS: junta()}), {"government_flagtype_unknown"})
        [problem] = [p for p in Validator(ctx).validate(codes={"government_flagtype_unknown"}).problems
                     if p.args["government"] == "junta"]
        explanation = explain(problem, ctx)
        self.assertEqual([(s.rel, s.line, s.excerpt, s.verdict) for s in explanation.steps],
                         [(GOVERNMENTS, 24, "flagType = theocracy", VERDICT_WINS),
                          (None, None, "gfx/flags/<TAG>_theocracy.tga", VERDICT_MISSING)])


# --- culture_name_duplicate ---------------------------------------------------------------------------------


def culture_group(name: str, *cultures: str) -> str:
    body = "".join(f"\t{culture} = {{\n\t\tcolor = {{ 1 2 3 }}\n\t}}\n" for culture in cultures)
    return crlf(f"{name} = {{\n\tleader = european\n{body}}}\n")


class CultureDuplicateTests(RuleTestCase):
    def test_the_same_culture_in_two_groups(self):
        files = {CULTURES: GAME_FILES[CULTURES] + culture_group("east_folk", "eastlander", "alander")}
        [problem] = self.problems("culture_name_duplicate", files)
        self.assertEqual((str(problem.rel), problem.line), (CULTURES, 26))
        self.assertEqual(problem.entity, (m.KIND_CULTURE, "alander"))
        self.assertEqual(dict(problem.args), {"culture": "alander", "group": "east_folk",
                                              "first_group": "north_folk", "first_line": 4})
        self.assertIs(problem.severity, Severity.ERROR)
        self.assertEqual(problem.message("es"), "La cultura alander está definida dos veces: en el grupo east_folk "
                                                "y en el grupo north_folk (línea 4).")

    def test_twice_in_the_same_group(self):
        files = {CULTURES: GAME_FILES[CULTURES] + culture_group("east_folk", "eastlander", "eastlander")}
        [problem] = self.problems("culture_name_duplicate", files)
        self.assertEqual((problem.args["culture"], problem.args["group"], problem.args["first_group"]),
                         ("eastlander", "east_folk", "east_folk"))

    def test_three_definitions_give_two_problems(self):
        files = {CULTURES: GAME_FILES[CULTURES] + culture_group("east_folk", "alander")
                 + culture_group("west_folk", "alander")}
        self.assertEqual([(p.args["group"], p.line) for p in self.problems("culture_name_duplicate", files)],
                         [("east_folk", 23), ("west_folk", 29)])

    def test_the_copy_of_the_mod_replaces_the_game_file_and_is_no_duplicate(self):
        """``cultures.txt`` es un archivo entero: las culturas del juego que el mod vuelve a traer no se repiten."""
        self.assertEqual(self.problems("culture_name_duplicate", {CULTURES: GAME_FILES[CULTURES]}), [])
        self.assertEqual(self.problems("culture_name_duplicate", {}), [])

    def test_a_group_field_named_like_a_culture_is_not_a_culture(self):
        files = {CULTURES: GAME_FILES[CULTURES] + culture_group("east_folk", "eastlander").replace(
            "leader = european", "leader = european\r\n\tunion = AAA\r\n\tunit = Generic")}
        self.assertEqual(self.problems("culture_name_duplicate", files), [])

    def test_the_explanation_shows_both_definitions(self):
        files = {CULTURES: GAME_FILES[CULTURES] + culture_group("east_folk", "alander")}
        [problem], ctx = run(self.game(files), {"culture_name_duplicate"})
        explanation = explain(problem, ctx)
        self.assertEqual([(s.layer, s.rel, s.line, s.excerpt, s.verdict) for s in explanation.steps],
                         [(LAYER_MOD, CULTURES, 4, "alander = {", VERDICT_WINS),
                          (LAYER_MOD, CULTURES, 23, "alander = {", VERDICT_LOSES),
                          (LAYER_GAME, CULTURES, 4, "", VERDICT_LOSES)],
                         "las dos del archivo del mod y, debajo, la del juego que ese archivo sustituye")
        self.assertIn("sin comprobar en el juego", explanation.outcome("es"))


# --- bookmark_without_pops ----------------------------------------------------------------------------------


class BookmarkPopsTests(RuleTestCase):
    """El minijuego trae ``history/pops/1836.1.1`` y ``1861.1.1`` y bookmarks en esas dos fechas."""

    def bookmarks(self, *extra: str, mod_files=None, **kwargs):
        files = {BOOKMARKS: GAME_FILES[BOOKMARKS] + "".join(extra), **(mod_files or {})}
        return self.problems("bookmark_without_pops", files, **kwargs)

    def test_a_bookmark_before_every_pops_folder_is_a_warning_on_its_date(self):
        [problem] = self.bookmarks(bookmark("MG_EARLY", 'desc = "MG_EARLY_DESC"', "date = 1820.6.1"))
        self.assertEqual((str(problem.rel), problem.line, problem.column), (BOOKMARKS, 14, 2))
        self.assertEqual(problem.entity, (m.KIND_BOOKMARK, "MG_EARLY"))
        self.assertEqual(problem.field, ("date",))
        self.assertEqual(dict(problem.args), {"bookmark": "MG_EARLY", "date": "1820.6.1"})
        self.assertIs(problem.severity, Severity.WARNING)
        self.assertEqual(problem.fixes, ())

    def test_a_folder_of_the_same_date_or_an_earlier_one_is_enough(self):
        same = bookmark("MG_SAME", "date = 1836.1.1")
        later = bookmark("MG_BETWEEN", "date = 1850.3.2")            # la de 1836.1.1 es anterior
        last = bookmark("MG_LAST", "date = 1900.1.1")
        self.assertEqual(self.bookmarks(same, later, last), [])

    def test_one_day_before_the_first_folder_is_not_enough(self):
        self.assertEqual([p.args["date"] for p in self.bookmarks(bookmark("MG_EVE", "date = 1835.12.31"))],
                         ["1835.12.31"])

    def test_a_pops_folder_of_the_mod_counts(self):
        early = bookmark("MG_EARLY", "date = 1820.6.1")
        pops = {"history/pops/1820.1.1/Mod.txt": crlf("1 = {\n\tfarmers = {\n\t\tculture = alander\n"
                                                      "\t\treligion = sunfaith\n\t\tsize = 10\n\t}\n}\n")}
        self.assertEqual(self.bookmarks(early, mod_files=pops), [])
        loose = {"history/pops/Mod.txt": pops["history/pops/1820.1.1/Mod.txt"],
                 "history/pops/old/Mod.txt": pops["history/pops/1820.1.1/Mod.txt"]}
        self.assertEqual(len(self.bookmarks(early, mod_files=loose)), 1, "un archivo suelto o sin fecha no es una "
                                                                         "carpeta de fecha")

    def test_a_bookmark_without_a_date_is_not_this_problem(self):
        self.assertEqual(self.bookmarks(bookmark("MG_NONE"), bookmark("MG_BAD", "date = soon")), [])

    def test_the_unsaved_document_is_what_counts(self):
        unsaved = {VPath.of(BOOKMARKS): (GAME_FILES[BOOKMARKS] + bookmark("MG_EARLY", "date = 1820.6.1")).encode()}
        [problem] = self.problems("bookmark_without_pops", {}, overrides=unsaved)
        self.assertEqual(problem.args["bookmark"], "MG_EARLY")

    def test_the_texts_do_not_claim_which_folder_the_game_uses(self):
        """Qué carpeta usa el juego es [verificar en juego] (wizard §14.10): el texto lo dice y no afirma más."""
        game = self.game({BOOKMARKS: GAME_FILES[BOOKMARKS] + bookmark("MG_EARLY", "date = 1820.6.1")})
        [problem], ctx = run(game, {"bookmark_without_pops"})
        explanation = explain(problem, ctx)
        self.assertEqual(problem.message("es"), "El bookmark MG_EARLY empieza el 1820.6.1 y no hay ninguna carpeta "
                                                "history/pops/<fecha> con una fecha igual o anterior.")
        self.assertIn("puede empezar sin población", explanation.outcome("es"))
        self.assertIn("sin comprobar en el juego", explanation.outcome("es"))
        self.assertIn("may start without population", explanation.outcome("en"))
        self.assertIn("not been checked in game", explanation.outcome("en"))
        self.assertEqual([(s.rel, s.line, s.excerpt, s.verdict) for s in explanation.steps],
                         [(BOOKMARKS, 13, "date = 1820.6.1", VERDICT_WINS),
                          (None, None, "history/pops/<≤ 1820.6.1>/", VERDICT_MISSING)],
                         "sin veredicto sobre las carpetas posteriores")


# --- bookmark_camera_outside_map ----------------------------------------------------------------------------


class BookmarkCameraTests(RuleTestCase):
    """El mapa del minijuego mide 64×32."""

    def cameras(self, *extra: str, **kwargs):
        files = {BOOKMARKS: GAME_FILES[BOOKMARKS] + "".join(extra)}
        return self.problems("bookmark_camera_outside_map", files, **kwargs)

    def test_a_camera_right_of_the_map_is_a_warning_on_that_field(self):
        [problem] = self.cameras(bookmark("MG_FAR", "date = 1836.1.1", "cameraX = 65", "cameraY = 10"))
        self.assertEqual((str(problem.rel), problem.line, problem.column), (BOOKMARKS, 14, 2))
        self.assertEqual(problem.entity, (m.KIND_BOOKMARK, "MG_FAR"))
        self.assertEqual(problem.field, ("cameraX",))
        self.assertEqual(dict(problem.args), {"bookmark": "MG_FAR", "x": "65", "y": "10", "width": 64, "height": 32})
        self.assertIs(problem.severity, Severity.WARNING)
        self.assertEqual(problem.fixes, ("move_camera_into_map",))
        self.assertEqual(problem.message("es"),
                         "La cámara del bookmark MG_FAR (65, 10) cae fuera del mapa, que mide 64×32.")

    def test_each_axis_has_its_own_limit(self):
        [below] = self.cameras(bookmark("MG_LOW", "cameraX = 40", "cameraY = 33"))
        self.assertEqual((below.field, below.line), (("cameraY",), 14))
        [negative] = self.cameras(bookmark("MG_NEG", "cameraX = 5", "cameraY = -1"))
        self.assertEqual(negative.field, ("cameraY",))
        [left] = self.cameras(bookmark("MG_LEFT", "cameraX = -3", "cameraY = 5"))
        self.assertEqual(left.field, ("cameraX",))
        [both] = self.cameras(bookmark("MG_BOTH", "cameraX = 900", "cameraY = 900"))
        self.assertEqual(both.field, ("cameraX",), "un problema por bookmark, en la primera coordenada")

    def test_inside_and_on_the_border_are_fine(self):
        inside = bookmark("MG_IN", "cameraX = 40", "cameraY = 20")       # 40 cabe en el ancho, no en el alto
        border = bookmark("MG_EDGE", "cameraX = 64", "cameraY = 0")
        corner = bookmark("MG_CORNER", "cameraX = 0", "cameraY = 32")
        self.assertEqual(self.cameras(inside, border, corner), [])

    def test_a_bookmark_without_camera_gives_nothing(self):
        self.assertEqual(self.cameras(bookmark("MG_PLAIN", "date = 1836.1.1"), bookmark("MG_WORD", "cameraX = east")),
                         [], "el minijuego tal cual no tiene cámaras; un valor que no es un número es de bad_type")

    def test_without_the_provinces_bitmap_the_rule_is_silent(self):
        files = {rel: data for rel, data in GAME_FILES.items() if rel != "map/provinces.bmp"}
        files[BOOKMARKS] = GAME_FILES[BOOKMARKS] + bookmark("MG_FAR", "cameraX = 9000", "cameraY = 9000")
        game = MiniGame(build_layers(game=files, mod={}, mod_name="TestMod"))
        self.addCleanup(game.cleanup)
        self.assertEqual(found(game, "bookmark_camera_outside_map"), [])

    def test_the_size_is_the_one_of_the_bitmap_default_map_names(self):
        from _minigame import provinces_bmp

        default_map = GAME_FILES["map/default.map"].replace('provinces = "provinces.bmp"', 'provinces = "big.bmp"')
        big = bytearray(provinces_bmp())
        big[18:22] = (640).to_bytes(4, "little")                      # solo la cabecera: la regla no lee más
        files = {"map/default.map": default_map, "map/big.bmp": bytes(big),
                 BOOKMARKS: GAME_FILES[BOOKMARKS] + bookmark("MG_FAR", "cameraX = 500", "cameraY = 10")}
        self.assertEqual(found(self.game(files), "bookmark_camera_outside_map"), [])

    def test_the_unsaved_document_is_what_counts(self):
        far = bookmark("MG_FAR", "cameraX = 65", "cameraY = 10")
        fixed = {VPath.of(BOOKMARKS): (GAME_FILES[BOOKMARKS] + far.replace("65", "60")).encode()}
        self.assertEqual(self.cameras(far, overrides=fixed), [])

    def test_the_explanation_shows_the_camera_and_the_bitmap(self):
        game = self.game({BOOKMARKS: GAME_FILES[BOOKMARKS] + bookmark("MG_FAR", "cameraX = 65", "cameraY = 10")})
        [problem], ctx = run(game, {"bookmark_camera_outside_map"})
        explanation = explain(problem, ctx)
        self.assertEqual([(s.rel, s.line, s.excerpt, s.verdict) for s in explanation.steps],
                         [(BOOKMARKS, 13, "cameraX = 65", VERDICT_LOSES),
                          ("map/provinces.bmp", None, "", VERDICT_WINS)])


# --- arreglos (SimpleFix, plan = aplicación) -----------------------------------------------------------------


def overrides_of(project) -> dict:
    return {handle.rel: None if handle.deleted else codec_for(handle.kind).snapshot(handle.model)
            for handle in project.ws.dirty()}


def project_problems(project, code):
    snap = project.vfs.snapshot()
    overrides = overrides_of(project)
    ctx = build_context(snap, build_index(snap, None, overrides), overrides)
    return list(Validator(ctx).validate(codes={code}).problems)


def state(project) -> tuple:
    ws = project.ws
    return (ws.history(), ws.redo_history(), [h.rel for h in ws.dirty()], [h.rel for h in ws.documents()])


class FixTestCase(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def open(self, **kwargs):
        game = build_minigame(mod=False, **kwargs)
        self.addCleanup(game.cleanup)
        project = Project.open(game.game_root, game.mod_root)
        self.addCleanup(project.close, discard=True)
        return game, project

    def fix(self, project, key: str, code: str):
        """Plan (sin efectos), aplicación (un paso de deshacer) y revalidación; devuelve (plan, problema, bytes)."""
        [problem] = project_problems(project, code)
        self.assertEqual([spec.key for spec in fixes_for(problem)], [key], "es el SimpleFix")
        before = state(project)
        plan = plan_fix(key, problem, project)
        self.assertEqual(plan_fix(key, problem, project).changes, plan.changes)
        self.assertEqual(state(project), before, "plan no cambia nada (pila de deshacer incluida)")
        apply_fix(key, problem, project, expected=plan)
        self.assertEqual(len(project.ws.history()), len(before[0]) + 1, "un solo paso de deshacer")
        self.assertEqual(project.ws.history()[0][0], f"undo.fix_{key}")
        self.assertEqual(project_problems(project, code), [], "revalidar quita el problema")
        handle = project.ws.peek(problem.rel)
        return plan, problem, codec_for(handle.kind).snapshot(handle.model)


class LowerPortLevelFixTests(FixTestCase):
    GALLEON = unit("galleon", "active = no", "min_port_level = 9 # demasiado", "hull = 40", kind="naval")
    FILES = {BUILDINGS: GAME_FILES[BUILDINGS] + naval_base(4), "units/galleon.txt": GALLEON}

    def test_it_changes_only_that_value_in_one_undoable_step(self):
        game, project = self.open(mod_files=self.FILES)
        plan, problem, after = self.fix(project, "lower_min_port_level", "unit_port_level_too_high")
        [change] = plan.changes
        self.assertEqual((str(change.rel), change.action), ("units/galleon.txt", ACTION_MODIFY))
        self.assertIn("-\tmin_port_level = 9 # demasiado", change.diff)
        self.assertIn("+\tmin_port_level = 4 # demasiado", change.diff)
        self.assertEqual(after, self.GALLEON.replace("min_port_level = 9", "min_port_level = 4").encode("cp1252"),
                         "solo ese token: el comentario, la sangría y los CRLF siguen")
        project.ws.undo()
        self.assertEqual(project.ws.dirty(), [])
        self.assertEqual(len(project_problems(project, "unit_port_level_too_high")), 1)

    def test_label_safety_and_refusals(self):
        game, project = self.open(mod_files=self.FILES)
        [problem] = project_problems(project, "unit_port_level_too_high")
        spec = FIXES["lower_min_port_level"]
        self.assertFalse(spec.safe, "sustituye un valor: pide confirmación")
        self.assertEqual(spec.label(problem, "es"), "Bajar «min_port_level» de galleon a 4")
        self.assertEqual(spec.label(problem, "en"), "Lower “min_port_level” of galleon to 4")
        apply_fix("lower_min_port_level", problem, project)
        with self.assertRaises(FixError) as raised:
            plan_fix("lower_min_port_level", problem, project)
        self.assertEqual(raised.exception.code, "nothing_to_do")
        with self.assertRaises(FixError) as raised:
            plan_fix("lower_min_port_level", problems_of_another_code(project), project)
        self.assertEqual(raised.exception.code, "not_applicable")

    def test_a_unit_of_the_game_is_copied_to_the_mod(self):
        game_files = {BUILDINGS: GAME_FILES[BUILDINGS] + naval_base(4), "units/galleon.txt": self.GALLEON}
        game, project = self.open(game_files=game_files)
        plan, _, after = self.fix(project, "lower_min_port_level", "unit_port_level_too_high")
        self.assertEqual([(str(c.rel), c.action) for c in plan.changes], [("units/galleon.txt", ACTION_COPY_FROM_GAME)])
        self.assertEqual(game.game("units/galleon.txt").read_bytes(), self.GALLEON.encode("cp1252"), "I1: el juego, "
                                                                                                    "intacto")
        self.assertIn(b"min_port_level = 4", after)


def problems_of_another_code(project):
    """Un problema que no es de puertos (sin ``max`` en sus args): el arreglo debe rechazarlo."""
    return project_problems(project, "peace_order_unknown")[0]


class MoveCameraFixTests(FixTestCase):
    FAR = bookmark("MG_FAR", "date = 1836.1.1", "cameraX = 900 # lejos", "cameraY = 10")

    def test_only_the_coordinate_outside_moves_to_the_nearest_border(self):
        game, project = self.open(mod_files={BOOKMARKS: GAME_FILES[BOOKMARKS] + self.FAR})
        plan, problem, after = self.fix(project, "move_camera_into_map", "bookmark_camera_outside_map")
        [change] = plan.changes
        self.assertEqual((str(change.rel), change.action), (BOOKMARKS, ACTION_MODIFY))
        self.assertEqual(after, (GAME_FILES[BOOKMARKS] + self.FAR.replace("cameraX = 900", "cameraX = 64")).encode(),
                         "cameraY, el comentario y los otros bookmarks no cambian")
        project.ws.undo()
        self.assertEqual(project.ws.dirty(), [])

    def test_negative_and_both_axes(self):
        both = bookmark("MG_BOTH", "cameraX = -7", "cameraY = 4000")
        game, project = self.open(mod_files={BOOKMARKS: GAME_FILES[BOOKMARKS] + both})
        _, _, after = self.fix(project, "move_camera_into_map", "bookmark_camera_outside_map")
        self.assertTrue(after.endswith(bookmark("MG_BOTH", "cameraX = 0", "cameraY = 32").encode()), after[-80:])

    def test_only_the_bookmark_of_the_problem_is_touched(self):
        other = bookmark("MG_OTHER", "cameraX = 700", "cameraY = 700")
        game, project = self.open(mod_files={BOOKMARKS: GAME_FILES[BOOKMARKS] + self.FAR + other})
        problems = {p.args["bookmark"]: p for p in project_problems(project, "bookmark_camera_outside_map")}
        apply_fix("move_camera_into_map", problems["MG_FAR"], project)
        self.assertEqual([p.args["bookmark"] for p in project_problems(project, "bookmark_camera_outside_map")],
                         ["MG_OTHER"])

    def test_label_safety_and_refusals(self):
        game, project = self.open(mod_files={BOOKMARKS: GAME_FILES[BOOKMARKS] + self.FAR})
        [problem] = project_problems(project, "bookmark_camera_outside_map")
        spec = FIXES["move_camera_into_map"]
        self.assertFalse(spec.safe)
        self.assertEqual(spec.label(problem, "es"), "Llevar la cámara de MG_FAR dentro del mapa")
        self.assertEqual(spec.label(problem, "en"), "Move the camera of MG_FAR inside the map")
        plan = plan_fix("move_camera_into_map", problem, project)
        apply_fix("move_camera_into_map", problem, project, expected=plan)
        with self.assertRaises(FixError) as raised:
            apply_fix("move_camera_into_map", problem, project, expected=plan)
        self.assertIn(raised.exception.code, ("nothing_to_do", "plan_changed"))
        with self.assertRaises(FixError) as raised:
            plan_fix("move_camera_into_map", problems_of_another_code(project), project)
        self.assertEqual(raised.exception.code, "not_applicable")


# --- catálogo y lectura sin escritura -----------------------------------------------------------------------


class CatalogueTests(RuleTestCase):
    def test_the_six_codes_are_registered_with_their_severity_family_and_texts(self):
        from vic2studio.core.texts import load_texts
        from vic2studio.core.validate import discover_rules

        rules = discover_rules()
        self.assertEqual({code: (rules[code].severity, rules[code].family, rules[code].fixes) for code in NEW_CODES}, {
            "sprite_missing": (Severity.WARNING, "units", ()),
            "unit_port_level_too_high": (Severity.ERROR, "units", ("lower_min_port_level",)),
            "government_flagtype_unknown": (Severity.WARNING, "countries", ()),
            "culture_name_duplicate": (Severity.ERROR, "cultures", ()),
            "bookmark_without_pops": (Severity.WARNING, "bookmarks", ()),
            "bookmark_camera_outside_map": (Severity.WARNING, "bookmarks", ("move_camera_into_map",)),
        })
        for lang in ("es", "en"):
            texts = load_texts(lang)
            for code in NEW_CODES:
                for key in (f"issue.{code}", f"explain.title.{code}", f"explain.outcome.{code}"):
                    self.assertIn(key, texts)
        self.assertEqual(RULES["sprite_missing"].scope, "project")

    def test_validating_writes_nothing(self):
        files = {"units/lancer.txt": unit("lancer", "sprite = Uhlan", "min_port_level = 9"),
                 BUILDINGS: GAME_FILES[BUILDINGS] + naval_base(4), GOVERNMENTS: junta(),
                 CULTURES: GAME_FILES[CULTURES] + culture_group("east_folk", "alander"),
                 BOOKMARKS: GAME_FILES[BOOKMARKS] + bookmark("MG_FAR", "date = 1820.1.1", "cameraX = 900")}
        game = self.game(files, GAME_ACTORS)
        before = game.tree(game.game_root)
        problems, _ = run(game, NEW_CODES)
        self.assertEqual({p.code for p in problems}, set(NEW_CODES), "las seis a la vez")
        self.assertEqual(game.tree(game.game_root), before, "I4: ni en el juego ni en el mod")


class F7Tests(RuleTestCase):
    """Decisión 3 del informe de la iteración 4: F7 es la validación global más los problemas de esquema
    (``Session`` los une con ``with_schema_problems``). Las reglas nuevas salen ahí junto a los de esquema de la
    misma entidad, con el mismo id (el editor que se abre) y el campo."""

    def test_the_new_problems_reach_f7_next_to_the_schema_ones(self):
        from vic2studio.ui.session import with_schema_problems

        files = {"units/lancer.txt": unit("lancer", "sprite = Uhlan", "mystery = 1"),
                 BOOKMARKS: GAME_FILES[BOOKMARKS] + bookmark("MG_FAR", "date = 1990.1.1", "cameraX = 900")}
        game = self.game(files, GAME_ACTORS)
        snap = game.snapshot()
        ctx = build_context(snap, build_index(snap, None))
        base_snap = game_only_snapshot(snap)
        base = compute_baseline(build_context(base_snap, build_index(base_snap, None), game_only=True))
        report = with_schema_problems(Validator(ctx, baseline=base).validate(), ctx)
        own = {(p.code, p.entity[1], p.field) for p in report.visible() if p.entity is not None}
        self.assertLessEqual({("sprite_missing", "lancer", ("sprite",)), ("unknown_field", "lancer", ("mystery",)),
                              ("bookmark_camera_outside_map", "MG_FAR", ("cameraX",)),
                              ("bookmark_date_outside_defines", "MG_FAR", ("date",))}, own)
        codes = [p.code for p in report.problems]
        self.assertEqual(codes.count("sprite_missing"), 1)
        self.assertEqual(codes.count("bookmark_camera_outside_map"), 1)
        hidden = {p.code for p in report.problems if p.inherited}
        self.assertIn("government_flagtype_unknown", hidden, "los del juego base, ocultos como el resto (I11)")


# --- corpus -------------------------------------------------------------------------------------------------


def full_vsm() -> Path | None:
    mod = user_mod()
    return mod if mod is not None and (mod / "localisation" / "text.csv").is_file() else None


@unittest.skipUnless(vanilla_root(), "requiere el corpus (VIC2_CORPUS)")
class CorpusTests(unittest.TestCase):
    """Vanilla no da ninguno de los seis (ni siquiera heredados) y los hechos medidos siguen ahí."""

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="vic2studio-y1-corpus-"))
        cls.cache = FactsCache(cls.base / "cache")
        cls.empty = cls.base / "EmptyMod"
        cls.empty.mkdir()
        cls.ctx = cls.context(cls.empty)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    @classmethod
    def context(cls, mod: Path, descriptor: Path | None = None):
        vfs = VirtualFS(vanilla_root(), mod, descriptor=descriptor)
        vfs.scan()
        snap = vfs.snapshot()
        return build_context(snap, build_index(snap, cls.cache))

    def setUp(self):
        isolate_appdirs(self)

    def test_vanilla_gives_none_of_the_six(self):
        report = Validator(self.ctx).validate(codes=set(NEW_CODES))
        self.assertEqual([(p.code, str(p.rel), dict(p.args)) for p in report.problems], [])

    def test_the_measured_facts_behind_the_rules(self):
        from vic2studio.core.validate.rules import bookmarks, countries, units

        index = self.ctx.index
        self.assertEqual(index.count(m.ACTOR_KIND), 285)
        self.assertEqual(index.count(m.KIND_GRAPHICAL_CULTURE), 22)
        blocks = list(units.unit_blocks(self.ctx))
        self.assertEqual(len(blocks), 21)
        fields = [entry.key.text for _, block in blocks for entry in units.model_fields(block)]
        self.assertEqual((fields.count("sprite"), fields.count("sprite_override"), fields.count("sprite_mount")),
                         (18, 3, 4))
        has_actor = units.actor_lookup(index)
        own = [block.get_text("sprite") for _, block in blocks if block.find("sprite_override") is not None]
        self.assertEqual([has_actor(sprite) for sprite in own], [False, False, False],
                         "con sprite_override, el sprite propio no es ningún actor: por eso no se comprueba")
        self.assertEqual(units.port_cap(index), ("naval_base", 6))
        levels = [int(block.get_text("min_port_level")) for _, block in blocks if block.has("min_port_level")]
        self.assertEqual((len(levels), max(levels)), (10, 5))
        self.assertEqual(countries.flag_types(index), {"communist", "fascist", "monarchy", "republic"})
        self.assertEqual([str(d) for d in bookmarks.pops_dates(self.ctx)], ["1836.1.1", "1861.4.14"])
        self.assertEqual(self.ctx.rules.map_size, (5616, 2160))
        self.assertEqual(len(bookmarks.effective_bookmarks(self.ctx)[1]), 2)
        self.assertEqual(index.count(m.KIND_CULTURE), 226)

    def test_planted_problems_over_vanilla_are_found(self):
        """Con los datos reales las reglas siguen encontrando lo suyo (no pasan por no mirar)."""
        mod = self.base / "Planted"
        (mod / "units").mkdir(parents=True)
        (mod / "common").mkdir()
        (mod / "units" / "zeppelin.txt").write_bytes(
            unit("zeppelin", "sprite = Zeppelin", "min_port_level = 7", kind="naval").encode("cp1252"))
        # Copias en una carpeta temporal de archivos del juego con un añadido inventado (nunca en el repositorio).
        game = vanilla_root()
        for name, extra in ((GOVERNMENTS, crlf("junta = {\n\tfascist = yes\n\tflagType = theocracy\n}\n")),
                            (BOOKMARKS, bookmark("TST_EARLY", "date = 1700.1.1", "cameraX = 6000", "cameraY = 100")),
                            (CULTURES, culture_group("tst_folk", "tst_first", "tst_first"))):
            (mod / name).write_bytes((game / name).read_bytes() + b"\r\n" + extra.encode("cp1252"))
        report = Validator(self.context(mod)).validate(codes=set(NEW_CODES))
        self.assertEqual(sorted((p.code, str(p.rel)) for p in report.problems), [
            ("bookmark_camera_outside_map", BOOKMARKS), ("bookmark_without_pops", BOOKMARKS),
            ("culture_name_duplicate", CULTURES), ("government_flagtype_unknown", GOVERNMENTS),
            ("sprite_missing", "units/zeppelin.txt"), ("unit_port_level_too_high", "units/zeppelin.txt")])

    @unittest.skipUnless(full_vsm(), "requiere el mod del usuario completo")
    def test_the_user_mod_gives_none_of_the_six(self):
        """Solo lectura: el mod real se recorre con la VFS (como ``test_validate_corpus``), nunca se abre como
        proyecto, y la caché va a una carpeta temporal."""
        mod = full_vsm()
        before = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in mod.rglob("*") if p.is_file()}
        report = Validator(self.context(mod, mod.with_suffix(".mod"))).validate(codes=set(NEW_CODES))
        self.assertEqual([(p.code, str(p.rel), dict(p.args)) for p in report.problems], [])
        self.assertEqual({p: (p.stat().st_size, p.stat().st_mtime_ns) for p in mod.rglob("*") if p.is_file()}, before)
        self.assertFalse((mod / ".vic2studio").exists())


if __name__ == "__main__":
    unittest.main()
