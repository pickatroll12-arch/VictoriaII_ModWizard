"""Taller de mapas, interfaz (wizard §18.2, iteración 9a): el asistente de punta a punta sobre el minijuego del
mapa (inventado), con los comandos en el mismo proceso (``inline``) para no depender de procesos ni de tiempos."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets)
from test_ui_entity import EntityWindowCase, WAIT_MS  # noqa: E402

from _minigame import build_map_minigame  # noqa: E402
from _mapforge_fixtures import tiny_world  # noqa: E402
from vic2studio.core.mapforge import export as ex  # noqa: E402
from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.halls.map.forge import ForgePage  # noqa: E402
from vic2studio.ui.main_window import UNSAVED_DISCARD  # noqa: E402
from vic2studio.ui.mapforge.preview import MODES, render  # noqa: E402
from vic2studio.ui.mapforge.wizard import MAP_NOT_IN_MOD, MAP_SAVED, MAP_UNSAVED, SCREEN_KEYS, SIZES  # noqa: E402
from vic2studio.ui.session_map import RASTER_READY  # noqa: E402


class ForgeCase(EntityWindowCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"VIC2STUDIO_FORGE_INLINE": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        set_language("es")
        self.addCleanup(set_language, "es")

    def open_forge(self) -> ForgePage:
        self.game = build_map_minigame(clean=True)
        self.addCleanup(self.game.cleanup)
        window = self.make_window()
        window.exec_dialog = self.dialogs
        window.ask_unsaved = mock.Mock(return_value=UNSAVED_DISCARD)
        page = window.page("project")
        page.set_game_path(self.game.game_root)
        page.set_mod_path(self.game.mod_root)
        s = window.session
        self.assertTrue(_qt.wait_until(lambda: s.project is not None and s.index_state() == "ready"
                                       and s.texts_ready() and not window.is_busy(), WAIT_MS))
        self.window = window
        forge = window.show_page("forge")
        self.assertIsInstance(forge, ForgePage)
        self.wiz = forge.wizard
        self.idle()
        return forge

    def idle(self):
        self.assertTrue(_qt.wait_until(lambda: not self.wiz.client.busy and not self.wiz._debounce.isActive(),
                                       WAIT_MS))
        _qt.process_events(20)

    def small_world(self):
        self.wiz.go("canvas")
        self.wiz.size_combo.setCurrentIndex(SIZES.index((1404, 540)))
        self.idle()
        self.assertIsNotNone(self.wiz.world)
        self.assertIsNotNone(self.wiz.world.raster)


class WizardFlowTests(ForgeCase):
    def test_learns_the_installation_when_shown(self):
        self.open_forge()
        prof = self.wiz.install
        self.assertIsNotNone(prof)
        self.assertFalse(prof.synthetic)
        self.assertIn("TAG", self.wiz.install_label.text())

    def test_generate_edit_undo_and_export(self):
        self.open_forge()
        self.small_world()
        w = self.wiz.world
        self.assertEqual(w.raster.scale, 2)          # 1404 de ancho: vista previa a W/2
        self.assertTrue(w.entities.get("owners"))    # repartido entre los TAG del minijuego
        # Pincel de relieve: una edición, el paso queda «editado» y se puede deshacer y rehacer.
        self.wiz.go("relief")
        self.wiz.tool_buttons["raise"].setChecked(True)
        self.wiz.preview.stroke.emit(0.5, 0.5, True)
        self.wiz.preview.stroke.emit(0.55, 0.5, False)
        self.wiz.preview.strokeFinished.emit()
        self.idle()
        self.assertEqual(len(self.wiz.world.edits), 1)
        self.assertEqual(self.wiz.world.steps["relief"].status, "edited")
        self.assertIn(tr("forge.status.edited"), self.wiz.steps.item(SCREEN_KEYS.index("relief")).text())
        self.wiz.undo()
        self.idle()
        self.assertEqual(len(self.wiz.world.edits), 0)
        self.wiz.redo()
        self.idle()
        self.assertEqual(len(self.wiz.world.edits), 1)
        # Renombrar desde la tabla de nombres.
        self.wiz.go("names")
        item = self.wiz.names_table.item(0, 2)
        item.setText("Villaprueba")
        self.idle()
        self.assertIn("Villaprueba", self.wiz.world.entities["province_names"])
        # Revisión: render final, plan y problemas; exportar es una transacción que se deshace entera.
        self.wiz.go("review")
        self.idle()
        self.assertIsNotNone(self.wiz.final)
        self.assertEqual(self.wiz.final.raster.scale, 1)
        self.assertGreater(len(self.wiz.review.plan), 100)
        # La revisión cabe a lo ancho en su columna (el resumen del plan se parte en líneas).
        self.window.resize(1560, 980)
        _qt.process_events(20)
        area = self.wiz.panels.currentWidget()
        self.assertLessEqual(area.widget().minimumSizeHint().width(), area.viewport().width())
        self.assertTrue(self.wiz.review.export_button.isEnabled(), [i.code for i in self.wiz.review.blocking()])
        touched = self.wiz.export()
        self.assertIn("map/provinces.bmp", touched)
        self.assertEqual(self.wiz.current(), "done")
        session = self.window.session
        self.assertTrue(session.project.ws.can_undo())
        step = session.undo()
        self.assertEqual(step.label, ex.UNDO_EXPORT)
        self.assertFalse(session.project.ws.can_undo())

    def map_raster(self):
        """El ráster del editor de mapa (Mapa › Mundo) cuando termina de cargar."""
        ms = self.window.session.map
        self.assertTrue(_qt.wait_until(lambda: ms.raster_state == RASTER_READY and ms.raster is not None, WAIT_MS))
        _qt.process_events(50)
        self.assertTrue(_qt.wait_until(lambda: ms.raster_state == RASTER_READY and ms.raster is not None, WAIT_MS))
        return ms.raster

    def test_the_exported_map_is_the_one_the_map_editor_shows_before_saving(self):
        """Regresión del vídeo del usuario: tras «Exportar al mod», «Abrir en el editor de mapa» enseñaba el mapa de
        antes hasta guardar, porque el editor (y la validación) leían el ``provinces.bmp`` del disco: los binarios
        sin guardar no iban en ``document_overrides``. Deshacer la exportación devuelve el mapa de antes."""
        from vic2studio.core.map.bmp import read_bmp

        self.open_forge()
        self.window.show_page("map:world")
        old_shape = self.map_raster().ids.shape
        self.window.show_page("forge")
        self.idle()
        self.small_world()
        self.wiz.go("review")
        self.idle()
        self.assertTrue(self.wiz.review.export_button.isEnabled(), [i.code for i in self.wiz.review.blocking()])
        self.wiz.review.export_button.click()
        self.assertEqual(self.wiz.current(), "done")
        self.assertEqual(self.wiz.map_state(), MAP_UNSAVED)
        self.assertFalse(self.wiz.open_editor.isHidden())
        self.wiz.open_editor.click()
        session = self.window.session
        exported = read_bmp(bytes(session.project.ws.peek("map/provinces.bmp").model)).pixels
        raster = self.map_raster()
        self.assertNotEqual(exported.shape[:2], old_shape)
        self.assertEqual(raster.ids.shape, exported.shape[:2], "el editor enseña el mapa exportado, sin guardar")
        self.assertEqual(raster.max_id, self.wiz.final.raster.count, "con las provincias del taller")
        step = session.undo()
        self.assertEqual(step.label, ex.UNDO_EXPORT)
        _qt.process_events(50)
        self.assertTrue(_qt.wait_until(lambda: session.map.raster is not None
                                       and session.map.raster.ids.shape == old_shape, WAIT_MS),
                        "deshecha la exportación, vuelve el mapa de antes")

    def test_the_done_screen_only_says_done_when_the_map_is_in_the_mod(self):
        """Regresión del vídeo: «13. Hecho» se abría desde la lista sin haber exportado, decía que el mapa ya era
        del mod y ofrecía «Abrir en el editor de mapa», que enseñaba el mapa viejo. Ahora dice que falta exportar
        y lleva a la revisión; tras exportar, guardar o deshacer, dice lo que hay de verdad."""
        self.open_forge()
        self.small_world()
        self.wiz.name_edit.setText("mundotest")
        self.wiz.save_project()
        self.wiz.go("done")
        self.assertEqual(self.wiz.map_state(), MAP_NOT_IN_MOD)
        self.assertEqual(self.wiz.done_text.text(), tr("forge.done.not_exported"))
        self.assertTrue(self.wiz.open_editor.isHidden(), "sin exportar no abre el mapa de antes")
        self.assertFalse(self.wiz.go_review.isHidden())
        self.wiz.go_review.click()
        self.idle()
        self.assertEqual(self.wiz.current(), "review")
        self.wiz.export()
        self.assertEqual(self.wiz.current(), "done")
        self.assertTrue(self.wiz.go_review.isHidden())
        self.assertFalse(self.wiz.open_editor.isHidden())
        self.assertIn(str(self.wiz.final.raster.count), self.wiz.done_text.text())
        # «Guardar proyecto» después de exportar no olvida lo exportado (se anota en el proyecto del taller).
        self.wiz.save_project()
        session = self.window.session
        session.save()
        _qt.process_events(50)
        self.assertEqual(self.wiz.map_state(), MAP_SAVED)
        self.assertEqual(self.wiz.done_text.text(), tr("forge.done.saved", name="mundotest"))
        # Al volver a abrir el proyecto del taller guardado, sigue sabiendo que su mapa es el del mod.
        self.wiz.on_project_opened(session.project)
        self.assertEqual(self.wiz.map_state(), MAP_NOT_IN_MOD)
        self.wiz._refresh_saved()
        names = [self.wiz.saved_list.item(i).text() for i in range(self.wiz.saved_list.count())]
        self.wiz.saved_list.setCurrentRow(names.index("mundotest"))
        self.wiz.open_saved()
        self.idle()
        self.assertEqual(self.wiz.map_state(), MAP_SAVED)

    def test_undoing_the_export_takes_the_done_screen_back(self):
        self.open_forge()
        self.small_world()
        self.wiz.go("review")
        self.idle()
        self.wiz.export()
        self.assertEqual(self.wiz.map_state(), MAP_UNSAVED)
        self.window.session.undo()
        _qt.process_events(20)
        self.assertEqual(self.wiz.map_state(), MAP_NOT_IN_MOD)
        self.assertEqual(self.wiz.done_text.text(), tr("forge.done.not_exported"))
        self.assertTrue(self.wiz.open_editor.isHidden())

    def test_a_failed_export_says_why_and_leaves_the_mod_as_it_was(self):
        """Regresión: si la exportación lanzaba, la excepción se perdía en la consola (el botón no hacía nada) y el
        usuario acababa en «13. Hecho» a mano con el mapa viejo. Ahora la revisión y la barra de estado lo dicen."""
        self.open_forge()
        self.small_world()
        self.wiz.go("review")
        self.idle()
        statuses = []
        self.wiz.status_requested.connect(lambda key, args: statuses.append((key, dict(args))))
        session = self.window.session
        from vic2studio.core.project import binary

        real, calls = binary.put_bytes, []

        def put_then_fail(ws, rel, data):
            calls.append(rel)
            if len(calls) > 20:              # a medias: ya hay archivos puestos en la transacción
                raise ValueError("carácter que el juego no tiene en «Łódź»")
            return real(ws, rel, data)

        with mock.patch.object(binary, "put_bytes", put_then_fail), \
                self.assertLogs("vic2studio.ui.mapforge.wizard", "ERROR"):
            self.wiz.review.export_button.click()
        self.assertGreater(len(calls), 20)
        self.assertEqual(self.wiz.exported, [])
        self.assertEqual(self.wiz.current(), "review", "no salta a «Hecho»")
        self.assertEqual(self.wiz.review.state_label.text(),
                         tr("forge.export.failed", error="carácter que el juego no tiene en «Łódź»"))
        self.assertEqual([k for k, _ in statuses], ["forge.export.failed"])
        self.assertFalse(session.project.ws.can_undo(), "la transacción se revirtió entera")
        self.assertEqual(list(session.project.ws.dirty()), [])

    def test_coming_back_to_the_review_after_a_change_exports_the_map_you_see(self):
        """Regresión del vídeo (lo que más probablemente le pasó al usuario): tras el render final, cambiar un valor y
        volver a «12» mientras el trabajador regeneraba dejaba el plan viejo con «Exportar al mod» activo, pero sin
        render final: el clic no hacía nada, sin aviso, y «13. Hecho» enseñaba después el mapa de antes. Ahora el
        botón se desactiva hasta rehacer la revisión, que se rehace sola, y entonces exporta el mapa de ahora."""
        self.open_forge()
        self.small_world()
        wiz = self.wiz
        wiz.go("review")
        self.idle()
        self.assertIsNotNone(wiz.final)
        old_digest = wiz.final.world_digest()
        wiz.go("relief")
        field = wiz._widgets[("relief", "land_fraction")]
        field.setValue(field.value() + 0.05)
        wiz._debounce.stop()
        wiz._regenerate_pending()
        self.assertTrue(wiz.client.busy)
        wiz.go("review")
        self.assertFalse(wiz.review.export_button.isEnabled(), "sin revisión al día no se ofrece exportar")
        self.assertEqual(wiz.review.state_label.text(), tr("forge.review.stale"))
        self.assertEqual(wiz.export(), [], "a mano tampoco: dice por qué y vuelve a preparar")
        self.idle()
        self.assertIsNotNone(wiz.final, "la revisión se rehízo sola al acabar de regenerar")
        self.assertNotEqual(wiz.final.world_digest(), old_digest)
        self.assertAlmostEqual(wiz.final.params.land_fraction, wiz.params.land_fraction)
        self.assertTrue(wiz.review.export_button.isEnabled(), [i.code for i in wiz.review.blocking()])
        wiz.review.export_button.click()
        self.assertEqual(wiz.current(), "done")
        self.assertIn("map/provinces.bmp", wiz.exported)
        self.assertEqual(wiz.map_state(), MAP_UNSAVED)

    def test_regenerating_at_the_review_disables_export_until_it_is_ready_again(self):
        self.open_forge()
        self.small_world()
        wiz = self.wiz
        wiz.go("review")
        self.idle()
        wiz.regen_from.click()
        self.assertFalse(wiz.review.export_button.isEnabled())
        self.idle()
        self.assertIsNotNone(wiz.final)
        self.assertTrue(wiz.review.export_button.isEnabled())
        self.assertIn("map/provinces.bmp", wiz.export())

    def test_a_late_final_render_of_an_older_world_is_ignored(self):
        """Con el trabajador en otro proceso, el render final pedido antes de un cambio podía llegar después y
        quedarse como el «final»: se habría exportado el mapa de antes del cambio."""
        self.open_forge()
        self.small_world()
        wiz = self.wiz
        old_world = wiz.world
        wiz.go("review")
        self.idle()
        stale_final = wiz.final
        wiz.go("relief")
        field = wiz._widgets[("relief", "land_fraction")]
        field.setValue(field.value() + 0.05)
        self.idle()
        self.assertIsNot(wiz.world, old_world)
        wiz._on_finished("final", type("R", (), {"world": stale_final})())
        self.assertIsNone(wiz.final, "la respuesta vieja no se toma como el final de ahora")

    def test_fields_show_the_real_parameters_on_first_show(self):
        """Regresión (lo vio el tutorial): al abrir el taller, cada campo enseñaba el mínimo de su rango (0
        provincias, 5 % de tierra, 1 000 000 de habitantes) y tocar uno lo metía en los parámetros: un clic arriba y
        otro abajo en las provincias daba un mundo de 13. Sin ``small_world``, que al cambiar el tamaño lo ocultaba."""
        self.open_forge()
        wiz = self.wiz
        p = wiz.params
        want = {"land_provinces": p.land_target(), "sea_provinces": p.sea_target()}
        for (screen, field), widget in wiz._widgets.items():
            with self.subTest(screen=screen, field=field):
                self.assertAlmostEqual(widget.value(), want.get(field, getattr(p, field)), places=4)
        self.assertEqual(wiz.template_combo.currentData(), p.template)
        wiz.go("canvas")
        land = wiz._widgets[("canvas", "land_provinces")]
        land.stepUp()
        land.stepDown()
        self.idle()
        self.assertEqual(wiz.params.land_target(), want["land_provinces"])
        self.assertGreater(wiz.world.raster.count, 1000)

    def test_changing_the_map_after_exporting_is_not_done(self):
        """Regresión (revisión del arreglo): tras exportar una vez, cambiar el mapa del taller y abrir «13. Hecho»
        seguía diciendo «Hecho» (con las cifras de la revisión nueva) y «Abrir en el editor de mapa» enseñaba el
        mapa de antes; «Guardar proyecto» anotaba lo exportado junto al mapa cambiado y, al volver a abrirlo, decía
        que ya estaba guardado en el mod. Deshacer el cambio vuelve a ser el mapa exportado."""
        import json

        from vic2studio.core.mapforge.project import FOLDER
        from vic2studio.ui.mapforge.wizard import MAP_CHANGED

        self.open_forge()
        self.small_world()
        wiz = self.wiz
        wiz.name_edit.setText("mundotest")
        wiz.go("review")
        self.idle()
        exported_count = wiz.final.raster.count
        wiz.export()
        self.assertEqual(wiz.map_state(), MAP_UNSAVED)
        self.assertIn(str(exported_count), wiz.done_text.text())
        # Un retoque del relieve después de exportar: el mapa del taller ya no es el del mod.
        wiz.go("relief")
        wiz.tool_buttons["raise"].setChecked(True)
        wiz.preview.stroke.emit(0.5, 0.5, True)
        wiz.preview.stroke.emit(0.55, 0.5, False)
        wiz.preview.strokeFinished.emit()
        self.idle()
        self.assertEqual(len(wiz.world.edits), 1)
        wiz.go("review")
        self.idle()
        self.assertIsNotNone(wiz.final, "la revisión del mapa cambiado está lista, pero no se ha exportado")
        wiz.go("done")
        self.assertEqual(wiz.map_state(), MAP_CHANGED)
        self.assertEqual(wiz.done_text.text(), tr("forge.done.changed"))
        self.assertTrue(wiz.open_editor.isHidden(), "no abre el mapa de antes como si fuera este")
        self.assertFalse(wiz.go_review.isHidden())
        # Deshacer el retoque: es otra vez el mapa exportado, con las cifras de lo exportado.
        wiz.undo()
        self.idle()
        self.assertEqual(len(wiz.world.edits), 0)
        wiz.go("done")
        self.assertEqual(wiz.map_state(), MAP_UNSAVED)
        self.assertIn(str(exported_count), wiz.done_text.text())
        self.assertFalse(wiz.open_editor.isHidden())
        # Rehacer el retoque y guardar el proyecto del taller: no se anota como exportado.
        wiz.redo()
        self.idle()
        wiz.save_project()
        session = self.window.session
        handle = session.project.ws.peek(f"{FOLDER}/mundotest/project.json")
        self.assertEqual(json.loads(bytes(handle.model).decode("utf-8"))["exported"], {})
        session.save()
        _qt.process_events(50)
        wiz.on_project_opened(session.project)
        wiz._refresh_saved()
        names = [wiz.saved_list.item(i).text() for i in range(wiz.saved_list.count())]
        wiz.saved_list.setCurrentRow(names.index("mundotest"))
        wiz.open_saved()
        self.idle()
        self.assertEqual(wiz.map_state(), MAP_NOT_IN_MOD, "el proyecto guardado no es el mapa del mod")

    def test_closing_the_mod_takes_the_done_screen_back(self):
        """Regresión (revisión del arreglo): con «13. Hecho» a la vista, cerrar el mod (o abrir otro) dejaba el texto
        «Hecho: … están en el mod» y «Abrir en el editor de mapa», que enseñaba el mapa del juego base."""
        self.open_forge()
        self.small_world()
        wiz = self.wiz
        wiz.go("review")
        self.idle()
        wiz.export()
        self.assertEqual(wiz.current(), "done")
        self.assertFalse(wiz.open_editor.isHidden())
        session = self.window.session
        session.close_project(discard=True)
        _qt.process_events(20)
        self.assertEqual(wiz.done_text.text(), tr("forge.done.not_exported"))
        self.assertTrue(wiz.open_editor.isHidden())
        session.open_project(self.game.game_root, self.game.mod_root)
        self.assertTrue(_qt.wait_until(lambda: session.project is not None, WAIT_MS))
        _qt.process_events(20)
        self.assertEqual(wiz.map_state(), MAP_NOT_IN_MOD)
        self.assertEqual(wiz.done_text.text(), tr("forge.done.not_exported"))
        self.assertTrue(wiz.open_editor.isHidden())
        # Abrir un proyecto (sin pasar por cerrar) también olvida lo exportado en la pantalla a la vista.
        wiz.generate()
        self.idle()
        wiz.go("review")
        self.idle()
        wiz.export()
        self.assertFalse(wiz.open_editor.isHidden())
        wiz.on_project_opened(session.project)
        self.assertEqual(wiz.done_text.text(), tr("forge.done.not_exported"))
        self.assertTrue(wiz.open_editor.isHidden())

    def test_the_review_comes_back_when_a_render_of_the_old_map_is_dropped(self):
        """Regresión (revisión del arreglo): «Regenerar desde aquí» y luego «Render final» en la revisión dejaban en
        cola un render del mapa de antes; sus archivos llegaban después del mapa nuevo, se descartaban y nadie pedía
        otro: «Exportar al mod» se quedaba desactivado con «se vuelve a preparar…» para siempre."""
        self.open_forge()
        self.small_world()
        wiz = self.wiz
        wiz.go("review")
        self.idle()
        old_world = wiz.world
        wiz.regen_from.click()
        wiz.review.render_button.click()
        self.idle()
        self.assertIsNot(wiz.world, old_world)
        self.assertIsNotNone(wiz.final, "la revisión se rehace para el mapa nuevo")
        self.assertFalse(wiz._final_stale())
        self.assertTrue(wiz.review.export_button.isEnabled(), [i.code for i in wiz.review.blocking()])

    def test_cancelling_a_regeneration_at_the_review_says_how_to_go_on(self):
        """Regresión (revisión del arreglo): cancelar «Regenerar» en la revisión dejaba el texto «se vuelve a
        preparar…», que no llegaba nunca. Ahora dice que se canceló y cómo prepararla otra vez."""
        self.open_forge()
        self.small_world()
        wiz = self.wiz
        wiz.go("review")
        self.idle()
        wiz.regen_from.click()
        self.assertTrue(wiz.client.busy)
        wiz.cancel_button.click()
        self.idle()
        self.assertEqual(wiz.review.state_label.text(), tr("forge.review.cancelled"))
        self.assertFalse(wiz.review.export_button.isEnabled())
        wiz.review.render_button.click()
        self.idle()
        self.assertTrue(wiz.review.export_button.isEnabled(), [i.code for i in wiz.review.blocking()])

    def test_world_level_creates_countries_on_export(self):
        """Iteración 9b: «Mundo» enseña sus campos, reparte la tierra entre países nuevos y la exportación los crea
        en la misma transacción que el mapa."""
        self.open_forge()
        wiz = self.wiz
        countries = wiz._widgets[("owners", "countries")]
        existing = wiz._widgets[("owners", "existing_tags")]
        self.assertTrue(countries.isHidden(), "en «Solo mapa» no se piden países nuevos")
        self.assertFalse(existing.isHidden())
        self.assertTrue(wiz._widgets[("owners", "colonized_fraction")].isHidden(), "avanzado, oculto al empezar")
        self.assertTrue(wiz.level_buttons["world"].isEnabled())
        self.assertFalse(wiz.level_buttons["overlay"].isEnabled())
        wiz.level_buttons["world"].setChecked(True)
        self.assertFalse(countries.isHidden())
        self.assertTrue(existing.isHidden())
        self.assertTrue(wiz.owners_buttons["existing_tags"].isHidden())
        countries.setValue(4)
        wiz._widgets[("owners", "culture_groups")].setValue(2)
        self.small_world()
        data = wiz.world.entities["world"]
        self.assertEqual(len(data["countries"]), 4)
        self.assertIn(data["countries"][0]["tag"], wiz.owners_stats.text())
        gallery = wiz.flag_gallery
        self.assertEqual([gallery.item(i).text() for i in range(gallery.count())],
                         [c["tag"] for c in data["countries"]])
        self.assertFalse(gallery.item(0).icon().isNull())
        wiz.go("owners")
        self.window.resize(1560, 980)
        _qt.process_events(20)
        area = wiz.panels.currentWidget()
        self.assertLessEqual(area.widget().minimumSizeHint().width(), area.viewport().width(), "cabe a lo ancho")
        wiz.go("review")
        self.idle()
        planned = {f.rel for f in wiz.review.plan}
        self.assertIn("common/cultures.txt", planned)
        touched = wiz.export()
        tags = [c["tag"] for c in data["countries"]]
        for tag in tags:
            self.assertIn(f"gfx/flags/{tag}.tga", touched)
        self.assertIn("common/countries.txt", touched)
        step = self.window.session.undo()
        self.assertEqual(step.label, ex.UNDO_EXPORT)
        self.assertFalse(self.window.session.project.ws.can_undo())

    def test_the_plan_names_the_country_files_the_export_writes(self):
        """Regresión (revisión del arreglo): con un archivo de país sin guardar (de «Nuevo país» o de otra exportación
        sin guardar), el plan de la revisión miraba solo el disco y listaba ese nombre, mientras la exportación, que
        ve lo sin guardar, escribía otro (``Nombre_TAG.txt``)."""
        from vic2studio.core.project.binary import put_bytes

        self.open_forge()
        wiz = self.wiz
        wiz.level_buttons["world"].setChecked(True)
        wiz._widgets[("owners", "countries")].setValue(3)
        self.small_world()
        wiz.go("review")
        self.idle()

        def planned_countries():
            return {f.rel for f in wiz.review.plan if f.rel.startswith("common/countries/")}

        first = sorted(planned_countries())[0]
        session = self.window.session
        with session.edit("undo.mapforge_save", name="prueba"):
            put_bytes(session.project.ws, first, b"color = { 1 2 3 }\n")
        wiz.review.render_button.click()
        self.idle()
        planned = planned_countries()
        self.assertNotIn(first, planned, "ese nombre ya lo tiene un archivo sin guardar")
        touched = wiz.export()
        self.assertEqual(planned, {rel for rel in touched if rel.startswith("common/countries/")},
                         "el plan dice los archivos que escribe la exportación")

    def test_the_states_step_shows_the_continents_as_typed(self):
        """Regresión (tercera revisión): los continentes escritos en otra escritura pasan a claves de script válidas
        (forge_continent_1) para los archivos, y el resumen de «6. Estados» enseñaba esas claves en vez de lo
        escrito."""
        self.open_forge()
        self.small_world()
        wiz = self.wiz
        wiz.go("states")
        wiz.continents_edit.setText("Европа, North America")
        wiz.continents_edit.editingFinished.emit()
        self.idle()
        keys = wiz.world.entities["continent_names"]
        self.assertEqual(keys[0], "forge_continent_1")
        text = wiz.states_stats.text()
        self.assertIn("Европа", text)
        self.assertNotIn("forge_continent_1", text)

    def test_exporting_a_review_the_mod_no_longer_matches_prepares_it_again(self):
        """Regresión (tercera revisión): la exportación calcula la papelera con el mod de ahora. Si el mod cambió
        después de la revisión (aquí, deshacer la exportación anterior), «Exportar al mod» aplicaba un plan que nadie
        había visto: mandaba a la papelera otros archivos. Ahora vuelve a preparar la revisión, lo dice y no
        exporta; el segundo clic exporta lo que dice el plan nuevo."""
        self.open_forge()
        self.small_world()
        wiz = self.wiz
        session = self.window.session
        wiz.go("review")
        self.idle()
        self.assertTrue(wiz.export())
        wiz.go("canvas")
        wiz.seed_spin.setValue(wiz.seed_spin.value() + 1)
        self.idle()
        wiz.go("review")
        self.idle()
        # La papelera de lo exportado antes pide confirmación (replace_path_mod_files_remain).
        for box in wiz.review._confirm_boxes.values():
            box.setChecked(True)
        self.assertTrue(wiz.review.export_button.isEnabled(), [i.code for i in wiz.review.blocking()])
        reviewed = wiz.inputs
        self.assertTrue(reviewed.replace_paths, "la primera exportación puso sus replace_path")
        session.undo()
        _qt.process_events(50)
        status = []
        wiz.status_requested.connect(lambda key, params: status.append(key))
        self.assertEqual(wiz.export(), [], "no se exporta un plan viejo")
        self.assertIn("forge.review.mod_changed", status)
        self.idle()
        self.assertIsNot(wiz.inputs, reviewed)
        self.assertNotEqual(wiz.inputs, reviewed)
        self.assertNotEqual(wiz.inputs.replace_paths, reviewed.replace_paths, "deshecha, el descriptor no las tiene")
        for box in wiz.review._confirm_boxes.values():
            box.setChecked(True)
        self.assertTrue(wiz.review.export_button.isEnabled(), [i.code for i in wiz.review.blocking()])
        touched = wiz.export()
        self.assertTrue(touched)
        self.assertEqual(wiz.current(), "done")

    def test_save_and_reopen_a_workshop_project(self):
        self.open_forge()
        self.small_world()
        self.wiz.name_edit.setText("prueba")
        self.wiz.save_project()
        self.assertEqual([self.wiz.saved_list.item(i).text() for i in range(self.wiz.saved_list.count())], [])
        self.window.session.save()
        self.wiz._refresh_saved()
        self.assertEqual(self.wiz.saved_list.item(0).text(), "prueba")
        digest = self.wiz.world.cells_digest()
        self.wiz.world = None
        self.wiz.saved_list.setCurrentRow(0)
        self.wiz.open_saved()
        self.idle()
        self.assertEqual(self.wiz.world.cells_digest(), digest)
        self.assertIsNotNone(self.wiz.world.raster)

    def test_size_fix_is_only_offered_when_it_works(self):
        self.open_forge()
        self.small_world()
        self.wiz.go("review")
        self.idle()
        codes = [i.code for i in self.wiz.review.issues]
        self.assertIn("forge_size", codes)
        row = codes.index("forge_size")
        self.wiz.review.tree.setCurrentItem(self.wiz.review.tree.topLevelItem(row))
        self.assertFalse(self.wiz.review.fix_button.isEnabled())   # «Rellenar con mar»: todavía no
        self.wiz.review.why_button.click()
        self.assertTrue(self.wiz.review.why_title.text())

    def test_import_bitmaps_screen(self):
        self.open_forge()
        files, _ = ex.render_files(tiny_world(3), ex.ExportInputs(prefix="FRG"))
        self.wiz.origin_buttons["bitmaps"].setChecked(True)
        self.assertTrue(self.wiz.steps.item(SCREEN_KEYS.index("relief")).isHidden())
        self.assertFalse(self.wiz.steps.item(SCREEN_KEYS.index("import")).isHidden())
        self.wiz.go("import")
        panel = self.wiz.import_panel
        for slot, rel in (("provinces", "map/provinces.bmp"), ("definition", "map/definition.csv"),
                          ("default_map", "map/default.map"), ("terrain", "map/terrain.bmp")):
            panel.set_file(slot, files[rel])
        panel.inspect_button.click()
        self.idle()
        self.assertIsNotNone(panel.report)
        self.assertTrue(panel.build_button.isEnabled())
        panel.build_button.click()
        self.idle()
        r = self.wiz.world.raster
        self.assertEqual(r.count, tiny_world(3).raster.count)
        self.assertIn(tr("forge.status.imported"), self.wiz.steps.item(SCREEN_KEYS.index("import")).text())

    def test_import_an_fmg_json_into_the_world_level(self):
        """Iteración 9b: el origen «JSON de FMG» solo enseña su ranura, y construir da los países de FMG."""
        from _mapforge_fixtures import fmg_json_full

        self.open_forge()
        wiz = self.wiz
        wiz.level_buttons["world"].setChecked(True)
        wiz.origin_buttons["fmg_json"].setChecked(True)
        panel = wiz.import_panel
        visible = [s for r, s in enumerate(panel.slots) if not panel.slot_table.isRowHidden(r)]
        self.assertEqual(visible, ["fmg_json"])
        wiz.go("canvas")
        wiz.size_combo.setCurrentIndex(SIZES.index((1404, 540)))
        self.idle()
        self.assertIsNone(wiz.world, "con un origen importado no se genera nada")
        wiz.go("import")
        panel.set_file("fmg_json", fmg_json_full())
        panel.inspect_button.click()
        self.idle()
        self.assertIsNotNone(panel.report)
        panel.build_button.click()
        self.idle()
        names = [c["name"] for c in wiz.world.entities["world"]["countries"]]
        self.assertEqual(names, ["Velmora", "Ostrand", "Kaldun"])
        self.assertIn(tr("forge.status.imported"), wiz.steps.item(SCREEN_KEYS.index("provinces")).text())
        wiz.origin_buttons["bitmaps"].setChecked(True)
        visible = [s for r, s in enumerate(panel.slots) if not panel.slot_table.isRowHidden(r)]
        self.assertNotIn("fmg_json", visible)

    def test_english_texts(self):
        self.open_forge()
        set_language("en")
        _qt.process_events(20)
        self.assertIn("Canvas", self.wiz.steps.item(SCREEN_KEYS.index("canvas")).text())
        self.assertEqual(self.wiz.quick_button.text(), "Quick generation")


class DoneScreenTests(ForgeCase):
    """La pantalla «13. Hecho» frente a mapas importados, rejillas fijadas, deshacer en ella y su coste."""

    def import_files(self, files):
        wiz = self.wiz
        wiz.go("import")
        panel = wiz.import_panel
        for slot, rel in (("provinces", "map/provinces.bmp"), ("definition", "map/definition.csv"),
                          ("default_map", "map/default.map"), ("terrain", "map/terrain.bmp")):
            panel.set_file(slot, files[rel])
        panel.inspect_button.click()
        self.idle()
        panel.build_button.click()
        self.idle()

    def export_an_import(self, name="imp"):
        from vic2studio.core.mapforge import export as ex

        self.open_forge()
        wiz = self.wiz
        files, _ = ex.render_files(tiny_world(3), ex.ExportInputs(prefix="FRG"))
        wiz.origin_buttons["bitmaps"].setChecked(True)
        self.import_files(files)
        wiz.name_edit.setText(name)
        wiz.go("review")
        self.idle()
        self.assertTrue(wiz.review.export_button.isEnabled(), [i.code for i in wiz.review.blocking()])
        wiz.export()
        self.assertEqual(wiz.map_state(), MAP_UNSAVED)
        return files

    def test_reimporting_different_bitmaps_is_not_done(self):
        """Regresión (segunda revisión): con «Importar bitmaps», el ráster sale del archivo y no de las celdas. Volver a
        importar unos bitmaps distintos (aquí solo cambian los nombres de definition.csv) daba la misma receta: «13»
        decía «Hecho» y su botón abría el mapa importado antes."""
        from vic2studio.ui.mapforge.wizard import MAP_CHANGED

        files = self.export_an_import()
        wiz = self.wiz
        lines = files["map/definition.csv"].split(b"\r\n")
        cut = lines[2].split(b";")
        cut[4] = b"Renombrada"
        lines[2] = b";".join(cut)
        self.import_files(dict(files, **{"map/definition.csv": b"\r\n".join(lines)}))
        wiz.go("done")
        self.assertEqual(wiz.map_state(), MAP_CHANGED)
        self.assertTrue(wiz.open_editor.isHidden())

    def test_looking_at_the_canvas_after_exporting_an_import_changes_nothing(self):
        """Regresión (segunda revisión): un mapa importado no fija su rejilla; pasar por «1. Lienzo» la fijaba (la misma)
        y «13» decía que el mapa había cambiado desde la exportación."""
        self.export_an_import()
        wiz = self.wiz
        self.assertIsNone(wiz.params.lattice)
        wiz.go("canvas")
        self.idle()
        wiz.go("done")
        self.assertIsNotNone(wiz.params.lattice)
        self.assertEqual(wiz.map_state(), MAP_UNSAVED)
        self.assertFalse(wiz.open_editor.isHidden())

    def test_a_reopened_imported_project_is_not_the_exported_map(self):
        """Regresión (segunda revisión): el proyecto guardado de un mapa importado no lleva el ráster del archivo; al
        abrirlo se vuelve a hacer desde las celdas y es otro mapa. «13» decía «ya está guardado»."""
        from vic2studio.ui.mapforge.wizard import MAP_CHANGED

        self.export_an_import("imp")
        wiz = self.wiz
        session = self.window.session
        session.save()
        _qt.process_events(50)
        self.assertEqual(wiz.map_state(), MAP_SAVED)
        wiz.on_project_opened(session.project)
        wiz._refresh_saved()
        names = [wiz.saved_list.item(i).text() for i in range(wiz.saved_list.count())]
        wiz.saved_list.setCurrentRow(names.index("imp"))
        wiz.open_saved()
        # Recién abierto, el mundo aún no tiene ráster (llega con la vista previa): ni así es el mapa exportado.
        self.assertIsNone(wiz.world.raster)
        self.assertEqual(wiz.map_state(), MAP_CHANGED, "antes de la vista previa")
        self.idle()
        wiz.go("done")
        self.assertEqual(wiz.map_state(), MAP_CHANGED)
        self.assertTrue(wiz.open_editor.isHidden())

    def test_undo_pressed_on_the_done_screen_updates_it(self):
        """Regresión (segunda revisión): «Deshacer» está en la barra de abajo también en «13». Deshacer un retoque
        después de exportar dejaba «Hecho» y «Abrir en el editor de mapa», que abría el mapa con el retoque."""
        from vic2studio.ui.mapforge.wizard import MAP_CHANGED

        self.open_forge()
        self.small_world()
        wiz = self.wiz
        wiz.go("relief")
        wiz.tool_buttons["raise"].setChecked(True)
        wiz.preview.stroke.emit(0.5, 0.5, True)
        wiz.preview.stroke.emit(0.55, 0.5, False)
        wiz.preview.strokeFinished.emit()
        self.idle()
        wiz.go("review")
        self.idle()
        wiz.export()
        self.assertEqual(wiz.current(), "done")
        self.assertFalse(wiz.open_editor.isHidden())
        wiz.undo_button.click()
        self.assertEqual(wiz.done_text.text(), tr("forge.done.changed"), "en el acto")
        self.assertTrue(wiz.open_editor.isHidden())
        self.idle()
        self.assertEqual(wiz.map_state(), MAP_CHANGED)
        self.assertEqual(wiz.done_text.text(), tr("forge.done.changed"))
        wiz.redo_button.click()
        self.idle()
        self.assertEqual(wiz.map_state(), MAP_UNSAVED)
        self.assertFalse(wiz.open_editor.isHidden(), "rehecho, vuelve a ser el mapa exportado")

    def test_the_done_screen_does_not_rehash_the_map_on_every_edit(self):
        """Regresión (segunda revisión): con el mod vuelto a abrir (el provinces.bmp sin abrir en el Workspace), la
        pantalla 13 leía y calculaba la huella del BMP entero en cada edición de cualquier sala (unos 40 ms con un
        mapa del tamaño de vanilla), también con el taller oculto."""
        from vic2studio.core.mapforge import project as mfp
        from vic2studio.core.project.binary import put_bytes

        self.open_forge()
        self.small_world()
        wiz = self.wiz
        wiz.name_edit.setText("coste")
        wiz.go("review")
        self.idle()
        wiz.export()
        session = self.window.session
        session.save()
        _qt.process_events(50)
        session.close_project(discard=True)
        _qt.process_events(20)
        session.open_project(self.game.game_root, self.game.mod_root)
        self.assertTrue(_qt.wait_until(lambda: session.project is not None and session.index_state() == "ready",
                                       WAIT_MS))
        self.window.show_page("forge")
        self.idle()
        wiz._refresh_saved()
        names = [wiz.saved_list.item(i).text() for i in range(wiz.saved_list.count())]
        wiz.saved_list.setCurrentRow(names.index("coste"))
        wiz.open_saved()
        self.idle()
        wiz.go("done")
        self.assertIsNone(session.project.ws.peek("map/provinces.bmp"), "el BMP no está abierto")
        self.assertEqual(wiz.map_state(), MAP_SAVED)
        hashes, states = [], []
        real_sha, real_state = mfp.sha256, wiz.map_state

        def edits(count):
            for i in range(count):
                with session.edit("undo.mapforge_save", name="x"):
                    put_bytes(session.project.ws, "map/otra_cosa.txt", f"x{i}\n".encode())
                _qt.process_events(30)

        with mock.patch.object(mfp, "sha256", lambda data: hashes.append(1) or real_sha(data)), \
                mock.patch.object(wiz, "map_state", lambda: states.append(1) or real_state()):
            edits(3)
            self.assertEqual(hashes, [], "a la vista: la huella del disco se guarda mientras el archivo no cambie")
            self.assertEqual(len(states), 3)
            self.window.show_page("map:world")
            _qt.process_events(50)
            states.clear()
            edits(3)
            self.assertEqual(states, [], "con el taller oculto no se mira")
            self.window.show_page("forge")
            _qt.process_events(50)
            self.assertEqual(len(states), 1, "al volver a enseñarlo, sí")
        self.assertEqual(wiz.done_text.text(), tr("forge.done.saved", name="coste"))


class PreviewTests(unittest.TestCase):
    def test_every_mode_renders(self):
        w = tiny_world(3)
        for mode in MODES:
            with self.subTest(mode=mode):
                img = render(w, mode, problems={1, 2})
                self.assertEqual(img.shape, w.raster.ids.shape + (3,))
                self.assertGreater(len({tuple(px) for px in img[::17, ::17].reshape(-1, 3).tolist()}), 1)


if __name__ == "__main__":
    unittest.main()
