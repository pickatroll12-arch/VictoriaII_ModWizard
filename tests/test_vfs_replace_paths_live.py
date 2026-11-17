"""Las ``replace_path`` de la VFS siguen al descriptor vivo (sin volver a abrir el proyecto).

``VirtualFS.set_replace_paths`` cambia las carpetas reemplazadas sin escanear; ``Project.sync_replace_paths`` las lee
del descriptor tal como está (el documento con lo sin guardar, o el archivo) y suelta los documentos limpios de
archivos del juego que quedan ocultos (``Workspace.forget_hidden``). Antes, las carpetas se fijaban al abrir y nada
las cambiaba: tras «Exportar al mod» (que las añade al descriptor) la historia del juego seguía contando.
"""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import build_layers, isolate_appdirs  # noqa: E402
from _minigame import build_map_minigame, build_minigame  # noqa: E402
from vic2studio.core.modfile import (  # noqa: E402
    DescriptorSpec,
    apply_descriptor,
    descriptor_from_result,
    read_descriptor,
)
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.vfs import DESCRIPTOR_REL, LayerKind, VirtualFS  # noqa: E402

GAME = {
    "history/provinces/north/1 - Top.txt": "owner = AAA\r\n",
    "history/provinces/east/3 - Costa.txt": "owner = CCC\r\n",
    "history/countries/AAA - Aland.txt": "capital = 1\r\n",
    "events/a.txt": "game a\r\n",
}
MOD = {"history/provinces/north/9 - Nueva.txt": "owner = AAA\r\n"}
CAPITAL = "history/provinces/north/1 - Capital.txt"     # del minijuego


class SetReplacePathsTests(unittest.TestCase):
    def build(self, **kwargs):
        layers = build_layers(game=GAME, mod=MOD)
        self.addCleanup(layers.cleanup)
        vfs = VirtualFS(layers.game_root, layers.mod_root, descriptor=layers.descriptor, **kwargs)
        vfs.scan()
        return vfs

    def test_the_view_follows_new_replace_paths_without_a_scan(self):
        vfs = self.build()
        top = "history/provinces/north/1 - Top.txt"
        # Lo listado antes queda guardado (``_listing``): también debe olvidarse.
        self.assertEqual(len(vfs.list("history/provinces")), 3)
        self.assertIsNotNone(vfs.resolve(top))
        self.assertTrue(vfs.set_replace_paths(["history\\provinces/", ""]))
        self.assertEqual(vfs.replace_paths, ("HISTORY/PROVINCES",))
        self.assertIsNone(vfs.resolve(top))
        self.assertEqual([str(e.rel) for e in vfs.list("history/provinces")], list(MOD))
        self.assertTrue(vfs.hidden_by_replace_path(vfs.stack(top)[0]))
        self.assertIn(vfs.stack(top)[0].rel.key, vfs.snapshot().hidden)
        self.assertIsNotNone(vfs.resolve("history/countries/AAA - Aland.txt"), "las otras carpetas no")
        self.assertTrue(vfs.set_replace_paths([]))
        self.assertEqual(vfs.replace_paths, ())
        self.assertEqual(len(vfs.list("history/provinces")), 3)
        self.assertEqual(vfs.snapshot().hidden, frozenset())

    def test_the_same_folders_change_nothing(self):
        vfs = self.build(replace_paths=["history/provinces"])
        listed = vfs.list("history/provinces")
        self.assertFalse(vfs.set_replace_paths(["History/Provinces/", "history\\provinces"]))
        self.assertFalse(vfs.set_replace_paths(("HISTORY/PROVINCES",)))
        self.assertEqual(vfs.list("history/provinces"), listed)

    def test_replace_recursive_still_applies(self):
        vfs = self.build(replace_recursive=False)
        self.assertTrue(vfs.set_replace_paths(["history"]))
        self.assertIsNotNone(vfs.resolve("history/provinces/north/1 - Top.txt"), "sin recursión, las subcarpetas no")


class ProjectSyncReplacePathsTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)
        self.game = build_minigame()
        self.addCleanup(self.game.cleanup)
        self.project = Project.open(self.game.game_root, self.game.mod_root)
        self.addCleanup(self.project.close)

    def set_replace(self, replace_paths: tuple[str, ...]) -> None:
        ws = self.project.ws
        with ws.transaction("descriptor.undo_edit", field="replace_path"):
            handle = ws.open(DESCRIPTOR_REL)
            spec = DescriptorSpec.from_descriptor(descriptor_from_result(self.game.descriptor, handle.model))
            ws.touch(handle)
            apply_descriptor(handle.model.document, DescriptorSpec(spec.name, spec.folder, spec.user_dir,
                                                                   replace_paths, spec.dependencies))

    def test_follows_the_unsaved_descriptor_undo_save_and_the_file(self):
        project = self.project
        vfs = project.vfs
        self.assertEqual(project.current_replace_paths(), ())
        self.assertFalse(project.sync_replace_paths(), "sin cambios")
        self.set_replace(("history/provinces",))
        self.assertEqual(vfs.replace_paths, (), "la VFS no cambia sola")
        self.assertEqual(project.current_replace_paths(), ("history/provinces",))
        self.assertTrue(project.sync_replace_paths())
        self.assertEqual(vfs.replace_paths, ("HISTORY/PROVINCES",))
        self.assertIsNone(vfs.resolve(CAPITAL))
        self.assertFalse(project.sync_replace_paths(), "otra vez: nada que cambiar")
        project.ws.undo()
        self.assertTrue(project.sync_replace_paths())
        self.assertEqual(vfs.replace_paths, ())
        self.assertIsNotNone(vfs.resolve(CAPITAL))
        project.ws.redo()
        self.assertTrue(project.sync_replace_paths())
        self.assertTrue(project.save().ok)
        self.assertFalse(project.sync_replace_paths(), "guardar no cambia lo que dice el descriptor")
        self.assertIn(b'replace_path = "history/provinces"', self.game.descriptor.read_bytes())
        # Sin el documento abierto, el archivo.
        project.ws._store.discard(DESCRIPTOR_REL)
        self.assertEqual(project.current_replace_paths(), ("history/provinces",))
        self.assertFalse(project.sync_replace_paths())

    def test_a_deleted_descriptor_replaces_nothing(self):
        """Borrado sin guardar no hay descriptor: ninguna carpeta reemplazada, aunque el archivo del disco (guardado
        antes con ``replace_path``) siga ahí. Con un descriptor guardado sin carpetas, «ninguna» y «las del disco» no
        se distinguían."""
        project = self.project
        self.set_replace(("history/provinces",))
        self.assertTrue(project.sync_replace_paths())
        self.assertTrue(project.save().ok)
        self.assertIn(b'replace_path = "history/provinces"', self.game.descriptor.read_bytes())
        self.assertIsNone(project.vfs.resolve(CAPITAL))
        with project.ws.transaction("pending.undo_revert", name="descriptor"):
            project.ws.delete(DESCRIPTOR_REL)
        self.assertTrue(self.game.descriptor.is_file(), "sin guardar: el archivo sigue")
        self.assertIsNone(project.current_descriptor())
        self.assertEqual(project.current_replace_paths(), ())
        self.assertTrue(project.sync_replace_paths())
        self.assertEqual(project.vfs.replace_paths, ())
        self.assertIsNotNone(project.vfs.resolve(CAPITAL), "la historia del juego vuelve a contar")

    def test_clean_game_documents_that_become_hidden_are_dropped(self):
        """Un documento limpio del juego abierto antes (la ficha de una provincia) se suelta al quedar oculto: si no,
        ``open`` lo seguía dando y ``core.schema.Entities`` lo contaba en la vista efectiva."""
        project = self.project
        ws = project.ws
        capital = ws.open(CAPITAL)
        self.assertIs(capital.origin.layer.kind, LayerKind.GAME)
        edited = ws.open("history/provinces/south/2  Llanura.txt")
        with ws.transaction("pending.undo_revert", name="2"):
            ws.touch(edited)
            edited.model.document.set("owner", "CCC")
        self.set_replace(("history/provinces",))
        self.assertTrue(project.sync_replace_paths())
        self.assertIsNone(ws.peek(CAPITAL), "limpio y oculto: fuera")
        with self.assertRaises(FileNotFoundError):
            ws.open(CAPITAL)
        self.assertIs(ws.peek(edited.rel), edited, "uno sucio se queda (se escribirá en el mod)")
        project.ws.undo()       # el descriptor
        self.assertTrue(project.sync_replace_paths())
        self.assertIsNot(ws.open(CAPITAL), capital, "vuelve a abrirse del juego")

    def test_forget_hidden_keeps_documents_of_the_undo_stack(self):
        project = self.project
        ws = project.ws
        capital = ws.open(CAPITAL)
        with ws.transaction("pending.undo_revert", name="1"):
            ws.touch(capital)
            capital.model.document.set("owner", "CCC")
        ws.undo()
        self.assertFalse(capital.dirty)
        self.assertTrue(project.vfs.set_replace_paths(["history/provinces"]))
        self.assertEqual(ws.forget_hidden(), [], "lo nombra la pila de rehacer")
        self.assertIs(ws.peek(CAPITAL), capital)

    def test_writing_at_the_path_of_a_hidden_document_of_the_undo_stack_reuses_it(self):
        """Regresión (tercera revisión): escribir (``put_bytes``, una exportación) en la ruta de un documento del juego
        oculto que la pila nombra creaba otro documento, sin origen. Al deshacerlo todo, los estados del juego caían en
        ese documento nuevo: quedaba sucio y guardar copiaba la historia del juego en el mod."""
        from vic2studio.core.project.binary import put_bytes

        project = self.project
        ws = project.ws
        capital = ws.open(CAPITAL)
        with ws.transaction("pending.undo_revert", name="1"):
            ws.touch(capital)
            capital.model.document.set("owner", "CCC")
        with ws.transaction("pending.undo_revert", name="1"):
            ws.revert(CAPITAL)
        self.assertFalse(capital.dirty)
        self.set_replace(("history/provinces",))
        self.assertTrue(project.sync_replace_paths())
        with ws.transaction("pending.undo_revert", name="1"):
            put_bytes(ws, CAPITAL, b"owner = BBB\r\n")
        self.assertIs(ws.peek(CAPITAL), capital, "el mismo documento")
        self.assertTrue(capital.dirty)
        for _ in range(4):
            ws.undo()
            project.sync_replace_paths()
        self.assertFalse(ws.can_undo())
        self.assertEqual([str(h.rel) for h in ws.dirty()], [])
        self.assertTrue(project.save().ok)
        self.assertFalse((self.game.mod_root / CAPITAL).exists(), "nada del juego copiado al mod")

    def test_a_hidden_document_of_the_undo_stack_is_not_effective(self):
        """Regresión (BAJO): un documento limpio del juego que la pila de deshacer nombra sigue en el ``Workspace``
        al quedar oculto (``forget_hidden`` no lo suelta), pero no es de la vista efectiva: ``open`` lo daba, la
        lista de documentos lo contaba y la ficha de la provincia (``Provinces.record``) leía el archivo que el
        juego ya no carga. Ahora no cuenta; rehacer su cambio lo vuelve a poner (sucio, se escribirá en el mod) y
        deshacerlo lo oculta otra vez."""
        from vic2studio.core.domain.province import Provinces
        from vic2studio.core.index import build_index
        from vic2studio.core.locsync import LocSync
        from vic2studio.core.project.codecs import codec_for
        from vic2studio.core.rules.game import GameRules
        from vic2studio.core.schema import Entities

        project = self.project
        ws = project.ws
        capital = ws.open(CAPITAL)
        with ws.transaction("pending.undo_revert", name="1"):
            ws.touch(capital)
            capital.model.document.set("owner", "CCC")
        ws.undo()
        # Otro programa añade la carpeta al descriptor (sin abrir en el Workspace): la pila de rehacer sigue entera.
        descriptor = self.game.descriptor
        descriptor.write_bytes(descriptor.read_bytes().rstrip(b"\r\n") + b'\r\nreplace_path = "history/provinces"\r\n')
        self.assertTrue(project.sync_replace_paths())
        self.assertIs(ws.peek(CAPITAL), capital, "la pila de rehacer lo nombra: sigue en el Workspace")
        self.assertNotIn(CAPITAL, [str(h.rel) for h in ws.documents()])
        snapshot = project.vfs.snapshot()
        index = build_index(snapshot, None)
        entities = Entities(ws, index, LocSync(ws, project.vfs, prefix=project.settings.prefix))
        self.assertIsNone(Provinces(entities, GameRules.from_snapshot(snapshot)).record(1))
        with self.assertRaises(FileNotFoundError):
            ws.open(CAPITAL)
        self.assertTrue(ws.can_redo())
        ws.redo()
        self.assertIs(ws.open(CAPITAL), capital, "rehacer lo recupera")
        self.assertTrue(capital.dirty)
        self.assertIn(b"owner = CCC", codec_for(capital.kind).snapshot(capital.model))
        ws.undo()
        self.assertFalse(capital.dirty)
        self.assertNotIn(CAPITAL, [str(h.rel) for h in ws.documents()])
        with self.assertRaises(FileNotFoundError):
            ws.open(CAPITAL)


