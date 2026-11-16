"""Taller de mapas, nivel «Mundo» (wizard §18.1 y §18.3, pasos 12–17; iteración 9b): países, culturas, grupos
culturales y banderas nuevas, y su exportación con la receta de países de la iteración 6.

El núcleo va con mundos inventados de 576×288 (``_mapforge_fixtures``); la exportación, contra el minijuego del mapa
abierto como proyecto en una carpeta temporal (nunca contra un mod de verdad)."""

from __future__ import annotations

import io
import unittest

import numpy as np
from PIL import Image

from _layers import isolate_appdirs
from _mapforge_fixtures import tiny_install, tiny_params
from _minigame import build_map_minigame
from vic2studio.core.domain.tags import check_tag
from vic2studio.core.gfx.flags import FLAG_SIZE, FLAG_SUFFIXES, procedural_flag, procedural_flag_set
from vic2studio.core.mapforge import export as ex, install, nations, pipeline
from vic2studio.core.mapforge.params import Level

INSTALL_TAGS = {"AAA", "BBB", "CCC"}


def world_of(seed: int = 3, countries: int = 8, groups: int = 3, install_profile=None):
    params = tiny_params(seed=seed, level=Level.WORLD, countries=countries, culture_groups=groups)
    return pipeline.run_all(params, install_profile if install_profile is not None else tiny_install())


class WorldPropertyTests(unittest.TestCase):
    def test_every_land_province_has_a_new_country_and_capitals_are_their_own(self):
        for seed in (1, 3, 5):
            with self.subTest(seed=seed):
                w = world_of(seed)
                r = w.raster
                owners = w.entities["owners"]
                land = r.owner[1:r.land_count + 1]
                self.assertTrue((land >= 0).all(), "«Mundo» reparte toda la tierra")
                self.assertTrue((r.owner[r.land_count + 1:] < 0).all(), "el mar no tiene dueño")
                self.assertEqual(len(owners), len(w.entities["world"]["countries"]))
                for k, cap in enumerate(r.capitals):
                    self.assertTrue(1 <= cap <= r.land_count, (k, cap))
                    self.assertEqual(int(r.owner[cap]), k, "la capital es del propio país")
                # Cada país tiene tierra y una cultura propia; cada provincia, una religión de la instalación.
                self.assertEqual(set(np.unique(land).tolist()), set(range(len(owners))))
                self.assertTrue(set(w.entities["religions"]) <= {"fe_a", "fe_b"})

    def test_tags_are_valid_free_and_unique(self):
        w = world_of(3, countries=12)
        tags = w.entities["owners"]
        self.assertEqual(len(set(tags)), len(tags))
        for tag in tags:
            self.assertTrue(check_tag(tag, INSTALL_TAGS).ok, tag)
        self.assertEqual({c["tag"] for c in w.entities["world"]["countries"]}, set(tags))

    def test_names_cultures_and_groups(self):
        w = world_of(5, countries=6, groups=2)
        data = w.entities["world"]
        self.assertEqual(len(data["groups"]), 2)
        keys = [c["key"] for c in data["cultures"]] + [g["key"] for g in data["groups"]]
        self.assertEqual(len(set(keys)), len(keys), "claves de cultura y de grupo sin repetir")
        for key in keys:
            self.assertRegex(key, r"^[a-z][a-z0-9_]*$")
        for c in data["cultures"]:
            self.assertGreaterEqual(len(c["first_names"]), 50)
            self.assertGreaterEqual(len(c["last_names"]), 50)
            self.assertIn(c["group"], range(2))
        for country in data["countries"]:
            for text in (country["name"], country["adjective"]):
                text.encode("cp1252")
        self.assertEqual(w.entities["cultures"], [c["key"] for c in data["cultures"]])
        block = nations.cultures_block(w, "\r\n")
        for c in data["cultures"]:
            self.assertIn(f"\t{c['key']} = {{", block)
        self.assertEqual(block.count("{"), block.count("}"))

    def test_civilized_share(self):
        w = world_of(3, countries=10)
        civ = w.entities["civilized"]
        self.assertEqual(sum(civ), 5, "la mitad (civilized_fraction = 0.5), los más grandes")
        r = w.raster
        size = np.bincount(r.owner[1:r.land_count + 1], minlength=len(civ))
        self.assertGreaterEqual(min(size[i] for i in range(len(civ)) if civ[i]),
                                max(size[i] for i in range(len(civ)) if not civ[i]))

    def test_same_seed_same_world_and_map_level_untouched(self):
        a, b = world_of(7), world_of(7)
        self.assertEqual(a.entities["owners"], b.entities["owners"])
        self.assertEqual(a.entities["world"]["cultures"][0]["first_names"],
                         b.entities["world"]["cultures"][0]["first_names"])
        self.assertTrue(np.array_equal(a.raster.ids, b.raster.ids))
        plain = pipeline.run_all(tiny_params(seed=7), tiny_install())
        self.assertNotIn("world", plain.entities)
        self.assertTrue(set(plain.entities["owners"]) <= INSTALL_TAGS)
        self.assertTrue(np.array_equal(plain.raster.ids, a.raster.ids), "el nivel no cambia las provincias")

    def test_regenerating_the_countries_leaves_the_map_files_alone(self):
        """Criterio 3: regenerar desde los dueños no cambia ningún archivo de ``map/`` (sha), y los pasos de
        dueños, economía y nombres tardan poco."""
        import hashlib
        import time

        w = world_of(4)
        files, _ = ex.render_files(w, ex.ExportInputs(prefix="FRG"))
        t = time.perf_counter()
        again = pipeline.run_cells(w.evolve(params=w.params.with_(countries=5, culture_groups=2)), from_step="owners")
        seconds = time.perf_counter() - t
        again = pipeline.run_raster(again, scale=1)
        files2, _ = ex.render_files(again, ex.ExportInputs(prefix="FRG"))
        self.assertEqual(len(again.entities["owners"]), 5)
        self.assertNotEqual(again.entities["owners"],
                            w.entities["owners"])
        for rel in sorted(k for k in files if k.startswith("map/")):
            self.assertEqual(hashlib.sha256(files[rel]).hexdigest(), hashlib.sha256(files2[rel]).hexdigest(), rel)
        self.assertLess(seconds, 3.0)

    def test_retag_moves_a_taken_tag(self):
        w = world_of(3)
        first = w.entities["owners"][0]
        moved, changes = nations.retag(w, {first})
        self.assertIn(first, changes)
        new = changes[first]
        self.assertNotIn(new, w.entities["owners"])
        self.assertEqual(moved.entities["owners"][0], new)
        self.assertEqual(moved.entities["world"]["countries"][0]["tag"], new)
        same, none = nations.retag(w, set())
        self.assertIs(same, w)
        self.assertEqual(none, {})


