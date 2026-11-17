"""«Exportar al mod» del taller de mapas sobre el estado vivo del proyecto (lo sin guardar, lo deshecho).

Cada prueba es la regresión de un fallo de la revisión: exportar tras deshacer una exportación guardada (las lápidas
de sus binarios), las ediciones sin guardar de archivos del juego bajo las carpetas que la exportación reemplaza, el
descriptor creado o borrado en la sesión, las ``replace_path`` escritas de otra forma y la localización de los
continentes vacíos. Todo contra el minijuego del mapa (inventado), nunca contra un mod de verdad.
"""

from __future__ import annotations

import unittest
from collections import Counter

from _layers import isolate_appdirs
from _mapforge_fixtures import tiny_install, tiny_params, tiny_world
from _minigame import build_map_minigame
from vic2studio.core.mapforge import export as ex, pipeline
from vic2studio.core.mapforge.project import MapForgeProject
from vic2studio.core.project.codecs import codec_for
from vic2studio.core.project.project import Project

CAPITAL = "history/provinces/north/1 - Capital.txt"     # historia del juego del minijuego


def histories(files) -> set[str]:
    return {rel for rel in files if rel.startswith(tuple(f"{f}/" for f in ex.REPLACED_FOLDERS))}


class LiveExportCase(unittest.TestCase):
    """El minijuego del mapa abierto como proyecto; ``export`` hace la revisión y «Exportar al mod» del taller."""

    def setUp(self):
        isolate_appdirs(self)
        self.game = build_map_minigame(clean=True)
        self.addCleanup(self.game.cleanup)
        self.project = Project.open(self.game.game_root, self.game.mod_root)
        self.addCleanup(lambda: self.project.close(discard=True))

    def effective(self, rel):
        """Bytes de ``rel`` en la vista efectiva del ``Workspace`` (None si no se ve)."""
        try:
            handle = self.project.ws.open(rel)
        except FileNotFoundError:
            return None
        return bytes(codec_for(handle.kind).snapshot(handle.model))

    def review(self, seed: int):
        world = tiny_world(seed)
        inputs = ex.gather_inputs(self.project, world)
        files, _ = ex.render_files(world, inputs)
        extra = MapForgeProject("prueba", world.params).files(world)
        return world, inputs, files, extra

    def export(self, seed: int):
        world, inputs, files, extra = self.review(seed)
        ex.apply_export(self.project, files, inputs, extra=extra)
        return world, inputs, files, extra

    def saved(self, rel):
        """Bytes que el juego leería de ``rel`` tras guardar: la copia del mod o, sin ella, el archivo del juego (una
        exportación que pone los mismos bytes que el juego no copia nada al mod)."""
        for root in (self.game.mod_root, self.game.game_root):
            if (root / rel).is_file():
                return (root / rel).read_bytes()
        return None

    def on_disk(self, folders=ex.REPLACED_FOLDERS) -> set[str]:
        """Los archivos del mod bajo ``folders`` (sin las copias ``.bak`` del diario)."""
        root = self.game.mod_root
        return {path.relative_to(root).as_posix() for folder in folders for path in (root / folder).rglob("*")
                if path.is_file() and path.suffix != ".bak"}


