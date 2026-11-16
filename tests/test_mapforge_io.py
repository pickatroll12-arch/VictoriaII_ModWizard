"""Taller de mapas: exportación, importación, auditoría y proceso trabajador (wizard §18.6, §18.8, §18.9 y §18.4).

La exportación va contra el minijuego del mapa (inventado) abierto como proyecto en una carpeta temporal; nunca
contra un mod de verdad."""

from __future__ import annotations

import io
import time
import unittest
from collections import Counter

import numpy as np
from PIL import Image

from _mapforge_fixtures import tiny_install, tiny_params, tiny_world
from _layers import isolate_appdirs
from _minigame import build_map_minigame
from vic2studio.core.cancel import Cancelled
from vic2studio.core.mapforge import export as ex, install, pipeline
from vic2studio.core.mapforge.audit import DependencyAudit
from vic2studio.core.mapforge.imports import bitmaps as bm, heightmap as hm
from vic2studio.core.mapforge.project import MapForgeProject
from vic2studio.core.mapforge.validate import world_issues
from vic2studio.core.mapforge.worker import ForgeCommand, ForgeWorker
from vic2studio.core.map.bmp import new_bmp, read_bmp


def _files(world):
    files, _ = ex.render_files(world, ex.ExportInputs(prefix="FRG"))
    return files


class ExportTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)
        from vic2studio.core.project.project import Project

        self.game = build_map_minigame(clean=True)
        self.addCleanup(self.game.cleanup)
        self.project = Project.open(self.game.game_root, self.game.mod_root)
        self.addCleanup(self.project.close)

    def test_export_is_coherent_and_undoable(self):
        from vic2studio.core.index import build_index
        from vic2studio.core.map.coherence import check_map
        from vic2studio.core.validate import build_context

        p = self.project
        prof = install.learn_install(install.source_from_vfs(p.vfs))
        self.assertFalse(prof.synthetic)
        self.assertTrue(prof.tags)
        world = pipeline.run_all(tiny_params(existing_tags=2), prof)
        inputs = ex.gather_inputs(p, world)
        files, report = ex.render_files(world, inputs)
        for rel in ("map/provinces.bmp", "map/definition.csv", "map/default.map", "map/terrain.bmp",
                    "map/rivers.bmp", "map/positions.txt", "map/adjacencies.csv", "map/region.txt",
                    "map/continent.txt", "map/climate.txt", "map/terrain/colormap.dds",
                    "map/terrain/colormap_water.dds", "map/terrain/colormap_no_shadow.dds",
                    "gfx/interface/minimap.dds"):
            self.assertIn(rel, files)
        self.assertTrue(any(r.startswith("history/provinces/") for r in files))
        self.assertTrue(any(r.startswith("history/pops/") for r in files))
        plan = ex.export_plan(files, inputs, lambda rel: p.vfs.resolve(rel) is not None)
        actions = Counter(f.action for f in plan)
        self.assertGreater(actions[ex.ACTION_GENERATE], 50)
        # El proyecto del taller va en la misma transacción.
        proj = MapForgeProject("mundo", world.params)
        extra = proj.files(world)
        touched = ex.apply_export(p, files, inputs, extra=extra)
        self.assertIn("map/provinces.bmp", touched)
        self.assertIn(".vic2studio/mapforge/mundo/cells.pack", touched)
        snap = p.vfs.snapshot()
        before = check_map(build_context(snap, build_index(snap, None)))
        self.assertEqual([x.code for x in before if x.severity.name == "ERROR"], [])
        # Deshacer quita la exportación entera (una sola transacción).
        step = p.ws.undo()
        self.assertEqual(step.label, ex.UNDO_EXPORT)
        self.assertFalse(p.ws.can_undo())
        saved = p.save()
        self.assertTrue(saved.result is None or not saved.result.written)
        self.assertFalse((self.game.mod_root / "map" / "provinces.bmp").exists())

    def test_a_failure_halfway_leaves_the_mod_as_it_was(self):
        """Criterio 7: un fallo a mitad de la exportación revierte la transacción entera (todo antes)."""
        from unittest import mock

        from vic2studio.core.project import binary
        from vic2studio.core.vfs.model import LayerKind

        p = self.project
        world = tiny_world(3)
        inputs = ex.gather_inputs(p, world)
        files, _ = ex.render_files(world, inputs)
        real = binary.put_bytes
        calls = []

        def flaky(ws, rel, data):
            calls.append(rel)
            if len(calls) == len(files) // 2:
                raise OSError("fallo inyectado")
            return real(ws, rel, data)

        with mock.patch.object(binary, "put_bytes", flaky), self.assertRaises(OSError):
            ex.apply_export(p, files, inputs)
        self.assertEqual(len(calls), len(files) // 2)
        self.assertFalse(p.ws.can_undo())
        self.assertEqual(p.ws.dirty(), [])
        self.assertIs(p.vfs.resolve("map/provinces.bmp").layer.kind, LayerKind.GAME)

    def test_the_mod_keeps_no_foreign_histories_after_exporting(self):
        """Criterio 7: las historias y POPs que el mod ya tenía bajo las carpetas reemplazadas van a la papelera."""
        self.game.cleanup()
        self.project.close()
        old = {"history/provinces/zz/1 - Vieja.txt": "owner = AAA\r\n",
               "history/pops/1836.1.1/zz_viejas.txt": "1 = { farmers = { culture = alander religion = catholic "
                                                       "size = 10 } }\r\n"}
        self.game = build_map_minigame(clean=True, mod_files=old)
        self.addCleanup(self.game.cleanup)
        from vic2studio.core.project.project import Project

        p = Project.open(self.game.game_root, self.game.mod_root)
        self.addCleanup(p.close)
        world = tiny_world(3)
        inputs = ex.gather_inputs(p, world)
        self.assertTrue(set(old) <= set(inputs.mod_trash))
        files, _ = ex.render_files(world, inputs)
        ex.apply_export(p, files, inputs)
        p.save()
        for rel in old:
            self.assertFalse((self.game.mod_root / rel).exists(), rel)
        mine = {str(e.rel) for e in p.vfs.list("history/provinces", "*", recursive=True)
                if e.layer.kind.name == "MOD"}
        self.assertEqual(mine, {rel for rel in files if rel.startswith("history/provinces/")})

    def test_audit_finds_old_province_ids_in_events(self):
        p = self.project
        world = tiny_world(3)
        inputs = ex.gather_inputs(p, world)
        from vic2studio.core.project.binary import put_bytes

        text = b"province_event = {\r\n\tid = 9001\r\n\ttrigger = { owns = 3 province_id = 9999 }\r\n}\r\n"
        with p.ws.transaction("undo.mapforge_export"):
            put_bytes(p.ws, "events/zz_prueba.txt", text)
        p.save()
        groups = DependencyAudit(p.vfs, world, inputs, old_province_count=10).run()
        ev = [g for g in groups if g.folder == "events" and g.role == "province_id"]
        self.assertTrue(ev)
        self.assertIn("events/zz_prueba.txt", ev[0].files)
        self.assertEqual(ev[0].files["events/zz_prueba.txt"], 2)


class ImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = tiny_world(3)
        cls.files = _files(cls.world)

    def _set(self, **slots):
        names = {"provinces": "map/provinces.bmp", "definition": "map/definition.csv",
                 "default_map": "map/default.map", "terrain": "map/terrain.bmp", "rivers": "map/rivers.bmp",
                 "positions": "map/positions.txt"}
        out = {k: self.files[v] for k, v in names.items()}
        out.update(slots)
        return bm.ImportSet({k: v for k, v in out.items() if v is not None})

    def test_roundtrip_same_bytes(self):
        fs = self._set()
        rep = bm.inspect(fs, tiny_install())
        self.assertTrue(rep.ok, [i.code for i in rep.errors])
        self.assertEqual(rep.land_source, "sea_starts")
        self.assertFalse(rep.flip)
        w2 = bm.build_world(fs, rep, tiny_params(), tiny_install())
        files2 = _files(w2)
        for rel in ("map/provinces.bmp", "map/definition.csv", "map/default.map", "map/terrain.bmp",
                    "map/rivers.bmp", "map/positions.txt"):
            self.assertEqual(files2[rel], self.files[rel], rel)

    def test_only_provinces_and_terrain(self):
        fs = self._set(definition=None, default_map=None, rivers=None, positions=None)
        rep = bm.inspect(fs, tiny_install())
        self.assertEqual(rep.land_source, "terrain")
        self.assertEqual(rep.matrix["rivers"], "generated")
        w2 = bm.build_world(fs, rep, tiny_params(), tiny_install())
        r = w2.raster
        self.assertEqual(r.count, self.world.raster.count)
        self.assertEqual(r.land_count, self.world.raster.land_count)
        self.assertTrue(np.array_equal(r.terrain == 254, r.is_sea[r.ids]))

    def test_png_orientation(self):
        px = read_bmp(self.files["map/provinces.bmp"]).pixels
        north_up = io.BytesIO()
        Image.fromarray(np.ascontiguousarray(px[::-1])).save(north_up, "PNG")
        rep = bm.inspect(self._set(provinces=north_up.getvalue(), terrain=None, rivers=None), tiny_install())
        self.assertNotIn("forge_orientation_suspect", [i.code for i in rep.issues])
        base = bm.inspect(self._set(terrain=None, rivers=None), tiny_install())
        self.assertTrue(np.array_equal(rep.pid, base.pid))
        upside = io.BytesIO()
        Image.fromarray(np.ascontiguousarray(px)).save(upside, "PNG")
        rep2 = bm.inspect(self._set(provinces=upside.getvalue(), terrain=None, rivers=None), tiny_install())
        self.assertIn("forge_orientation_suspect", [i.code for i in rep2.issues])
        self.assertTrue(np.array_equal(rep2.pid, base.pid))

    def test_problems_detected(self):
        px = read_bmp(self.files["map/provinces.bmp"]).pixels.copy()
        px[0:2, 0:2] = 0                         # 4 px negros: color reservado y provincia diminuta
        rgba = io.BytesIO()
        Image.fromarray(np.ascontiguousarray(px[::-1])).convert("RGBA").save(rgba, "PNG")
        rep = bm.inspect(self._set(provinces=rgba.getvalue(), definition=None, default_map=None, terrain=None,
                                   rivers=None, positions=None), tiny_install())
        codes = {i.code for i in rep.issues}
        self.assertTrue({"forge_not_24bit", "forge_color_reserved", "forge_tiny_province",
                         "forge_land_sea_unknown"} <= codes, codes)
        self.assertFalse(rep.ok)

    def test_river_checks(self):
        riv = read_bmp(self.files["map/rivers.bmp"]).pixels.copy()
        land = np.argwhere(riv == 255)
        y, x = (int(v) for v in land[len(land) // 2])
        riv[y, x] = 5
        riv[y + 1, x + 1] = 5
        riv[y + 1, x] = 255
        riv[y, x + 1] = 255
        pal = np.frombuffer(tiny_install().rivers_palette, np.uint8).reshape(-1, 3)
        rep = bm.inspect(self._set(rivers=new_bmp(riv, pal)), tiny_install())
        codes = {i.code for i in rep.issues}
        self.assertIn("rivers_diagonal", codes)
        self.assertIn("river_source_missing", codes)

    def test_rgb_terrain_converted_with_palette(self):
        idx = read_bmp(self.files["map/terrain.bmp"]).pixels
        pal = np.frombuffer(tiny_install().terrain_palette, np.uint8).reshape(-1, 3)
        rgb = new_bmp(np.ascontiguousarray(pal[idx]))
        rep = bm.inspect(self._set(terrain=rgb), tiny_install())
        self.assertIn("terrain_not_indexed", [i.code for i in rep.issues])
        self.assertTrue(np.array_equal(rep.terrain, idx))


class HeightmapTests(unittest.TestCase):
    def test_fmg_png_detected_and_inverted(self):
        h = np.linspace(0, 100, 256 * 64).reshape(64, 256)
        v = np.where(h >= 20, h / 100 * 255, h / 100 * 255 / 1.5).round().astype(np.uint8)
        self.assertTrue(hm.is_fmg(v))
        back = hm.to_heights(v)
        self.assertLess(float(np.abs(back - h).max()), 1.0)
        self.assertFalse(hm.is_fmg(np.linspace(0, 255, 256 * 64).reshape(64, 256).astype(np.uint8)))

    def test_sixteen_bit(self):
        g = (np.arange(64 * 64).reshape(64, 64) * 16).astype(np.uint16)
        buf = io.BytesIO()
        Image.fromarray(g).save(buf, "PNG")
        gray, _ = hm.load_gray(buf.getvalue())
        self.assertEqual(gray.dtype, np.uint16)
        self.assertAlmostEqual(float(hm.to_heights(gray).max()), g.max() / 65535 * 100, places=3)

    def test_imported_heights_drive_relief(self):
        w = pipeline.new_world(tiny_params())
        img = np.zeros((288, 576), np.uint8)
        img[:, 288:] = 200                      # tierra al este (orden del juego)
        h = hm.heights_from_image(img, w.cells.pts, (576, 288))
        w = w.evolve(imported={"heightmap": h})
        w = pipeline.run_cells(w, until="features")
        east = w.cells.pts[:, 0] > 300
        self.assertTrue(w.cells.land[east].all())
        self.assertFalse(w.cells.land[w.cells.pts[:, 0] < 270].any())


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.progress = []
        self.worker = ForgeWorker(on_progress=lambda job, name, i, n: self.progress.append(name))
        self.addCleanup(self.worker.close)

    def test_run_in_other_process_is_identical(self):
        reply = self.worker.submit(ForgeCommand("run_all", {"params": tiny_params(), "install": tiny_install()})
                                   ).result(120)
        self.assertEqual(reply.world.world_digest(), tiny_world(3).world_digest())
        self.assertIn("raster", self.progress)
        files = self.worker.submit(ForgeCommand("export_bytes", {"world": reply.world,
                                                                 "inputs": ex.ExportInputs(prefix="FRG")})
                                   ).result(120).files
        self.assertEqual(files["map/provinces.bmp"], _files(tiny_world(3))["map/provinces.bmp"])

    def test_cancel_is_quick(self):
        fut = self.worker.submit(ForgeCommand("run_all", {"params": tiny_params(size=(5616, 2160),
                                                                                land_provinces=None,
                                                                                sea_provinces=None)}))
        deadline = time.monotonic() + 30
        while not self.progress and time.monotonic() < deadline:
            time.sleep(0.05)
        t0 = time.monotonic()
        self.worker.cancel()
        with self.assertRaises(Cancelled):
            fut.result(10)
        self.assertLess(time.monotonic() - t0, 3.0)
        self.assertEqual(self.worker.submit(ForgeCommand("ping", {"value": 1})).result(60).report, 1)


class ReviewIssueTests(unittest.TestCase):
    def test_mod_files_under_replaced_folders(self):
        inputs = ex.ExportInputs(mod_trash=["history/provinces/europe/1 - Uno.txt", "history/pops/1836.1.1/a.txt"])
        issues = world_issues(tiny_world(3), inputs)
        rp = [i for i in issues if i.code == "replace_path_mod_files_remain"]
        self.assertEqual(len(rp), 1)
        self.assertTrue(rp[0].needs_confirmation)
        self.assertEqual(rp[0].fixes[0], "trash_mod_files")
        self.assertIn("history/pops", rp[0].message("es"))


if __name__ == "__main__":
    unittest.main()
