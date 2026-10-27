"""Regresiones de la revisión adversarial del núcleo de la iteración 3: validación, línea base y explicador (§11).

Una clase por hallazgo (el número es el del informe de la revisión). Todo sobre el minijuego, salvo la última
clase, que compara ``is_degraded`` con la especificación en las filas reales de VSM (``VIC2_CORPUS``).
"""

import builtins
import os
import random
import re
import sys
import time
import unittest
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _corpus import user_mod, vanilla_root  # noqa: E402
from _layers import isolate_appdirs  # noqa: E402
from _minigame import GAME_FILES, build_minigame, build_minigame_with_deps, deps_snapshot  # noqa: E402
from vic2studio.core.clausewitz import ClausewitzDate, Severity  # noqa: E402
from vic2studio.core.index import build_index  # noqa: E402
from vic2studio.core.index import model as index_model  # noqa: E402
from vic2studio.core.validate import (BaselineCache, Problem, ValidationContext, Validator,  # noqa: E402
                                      base_snapshot, baseline_for, build_context, compute_baseline, explain,
                                      game_only_snapshot, rule)
from vic2studio.core.validate import baseline as baseline_module  # noqa: E402
from vic2studio.core.validate import context as context_module  # noqa: E402
from vic2studio.core.validate import registry  # noqa: E402
from vic2studio.core.validate.model import LAYER_GAME, LAYER_MOD, VERDICT_LOSES, VERDICT_WINS  # noqa: E402
from vic2studio.core.validate.registry import SCOPE_FILE  # noqa: E402
from vic2studio.core.validate.rules import localisation as loc_rules  # noqa: E402
from vic2studio.core.validate.rules import provinces as province_rules  # noqa: E402
from vic2studio.core.vfs import LayerKind, VPath  # noqa: E402
from vic2studio.core.vfs.paths import DESCRIPTOR_REL  # noqa: E402

explain_module = sys.modules["vic2studio.core.validate.explain"]
NAMES = "localisation/minigame_names.csv"
# «alandés» → «aland?» en AAA_ADJ y en alander; «borlandés» → «borland?s» en BBB_ADJ: 3 filas degradadas.
DEGRADED_NAMES = GAME_FILES[NAMES].replace("alandés", "aland?").replace("borlandés", "borland?s")
AAA = "history/countries/AAA - Aland.txt"


def reference_is_degraded(mod_line: str, game_line: str) -> bool:
    """La especificación: la expresión regular de antes (correcta, pero compilaba una por fila y retrocedía)."""
    if mod_line == game_line or "?" not in mod_line:
        return False
    gap = "(?:\\?|[^\\x00-\\x7f][\\s\\S]{0,2})"
    return re.fullmatch(gap.join(re.escape(part) for part in mod_line.split("?")), game_line) is not None


def context(snap, *, overrides=None, **kwargs):
    return build_context(snap, build_index(snap, None, overrides), overrides, **kwargs)


def problems(snap, codes, *, baseline=None, **kwargs):
    return list(Validator(context(snap, **kwargs), baseline=baseline).validate(codes=codes).problems)


# --- 1: is_degraded lineal ------------------------------------------------------------------------------------


class IsDegradedTests(unittest.TestCase):
    def test_same_answer_as_the_specification(self):
        rnd = random.Random(1836)
        alphabet = "ab;?éü x"
        for _ in range(20000):
            game_line = "".join(rnd.choice(alphabet) for _ in range(rnd.randrange(0, 10)))
            mod_line = "".join(rnd.choice(alphabet) for _ in range(rnd.randrange(0, 10)))
            self.assertEqual(loc_rules.is_degraded(mod_line, game_line), reference_is_degraded(mod_line, game_line),
                             (mod_line, game_line))
        cases = [("KEY;Efficacit?fiscale;x", "KEY;Efficacité fiscale;x", True),     # «?» por letra y 1 más
                 ("KEY;Capacit?;x", "KEY;Capacité;x", True),
                 ("KEY;Caf?;x", "KEY;Café;x", True),
                 ("KEY;Caf?;x", "KEY;Cafe;x", False),                                  # «e» es ASCII
                 ("KEY;a?;x", "KEY;aé123;x", False),                                   # más de 2 caracteres detrás
                 ("KEY;same;x", "KEY;same;x", False), ("KEY;?;x", "KEY;?;x", False)]
        for mod_line, game_line, expected in cases:
            self.assertIs(loc_rules.is_degraded(mod_line, game_line), expected, mod_line)
            self.assertIs(reference_is_degraded(mod_line, game_line), expected, mod_line)

    def test_a_run_of_question_marks_is_linear(self):
        """28 «?» seguidos tardaban ~1 s y cada 2 más, ×1,8 (retroceso exponencial de la expresión regular)."""
        start = time.perf_counter()
        self.assertTrue(loc_rules.is_degraded("KEY;" + "?" * 32 + ";x", "KEY;" + "é" * 32 + ";x"))
        self.assertFalse(loc_rules.is_degraded("KEY;" + "?" * 32 + ";x", "KEY;" + "é" * 32 + ";y"))
        self.assertTrue(loc_rules.is_degraded("KEY;" + "?" * 300 + ";x", "KEY;" + "é" * 300 + ";x"))
        self.assertLess(time.perf_counter() - start, 0.5)


