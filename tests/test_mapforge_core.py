"""Taller de mapas, núcleo (wizard §18 y §19, iteración 9a): determinismo, propiedades del mapa, ediciones,
persistencia, problemas y textos. Todo con mundos inventados de 576×288 (``_mapforge_fixtures``)."""

from __future__ import annotations

import pickle
import unittest

import numpy as np

from _mapforge_fixtures import tiny_install, tiny_params, tiny_world
from vic2studio.core.mapforge import edits, pipeline
from vic2studio.core.mapforge.data.templates import FMG_TEMPLATES, TEMPLATES
from vic2studio.core.mapforge.imports import fmg_template
from vic2studio.core.mapforge.params import ForgeParams, Owners
from vic2studio.core.mapforge.project import MapForgeProject, pack_arrays, unpack_arrays
from vic2studio.core.mapforge.reconcile import run_components
from vic2studio.core.mapforge.validate import CODES, ForgeIssue, fix_params, world_issues
from vic2studio.core.texts import load_texts


class DeterminismTests(unittest.TestCase):
    def test_same_seed_same_world(self):
        a = pipeline.run_all(tiny_params(seed=11), tiny_install())
        b = pipeline.run_all(tiny_params(seed=11), tiny_install())
        self.assertEqual(a.cells_digest(), b.cells_digest())
        self.assertEqual(a.world_digest(), b.world_digest())
        self.assertTrue(np.array_equal(a.raster.ids, b.raster.ids))
        self.assertTrue(np.array_equal(a.raster.terrain, b.raster.terrain))
        self.assertTrue(np.array_equal(a.raster.rivers, b.raster.rivers))

    def test_other_seed_other_world(self):
        a = tiny_world(3)
        b = tiny_world(4)
        self.assertNotEqual(a.cells_digest(), b.cells_digest())

    def test_one_rng_per_step(self):
        """Regenerar los nombres no cambia el relieve ni las provincias (un PRNG por paso)."""
        w = tiny_world(3)
        again = pipeline.run_cells(w, from_step="names")
        self.assertTrue(np.array_equal(again.cells.h, w.cells.h))
        self.assertTrue(np.array_equal(again.cells.province0, w.cells.province0))
        self.assertEqual(again.entities["province_names"], w.entities["province_names"])

    def test_world_pickles(self):
        w = tiny_world(3)
        w2 = pickle.loads(pickle.dumps(w))
        self.assertEqual(w.world_digest(), w2.world_digest())
        p2 = pickle.loads(pickle.dumps(w.params))
        self.assertEqual(p2, w.params)


class MapPropertyTests(unittest.TestCase):
    """Lo que el juego exige del mapa (§16.6), sobre varias plantillas y semillas."""

    CASES = (("continents", 3), ("archipelago", 5), ("pangea", 7), ("volcano", 9))

    def test_properties(self):
        for template, seed in self.CASES:
            with self.subTest(template=template, seed=seed):
                w = tiny_world(seed, template)
                r = w.raster
                n = r.count
                self.assertEqual(r.ids.shape, (288, 576))
                present = np.unique(r.ids)
                # Ids 1..N sin huecos, sin el 0, tierra primero y mares contiguos al final.
                self.assertTrue(np.array_equal(present, np.arange(1, n + 1)))
                self.assertFalse(r.is_sea[1:r.land_count + 1].any())
                self.assertTrue(r.is_sea[r.land_count + 1:].all())
                # Cada provincia es de una pieza (4-conexa, sin envoltura: así cuenta fix_fragments).
                comp, lab_run, run_comp = run_components(r.ids.astype(np.int32), wrap_x=False)
                pieces = np.bincount(np.unique(np.column_stack([r.ids.ravel(), comp.ravel()]), axis=0)[:, 0],
                                     minlength=n + 1)
                self.assertLessEqual(int(pieces[1:].max()), 1, template)
                # Colores únicos y nunca negro ni blanco.
                cols = r.colors[1:]
                self.assertEqual(np.unique(cols).size, n)
                self.assertNotIn(0, cols.tolist())
                self.assertNotIn(0xFFFFFF, cols.tolist())
                # Agua del terreno = mar del ráster.
                self.assertTrue(np.array_equal(r.terrain == 254, r.is_sea[r.ids]))
                # Cada provincia tiene posiciones y su punto «unit» cae dentro.
                inside = 0
                for pid in range(1, n + 1):
                    x, y = int(r.positions["ux"][pid]), int(r.positions["uy"][pid])
                    inside += int(r.ids[min(y, 287), min(x, 575)] == pid)
                self.assertGreaterEqual(inside / n, 0.95)

    def test_province_counts_near_target(self):
        w = tiny_world(3)
        r = w.raster
        self.assertLessEqual(abs(r.land_count - 60), 12)
        self.assertLessEqual(abs((r.count - r.land_count) - 15), 6)

    def test_owners_modes(self):
        owned = tiny_world(3).raster
        self.assertGreater(int((owned.owner[1:owned.land_count + 1] >= 0).sum()), 0)
        free = tiny_world(3, owners_none=True).raster
        self.assertEqual(int((free.owner[1:free.land_count + 1] >= 0).sum()), 0)


