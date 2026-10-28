"""Vista efectiva de ``Entities.list`` y de la comprobación de ids (corrección B1, I7).

Los documentos abiertos con cambios ganan sobre el índice: lo creado sin guardar sale, un
segundo ``create``/``duplicate`` con el mismo id lanza ``InvalidIdentError("taken")`` sin
cambiar nada, borrar y deshacer lo quita y lo devuelve a la lista, y ``ws.delete`` de un
archivo del mod lo quita. Los cuatro casos se prueban con ``unit`` (OnePerFile) y con
``government`` (SingleFile).
"""

from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
if str(PROJECT_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from vic2studio.core.schema import Entities, InvalidIdentError, RecordRef  # noqa: E402
from vic2studio.core.vfs.paths import VPath  # noqa: E402

from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402


class EffectiveViewCase(unittest.TestCase):
    """Andamiaje: minijuego con el índice del momento y las entidades encima."""

    def setUp(self):
        isolate_appdirs(self)
        game = build_minigame(mod=True)
        self.addCleanup(game.cleanup)
        from vic2studio.core.index.builder import build_index
        from vic2studio.core.locsync import LocSync
        from vic2studio.core.project import Project

        self.project = Project.open(game.game_root, game.mod_root)
        self.addCleanup(self.project.close, discard=True)
        self._build_index = build_index
        self.entities = Entities(self.project.ws,
                                 build_index(self.project.vfs.snapshot(), None, {}),
                                 LocSync(self.project.ws, self.project.vfs,
                                         prefix=self.project.settings.prefix))

    def refresh_index(self):
        """El índice tras guardar (la Session lo reextrae en producción; aquí, a mano)."""
        self.entities.index = self._build_index(self.project.vfs.snapshot(), None, {})

    def idents(self, kind: str) -> list[str]:
        return [summary.ref.ident for summary in self.entities.list(kind)]


class UnitEffectiveTests(EffectiveViewCase):
    """Los cuatro casos con ``unit`` (OnePerFile)."""

    def test_duplicate_without_saving_shows_in_list(self):
        self.assertNotIn("my_unit", self.idents("unit"))
        self.entities.duplicate(RecordRef("unit", "infantry"), "my_unit")
        self.assertIn("my_unit", self.idents("unit"))

    def test_second_duplicate_with_same_id_fails_without_effects(self):
        self.entities.duplicate(RecordRef("unit", "infantry"), "my_unit")
        dirty = [handle.rel.key for handle in self.project.ws.dirty()]
        history = len(self.project.ws.history())
        with self.assertRaises(InvalidIdentError) as caught:
            self.entities.duplicate(RecordRef("unit", "infantry"), "my_unit")
        self.assertEqual(caught.exception.code, "taken")
        with self.assertRaises(InvalidIdentError):
            self.entities.create("unit", "my_unit", {"type": "land"})
        self.assertEqual([handle.rel.key for handle in self.project.ws.dirty()], dirty,
                         "el id ocupado cambia documentos")
        self.assertEqual(len(self.project.ws.history()), history, "el id ocupado apila deshacer")

    def test_delete_and_undo_return_it_to_the_list(self):
        self.entities.duplicate(RecordRef("unit", "infantry"), "my_unit")
        self.entities.delete(RecordRef("unit", "my_unit"))
        self.assertNotIn("my_unit", self.idents("unit"))
        self.project.ws.undo()
        self.assertIn("my_unit", self.idents("unit"))

    def test_ws_delete_of_a_mod_unit_file_removes_it_from_the_list(self):
        self.entities.duplicate(RecordRef("unit", "infantry"), "my_unit")
        self.project.ws.save()
        self.refresh_index()
        self.assertIn("my_unit", self.idents("unit"))
        with self.project.ws.transaction("test.undo_delete", rel="units/my_unit.txt"):
            self.project.ws.delete(VPath("units/my_unit.txt"))
        self.assertNotIn("my_unit", self.idents("unit"))
        self.project.ws.undo()
        self.assertIn("my_unit", self.idents("unit"))


class GovernmentEffectiveTests(EffectiveViewCase):
    """Los cuatro casos con ``government`` (SingleFile)."""

    def test_duplicate_without_saving_shows_in_list(self):
        self.assertNotIn("republic2", self.idents("government"))
        self.entities.duplicate(RecordRef("government", "republic"), "republic2")
        self.assertIn("republic2", self.idents("government"))

    def test_second_duplicate_with_same_id_fails_without_effects(self):
        self.entities.duplicate(RecordRef("government", "republic"), "republic2")
        dirty = [handle.rel.key for handle in self.project.ws.dirty()]
        history = len(self.project.ws.history())
        with self.assertRaises(InvalidIdentError) as caught:
            self.entities.duplicate(RecordRef("government", "republic"), "republic2")
        self.assertEqual(caught.exception.code, "taken")
        with self.assertRaises(InvalidIdentError):
            self.entities.create("government", "republic2", {"election": False})
        self.assertEqual([handle.rel.key for handle in self.project.ws.dirty()], dirty)
        self.assertEqual(len(self.project.ws.history()), history)

    def test_delete_and_undo_return_it_to_the_list(self):
        self.entities.duplicate(RecordRef("government", "republic"), "republic2")
        self.entities.delete(RecordRef("government", "republic2"))
        self.assertNotIn("republic2", self.idents("government"))
        self.project.ws.undo()
        self.assertIn("republic2", self.idents("government"))

    def test_ws_delete_of_the_mod_governments_file_removes_it_from_the_list(self):
        self.entities.duplicate(RecordRef("government", "republic"), "republic2")
        self.project.ws.save()
        self.refresh_index()
        self.assertIn("republic2", self.idents("government"))
        with self.project.ws.transaction("test.undo_delete", rel="common/governments.txt"):
            self.project.ws.delete(VPath("common/governments.txt"))
        self.assertEqual(self.idents("government"), [], "el archivo borrado no aporta gobiernos")
        self.project.ws.undo()
        self.assertIn("republic2", self.idents("government"))


if __name__ == "__main__":
    unittest.main()
