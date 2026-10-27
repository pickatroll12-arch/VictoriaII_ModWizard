"""Vista efectiva de la localización (wizard §8, I7): lo que vería el juego, con los cambios sin guardar.

``LocSync.entries``/``text``/``localisation_db`` sobre el ``Project`` real y el minijuego: documentos sin guardar
(también los nuevos), un CSV del mod que sustituye al del juego con el mismo nombre (sin distinguir mayúsculas),
un CSV del mod borrado (vuelve a verse el del juego), ``replace_path = "localisation"``, el orden de carga por
nombre y que editar una clave del juego nunca copia su CSV.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import descriptor_bytes, isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402
from test_locsync import OTHER_GAME_CSVS, only_minigame_csv  # noqa: E402

from vic2studio.core.csvloc.serialization import parse_csv  # noqa: E402
from vic2studio.core.locsync import LocSync  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.vfs import LayerKind, VPath  # noqa: E402

LABEL = "pending.undo_revert"


class EffectiveCase(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def open(self, *, mod: bool = True, mod_files=None, game_files=None, replace_localisation: bool = False):
        self.game = build_minigame(mod=mod, mod_files=mod_files, game_files=only_minigame_csv(game_files))
        self.addCleanup(self.game.cleanup)
        if replace_localisation:
            self.game.descriptor.write_bytes(descriptor_bytes("TestMod", "TestMod", "TestMod",
                                                              replace_paths=("localisation",)))
        self.project = Project.open(self.game.game_root, self.game.mod_root)
        self.addCleanup(self.project.close, discard=True)
        self.loc = LocSync(self.project.ws, self.project.vfs, prefix=self.project.settings.prefix)
        return self.loc

    def keys(self) -> list[str]:
        return [entry.key for entry in self.loc.entries()]


class EffectiveViewTests(EffectiveCase):
    def test_an_unsaved_edit_of_a_csv_document_is_visible(self):
        loc = self.open()
        ws = self.project.ws
        with self.project.edit(LABEL, name="x"):
            handle = ws.open("localisation/00_TST_decisions.csv")
            ws.touch(handle)
            handle.model.set("tst_reform", "es", "Reforma sin guardar")
            handle.model.add_row("tst_extra", {"en": "Extra"})
        self.assertEqual(loc.text("tst_reform", "es"), "Reforma sin guardar")
        self.assertIn("tst_extra", self.keys())
        entry = loc.entry("tst_extra")
        self.assertIs(entry.layer, LayerKind.MOD)
        self.assertEqual(entry.line, 2, "la línea es la posición actual de la fila")
        ws.undo()
        self.assertEqual(loc.text("tst_reform", "es"), "Reforma")
        self.assertNotIn("tst_extra", self.keys())

    def test_a_new_unsaved_file_is_part_of_the_effective_database(self):
        loc = self.open(mod=False)
        with self.project.edit(LABEL, name="x"):
            loc.ensure({"NEW": {"en": "New"}}, area="misc")
        db = loc.localisation_db()
        path, line = db.source_of("NEW")
        self.assertEqual(path, self.project.vfs.mod_target("localisation/00_TESTMOD_misc.csv"))
        self.assertEqual(line, 1)
        self.assertFalse(path.exists(), "sin guardar: aún no está en el disco")
        self.assertEqual(db.lookup("NEW"), "New")
        self.assertEqual(loc.where("NEW"), (VPath.of("localisation/00_TESTMOD_misc.csv"), 1))

    def test_a_mod_csv_with_the_name_of_a_game_csv_replaces_it_whatever_the_case(self):
        loc = self.open(mod=False, mod_files={"localisation/MINIGAME.CSV": "conquer_land;Take land;;;;Tomar;;;;;;;;x\r\n"})
        self.assertEqual(self.keys(), ["conquer_land"], "el CSV del juego entero queda sustituido")
        entry = loc.entry("conquer_land")
        self.assertIs(entry.layer, LayerKind.MOD)
        self.assertTrue(entry.overrides_game)
        self.assertEqual(loc.text("conquer_land", "es"), "Tomar")
        self.assertIsNone(loc.text("free_people"), "ya no la carga nadie")

    def test_a_deleted_mod_csv_lets_the_game_csv_be_seen_again(self):
        loc = self.open(mod=False, mod_files={"localisation/minigame.csv": "conquer_land;Take land;;;;;;;;;;;;x\r\n"})
        with self.project.edit(LABEL, name="x"):
            self.project.ws.delete("localisation/minigame.csv")
        self.assertEqual(self.keys(), ["conquer_land", "free_people", "humble_rival"])
        self.assertIs(loc.entry("free_people").layer, LayerKind.GAME)
        self.project.ws.undo()
        self.assertEqual(self.keys(), ["conquer_land"])

    def test_replace_path_localisation_hides_every_game_csv(self):
        loc = self.open(replace_localisation=True)
        self.assertEqual(self.keys(), ["tst_reform"])
        self.assertFalse(loc.entry("tst_reform").overrides_game)
        self.assertEqual(loc.disk_entries(missing_only=False)[0].layer.kind, LayerKind.MOD)

    def test_files_load_in_alphabetical_order_and_the_first_key_wins(self):
        loc = self.open(mod=False, mod_files={
            "localisation/zz_late.csv": "free_people;Late;;;;Tarde;;;;;;;;x\r\n",
            "localisation/00_early.csv": "humble_rival;Early;;;;Pronto;;;;;;;;x\r\n",
        })
        self.assertEqual(loc.text("humble_rival", "es"), "Pronto", "00_early carga antes que minigame")
        self.assertEqual(loc.text("free_people", "es"), "Liberar", "minigame carga antes que zz_late")
        self.assertEqual(self.keys()[0], "humble_rival")
        db = loc.localisation_db()
        others = {VPath.of(rel).name for rel in OTHER_GAME_CSVS}
        self.assertEqual([f.path.name for f in db.files if f.path.name not in others],
                         ["00_early.csv", "minigame.csv", "zz_late.csv"])

    def test_editing_a_game_key_never_copies_its_csv(self):
        loc = self.open(mod=False)
        for key in ("conquer_land", "free_people", "humble_rival"):
            with self.project.edit(LABEL, name=key):
                loc.set_text(key, "es", key.upper())
        self.assertEqual([str(w.rel) for w in self.project.ws.changeset().writes],
                         ["localisation/00_TESTMOD_overrides.csv"])
        self.assertEqual([loc.text(k, "es") for k in ("conquer_land", "free_people", "humble_rival")],
                         ["CONQUER_LAND", "FREE_PEOPLE", "HUMBLE_RIVAL"])
        rows = parse_csv(self.project.ws.changeset().writes[0].data.decode("cp1252"))
        self.assertEqual(rows.keys(), ["conquer_land", "free_people", "humble_rival"])

    def test_the_view_follows_undo_and_redo(self):
        loc = self.open()
        before = [(e.key, dict(e.texts), str(e.rel), e.line, e.layer) for e in loc.entries()]
        with self.project.edit(LABEL, name="x"):
            loc.set_text("conquer_land", "es", "Conquista")
        after = [(e.key, dict(e.texts), str(e.rel), e.line, e.layer) for e in loc.entries()]
        self.assertNotEqual(before, after)
        self.project.ws.undo()
        self.assertEqual([(e.key, dict(e.texts), str(e.rel), e.line, e.layer) for e in loc.entries()], before)
        self.project.ws.redo()
        self.assertEqual([(e.key, dict(e.texts), str(e.rel), e.line, e.layer) for e in loc.entries()], after)

    def test_after_saving_the_view_is_the_same(self):
        loc = self.open(mod=False)
        with self.project.edit(LABEL, name="x"):
            loc.set_text("free_people", "es", "Libres")
        before = [(e.key, dict(e.texts), str(e.rel), e.layer) for e in loc.entries()]
        self.assertTrue(self.project.save().ok)
        self.assertEqual([(e.key, dict(e.texts), str(e.rel), e.layer) for e in loc.entries()], before)
        self.assertTrue((self.game.mod_root / "localisation" / "00_TESTMOD_overrides.csv").is_file())


if __name__ == "__main__":
    unittest.main()