class TemplateTests(unittest.TestCase):
    def test_fourteen_templates_valid(self):
        self.assertEqual(len(FMG_TEMPLATES), 14)
        for name, text in FMG_TEMPLATES.items():
            self.assertEqual(fmg_template.validate(text), [], name)
            self.assertIn(name, TEMPLATES)

    def test_y_flipped_for_game(self):
        self.assertEqual(fmg_template.to_game("Hill 1 30 50-60 20-30").split()[-1], "70-80")

    def test_errors_point_to_column(self):
        errs = fmg_template.validate("Hill 1 30 50-60 20-30\nBlob 2 3 4 5\nHill x 30 1 1")
        self.assertEqual([(e.line, e.code) for e in errs][:2], [(2, "unknown_op"), (3, "bad_range")])
        self.assertEqual(errs[1].column, 2)


class EditTests(unittest.TestCase):
    def test_relief_stroke_raises_cells_and_survives_regeneration(self):
        w = tiny_world(3)
        e = edits.make("relief_stroke", {"tool": "raise", "pts_norm": [[0.5, 0.5]], "r_norm": 0.05,
                                         "strength": 30})
        w2 = pipeline.run_cells(edits.add(w, e))
        hit = edits._disc_cells(w2, [[0.5, 0.5]], 0.05)
        self.assertTrue(hit.any())
        base = pipeline.run_cells(w)
        self.assertGreater(float(w2.cells.h[hit].mean()), float(base.cells.h[hit].mean()))
        self.assertEqual(w2.steps["relief"].status, "edited")

    def test_rename_by_cell_uid(self):
        w = tiny_world(3)
        cell = int(np.flatnonzero(w.cells.land)[0])
        p = int(w.cells.province0[cell])
        e = edits.make("rename", {"uid": f"p:{cell}", "name": "Villaprueba"})
        w2 = pipeline.run_cells(edits.add(w, e), from_step="names")
        self.assertEqual(w2.entities["province_names"][p], "Villaprueba")

    def test_grid_bound_edit_conflicts_when_lattice_changes(self):
        w = tiny_world(3)
        e = edits.make("paint_category", {"lattice_sha": "deadbeef0000", "cells": [1, 2], "cat": 3})
        conf = edits.conflicts(edits.add(w, e))
        self.assertEqual([c.reason for c in conf], ["lattice_changed"])
        issues = world_issues(w, conflicts=conf)
        self.assertIn("forge_edit_conflict", [i.code for i in issues])