class ExportReadsTheLiveDescriptorTests(unittest.TestCase):
    """«Exportar al mod» añade sus ``replace_path`` al descriptor de ahora, no al que se leyó al abrir el proyecto
    (``project.descriptor``): este se quedaba atrás y la exportación deshacía lo editado después en la sala Proyecto
    (el nombre, una ``replace_path`` puesta a mano)."""

    def setUp(self):
        isolate_appdirs(self)
        self.game = build_map_minigame(clean=True)
        self.addCleanup(self.game.cleanup)
        self.project = Project.open(self.game.game_root, self.game.mod_root)
        self.addCleanup(self.project.close)

    def edit(self, **changes) -> None:
        ws = self.project.ws
        with ws.transaction("descriptor.undo_edit", field="all"):
            handle = ws.open(DESCRIPTOR_REL)
            spec = DescriptorSpec.from_descriptor(descriptor_from_result(self.game.descriptor, handle.model))
            ws.touch(handle)
            apply_descriptor(handle.model.document, replace(spec, **changes))

    def live(self):
        """El descriptor de ahora: el documento abierto o, si no lo está, el archivo."""
        handle = self.project.ws.peek(DESCRIPTOR_REL)
        if handle is None:
            return read_descriptor(self.game.descriptor)
        return descriptor_from_result(self.game.descriptor, handle.model)

    def export(self):
        from _mapforge_fixtures import tiny_params
        from vic2studio.core.mapforge import export as ex, install, pipeline

        project = self.project
        world = pipeline.run_all(tiny_params(existing_tags=2), install.learn_install(install.source_from_vfs(
            project.vfs)))
        inputs = ex.gather_inputs(project, world)
        files, _ = ex.render_files(world, inputs)
        ex.apply_export(project, files, inputs)
        return inputs

    def test_the_export_keeps_what_was_edited_in_the_descriptor(self):
        from vic2studio.core.mapforge import export as ex

        self.edit(name="Otro nombre", replace_paths=("common/countries",))
        inputs = self.export()
        self.assertEqual(inputs.replace_paths, ["common/countries"])
        live = self.live()
        self.assertEqual(live.name, "Otro nombre")
        self.assertEqual(live.replace_paths, ("common/countries", *ex.REPLACED_FOLDERS))
        # Guardado y exportado otra vez: ya tiene sus carpetas (no hay fila «@descriptor.mod» ni cambio).
        self.assertTrue(self.project.save().ok)
        self.project.ws._store.discard(DESCRIPTOR_REL)      # sin abrir: se lee del archivo
        inputs = self.export()
        self.assertEqual(inputs.replace_paths, ["common/countries", *ex.REPLACED_FOLDERS])
        self.assertNotIn("@descriptor.mod", [f.rel for f in ex.export_plan({}, inputs, lambda rel: False)])
        self.assertEqual(self.live().name, "Otro nombre")


if __name__ == "__main__":
    unittest.main()
