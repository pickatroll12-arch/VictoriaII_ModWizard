"""Criterios de los encargos del motor (ENCARGO_MOTOR.md, fase 3) y de la iteración 4 (wizard §22, ENCARGO_IT4).

Los criterios 1, 2 y 6 necesitan el corpus (``vanilla_root()``) y trabajan sobre una copia
temporal: el juego base se abre como proyecto con un mod vacío en una carpeta temporal, nunca
el mod real del usuario. Los criterios 3, 4 y 5 corren sobre el minijuego sintético.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
if str(PROJECT_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from vic2studio.core.index.builder import build_index  # noqa: E402
from vic2studio.core.locsync import LocSync  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.project.model import WriteAction  # noqa: E402
from vic2studio.core.schema import CheckContext, Entities, EntityInUseError, RecordRef  # noqa: E402
from vic2studio.core.vfs.paths import VPath  # noqa: E402

from _corpus import vanilla_root  # noqa: E402
from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402


class CriteriaCase(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def open_minigame(self) -> tuple[Project, Entities, LocSync]:
        game = build_minigame(mod=True)
        self.addCleanup(game.cleanup)
        project = Project.open(game.game_root, game.mod_root)
        self.addCleanup(project.close, discard=True)
        index = build_index(project.vfs.snapshot(), None, {})
        loc = LocSync(project.ws, project.vfs, prefix=project.settings.prefix)
        return project, Entities(project.ws, index, loc), loc

    def open_vanilla(self) -> tuple[Project, Entities, LocSync, Path]:
        """Juego base real con un mod vacío en una carpeta temporal (nunca el mod del usuario)."""
        game_root = vanilla_root()
        mod_root = Path(tempfile.mkdtemp(prefix="vic2studio-criteria-mod-"))
        self.addCleanup(shutil.rmtree, mod_root, True)
        project = Project.open(game_root, mod_root)
        self.addCleanup(project.close, discard=True)
        index = build_index(project.vfs.snapshot(), None, {})
        loc = LocSync(project.ws, project.vfs, prefix=project.settings.prefix)
        return project, Entities(project.ws, index, loc), loc, mod_root

    def _ctx(self, entities: Entities) -> CheckContext:
        return CheckContext(entities.ws, entities.index, entities.loc)


class CorpusTests(CriteriaCase):
    """Criterios 1, 2 y 6 (necesitan vanilla)."""

    @unittest.skipUnless(vanilla_root(), "sin corpus")
    def test_criterion1_corpus_conformance(self):
        project, entities, _, _ = self.open_vanilla()
        counts: dict[str, int] = {}
        for kind in ("government", "unit"):
            summaries = entities.list(kind)
            counts[kind] = len(summaries)
            for summary in summaries:
                record = entities.open(summary.ref)
                for problem in record.issues(self._ctx(entities)):
                    self.assertNotIn(problem.code, ("unknown_field", "bad_type"),
                                     f"{summary.ref.ident}: {problem.code} en {problem.field}")
                for key in record._index_schema()[0]:
                    record.get(key)
                for name in record._index_schema()[2]:
                    record.dynamic(name)
        self.assertEqual(counts, {"government": 8, "unit": 21},
                         "vanilla: 8 gobiernos y 21 unidades (11 terrestres y 10 navales)")
        self.assertTrue(project.ws.save().nothing_to_save, "abrir y leer el corpus escribe")

    @unittest.skipUnless(vanilla_root(), "sin corpus")
    def test_criterion2_set_attack_single_line(self):
        project, entities, _, mod_root = self.open_vanilla()
        game_file = vanilla_root() / "units" / "infantry.txt"
        before = game_file.read_bytes()
        infantry = entities.open(RecordRef("unit", "infantry"))
        with project.ws.transaction("test.undo_set", key="attack", ident="infantry"):
            infantry.set("attack", 5.0)
        project.ws.save()
        after = (mod_root / "units" / "infantry.txt").read_bytes()
        before_lines = before.decode("cp1252").splitlines()
        after_lines = after.decode("cp1252").splitlines()
        changed = [i for i, (old, new) in enumerate(zip(before_lines, after_lines)) if old != new]
        self.assertEqual(len(before_lines), len(after_lines), "cambió el número de líneas")
        self.assertEqual(changed, [before_lines.index("	attack = 4")],
                         "cambia una sola línea: la de attack")
        self.assertIn("attack = 5", after_lines[changed[0]])
        self.assertIn(b"\r\n", after, "se conservan los saltos CRLF")
        self.assertIn(b"#Core Abilities", after, "se conservan los comentarios")

    @unittest.skipUnless(vanilla_root(), "sin corpus")
    def test_criterion6_unknown_and_comment_survive(self):
        project, entities, _, mod_root = self.open_vanilla()
        infantry = entities.open(RecordRef("unit", "infantry"))
        with project.ws.transaction("test.undo_add", key="mystery", ident="infantry"):
            entry = infantry.block.append("mystery_thing", 42)
            entry.comments = ["# nota de campo propio"]
        with project.ws.transaction("test.undo_set", key="maximum_speed", ident="infantry"):
            infantry.set("maximum_speed", 5)
        project.ws.save()
        after = (mod_root / "units" / "infantry.txt").read_bytes().decode("cp1252")
        self.assertIn("mystery_thing = 42", after, "la clave desconocida no sobrevive")
        self.assertIn("# nota de campo propio", after, "el comentario no sobrevive")
        self.assertIn("maximum_speed = 5.00", after, "4.00 puesto a 5 no queda 5.00")
        reopened = entities.open(RecordRef("unit", "infantry"))
        self.assertIn("mystery_thing", [entry.key.text for entry in reopened.unknown()])


class MinigameTests(CriteriaCase):
    """Criterios 3, 4 y 5 (minijuego sintético)."""

    def test_criterion3_duplicate_unit(self):
        project, entities, loc = self.open_minigame()
        ref = entities.duplicate(RecordRef("unit", "infantry"), "my_unit")
        self.assertEqual(ref.ident, "my_unit")
        self.assertEqual(len(project.ws.history()), 1, "una sola transacción")
        handle = project.ws.peek(VPath("units/my_unit.txt"))
        self.assertIsNotNone(handle, "units/my_unit.txt no existe en el workspace")
        self.assertTrue(handle.is_new)
        self.assertIsNotNone(loc.entry("my_unit"), "falta la clave my_unit")
        self.assertIsNotNone(loc.entry("my_unit_short"), "falta la clave my_unit_short")
        project.ws.undo()
        self.assertEqual(project.ws.dirty(), [], "el deshacer no quita la duplicación")
        self.assertIsNone(project.ws.peek(VPath("units/my_unit.txt")))
        self.assertIsNone(loc.entry("my_unit"), "el deshacer no quita la clave my_unit")

    def test_criterion4_create_government(self):
        project, entities, loc = self.open_minigame()
        ref = entities.create("government", "junta", {"election": True},
                              texts={"junta": {"es": "Junta Militar", "en": "Military Junta"},
                                     "junta_ruler": {"es": "Gobernante", "en": "Ruler"}})
        self.assertEqual(ref.ident, "junta")
        self.assertEqual(len(project.ws.history()), 1, "una sola transacción")
        handle = project.ws.open("common/governments.txt")
        document = handle.model.document
        self.assertEqual(document.entries[-1].key.text, "junta", "junta no queda al final")
        writes = project.ws.changeset().writes
        self.assertTrue(any(w.rel.key == VPath("common/governments.txt").key
                            and w.action is WriteAction.COPY_FROM_GAME for w in writes),
                        "governments.txt no se copia del juego al mod")
        self.assertIsNotNone(loc.entry("junta"), "falta la clave junta")
        self.assertIsNotNone(loc.entry("junta_ruler"), "falta la clave junta_ruler")
        record = entities.open(ref)
        self.assertIn("government_election_without_duration",
                      [p.code for p in record.issues(self._ctx(entities))],
                      "election = yes sin duration no avisa")
        project.ws.undo()
        self.assertEqual(project.ws.dirty(), [], "el deshacer no quita la creación")
        self.assertIsNone(loc.entry("junta"), "el deshacer no quita la clave junta")

    def test_criterion5_delete_guarded(self):
        project, entities, loc = self.open_minigame()
        entities.duplicate(RecordRef("unit", "infantry"), "my_unit")
        dirty_before = [h.rel.key for h in project.ws.dirty()]
        with self.assertRaises(EntityInUseError) as caught:
            entities.delete(RecordRef("unit", "infantry"))
        self.assertTrue(any(use.role == "activate_unit" for use in caught.exception.uses),
                        "los usos no incluyen el activate_unit de la tecnología")
        self.assertEqual([h.rel.key for h in project.ws.dirty()], dirty_before,
                         "el borrado bloqueado cambia algo")
        entities.delete(RecordRef("unit", "my_unit"))
        self.assertEqual(len(project.ws.history()), 2, "duplicar y borrar: una transacción cada uno")
        self.assertIsNone(project.ws.peek(VPath("units/my_unit.txt")),
                          "el archivo nuevo borrado desaparece de la vista efectiva")
        self.assertIsNone(loc.entry("my_unit"), "el borrado no quita la clave my_unit")
        project.ws.undo()
        handle = project.ws.peek(VPath("units/my_unit.txt"))
        self.assertIsNotNone(handle, "el deshacer no devuelve my_unit")
        self.assertFalse(handle.deleted, "el deshacer no devuelve my_unit")


class It4CriteriaTests(CriteriaCase):
    """Criterios 1, 3, 6 y 7 de la iteración 4 (wizard §22) en el núcleo; los de la interfaz están en
    ``test_e2e_it4.py``."""

    @unittest.skipUnless(vanilla_root(), "sin corpus")
    def test_criterion1_all_schemas_conform_to_vanilla(self):
        project, entities, _, _ = self.open_vanilla()
        expected = {"government": 8, "casus_belli": 31, "bookmark": 2, "culture_group": 34, "culture": 226,
                    "unit": 21}
        counts = {}
        for kind in expected:
            summaries = entities.list(kind)
            counts[kind] = len(summaries)
            for summary in summaries:
                record = entities.open(summary.ref)
                for problem in record.issues(self._ctx(entities)):
                    self.assertNotIn(problem.code, ("unknown_field", "bad_type"),
                                     f"{kind}:{summary.ref.ident}: {problem.code} en {problem.field}")
                for key in record._index_schema()[0]:
                    record.get(key)
                for name in record._index_schema()[2]:
                    record.dynamic(name)
                record.children()
        self.assertEqual(counts, expected)
        self.assertEqual(project.ws.dirty(), [], "leer el corpus ensucia algún documento")
        self.assertTrue(project.ws.save().nothing_to_save, "abrir y leer el corpus escribe")

    def _my_cb_game(self):
        from _minigame import SCHEMA_GAME_FILES

        game_files = dict(SCHEMA_GAME_FILES)
        # Una guerra de inicio que ya usa el CB que se va a crear (como si viniera de otro mod).
        game_files["history/wars/Future War.txt"] = (
            'name = "Future War"\r\n1835.1.1 = {\r\n\tadd_attacker = AAA\r\n\tadd_defender = BBB\r\n'
            '\twar_goal = {\r\n\t\tcasus_belli = my_cb\r\n\t\tactor = AAA\r\n\t\treceiver = BBB\r\n\t}\r\n}\r\n')
        game = build_minigame(mod=True, game_files=game_files)
        self.addCleanup(game.cleanup)
        project = Project.open(game.game_root, game.mod_root)
        self.addCleanup(project.close, discard=True)
        index = build_index(project.vfs.snapshot(), None, {})
        loc = LocSync(project.ws, project.vfs, prefix=project.settings.prefix)
        return game, project, Entities(project.ws, index, loc), loc

    def test_criterion3_my_cb(self):
        game, project, entities, loc = self._my_cb_game()
        before = {rel: data for rel, data in game.tree(game.mod_root).items()}
        ref = entities.create("casus_belli", "my_cb")
        self.assertEqual(len(project.ws.history()), 1, "crear el CB es una sola transacción")
        cb_doc = project.ws.open("common/cb_types.txt").model.document
        order = [entry.value.text for entry in cb_doc.find("peace_order").value.entries]
        self.assertEqual(order[-1], "my_cb", "my_cb va al final de peace_order")
        self.assertEqual(order[:-1], ["conquer_land", "free_people", "humble_rival", "annex"])
        self.assertEqual(cb_doc.entries[-1].key.text, "my_cb", "el bloque va al final del archivo")
        target = VPath(f"localisation/00_{project.settings.prefix}_cb.csv")
        for key in ("my_cb", "my_cb_desc", "my_cb_setup", "my_cb_short"):
            entry = loc.entry(key)
            self.assertIsNotNone(entry, f"falta la clave {key}")
            self.assertEqual(entry.rel.key, target.key, f"{key} no está en {target}")
        self.assertEqual(entities.open(ref).issues(self._ctx(entities)), [], "my_cb nace sin problemas")
        # Borrarlo mientras se usa se bloquea y enseña los usos, sin cambiar nada.
        dirty = sorted(h.rel.key for h in project.ws.dirty())
        with self.assertRaises(EntityInUseError) as caught:
            entities.delete(ref)
        self.assertEqual([(use.rel.name, use.role) for use in caught.exception.uses],
                         [("Future War.txt", "casus_belli")], "el peace_order propio no cuenta como uso")
        self.assertEqual(sorted(h.rel.key for h in project.ws.dirty()), dirty)
        self.assertEqual(len(project.ws.history()), 1)
        # Un solo deshacer quita la creación entera: bloque, peace_order y las 4 claves.
        project.ws.undo()
        self.assertEqual(project.ws.dirty(), [])
        self.assertIsNone(loc.entry("my_cb"))
        self.assertNotIn("my_cb", [e.value.text for e in project.ws.open("common/cb_types.txt").model.document
                                   .find("peace_order").value.entries])
        # Rehacer y guardar: el CSV del mod lleva exactamente las 4 claves.
        project.ws.redo()
        self.assertTrue(project.ws.save().ok)
        csv = (game.mod_root / "localisation" / target.name).read_bytes().decode("cp1252")
        self.assertEqual([line.split(";")[0] for line in csv.splitlines() if line],
                         ["my_cb", "my_cb_desc", "my_cb_setup", "my_cb_short"])
        self.assertNotIn("common/cb_types.txt", before)

    def test_criterion6_event_modifier_touches_no_ui_file(self):
        """El esquema ``event_modifier`` no aparece en ningún archivo de ``ui/`` (su sección sale por descubrimiento)
        y su prueba es una subclase de 3 líneas."""
        import ast

        ui = PROJECT_ROOT / "src" / "vic2studio" / "ui"
        mentions = [path for path in ui.rglob("*.py") if "event_modifier" in path.read_text(encoding="utf-8")]
        self.assertEqual(mentions, [], "un archivo de ui/ nombra el esquema event_modifier")
        tree = ast.parse((PROJECT_ROOT / "tests" / "test_schema_event_modifier.py").read_text(encoding="utf-8"))
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        self.assertEqual(len(classes), 1)
        self.assertEqual(len(classes[0].body), 3, "la prueba del esquema es una subclase de 3 líneas")
        self.assertEqual(classes[0].body[-1].end_lineno - classes[0].lineno, 3)

    def test_criterion7_reference_is_complete_and_up_to_date(self):
        from vic2studio.core.schema.docgen import missing_keys

        for lang in ("es", "en"):
            self.assertEqual(missing_keys(lang), [], f"{lang}: la referencia tiene claves sin traducir")
        done = __import__("subprocess").run([sys.executable, str(PROJECT_ROOT / "tools" / "gen_reference.py"),
                                             "--check"], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, "docs/referencia no está al día: python tools/gen_reference.py\n"
                         + done.stdout + done.stderr)
        from vic2studio.core.schema import registry

        for lang in ("es", "en"):
            names = {path.name for path in (PROJECT_ROOT / "docs" / "referencia" / lang).glob("*.md")}
            self.assertEqual(names, {f"{s.kind}.md" for s in registry.all_schemas()} | {"README.md"})


class DuplicateCompanionTests(CriteriaCase):
    """Corrección M1: duplicate pasa por los compañeros (la matriz de rebeldes)."""

    @staticmethod
    def _rebel_tables(project) -> list:
        handle = project.ws.open("common/rebel_types.txt")
        document = handle.model.document
        tables = []

        def walk(block):
            for entry in block.entries:
                if entry.key is not None and entry.key.text == "government" \
                        and hasattr(entry.value, "entries"):
                    tables.append(entry.value)
                if hasattr(entry.value, "entries"):
                    walk(entry.value)

        walk(document)
        return tables

    def test_duplicate_government_fills_the_rebel_tables(self):
        """Minijuego: las dos tablas ganan la clave, en la misma transacción, y el deshacer
        lo quita todo."""
        project, entities, loc = self.open_minigame()
        entities.duplicate(RecordRef("government", "republic"), "republic2")
        tables = self._rebel_tables(project)
        self.assertEqual(len(tables), 2)
        for table in tables:
            self.assertIsNotNone(table.find("republic2"),
                                 "el duplicado no está en todas las tablas")
        self.assertEqual(len(project.ws.history()), 1, "una sola transacción")
        project.ws.undo()
        self.assertEqual(project.ws.dirty(), [], "el deshacer no quita la duplicación")
        tables = self._rebel_tables(project)
        for table in tables:
            self.assertIsNone(table.find("republic2"))

    @unittest.skipUnless(vanilla_root(), "sin corpus")
    def test_duplicate_democracy_fills_all_14_tables(self):
        project, entities, _, _ = self.open_vanilla()
        entities.duplicate(RecordRef("government", "democracy"), "democracia2")
        tables = self._rebel_tables(project)
        self.assertEqual(len(tables), 14, "vanilla tiene 14 tablas de rebeldes (H16)")
        for table in tables:
            self.assertIsNotNone(table.find("democracia2"),
                                 "el duplicado no está en las 14 tablas")
        self.assertEqual(len(project.ws.history()), 1)
        project.ws.undo()
        self.assertEqual(project.ws.dirty(), [], "el deshacer no quita la duplicación")

    @unittest.skipUnless(vanilla_root(), "sin corpus")
    def test_duplicate_keeps_the_source_format(self):
        """Corrección M2: el bloque duplicado es el del origen byte a byte, salvo la clave:
        las líneas en blanco entre campos (``fascist = yes`` y ``election = yes`` en
        ``democracy``) se conservan."""
        project, entities, _, mod_root = self.open_vanilla()
        entities.duplicate(RecordRef("government", "democracy"), "democracia2")
        project.ws.save()
        data = (mod_root / "common" / "governments.txt").read_bytes().decode("cp1252")

        def block_text(ident: str) -> str:
            start = data.index(f"{ident} = {{")
            end = data.index("\n}", start) + 2
            return data[start:end]

        self.assertEqual(block_text("democracia2"), block_text("democracy").replace(
            "democracy = {", "democracia2 = {", 1),
            "el duplicado no conserva el formato del origen")


class GapTests(CriteriaCase):
    """Huecos de la revisión: comentario de línea, vistas land/naval y bad_type."""

    def test_line_comment_survives_set_of_another_field(self):
        """Un comentario al final de la línea sobrevive a ``set`` de otro campo (el caso real
        de VSM ``election = yes  # election = no``, H14)."""
        from vic2studio.core.project.codecs import codec_for

        project, entities, loc = self.open_minigame()
        handle = project.ws.open("common/governments.txt")
        original = codec_for(handle.kind).snapshot(handle.model)
        edited = original.replace(b"council = {\r\n\tsocialist = yes\r\n\telection = yes\r\n",
                                  b"council = {\r\n\tsocialist = yes\r\n"
                                  b"\telection = yes  # election = no\r\n", 1)
        with project.ws.transaction("test.undo_edit", rel="common/governments.txt"):
            project.ws.replace_text(handle, edited)
        record = entities.open(RecordRef("government", "council"))
        with project.ws.transaction("test.undo_edit", key="duration", ident="council"):
            record.set("duration", 48)
        rendered = codec_for(handle.kind).snapshot(handle.model).decode("cp1252")
        self.assertIn("election = yes  # election = no", rendered,
                      "el comentario de la línea no sobrevive al set")
        self.assertIn("\tduration = 48", rendered, "el set no escribió el campo")
        project.ws.undo()

    def test_line_comment_survives_set_of_an_existing_field(self):
        """Como la anterior, pero cambiando un campo que ya está: el valor se reescribe en su sitio y
        el comentario de la línea vecina queda igual (revisión de la corrección)."""
        from vic2studio.core.project.codecs import codec_for

        project, entities, loc = self.open_minigame()
        handle = project.ws.open("common/governments.txt")
        original = codec_for(handle.kind).snapshot(handle.model)
        edited = original.replace(b"council = {\r\n\tsocialist = yes\r\n\telection = yes\r\n",
                                  b"council = {\r\n\tsocialist = yes\r\n"
                                  b"\telection = yes  # election = no\r\n", 1)
        self.assertNotEqual(edited, original, "el minijuego ya no tiene ese gobierno")
        with project.ws.transaction("test.undo_edit", rel="common/governments.txt"):
            project.ws.replace_text(handle, edited)
        record = entities.open(RecordRef("government", "council"))
        with project.ws.transaction("test.undo_edit", key="appoint_ruling_party", ident="council"):
            record.set("appoint_ruling_party", not record.get("appoint_ruling_party"))
        rendered = codec_for(handle.kind).snapshot(handle.model).decode("cp1252")
        self.assertIn("election = yes  # election = no", rendered,
                      "el comentario de la línea no sobrevive al set de un campo existente")

    def test_new_records_report_their_own_lines(self):
        """Tras ``duplicate`` y ``create``, las líneas del CST del registro nuevo son las del archivo:
        los problemas e «ir al código» no señalan otro registro (revisión de la corrección)."""
        from vic2studio.core.project.codecs import codec_for

        project, entities, loc = self.open_minigame()
        entities.duplicate(RecordRef("government", "council"), "council2")
        entities.duplicate(RecordRef("unit", "infantry"), "my_unit")
        entities.create("government", "junta", {"election": False, "appoint_ruling_party": True,
                                                 "ideology": {"conservative": True}})
        for ref in (RecordRef("government", "council2"), RecordRef("unit", "my_unit"),
                    RecordRef("government", "junta")):
            record = entities.open(ref)
            lines = codec_for(record.handle.kind).snapshot(record.handle.model).split(b"\n")
            for entry in record.block.entries:
                if entry.key is None:
                    continue
                with self.subTest(ref=ref.ident, key=entry.key.text):
                    self.assertIsNotNone(entry.line)
                    self.assertTrue(lines[entry.line - 1].lstrip().startswith(entry.key.text.encode()),
                                    (entry.line, lines[entry.line - 1]))

    @unittest.skipUnless(vanilla_root(), "sin corpus")
    def test_vanilla_views_are_11_land_and_10_naval(self):
        project, entities, _, _ = self.open_vanilla()
        land = entities.list("unit", view="land")
        naval = entities.list("unit", view="naval")
        self.assertEqual(len(land), 11, "11 unidades terrestres en vanilla")
        self.assertEqual(len(naval), 10, "10 unidades navales en vanilla")
        self.assertFalse({s.ref.ident for s in land} & {s.ref.ident for s in naval},
                         "ninguna unidad está en las dos vistas")

    def test_bad_type_is_reported(self):
        project, entities, loc = self.open_minigame()
        record = entities.open(RecordRef("unit", "infantry"))
        with project.ws.transaction("test.undo_edit", key="attack", ident="infantry"):
            record.block.append("attack", "abc")
        reopened = entities.open(RecordRef("unit", "infantry"))
        problems = {problem.code: problem.field for problem in reopened.issues()}
        self.assertIn("bad_type", problems, "attack = abc no da bad_type")
        self.assertEqual(problems["bad_type"], ("attack",))
        project.ws.undo()


if __name__ == "__main__":
    unittest.main()
