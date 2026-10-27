"""Reglas de validación (wizard §11): el minijuego con un fallo inyectado por regla.

Cada caso parte del minijuego con el mod vacío, añade archivos al mod (o cambia
el descriptor) y comprueba que sale el código esperado, con sus argumentos, en el
archivo esperado. ``ExpectedCleanTests`` fija lo que da el minijuego sin tocar:
solo los heredados que trae a propósito.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import descriptor_bytes, isolate_appdirs  # noqa: E402
from _minigame import GAME_FILES, build_minigame  # noqa: E402
from vic2studio.core.clausewitz import Severity  # noqa: E402
from vic2studio.core.index import build_index  # noqa: E402
from vic2studio.core.validate import (RULES, Validator, build_context, compute_baseline,  # noqa: E402
                                      discover_rules, game_only_snapshot, rule)
from vic2studio.core.validate import registry  # noqa: E402

AAA = "history/countries/AAA - Aland.txt"
ALAND = "common/countries/Aland.txt"
COUNTRIES = "common/countries.txt"


def history(extra: str) -> str:
    return "capital = 1\r\nprimary_culture = alander\r\ngovernment = monarchy\r\n" + extra.replace("\n", "\r\n")


def validate(game, *, codes=None, replace_paths=(), baseline=False, overrides=None):
    snap = game.snapshot(replace_paths=replace_paths)
    ctx = build_context(snap, build_index(snap, None, overrides), overrides)
    base = None
    if baseline:
        game_snap = game_only_snapshot(snap)
        base = compute_baseline(build_context(game_snap, build_index(game_snap, None), game_only=True))
    return Validator(ctx, baseline=base).validate(codes=codes)


# código → (archivos del mod, argumentos que deben aparecer en algún problema de ese código, archivo del problema)
CASES = {
    "unclosed_block": ({"decisions/broken.txt": "political_decisions = {\r\n\td = { }\r\n"},
                       {"key": "political_decisions"}, "decisions/broken.txt"),
    "non_game_encoding": ({"events/utf8.txt": 'country_event = { id = 5001 title = "Café" }\r\n'.encode("utf-8")},
                          {"source": "clausewitz"}, "events/utf8.txt"),
    "unreadable_encoding": ({"events/utf16.txt": "country_event = { id = 5002 }".encode("utf-16")}, {},
                            "events/utf16.txt"),
    "stray_bom": ({"events/bom.txt": b"\xef\xbb\xbfcountry_event = { id = 5003 title = \"Caf\xe9\" }\r\n"}, {},
                  "events/bom.txt"),
    "semicolon_in_quotes": ({"localisation/00_bad.csv": 'bad_key;"A; B";;;;;;;;;;;;;x\r\n'}, {"key": "bad_key"},
                            "localisation/00_bad.csv"),
    "duplicate_key": ({"localisation/00_dup.csv": "k;A;;;;;;;;;;;;;x\r\nk;B;;;;;;;;;;;;;x\r\n"}, {"key": "k"},
                      "localisation/00_dup.csv"),
    "mod_shadow_identical": ({"common/cb_types.txt": GAME_FILES["common/cb_types.txt"]}, {},
                             "common/cb_types.txt"),
    "case_collision": ({"events/Same.txt": "country_event = { id = 5004 }\r\n",
                        "events/same.txt": "country_event = { id = 5005 }\r\n"}, {}, None),
    "windows_reserved_name": ({"events/CON.txt": "country_event = { id = 5006 }\r\n"}, {"folder": "CON.txt"},
                              "events/CON.txt"),
    "path_too_long": ({"events/" + "x" * 120 + "/" + "y" * 120 + ".txt": "a = 1\r\n"}, {}, None),
    "tag_not_registered": ({"history/countries/EEE - Esland.txt": history(""),
                            "history/provinces/north/1 - Capital.txt": "owner = EEE\r\nadd_core = EEE\r\n"},
                           {"tag": "EEE"}, "history/countries/EEE - Esland.txt"),
    "tag_after_dynamic_tags": ({COUNTRIES: GAME_FILES[COUNTRIES] + 'ZZZ = "countries/Aland.txt"\r\n'},
                               {"tag": "ZZZ"}, COUNTRIES),
    "tag_invalid": ({COUNTRIES: 'Abc = "countries/Aland.txt"\r\n' + GAME_FILES[COUNTRIES]}, {"tag": "Abc"}, COUNTRIES),
    "tag_taken": ({COUNTRIES: GAME_FILES[COUNTRIES] + 'AAA = "countries/Aland.txt"\r\n'}, {"tag": "AAA"}, COUNTRIES),
    "country_file_missing": ({COUNTRIES: 'EEE = "countries/Nowhere.txt"\r\n' + GAME_FILES[COUNTRIES]},
                             {"tag": "EEE", "file": "countries/Nowhere.txt"}, COUNTRIES),
    "country_history_missing": ({COUNTRIES: 'EEE = "countries/Aland.txt"\r\n' + GAME_FILES[COUNTRIES]},
                                {"tag": "EEE"}, COUNTRIES),
    "country_history_duplicate": ({"history/countries/AAA - Otra.txt": history("")}, {"tag": "AAA"},
                                  "history/countries/AAA - Otra.txt"),
    "ruling_party_not_of_country": ({AAA: history("ruling_party = shared_party\n")},
                                    {"tag": "AAA", "party": "shared_party"}, AAA),
    "ruling_party_ideology_not_allowed": (
        {AAA: history("ruling_party = AAA_conservative\n").replace("monarchy", "council")},
        {"party": "AAA_conservative", "ideology": "conservative", "government": "council"}, AAA),
    "party_unknown_policy": ({ALAND: GAME_FILES[ALAND].replace("war_policy", "social_policy")},
                             {"policy": "social_policy", "value": "pro_military", "party": "AAA_conservative"}, ALAND),
    "government_missing_in_rebel_map": (
        {"common/governments.txt": GAME_FILES["common/governments.txt"]
         + "empire = {\r\n\tconservative = yes\r\n}\r\n"},
        {"government": "empire", "rebel": "free_rebels"}, "common/rebel_types.txt"),
    "government_election_without_duration": (
        {"common/governments.txt": GAME_FILES["common/governments.txt"].replace("duration = 48", "")},
        {"government": "republic"}, "common/governments.txt"),
    "upper_house_sum": ({AAA: history("upper_house = {\n\tconservative = 50\n\tliberal = 30\n}\n")},
                        {"tag": "AAA", "total": 80.0}, AAA),
    "duplicate_field": ({AAA: history("civilized = yes\ncivilized = yes\n")}, {"name": "civilized"}, AAA),
    "culture_unknown": ({AAA: history("culture = nowhere_folk\n")}, {"name": "nowhere_folk"}, AAA),
    "religion_unknown": ({AAA: history("religion = nofaith\n")}, {"name": "nofaith"}, AAA),
    "government_unknown": ({AAA: history("1850.1.1 = { government = nogov }\n")}, {"name": "nogov"}, AAA),
    "nationalvalue_unknown": ({AAA: history("nationalvalue = nv_tradition\n")}, {"name": "nv_tradition"}, AAA),
    "technology_unknown": ({AAA: history("steam_drill = 1\n")}, {"name": "steam_drill"}, AAA),
    "invention_unknown": ({AAA: history("air_kitchens = yes\n")}, {"name": "air_kitchens"}, AAA),
    "reform_unknown": ({AAA: history("slavery = maybe_slavery\n")}, {"group": "slavery", "name": "maybe_slavery"}, AAA),
    "tech_school_unknown": ({AAA: history("schools = noschool\n")}, {"name": "noschool"}, AAA),
    "decision_unknown": ({AAA: history("decision = nodecision\n")}, {"name": "nodecision"}, AAA),
    "province_unknown": ({AAA: history("").replace("capital = 1", "capital = 77")}, {"name": "77"}, AAA),
    "oob_file_missing": ({AAA: history('oob = "AAA_oob.txt"\n')}, {"file": "history/units/aaa_oob.txt"}, AAA),
    "graphical_culture_unknown": ({ALAND: GAME_FILES[ALAND].replace("Generic", "NoGC")}, {"name": "NoGC"}, ALAND),
    "ideology_unknown": ({ALAND: GAME_FILES[ALAND].replace("ideology = conservative", "ideology = anarchist")},
                         {"name": "anarchist"}, ALAND),
    "goods_unknown": ({"history/provinces/north/1 - Capital.txt": "owner = AAA\r\ntrade_goods = gold\r\n"},
                      {"name": "gold"}, "history/provinces/north/1 - Capital.txt"),
    "terrain_unknown": ({"history/provinces/north/1 - Capital.txt": "owner = AAA\r\nterrain = lava\r\n"},
                        {"name": "lava"}, "history/provinces/north/1 - Capital.txt"),
    "pop_type_unknown": ({"history/pops/1836.1.1/North.txt": "1 = { ghosts = { culture = alander religion = sunfaith "
                                                             "size = 1 } }\r\n"}, {"name": "ghosts"}, None),
    "unit_unknown": ({"technologies/army_tech.txt": "musket_drill = {\r\n\tarea = army_doctrine\r\n"
                                                    "\tactivate_unit = tank\r\n}\r\n"}, {"name": "tank"}, None),
    "building_unknown": ({"technologies/army_tech.txt": "musket_drill = {\r\n\tactivate_building = factory\r\n}\r\n"},
                         {"name": "factory"}, None),
    "cb_unknown": ({"history/wars/New War.txt": "1840.1.1 = {\r\n\twar_goal = {\r\n"
                                                "\t\tcasus_belli = nocb\r\n\t}\r\n}\r\n"},
                   {"name": "nocb"}, "history/wars/New War.txt"),
    "province_history_duplicate": ({"history/provinces/x/1 - Otra.txt": "owner = AAA\r\n"}, {"province": "1"},
                                   "history/provinces/x/1 - Otra.txt"),
    "province_id_invalid": ({"map/definition.csv": GAME_FILES["map/definition.csv"].replace(
        ";99;98;97;x;x", "13;99;98;97;Trece;x")}, {"province": "13", "max": 13}, "map/definition.csv"),
    "land_province_without_region": ({"map/region.txt": "AAA_1 = { 1 2 3 }\r\nBBB_4 = { 4 5 6 }\r\nCCC_7 = { 7 }\r\n"},
                                     {"province": "8"}, "map/region.txt"),
    "land_province_multiple_regions": ({"map/region.txt": GAME_FILES["map/region.txt"] + "XXX_1 = { 1 }\r\n"},
                                       {"province": "1"}, "map/region.txt"),
    "sea_in_region": ({"map/region.txt": GAME_FILES["map/region.txt"] + "SEA_9 = { 9 }\r\n"},
                      {"province": "9", "region": "SEA_9"}, "map/region.txt"),
    "land_province_without_continent": ({"map/continent.txt": "west_land = {\r\n"
                                                              "\tprovinces = { 1 2 3 4 5 6 7 }\r\n}\r\n"},
                                        {"province": "8"}, "map/continent.txt"),
    "loc_copy_degraded": ({"localisation/minigame_names.csv": GAME_FILES["localisation/minigame_names.csv"].replace(
        "alandés", "aland?").replace("borlandés", "borland?s")}, {"file": "minigame_names.csv", "rows": 3},
        "localisation/minigame_names.csv"),
    "loc_key_missing": ({COUNTRIES: 'EEE = "countries/Aland.txt"\r\n' + GAME_FILES[COUNTRIES]}, {"key": "EEE_ADJ"},
                        COUNTRIES),
    "loc_untranslated": ({"localisation/00_new.csv": "AAA_conservative;Conservatives;;;;;;;;;;;;;x\r\n"},
                         {"key": "AAA_conservative", "languages": "es"}, "localisation/00_new.csv"),
    "loc_key_orphan": ({"localisation/00_new.csv": "nobody_uses_me;Text;;;;Texto;;;;;;;;;x\r\n"},
                       {"key": "nobody_uses_me"}, "localisation/00_new.csv"),
    "event_id_duplicate": ({"events/dup.txt": "country_event = { id = 1001 }\r\n"}, {"event": "1001"}, None),
    "event_id_invalid": ({"events/big.txt": "country_event = { id = 3000000000 }\r\n"}, {"event": "3000000000"},
                         "events/big.txt"),
    "event_ref_missing": ({"events/ref.txt": "country_event = { id = 5100 option = { country_event = 5555 } }\r\n"},
                          {"event": "5555"}, "events/ref.txt"),
    "decision_duplicate": ({"decisions/dup.txt": "political_decisions = { unite_lands = { } }\r\n"},
                           {"decision": "unite_lands"}, None),
    "decision_picture_missing": ({"decisions/pic.txt": "political_decisions = { no_picture = { } }\r\n"},
                                 {"decision": "no_picture", "picture": "no_picture"}, "decisions/pic.txt"),
    "cb_not_in_peace_order": ({"common/cb_types.txt": GAME_FILES["common/cb_types.txt"]
                               + "new_cb = {\r\n\tmonths = 1\r\n}\r\n"}, {"cb": "new_cb"}, "common/cb_types.txt"),
    "peace_order_unknown": ({"common/cb_types.txt": GAME_FILES["common/cb_types.txt"].replace("annex", "ghost_cb")},
                            {"cb": "ghost_cb"}, "common/cb_types.txt"),
}


class RuleCaseTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def test_each_rule_finds_its_problem(self):
        for code, (files, args, rel) in CASES.items():
            with self.subTest(code=code), build_minigame(mod=False, mod_files=files) as game:
                report = validate(game, codes={code})
                found = [p for p in report.problems if p.code == code]
                self.assertTrue(found, f"{code}: {[(p.code, dict(p.args)) for p in report.problems]}")
                matching = [p for p in found if all(p.args.get(k) == v for k, v in args.items())
                            and (rel is None or p.rel == rel)]
                self.assertTrue(matching, f"{code}: {[(str(p.rel), dict(p.args)) for p in found]}")
                problem = matching[0]
                self.assertIs(problem.severity, RULES[code].severity if problem.code not in _VARIABLE else
                              problem.severity)
                self.assertNotIn("{", problem.message("es"), problem.message("es"))
                self.assertNotIn("{", problem.message("en"))
                self.assertEqual(problem.fixes, RULES[code].fixes)

    def test_the_cases_cover_the_rule_catalogue(self):
        untested = set(discover_rules()) - set(CASES) - _COVERED_ELSEWHERE
        self.assertEqual(untested, set())


# Códigos con gravedad del propio diagnóstico (el lint del CSV da INFO o WARNING según la fila).
_VARIABLE = {"missing_end_marker"}
# Se prueban en otras clases de este archivo o en test_validate_fixes/explain.
_COVERED_ELSEWHERE = {
    # sintaxis: los mismos diagnósticos que el parser y el lint (sus propias pruebas), y estos dos aquí abajo
    "unexpected_close_brace", "missing_value", "missing_key", "unterminated_string", "invalid_key",
    "unexpected_operator", "invalid_character", "multiline_string", "control_character", "invisible_character",
    "suspicious_close_brace", "missing_end_marker", "too_few_columns", "empty_key", "key_whitespace",
    "unencodable_character", "header_row", "read_error", "check_failed",
    # descriptor y replace_path: DescriptorTests
    "descriptor_no_name", "descriptor_no_path", "descriptor_bad_path", "descriptor_other_folder",
    "descriptor_missing_folder", "descriptor_bad_user_dir", "descriptor_bad_replace_path",
    "descriptor_user_dir_empty", "replace_path_empty", "replace_path_hides_referenced",
    # heredado del minijuego: ExpectedCleanTests
    "bmp_color_unmapped",
}


class SyntaxTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def test_parser_diagnostics_keep_their_message_and_severity(self):
        files = {"events/bad.txt": "country_event = { id = 6001 }\r\n}\r\nx = \r\n"}
        with build_minigame(mod=False, mod_files=files) as game:
            report = validate(game, codes={"unexpected_close_brace", "missing_value"})
            codes = {p.code: p for p in report.problems}
            self.assertEqual(set(codes), {"unexpected_close_brace", "missing_value"})
            self.assertEqual(codes["missing_value"].line, 3)
            self.assertIn("'x'", codes["missing_value"].message("es"))
            self.assertIs(codes["missing_value"].severity, Severity.ERROR)

    def test_unsaved_documents_are_checked_instead_of_the_disk(self):
        from vic2studio.core.vfs import VPath

        with build_minigame() as game:
            overrides = {VPath.of("decisions/tst_decisions.txt"): b"political_decisions = {\r\n"}
            report = validate(game, codes={"unclosed_block"}, overrides=overrides)
            self.assertEqual([str(p.rel) for p in report.problems], ["decisions/tst_decisions.txt"])
            self.assertEqual(validate(game, codes={"unclosed_block"}).problems, ())

    def test_read_error(self):
        with build_minigame() as game:
            snap = game.snapshot()
            ctx = build_context(snap, build_index(snap, None))
            game.mod("decisions/tst_decisions.txt").unlink()
            report = Validator(ctx).validate(codes={"read_error"})
            self.assertEqual([(p.code, str(p.rel)) for p in report.problems],
                             [("read_error", "decisions/tst_decisions.txt")])

    def test_a_rule_that_raises_gives_check_failed_and_the_rest_still_runs(self):
        @rule("probe_raises", Severity.WARNING)
        def probe(ctx):
            raise RuntimeError("roto a propósito")

        self.addCleanup(registry.RULES.pop, "probe_raises", None)
        with build_minigame(mod=False) as game, self.assertLogs("vic2studio.core.validate.validator", "ERROR"):
            report = validate(game)
        failed = [p for p in report.problems if p.code == "check_failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].args["rule"], "test_validate_rules.probe")
        self.assertIn("roto a propósito", failed[0].message("es"))
        self.assertTrue(any(p.code == "peace_order_unknown" for p in report.problems), "las demás reglas corren")

    def test_files_limit_the_file_rules(self):
        from vic2studio.core.vfs import VPath

        files = {"events/a.txt": "x = \r\n", "events/b.txt": "y = \r\n"}
        with build_minigame(mod=False, mod_files=files) as game:
            snap = game.snapshot()
            ctx = build_context(snap, build_index(snap, None))
            report = Validator(ctx).validate(codes={"missing_value"}, files=[VPath.of("events/b.txt")])
            self.assertEqual([str(p.rel) for p in report.problems], ["events/b.txt"])


class DescriptorTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def check(self, descriptor: bytes, code: str, *, mod_files=None, **args):
        with build_minigame(mod=False, mod_files=mod_files) as game:
            game.descriptor.write_bytes(descriptor)
            from vic2studio.core.modfile import read_descriptor

            replace = read_descriptor(game.descriptor).replace_paths
            report = validate(game, codes={code}, replace_paths=replace)
            found = [p for p in report.problems if p.code == code and all(p.args.get(k) == v for k, v in args.items())]
            self.assertTrue(found, (code, [(p.code, dict(p.args)) for p in report.problems]))
            self.assertEqual(str(found[0].rel), "@descriptor.mod")
            self.assertNotIn("{", found[0].message("es"))
            return found[0]

    def test_fields(self):
        self.check(b'path = "mod/TestMod"\r\nuser_dir = "T"\r\n', "descriptor_no_name")
        self.check(b'name = "T"\r\nuser_dir = "T"\r\n', "descriptor_no_path")
        self.check(b'name = "T"\r\npath = "TestMod"\r\nuser_dir = "T"\r\n', "descriptor_bad_path", path="TestMod")
        self.check(b'name = "T"\r\npath = "mod/Other"\r\nuser_dir = "T"\r\n', "descriptor_other_folder",
                   folder="Other", actual="TestMod")
        self.check(b'name = "T"\r\npath = "mod/TestMod"\r\nuser_dir = "a:b"\r\n', "descriptor_bad_user_dir")
        self.check(b'name = "T"\r\npath = "mod/TestMod"\r\nuser_dir = "T"\r\nreplace_path = "../x"\r\n',
                   "descriptor_bad_replace_path")
        self.check(b'name = "T"\r\npath = "mod/TestMod"\r\n', "descriptor_user_dir_empty")

    def test_replace_paths(self):
        problem = self.check(descriptor_bytes("T", "TestMod", "T", replace_paths=["history/wars"]),
                             "replace_path_empty", replace_path="history/wars")
        self.assertIs(problem.severity, Severity.ERROR)
        oob = {"history/countries/AAA - Aland.txt": history('oob = "AAA_oob.txt"\n')}
        game_units = dict(oob)
        with build_minigame(mod=False, mod_files=game_units,
                            game_files={"history/units/AAA_oob.txt": "army = { }\r\n"}) as game:
            game.descriptor.write_bytes(descriptor_bytes("T", "TestMod", "T", replace_paths=["history/units"]))
            report = validate(game, codes={"replace_path_hides_referenced"}, replace_paths=["history/units"])
            found = [p for p in report.problems if p.code == "replace_path_hides_referenced"]
            self.assertEqual([(p.args["replace_path"], p.args["count"]) for p in found], [("history/units", 1)])

    def test_the_minigame_descriptor_is_fine(self):
        with build_minigame(mod=False) as game:
            codes = {c for c in discover_rules() if c.startswith(("descriptor_", "replace_path_"))}
            self.assertEqual(validate(game, codes=codes).problems, ())


class ExpectedCleanTests(unittest.TestCase):
    """El minijuego sin mod: solo sus heredados a propósito, que la línea base marca."""

    def setUp(self):
        isolate_appdirs(self)

    def test_only_the_planted_problems_and_all_inherited(self):
        with build_minigame(mod=False) as game:
            report = validate(game, baseline=True)
        planted = {(p.code, str(p.rel)) for p in report.problems if p.code != "missing_end_marker"}
        self.assertEqual(planted, {
            ("government_missing_in_rebel_map", "common/rebel_types.txt"),
            ("province_history_duplicate", "history/provinces/west/3 - Costa.txt"),
            ("peace_order_unknown", "common/cb_types.txt"),
            ("country_history_missing", "common/countries.txt"),
            ("government_election_without_duration", "common/governments.txt"),
            ("event_ref_missing", "events/minigame_more.txt"),
            ("loc_key_missing", "map/definition.csv"),
            ("bmp_color_unmapped", "map/provinces.bmp"),
        })
        self.assertTrue(all(p.inherited for p in report.problems))
        self.assertTrue(report.baseline_ready)
        self.assertEqual(report.visible(), [])
        color = next(p for p in report.problems if p.code == "bmp_color_unmapped")
        self.assertEqual(dict(color.args), {"color": "7 7 7", "pixels": 4})

    def test_mod_problems_are_not_inherited(self):
        with build_minigame(mod_files={AAA: history("nationalvalue = nv_tradition\n")}) as game:
            report = validate(game, baseline=True)
        own = [(p.code, dict(p.args).get("name")) for p in report.visible() if p.severity is Severity.ERROR]
        self.assertEqual(own, [("nationalvalue_unknown", "nv_tradition")])
        self.assertGreater(report.inherited_count(), 5)

    def test_unloaded_files_are_not_validated(self):
        """El juego no carga el archivo de país ni la historia de un TAG sin registrar: sus referencias no
        cuentan (las de SIL en VSM salen al registrarlo)."""
        files = {"history/countries/EEE - Esland.txt": history("nationalvalue = nv_bad\n"),
                 "common/countries/Esland.txt": GAME_FILES[ALAND].replace("Generic", "NoGC")}
        with build_minigame(mod=False, mod_files=files) as game:
            report = validate(game)
            errors = sorted(p.code for p in report.problems if p.severity is Severity.ERROR and not p.inherited
                            and p.code not in ("government_missing_in_rebel_map", "province_history_duplicate"))
            self.assertEqual(errors, ["tag_not_registered"])
            files[COUNTRIES] = 'EEE = "countries/Esland.txt"\r\n' + GAME_FILES[COUNTRIES]
        with build_minigame(mod=False, mod_files=files) as game:
            report = validate(game)
            errors = sorted(p.code for p in report.problems if p.severity is Severity.ERROR
                            and p.code not in ("government_missing_in_rebel_map", "province_history_duplicate"))
            self.assertEqual(errors, ["graphical_culture_unknown", "nationalvalue_unknown"])

    def test_validation_writes_nothing(self):
        with build_minigame() as game:
            mod_tree, game_tree = game.tree(), game.game_tree()
            validate(game, baseline=True)
            self.assertEqual(game.tree(), mod_tree)
            self.assertEqual(game.game_tree(), game_tree)

    def test_report_order_and_counts(self):
        with build_minigame(mod_files={AAA: history("nationalvalue = nv_tradition\n")}) as game:
            report = validate(game)
        order = [p.severity for p in report.problems]
        self.assertEqual(order, sorted(order, key=lambda s: {Severity.ERROR: 0, Severity.WARNING: 1,
                                                             Severity.INFO: 2}[s]))
        self.assertGreater(report.files, 50)
        self.assertFalse(report.baseline_ready)
        self.assertEqual(report.inherited_count(), 0, "sin línea base no se marca nada")


if __name__ == "__main__":
    unittest.main()
