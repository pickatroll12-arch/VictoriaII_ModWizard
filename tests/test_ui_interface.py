"""Sala Interfaz de la iteración 8 (wizard §17.2, §17.3): Ventanas, Sprites e Imágenes, y la vista previa de
eventos con el ``.gui`` real. La ventana de verdad sobre el minijuego con los archivos de interfaz inventados de
``_interface_fixtures`` como archivos del juego (como un ``.gui`` de vanilla).
"""

from __future__ import annotations

import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets)
from test_ui_entity import EntityWindowCase  # noqa: E402

APP = _qt.application()

from PIL import Image  # noqa: E402
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402

from _interface_fixtures import INTERFACE_FILES, PANEL_GUI  # noqa: E402
from test_ui_event_studio import EventStudioCase  # noqa: E402
from vic2studio.core.gfx.dds import read_dds  # noqa: E402
from vic2studio.core.schema import RecordRef  # noqa: E402
from vic2studio.core.vfs import VPath  # noqa: E402
from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.halls.interface.images import ImagesPage  # noqa: E402
from vic2studio.ui.halls.interface.sprites import SpritesPage  # noqa: E402
from vic2studio.ui.halls.interface.windows import WindowsPage  # noqa: E402
from vic2studio.ui.halls.registry import discover_halls, hosting_section  # noqa: E402

PANEL = "interface/mg_panel.gui"
EVENT_GUI = "interface/event_country_window.gui"
ALT_ICON = "mg_panel_window/mg_alt_icon"


def changed(before: str, after: str) -> list[tuple[str, str]]:
    a, b = before.split("\r\n"), after.split("\r\n")
    assert len(a) == len(b), (len(a), len(b))
    return [(x, y) for x, y in zip(a, b) if x != y]


class InterfaceWindowCase(EntityWindowCase):
    def open_interface(self, section: str = "windows", **kwargs):
        files = dict(INTERFACE_FILES)
        files.update(kwargs.pop("game_files", {}) or {})
        self.open_window(game_files=files, **kwargs)
        page = self.window.show_page(f"interface:{section}")
        self.settle()
        return page

    def history(self) -> list:
        return list(self.window.session.history())


class HallTests(unittest.TestCase):
    def test_the_three_sections_exist_and_host_their_schemas(self):
        found = {f"{hall.key}:{section.key}": section for hall, sections in discover_halls() for section in sections}
        for key in ("interface:windows", "interface:sprites", "interface:images"):
            self.assertFalse(found[key].planned, key)
        self.assertEqual(hosting_section("gui_button"), "interface:windows")
        self.assertEqual(hosting_section("gui_shield"), "interface:windows")
        self.assertEqual(hosting_section("sprite"), "interface:sprites")
        generated = [s for k, s in found.items() if k.startswith("interface:") and s.schema_kind]
        self.assertEqual(generated, [], "los esquemas gui_* y sprite no generan páginas propias")


