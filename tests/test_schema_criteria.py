"""Los 6 criterios del encargo del motor (ENCARGO_MOTOR.md, fase 3).

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


if __name__ == "__main__":
    unittest.main()
