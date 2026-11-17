"""Las salas que listan una carpeta siguen a las ``replace_path`` vivas del descriptor.

Cuando cambian las ``replace_path`` (a mano en el descriptor, fuera del Studio, al deshacer o rehacer, o con «Exportar
al mod» del taller), ``Session.documentsChanged`` solo nombra el descriptor: las salas que se rehacían solo si se
nombraba un archivo de su carpeta (las guerras de ``history/wars``, la diplomacia de ``history/diplomacy``, las ventanas
y los sprites de ``interface/``, las imágenes de ``gfx/``) seguían enseñando los archivos del juego que el juego ya no
carga, o sin los que vuelve a cargar. Ahora ``Session.replacePathsChanged`` les dice qué carpetas cambiaron, una vez,
y ``symbolsChanged`` lleva todos los tipos cuando el índice las aplica.

Sobre el minijuego (inventado) con la ventana real, como ``test_ui_wars``.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets)
from test_ui_entity import WAIT_MS, EntityWindowCase  # noqa: E402

APP = _qt.application()

from vic2studio.core.domain import war as core_war  # noqa: E402
from vic2studio.core.modfile import DescriptorSpec, apply_descriptor, descriptor_from_result  # noqa: E402
from vic2studio.core.project.binary import put_bytes  # noqa: E402
from vic2studio.core.vfs.paths import DESCRIPTOR_REL  # noqa: E402
from vic2studio.ui.countries import domain_context  # noqa: E402
from vic2studio.ui.halls.nations.countries import ROLE_TAG  # noqa: E402
from vic2studio.ui.session import replace_paths_touch  # noqa: E402

OLD_WAR = "history/wars/Old War.txt"
ALLIANCES = "history/diplomacy/Alliances.txt"
DECISIONS = "decisions/tst_decisions.txt"          # del mod: otra edición en la misma tanda que el descriptor
AAA_HISTORY = "history/countries/AAA - Aland.txt"


class ReplacePathsHallCase(EntityWindowCase):
    def edit_descriptor(self, replace_paths: tuple[str, ...], *, also=None) -> None:
        """Escribe ``replace_paths`` en el descriptor, como la sala Proyecto; ``also(ws)`` edita algo más en el
        mismo paso de deshacer (y en la misma tanda de reindexado)."""
        session = self.window.session
        ws = session.project.ws
        with session.edit("descriptor.undo_edit", field="replace_path"):
            handle = ws.open(DESCRIPTOR_REL)
            spec = DescriptorSpec.from_descriptor(descriptor_from_result(self.game.descriptor, handle.model))
            ws.touch(handle)
            apply_descriptor(handle.model.document, DescriptorSpec(spec.name, spec.folder, spec.user_dir,
                                                                   replace_paths, spec.dependencies))
            if also is not None:
                also(ws)

    def caught_up(self):
        """Espera a que el índice aplique lo último (las salas que leen el índice se rehacen entonces)."""
        session = self.window.session
        self.assertTrue(_qt.wait_until(lambda: session.index_state() == "ready" and not session._index_behind(),
                                       WAIT_MS))
        _qt.process_events(50)
        return session


class TouchTests(unittest.TestCase):
    def test_a_folder_inside_or_around_touches_and_a_sibling_does_not(self):
        self.assertTrue(replace_paths_touch({"HISTORY/WARS"}, "history/wars"))
        self.assertTrue(replace_paths_touch({"HISTORY"}, "history/wars"), "replace_recursive")
        self.assertTrue(replace_paths_touch({"GFX/PICTURES/EVENTS"}, "gfx/"), "una de dentro")
        self.assertTrue(replace_paths_touch({"INTERFACE"}, "gfx/", "interface/"))
        self.assertTrue(replace_paths_touch({""}, "history/wars"), "sin saber cuáles: todas")
        self.assertFalse(replace_paths_touch({"HISTORY/DIPLOMACY"}, "history/wars"))
        self.assertFalse(replace_paths_touch({"HISTORY/WARSHIPS"}, "history/wars"))
        self.assertFalse(replace_paths_touch(set(), "history/wars"))


class WarHallsTests(ReplacePathsHallCase):
    def wars_page(self):
        self.open_window()
        page = self.window.show_page("war:wars")
        self.caught_up()
        self.assertEqual([str(rel) for rel, _model in page.items], [OLD_WAR])
        return page

    def test_the_wars_hall_follows_a_replace_path_written_by_hand(self):
        """Regresión: con la sala Guerras a la vista, ``replace_path = "history/wars"`` escrito a mano dejaba la
        guerra del juego en la lista (y elegida) aunque la VFS ya no la resuelve; igual al deshacer y rehacer, y al
        volver a la sala si no estaba a la vista."""
        page = self.wars_page()
        session = self.window.session
        self.edit_descriptor(("history/wars",))
        _qt.process_events(20)
        self.assertIsNone(session.project.vfs.resolve(OLD_WAR))
        self.assertEqual(core_war.wars(domain_context(session)), [])
        self.assertEqual(page.items, [], "la guerra oculta ya no está en la lista")
        self.assertIsNone(page.current_rel())
        self.assertEqual(page.list.count(), 0)
        session.undo()
        _qt.process_events(20)
        self.assertEqual([str(rel) for rel, _model in page.items], [OLD_WAR], "deshacer la devuelve")
        session.redo()
        _qt.process_events(20)
        self.assertEqual(page.items, [], "rehacer la vuelve a ocultar")
        # Fuera de la vista solo se apunta: al volver, la lista es la de la vista efectiva.
        self.window.show_page("war:diplomacy")
        _qt.process_events(20)
        session.undo()
        _qt.process_events(20)
        page = self.window.show_page("war:wars")
        _qt.process_events(20)
        self.assertEqual([str(rel) for rel, _model in page.items], [OLD_WAR])

    def test_the_wars_hall_follows_a_descriptor_changed_outside_the_studio(self):
        """Otro programa añade ``replace_path = "history/wars"`` al descriptor: al recuperar el foco
        (``check_external_changes``) la sala Guerras lo sigue, esté el descriptor abierto o no."""
        page = self.wars_page()
        session = self.window.session
        descriptor = self.game.descriptor
        old = descriptor.read_bytes()
        session.project.ws._store.discard(DESCRIPTOR_REL)     # lo que hace la LRU con un documento limpio
        descriptor.write_bytes(old.rstrip(b"\r\n") + b'\r\nreplace_path = "history/wars"\r\n')
        os.utime(descriptor, ns=(10**18, 10**18))
        session.check_external_changes()
        _qt.process_events(50)
        self.assertEqual(session.project.vfs.replace_paths, ("HISTORY/WARS",))
        self.assertEqual(page.items, [])
        descriptor.write_bytes(old)
        os.utime(descriptor, ns=(2 * 10**18, 2 * 10**18))
        session.check_external_changes()
        _qt.process_events(50)
        self.assertEqual(session.project.vfs.replace_paths, ())
        self.assertEqual([str(rel) for rel, _model in page.items], [OLD_WAR])

    def test_the_diplomacy_hall_follows_a_replace_path_written_by_hand(self):
        """Regresión: ``replace_path = "history/diplomacy"`` dejaba en la tabla la alianza del juego."""
        self.open_window()
        page = self.window.show_page("war:diplomacy")
        self.caught_up()
        self.assertEqual([str(r.rel) for r in page.relations], [ALLIANCES])
        self.assertEqual(page.table.rowCount(), 1)
        session = self.window.session
        self.edit_descriptor(("history/diplomacy",))
        _qt.process_events(20)
        self.assertEqual(core_war.relations(domain_context(session)), [])
        self.assertEqual(page.relations, [])
        self.assertEqual(page.table.rowCount(), 0)
        session.undo()
        _qt.process_events(20)
        self.assertEqual([str(r.rel) for r in page.relations], [ALLIANCES])


class InterfaceHallsTests(ReplacePathsHallCase):
    def test_the_windows_hall_follows_a_replace_path_on_interface(self):
        """Regresión: ``replace_path = "interface"`` dejaba en «Ventanas» los ``.gui`` del juego."""
        self.open_window()
        page = self.window.show_page("interface:windows")
        self.caught_up()
        self.assertIn("interface/minigame.gui", [str(rel) for rel in page.files])
        self.edit_descriptor(("interface",))
        _qt.process_events(20)
        self.assertEqual(page.files, [])
        self.assertIsNone(page.rel)
        self.window.session.undo()
        _qt.process_events(20)
        self.assertIn("interface/minigame.gui", [str(rel) for rel in page.files])

    def test_the_sprites_hall_follows_a_replace_path_on_interface(self):
        """Regresión: ``replace_path = "interface"`` dejaba en «Sprites» los del juego. La sala lo vuelve a leer y
        el renderizador compartido (``RendererCache``) se rehace aunque ningún ``.gfx`` se nombre."""
        self.open_window()
        page = self.window.show_page("interface:sprites")
        self.caught_up()
        self.assertIn("GFX_mg_icon", [s.name for s in page.browser.sprites])
        self.edit_descriptor(("interface",))
        _qt.process_events(20)
        self.assertEqual(page.browser.sprites, [])
        self.window.session.undo()
        _qt.process_events(20)
        self.assertIn("GFX_mg_icon", [s.name for s in page.browser.sprites])

    def test_the_images_hall_follows_a_replace_path_on_its_folder(self):
        """Regresión: ``replace_path = "gfx/pictures/decisions"`` dejaba en «Imágenes» la del juego."""
        self.open_window()
        page = self.window.show_page("interface:images")
        manager = page.manager
        self.assertTrue(manager.select_slot("decision"))
        self.caught_up()
        names = lambda: [manager.grid.item(i).text() for i in range(manager.grid.count())]  # noqa: E731
        self.assertIn("unite_lands.dds", names())
        self.edit_descriptor(("gfx/pictures/decisions",))
        _qt.process_events(20)
        self.assertEqual(names(), [])
        self.window.session.undo()
        _qt.process_events(20)
        self.assertIn("unite_lands.dds", names())


class SymbolsAfterReplacePathsTests(ReplacePathsHallCase):
    @staticmethod
    def swatch(page, tag: str):
        """Color de la muestra de ``tag`` en la lista de la sala Países (transparente sin color)."""
        for row in range(page.list.count()):
            item = page.list.item(row)
            if item.data(ROLE_TAG) == tag:
                return item.icon().pixmap(14, 14).toImage().pixelColor(7, 7).getRgb()
        return None

    def test_the_reindex_that_applies_new_replace_paths_tells_every_kind(self):
        """Regresión: el ``symbolsChanged`` del reindexado que aplica otras ``replace_path`` llevaba solo los tipos
        de los archivos de la tanda. Con otra edición en el mismo paso (aquí, las decisiones del mod), la sala Países
        (que solo se rehace con ``tag`` o ``country_history``) no se enteraba de ``replace_path = "common/countries"``:
        AAA seguía con el color de su archivo del juego, ya oculto; y al deshacerlo, sin color."""
        self.open_window()
        page = self.window.show_page("nations:countries")
        self.caught_up()
        self.assertEqual(self.swatch(page, "AAA"), (10, 20, 30, 255), "el color de common/countries/Aland.txt")
        session = self.window.session
        decisions = session.project.vfs.read_bytes(DECISIONS)
        kinds = []
        session.symbolsChanged.connect(lambda changed: kinds.append(set(changed)))

        def touch_decisions(ws):
            put_bytes(ws, DECISIONS, decisions.replace(b"prestige = 1", b"prestige = 2"))

        self.edit_descriptor(("common/countries",), also=touch_decisions)
        self.caught_up()
        self.assertIn("tag", set().union(*kinds), "un tipo que no es de la tanda")
        self.assertEqual(self.swatch(page, "AAA"), (0, 0, 0, 0), "su archivo ya no cuenta: sin color")
        self.assertIn("AAA", page.tags(), "el TAG sigue en common/countries.txt")
        kinds.clear()
        session.undo()
        self.caught_up()
        self.assertIn("tag", set().union(*kinds))
        self.assertEqual(self.swatch(page, "AAA"), (10, 20, 30, 255), "deshecho, vuelve su color")


class ExportZipTests(ReplacePathsHallCase):
    def test_the_zip_prunes_with_the_replace_paths_of_the_descriptor_it_ships(self):
        """Regresión: la poda de copias idénticas del zip usaba las ``replace_path`` leídas al abrir el proyecto.
        Tras escribir a mano ``replace_path = "history/countries"`` y guardar, la copia del mod de la historia de
        AAA salía como idéntica a la del juego y se quedaba fuera, pero el descriptor del zip oculta la del juego:
        el mod compartido perdía la historia de AAA."""
        from vic2studio.ui.dialogs.export import ExportZipDialog

        self.open_window(mod_copies=[AAA_HISTORY])
        session = self.window.session
        self.edit_descriptor(("history/countries",))
        report = session.save()
        self.assertTrue(report.ok, report)
        self.assertEqual(session.dirty_count(), 0)
        dialog = ExportZipDialog(session, self.window)
        self.assertTrue(_qt.wait_until(lambda: dialog.plan is not None, WAIT_MS))
        dialog.prune_check.setChecked(True)
        self.assertTrue(_qt.wait_until(lambda: dialog.plan is not None, WAIT_MS))
        self.assertTrue(dialog.plan is not None and dialog.prune_check.isChecked())
        skipped = [s.rel for s in dialog.plan.skipped]
        self.assertNotIn(AAA_HISTORY, skipped, "el juego no la carga: no es una copia de sobra")
        self.assertTrue(any(m.arcname.endswith(AAA_HISTORY) for m in dialog.plan.members))
        # Sin replace_path, la misma copia sí es idéntica (la poda sigue podando).
        self.edit_descriptor(())
        self.assertTrue(session.save().ok)
        dialog.prune_check.setChecked(False)
        dialog.prune_check.setChecked(True)
        self.assertTrue(_qt.wait_until(lambda: dialog.plan is not None, WAIT_MS))
        self.assertIn(AAA_HISTORY, [s.rel for s in dialog.plan.skipped])


if __name__ == "__main__":
    unittest.main()