class ExportAfterUndoingASavedExportTests(LiveExportCase):
    def test_exporting_again_revives_the_tombstones_of_a_saved_export(self):
        """Regresión (MEDIO): deshacer una exportación guardada deja una lápida en cada archivo que creó, también en
        los binarios (``gfx/interface/minimap.dds``, las texturas de ``map/terrain``, el ``cells.pack`` del proyecto
        del taller). Volver a exportar pasaba por ``open(create=True)``, que revive la lápida con
        ``Workspace.create``, y ``create`` rechaza los binarios: ``ReadOnlyDocumentError(binary)`` y la exportación
        entera se revertía. Ahora la lápida de un binario revive con los bytes nuevos; deshacer la devuelve y rehacer
        pone otra vez los bytes. Al guardar, el disco tiene justo lo de la segunda exportación."""
        p = self.project
        _, _, files_a, extra_a = self.export(3)
        self.assertTrue(p.save().ok)
        p.ws.undo()
        tombs = {rel for rel in (*files_a, *extra_a) if p.ws.peek(rel).deleted}
        binary = {rel for rel in tombs if not codec_for(p.ws.peek(rel).kind).writable}
        self.assertLessEqual({".vic2studio/mapforge/prueba/cells.pack", "gfx/interface/minimap.dds",
                              "map/terrain/colormap.dds"}, binary)
        self.assertIn(".vic2studio/mapforge/prueba/project.json", tombs - binary, "y lápidas de texto")
        self.assertTrue(histories(files_a) <= tombs)
        world_b, _, files_b, extra_b = self.export(5)      # antes: ReadOnlyDocumentError (un binario de A)
        written = {**files_b, **extra_b}
        for rel, data in written.items():
            self.assertEqual(self.effective(rel), data, rel)
        p.ws.undo()
        for rel in tombs:
            self.assertTrue(p.ws.peek(rel).deleted, f"deshacer devuelve la lápida: {rel}")
        p.ws.redo()
        for rel, data in written.items():
            self.assertEqual(self.effective(rel), data, rel)
        self.assertTrue(p.save().ok)
        self.assertEqual(p.ws.dirty(), [])
        for rel, data in written.items():
            self.assertEqual(self.saved(rel), data, rel)
        for rel in set(files_a) - set(written):
            self.assertIsNone(self.saved(rel), f"de A y no de B: a la papelera ({rel})")
        self.assertEqual(self.on_disk(), histories(files_b))
        ids = Counter(int(rel.rsplit("/", 1)[1].split(" ")[0]) for rel in self.on_disk(("history/provinces",)))
        self.assertEqual(sorted(ids), list(range(1, world_b.raster.land_count + 1)))
        self.assertEqual(set(ids.values()), {1})

    def test_exporting_after_undoing_two_saved_exports(self):
        """La misma lápida con dos exportaciones guardadas deshechas (``A, B, guardar, deshacer B, deshacer A, C``) y
        con la revisión preparada antes de deshacer (``A, guardar, revisión de B, deshacer A, exportar B``)."""
        p = self.project
        self.export(3)
        self.export(5)
        self.assertTrue(p.save().ok)
        p.ws.undo()
        p.ws.undo()
        _, _, files_c, extra_c = self.export(7)
        self.assertTrue(p.save().ok)
        for rel, data in {**files_c, **extra_c}.items():
            self.assertEqual(self.saved(rel), data, rel)
        self.assertEqual(self.on_disk(), histories(files_c))
        # Revisión preparada con la exportación guardada aún hecha, aplicada después de deshacerla.
        world, inputs, files, extra = self.review(3)
        p.ws.undo()
        ex.apply_export(p, files, inputs, extra=extra)
        self.assertTrue(p.save().ok)
        for rel, data in {**files, **extra}.items():
            self.assertEqual(self.saved(rel), data, rel)
        self.assertEqual(self.on_disk(), histories(files))

    def test_the_next_export_reads_what_undo_left_not_the_disk(self):
        """Regresión: tras deshacer una exportación guardada, ``map/region_sea.txt`` y las historias de país vuelven
        a ser las del juego en el ``Workspace``, pero en el disco siguen las de la exportación deshecha. La revisión
        las leía del disco: el ``region_sea.txt`` de la primera no cita provincias, así que la segunda no lo
        reescribía y al guardar quedaba el del juego, con las provincias del mapa viejo (lo mismo con una capital que
        ya estaba puesta). Ahora se leen de la vista efectiva con lo sin guardar."""
        p = self.project
        _, _, files_a, _ = self.export(3)
        self.assertIn("map/region_sea.txt", files_a, "el del juego cita provincias: la exportación lo vacía")
        self.assertTrue(p.save().ok)
        p.ws.undo()
        game = (self.game.game_root / "map/region_sea.txt").read_bytes()
        self.assertEqual(self.effective("map/region_sea.txt"), game)
        _, inputs, files_b, _ = self.export(5)
        self.assertTrue(inputs.region_sea_cites)
        self.assertIn("map/region_sea.txt", files_b)        # antes: no, y se guardaba el del juego
        for rel, data in inputs.country_histories.items():
            self.assertEqual(data, (self.game.game_root / rel).read_bytes(), f"la de ahora, no la del disco: {rel}")
        self.assertTrue(p.save().ok)
        self.assertEqual(self.saved("map/region_sea.txt"), files_b["map/region_sea.txt"])