# --- 10 y args de loc_copy_degraded -----------------------------------------------------------------------------


class DegradedCopyTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def test_only_keys_whose_effective_row_is_degraded_count(self):
        """Un CSV que carga antes con la fila buena de AAA_ADJ: esa clave ya no se ve rota en partida."""
        fix = "AAA_ADJ;Alandish;Alandish;Alandish;;alandés" + ";" * 9 + "x\r\n"
        files = {NAMES: DEGRADED_NAMES, "localisation/00_fix.csv": fix}
        with build_minigame(mod=False, mod_files=files) as game:
            [problem] = problems(game.snapshot(), {"loc_copy_degraded"})
            game_rows = [row for row in GAME_FILES[NAMES].split("\r\n")]
        self.assertEqual(problem.args["rows"], 2, "AAA_ADJ la gana 00_fix.csv")
        self.assertEqual(problem.args["lines"], 3, "las filas degradadas del archivo: las que cambia el arreglo")
        self.assertEqual(problem.args["key"], "BBB_ADJ", "la primera clave efectiva degradada")
        self.assertTrue(game_rows[problem.args["game_line"] - 1].startswith("BBB_ADJ;"))
        self.assertNotIn("game_line", dict(problem.fingerprint()[4]), "una posición no cuenta en la huella")

    def test_without_a_competing_file_every_degraded_key_counts(self):
        with build_minigame(mod=False, mod_files={NAMES: DEGRADED_NAMES}) as game:
            [problem] = problems(game.snapshot(), {"loc_copy_degraded"})
        self.assertEqual((problem.args["rows"], problem.args["lines"], problem.args["key"]), (3, 3, "AAA_ADJ"))

    def test_the_explainer_uses_the_example_row_of_the_args(self):
        """El explicador corre en el hilo de la interfaz: con ``key`` y ``game_line`` no vuelve a comparar el
        archivo entero (1,8 s en VSM)."""
        with build_minigame(mod=False, mod_files={NAMES: DEGRADED_NAMES}) as game:
            ctx = context(game.snapshot())
            [problem] = Validator(ctx).validate(codes={"loc_copy_degraded"}).problems
            with mock.patch.object(loc_rules, "degraded_rows", side_effect=AssertionError("recalcula")):
                explanation = explain(problem, ctx)
            self.assertEqual([(s.layer, s.verdict) for s in explanation.steps],
                             [(LAYER_MOD, VERDICT_WINS), (LAYER_GAME, VERDICT_LOSES)])
            self.assertEqual((explanation.args["key"], explanation.args["example"], explanation.args["original"]),
                             ("AAA_ADJ", "aland?", "alandés"))
            self.assertEqual(explanation.steps[1].line, problem.args["game_line"])
            # Un problema sin esos args (de un informe anterior) se explica igual, recalculando.
            bare = Problem(problem.code, problem.severity, problem.rel, problem.line,
                           args=MappingProxyType({"file": "minigame_names.csv", "rows": 3}),
                           fixes=problem.fixes)
            self.assertEqual(explain(bare, ctx).args["example"], "aland?")

    def test_the_explainer_does_not_decode_binary_files_as_text(self):
        """El de ``bmp_color_unmapped`` decodificaba el BMP entero para no mostrar ninguna línea (0,5 s en VSM)."""
        real = explain_module.decode_bytes

        def no_bmp(data, *args, **kwargs):
            if data[:2] == b"BM":
                raise AssertionError("decodifica el BMP como texto")
            return real(data, *args, **kwargs)

        with build_minigame(mod=False) as game:
            ctx = context(game.snapshot())
            [problem] = Validator(ctx).validate(codes={"bmp_color_unmapped"}).problems
            with mock.patch.object(explain_module, "decode_bytes", side_effect=no_bmp):
                explanation = explain(problem, ctx)
        self.assertEqual([(s.layer, str(s.rel), s.verdict) for s in explanation.steps],
                         [(LAYER_GAME, "map/provinces.bmp", VERDICT_WINS)])


