"""Buscador universal Ctrl+K (wizard §13.4, criterio 7), contra el ``Project`` real con el índice falso.

Abre con Ctrl+K y se cierra con Esc; busca por id, por nombre y por nombre localizado sin acentos; muestra el
tipo, el id, el archivo y el origen de cada resultado; Intro abre el archivo en su línea (una clave de texto, en
Textos); también busca secciones. Con corpus y el índice real de A, el criterio 7 («549», «Berlín», «PRU»,
«north_german»).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
from _corpus import copy_user_mod, user_mod, vanilla_root  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from test_ui_loc_edit import TextsWindowCase  # noqa: E402

APP = _qt.application()

from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.session import Session  # noqa: E402
from vic2studio.ui.shell.command_palette import KIND_LABELS  # noqa: E402

LOC = {"localisation/00_TESTMOD_countries.csv": "AAA;Åland;;;;Álandia;;;;;;;;x\r\nPROV3;Coast;;;;Costa;;;;;;;;x\r\n"}


class PaletteCase(TextsWindowCase):
    def open_palette(self, text: str = ""):
        window = self.window
        window.activateWindow()
        QTest.qWaitForWindowActive(window, 2000)
        QTest.keyClick(window, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
        _qt.process_events(20)
        palette = window.palette
        self.assertTrue(palette.isVisible(), "Ctrl+K no abrió el buscador")
        if text:
            QTest.keyClicks(palette.edit, text)
            palette.search()
        return palette


class PaletteTests(PaletteCase):
    def test_ctrl_k_opens_it_with_the_focus_and_esc_closes_it(self):
        self.open_window(mod_files=LOC)
        palette = self.open_palette()
        self.assertTrue(palette.edit.hasFocus())
        self.assertEqual(palette.state.text(), tr("palette.empty"))
        QTest.keyClick(palette.edit, Qt.Key.Key_Escape)
        self.assertFalse(palette.isVisible())

    def test_search_by_id_shows_kind_file_and_origin_and_enter_opens_the_file_at_its_line(self):
        window = self.open_window(mod_files=LOC)
        palette = self.open_palette("AAA")
        kinds = [r.symbol.kind for r in palette.results()]
        self.assertIn("tag", kinds)
        row = kinds.index("tag")
        self.assertEqual(palette.result_texts()[row],
                         tr("palette.result", name="Álandia (AAA)", kind=tr(KIND_LABELS["tag"]), id="AAA",
                            file="common/countries.txt:1", layer=tr("palette.layer.game")))
        palette.list.setCurrentRow(row)
        QTest.keyClick(palette.edit, Qt.Key.Key_Return)
        _qt.process_events(30)
        self.assertFalse(palette.isVisible())
        files = window.page("project")
        self.assertEqual(window.current_page_key(), "project")
        viewer = files.clausewitz_viewer
        target = self.game.game("common/countries.txt")
        self.assertTrue(_qt.wait_until(lambda: viewer.current_load() is not None
                                       and viewer.current_load().path == target, 5000))
        self.assertTrue(_qt.wait_until(lambda: viewer.code.current_line() == 1, 3000))
        palette = self.open_palette("CCC")
        row = next(i for i, r in enumerate(palette.results()) if (r.symbol.kind, r.symbol.name) == ("tag", "CCC"))
        palette.list.setCurrentRow(row)
        QTest.keyClick(palette.edit, Qt.Key.Key_Return)
        self.assertTrue(_qt.wait_until(lambda: viewer.code.current_line() == 3, 3000), "en su línea, no en la 1")

    def test_localised_names_are_found_without_case_or_accents(self):
        self.open_window(mod_files=LOC)
        palette = self.open_palette("alandia")
        found = [(r.symbol.kind, r.symbol.name) for r in palette.results()]
        self.assertIn(("tag", "AAA"), found)
        palette.edit.setText("COSTA")
        palette.search()
        found = [(r.symbol.kind, r.symbol.name) for r in palette.results()]
        self.assertIn(("province", "3"), found)
        self.assertIn("3 Costa", palette.result_texts()[found.index(("province", "3"))], "«id nombre» en provincias")
        self.assertEqual(palette.state.text(), tr("palette.count", count=len(palette.results())))

    def test_a_text_key_opens_in_all_texts(self):
        window = self.open_window(mod_files=LOC)
        palette = self.open_palette("free_people")
        row = next(i for i, r in enumerate(palette.results()) if r.symbol.kind == "loc_key")
        palette.activate(row)
        page = window.page("localisation:all")
        self.assertIs(window.current_page(), page)
        self.assertEqual(page.model.entries[page.proxy.source_row(page.table.currentIndex().row())].key, "free_people")

    def test_sections_are_found_too(self):
        window = self.open_window()
        palette = self.open_palette("validaci")
        sections = [r for r in palette.results() if r.kind == "section"]
        self.assertEqual([r.target for r in sections], ["project:validation"])
        self.assertEqual(palette.result_texts()[-1], tr("palette.section", title="Proyecto › Validación"))
        palette.activate(len(palette.results()) - 1)
        self.assertEqual(window.current_page_key(), "project:validation")

    def test_arrows_choose_and_shift_enter_asks_for_the_code(self):
        window = self.open_window(mod_files=LOC)
        palette = self.open_palette("AAA")
        self.assertEqual(palette.list.currentRow(), 0)
        QTest.keyClick(palette.edit, Qt.Key.Key_Down)
        self.assertEqual(palette.list.currentRow(), 1)
        QTest.keyClick(palette.edit, Qt.Key.Key_Up)
        self.assertEqual(palette.list.currentRow(), 0)
        asked = []
        palette.code_requested.connect(asked.append)
        QTest.keyClick(palette.edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual([s.name for s in asked], [palette.results()[0].symbol.name] if palette.results() else [])
        self.assertFalse(palette.isVisible())
        self.assertTrue(window.palette is palette)

    def test_nothing_found_and_no_project(self):
        self.open_window(mod_files=LOC)
        palette = self.open_palette("AAA")
        tall = palette.height()
        self.assertFalse(palette.list.isHidden())
        palette.edit.setText("zzzz")
        palette.search()
        self.assertEqual(palette.results(), [])
        self.assertEqual(palette.state.text(), tr("palette.nothing", text="zzzz"))
        self.assertTrue(palette.list.isHidden(), "sin resultados, sin lista vacía")
        self.assertLess(palette.height(), tall / 2)
        self.assertTrue(palette.isVisible() and palette.edit.hasFocus())
        set_language("en")
        self.assertEqual(palette.title.text(), "Search")
        self.assertEqual(palette.state.text(), tr("palette.nothing", text="zzzz"))

    def test_without_a_project_only_sections(self):
        window = self.make_window(session=Session())
        self.window = window
        palette = self.open_palette("textos")
        self.assertEqual(palette.state.text(), tr("palette.no_project"))
        self.assertTrue(all(r.kind == "section" for r in palette.results()))
        self.assertTrue(palette.results())

    def test_the_banner_button_opens_it(self):
        window = self.open_window()
        window.search_button.click()
        self.assertTrue(window.palette.isVisible())
        self.assertIn("Ctrl+K", window.search_button.text())


class KindLabelTests(unittest.TestCase):
    def test_every_kind_of_the_contract_has_its_label_and_icon(self):
        from vic2studio.core.index import model
        from vic2studio.ui.shell.command_palette import KIND_ICONS

        self.addCleanup(set_language, "es")
        kinds = {value for name, value in vars(model).items() if name.startswith("KIND_") and isinstance(value, str)}
        self.assertEqual(sorted(kinds - set(KIND_LABELS)), [], "tipos sin nombre ES/EN en Ctrl+K")
        for kind in kinds:
            with self.subTest(kind=kind):
                for lang in ("es", "en"):
                    set_language(lang)
                    self.assertNotEqual(tr(KIND_LABELS[kind]), KIND_LABELS[kind])
        self.assertLessEqual(set(KIND_ICONS), set(KIND_LABELS))


class BannerTests(PaletteCase):
    """El estandarte, con Buscar y Problemas de más, cabe a 1100 px en los dos idiomas (y a 1920, entero)."""

    BUTTONS = ("search_button", "undo_button", "redo_button", "history_button", "problems_button", "save_button",
               "language_combo")

    def settle(self, window):
        """Procesa eventos hasta que la disposición del estandarte se asienta (cambiar el estilo de Buscar pide otra
        pasada del layout; con la máquina cargada, 30 ms fijos no bastaban)."""
        widgets = [getattr(window, name) for name in self.BUTTONS]
        _qt.wait_until(lambda: all(w.width() >= w.sizeHint().width() for w in widgets)
                       and window._banner_box.geometry().right() <= window.banner.width(), 2000)

    def assert_fits(self, window):
        self.settle(window)
        for widget in (getattr(window, name) for name in self.BUTTONS):
            self.assertGreaterEqual(widget.width(), widget.sizeHint().width(), f"{widget.objectName()} recortado")
        self.assertLessEqual(window._banner_box.geometry().right(), window.banner.width())
        title = window.banner.title_label
        self.assertGreaterEqual(title.width(), title.sizeHint().width(), "el título recortado")

    def test_it_folds_at_1100_px_and_shows_everything_at_1920(self):
        window = self.make_window(session=Session())
        for lang in ("es", "en"):
            with self.subTest(lang=lang):
                set_language(lang)
                window.resize(1100, 700)
                _qt.process_events(30)
                self.assert_fits(window)
                self.assertEqual(window.search_button.toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonIconOnly)
                self.assertIn("Ctrl+K", window.search_button.text())
                self.assertIn("Ctrl+K", window.search_button.toolTip(), "sin texto, el atajo va en la ayuda")
                window.save_button.setText(tr("shell.save_count", count=128))
                window._fit_banner()
                _qt.process_events(30)
                self.assert_fits(window)
                window.resize(1920, 1080)
                _qt.process_events(30)
                self.assert_fits(window)
                self.assertEqual(window.search_button.toolButtonStyle(),
                                 Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                self.assertTrue(window.language_label.isVisible())
                self.assertTrue(window.banner.tagline_label.isVisible())


@unittest.skipUnless(vanilla_root() is not None and user_mod() is not None,
                     "necesita el índice real del agente A y VIC2_CORPUS con vanilla y VSM")
class CorpusCriterion7Tests(PaletteCase):
    """Criterio 7: Ctrl+K encuentra «549», «Berlín», «PRU» y «north_german» y abre el archivo en su línea.

    Revisión it3 (hallazgo 4): «549» y «Berlín» abrían map/definition.csv:550 en una ficha con las primeras 160 líneas,
    así que la línea no se veía. Ahora se comprueba la línea que queda a la vista, no solo que se abra algo.
    """

    def test_the_four_searches_of_the_criterion(self):
        window = self.make_window(session=Session())
        self.window = window
        window.resize(1100, 700)
        files = window.page("project")
        files.set_game_path(vanilla_root())
        files.set_mod_path(copy_user_mod(self))   # nunca el VSM real del corpus
        session = window.session
        self.assertTrue(_qt.wait_until(lambda: session.index is not None and session.texts_ready(), 60000))
        for text, kind, name in (("549", "province", "549"), ("Berlín", "province", "549"), ("PRU", "tag", "PRU"),
                                 ("north_german", "culture", "north_german")):
            with self.subTest(text=text):
                found = session.search(text)
                self.assertIn((kind, name), [(s.kind, s.name) for s in found])
                symbol = next(s for s in found if (s.kind, s.name) == (kind, name))
                self.assertTrue(window.open_symbol(symbol))
                if kind == "culture":
                    # Iteración 4: una cultura tiene esquema y abre su editor de entidad («o el editor de la entidad
                    # cuando exista», wizard §22, iteración 3, criterio 7), no el archivo.
                    self.assertEqual(window.current_page_key(), "nations:cultures")
                    self.assertEqual(window.current_page().current_ref().ident, name)
                    continue
                expected = session.location_path(symbol.rel, symbol.layer)
                self.assertTrue(_qt.wait_until(lambda: files.shown_location() == (expected, symbol.line)
                                               and not window.is_busy(), 20000),
                                f"{text}: se ve {files.shown_location()}, no {symbol.rel}:{symbol.line}")
                if files.preview_stack.currentWidget() is files.preview:   # la ficha: la línea, a la vista
                    excerpt = files.preview.excerpt
                    self.assertTrue(excerpt.viewport().rect().contains(excerpt.cursorRect().center()))
                    self.assertTrue(excerpt.textCursor().block().text().startswith(f"{name};"), text)


if __name__ == "__main__":
    unittest.main()