class WindowsPageTests(InterfaceWindowCase):
    def open_panel(self) -> WindowsPage:
        page = self.open_interface()
        self.assertIsInstance(page, WindowsPage)
        self.assertTrue(page.select_file(PANEL))
        self.settle()
        return page

    def test_files_windows_tree_and_canvas(self):
        page = self.open_panel()
        names = [page.file_combo.itemText(i) for i in range(page.file_combo.count())]
        self.assertIn("mg_panel.gui", names)
        self.assertIn("event_country_window.gui", names)
        self.assertEqual(page.window_path, "mg_panel_window")
        paths = set(page.canvas.items_by_path)
        self.assertTrue({"mg_panel_window", ALT_ICON, "mg_panel_window/mg_inner/mg_label",
                         "mg_panel_window/mg_anchor"} <= paths)
        self.assertEqual(set(page.tree.items_by_path), paths, "árbol y lienzo enseñan los mismos elementos")
        self.assertEqual([page.screen_combo.itemText(i) for i in range(page.screen_combo.count())],
                         ["1024×768", "1280×720", "1920×1080"])
        self.assertEqual(page.screen(), (1024, 768))
        self.assertIn("mg_panel.gui", page.info_label.text())
        self.assertEqual(page.info_label.text(), tr("interface.windows.from_game", file=PANEL, count=len(paths)))
        image = page.canvas.grab()
        self.assertGreater(image.width(), 100)

    def test_choosing_in_the_tree_selects_on_the_canvas_and_binds_the_form(self):
        page = self.open_panel()
        page.tree.items_by_path[ALT_ICON].setSelected(True)
        _qt.process_events(10)
        self.assertEqual(page.canvas.selected_path(), ALT_ICON)
        form = page.current_form()
        self.assertIsNotNone(form)
        self.assertEqual(form.schema.kind, "gui_icon")
        self.assertEqual(form.ref, RecordRef("gui_icon", ALT_ICON, VPath.of(PANEL)))
        page.select_element("mg_panel_window/mg_inner")
        self.assertEqual(page.tree.selected_path(), "mg_panel_window/mg_inner")
        self.assertEqual(page.current_form().schema.kind, "gui_window")
        self.assertTrue(page.hide_button.isEnabled())
        page.select_element("mg_panel_window")
        self.assertFalse(page.hide_button.isEnabled(), "la ventana entera no se oculta")

    def drag(self, page: WindowsPage, path: str, dx: int, dy: int) -> None:
        """Arrastra el elemento con el ratón de verdad (eventos del visor)."""
        canvas = page.canvas
        canvas.resetTransform()
        item = canvas.items_by_path[path]
        canvas.centerOn(item)
        start = canvas.mapFromScene(item.scenePos() + QPointF(4, 4))
        end = canvas.mapFromScene(item.scenePos() + QPointF(4 + dx, 4 + dy))
        viewport = canvas.viewport()

        def send(kind, point, buttons):
            event = QMouseEvent(kind, QPointF(point), QPointF(viewport.mapToGlobal(point)), Qt.MouseButton.LeftButton,
                                buttons, Qt.KeyboardModifier.NoModifier)
            APP.sendEvent(viewport, event)

        send(QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)
        send(QEvent.Type.MouseMove, QPoint((start.x() + end.x()) // 2, (start.y() + end.y()) // 2),
             Qt.MouseButton.LeftButton)
        send(QEvent.Type.MouseMove, end, Qt.MouseButton.LeftButton)
        send(QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton)
        _qt.process_events(20)
        self.settle()

    def test_dragging_changes_only_the_position_line_in_one_undo_step(self):
        page = self.open_panel()
        self.drag(page, ALT_ICON, 16, 8)
        self.assertEqual(changed(PANEL_GUI, self.text_of(PANEL)),
                         [("\t\t\tposition = { x = 40 y = 50 }", "\t\t\tposition = { x = 56 y = 58 }")])
        self.assertEqual(len(self.history()), 1)
        self.assertEqual(page.element_path, ALT_ICON, "el elemento sigue elegido tras rehacer la escena")
        self.assertEqual(page.canvas.items_by_path[ALT_ICON].pos().x() - page.canvas.items_by_path[
            "mg_panel_window"].pos().x(), 56)
        self.assertEqual(page.info_label.text(),
                         tr("interface.windows.copied", file=PANEL, count=len(page.canvas.items_by_path)))
        self.window.undo()
        self.settle()
        self.assertEqual(self.text_of(PANEL), PANEL_GUI)

    def test_snap_rounds_the_drag_to_the_grid(self):
        page = self.open_panel()
        page.snap_check.setChecked(True)
        self.drag(page, ALT_ICON, 13, 3)
        # El elemento estaba en (40+20, 50+30) de la pantalla: el imán lo deja en múltiplos de 8.
        line = [b for _a, b in changed(PANEL_GUI, self.text_of(PANEL))]
        self.assertEqual(len(line), 1)
        x = page.document.find(ALT_ICON).position[0] + 20
        y = page.document.find(ALT_ICON).position[1] + 30
        self.assertEqual((x % 8, y % 8), (0, 0), line)

    def test_resize_and_hide_are_one_line_and_one_step_each(self):
        page = self.open_panel()
        self.assertTrue(page.resize_element("mg_panel_window/mg_inner", 120, 80))
        self.assertEqual(changed(PANEL_GUI, self.text_of(PANEL)),
                         [("\t\t\tsize = { x = 100 y = 60 }", "\t\t\tsize = { x = 120 y = 80 }")])
        page.select_element("mg_panel_window/mg_inner/mg_label")
        self.assertTrue(page.hide_selected())
        lines = changed(PANEL_GUI, self.text_of(PANEL))
        self.assertEqual(lines[1], ("\t\t\t\tposition = { x = 5 y = 5 }", "\t\t\t\tposition = { x = -4000 y = -4000 }"))
        self.assertEqual(len(self.history()), 2)
        self.assertEqual(page.element_path, "mg_panel_window/mg_inner/mg_label")
        self.window.undo()
        self.window.undo()
        self.settle()
        self.assertEqual(self.text_of(PANEL), PANEL_GUI)

    def test_the_resize_handle_emits_the_new_size(self):
        page = self.open_panel()
        page.select_element("mg_panel_window/mg_inner")
        item = page.canvas.items_by_path["mg_panel_window/mg_inner"]
        self.assertTrue(item.handle.isVisible())
        seen = []
        page.canvas.resized.connect(lambda *args: seen.append(args))
        item.set_box(130, 70)
        item.handle._size = (100.0, 60.0)
        item.handle._start = QPointF(0, 0)
        item.handle.mouseReleaseEvent(mock.Mock())
        self.assertEqual(seen, [("mg_panel_window/mg_inner", 130, 70)])
        self.settle()
        self.assertIn("\t\t\tsize = { x = 130 y = 70 }", self.text_of(PANEL))

    def test_saving_copies_the_whole_game_file_into_the_mod(self):
        page = self.open_panel()
        self.assertTrue(page.move_element(ALT_ICON, 7, -3))
        self.window.session.save()
        self.settle()
        copy = (self.game.mod_root / PANEL).read_bytes().decode("cp1252")
        self.assertEqual(changed(PANEL_GUI, copy),
                         [("\t\t\tposition = { x = 40 y = 50 }", "\t\t\tposition = { x = 47 y = 47 }")])
        self.assertEqual(page.info_label.text(),
                         tr("interface.windows.from_mod", file=PANEL, count=len(page.canvas.items_by_path)))

    def test_the_screen_size_moves_anchored_elements(self):
        page = self.open_interface()
        self.assertTrue(page.select_file(EVENT_GUI))
        self.settle()
        window = page.canvas.items_by_path["Event_Country_Window"]
        small = window.pos()
        page.select_screen((1920, 1080))
        self.assertEqual(page.canvas.sceneRect().size().toTuple(), (1920.0, 1080.0))
        big = page.canvas.items_by_path["Event_Country_Window"].pos()
        self.assertEqual((small.x(), small.y()), (1024 / 2 - 260, 768 / 2 - 250), "anclada al centro")
        self.assertEqual((big.x(), big.y()), (1920 / 2 - 260, 1080 / 2 - 250))

    def test_a_problem_on_an_element_opens_it(self):
        self.open_interface("images")
        self.assertTrue(self.window.open_entity("gui_icon", ALT_ICON, ("orientation",), VPath.of(PANEL)))
        page = self.window.current_page()
        self.assertIsInstance(page, WindowsPage)
        self.assertEqual(page.rel, VPath.of(PANEL))
        self.assertEqual(page.element_path, ALT_ICON)
        self.assertEqual(page.current_form().ref.ident, ALT_ICON)

    def test_the_form_edits_the_element(self):
        page = self.open_panel()
        page.select_element(ALT_ICON)
        form = page.current_form()
        self.assertTrue(form._commit_field("orientation", "UPPER_LEFT"))
        self.settle()
        self.assertEqual(changed(PANEL_GUI, self.text_of(PANEL)),
                         [('\t\t\tOrientation = "UPPERL_LEFT"', '\t\t\tOrientation = "UPPER_LEFT"')])
        self.assertIn(ALT_ICON, page.canvas.items_by_path, "el lienzo se rehace con el cambio")

    def test_without_game_art_the_canvas_is_procedural(self):
        with mock.patch.dict(os.environ, {"VIC2STUDIO_NO_GAME_ART": "1"}):
            page = self.open_panel()
            from vic2studio.ui.interface import renderer_of

            self.assertFalse(renderer_of(self.window.session).game_art)
            self.assertIn(ALT_ICON, page.canvas.items_by_path)

    def test_texts_follow_the_language(self):
        page = self.open_panel()
        set_language("en")
        self.addCleanup(set_language, "es")
        _qt.process_events(10)
        self.assertEqual(page.hide_button.text(), "Hide")
        self.assertEqual(page.grid_check.text(), "Grid")
        self.assertIn("comes from the game", page.info_label.text())


class SpritesPageTests(InterfaceWindowCase):
    def open_sprites(self) -> SpritesPage:
        page = self.open_interface("sprites")
        self.assertIsInstance(page, SpritesPage)
        page.browser.finish()
        return page

    def names(self, page) -> list[str]:
        return [page.browser.grid.item(i).text() for i in range(page.browser.grid.count())]

    def test_grid_search_filters_and_detail(self):
        page = self.open_sprites()
        browser = page.browser
        self.assertIn("GFX_mg_panel", self.names(page))
        browser.search.setText("panel")
        self.assertEqual(self.names(page), ["GFX_mg_panel"])
        browser.search.setText("")
        browser.only_duplicates.setChecked(True)
        self.assertEqual(sorted(name.lower() for name in self.names(page)), ["gfx_mg_twice", "gfx_mg_twice"])
        self.assertIn(tr("interface.sprites.duplicate", places="")[:12], browser.detail.text())
        browser.only_duplicates.setChecked(False)
        browser.only_missing.setChecked(True)
        self.assertEqual(self.names(page), ["GFX_mg_lost"])
        self.assertIn(tr("interface.sprites.texture_missing"), browser.detail.text())
        browser.only_missing.setChecked(False)
        index = browser.file_filter.findData("interface/mg_extra.gfx")
        browser.file_filter.setCurrentIndex(index)
        self.assertEqual(self.names(page), ["GFX_MG_TWICE"])
        browser.file_filter.setCurrentIndex(0)
        self.assertTrue(browser.select("GFX_mg_alt"))
        self.assertIn("gfx/interface/mg_alt.dds", browser.detail.text(), "la otra extensión")
        self.assertTrue(browser.select("GFX_event_country_button"))
        usages = [browser.usages.item(i).text() for i in range(browser.usages.count())]
        self.assertTrue(any(text.startswith(PANEL) for text in usages), usages)
        self.assertTrue(any(text.startswith(EVENT_GUI) for text in usages), usages)
        self.assertIsNotNone(browser.preview.pixmap())

    def test_a_usage_opens_the_window_with_its_element(self):
        page = self.open_sprites()
        browser = page.browser
        browser.select("GFX_mg_alt")
        browser._on_usage(browser.usages.item(0))
        self.settle()
        windows = self.window.current_page()
        self.assertIsInstance(windows, WindowsPage)
        self.assertEqual(windows.element_path, ALT_ICON)

    def test_new_sprite_writes_a_readable_dds_and_its_definition_in_one_step(self):
        page = self.open_sprites()
        dialog = page.new_sprite_dialog()
        self.assertFalse(dialog.create_button.isEnabled(), "sin imagen no se puede")
        image = Image.new("RGBA", (64, 32), (10, 200, 30, 255))
        dialog.set_image(image, "mi icono")
        self.assertEqual(dialog.name_edit.text(), "GFX_testmod_mi_icono")
        dialog.frames_spin.setValue(2)
        self.assertIn("gfx/interface/", dialog.plan_label.text())
        created = dialog.create()
        self.assertIsNotNone(created, dialog.error_label.text())
        dialog.accept()
        self.settle()
        session = self.window.session
        self.assertEqual(len(self.history()), 1)
        data = session.project.ws.open(created.texture).model
        self.assertEqual(read_dds(bytes(data)).rgba.shape, (32, 64, 4))
        gfx = self.text_of(created.gfx)
        self.assertIn('name = "GFX_testmod_mi_icono"', gfx)
        self.assertIn("noOfFrames = 2", gfx)
        self.assertEqual(page.browser.current_name(), "GFX_testmod_mi_icono")
        frame = page.browser.renderer().sprite_image("GFX_testmod_mi_icono")
        self.assertEqual(frame.size, (32, 32), "la textura sin guardar ya se ve, partida en 2 fotogramas")
        self.window.undo()
        self.settle()
        self.assertIsNone(page.browser.renderer().sprites.get("GFX_testmod_mi_icono"))

    def test_new_sprite_explains_its_errors(self):
        page = self.open_sprites()
        dialog = page.new_sprite_dialog()
        dialog.set_image(Image.new("RGBA", (30, 10)), "x")
        dialog.name_edit.setText("GFX_mg_panel")
        self.assertIsNone(dialog.create())
        self.assertEqual(dialog.error_label.text(), tr("gui.sprite_error.taken", name="GFX_mg_panel"))
        dialog.name_edit.setText("GFX_ok")
        dialog.frames_spin.setValue(4)
        self.assertIsNone(dialog.create())
        self.assertEqual(dialog.error_label.text(), tr("gui.sprite_error.bad_frames", frames=4, width=30))
        self.assertEqual(self.history(), [])

    def test_a_problem_on_a_sprite_opens_it(self):
        self.open_interface("images")
        self.assertTrue(self.window.open_entity("sprite", "GFX_mg_alt"))
        page = self.window.current_page()
        self.assertIsInstance(page, SpritesPage)
        self.assertEqual(page.browser.current_name(), "GFX_mg_alt")


class ImagesPageTests(InterfaceWindowCase):
    def test_families_and_import_with_the_real_frame(self):
        page = self.open_interface("images")
        self.assertIsInstance(page, ImagesPage)
        manager = page.manager
        self.assertEqual(manager.slots.count(), 6)
        self.assertTrue(manager.select_slot("event"))
        self.assertIn("521×203", manager.slot_info.text())
        dialog = manager.import_dialog()
        dialog.set_image(Image.new("RGBA", (400, 300), (200, 120, 40, 255)), "mg_puerto_nuevo")
        preview = dialog.preview_image()
        self.assertGreater(preview.size[1], 300, "la vista previa es la ventana del evento con la imagen dentro")
        rel = dialog.do_import()
        self.assertEqual(rel, VPath.of("gfx/pictures/events/mg_puerto_nuevo.tga"))
        dialog.accept()
        self.settle()
        self.assertEqual(len(self.history()), 1)
        data = self.window.session.project.ws.open(rel).model
        with Image.open(io.BytesIO(bytes(data))) as written:
            self.assertEqual(written.size, (521, 203))
        self.assertTrue(manager.select_picture("mg_puerto_nuevo.tga"))
        self.assertIn("521×203", manager.detail.text())

    def test_decisions_are_dds_and_names_are_checked(self):
        page = self.open_interface("images")
        manager = page.manager
        manager.select_slot("decision")
        dialog = manager.import_dialog()
        self.assertEqual(dialog.size, (95, 95))
        dialog.set_image(Image.new("RGBA", (50, 80), (0, 0, 255, 255)))
        dialog.name_edit.setText("mal/nombre")
        self.assertIsNone(dialog.do_import())
        self.assertEqual(dialog.error_label.text(), tr("gui.sprite_error.bad_name", name="mal/nombre"))
        dialog.name_edit.setText("mg_decision")
        dialog.mode_combo.setCurrentIndex(dialog.mode_combo.findData("contain"))
        rel = dialog.do_import()
        self.assertEqual(rel.suffix, ".dds")
        rgba = read_dds(bytes(self.window.session.project.ws.open(rel).model)).rgba
        self.assertEqual(rgba.shape, (95, 95, 4))
        self.assertEqual(int(rgba[47, 0, 3]), 0, "encajar deja bandas transparentes")


class EventPreviewTests(EventStudioCase):
    def test_the_preview_uses_the_real_window_when_its_art_exists(self):
        self.open_window(game_files=INTERFACE_FILES)
        page = self.window.show_page("events:events")
        self.settle()
        page.show_record(RecordRef("event", "2001"))
        self.settle()
        self.assertTrue(page.preview.uses_real_window())
        image = page.preview.render_image()
        self.assertEqual(image.width(), page.preview.canvas.real.width() + 16)
        self.assertGreater(page.preview.canvas.real.height(), 400, "la ventana y los botones de sus opciones")
        page.preview.set_game_art(False)
        self.assertFalse(page.preview.uses_real_window(), "sin arte: la vista procedural")

    def test_without_the_gui_or_with_no_game_art_it_stays_procedural(self):
        page = self.studio()
        self.assertFalse(page.preview.uses_real_window(), "el minijuego de guion no trae interfaz")
        with mock.patch.dict(os.environ, {"VIC2STUDIO_NO_GAME_ART": "1"}):
            page.preview.set_game_art(True)
            self.assertFalse(page.preview.uses_real_window())


if __name__ == "__main__":
    unittest.main()