# --- 3, 8, 9 y 14: línea base -----------------------------------------------------------------------------------

BIG_EVENTS = "events/big.txt"
# Un evento roto de la dependencia: bloque sin cerrar, claves de localización que faltan y un evento que no existe.
BROKEN_EVENT = "country_event = {\r\n\tid = 777001\r\n\ttitle = X\r\n\toption = { name = Y country_event = 999999 }\r\n"


class DependencyBaselineTests(unittest.TestCase):
    """Un submod vacío sobre un mod grande veía como propios los fallos de su dependencia."""

    def setUp(self):
        isolate_appdirs(self)
        self.game = build_minigame_with_deps({"BigMod": {BIG_EVENTS: BROKEN_EVENT}})
        self.addCleanup(self.game.cleanup)

    def test_an_empty_submod_inherits_the_problems_of_its_dependency(self):
        snap = deps_snapshot(self.game)
        baseline = baseline_for(snap)
        report = Validator(context(snap), baseline=baseline).validate()
        from_dependency = [p for p in report.problems if str(p.rel) == BIG_EVENTS]
        self.assertTrue(from_dependency)
        self.assertEqual([(p.code, dict(p.args)) for p in report.visible() if str(p.rel) == BIG_EVENTS], [])
        self.assertEqual(report.visible(), [], "el submod está vacío: nada es suyo")

    def test_the_mod_own_problems_are_still_its_own(self):
        broken = {"events/mine.txt": "country_event = {\r\n\tid = 777002\r\n"}
        with build_minigame_with_deps({"BigMod": {BIG_EVENTS: BROKEN_EVENT}}, mod_files=broken) as game:
            snap = deps_snapshot(game)
            report = Validator(context(snap), baseline=baseline_for(snap)).validate(codes={"unclosed_block"})
        self.assertEqual(sorted((str(p.rel), p.inherited) for p in report.problems),
                         [(BIG_EVENTS, True), ("events/mine.txt", False)])

    def test_base_snapshot_keeps_the_dependencies_and_drops_the_mod(self):
        snap = deps_snapshot(self.game, replace_paths=["history/countries"])
        base = base_snapshot(snap)
        self.assertEqual([layer.kind for layer in base.layers], [LayerKind.DEPENDENCY, LayerKind.GAME])
        self.assertIs(base.resolve(BIG_EVENTS).layer.kind, LayerKind.DEPENDENCY)
        self.assertIsNone(base.resolve(DESCRIPTOR_REL))
        self.assertEqual(base.hidden, frozenset(), "el replace_path del mod no es de la base")
        self.assertEqual(base_snapshot(base), base, "idempotente")
        game_only = game_only_snapshot(snap)
        self.assertEqual(base_snapshot(game_only).layers, game_only.layers)
        ctx = build_context(snap, build_index(snap, None), game_only=True)
        self.assertEqual([layer.kind for layer in ctx.snapshot.layers], [LayerKind.DEPENDENCY, LayerKind.GAME])
        self.assertTrue(ctx.index.exists("event", "777001"), "el índice de la base lleva la dependencia")

    def test_the_cache_is_keyed_to_the_dependencies(self):
        snap = deps_snapshot(self.game)
        cache = BaselineCache()
        baseline = baseline_for(snap, cache=cache)
        self.assertEqual(cache.load(snap), baseline)
        self.assertIsNone(cache.load(self.game.snapshot()), "sin la dependencia es otra línea base")
        self.assertNotEqual(cache.path(snap), cache.path(self.game.snapshot()))
        dep_file = self.game.layers.dependencies[0] / BIG_EVENTS
        stat = dep_file.stat()
        os.utime(dep_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
        self.assertIsNone(cache.load(deps_snapshot(self.game)), "un archivo de la dependencia cambió")


class BaselineDateTests(unittest.TestCase):
    """Un problema de vanilla que solo existe a la fecha de trabajo salía como propio de un mod vacío."""

    DATE = ClausewitzDate(1861, 1, 1)

    def setUp(self):
        isolate_appdirs(self)
        history = GAME_FILES[AAA] + "1861.1.1 = {\r\n\tgovernment = council\r\n\truling_party = AAA_conservative\r\n}\r\n"
        self.game = build_minigame(mod=False, game_files={AAA: history})
        self.addCleanup(self.game.cleanup)

    def test_the_baseline_looks_at_the_working_date(self):
        snap = self.game.snapshot()
        codes = {"ruling_party_ideology_not_allowed"}
        [found] = problems(snap, codes, date=self.DATE)
        self.assertFalse(problems(snap, codes), "a 1836.1.1 no ocurre")
        self.assertNotIn(found.fingerprint(), baseline_for(snap), "una línea base sin fecha no lo ve")
        [dated] = problems(snap, codes, date=self.DATE, baseline=baseline_for(snap, date=self.DATE))
        self.assertTrue(dated.inherited)
        base = base_snapshot(snap)
        ctx = build_context(base, build_index(base, None), game_only=True)
        self.assertIn(found.fingerprint(), compute_baseline(ctx, date=self.DATE))

    def test_the_date_is_part_of_the_cache_key(self):
        snap = self.game.snapshot()
        cache = BaselineCache()
        undated = baseline_for(snap, cache=cache)
        self.assertIsNone(cache.load(snap, date=self.DATE))
        dated = baseline_for(snap, cache=cache, date=self.DATE)
        self.assertNotEqual(dated, undated)
        self.assertEqual((cache.load(snap), cache.load(snap, date=self.DATE)), (undated, dated))
        self.assertNotEqual(cache.path(snap), cache.path(snap, date=self.DATE))


class CheckFailedTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def test_a_failing_rule_is_never_inherited(self):
        @rule("probe_always_raises", Severity.WARNING)
        def probe(ctx):
            raise KeyError("annex")

        self.addCleanup(registry.RULES.pop, "probe_always_raises", None)
        with build_minigame(mod=False) as game, self.assertLogs("vic2studio.core.validate.validator", "ERROR"):
            snap = game.snapshot()
            baseline = baseline_for(snap)
            report = Validator(context(snap), baseline=baseline).validate(codes={"probe_always_raises"})
            [failed] = report.problems
            self.assertNotIn(failed.fingerprint(), baseline, "la línea base no guarda fallos de reglas")
            report = Validator(context(snap), baseline=baseline | {failed.fingerprint()}).validate(
                codes={"probe_always_raises"})
        [failed] = report.problems
        self.assertEqual(failed.code, "check_failed")
        self.assertFalse(failed.inherited)
        self.assertEqual(report.visible(), [failed])


class RulesSignatureTests(unittest.TestCase):
    def test_extractor_versions_and_the_index_format_are_part_of_it(self):
        from dataclasses import replace

        before = baseline_module.rules_signature()
        index_model.discover_extractors()
        position = next(i for i, s in enumerate(index_model.EXTRACTORS) if s.name == "countries.tag_registry")
        original = index_model.EXTRACTORS[position]
        index_model.EXTRACTORS[position] = replace(original, version=original.version + 1)
        try:
            self.assertNotEqual(baseline_module.rules_signature(), before)
        finally:
            index_model.EXTRACTORS[position] = original
        self.assertEqual(baseline_module.rules_signature(), before)
        with mock.patch.object(index_model, "INDEX_FORMAT", index_model.INDEX_FORMAT + 1):
            self.assertNotEqual(baseline_module.rules_signature(), before)


# --- 5, 6, 7 y el contexto -----------------------------------------------------------------------------------------


class ContextTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def test_languages_reach_the_context(self):
        rows = "new_key;English;;;;Español;;;;;;;;x\r\n"
        with build_minigame(mod=False, mod_files={"localisation/00_new.csv": rows}) as game:
            snap = game.snapshot()
            self.assertEqual(context(snap).languages, ("en", "es"), "por defecto, como antes")
            ctx = context(snap, languages=["en", "fr"])
            self.assertEqual(ctx.languages, ("en", "fr"))
            [problem] = Validator(ctx).validate(codes={"loc_untranslated"}).problems
        self.assertEqual((problem.args["key"], problem.args["languages"]), ("new_key", "fr"))

    def test_validate_does_not_mutate_the_context_it_receives(self):
        seen = []

        @rule("probe_file_scope", Severity.INFO, scope=SCOPE_FILE)
        def probe(ctx):
            seen.append((ctx.files, validator.ctx.files, validator.ctx.cancelled))
            return []

        self.addCleanup(registry.RULES.pop, "probe_file_scope", None)
        with build_minigame(mod=False) as game:
            validator = Validator(context(game.snapshot()))
            stop = lambda: False  # noqa: E731
            validator.validate(codes={"probe_file_scope"}, files=[VPath.of("events/x.txt")], cancelled=stop)
        self.assertEqual(seen, [({"EVENTS/X.TXT"}, None, None)])
        self.assertIsNone(validator.ctx.files)

    def test_a_bad_map_file_name_in_default_map(self):
        """``provinces = "../../etc"`` en default.map tumbaba ``bmp_color_unmapped`` (``check_failed``)."""
        default_map = GAME_FILES["map/default.map"].replace('provinces = "provinces.bmp"', 'provinces = "../../etc"')
        with build_minigame(mod=False, mod_files={"map/default.map": default_map}) as game:
            ctx = context(game.snapshot())
            self.assertEqual(ctx.rules.map_files["provinces"], "provinces.bmp", "el de vanilla")
            report = Validator(ctx).validate(codes={"bmp_color_unmapped"})
            hand_made = ValidationContext(ctx.snapshot, ctx.index, None,
                                          SimpleNamespace(map_files={"provinces": "../x"}))
            self.assertEqual(len(province_rules.unmapped_colors(hand_made)), 1, "la regla tampoco lanza")
        self.assertEqual([(p.code, p.args.get("color")) for p in report.problems], [("bmp_color_unmapped", "7 7 7")])

    def test_path_args_do_not_care_about_case_in_the_fingerprint(self):
        def problem(other):
            return Problem("province_history_duplicate", Severity.ERROR, VPath.of("history/provinces/x/1 - A.txt"),
                           args=MappingProxyType({"province": "1", "other": other}))

        self.assertEqual(problem("history/provinces/Asia/1396 - Api.txt").fingerprint(),
                         problem("history/provinces/asia/1396 - Api.txt").fingerprint())
        self.assertNotEqual(problem("history/provinces/asia/1396 - Api.txt").fingerprint(),
                            problem("history/provinces/asia/1397 - Api.txt").fingerprint())

    def test_a_copy_with_other_case_keeps_a_vanilla_duplicate_inherited(self):
        copy = {"history/provinces/East/3 - Costa.txt": GAME_FILES["history/provinces/east/3 - Costa.txt"]}
        with build_minigame(mod=False, mod_files=copy) as game:
            snap = game.snapshot()
            [found] = problems(snap, {"province_history_duplicate"}, baseline=baseline_for(snap))
        self.assertEqual(found.args["other"], "history/provinces/East/3 - Costa.txt")
        self.assertTrue(found.inherited)


# --- 11: tag_not_registered --------------------------------------------------------------------------------------


class TagUsesTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def test_cultures_and_flags_are_uses(self):
        cultures = (GAME_FILES["common/cultures.txt"]
                    .replace("\tunit = NorthGC\r\n", "\tunit = NorthGC\r\n\tunion = ZZZ\r\n")
                    .replace("\t\tprimary = D01\r\n", "\t\tprimary = QQ1\r\n"))
        files = {"common/cultures.txt": cultures, "gfx/flags/FFF_communist.tga": b"\x00\x00\x02flag",
                 "gfx/flags/REB.tga": b"\x00\x00\x02flag", "gfx/flags/notatag.tga": b"\x00\x00\x02flag",
                 "gfx/flags/GGG_unknown.tga": b"\x00\x00\x02flag"}
        with build_minigame(mod=False, mod_files=files) as game:
            ctx = context(game.snapshot())
            found = Validator(ctx).validate(codes={"tag_not_registered"}).problems
            by_tag = {p.args["tag"]: p for p in found}
            self.assertEqual(sorted((tag, str(p.rel), p.line is None) for tag, p in by_tag.items()), [
                ("FFF", "gfx/flags/FFF_communist.tga", True),
                ("QQ1", "common/cultures.txt", False),
                ("ZZZ", "common/cultures.txt", False)])
            steps = [(str(s.rel), s.verdict) for s in explain(by_tag["FFF"], ctx).steps]
            self.assertIn(("gfx/flags/FFF_communist.tga", "not_loaded"), steps)
            steps = [(str(s.rel), s.excerpt) for s in explain(by_tag["ZZZ"], ctx).steps]
            self.assertIn(("common/cultures.txt", "union = ZZZ"), steps)

    def test_registered_tags_and_their_flags_are_fine(self):
        with build_minigame(mod=False) as game:
            self.assertEqual(problems(game.snapshot(), {"tag_not_registered"}), [], "gfx/flags/AAA.tga: AAA existe")


# --- 12: mod_shadow_identical -------------------------------------------------------------------------------------

CB = "common/cb_types.txt"


class ShadowIdenticalTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)
        context_module.forget_identical()
        self.addCleanup(context_module.forget_identical)

    def test_compared_with_what_would_win_without_the_mod(self):
        """Con una dependencia en medio que trae otra versión, la copia igual a la del juego sí hace falta."""
        other = GAME_FILES[CB].replace("months = 12", "months = 24")
        with build_minigame_with_deps({"Dep": {CB: other}}, mod_files={CB: GAME_FILES[CB]}) as game:
            self.assertEqual(problems(deps_snapshot(game), {"mod_shadow_identical"}), [])
        with build_minigame_with_deps({"Dep": {CB: other}}, mod_files={CB: other}) as game:
            [problem] = problems(deps_snapshot(game), {"mod_shadow_identical"})
            self.assertEqual(str(problem.rel), CB, "igual a la de la dependencia: borrarla no cambia nada")

    def test_the_comparison_is_remembered_between_validations(self):
        """VSM releía 942 MB en cada validación."""
        opened = []
        real_open = builtins.open

        def counting_open(path, *args, **kwargs):
            opened.append(str(path))
            return real_open(path, *args, **kwargs)

        with build_minigame(mod=False, mod_copies=[CB]) as game, \
                mock.patch.object(context_module, "open", side_effect=counting_open, create=True):
            for _ in range(2):
                self.assertEqual(len(problems(game.snapshot(), {"mod_shadow_identical"})), 1)
            self.assertEqual(len(opened), 2, "solo la primera validación abre las dos copias")
            path = game.mod(CB)
            stat = path.stat()
            path.write_bytes(path.read_bytes().replace(b"months = 12", b"months = 99"))
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
            self.assertEqual(problems(game.snapshot(), {"mod_shadow_identical"}), [], "otra huella: se compara")