class ProjectPersistenceTests(unittest.TestCase):
    def test_pack_roundtrip(self):
        arrays = {"a": np.arange(10, dtype=np.int32), "b": np.ones((3, 2), np.float64), "c": np.zeros(4, bool)}
        back = unpack_arrays(pack_arrays(arrays))
        for k, v in arrays.items():
            self.assertTrue(np.array_equal(back[k], v))
            self.assertEqual(back[k].dtype, v.dtype)

    def test_load_does_not_recompute_cells(self):
        w = tiny_world(3)
        proj = MapForgeProject("prueba", w.params, edits=list(w.edits))
        files = proj.files(w)
        self.assertIn(".vic2studio/mapforge/prueba/cells.pack", files)
        self.assertLess(len(files[".vic2studio/mapforge/prueba/cells.pack"]), 2_000_000)
        calls = []
        orig = pipeline.run_cells
        pipeline.run_cells = lambda *a, **k: calls.append(1) or orig(*a, **k)
        try:
            p2, w2, warnings = MapForgeProject.load(files.get, "prueba")
        finally:
            pipeline.run_cells = orig
        self.assertEqual(calls, [])
        self.assertEqual(warnings, [])
        self.assertEqual(w2.cells_digest(), w.cells_digest())
        self.assertEqual(p2.params, w.params)
        # El ráster sale igual desde lo guardado.
        r2 = pipeline.run_raster(w2, scale=1, with_textures=False).raster
        self.assertTrue(np.array_equal(r2.ids, w.raster.ids))

    def test_env_change_warns(self):
        w = tiny_world(3)
        proj = MapForgeProject("prueba", w.params)
        files = proj.files(w)
        import json

        meta = json.loads(files[".vic2studio/mapforge/prueba/project.json"])
        meta["env"] = {"numpy": "0.0", "pillow": "0.0"}
        files[".vic2studio/mapforge/prueba/project.json"] = json.dumps(meta).encode()
        _, _, warnings = MapForgeProject.load(files.get, "prueba")
        self.assertIn("forge_env_changed", warnings)

    def test_params_json_roundtrip(self):
        p = tiny_params(owners=Owners.NONE, custom_names=("Uno", "Dos"), name_source="custom")
        self.assertEqual(ForgeParams.from_json(p.to_json()), p)


class IssueTextTests(unittest.TestCase):
    def test_every_code_has_texts_and_fixes(self):
        for lang in ("es", "en"):
            texts = load_texts(lang)
            for code, (_, fixes) in CODES.items():
                for key in (f"issue.{code}", f"explain.title.{code}", f"explain.outcome.{code}"):
                    self.assertIn(key, texts, (lang, key))
                for f in fixes:
                    self.assertIn(f"fix.mapforge.{f}", texts, (lang, f))
            self.assertIn("undo.mapforge_export", texts)

    def test_messages_format_with_args(self):
        i = ForgeIssue("province_isolated", {"count": 2, "first": 17}, "map/provinces.bmp", 2)
        self.assertIn("17", i.message("es"))
        self.assertNotIn("{", i.message("en"))
        title, outcome = i.explanation("es")
        self.assertIn("17", title)
        self.assertTrue(outcome)
        self.assertEqual(i.problem().fixes, ("mapforge.merge_isolated",))

    def test_reduce_target_fix(self):
        p = tiny_params(land_provinces=60000, sea_provinces=10000)
        self.assertIn("forge_too_many_provinces", [c for c, _ in p.validate()])
        q = fix_params(p, "reduce_target")
        self.assertLessEqual(q.land_target() + q.sea_target(), 60000)
        self.assertNotIn("forge_too_many_provinces", [c for c, _ in q.validate()])

    def test_no_owned_provinces_issue(self):
        codes = [i.code for i in world_issues(tiny_world(3, owners_none=True))]
        self.assertIn("forge_no_owned_provinces", codes)
        self.assertEqual(fix_params(tiny_params(owners=Owners.NONE), "share_existing_tags").owners,
                         Owners.EXISTING_TAGS)


if __name__ == "__main__":
    unittest.main()
