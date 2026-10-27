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

    def test_refused_on_a_countries_txt_with_syntax_errors(self):
        """Revisión it3: con un bloque sin cerrar, dynamic_tags queda dentro y la línea iba al final, detrás."""
        broken = GAME_FILES[COUNTRIES].replace('dynamic_tags = yes', 'oops = {\r\ndynamic_tags = yes', 1)
        self.assertNotEqual(broken, GAME_FILES[COUNTRIES])
        game, project = self.open(mod_files={**ESLAND, COUNTRIES: broken})
        # D01 también sale: con el bloque sin cerrar queda dentro de «oops», y cultures.txt lo usa.
        [problem] = [p for p in problems(project, {"tag_not_registered"}) if p.entity == ("tag", "EEE")]
        with self.assertRaises(FixError) as raised:
            plan_fix("register_tag", problem, project)
        self.assertEqual(raised.exception.code, "syntax_errors")
        self.assertIn("countries.txt", raised.exception.message("es"))

    def test_registers_in_the_game_file_after_trashing_the_mod_copy(self):
        """Revisión it3: con la copia del mod de countries.txt en la papelera, lo efectivo es el del juego."""
        game, project = self.open(mod_files={**ESLAND, COUNTRIES: GAME_FILES[COUNTRIES]})
        with project.edit("undo.delete"):
            project.ws.delete(COUNTRIES)
        [problem] = problems(project, {"tag_not_registered"})
        [change] = plan_fix("register_tag", problem, project).changes
        self.assertIn('+EEE = "countries/Esland.txt"', change.diff)
        apply_fix("register_tag", problem, project)
        handle = project.ws.peek(COUNTRIES)
        self.assertFalse(handle.deleted)
        self.assertEqual(changed_lines(game.game(COUNTRIES).read_bytes(), codec_for(handle.kind).snapshot(handle.model)),
                         (1, 0))

    def test_read_only_projects_and_stale_plans_are_refused(self):
        game, project = self.open(mod_files=ESLAND)
        [problem] = problems(project, {"tag_not_registered"})
        plan = plan_fix("register_tag", problem, project)
        with project.edit("undo.edit"):                          # cambia countries.txt entre el plan y el apply
            handle = project.ws.open(COUNTRIES)
            data = codec_for(handle.kind).snapshot(handle.model)
            project.ws.replace_text(handle, data.replace(b"countries/Corland.txt", b"countries/Corland2.txt"))
        with self.assertRaises(FixError) as raised:
            apply_fix("register_tag", problem, project, expected=plan)
        self.assertEqual(raised.exception.code, "plan_changed")
        self.assertEqual(len(project.ws.history()), 1, "no aplicó nada")
        holder = Project.open(game.game_root, game.mod_root)     # la otra ventana: solo lectura
        self.addCleanup(holder.close, discard=True)
        self.assertTrue(holder.ws.read_only)
        with self.assertRaises(FixError) as raised:
            apply_fix("register_tag", problem, holder)
        self.assertEqual(raised.exception.code, "read_only")
        self.assertEqual(holder.ws.documents(), [], "no abrió nada")

    def test_modifies_the_mod_copy_and_falls_back_to_the_tag_file_name(self):
        files = {COUNTRIES: GAME_FILES[COUNTRIES], "history/countries/FFF.txt": "capital = 1\r\n",
                 "common/countries/fff.txt": GAME_FILES["common/countries/Aland.txt"]}
        game, project = self.open(mod_files=files)
        [problem] = problems(project, {"tag_not_registered"})
        [change] = plan_fix("register_tag", problem, project).changes
        self.assertEqual(change.action, ACTION_MODIFY)
        self.assertIn('+FFF = "countries/fff.txt"', change.diff, "sin nombre en la historia, el del TAG, como está")

    def test_refused_without_a_country_file(self):
        """Revisión it3: CSR de VSM solo tiene banderas; registrarlo con un archivo de país que no existe cambiaba
        tag_not_registered por country_file_missing (y el juego no carga ese país)."""
        files = {"history/countries/FFF - Fenland.txt": "capital = 1\r\n"}
        game, project = self.open(mod_files=files)
        [problem] = problems(project, {"tag_not_registered"})
        before = state(project)
        for call in (lambda: plan_fix("register_tag", problem, project),
                     lambda: apply_fix("register_tag", problem, project)):
            with self.assertRaises(FixError) as raised:
                call()
            self.assertEqual(raised.exception.code, "no_country_file")
            self.assertIn("common/countries/Fenland.txt", raised.exception.message("es"))
            self.assertIn("FFF", raised.exception.message("en"))
        self.assertEqual(state(project), before, "no cambia nada")
        # Un archivo de país nuevo sin guardar ya cuenta (la vista efectiva, I7); en la papelera, ya no.
        with project.edit("undo.edit"):
            handle = project.ws.open("common/countries/Fenland.txt", create=True)
            project.ws.replace_text(handle, GAME_FILES["common/countries/Aland.txt"].encode("cp1252"))
        [change] = plan_fix("register_tag", problem, project).changes
        self.assertIn('+FFF = "countries/Fenland.txt"', change.diff)
        with project.edit("undo.delete"):
            project.ws.delete("common/countries/Fenland.txt")
        with self.assertRaises(FixError):
            plan_fix("register_tag", problem, project)

    def test_refused_when_the_country_file_is_in_the_trash(self):
        """La lápida de un archivo de país del mod (sin nada debajo en el juego) es «no existe»."""
        files = {"history/countries/FFF - Fenland.txt": "capital = 1\r\n",
                 "common/countries/Fenland.txt": GAME_FILES["common/countries/Aland.txt"]}
        game, project = self.open(mod_files=files)
        [problem] = problems(project, {"tag_not_registered"})
        self.assertIn('+FFF = "countries/Fenland.txt"', plan_fix("register_tag", problem, project).changes[0].diff)
        with project.edit("undo.delete"):
            project.ws.delete("common/countries/Fenland.txt")
        self.assertTrue(project.ws.peek("common/countries/Fenland.txt").deleted)
        with self.assertRaises(FixError) as raised:
            plan_fix("register_tag", problem, project)
        self.assertEqual(raised.exception.code, "no_country_file")


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
                # Las líneas del diff entero, en el plan; el UTF-16 tiene NUL: su diff es el resumen de un binario.
                self.assertEqual(plan.changes[0].lines, None if code == "unreadable_encoding" else (1, 1))
                apply_fix("convert_to_cp1252", problem, project)
                handle = project.ws.peek(rel)
                data = codec_for(handle.kind).snapshot(handle.model)
                wanted = f'country_event = {{ id = {event} title = "{expected}" }}\r\n'
                self.assertEqual(data, wanted.encode("cp1252"))
                self.assertFalse([p for p in problems(project, {code}) if p.rel == rel])

    def test_doubly_encoded_text_is_refused(self):
        """Revisión it3: «CafÃ©» en UTF-8 pasa a cp1252 como «Café» en UTF-8: la conversión no surtía efecto."""
        rel = "events/double.txt"
        game, project = self.open(mod_files={rel: 'e = { title = "CafÃ©" }\r\n'.encode("utf-8")})
        [problem] = [p for p in problems(project, {"non_game_encoding"}) if p.rel == rel]
        with self.assertRaises(FixError) as raised:
            plan_fix("convert_to_cp1252", problem, project)
        self.assertEqual(raised.exception.code, "still_utf8")

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

    def test_a_copy_that_hides_a_different_dependency_stays(self):
        """Revisión it3: la copia es idéntica al juego pero tapa otra versión de una dependencia; borrarla cambiaría
        lo que carga el juego. Solo cuenta lo que ganaría sin la copia."""
        import tempfile

        from _layers import build_layers

        rel = "common/cb_types.txt"
        dep = GAME_FILES[rel].replace("months = 12", "months = 99")
        descriptor = b'name = "TestMod"\r\npath = "mod/TestMod"\r\ndependencies = { "Dep" }\r\n'
        for dependency, expected in ((dep, []), (GAME_FILES[rel], [rel])):
            with self.subTest(dependencia_igual=dependency == GAME_FILES[rel]):
                layers = build_layers(game=GAME_FILES, mod={rel: GAME_FILES[rel]}, descriptor=descriptor,
                                      dependencies={"Dep": {rel: dependency}}, base=Path(tempfile.mkdtemp()))
                self.addCleanup(layers.cleanup)
                project = Project.open(layers.game_root, layers.mod_root)
                self.addCleanup(project.close, discard=True)
                from vic2studio.core.validate.fixes import identical_copies

                self.assertEqual([str(r) for r in identical_copies(project)], expected)

    def test_refused_while_the_descriptor_names_other_replace_paths(self):
        """Revisión it3: un replace_path añadido en la sesión no está aún en la vista abierta; la papelera se llevaba
        las copias que lo hacen imprescindible."""
        from _layers import descriptor_bytes
        from vic2studio.core.vfs import DESCRIPTOR_REL

        game, project = self.open(mod_files={"events/minigame_events.txt": GAME_FILES["events/minigame_events.txt"]})
        self.assertTrue(plan_fix("trash_identical_copies", None, project).changes)
        with project.edit("undo.edit"):
            project.ws.replace_text(project.ws.open(DESCRIPTOR_REL),
                                    descriptor_bytes("TestMod", "TestMod", "TestMod", replace_paths=["events"]))
        for call in (plan_fix, apply_fix):
            with self.subTest(call=call.__name__):
                with self.assertRaises(FixError) as raised:
                    call("trash_identical_copies", None, project)
                self.assertEqual(raised.exception.code, "descriptor_changed")
        self.assertEqual([h.rel for h in project.ws.dirty()], [DESCRIPTOR_REL], "no mandó nada a la papelera")

    def test_applying_with_the_shown_plan_compares_the_copies_once(self):
        """Revisión it3: plan + comprobación + apply comparaban los 8462 archivos de VSM tres veces."""
        from unittest import mock

        from vic2studio.core.validate import fixes as fixes_module

        game, project = self.open(mod_files={"common/cb_types.txt": GAME_FILES["common/cb_types.txt"]})
        plan = plan_fix("trash_identical_copies", None, project)
        with mock.patch.object(fixes_module, "identical_copies", wraps=fixes_module.identical_copies) as spy:
            apply_fix("trash_identical_copies", None, project, expected=plan)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual([str(h.rel) for h in project.ws.dirty()], ["common/cb_types.txt"])

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
