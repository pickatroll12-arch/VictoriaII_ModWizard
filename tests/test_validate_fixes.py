"""SimpleFix (wizard §11.1): cada arreglo sobre un ``Project`` real del minijuego.

En todos: ``plan`` deja el proyecto idéntico (documentos, sucios y pila de deshacer)
y su diff es exactamente lo que hará ``apply``; ``apply`` es una transacción
deshacible en un paso; tras aplicar, revalidar con los documentos sin guardar ya no
da el problema; Ctrl+Z lo deja todo como estaba.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import descriptor_bytes, isolate_appdirs  # noqa: E402
from _minigame import GAME_FILES, build_minigame  # noqa: E402
from vic2studio.core.index import build_index  # noqa: E402
from vic2studio.core.project import Project, WriteAction  # noqa: E402
from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.project.diffing import changed_lines  # noqa: E402
from vic2studio.core.validate import FIXES, Validator, apply_fix, build_context, fixes_for, plan_fix  # noqa: E402
from vic2studio.core.validate.fixes import FixError  # noqa: E402
from vic2studio.core.validate.model import ACTION_COPY_FROM_GAME, ACTION_MODIFY, ACTION_TRASH  # noqa: E402

COUNTRIES = "common/countries.txt"
ESLAND = {"history/countries/EEE - Esland.txt": "capital = 1\r\nprimary_culture = alander\r\ngovernment = monarchy\r\n",
          "common/countries/Esland.txt": GAME_FILES["common/countries/Aland.txt"]}


def overrides_of(project) -> dict:
    found = {}
    for handle in project.ws.dirty():
        found[handle.rel] = None if handle.deleted else codec_for(handle.kind).snapshot(handle.model)
    return found


def problems(project, codes):
    snap = project.vfs.snapshot()
    overrides = overrides_of(project)
    ctx = build_context(snap, build_index(snap, None, overrides), overrides)
    return list(Validator(ctx).validate(codes=codes).problems)


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

    def run_fix(self, project, key: str, code: str):
        """Plan (sin efectos), apply (un paso) y revalidación; devuelve (plan, problema)."""
        [problem] = [p for p in problems(project, {code}) if key in p.fixes]
        self.assertEqual(fixes_for(problem)[0].key, key, "es el SimpleFix")
        before = state(project)
        plan = plan_fix(key, problem, project)
        plan_fix(key, problem, project)
        self.assertEqual(state(project), before, "plan no cambia nada (pila de deshacer incluida)")
        apply_fix(key, problem, project)
        self.assertEqual(len(project.ws.history()), len(before[0]) + 1, "un solo paso de deshacer")
        self.assertEqual(project.ws.history()[0][0], f"undo.fix_{key}")
        self.assertEqual([p for p in problems(project, {code}) if p.rel == problem.rel and p.args == problem.args], [],
                         "revalidar quita el problema")
        return plan, problem


class RegisterTagTests(FixTestCase):
    def test_register_before_dynamic_tags_in_one_line(self):
        game, project = self.open(mod_files=ESLAND)
        plan, problem = self.run_fix(project, "register_tag", "tag_not_registered")
        self.assertEqual(problem.entity, ("tag", "EEE"))
        [change] = plan.changes
        self.assertEqual((change.rel, change.action), (COUNTRIES, ACTION_COPY_FROM_GAME))
        self.assertIn('+EEE = "countries/Esland.txt"', change.diff)
        handle = project.ws.peek(COUNTRIES)
        after = codec_for(handle.kind).snapshot(handle.model)
        before = game.game(COUNTRIES).read_bytes()
        self.assertEqual(changed_lines(before, after), (1, 0))
        # Justo antes de dynamic_tags, delante de los comentarios (y la línea vacía) que lo preceden (D7, H11).
        self.assertEqual(after, before.replace(b'CCC = "countries/Corland.txt"\r\n',
                                               b'CCC = "countries/Corland.txt"\r\nEEE = "countries/Esland.txt"\r\n'))
        writes = project.ws.changeset().writes
        self.assertEqual([(str(w.rel), w.action) for w in writes], [(COUNTRIES, WriteAction.COPY_FROM_GAME)])
        project.ws.undo()
        self.assertEqual(project.ws.dirty(), [])
        self.assertTrue(problems(project, {"tag_not_registered"}))

    def test_label_and_errors(self):
        game, project = self.open(mod_files=ESLAND)
        [problem] = problems(project, {"tag_not_registered"})
        spec = FIXES["register_tag"]
        self.assertTrue(spec.safe)
        self.assertEqual(spec.label(problem, "es"), "Registrar EEE en countries.txt")
        self.assertEqual(spec.label(problem, "en"), "Register EEE in countries.txt")
        apply_fix("register_tag", problem, project)
        with self.assertRaises(FixError) as raised:
            plan_fix("register_tag", problem, project)
        self.assertEqual(raised.exception.code, "already_registered")
        self.assertIn("EEE", raised.exception.message("es"))
        with self.assertRaises(KeyError):
            plan_fix("no_such_fix", problem, project)

    def test_modifies_the_mod_copy_and_falls_back_to_a_new_file_name(self):
        files = {COUNTRIES: GAME_FILES[COUNTRIES], "history/countries/FFF.txt": "capital = 1\r\n"}
        game, project = self.open(mod_files=files)
        [problem] = problems(project, {"tag_not_registered"})
        [change] = plan_fix("register_tag", problem, project).changes
        self.assertEqual(change.action, ACTION_MODIFY)
        self.assertIn('+FFF = "countries/FFF.txt"', change.diff, "sin nombre en la historia, el del TAG")


class ConvertTests(FixTestCase):
    def test_utf8_and_utf16_become_cp1252(self):
        files = {"events/utf8.txt": 'country_event = { id = 5001 title = "Café" }\r\n'.encode("utf-8"),
                 "events/utf16.txt": 'country_event = { id = 5002 title = "Ñu" }\r\n'.encode("utf-16"),
                 "events/bom.txt": b'\xef\xbb\xbfcountry_event = { id = 5003 title = "Caf\xe9" }\r\n'}
        game, project = self.open(mod_files=files)
        for event, rel, code, expected in ((5001, "events/utf8.txt", "non_game_encoding", "Café"),
                                           (5002, "events/utf16.txt", "unreadable_encoding", "Ñu"),
                                           (5003, "events/bom.txt", "stray_bom", "Café")):
            with self.subTest(rel=rel):
                [problem] = [p for p in problems(project, {code}) if p.rel == rel]
                plan = plan_fix("convert_to_cp1252", problem, project)
                self.assertEqual(plan.changes[0].action, ACTION_MODIFY)
                apply_fix("convert_to_cp1252", problem, project)
                handle = project.ws.peek(rel)
                data = codec_for(handle.kind).snapshot(handle.model)
                wanted = f'country_event = {{ id = {event} title = "{expected}" }}\r\n'
                self.assertEqual(data, wanted.encode("cp1252"))
                self.assertFalse([p for p in problems(project, {code}) if p.rel == rel])

    def test_unencodable_text_is_refused_without_changes(self):
        cjk = 'country_event = { id = 5009 title = "中" }'.encode("utf-8")
        game, project = self.open(mod_files={"events/cjk.txt": cjk})
        [problem] = problems(project, {"non_game_encoding"})
        before = state(project)
        for action in (plan_fix, apply_fix):
            with self.assertRaises(FixError) as raised:
                action("convert_to_cp1252", problem, project)
            self.assertEqual(raised.exception.code, "unencodable")
            self.assertEqual(raised.exception.params["char"], "中")
        self.assertEqual(state(project), before)


class ClosingBraceTests(FixTestCase):
    def test_closes_the_unclosed_block_of_a_read_only_document(self):
        game, project = self.open(mod_files={"decisions/broken.txt": "political_decisions = {\r\n\td = { }\r\n"})
        handle = project.ws.open("decisions/broken.txt")
        self.assertEqual(handle.read_only_reason, "parse_errors")
        plan, _ = self.run_fix(project, "add_closing_brace", "unclosed_block")
        self.assertIn("+}", plan.changes[0].diff)
        data = codec_for(handle.kind).snapshot(project.ws.peek("decisions/broken.txt").model)
        self.assertEqual(data, b"political_decisions = {\r\n\td = { }\r\n}\r\n")
        self.assertIsNone(project.ws.peek("decisions/broken.txt").read_only_reason, "D17: vuelve a ser editable")
        project.ws.undo()
        self.assertEqual(project.ws.dirty(), [])


class RestoreRowsTests(FixTestCase):
    def test_restores_the_degraded_rows_and_nothing_else(self):
        rel = "localisation/minigame_names.csv"
        original = GAME_FILES[rel]
        degraded = original.replace("alandés", "aland?").replace("borlandés", "borland?s") \
            + "mod_only;Only;;;;Solo;;;;;;;;;x\r\n"
        game, project = self.open(mod_files={rel: degraded})
        plan, problem = self.run_fix(project, "restore_vanilla_loc_rows", "loc_copy_degraded")
        self.assertEqual(problem.args["rows"], 3)
        self.assertEqual(plan.changes[0].diff.count("\n-AAA_ADJ;"), 1)
        handle = project.ws.peek(rel)
        data = codec_for(handle.kind).snapshot(handle.model)
        self.assertEqual(data, (original + "mod_only;Only;;;;Solo;;;;;;;;;x\r\n").encode("cp1252"),
                         "solo cambian las filas degradadas; la fila propia del mod se queda")
        self.assertEqual(FIXES["restore_vanilla_loc_rows"].label(problem, "es"),
                         "Recuperar las filas de vanilla de «minigame_names.csv» (3)")


class TrashCopiesTests(FixTestCase):
    def test_trashes_identical_copies_outside_replace_path_folders(self):
        game, project = self.open(mod_files={"common/cb_types.txt": GAME_FILES["common/cb_types.txt"],
                                             "map/region.txt": GAME_FILES["map/region.txt"],
                                             "events/minigame_events.txt": GAME_FILES["events/minigame_events.txt"],
                                             "events/minigame_more.txt": GAME_FILES["events/minigame_more.txt"]})
        project.close(discard=True)
        game.descriptor.write_bytes(descriptor_bytes("TestMod", "TestMod", "TestMod", replace_paths=["events"]))
        project = Project.open(game.game_root, game.mod_root)
        self.addCleanup(project.close, discard=True)
        found = problems(project, {"mod_shadow_identical"})
        self.assertEqual([str(p.rel) for p in found], ["common/cb_types.txt", "map/region.txt"],
                         "las de events/ hacen falta: replace_path oculta las del juego")
        spec = FIXES["trash_identical_copies"]
        self.assertFalse(spec.safe, "borra: pide confirmación explícita")
        [problem] = [p for p in found if p.rel == "map/region.txt"]
        history = project.ws.history()
        plan = plan_fix("trash_identical_copies", problem, project)
        self.assertEqual(project.ws.history(), history)
        self.assertEqual([(str(c.rel), c.action, c.diff) for c in plan.changes],
                         [("common/cb_types.txt", ACTION_TRASH, ""), ("map/region.txt", ACTION_TRASH, "")],
                         "todas las copias idénticas, no solo la del problema")
        apply_fix("trash_identical_copies", problem, project)
        self.assertEqual(project.ws.history(), [("undo.fix_trash_identical_copies", {"count": 2})] + history,
                         "las dos en un solo paso")
        self.assertEqual(problems(project, {"mod_shadow_identical"}), [])
        self.assertEqual([(str(w.rel), w.action) for w in project.ws.changeset().writes],
                         [("common/cb_types.txt", WriteAction.TRASH), ("map/region.txt", WriteAction.TRASH)])
        project.ws.undo()
        self.assertEqual(project.ws.dirty(), [])

    def test_nothing_to_trash(self):
        game, project = self.open()
        with self.assertRaises(FixError):
            FIXES["trash_identical_copies"].apply(None, project)


class CatalogueTests(unittest.TestCase):
    def test_every_declared_fix_is_registered_with_texts(self):
        from vic2studio.core import texts
        from vic2studio.core.validate import discover_rules

        declared = {key for spec in discover_rules().values() for key in spec.fixes}
        self.assertEqual(declared, set(FIXES))
        self.assertEqual(set(FIXES), {"register_tag", "convert_to_cp1252", "add_closing_brace",
                                      "restore_vanilla_loc_rows", "trash_identical_copies"})
        for lang in ("es", "en"):
            catalogue = texts.load_texts(lang)
            for key in FIXES:
                self.assertIn(f"fix.{key}", catalogue)
                self.assertIn(f"undo.fix_{key}", catalogue)

    def test_fix_error_pickles(self):
        import pickle

        error = pickle.loads(pickle.dumps(FixError("already_registered", tag="SIL")))
        self.assertEqual((error.code, error.params), ("already_registered", {"tag": "SIL"}))


if __name__ == "__main__":
    unittest.main()