class DirtyGameEditsUnderReplacedFoldersTests(LiveExportCase):
    """Una edición sin guardar de un archivo del juego bajo las carpetas que la exportación reemplaza (la historia de
    una provincia pintada en el mapa del juego) es del mapa viejo: «Exportar al mod» la descarta."""

    def edit(self, rel: str, key: str, value: str) -> None:
        ws = self.project.ws
        handle = ws.open(rel)
        with ws.transaction("pending.undo_revert", name=rel):
            ws.touch(handle)
            handle.model.document.set(key, value)

    def test_the_export_drops_unsaved_edits_of_game_histories(self):
        """Regresión (MEDIO): pintar la provincia 1 del mapa del juego y exportar sin guardar dejaba la historia del
        juego editada sin guardar: ``_mod_trash`` solo mira lo del mod (``Workspace.delete`` lanza con un archivo del
        juego) y al guardar se copiaba al mod junto a la exportada (dos historias para la provincia 1). Ahora la
        exportación la revierte al archivo del juego (no queda sucia ni se guarda una copia idéntica) y lo dice el
        plan; deshacer la exportación devuelve la edición y rehacerla la vuelve a quitar."""
        p = self.project
        ws = p.ws
        game = (self.game.game_root / CAPITAL).read_bytes()
        self.edit(CAPITAL, "owner", "BBB")
        self.assertTrue(ws.peek(CAPITAL).dirty)
        world, inputs, files, extra = self.review(3)
        self.assertEqual(inputs.dropped_edits, [CAPITAL])
        self.assertNotIn(CAPITAL, inputs.mod_trash, "no es un archivo del mod: no se borra")
        self.assertNotIn(CAPITAL, files)
        plan = ex.export_plan(files, inputs, lambda rel: self.effective(rel) is not None)
        self.assertIn(ex.PlannedFile(CAPITAL, ex.ACTION_TRASH, "A", 0), plan)
        ex.apply_export(p, files, inputs, extra=extra)
        handle = ws.peek(CAPITAL)
        self.assertFalse(handle.dirty, "descartada: ni sucia ni una copia idéntica por guardar")
        self.assertEqual(self.effective(CAPITAL), game)
        ws.undo()
        self.assertTrue(ws.peek(CAPITAL).dirty)
        self.assertIn(b"owner = BBB", self.effective(CAPITAL))
        ws.redo()
        self.assertFalse(ws.peek(CAPITAL).dirty)
        self.assertTrue(p.sync_replace_paths())
        self.assertTrue(p.save().ok)
        self.assertFalse((self.game.mod_root / CAPITAL).exists(), "el archivo del juego no llega al mod")
        self.assertEqual(self.on_disk(), histories(files))
        ids = Counter(int(rel.rsplit("/", 1)[1].split(" ")[0]) for rel in self.on_disk(("history/provinces",)))
        self.assertEqual(set(ids.values()), {1}, "una historia por provincia")

    def test_a_game_unit_edited_before_a_second_export(self):
        """La papelera solo borra lo del mod (``handle.origin is None`` o de la capa MOD): un documento del juego
        bajo ``history/units`` cambiado sin guardar entre dos exportaciones no se puede borrar
        (``PermissionError`` revertía la exportación entera); se descarta con las demás ediciones del juego."""
        p = self.project
        oob = "history/units/BBB_oob.txt"
        self.export(3)
        self.edit(oob, "leader", "nadie")
        _, inputs, files, extra = self.review(5)
        self.assertNotIn(oob, files, "ningún país lo cita: la exportación no lo escribe")
        self.assertNotIn(oob, inputs.mod_trash)
        self.assertEqual(inputs.dropped_edits, [oob])
        ex.apply_export(p, files, inputs, extra=extra)      # antes de filtrar: PermissionError
        self.assertFalse(p.ws.peek(oob).dirty)
        self.assertTrue(p.save().ok)
        self.assertFalse((self.game.mod_root / oob).exists())


