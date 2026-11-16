"""Núcleo del guion de la iteración 7 (wizard §12, §22): catálogo, árbol, frases, MTTH, ids y modo texto.

Las pruebas corren sobre el minijuego de guion inventado (``_minigame.build_script_minigame``) con un
``Project`` real, su índice y sus textos. Las de corpus (criterios 1, 2, 4 y 5 sobre vanilla y el mod del
usuario) se saltan sin ``VIC2_GAME``; nunca escriben en el juego ni en el mod real (se abre una copia).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _corpus import copy_user_mod, user_mod, vanilla_root  # noqa: E402
from _layers import isolate_appdirs  # noqa: E402
from _minigame import SCRIPT_BROKEN_DECISIONS, SCRIPT_BROKEN_IDS, build_script_minigame  # noqa: E402

from vic2studio.core.clausewitz import Block, parse, to_source  # noqa: E402
from vic2studio.core.encoding import decode_bytes  # noqa: E402
from vic2studio.core.index.builder import build_index  # noqa: E402
from vic2studio.core.locsync import LocSync  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.schema import Entities  # noqa: E402
from vic2studio.core.schema.record import InvalidIdentError  # noqa: E402
from vic2studio.core.schema.record import RecordRef  # noqa: E402
from vic2studio.core.script.catalog import ScriptCatalog, entry_problems  # noqa: E402
from vic2studio.core.script.idalloc import ID_NOT_A_NUMBER, ID_OUT_OF_RANGE, ID_TAKEN  # noqa: E402
from vic2studio.core.script.mtth import (  # noqa: E402
    AI_CHANCE_KEY,
    AI_WILL_DO_KEY,
    effective,
    format_duration,
    read_weights,
    to_months,
)
from vic2studio.core.script.phrases import phrase, phrase_lines  # noqa: E402
from vic2studio.core.script.scopes import Scope, ScriptKind  # noqa: E402
from vic2studio.core.script.textonly import text_only_of  # noqa: E402
from vic2studio.core.script.tree import SCOPE_MISMATCH, NodeForm, ScriptTree  # noqa: E402
from vic2studio.core.vfs import VPath  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import catalog_census  # noqa: E402


def _text(project: Project, rel: str) -> str:
    handle = project.ws.peek(VPath.of(rel))
    if handle is None:
        handle = project.ws.open(VPath.of(rel))
    return codec_for(handle.kind).snapshot(handle.model).decode("cp1252")


class ScriptProjectCase(unittest.TestCase):
    """El minijuego de guion abierto con ``Project``, su índice, sus textos y ``Entities``."""

    broken = True

    def setUp(self):
        isolate_appdirs(self)
        self.game = build_script_minigame(broken=self.broken)
        self.addCleanup(self.game.cleanup)
        self.project = Project.open(self.game.game_root, self.game.mod_root)
        self.addCleanup(self.project.close)
        self.index = build_index(self.project.vfs.snapshot(), None, {})
        self.loc = LocSync(self.project.ws, self.project.vfs, prefix=self.project.settings.prefix)
        self.entities = Entities(self.project.ws, self.index, self.loc)

    def event(self, ident) -> object:
        return self.entities.open(RecordRef("event", str(ident)))

    def decision(self, ident: str) -> object:
        return self.entities.open(RecordRef("decision", ident))


class CatalogTests(unittest.TestCase):
    def test_every_entry_of_the_shipped_catalog_is_valid(self):
        catalog = ScriptCatalog.load()
        definitions = catalog.definitions()
        self.assertGreater(len(definitions), 150)
        for definition in definitions:
            self.assertTrue(definition.label.get("es") and definition.label.get("en"), definition.name)

    def test_entry_problems_reports_a_bad_entry(self):
        self.assertTrue(entry_problems({"name": "x", "role": "condition"}))       # sin textos ni ámbitos
        self.assertTrue(entry_problems("no es un diccionario"))

    def test_suggestions_search_both_languages_and_respect_the_scope(self):
        catalog = ScriptCatalog.load()
        for lang, text in (("es", "gobierno"), ("en", "government")):
            names = [d.name for d in catalog.suggestions(ScriptKind.TRIGGER, Scope.COUNTRY, text, lang)]
            self.assertIn("government", names, lang)
        province = [d.name for d in catalog.suggestions(ScriptKind.TRIGGER, Scope.PROVINCE, "", "es")]
        self.assertNotIn("government", province, "una condición de país no se ofrece en una provincia")
        effects = [d.name for d in catalog.suggestions(ScriptKind.EFFECT, Scope.COUNTRY, "prestig", "en")]
        self.assertIn("prestige", effects)

    def test_family_keys_come_from_the_symbols(self):
        catalog = ScriptCatalog.load()
        definition = catalog.lookup("AAA", ScriptKind.EFFECT, Scope.COUNTRY, block=True)
        self.assertIsNotNone(definition, "un TAG como ámbito se reconoce por patrón")
        self.assertTrue(definition.family)


class TreeTests(ScriptProjectCase):
    def test_tree_forms_and_raw_nodes_are_kept(self):
        tree = self.event(2001).script("trigger")
        root = [node.key for node in tree.root.children]
        self.assertEqual(root, ["OR", "year", "OR", "NOT", "mg_made_up_check"])
        self.assertEqual(tree.root.children[0].form, NodeForm.GROUP)
        self.assertEqual(tree.root.children[1].form, NodeForm.VALUE)
        self.assertEqual(tree.raw_count(), 1, "la clave inventada se muestra como nodo crudo")
        self.assertIn("mg_made_up_check = 3", tree.root.children[4].source())

    def test_changing_a_value_changes_only_its_line_and_keeps_the_comment(self):
        before = _text(self.project, "events/mg_flavor.txt")
        with self.project.ws.transaction("edit"):
            tree = self.event(2001).script("trigger")
            tree.root.children[1].set_value(1843)
        after = _text(self.project, "events/mg_flavor.txt")
        changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
        self.assertEqual(len(before.splitlines()), len(after.splitlines()))
        self.assertEqual(changed, [("\t\tyear = 1842 # desde ese año", "\t\tyear = 1843 # desde ese año")])
        handle = self.project.ws.peek(VPath.of("events/mg_flavor.txt"))
        self.assertEqual(handle.rel, VPath.of("events/mg_flavor.txt"), "la copia va a la misma ruta del mod")

    def test_wrap_unwrap_add_and_remove(self):
        with self.project.ws.transaction("edit"):
            tree = self.event(2001).script("trigger")
            year = tree.root.children[1]
            group = year.wrap("NOT")
            self.assertEqual(group.key, "NOT")
            self.assertEqual([c.key for c in group.children], ["year"])
            group.unwrap()
            self.assertEqual(tree.root.children[1].key, "year")
            added = tree.root.add_child("prestige", 3)
            self.assertEqual(added.key, "prestige")
            added.remove()
        self.assertNotIn("prestige = 3", _text(self.project, "events/mg_flavor.txt"))
        self.assertIn("\t\tyear = 1842 # desde ese año", _text(self.project, "events/mg_flavor.txt"))

    def test_scope_mismatch_in_a_province_event(self):
        tree = self.event(2002).script("trigger")
        codes = [problem.code for problem in tree.issues(self.entities.check_context())]
        self.assertIn(SCOPE_MISMATCH, codes, "prestige es de país y el evento 2002 es de provincia")
        self.assertNotIn(SCOPE_MISMATCH, [p.code for p in self.event(2001).script("trigger").issues(
            self.entities.check_context())])


class PhraseTests(ScriptProjectCase):
    def test_phrase_of_the_criterion_shape(self):
        tree = self.event(2001).script("trigger")
        names = self.loc.localisation_db()
        es = phrase(tree, "es", self.index, names, lead="trigger")
        en = phrase(tree, "en", self.index, names, lead="trigger")
        for text in ("Aland", "Borland", "1842 o después", "antes de 1845", "monarchy", "republic", "council"):
            self.assertIn(text, es)
        for text in ("Aland", "Borland", "1842 or later", "before 1845"):
            self.assertIn(text, en)
        self.assertIn("«mg_made_up_check = 3»", es, "lo que el catálogo no conoce se cita tal cual")

    def test_phrase_lines_follow_the_tree(self):
        lines = phrase_lines(self.event(2001).script("trigger"), "en")
        self.assertEqual([line.path for line in lines][:3], [(0,), (0, 0), (0, 1)])
        self.assertEqual(lines[0].depth, 0)
        self.assertEqual(lines[1].depth, 1)
        self.assertTrue(lines[-1].raw)


class MtthTests(ScriptProjectCase):
    def test_read_weights_of_an_event(self):
        model = read_weights(self.event(2001))
        self.assertEqual((model.unit, model.base), ("months", 6.0))
        self.assertEqual([m.factor for m in model.modifiers], [0.75, 0.95])
        months = effective(to_months(model.base, model.unit), [m.factor for m in model.modifiers], [True, True])
        self.assertAlmostEqual(months, 6 * 0.75 * 0.95)
        self.assertEqual(format_duration(months, "es"), "4,3 meses")
        self.assertEqual(format_duration(months, "en"), "4.3 months")
        self.assertAlmostEqual(effective(6, [0.75, 0.95], [False, True]), 6 * 0.95)

    def test_ai_chance_and_ai_will_do(self):
        option = self.event(2001).group("option", 0)
        chance = read_weights(option, AI_CHANCE_KEY)
        self.assertEqual(chance.base, 70.0)
        self.assertEqual([m.factor for m in chance.modifiers], [0.0])
        will = read_weights(self.decision("mg_build_harbour"), AI_WILL_DO_KEY)
        self.assertEqual((will.base, [m.factor for m in will.modifiers]), (1.0, [0.0]))
        self.assertIsNone(read_weights(self.decision("mg_call_council"), AI_WILL_DO_KEY))


class EventCreateTests(ScriptProjectCase):
    def test_new_event_gets_the_first_free_id_its_file_and_its_texts(self):
        allocator = self.entities.id_allocator("event")
        self.assertEqual(allocator.range, (200_000_000, 200_009_999))
        ident = allocator.next_free()
        self.assertEqual(ident, 200_000_000)
        with self.project.ws.transaction("new"):
            self.entities.create("event", str(ident), None)
        source = _text(self.project, "events/TESTMOD_events.txt")
        self.assertIn(f"id = {ident}", source)
        self.assertIn("is_triggered_only = yes", source)
        csv = _text(self.project, "localisation/00_TESTMOD_events.csv")
        for key in ("EVTNAME", "EVTDESC", "EVTOPTA", "EVTOPTB"):
            self.assertIn(f"{key}{ident};", csv)
        self.assertEqual(self.entities.id_allocator("event").next_free(), ident + 1)

    def test_new_decision_has_its_three_script_blocks_and_texts(self):
        with self.project.ws.transaction("new"):
            ref = self.entities.create("decision", "tst_new_harbour", None)
        record = self.entities.open(ref)
        rel = str(record.handle.rel)
        self.assertTrue(rel.startswith("decisions/"), rel)
        source = _text(self.project, rel)
        self.assertIn("political_decisions = {", source)
        for key in ("potential", "allow", "effect"):
            self.assertIsNotNone(record.script(key), key)
            self.assertRegex(source, rf"\t\t{key} = {{\s*}}")
        csv = _text(self.project, "localisation/00_TESTMOD_decisions.csv")
        self.assertIn("tst_new_harbour_title;", csv)
        self.assertIn("tst_new_harbour_desc;", csv)

    def test_bad_ids_are_rejected_with_the_next_free(self):
        allocator = self.entities.id_allocator("event")
        self.assertEqual(allocator.problem("abc"), ID_NOT_A_NUMBER)
        self.assertEqual(allocator.problem(2001), ID_OUT_OF_RANGE, "los ids de vanilla quedan fuera del rango")
        with self.project.ws.transaction("new"):
            self.entities.create("event", "200000000", None)
        self.assertEqual(self.entities.id_allocator("event").problem(200_000_000), ID_TAKEN)
        with self.assertRaises(InvalidIdentError) as caught:
            with self.project.ws.transaction("new"):
                self.entities.create("event", "200000000", None)
        self.assertEqual(caught.exception.code, ID_TAKEN)
        self.assertEqual(caught.exception.params.get("next_free"), 200_000_001)


class TextOnlyTests(ScriptProjectCase):
    def test_broken_decisions_open_in_text_mode_with_the_fix(self):
        for ident in SCRIPT_BROKEN_IDS:
            state = text_only_of(self.entities, RecordRef("decision", ident))
            self.assertIsNotNone(state, ident)
            self.assertEqual(state.rel, VPath.of(SCRIPT_BROKEN_DECISIONS))
            self.assertEqual(state.reason, "parse_errors")
            self.assertEqual(state.fixes, ("add_closing_brace",))
        self.assertIsNone(text_only_of(self.entities, RecordRef("decision", "mg_build_harbour")))


@unittest.skipUnless(vanilla_root(), "sin VIC2_GAME (corpus de vanilla)")
class VanillaCorpusTests(unittest.TestCase):
    """Criterios 1 y 2 sobre vanilla: ida y vuelta, cambio de una sola línea y cobertura del catálogo."""

    def test_round_trip_and_single_line_change(self):
        game = vanilla_root()
        catalog = ScriptCatalog.load()
        counts = {"events": 0, "decisions": 0}
        single_line = 0
        for rel_dir in counts:
            for path in sorted((game / rel_dir).glob("*.txt")):
                decoded = decode_bytes(path.read_bytes())
                result = parse(decoded.text)
                counts[rel_dir] += 1
                trees = []
                for item, scope in catalog_census.items_of(rel_dir, result.document):
                    for block, kind, start, skip in catalog_census.script_blocks(item, scope):
                        trees.append(ScriptTree(block, kind, start, catalog, skip=skip, touch=lambda: None))
                        for node in trees[-1].walk():
                            node.source()
                self.assertEqual(to_source(result.document), decoded.text, path.name)
                if self._change_one_value(trees, result.document, decoded.text):
                    single_line += 1
        self.assertEqual(counts, {"events": 82, "decisions": 29})
        self.assertGreaterEqual(single_line, 80, "casi todos los archivos tienen un valor entero que cambiar")

    def _change_one_value(self, trees, document: Block, original: str) -> bool:
        for tree in trees:
            for node in tree.walk():
                value = node.value
                if node.form is not NodeForm.VALUE or isinstance(value, bool) or not isinstance(value, int):
                    continue
                try:
                    node.set_value(value + 1)
                except (ValueError, TypeError):
                    continue
                before, after = original.splitlines(), to_source(document).splitlines()
                self.assertEqual(len(before), len(after))
                self.assertEqual(sum(a != b for a, b in zip(before, after)), 1)
                return True
        return False

    def test_catalog_covers_95_percent_of_vanilla(self):
        game = vanilla_root()
        report = catalog_census.census(game, symbols=catalog_census.game_index(game))
        self.assertEqual(report["round_trip_failures"], 0)
        for kind, data in report["kinds"].items():
            self.assertGreaterEqual(data["coverage"], 0.95, kind)


@unittest.skipUnless(vanilla_root() and user_mod(), "sin VIC2_GAME o sin el mod del usuario en el corpus")
class UserModCorpusTests(unittest.TestCase):
    """Criterios 4 y 5 con el juego real y una copia de las decisiones del mod del usuario."""

    @classmethod
    def setUpClass(cls):
        cls._config = tempfile.TemporaryDirectory(prefix="vic2studio-it7-")
        os.environ.setdefault("XDG_CONFIG_HOME", cls._config.name)

    @classmethod
    def tearDownClass(cls):
        cls._config.cleanup()

    def setUp(self):
        isolate_appdirs(self)
        mod = copy_user_mod(self, "decisions")
        self.project = Project.open(vanilla_root(), mod)
        self.addCleanup(self.project.close)
        self.index = build_index(self.project.vfs.snapshot(), None, {})
        self.loc = LocSync(self.project.ws, self.project.vfs, prefix=self.project.settings.prefix)
        self.entities = Entities(self.project.ws, self.index, self.loc)

    def test_user_broken_decisions_and_the_austrian_phrase(self):
        from _corpus import USER_BROKEN_FILES

        broken = {VPath.of(rel) for rel in USER_BROKEN_FILES}
        found = set()
        for summary in self.entities.list("decision"):
            state = text_only_of(self.entities, summary.ref)
            if state is not None:
                found.add(state.rel)
                self.assertIn("add_closing_brace", state.fixes)
        self.assertEqual(found, broken)
        record = self.entities.open(RecordRef("event", "31502"))
        names = self.loc.localisation_db()
        es = phrase(record.script("trigger"), "es", self.index, names)
        for text in ("Austria", "Imperio Austrohúngaro", "1842 o después", "antes de 1845"):
            self.assertIn(text, es)
        en = phrase(record.script("trigger"), "en", self.index, names)
        for text in ("Austria", "Austria-Hungary", "1842 or later", "before 1845"):
            self.assertIn(text, en)
        self.assertEqual(es.count(","), en.count(","), "los tres gobiernos, con su nombre, en los dos idiomas")
        self.assertIsNotNone(read_weights(record))


if __name__ == "__main__":
    unittest.main()