class FlagTests(unittest.TestCase):
    def test_flags_are_valid_tga_and_the_five_differ(self):
        colors = ((200, 30, 30), (240, 240, 240), (20, 60, 160))
        flags = procedural_flag_set(42, colors)
        self.assertEqual(set(flags), set(FLAG_SUFFIXES))
        images = {}
        for suffix, data in flags.items():
            img = Image.open(io.BytesIO(data))
            self.assertEqual(img.format, "TGA")
            self.assertEqual(img.size, FLAG_SIZE)
            images[suffix] = np.asarray(img.convert("RGB"))
        distinct = {img.tobytes() for img in images.values()}
        self.assertEqual(len(distinct), len(FLAG_SUFFIXES), "una bandera distinta por gobierno")
        self.assertEqual(procedural_flag(42, colors).tobytes(), procedural_flag(42, colors).tobytes())
        self.assertNotEqual(procedural_flag(42, colors).tobytes(), procedural_flag(43, colors).tobytes())


class WorldExportTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)
        from vic2studio.core.domain.country import DomainContext
        from vic2studio.core.index import build_index
        from vic2studio.core.locsync import LocSync
        from vic2studio.core.project.project import Project
        from vic2studio.core.rules.game import GameRules
        from vic2studio.core.schema import Entities

        self.game = build_map_minigame(clean=True)
        self.addCleanup(self.game.cleanup)
        p = Project.open(self.game.game_root, self.game.mod_root)
        self.project = p
        self.addCleanup(lambda: self.project.close(discard=True))
        snap = p.vfs.snapshot()
        self.index = build_index(snap, None)
        loc = LocSync(p.ws, p.vfs, prefix=p.settings.prefix)
        self.domain = DomainContext(p.ws, p.vfs, self.index, loc, Entities(p.ws, self.index, loc),
                                    GameRules.from_snapshot(snap), p.settings)
        self.profile = install.learn_install(install.source_from_vfs(p.vfs))

    def problems(self, project):
        from vic2studio.core.index import build_index
        from vic2studio.core.validate import Validator, build_context

        snap = project.vfs.snapshot()
        index = build_index(snap, None)
        report = Validator(build_context(snap, index)).validate()
        return index, {(x.code, str(x.rel), str(x.args)) for x in report.problems if x.severity.name == "ERROR"}

    def test_export_creates_countries_cultures_and_flags_in_one_transaction(self):
        from vic2studio.core.index import model as m
        from vic2studio.core.project.project import Project

        p = self.project
        _, before = self.problems(p)
        w = world_of(3, countries=5, groups=2, install_profile=self.profile)
        inputs = ex.gather_inputs(p, w, index=self.index)
        self.assertTrue({"AAA", "BBB"} <= set(inputs.taken_tags))
        files, report = ex.render_files(w, inputs)
        self.assertEqual(report["new_countries"], 5)
        tags = w.entities["owners"]
        hist = b"".join(v for k, v in files.items() if k.startswith("history/provinces/"))
        for tag in tags:
            self.assertIn(f"owner = {tag}".encode(), hist)
        plan = ex.export_plan(files, inputs, lambda rel: p.vfs.resolve(rel) is not None, world=w)
        planned = {f.rel for f in plan}
        self.assertIn("common/cultures.txt", planned)
        for tag in tags:
            self.assertIn(f"gfx/flags/{tag}_monarchy.tga", planned)
        touched = ex.apply_export(p, files, inputs, world=w, domain=self.domain)
        for rel in ("common/countries.txt", "common/cultures.txt", "map/provinces.bmp"):
            self.assertIn(rel, touched)
        self.assertEqual(sum(1 for t in touched if t.startswith("gfx/flags/")), 5 * len(FLAG_SUFFIXES))
        # Un solo deshacer quita la exportación entera, países incluidos.
        step = p.ws.undo()
        self.assertEqual(step.label, ex.UNDO_EXPORT)
        self.assertFalse(p.ws.can_undo())
        p.ws.redo()
        p.save()
        p.close()
        self.project = Project.open(self.game.game_root, self.game.mod_root)
        index, after = self.problems(self.project)
        self.assertTrue(set(tags) <= set(index.names(m.KIND_TAG)))
        self.assertTrue(set(tags) <= set(index.names(m.KIND_COUNTRY_HISTORY)))
        cultures = set(index.names(m.KIND_CULTURE))
        for c in w.entities["world"]["cultures"]:
            self.assertIn(c["key"], cultures)
        # Ningún error nuevo, salvo los tipos de POP que el minijuego no define (igual que en «Solo mapa»).
        new = {x for x in after - before if x[0] != "pop_type_unknown"}
        self.assertEqual(new, set())

    def test_a_tag_taken_after_generating_is_moved_on_export(self):
        p = self.project
        w = world_of(3, countries=4, install_profile=self.profile)
        first = w.entities["owners"][0]
        inputs = ex.gather_inputs(p, w, index=self.index)
        inputs.taken_tags = sorted(set(inputs.taken_tags) | {first})
        files, report = ex.render_files(w, inputs)
        self.assertIn(first, report["retagged"])
        new = report["retagged"][first]
        hist = b"".join(v for k, v in files.items() if k.startswith("history/provinces/"))
        self.assertNotIn(f"owner = {first}\r\n".encode(), hist)
        self.assertIn(f"owner = {new}".encode(), hist)

    def test_overlay_is_not_exported(self):
        w = pipeline.run_all(tiny_params(level=Level.OVERLAY), tiny_install())
        with self.assertRaises(NotImplementedError):
            ex.render_files(w, ex.ExportInputs(prefix="FRG"))


if __name__ == "__main__":
    unittest.main()