class LiveDescriptorTests(LiveExportCase):
    """La exportación mira el descriptor de ahora (``Project.current_descriptor``), no el que se leyó al abrir."""

    def set_descriptor(self, data: bytes) -> None:
        from vic2studio.core.vfs import DESCRIPTOR_REL

        ws = self.project.ws
        with ws.transaction("descriptor.undo_edit", field="all"):
            handle = ws.open(DESCRIPTOR_REL, create=True)
            ws.replace_text(handle, data)

    def test_a_descriptor_created_in_the_session_gets_the_replace_paths(self):
        """Regresión (MEDIO): un mod abierto sin ``.mod`` y con el descriptor creado en la sesión («Crear el
        descriptor» en la sala Proyecto) se exportaba con ``has_descriptor=False`` (el de al abrir): sin fila
        «@descriptor.mod» ni ``replace_path``, y al guardar las historias del juego seguían contando junto a las
        exportadas, el fallo de partida."""
        from vic2studio.core.modfile import DescriptorSpec, read_descriptor, render_descriptor

        self.project.close(discard=True)
        self.game.descriptor.unlink()
        self.project = p = Project.open(self.game.game_root, self.game.mod_root)
        self.assertIsNone(p.descriptor)
        name = self.game.mod_root.name
        self.set_descriptor(render_descriptor(DescriptorSpec(name, name, name)))
        _, inputs, files, extra = self.review(3)
        self.assertTrue(inputs.has_descriptor)
        self.assertIn("@descriptor.mod", [f.rel for f in ex.export_plan(files, inputs, lambda rel: False)])
        ex.apply_export(p, files, inputs, extra=extra)
        self.assertEqual(p.current_replace_paths(), ex.REPLACED_FOLDERS)
        self.assertTrue(p.sync_replace_paths())
        self.assertIsNone(p.vfs.resolve(CAPITAL), "la historia del juego ya no cuenta")
        self.assertTrue(p.save().ok)
        self.assertEqual(read_descriptor(p.vfs.descriptor_path).replace_paths, ex.REPLACED_FOLDERS)

    def test_a_descriptor_deleted_without_saving_does_not_break_the_export(self):
        """Regresión (MEDIO): con el descriptor borrado sin guardar (una lápida), ``_live_descriptor`` daba el de al
        abrir y ``_add_replace_paths`` abría el documento borrado: ``FileNotFoundError`` y la exportación entera se
        revertía. Ahora es un mod sin descriptor: ni fila «@descriptor.mod» ni ``replace_path``. Y la exportación
        mira el de ahora al aplicar: borrado después de la revisión, tampoco lanza."""
        from vic2studio.core.vfs import DESCRIPTOR_REL

        p = self.project
        ws = p.ws
        _, inputs_before, files_before, extra_before = self.review(3)
        self.assertTrue(inputs_before.has_descriptor)
        with ws.transaction("pending.undo_revert", name="descriptor"):
            ws.delete(DESCRIPTOR_REL)
        _, inputs, files, extra = self.review(3)
        self.assertFalse(inputs.has_descriptor)
        self.assertEqual(inputs.replace_paths, [])
        self.assertNotIn("@descriptor.mod", [f.rel for f in ex.export_plan(files, inputs, lambda rel: False)])
        ex.apply_export(p, files, inputs, extra=extra)      # antes: FileNotFoundError (@descriptor.mod)
        self.assertTrue(ws.peek(DESCRIPTOR_REL).deleted)
        ws.undo()
        ex.apply_export(p, files_before, inputs_before, extra=extra_before)   # revisada con él, aplicada sin él
        self.assertTrue(ws.peek(DESCRIPTOR_REL).deleted)
        self.assertEqual(p.current_replace_paths(), ())

    def test_replace_paths_written_another_way_are_not_added_again(self):
        """Regresión (BAJO): con ``replace_path = "History/Provinces"`` la exportación añadía otra línea
        ``history/provinces``: se comparaba el texto tal cual y la VFS compara la carpeta (``folder_key``)."""
        from vic2studio.core.project.codecs import codec_for
        from vic2studio.core.vfs import DESCRIPTOR_REL

        def lines():
            handle = self.project.ws.peek(DESCRIPTOR_REL)
            text = codec_for(handle.kind).snapshot(handle.model).decode("cp1252")
            return [line for line in text.splitlines() if line.startswith("replace_path")]

        self.project.close(discard=True)
        base = self.game.descriptor.read_bytes().rstrip(b"\r\n")
        self.game.descriptor.write_bytes(base + b'\r\nreplace_path = "History/Provinces"\r\n')
        self.project = p = Project.open(self.game.game_root, self.game.mod_root)
        _, inputs, files, extra = self.review(3)
        ex.apply_export(p, files, inputs, extra=extra)
        self.assertEqual(lines(), ['replace_path = "History/Provinces"', *(f'replace_path = "{f}"' for f in
                                                                           ex.REPLACED_FOLDERS[1:])])
        # Todas escritas de otra forma: nada que añadir, ni fila «@descriptor.mod» ni cambio en el descriptor.
        p.ws.undo()
        written = ("History\\Provinces/", "HISTORY/POPS", "history//units", "./history/wars", "History/Diplomacy")
        self.set_descriptor(base + b"\r\n" + b"".join(f'replace_path = "{w}"\r\n'.encode() for w in written))
        _, inputs, files, extra = self.review(3)
        self.assertNotIn("@descriptor.mod", [f.rel for f in ex.export_plan(files, inputs, lambda rel: False)])
        before = lines()
        ex.apply_export(p, files, inputs, extra=extra)
        self.assertEqual(lines(), before)