# --- 1 con el corpus: las filas reales ---------------------------------------------------------------------------


def _full_vsm():
    mod = user_mod()
    return mod if mod is not None and (mod / "localisation" / "text.csv").is_file() else None


@unittest.skipUnless(vanilla_root() and _full_vsm(), "requiere el corpus completo (VIC2_CORPUS)")
class VsmDegradedRowsTests(unittest.TestCase):
    def test_same_rows_as_the_specification(self):
        mod_data = (_full_vsm() / "localisation" / "text.csv").read_bytes()
        game_data = (vanilla_root() / "localisation" / "text.csv").read_bytes()
        rows = loc_rules.degraded_rows(mod_data, game_data)
        self.assertEqual((len(rows), sum(1 for _, _, first in rows if first)), (3438, 3430))
        game_rows = {}
        for row in loc_rules._rows(game_data).rows:
            if row.key:
                game_rows.setdefault(row.key, row.raw)
        pairs = [(row.raw, game_rows[row.key]) for row in loc_rules._rows(mod_data).rows if row.key in game_rows]
        self.assertEqual(len(pairs), 15234)
        self.assertEqual([loc_rules.is_degraded(a, b) for a, b in pairs],
                         [reference_is_degraded(a, b) for a, b in pairs])


if __name__ == "__main__":
    unittest.main()
