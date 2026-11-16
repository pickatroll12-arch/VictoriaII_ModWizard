"""Taller de mapas: importar un JSON de Azgaar's Fantasy Map Generator (wizard §18.6, criterio 4 de la iteración 9b).

El JSON es inventado (``_mapforge_fixtures.fmg_json_full``): la forma de ``getFullDataJson`` con 200 celdas, 3
estados, 6 provincias, 2 culturas y 1 río."""

from __future__ import annotations

import time
import unittest

import numpy as np

from _mapforge_fixtures import fmg_json_full, tiny_install, tiny_params
from vic2studio.core.mapforge.imports import fmg_json as fj
from vic2studio.core.mapforge.params import Level


def imported(level=Level.WORLD, **kw):
    fmg = fj.read_fmg_json(fmg_json_full(**kw))
    params = tiny_params(level=level, land_provinces=30, sea_provinces=10)
    rep, extra = fj.to_import(fmg, params)
    world, _ = fj.fmg_to_world(fmg, params, tiny_install())
    return fmg, rep, extra, world


class ReadTests(unittest.TestCase):
    def test_reads_the_full_json(self):
        fmg = fj.read_fmg_json(fmg_json_full())
        self.assertEqual(fmg.count, 200)
        self.assertEqual((fmg.width, fmg.height), (960.0, 480.0))
        self.assertEqual(sorted(s for s in fmg.states if s > 0), [1, 2, 3])
        self.assertEqual(sorted(fmg.provinces), [1, 2, 3, 4, 5, 6])
        self.assertEqual(len(fmg.rivers), 1)
        self.assertEqual(fmg.issues, [])

    def test_a_later_version_is_reported_and_imported(self):
        fmg = fj.read_fmg_json(fmg_json_full(version="9.0"))
        self.assertEqual([i.code for i in fmg.issues], ["fmg_version_unknown"])
        self.assertIn("9.0", fmg.issues[0].message("es"))

    def test_without_pack_cells_it_refuses(self):
        with self.assertRaises(ValueError):
            fj.read_fmg_json(b'{"info": {"version": "1.99"}, "pack": {"cells": []}}')


class ImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fmg, cls.rep, cls.extra, cls.world = imported()

    def test_no_game_province_crosses_an_fmg_province_or_the_seam(self):
        r = self.world.raster
        cell_px = self.extra["cell_px"]
        prov_px = np.where(cell_px >= 0, self.fmg.province[np.maximum(cell_px, 0)], -1)
        land_px = np.where(cell_px >= 0, self.fmg.h[np.maximum(cell_px, 0)] >= 20, False)
        for pid in range(1, r.land_count + 1):
            mask = (r.ids == pid) & land_px
            found = set(np.unique(prov_px[mask]).tolist())
            self.assertLessEqual(len(found), 1, (pid, found))
        W = r.ids.shape[1]
        self.assertEqual(np.intersect1d(np.unique(r.ids[:, 0]), np.unique(r.ids[:, W - 1])).size, 0)

    def test_y_is_flipped_to_the_game_order(self):
        cell_px = self.extra["cell_px"]
        cols = 20
        rows_of = {}
        for fmg_row in (0, 9):
            cells = list(range(fmg_row * cols, (fmg_row + 1) * cols))
            ys = np.nonzero(np.isin(cell_px, cells))[0]
            rows_of[fmg_row] = ys.mean()
        self.assertGreater(rows_of[0], rows_of[9], "la fila de arriba de FMG (norte) va a las y altas del juego")

    def test_fmg_states_become_countries_and_provinces_states(self):
        w = self.world
        r = w.raster
        countries = w.entities["world"]["countries"]
        self.assertEqual([c["name"] for c in countries], ["Velmora", "Ostrand", "Kaldun"])
        self.assertEqual(w.entities["owners"], [c["tag"] for c in countries])
        cell_px = self.extra["cell_px"]
        state_px = np.where(cell_px >= 0, self.fmg.state[np.maximum(cell_px, 0)], -1)
        prov_px = np.where(cell_px >= 0, self.fmg.province[np.maximum(cell_px, 0)], -1)
        for pid in range(1, r.land_count + 1):
            mask = r.ids == pid
            fmg_state = int(np.bincount(state_px[mask][state_px[mask] > 0]).argmax())
            self.assertEqual(int(r.owner[pid]), fmg_state - 1, pid)
        # Cada estado del juego está dentro de una sola provincia de FMG.
        for s in np.unique(r.state[1:r.land_count + 1]).tolist():
            members = np.flatnonzero(r.state == s)
            found = set()
            for pid in members.tolist():
                vals = prov_px[r.ids == pid]
                found |= set(np.unique(vals[vals > 0]).tolist())
            self.assertEqual(len(found), 1, (s, found))
        self.assertIn("Arvel", w.entities["state_names"])
        names = {c["name"] for c in w.entities["world"]["cultures"]}
        self.assertTrue({"Velmorian", "Ostric"} <= names)
        for k, cap in enumerate(r.capitals):
            self.assertEqual(int(r.owner[cap]), k)

    def test_map_level_keeps_existing_tags(self):
        _, _, _, w = imported(Level.MAP)
        self.assertNotIn("world", w.entities)
        self.assertTrue(set(w.entities["owners"]) <= {"AAA", "BBB", "CCC"})
        self.assertIn("Corran", w.entities["state_names"])

    def test_a_large_json_reads_quickly(self):
        data = fmg_json_full(cols=300, rows=200)
        t = time.perf_counter()
        fmg = fj.read_fmg_json(data)
        seconds = time.perf_counter() - t
        self.assertEqual(fmg.count, 60000)
        self.assertLess(seconds, 3.0, f"{seconds:.2f} s para 60 000 celdas")


if __name__ == "__main__":
    unittest.main()
