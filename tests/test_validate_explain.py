"""Explicador de conflicto (wizard §11.1): capas en orden de carga, su línea real, su veredicto y la frase final."""

import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import isolate_appdirs  # noqa: E402
from _minigame import GAME_FILES, build_minigame  # noqa: E402
from test_validate_rules import CASES  # noqa: E402
from vic2studio.core import texts  # noqa: E402
from vic2studio.core.index import build_index  # noqa: E402
from vic2studio.core.validate import Validator, build_context, discover_rules, explain  # noqa: E402
explain_module = importlib.import_module("vic2studio.core.validate.explain")
from vic2studio.core.validate.model import (LAYER_GAME, LAYER_MOD, LAYER_REPLACE_PATH, LAYER_UNSAVED,  # noqa: E402
                                            VERDICT_HIDDEN, VERDICT_LOSES, VERDICT_MISSING, VERDICT_NOT_LOADED,
                                            VERDICT_WINS)
from vic2studio.core.vfs import VPath  # noqa: E402

ESLAND = {"history/countries/EEE - Esland.txt": "capital = 1\r\nprimary_culture = alander\r\n",
          "common/countries/Esland.txt": GAME_FILES["common/countries/Aland.txt"],
          "gfx/flags/EEE.tga": b"\x00\x00\x02flag",
          "history/provinces/north/1 - Capital.txt": "owner = AAA\r\nadd_core = EEE\r\n"}


def context(game, *, overrides=None, replace_paths=()):
    snap = game.snapshot(replace_paths=replace_paths)
    return build_context(snap, build_index(snap, None, overrides), overrides)


def found(ctx, code):
    return [p for p in Validator(ctx).validate(codes={code}).problems if p.code == code]


def rendered(explanation, lang):
    parts = [explanation.title(lang), explanation.outcome(lang)]
    parts += [s.layer_text(lang) for s in explanation.steps] + [s.verdict_text(lang) for s in explanation.steps]
    return parts


class EveryCodeTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def test_every_code_has_title_outcome_and_steps(self):
        es, en = texts.load_texts("es"), texts.load_texts("en")
        for code in discover_rules():
            with self.subTest(code=code):
                self.assertIn(f"explain.title.{code}", es)
                self.assertIn(f"explain.outcome.{code}", en)
        for code, (files, _, _) in CASES.items():
            with self.subTest(case=code), build_minigame(mod=False, mod_files=files) as game:
                ctx = context(game)
                problem = found(ctx, code)[0]
                explanation = explain(problem, ctx)
                self.assertTrue(explanation.steps, code)
                self.assertEqual(explanation.fixes, problem.fixes)
                for lang in ("es", "en"):
                    for text in rendered(explanation, lang):
                        self.assertNotIn("{", text, f"{code}: {text}")
                        self.assertFalse(text.startswith(("explain.", "issue.")), text)

    def test_texts_of_layers_and_verdicts(self):
        es = texts.load_texts("es")
        for layer in (LAYER_GAME, LAYER_MOD, LAYER_REPLACE_PATH, LAYER_UNSAVED, "dependency"):
            self.assertIn(f"explain.layer.{layer}", es)
        for verdict in (VERDICT_WINS, VERDICT_LOSES, VERDICT_HIDDEN, VERDICT_NOT_LOADED, VERDICT_MISSING):
            self.assertIn(f"explain.verdict.{verdict}", es)


class SpecificTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def test_tag_not_registered_shows_every_layer_against_countries_txt(self):
        with build_minigame(mod=False, mod_files=ESLAND) as game:
            ctx = context(game)
            [problem] = found(ctx, "tag_not_registered")
            explanation = explain(problem, ctx)
        steps = [(s.layer, str(s.rel), s.verdict) for s in explanation.steps]
        self.assertEqual(steps, [
            (LAYER_GAME, "common/countries.txt", VERDICT_MISSING),
            (LAYER_MOD, "common/countries/Esland.txt", VERDICT_NOT_LOADED),
            (LAYER_MOD, "history/countries/EEE - Esland.txt", VERDICT_NOT_LOADED),
            (LAYER_MOD, "gfx/flags/EEE.tga", VERDICT_NOT_LOADED),
            (LAYER_MOD, "history/provinces/north/1 - Capital.txt", VERDICT_MISSING)])
        self.assertEqual(explanation.steps[0].excerpt, "dynamic_tags = yes", "la línea real de countries.txt")
        self.assertEqual(explanation.steps[-1].excerpt, "add_core = EEE")
        self.assertIn("(1)", explanation.outcome("es"))
        self.assertEqual(explanation.fixes, ("register_tag",))

    def test_loc_copy_degraded_shows_the_mod_file_replacing_the_game_file(self):
        rel = "localisation/minigame_names.csv"
        degraded = GAME_FILES[rel].replace("borlandés", "borland?s")
        with build_minigame(mod=False, mod_files={rel: degraded}) as game:
            ctx = context(game)
            [problem] = found(ctx, "loc_copy_degraded")
            explanation = explain(problem, ctx)
        self.assertEqual([(s.layer, s.verdict) for s in explanation.steps],
                         [(LAYER_MOD, VERDICT_WINS), (LAYER_GAME, VERDICT_LOSES)])
        self.assertTrue(explanation.steps[0].excerpt.startswith("BBB_ADJ;Borlandish;"))
        self.assertIn("borland?s", explanation.steps[0].excerpt)
        self.assertIn("borlandés", explanation.steps[1].excerpt)
        self.assertEqual(explanation.outcome("es"), "En partida verás «borland?s» en español en lugar de «borlandés», "
                                                    "porque tu minigame_names.csv sustituye entero al del juego.")
        self.assertIn("in Spanish", explanation.outcome("en"))

    def test_duplicates_list_every_definition(self):
        with build_minigame(mod=False, mod_files={"events/dup.txt": "country_event = { id = 1001 }\r\n"}) as game:
            ctx = context(game)
            [problem] = found(ctx, "event_id_duplicate")
            explanation = explain(problem, ctx)
        self.assertEqual([(str(s.rel), s.verdict) for s in explanation.steps],
                         [("events/dup.txt", VERDICT_WINS), ("events/minigame_events.txt", VERDICT_LOSES)])

    def test_shadowed_file_layers_and_replace_path(self):
        with build_minigame(mod=False, mod_copies=["common/cb_types.txt"]) as game:
            ctx = context(game)
            [problem] = found(ctx, "mod_shadow_identical")
            steps = [(s.layer, s.verdict) for s in explain(problem, ctx).steps]
            self.assertEqual(steps, [(LAYER_MOD, VERDICT_WINS), (LAYER_GAME, VERDICT_LOSES)])
        with build_minigame(mod=False, mod_files={"history/provinces/north/1 - Capital.txt": "owner = AAA\r\n"}) \
                as game:
            ctx = context(game, replace_paths=["history/provinces"])
            steps = explain_module.layer_steps(ctx, VPath.of("history/provinces/north/1 - Capital.txt"), 1)
            self.assertEqual([(s.layer, s.verdict) for s in steps],
                             [(LAYER_MOD, VERDICT_WINS), (LAYER_REPLACE_PATH, VERDICT_HIDDEN)])

    def test_unsaved_document_is_the_first_layer(self):
        rel = VPath.of("decisions/tst_decisions.txt")
        with build_minigame() as game:
            ctx = context(game, overrides={rel: b"political_decisions = {\r\n"})
            [problem] = found(ctx, "unclosed_block")
            steps = explain(problem, ctx).steps
        self.assertEqual([(s.layer, s.verdict) for s in steps], [(LAYER_UNSAVED, VERDICT_WINS),
                                                                 (LAYER_MOD, VERDICT_LOSES)])
        self.assertEqual(steps[0].excerpt, "political_decisions = {")

    def test_inherited_problems_are_explained_too(self):
        from vic2studio.core.validate import compute_baseline, game_only_snapshot

        with build_minigame(mod=False) as game:
            snap = game.snapshot()
            gsnap = game_only_snapshot(snap)
            baseline = compute_baseline(build_context(gsnap, build_index(gsnap, None), game_only=True))
            ctx = context(game)
            [problem] = [p for p in Validator(ctx, baseline=baseline).validate(codes={"peace_order_unknown"}).problems]
            self.assertTrue(problem.inherited)
            explanation = explain(problem, ctx)
        self.assertEqual(explanation.steps[0].excerpt, "annex")
        self.assertIn("annex", explanation.outcome("es"))

    def test_a_failing_explainer_falls_back_to_the_generic_one(self):
        with build_minigame(mod=False, mod_files=ESLAND) as game:
            ctx = context(game)
            [problem] = found(ctx, "tag_not_registered")
            with mock.patch.dict(explain_module.EXPLAINERS, {"tag_not_registered": mock.Mock(side_effect=KeyError)}):
                with self.assertLogs("vic2studio.core.validate.explain", "ERROR"):
                    explanation = explain(problem, ctx)
        self.assertEqual(explanation.title_key, "explain.title.tag_not_registered")
        self.assertEqual([s.verdict for s in explanation.steps], [VERDICT_WINS])


if __name__ == "__main__":
    unittest.main()