class ContinentLocalisationTests(unittest.TestCase):
    def test_an_empty_typed_continent_gets_no_localisation(self):
        """Más continentes escritos en «Continentes» de los que la partición llena: los que se quedan sin
        provincias no están en ``map/continent.txt`` y tampoco llevan fila en la localización del mapa. La partición
        no da claves a los que sobran; uno que se queda vacío en el ráster final (sus provincias pasan a otro) sí
        tiene clave, y sin ``(cont == k).any()`` tenía fila."""
        import numpy as np

        def rows(world):
            return {line.split(";", 1)[0] for line in ex.localisation(world, "TST").decode("cp1252").splitlines()}

        typed = tuple(f"Tierra {k} Norte" for k in range(30))
        world = pipeline.run_all(tiny_params(seed=3, continents=typed), tiny_install())
        keys = world.entities["continent_names"]
        self.assertLess(len(keys), len(typed), "la partición llena menos de los escritos")
        self.assertNotIn(f"tierra_{len(typed) - 1}_norte", rows(world))
        r = world.raster
        cont = r.continent.copy()
        gone = len(keys) - 1
        cont[cont == gone] = 0
        emptied = world.evolve(raster=r.evolve(continent=cont))
        filled = set(np.unique(cont[1:r.land_count + 1]).tolist())
        self.assertEqual(filled, set(range(gone)))
        found = rows(emptied)
        for k, key in enumerate(keys):
            self.assertEqual(key in found, k in filled, key)
        self.assertIn(keys[gone], rows(world), "con provincias sí la tenía")


if __name__ == "__main__":
    unittest.main()
