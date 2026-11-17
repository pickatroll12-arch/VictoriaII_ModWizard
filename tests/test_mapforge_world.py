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

    def fmg_world(self, level, states=None, provinces=None, cultures=None):
        """El JSON de FMG inventado con nombres que el juego no sabe escribir (otras escrituras, letras sin cp1252 y
        un emoji, o los de ``states``/``provinces``/``cultures`` por su ``i``), importado al nivel ``level``."""
        import json

        from _mapforge_fixtures import fmg_json_full
        from vic2studio.core.mapforge.imports import fmg_json as fj

        data = json.loads(fmg_json_full())
        pack = data["pack"]
        states = {1: "Łódź", 2: "東京", 3: "Ŝtato 🙂"} if states is None else states
        provinces = {1: "Ősz", 2: "Łęczyca", 3: "大阪", 5: "Ŝkolo", 6: "🙂 Fenna"} if provinces is None else provinces
        cultures = {1: "Ślązak", 2: "日本人"} if cultures is None else cultures
        for item, names in ((pack["states"], states), (pack["provinces"], provinces), (pack["cultures"], cultures)):
            for x in item:
                if isinstance(x, dict) and x.get("i") in names:
                    x["name"] = names[x["i"]]
                    if "fullName" in x:
                        x["fullName"] = names[x["i"]]
        fmg = fj.read_fmg_json(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        world, _ = fj.fmg_to_world(fmg, tiny_params(level=level, land_provinces=30, sea_provinces=10), self.profile)
        return world

    def test_azgaar_names_the_game_cannot_write_export_without_failing(self):
        """Regresión (la vio el tutorial): un mundo de Azgaar con letras que el juego no tiene hacía fallar la
        exportación de «Mundo» sin ningún mensaje (``UnencodableTextError`` al escribir los textos de los países), y
        dos nombres de otra escritura daban el mismo archivo ``common/countries/x.txt``. Ahora los nombres se pasan a
        cp1252 al importar ('Łódź' → 'Lódz'), lo que no tiene letras usa el nombre generado y cada país tiene su
        archivo."""
        from vic2studio.core.mapforge.names import cp1252_ok

        p = self.project
        w = self.fmg_world(Level.WORLD)
        data = w.entities["world"]
        for c in data["countries"]:
            self.assertTrue(cp1252_ok(c["name"]) and cp1252_ok(c["adjective"]), c)
            self.assertTrue(any(ch.isalpha() for ch in c["name"]), c)
        for c in data["cultures"]:
            self.assertTrue(cp1252_ok(c["name"]), c)
        self.assertIn("Lódz", [c["name"] for c in data["countries"]])
        self.assertIn("Slazak", [c["name"] for c in data["cultures"]])
        inputs = ex.gather_inputs(p, w, index=self.index)
        files, _ = ex.render_files(w, inputs)
        loc = files[f"localisation/00_{inputs.prefix}_map.csv"]
        self.assertNotIn(b"?", loc)
        self.assertIn("Osz".encode("cp1252"), loc)
        touched = ex.apply_export(p, files, inputs, world=w, domain=self.domain)
        countries = [t for t in touched if t.startswith("common/countries/")]
        self.assertEqual(len(countries), len(set(t.lower() for t in countries)))
        self.assertEqual(len(countries), len(data["countries"]))

    def test_azgaar_names_with_a_separator_or_a_line_break_export_without_failing(self):
        """Regresión: un ';' en el nombre de un estado o de una cultura de Azgaar ('Alta;Baja', 'Norte;Sur') cabe en
        cp1252, así que llegaba tal cual a los textos de los países y las culturas; ``LocSync`` lo rechaza
        (``separator_in_text``: partiría la fila del CSV) y la exportación de «Mundo» entera se deshacía. Ahora los
        nombres de fuera salen con todo lo que ``csvloc.check_text`` rechaza cambiado: ';' → ',' y saltos de línea,
        tabulaciones y otros caracteres de control → espacio."""
        from vic2studio.core.csvloc.model import check_text
        from vic2studio.core.mapforge.names import cp1252_name

        for raw, clean in (("Alta;Baja", "Alta,Baja"), ("Este\r\nOeste", "Este Oeste"), ("Sur\x00Norte\t", "Sur Norte"),
                           ("Mar\u2028Tierra\x85", "Mar Tierra")):
            self.assertEqual(cp1252_name(raw), clean)
        self.assertEqual(cp1252_name(";\n", "AAA"), "AAA", "sin letras ni cifras, el de reserva")
        p = self.project
        w = self.fmg_world(Level.WORLD, states={1: "Alta;Baja", 2: "Este\r\nOeste", 3: "Sur\x00Norte"},
                           provinces={1: "Mar;Tierra"}, cultures={1: "Norte;Sur", 2: "Gente\tde mar"})
        data = w.entities["world"]
        texts = [c["name"] for c in data["countries"]] + [c["adjective"] for c in data["countries"]] + \
            [c["name"] for c in data["cultures"]] + [g["name"] for g in data["groups"]] + w.entities["state_names"]
        for text in texts:
            check_text(text)
            text.encode("cp1252")
            self.assertFalse(any(ord(ch) < 32 for ch in text), repr(text))
        self.assertEqual([c["name"] for c in data["countries"]], ["Alta,Baja", "Este Oeste", "Sur Norte"])
        self.assertIn("Mar,Tierra", w.entities["state_names"])
        inputs = ex.gather_inputs(p, w, index=self.index)
        files, _ = ex.render_files(w, inputs)
        ex.apply_export(p, files, inputs, world=w, domain=self.domain)      # antes: InvalidFieldError
        loc = self.domain.loc
        self.assertEqual([loc.text(c["tag"], "en") for c in data["countries"]], ["Alta,Baja", "Este Oeste",
                                                                                 "Sur Norte"])
        self.assertEqual(loc.text(f"{data['countries'][0]['tag']}_ADJ", "en"), "Alta,Bajian")
        self.assertEqual({loc.text(c["key"], "en") for c in data["cultures"]}, {"Norte,Sur", "Gente de mar"})

    def test_azgaar_names_without_letters_do_not_name_countries(self):
        """Un estado o una cultura de Azgaar sin letras ('12', '½', '2026') no da nombre a un país ni a una cultura:
        saldrían países «12» con gentilicio «12ian». Van los nombres generados, como con otras escrituras."""
        w = self.fmg_world(Level.WORLD, states={1: "12", 2: "½", 3: "2026"}, cultures={1: "42", 2: "7"})
        data = w.entities["world"]
        texts = [c["name"] for c in data["countries"]] + [c["adjective"] for c in data["countries"]] + \
            [c["name"] for c in data["cultures"]]
        for text in texts:
            self.assertTrue(any(ch.isalpha() for ch in text), repr(text))
        self.assertFalse({"12", "½", "2026", "42", "7"} & set(texts))

    def test_azgaar_state_names_are_transliterated_at_the_map_level(self):
        """En «Solo mapa» no fallaba, pero los nombres perdían letras sin avisar: 'Ősz' salía como '?sz'."""
        w = self.fmg_world(Level.MAP)
        inputs = ex.gather_inputs(self.project, w, index=self.index)
        files, _ = ex.render_files(w, inputs)
        loc = files[f"localisation/00_{inputs.prefix}_map.csv"]
        self.assertNotIn(b"?", loc)
        self.assertIn(b";Osz;", loc)
        self.assertIn(b";Leczyca;", loc)

    def test_a_hand_rename_the_game_cannot_write_is_transliterated_not_lost(self):
        """Un nombre puesto a mano en la tabla de nombres ('Łódź東京;') salía como '?ód??;' y su ';' partía la fila.
        Uno sin ninguna letra que el juego sepa escribir ('大阪', 'Москва') salía vacío ('PROV2;;;;…'). Aquí se cambia
        la entidad sin pasar por una edición, así que no se sabe qué nombre generado tapa: va la clave, como en los
        estados."""
        w = world_of(3, countries=3, install_profile=self.profile)
        names = list(w.entities["province_names"])
        names[:6] = ["Łódź東京;", "大阪", "Ŝkolo", "Москва", "12", "..."]
        w = pipeline.run_raster(w.evolve(entities=dict(w.entities, province_names=names)), scale=1,
                                with_textures=False)
        self.assertIn("Łódź東京;", w.raster.names)
        inputs = ex.gather_inputs(self.project, w, index=self.index)
        files, _ = ex.render_files(w, inputs)
        loc = files[f"localisation/00_{inputs.prefix}_map.csv"]
        self.assertNotIn(b"?", loc)
        rows = [r for r in loc.split(b"\r\n") if r.startswith(b"PROV")]
        self.assertTrue(all(r.count(b";") == 14 for r in rows), "cada fila conserva sus columnas")
        self.assertEqual(len(rows), w.raster.count)
        self.assertTrue(all(r.split(b";")[1] for r in rows), "ninguna provincia sin nombre")
        self.assertIn(";Lódz,;".encode("cp1252"), loc)
        self.assertIn(b";Skolo;", loc)
        # Lo que el juego sí sabe escribir se respeta aunque no tenga letras: lo ha puesto alguien a mano.
        self.assertIn(b";12;12;12;;12;", loc)
        self.assertIn(b";...;...;...;;...;", loc)
        for name in ("大阪", "Москва"):
            pid = list(w.raster.names).index(name)
            self.assertIn(f"PROV{pid};PROV{pid};PROV{pid};PROV{pid};;PROV{pid};;;;;;;;;x".encode(), rows)

    def test_a_hand_rename_with_nothing_the_game_can_write_exports_the_generated_name(self):
        """Regresión: una provincia renombrada en «10. Nombres» a un nombre sin letras de cp1252 ('大阪', 'Москва')
        salía en la localización con el nombre vacío ('PROV2;;;;…'). Ahora va el nombre generado al que tapó la
        edición (también al guardar y volver a abrir el proyecto del taller, que no rehace los pasos), y lo mismo con
        un estado; la tabla sigue enseñando el nombre puesto a mano con su aviso."""
        from vic2studio.core.mapforge import edits
        from vic2studio.core.mapforge.project import MapForgeProject

        w = world_of(3, countries=3, install_profile=self.profile)
        r = w.raster
        renamed = {}
        for pid, name in ((2, "大阪"), (3, "Москва")):
            cell = int(np.flatnonzero(w.cells.province0 == int(r.parent[pid]))[0])
            w = edits.add(w, edits.make("rename", {"uid": f"p:{cell}", "name": name}))
            renamed[pid] = (name, r.names[pid])
        state = int(r.state[4])
        self.assertGreaterEqual(state, 0)
        cell = int(np.flatnonzero(w.cells.province0 == int(r.parent[4]))[0])
        w = edits.add(w, edits.make("rename", {"uid": f"s:{cell}", "name": "🙂"}))
        state_name = w.entities["state_names"][state]
        w = pipeline.run_cells(w, from_step="names")
        self.assertEqual(w.entities["state_names"][state], "🙂")
        forge = MapForgeProject("prueba", w.params, edits=list(w.edits))
        _, loaded, _ = MapForgeProject.load(forge.files(w).get, "prueba", self.profile)
        for label, world in (("generado", w), ("reabierto", loaded)):
            with self.subTest(label):
                world = pipeline.run_raster(world, scale=1, with_textures=False)
                rows = dict(row.split(b";")[:2] for row in ex.localisation(world, "TST").split(b"\r\n") if row)
                self.assertTrue(all(rows.values()), "ningún nombre vacío")
                for pid, (name, generated) in renamed.items():
                    self.assertEqual(world.raster.names[pid], name)
                    self.assertEqual(rows[f"PROV{pid}".encode()], generated.encode("cp1252"))
                self.assertEqual(rows[ex.state_key("TST", state).encode()], state_name.encode("cp1252"))

    def test_continents_typed_in_the_workshop_become_valid_unique_keys(self):
        """Regresión: los continentes escritos en «Continentes» iban tal cual como claves de ``map/continent.txt``.
        Uno en otra escritura ('Европа', 'Азия') daba la clave vacía (' = {') desde que la exportación translitera, y
        uno con espacio ('North America'), una clave partida: errores de sintaxis y provincias sin continente
        (``land_province_without_continent``). Ahora cada uno es una clave válida y distinta (la misma en
        continent.txt, en las carpetas de history/provinces y en la auditoría); los que ya eran claves se quedan
        ('west_land', con sus modificadores de la instalación), uno de la instalación escrito como nombre ('East
        Land') es esa clave y conserva sus textos, y lo escrito de uno nuevo va a la localización. Un proyecto del
        taller guardado antes (con los nombres tal cual) se abre con las mismas claves."""
        import re

        from vic2studio.core.mapforge.names import script_keys
        from vic2studio.core.mapforge.project import MapForgeProject
        from vic2studio.core.project.project import Project

        install_keys = ["west_land", "east_land", "europe"]
        keys = script_keys(["Европа", "Азия", "North America", "west_land", "East Land", "Łódź Land", "12",
                            "north america", "EUROPE", "Europa", " "], keep=install_keys)
        self.assertEqual(keys, ["forge_continent_1", "forge_continent_2", "north_america", "west_land", "east_land",
                                "lodz_land", "forge_continent_7", "north_america_2", "europe", "Europa",
                                "forge_continent_11"])
        self.assertEqual(script_keys(keys, keep=install_keys), keys, "aplicarla otra vez no cambia nada")
        p = self.project
        _, before = self.problems(p)
        typed = ("Европа", "Азия", "North America", "west_land")
        w = pipeline.run_all(tiny_params(seed=3, continents=typed), self.profile)
        keys = w.entities["continent_names"]
        self.assertEqual(keys, ["forge_continent_1", "forge_continent_2", "north_america", "west_land"])
        forge = MapForgeProject("prueba", w.params)
        old = w.evolve(entities=dict(w.entities, continent_names=list(typed)))
        _, loaded, _ = MapForgeProject.load(forge.files(old).get, "prueba", self.profile)
        self.assertEqual(loaded.entities["continent_names"], keys)
        inputs = ex.gather_inputs(p, w, index=self.index)
        files, _ = ex.render_files(w, inputs)
        text = files["map/continent.txt"].decode("cp1252")
        heads = [line for line in text.splitlines() if line and not line.startswith(("\t", "#", "}"))]
        self.assertEqual(len(heads), len(set(h.lower() for h in heads)))
        for head in heads:
            self.assertRegex(head, r"^[A-Za-z_][A-Za-z0-9_]* = \{$")
        blocks = dict(ex._top_blocks(text))
        self.assertEqual(set(blocks), set(keys))
        self.assertIn("assimilation_rate = 0.5", blocks["west_land"])
        members = [int(x) for inner in blocks.values()
                   for x in re.search(r"provinces\s*=\s*\{([^}]*)\}", inner).group(1).split()]
        self.assertEqual(sorted(members), list(range(1, w.raster.land_count + 1)), "cada provincia, en uno")
        folders = {rel.split("/")[2] for rel in files if rel.startswith("history/provinces/")}
        self.assertEqual(folders, set(keys))
        loc = files[f"localisation/00_{inputs.prefix}_map.csv"]
        self.assertIn(b"\r\nnorth_america;North America;North America;North America;;North America;", loc)
        self.assertNotIn(b"\r\nwest_land;", loc)
        self.assertNotIn(b"\r\nforge_continent_1;", loc, "sin nada que el juego sepa escribir, la clave")
        # Un continente de la instalación escrito como nombre es esa clave y se queda con sus textos.
        other = pipeline.run_all(tiny_params(seed=3, continents=("East Land", "Nueva Tierra")), self.profile)
        self.assertEqual(other.entities["continent_names"], ["east_land", "nueva_tierra"])
        rows = ex.localisation(other, "TST").split(b"\r\n")
        self.assertIn(b"nueva_tierra;Nueva Tierra;Nueva Tierra;Nueva Tierra;;Nueva Tierra;;;;;;;;;x", rows)
        self.assertFalse([row for row in rows if row.startswith(b"east_land;")])
        ex.apply_export(p, files, inputs)
        p.save()
        p.close()
        self.project = Project.open(self.game.game_root, self.game.mod_root)
        _, after = self.problems(self.project)
        new = {x for x in after - before if x[0] != "pop_type_unknown"}
        self.assertEqual(new, set())

    def test_country_file_names_are_unique_and_avoid_existing_files(self):
        countries = [{"tag": "AAA", "name": "Ææ"}, {"tag": "BBB", "name": "東京"}, {"tag": "CCC", "name": "大阪"},
                     {"tag": "DDD", "name": "Kaldun"}, {"tag": "EEE", "name": "kaldun"}, {"tag": "FFF", "name": "Prussia"}]
        names = nations.country_file_names(countries, lambda rel: rel.lower() == "common/countries/prussia.txt")
        self.assertEqual(names, ["AAA", "BBB", "CCC", "Kaldun", "kaldun_EEE", "Prussia_FFF"])

    def test_overlay_is_not_exported(self):
        w = pipeline.run_all(tiny_params(level=Level.OVERLAY), tiny_install())
        with self.assertRaises(NotImplementedError):
            ex.render_files(w, ex.ExportInputs(prefix="FRG"))


if __name__ == "__main__":
    unittest.main()
