"""Página «Proyecto y Archivos»: explorador, vista previa, descriptor, imágenes y validación (offscreen).

Todo se hace sobre un juego y un mod sintéticos creados por código
(``<tmp>/Victoria 2/mod/TestMod``, con el juego conteniendo al mod como en una
instalación real). Fallan ante cualquier aviso de Qt.
"""

import errno
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
from PIL import Image  # noqa: E402
from PySide6.QtCore import QModelIndex, QRect, QSize, Qt  # noqa: E402
from PySide6.QtGui import QTextDocument  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QComboBox, QLabel, QProxyStyle, QStyle  # noqa: E402

APP = _qt.application()

from vic2studio.core.cancel import Cancelled  # noqa: E402
from vic2studio.core.clausewitz import to_json  # noqa: E402
from vic2studio.core.encoding import GAME_ENCODING, GAME_UNREADABLE, UTF8, UTF8_BOM, decode_bytes  # noqa: E402
from vic2studio.i18n import set_language, tr, translator  # noqa: E402
from vic2studio.ui.main_window import MINIMUM_SIZE, MainWindow  # noqa: E402
from vic2studio.ui.pages import PAGE_KEYS, project_page  # noqa: E402
from vic2studio.ui.pages.project_page import evaluate_mod, inspect_folder, preview_kind  # noqa: E402
from vic2studio.ui.tasks import wait_for_tasks  # noqa: E402
from vic2studio.ui.viewers import clausewitz_viewer as clausewitz_viewer_module  # noqa: E402
from vic2studio.ui.viewers import image_viewer as image_viewer_module  # noqa: E402
from vic2studio.ui.viewers import validation_panel as validation_panel_module  # noqa: E402
from vic2studio.ui.viewers.image_viewer import ImageViewer  # noqa: E402
from vic2studio.ui.widgets import EmptyState  # noqa: E402

TIMEOUT_MS = 15000


def build_game(base: Path) -> tuple[Path, Path]:
    """Juego base sintético con un mod en su carpeta ``mod/``; devuelve (juego, mod)."""
    game = base / "Victoria 2"
    for name in ("common", "history", "localisation", "map", "events", "interface", "gfx"):
        (game / name).mkdir(parents=True)
    (game / "v2game.exe").write_bytes(b"MZ")
    (game / "events" / "vanilla.txt").write_text("country_event = {\n\tid = 1\n", encoding="cp1252")
    mod = game / "mod" / "TestMod"
    for folder in ("common", "decisions", "history/provinces/france", "localisation", "map", "gfx/flags"):
        (mod / folder).mkdir(parents=True)
    (mod / "common" / "countries.txt").write_text('GER = "countries/Germany.txt"\n', encoding="cp1252")
    (mod / "common" / "notes.lua").write_text("-- notas\n", encoding="cp1252")
    for name in ("a", "b", "c", "d", "e"):
        (mod / "decisions" / f"{name}.txt").write_text(f"political_decisions = {{\n\t{name} = {{ }}\n}}\n",
                                                       encoding="cp1252")
    for name in ("400 - Dunkirk", "401 - Calais", "402 - Lille"):
        (mod / "history" / "provinces" / "france" / f"{name}.txt").write_text("owner = FRA\n", encoding="cp1252")
    (mod / "localisation" / "test.csv").write_bytes(b"KEY;Hello;;;;Hola;;;;;;;;;x\n")
    (mod / "map" / "definition.csv").write_bytes(b"province;red;green;blue;x;x\n1;10;20;30;Paris;x\n")
    Image.new("RGB", (40, 30), (200, 30, 40)).save(mod / "gfx" / "flags" / "TST.tga")
    Image.new("RGB", (20, 10), (10, 120, 40)).save(mod / "gfx" / "flags" / "anim.gif")
    (mod / "gfx" / "flags" / "a[1].tga").write_bytes(b"")
    (mod.parent / "TestMod.mod").write_text('name = "Test Mod"\npath = "mod/TestMod"\n', encoding="cp1252")
    return game, mod


def double_click(view, index) -> None:
    """Doble clic real (pulsar, soltar, doble clic): ``QTest.mouseDClick`` solo no activa la vista."""
    center = view.visualRect(index).center()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    _qt.process_events(20)


def plain(html_text: str) -> str:
    document = QTextDocument()
    document.setHtml(html_text)
    return document.toPlainText()


class SingleClickStyle(QProxyStyle):
    """Como KDE/Plasma con «un clic abre»: un solo clic emite ``clicked`` y también ``activated``."""

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ItemView_ActivateItemOnSingleClick:
            return 1
        return super().styleHint(hint, option, widget, returnData)


class PageCase(unittest.TestCase):
    def setUp(self):
        _qt.reset_settings()
        set_language("es")
        _qt.take_qt_messages()
        self.missing_before = translator().missing_keys()
        self._tmp = tempfile.TemporaryDirectory()
        self.game, self.mod = build_game(Path(self._tmp.name))
        self.window = MainWindow()
        self.window.resize(1440, 900)
        self.window.show()
        _qt.process_events(30)
        self.project = self.window.page("project")

    def tearDown(self):
        self.window.close()
        self.assertTrue(wait_for_tasks(10000), "quedaron tareas en segundo plano")
        _qt.process_events()
        self.assertEqual(_qt.dispose(self.window), [], "la ventana de la prueba sigue viva")
        self.assertEqual(_qt.live_main_windows(), [], "quedó viva otra ventana principal")
        _qt.process_events()
        set_language("es")
        self._tmp.cleanup()
        self.assertEqual(_qt.take_qt_messages(), [], "avisos de Qt durante la prueba")
        self.assertEqual(sorted(translator().missing_keys() - self.missing_before), [],
                         "claves pedidas en tiempo de ejecución que no existen")

    def wait(self, predicate, message: str, timeout: int = TIMEOUT_MS) -> None:
        self.assertTrue(_qt.wait_until(predicate, timeout), message)

    def set_mod(self, path: Path | None = None) -> None:
        self.project.set_mod_path(path or self.mod)
        self.wait(lambda: not self.project.is_busy(), "el explorador no terminó de cargar")

    def index_of(self, path: Path, column: int = 0) -> QModelIndex:
        index = self.project.model.mapFromSource(self.project.fs.index(os.fspath(path)))
        return index.siblingAtColumn(column)

    def show_folder(self, folder: Path) -> None:
        """Expande ``folder`` y espera a que el modelo cargue su contenido."""
        index = self.index_of(folder)
        self.project.tree.expand(index)
        self.wait(lambda: self.project.model.rowCount(self.index_of(folder)) > 0, f"{folder.name} no cargó")
        _qt.process_events(50)

    def click(self, index: QModelIndex) -> None:
        QTest.mouseClick(self.project.tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         self.project.tree.visualRect(index).center())
        _qt.process_events(20)

    def status(self) -> str:
        return self.window.status_label.text()


class ExplorerTests(PageCase):
    def test_double_click_and_enter_toggle_folders_from_any_column(self):
        """FI-1 y FI-M3: el doble clic se anulaba (expandía y contraía) y en Tamaño/Modificado solo expandía."""
        self.set_mod()
        tree = self.project.tree
        folder = self.mod / "history"
        for column in (0, 3):
            double_click(tree, self.index_of(folder, column))
            self.assertTrue(tree.isExpanded(self.index_of(folder)), f"doble clic en la columna {column}")
            double_click(tree, self.index_of(folder, column))
            self.assertFalse(tree.isExpanded(self.index_of(folder)), f"segundo doble clic en la columna {column}")
        self.click(self.index_of(folder, 3))
        self.assertEqual(tree.currentIndex().column(), 3)
        for expanded in (True, False, True):
            QTest.keyClick(tree, Qt.Key.Key_Return)
            _qt.process_events(20)
            self.assertEqual(tree.isExpanded(self.index_of(folder)), expanded)

    def test_clicking_the_highlighted_file_shows_it_again(self):
        """CP-12: tras abrir el descriptor (fuera de la raíz), el archivo resaltado no se podía reabrir."""
        self.set_mod()
        viewer = self.project.clausewitz_viewer
        target = self.mod / "common" / "countries.txt"
        self.assertTrue(self.project.reveal_file(target))
        self.wait(lambda: viewer.current_load() is not None and viewer.current_path() == target, "no cargó")
        descriptor = self.mod.parent / "TestMod.mod"
        self.assertTrue(self.project.open_file(descriptor))
        self.assertEqual(viewer.current_path(), descriptor)
        self.assertEqual(self.project.model.file_path(self.project.tree.currentIndex()), target)
        self.click(self.index_of(target))
        self.assertEqual(viewer.current_path(), target, "un clic en el archivo resaltado debe volver a mostrarlo")
        self.assertTrue(self.project.open_file(descriptor))
        QTest.keyClick(self.project.tree, Qt.Key.Key_Return)
        _qt.process_events(20)
        self.assertEqual(viewer.current_path(), target, "Intro en el archivo resaltado debe volver a mostrarlo")

    def test_clicking_the_selected_file_rereads_it_if_it_changed(self):
        """MISSED-1: clic, Intro o doble clic en el archivo ya seleccionado no lo releía tras corregirlo fuera."""
        self.set_mod()
        folder = self.mod / "decisions"
        self.show_folder(folder)
        viewer = self.project.clausewitz_viewer
        tree = self.project.tree

        def act(how: str, index) -> None:
            if how == "Intro":
                QTest.keyClick(tree, Qt.Key.Key_Return)
                _qt.process_events(20)
            elif how == "doble clic":
                double_click(tree, index)
            else:
                self.click(index)
            self.wait(lambda: not self.project.is_busy(), f"{how}: la vista previa no terminó")

        for how, name in (("clic", "a"), ("Intro", "b"), ("doble clic", "c")):
            path = folder / f"{name}.txt"
            path.write_text("political_decisions = {\n", encoding="cp1252")  # le falta la llave de cierre
            index = self.index_of(path)
            self.click(index)
            self.wait(lambda: viewer.current_path() == path and viewer.current_load() is not None
                      and not self.project.is_busy(), f"{name}.txt no cargó")
            first = viewer.current_load()
            self.assertEqual([e.code for e in first.result.errors], ["unclosed_block"])
            act(how, index)
            self.assertIs(viewer.current_load(), first, f"{how}: sin cambios en disco no se vuelve a analizar")
            path.write_text("political_decisions = {\n}\n", encoding="cp1252")  # corregido en otro editor
            act(how, index)
            self.assertIsNot(viewer.current_load(), first, f"{how}: el visor sigue con el archivo viejo")
            self.assertEqual(viewer.current_load().result.errors, [], how)
            self.assertEqual(viewer.header.badge.level, "ok", how)

    def test_returning_to_the_application_rereads_the_visible_file_if_it_changed(self):
        """MISSED-1: al volver a la aplicación (p. ej. desde Notepad++) se relee lo que se ve, solo si cambió."""
        self.set_mod()
        viewer, image = self.project.clausewitz_viewer, self.project.image_viewer
        activate = lambda: APP.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)  # noqa: E731

        def settle() -> None:
            _qt.process_events(20)
            self.wait(lambda: not self.project.is_busy(), "la vista previa no terminó")

        decision = self.mod / "decisions" / "a.txt"
        self.assertTrue(self.project.reveal_file(decision))
        settle()
        first = viewer.current_load()
        activate()
        settle()
        self.assertIs(viewer.current_load(), first, "sin cambios no se relee nada")
        decision.write_text("political_decisions = {\n", encoding="cp1252")
        activate()
        settle()
        self.assertIsNot(viewer.current_load(), first)
        self.assertEqual([e.code for e in viewer.current_load().result.errors], ["unclosed_block"])
        # Solo la página a la vista: con otra página delante no se relee.
        second = viewer.current_load()
        decision.write_text("political_decisions = {\n}\n", encoding="cp1252")
        self.window.set_current_page(PAGE_KEYS.index("localisation"))
        activate()
        settle()
        self.assertIs(viewer.current_load(), second)
        self.window.set_current_page(PAGE_KEYS.index("project"))
        activate()
        settle()
        self.assertEqual(viewer.current_load().result.errors, [])
        # Las imágenes y la ficha de una carpeta, igual.
        flag = self.mod / "gfx" / "flags" / "TST.tga"
        self.assertTrue(self.project.reveal_file(flag))
        settle()
        Image.new("RGB", (80, 60), (0, 0, 255)).save(flag)
        activate()
        settle()
        self.assertEqual((image.current_load().width, image.current_load().height), (80, 60))
        france = self.mod / "history" / "provinces" / "france"
        self.assertTrue(self.project.reveal_file(france))
        settle()
        self.assertEqual(self.project.preview.form_values["entries"].text(), "3 elementos")
        (france / "403 - Arras.txt").write_text("owner = FRA\n", encoding="cp1252")
        activate()
        settle()
        self.assertEqual(self.project.preview.form_values["entries"].text(), "4 elementos")

    def test_a_file_that_could_not_be_read_is_retried_when_fixed(self):
        """R3: tras «no tienes permiso», arreglarlo (sin cambiar fecha ni tamaño) y hacer clic en el archivo
        o volver a la aplicación lo dejaba igual: el reintento exigía que el archivo cambiara."""
        self.set_mod()
        viewer, image = self.project.clausewitz_viewer, self.project.image_viewer
        tree = self.project.tree

        def settle() -> None:
            _qt.process_events(20)
            self.wait(lambda: not self.project.is_busy(), "la vista previa no terminó")

        def click() -> None:
            self.click(tree.currentIndex())
            settle()

        def activate() -> None:
            APP.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
            settle()

        def denied(module, name, path):
            error = PermissionError(errno.EACCES, os.strerror(errno.EACCES), os.fspath(path))
            return mock.patch.object(module, name, side_effect=error, create=True)

        cases = ((click, self.mod / "decisions" / "a.txt"), (activate, self.mod / "common" / "countries.txt"))
        for retry, path in cases:
            with denied(clausewitz_viewer_module, "parse_file", path):  # siendo root se podría leer
                self.assertTrue(self.project.reveal_file(path))
                settle()
                self.assertEqual(viewer.failure_text(), tr("file_error.permission"), path.name)
            retry()  # el permiso ya está arreglado
            self.assertEqual(viewer.failure_text(), "", f"{retry.__name__}: {path.name} sigue sin leerse")
            self.assertEqual(viewer.current_load().path, path)
        flag = self.mod / "gfx" / "flags" / "TST.tga"
        with denied(image_viewer_module, "open", flag):
            self.assertTrue(self.project.reveal_file(flag))
            settle()
            self.assertIsNone(image.current_load())
        click()
        self.assertIsNotNone(image.current_load(), "la imagen sigue sin leerse")

    def test_clicking_the_selected_file_replaces_a_custom_preview(self):
        """CP-12 (resto): tras ``set_preview_widget(widget)``, un clic en el archivo resaltado no lo mostraba."""
        self.set_mod()
        viewer = self.project.clausewitz_viewer
        target = self.mod / "common" / "countries.txt"
        self.assertTrue(self.project.reveal_file(target))
        self.wait(lambda: viewer.current_load() is not None and not self.project.is_busy(), "no cargó")
        custom = QLabel("editor")
        self.addCleanup(_qt.dispose, custom)
        for widget in (custom, None):
            self.project.set_preview_widget(widget)
            self.click(self.index_of(target))
            self.assertIs(self.project.preview_stack.currentWidget(), viewer, widget)

    def test_viewer_header_follows_the_explorer_root(self):
        """NEW-2: tras cambiar «Mostrar: Juego/Mod», la cabecera seguía con la ruta relativa a la raíz anterior."""
        self.project.set_game_path(self.game)
        self.set_mod()
        viewer = self.project.clausewitz_viewer
        target = self.mod / "common" / "countries.txt"
        for root, shown in (("mod", "common/countries.txt"), ("game", "mod/TestMod/common/countries.txt"),
                            ("mod", "common/countries.txt")):
            self.project.set_explorer_root(root)
            self.wait(lambda: not self.project.is_busy(), f"el explorador ({root}) no cargó")
            self.assertTrue(self.project.reveal_file(target))
            self.wait(lambda: viewer.current_load() is not None and not self.project.is_busy(), "no cargó")
            self.assertTrue(viewer.header.details.text().startswith(f"{shown} · "),
                            f"{root}: {viewer.header.details.text()}")

    def test_switching_the_explorer_root_leaves_nothing_highlighted(self):
        """MISSED-2: al cambiar «Mostrar: Juego/Mod» seguía resaltado un archivo que la vista previa no mostraba."""
        self.project.set_game_path(self.game)
        self.set_mod()
        target = self.mod / "common" / "countries.txt"
        self.assertTrue(self.project.reveal_file(target))
        _qt.process_events(20)
        self.project.set_explorer_root("game")
        self.wait(lambda: not self.project.is_busy(), "el explorador del juego no cargó")
        self.assertEqual(self.project.explorer_root(), self.game)
        self.assertFalse(self.project.tree.currentIndex().isValid())
        self.assertFalse(self.project.tree.selectionModel().hasSelection())
        self.assertIs(self.project.preview_stack.currentWidget(), self.project.preview)
        # El mismo archivo, bajo la nueva raíz, se vuelve a mostrar.
        self.assertTrue(self.project.reveal_file(target))
        viewer = self.project.clausewitz_viewer
        self.wait(lambda: viewer.current_load() is not None and not self.project.is_busy(), "no cargó")
        self.assertIs(self.project.preview_stack.currentWidget(), viewer)
        self.assertEqual(viewer.current_path(), target)

    def test_keyboard_navigation_only_loads_where_it_stops(self):
        """CP-9: cada flecha lanzaba un análisis; ahora la vista previa espera a que la selección se asiente."""
        self.set_mod()
        folder = self.mod / "decisions"
        self.show_folder(folder)
        viewer = self.project.clausewitz_viewer
        loads = []
        original = viewer.load
        viewer.load = lambda path, **kwargs: (loads.append(Path(path).name), original(path, **kwargs))[1]
        self.click(self.index_of(folder / "a.txt"))
        self.assertEqual(loads, ["a.txt"], "con el ratón la vista previa se muestra en el acto")
        for _ in range(4):
            QTest.keyClick(self.project.tree, Qt.Key.Key_Down)
        self.assertEqual(self.project.model.file_path(self.project.tree.currentIndex()).name, "e.txt")
        self.assertTrue(self.project.is_busy(), "la selección pendiente cuenta como trabajo en curso")
        self.wait(lambda: not self.project.is_busy(), "la vista previa no se actualizó")
        self.assertEqual(loads, ["a.txt", "e.txt"])
        self.assertEqual(viewer.current_load().path, folder / "e.txt")
        self.assertEqual(self.status(), "Seleccionado: decisions/e.txt")

    def test_selecting_another_kind_of_file_cancels_the_pending_analysis(self):
        """CP-7: el análisis viejo seguía vigente y escribía sus errores en la barra de estado."""
        big = self.mod / "events" / "big_broken.txt"
        big.parent.mkdir()
        big.write_text("political_decisions = {\n" + "".join(
            f"\tdecision_{n} = {{ potential = {{ owner = {{ tag = TAG }} }} allow = {{ prestige = {n} }} }}\n"
            for n in range(40_000)), encoding="cp1252")
        self.set_mod()
        viewer = self.project.clausewitz_viewer
        self.assertTrue(self.project.reveal_file(big))
        self.assertTrue(viewer.is_busy())
        notes = self.mod / "common" / "notes.lua"
        self.assertTrue(self.project.reveal_file(notes))
        self.assertFalse(viewer.is_busy(), "el análisis que ya no se va a ver debe cancelarse")
        self.assertIs(self.project.preview_stack.currentWidget(), self.project.preview)
        self.assertTrue(wait_for_tasks(TIMEOUT_MS))
        _qt.process_events(50)
        self.assertEqual(self.status(), "Seleccionado: common/notes.lua")
        self.assertIsNone(viewer.current_load())
        # Volver al archivo lo analiza de nuevo, y entonces sí se informa de su error.
        self.assertTrue(self.project.reveal_file(big))
        self.wait(lambda: viewer.current_load() is not None, "el archivo grande no cargó")
        self.assertIn("1 error de sintaxis", self.status())

    def test_another_kind_of_file_keeps_the_file_already_analysed(self):
        """REG-2: elegir un .lua mientras se generaba el JSON descartaba el análisis y volver lo repetía."""
        self.set_mod()
        viewer = self.project.clausewitz_viewer
        decision = self.mod / "decisions" / "a.txt"
        self.assertTrue(self.project.reveal_file(decision))
        self.wait(lambda: not viewer.is_busy(), "el archivo no cargó")
        load = viewer.current_load()
        viewer.select_tab("json")
        self.assertTrue(viewer.is_busy(), "el JSON se genera en segundo plano")
        self.assertTrue(self.project.reveal_file(self.mod / "common" / "notes.lua"))
        self.assertIs(self.project.preview_stack.currentWidget(), self.project.preview)
        self.assertTrue(viewer.current_load() is load, "elegir otro tipo de archivo no debe soltar el análisis")
        self.assertTrue(self.project.reveal_file(decision))
        self.wait(lambda: not self.project.is_busy(), "la vista previa no terminó")
        self.assertTrue(viewer.current_load() is load, "volver al archivo no debe analizarlo otra vez")
        self.assertEqual(viewer.current_tab(), "json")

    def test_showing_something_else_stops_the_json_and_returning_makes_it_again(self):
        """El JSON a medio generar no ocupa un hilo mientras se ve otra cosa; al volver a su pestaña se rehace."""
        self.set_mod()
        viewer = self.project.clausewitz_viewer
        decision = self.mod / "decisions" / "a.txt"
        self.assertTrue(self.project.reveal_file(decision))
        self.wait(lambda: not viewer.is_busy(), "el archivo no cargó")
        load = viewer.current_load()
        viewer.select_tab("json")
        self.assertTrue(viewer.is_busy(), "el JSON se genera en segundo plano")
        self.assertTrue(self.project.reveal_file(self.mod / "common" / "notes.lua"))
        self.assertFalse(viewer.is_busy(), "el JSON siguió generándose sin que nadie lo viera")
        self.assertIs(viewer.current_load(), load)
        self.assertTrue(self.project.reveal_file(decision))
        self.wait(lambda: not self.project.is_busy(), "la vista previa no terminó")
        self.assertIs(viewer.current_load(), load)
        self.assertEqual(json.loads(viewer.json_view.toPlainText()), to_json(load.result.document))

    def test_reanalysis_that_ends_out_of_sight_leaves_the_status_alone(self):
        """CP-7: si el archivo cambió en disco se analiza otra vez; si termina con otra cosa a la vista, no informa."""
        broken = self.mod / "decisions" / "broken.txt"
        broken.write_text("political_decisions = {\n", encoding="cp1252")
        self.set_mod()
        viewer = self.project.clausewitz_viewer
        self.assertTrue(self.project.reveal_file(broken))
        self.wait(lambda: not viewer.is_busy(), "el archivo no cargó")
        self.assertIn("broken.txt: 1 error de sintaxis", self.status())
        broken.write_text("political_decisions = {\n\ta = { }\n", encoding="cp1252")  # sigue roto
        self.assertTrue(viewer.reload_if_changed())
        self.assertTrue(self.project.reveal_file(self.mod / "common" / "notes.lua"))
        self.wait(lambda: not self.project.is_busy(), "el nuevo análisis no terminó")
        self.assertEqual(viewer.current_load().text, broken.read_text(encoding="cp1252"))
        self.assertEqual(self.status(), "Seleccionado: common/notes.lua")

    def test_filter_takes_spaces_and_brackets_literally(self):
        """FI-9 y FI-10: «[» llenaba el registro de avisos y «400 - Dunkirk» mostraba todas las provincias."""
        self.set_mod()
        france = self.mod / "history" / "provinces" / "france"
        flags = self.mod / "gfx" / "flags"
        for folder in (self.mod / "history", self.mod / "history" / "provinces", france, self.mod / "gfx", flags):
            self.show_folder(folder)

        def names(folder: Path) -> list[str]:
            parent = self.index_of(folder)
            return sorted(self.project.model.index(r, 0, parent).data()
                          for r in range(self.project.model.rowCount(parent)))

        self.project.filter_edit.setText("400 - Dunkirk")
        self.wait(lambda: names(france) == ["400 - Dunkirk.txt"], f"filtro con espacios: {names(france)}")
        self.project.filter_edit.setText("[")
        self.wait(lambda: names(flags) == ["a[1].tga"], f"filtro con corchete: {names(flags)}")
        self.project.filter_edit.setText("a[1]")
        self.wait(lambda: names(flags) == ["a[1].tga"], f"filtro con corchetes: {names(flags)}")
        self.project.filter_edit.setText("*.gif; TST")
        self.wait(lambda: names(flags) == ["TST.tga", "anim.gif"], f"dos patrones: {names(flags)}")
        self.project.filter_edit.clear()

    def test_context_menu_opens_the_containing_folder(self):
        """FI-13: en una carpeta, «Abrir la carpeta contenedora» abría la propia carpeta."""
        self.set_mod()
        opened = []
        with mock.patch.object(project_page, "QDesktopServices") as services:
            services.openUrl.side_effect = lambda url: opened.append(Path(url.toLocalFile()))
            for path in (self.mod / "localisation", self.mod / "localisation" / "test.csv"):
                menu = self.project.context_menu(path)
                copy, reveal = menu.actions()
                self.assertEqual(reveal.text(), "Abrir la carpeta contenedora")
                reveal.trigger()
                menu.deleteLater()
        self.assertEqual(opened, [self.mod, self.mod / "localisation"])

    def test_single_click_activation_requests_a_csv_once(self):
        """FI-M4: con la activación de un solo clic (KDE) un clic en un CSV lanzaba dos cargas."""
        self.set_mod()
        style = SingleClickStyle("Fusion")
        self.project.tree.setStyle(style)
        self.show_folder(self.mod / "localisation")
        requests = []
        self.project.csv_requested.connect(lambda path, line: requests.append(path.name))
        self.click(self.index_of(self.mod / "localisation" / "test.csv"))
        self.assertEqual(requests, ["test.csv"])
        self.wait(lambda: not self.window.page("localisation").is_busy(), "el CSV no cargó")
        self.project.tree.setStyle(None)

    def test_only_localisation_csv_files_go_to_the_localisation_page(self):
        """VAL-M2: ``map/definition.csv`` no es un CSV de localización."""
        self.assertEqual(preview_kind(self.mod / "localisation" / "test.csv"), "csv")
        self.assertIsNone(preview_kind(self.mod / "map" / "definition.csv"))
        self.set_mod()
        self.show_folder(self.mod / "map")
        requests = []
        self.project.csv_requested.connect(lambda path, line: requests.append(path.name))
        self.click(self.index_of(self.mod / "map" / "definition.csv"))
        self.assertEqual(requests, [])
        self.assertEqual(self.window.current_page_index(), 0)
        self.assertIs(self.project.preview_stack.currentWidget(), self.project.preview)
        self.assertFalse(self.project.preview.csv_button.isVisible())
        self.assertIn("Paris", self.project.preview.excerpt.toPlainText())

    def test_folder_card_and_status(self):
        """FI-M1, FI-M2 y FI-6: singular, barra de estado al elegir una carpeta y nota de la ficha al día."""
        self.set_mod()
        self.assertTrue(self.project.reveal_file(self.mod / "common" / "countries.txt"))
        self.assertTrue(self.project.reveal_file(self.mod / "map"))
        _qt.process_events(20)
        self.assertEqual(self.status(), "Seleccionado: map")
        self.assertEqual(self.project.preview.form_values["entries"].text(), "1 elemento")
        note = self.project.preview.note
        self.assertTrue(note.isVisible())
        self.assertNotIn("llegará", note.text())
        set_language("en")
        self.assertEqual(self.project.preview.form_values["entries"].text(), "1 item")
        self.assertNotIn("arrives", note.text())

    def test_utf16_files_say_the_game_cannot_read_them(self):
        """NF-7: la ficha mostraba «utf-16», «utf-16-be-bom»… tal cual, sin avisar de que el juego no los lee."""
        self.assertLessEqual({GAME_ENCODING, UTF8, UTF8_BOM} | GAME_UNREADABLE, set(project_page.ENCODING_KEYS),
                             "una codificación que puede detectarse no tiene etiqueta")
        self.window.resize(MINIMUM_SIZE)  # el texto más largo tiene que verse entero también así
        self.set_mod()
        text = "-- notas\r\nprint('hola')\r\n"
        files = {"utf-16": b"\xff\xfe" + text.encode("utf-16-le"),
                 "utf-16-be-bom": b"\xfe\xff" + text.encode("utf-16-be"),
                 "utf-16-le": text.encode("utf-16-le"), "utf-16-be": text.encode("utf-16-be")}
        for encoding, data in files.items():
            path = self.mod / "common" / f"{encoding}.lua"
            path.write_bytes(data)
            self.assertEqual(decode_bytes(data).encoding, encoding)
            self.assertTrue(self.project.reveal_file(path))
            self.wait(lambda: self.project.preview.facts is not None and self.project.preview.facts.path == path,
                      f"la ficha de {path.name} no apareció")
            shown = self.project.preview.form_values["encoding"]
            # Literal, no sacado de ENCODING_KEYS: cruzar dos etiquetas tiene que hacer fallar la prueba.
            big, bom = {"utf-16": (False, True), "utf-16-be-bom": (True, True),
                        "utf-16-le": (False, False), "utf-16-be": (True, False)}[encoding]
            splitter = self.project.splitter
            default_sizes = splitter.sizes()
            # Con el divisor por defecto y con la vista previa estrecha (~300 px, moviendo el divisor): con la
            # política vertical Fixed el alto se quedaba en el sizeHint y se perdía «puede leerlo».
            for sizes in (default_sizes, [sum(default_sizes) - 300, 300]):
                splitter.setSizes(sizes)
                for lang, says, with_bom, without_bom in (
                        ("es", "el juego no puede leerlo", "con BOM", "sin BOM"),
                        ("en", "the game cannot read it", "with BOM", "without BOM")):
                    set_language(lang)
                    _qt.process_events(40)
                    where = (lang, encoding, sizes)
                    self.assertEqual(shown.text(), tr(project_page.ENCODING_KEYS[encoding]), where)
                    self.assertIn(says, shown.text(), where)
                    self.assertNotIn(encoding, shown.text(), where)
                    self.assertEqual(("UTF-16 BE" in shown.text(), "UTF-16 LE" in shown.text()), (big, not big), where)
                    self.assertIn(with_bom if bom else without_bom, shown.text(), where)
                    # Se veía en una sola línea recortada por la derecha: se perdía justo el aviso.
                    room, metrics = shown.contentsRect(), shown.fontMetrics()
                    if shown.wordWrap():
                        needed = metrics.boundingRect(QRect(0, 0, room.width(), 10 * room.height()),
                                                      int(shown.alignment()) | Qt.TextFlag.TextWordWrap, shown.text())
                        fits = needed.width() <= room.width() and shown.height() >= shown.heightForWidth(
                            shown.width()) > 0
                    else:
                        fits = metrics.horizontalAdvance(shown.text()) <= room.width()
                    self.assertTrue(fits, (*where, room.width(), room.height()))
            splitter.setSizes(default_sizes)
            set_language("es")

    UTF16_SCRIPT = b"\xff\xfe" + "political_decisions = {\r\n\ta = { }\r\n}\r\n".encode("utf-16-le")

    def open_script(self, path: Path):
        viewer = self.project.clausewitz_viewer
        self.assertTrue(self.project.reveal_file(path))
        self.wait(lambda: viewer.current_load() is not None and viewer.current_load().path == path
                  and not viewer.is_busy(), f"{path.name} no cargó")
        _qt.process_events(50)
        return viewer

    def test_a_utf16_script_is_not_a_syntax_error(self):
        """La barra de estado decía «a.txt: 1 error de sintaxis» de un UTF-16 sin ningún error de sintaxis
        (contaba ``unreadable_encoding``); ahora dice que el juego no puede leerlo."""
        self.set_mod()
        path = self.mod / "decisions" / "a.txt"
        path.write_bytes(self.UTF16_SCRIPT)
        self.open_script(path)
        for lang, word in (("es", "sintaxis"), ("en", "syntax")):
            set_language(lang)
            self.assertNotIn(word, self.status(), lang)
            self.assertEqual(self.status(), tr("status.file_unreadable", name="a.txt"), lang)
        set_language("es")
        # Un error de sintaxis de verdad se sigue contando, y solo él.
        broken = self.mod / "decisions" / "b.txt"
        broken.write_bytes(b"political_decisions = {\r\n\ta = { }\r\n")
        self.open_script(broken)
        self.assertEqual(self.status(), tr("status.file_errors_one", name="b.txt", count=1))

    def test_a_utf16_descriptor_is_not_a_syntax_error(self):
        """El descriptor en UTF-16 salía en Rutas como «· 1 error de sintaxis»."""
        (self.mod.parent / "TestMod.mod").write_bytes(
            b"\xff\xfe" + 'name = "Test Mod"\r\npath = "mod/TestMod"\r\n'.encode("utf-16-le"))
        self.set_mod()
        for lang, word in (("es", "sintaxis"), ("en", "syntax")):
            set_language(lang)
            shown = plain(self.project.mod_field.descriptor.text())
            self.assertNotIn(word, shown, lang)
            self.assertIn(tr("check.descriptor_unreadable"), shown, lang)
        set_language("es")

    def test_the_header_of_a_utf16_file_fits(self):
        """A 1440x900, con la ruta más corta, la cabecera de un UTF-16 perdía la ruta entera y el tamaño: repetía
        «(el juego no puede leerlo)» y la insignia, más ancha, le quitaba sitio a la línea de detalles."""
        self.set_mod()
        path = self.mod / "decisions" / "a.txt"
        path.write_bytes(self.UTF16_SCRIPT)
        header = self.open_script(path).header
        for size in (MINIMUM_SIZE, QSize(1440, 900)):
            self.window.resize(size)
            for lang in ("es", "en"):
                set_language(lang)
                _qt.process_events(40)
                self.assertEqual(header.details.displayed_text(), header.details.text(), (lang, size))
                self.assertTrue(header.badge.isVisible())
        set_language("es")

    def test_a_long_file_name_does_not_widen_the_file_card(self):
        """Un nombre largo sin espacios no puede partirse: la ficha se ensanchaba y la etiqueta UTF-16 perdía
        «el juego no puede leerlo». Ahora el nombre se recorta por el medio (la fila «Ruta» lo lleva entero)."""
        self.window.resize(MINIMUM_SIZE)
        self.set_mod()
        long_name = "definicion_de_provincias_con_un_nombre_larguisimo_que_no_cabe_en_la_ficha_" * 2 + "be.csv"
        for name in ("corto.csv", long_name):
            path = self.mod / "map" / name
            path.write_bytes(b"\xfe\xff" + "province;red\r\n".encode("utf-16-be"))
            self.assertTrue(self.project.reveal_file(path))
            self.wait(lambda: self.project.preview.facts is not None and self.project.preview.facts.path == path,
                      f"la ficha de {name} no apareció")
            _qt.process_events(60)
            preview, shown = self.project.preview, self.project.preview.form_values["encoding"]
            if name == "corto.csv":
                width = preview.width()
                continue
            self.assertEqual(preview.width(), width, "el nombre largo ensanchó la vista previa")
            self.assertEqual(preview.name.text(), long_name)
            self.assertNotEqual(preview.name.displayed_text(), long_name)
            self.assertIn(long_name, preview.form_values["path"].text())
            self.assertIn("el juego no puede leerlo", shown.text())
            self.assertGreaterEqual(shown.height(), shown.heightForWidth(shown.width()))

    def test_a_long_file_cut_inside_a_character_keeps_its_encoding(self):
        """De un archivo de más de ``MAX_SCAN_BYTES`` la ficha lee solo el principio; si el corte caía dentro
        de un carácter UTF-8, dejaba de ser UTF-8 válido y la ficha decía Windows-1252."""
        line = ("-- " + "Привет мир " * 8 + "\n").encode("utf-8")
        with mock.patch.object(project_page, "MAX_SCAN_BYTES", 4 * len(line) + 4):  # corta la «П» de la 5.ª línea
            path = self.mod / "common" / "largo.lua"
            path.write_bytes(line * 10)
            facts = project_page.gather_facts(path, self.mod)
        self.assertTrue(facts.partial)
        self.assertEqual(facts.encoding, UTF8)
        self.assertEqual(facts.lines, 5)

    def test_opening_a_csv_keeps_its_loading_message_visible(self):
        """FI-8: «Abriendo text.csv…» se sustituía al instante por «Módulo activo…»."""
        self.set_mod()
        self.window.open_in_localisation(self.mod / "localisation" / "test.csv")
        self.assertEqual(self.window.current_page_index(), PAGE_KEYS.index("localisation"))
        self.assertEqual(self.status(), "Abriendo test.csv…")
        localisation = self.window.page("localisation")
        self.wait(lambda: not localisation.is_busy(), "el CSV no cargó")


class DescriptorTests(PageCase):
    def test_backticks_in_the_mod_name_are_shown_as_typed(self):
        """CP-17: las comillas invertidas del nombre se emparejaban con las de la plantilla."""
        (self.mod.parent / "TestMod.mod").write_text('name = "My `beta` mod"\npath = "mod/TestMod"\n',
                                                     encoding="cp1252")
        self.set_mod()
        text = plain(self.project.mod_field.descriptor.text())
        self.assertIn("name My `beta` mod · path mod/TestMod · user_dir —", text)

    def test_validate_mod_reads_the_descriptor_again(self):
        """MISSED-3 y VAL-9: «Validar mod» usaba el descriptor y la carpeta leídos al elegir el mod."""
        self.set_mod()
        self.assertIn("user_dir —", plain(self.project.mod_field.descriptor.text()))
        (self.mod.parent / "TestMod.mod").write_text(
            'name = "Test Mod"\npath = "mod/TestMod"\nuser_dir = "TestDir"\n', encoding="cp1252")
        self.assertTrue(self.project.validate_mod())
        self.assertIn("user_dir TestDir", plain(self.project.mod_field.descriptor.text()))
        self.wait(lambda: self.project.validation_report() is not None, "la validación no terminó")
        shutil.rmtree(self.mod)
        self.assertFalse(self.project.validate_mod(), "una carpeta borrada no se valida como un mod sin problemas")
        self.assertEqual(self.project.mod_field.badge.level, "error")
        self.assertFalse(self.project.validate_button.isEnabled())

    def test_compact_mode_keeps_the_descriptor_reachable(self):
        """MISSED-4: en modo compacto desaparecía el enlace del descriptor y su path/user_dir."""
        self.set_mod()
        self.window.resize(1100, 700)
        _qt.process_events(50)
        field = self.project.mod_field
        self.assertTrue(field.status_action.isVisible())
        self.assertFalse(field.descriptor.isVisible())
        tooltip = field.status_action.toolTip()
        for fragment in ("TestMod.mod", "Test Mod", "path mod/TestMod", "user_dir —", "Haz clic en el icono"):
            self.assertIn(fragment, tooltip)
        field.status_action.trigger()
        viewer = self.project.clausewitz_viewer
        self.wait(lambda: viewer.current_load() is not None, "el descriptor no se abrió")
        self.assertEqual(viewer.current_path(), self.mod.parent / "TestMod.mod")


class ModFolderTests(unittest.TestCase):
    def test_game_folders_are_never_a_mod(self):
        """VAL-7 y VAL-M1: la carpeta que contiene el juego, o una subcarpeta suya, se aceptaban como mod."""
        with tempfile.TemporaryDirectory() as tmp:
            game, mod = build_game(Path(tmp))

            def status(path: Path) -> tuple[str, str]:
                return evaluate_mod(inspect_folder(path), game)[:2]

            self.assertEqual(status(game), ("error", "check.mod_is_game"))
            self.assertEqual(status(game / "events"), ("error", "check.mod_inside_game"))
            self.assertEqual(status(game / "history"), ("error", "check.mod_inside_game"))
            self.assertEqual(status(Path(tmp)), ("error", "check.mod_contains_game"))
            self.assertEqual(status(mod), ("ok", "check.mod_ok"))
            self.assertEqual(evaluate_mod(inspect_folder(game / "events"), None)[0], "warning")


class ImageViewerTests(unittest.TestCase):
    def setUp(self):
        _qt.take_qt_messages()
        set_language("es")
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.viewer = ImageViewer()
        # Ventana propia con tamaño mínimo fijo, como MainWindow: si no, el layout lo cambia al
        # maquetar y la plataforma offscreen avisa («does not support propagateSizeHints»).
        self.viewer.setMinimumSize(200, 200)
        self.viewer.resize(600, 500)
        self.viewer.show()

    def tearDown(self):
        self.viewer.close()
        self.assertTrue(wait_for_tasks(10000))
        self.assertEqual(_qt.dispose(self.viewer), [], "el visor de la prueba sigue vivo")
        _qt.process_events()
        self._tmp.cleanup()
        self.assertEqual(_qt.take_qt_messages(), [], "avisos de Qt durante la prueba")

    def load(self, path: Path) -> None:
        self.viewer.load(path, root=self.folder)
        self.assertTrue(_qt.wait_until(lambda: not self.viewer.is_busy(), TIMEOUT_MS), f"{path.name} no cargó")

    def center_color(self) -> tuple[int, int, int]:
        image = self.viewer.canvas.grab().toImage()
        return image.pixelColor(image.width() // 2, image.height() // 2).getRgb()[:3]

    def test_image_edited_outside_is_reloaded(self):
        """FI-2: al volver a seleccionar una imagen editada fuera se mostraba la versión vieja."""
        path = self.folder / "flag.tga"
        Image.new("RGB", (93, 64), (255, 0, 0)).save(path)
        self.load(path)
        self.assertEqual(self.center_color(), (255, 0, 0))
        self.load(path)  # sin cambios: no se vuelve a decodificar
        Image.new("RGB", (186, 128), (0, 0, 255)).save(path)
        os.utime(path, ns=(time.time_ns(), time.time_ns() + 1_000_000))
        self.load(path)
        load = self.viewer.current_load()
        self.assertEqual((load.width, load.height), (186, 128))
        self.assertIn("186 × 128 px", self.viewer.header.details.text())
        self.assertEqual(self.center_color(), (0, 0, 255))

    def test_failure_keeps_the_detail_paragraph_and_disables_the_zoom(self):
        """FI-11: el detalle técnico quedaba pegado al texto y Ajustar/100 % seguían activos."""
        good = self.folder / "good.png"
        Image.new("RGB", (10, 10)).save(good)
        broken = self.folder / "broken.tga"
        broken.write_bytes(b"no es una imagen")
        for path, usable in ((good, True), (broken, False), (good, True)):
            self.load(path)
            self.assertEqual(self.viewer.error() is None, usable, path.name)
            self.assertEqual(self.viewer.fit_button.isEnabled(), usable, path.name)
            self.assertEqual(self.viewer.actual_button.isEnabled(), usable, path.name)
        self.load(broken)
        self.assertIn("<br><br>Detalle:", self.viewer.failure.text.text())

    def test_read_errors_are_explained_and_not_blamed_on_pillow(self):
        """Sin permiso de lectura o borrada, la imagen se daba por «formato no compatible o archivo dañado»."""
        path = self.folder / "flag.dds"
        path.write_bytes(b"DDS ")
        denied = PermissionError(errno.EACCES, "Permission denied", str(path))
        with mock.patch.object(image_viewer_module, "open", side_effect=denied, create=True):
            self.load(path)
        for lang, reason, header in (("es", "no tienes permiso para leerlo", "flag.dds · no se pudo leer"),
                                     ("en", "you do not have permission to read it", "flag.dds · could not be read")):
            set_language(lang)
            self.viewer.retranslate()
            self.assertIn(reason, self.viewer.failure.text.text(), lang)
            self.assertNotIn("Pillow", self.viewer.failure.text.text(), lang)
            self.assertEqual(self.viewer.header.details.text(), header)
        set_language("es")
        self.viewer.retranslate()
        self.assertEqual(self.viewer.failure.toolTip(), f"{path}\nDetalle del sistema: Permission denied")
        self.assertFalse(self.viewer.fit_button.isEnabled())
        path.unlink()
        self.assertTrue(self.viewer.reload_if_changed())
        self.assertTrue(_qt.wait_until(lambda: not self.viewer.is_busy(), TIMEOUT_MS))
        self.assertIn("el archivo no existe", self.viewer.failure.text.text())
        broken = self.folder / "broken.tga"
        broken.write_bytes(b"no es una imagen")
        self.load(broken)  # lo que falla al decodificar sí es cosa de Pillow
        self.assertIn("Pillow no puede abrir esta imagen", self.viewer.failure.text.text())
        self.assertEqual(self.viewer.failure.toolTip(), "")

    def test_a_read_failure_is_retried_even_if_the_image_did_not_change(self):
        """R3: tras arreglar el permiso (sin cambiar fecha ni tamaño) la imagen no se volvía a leer."""
        path = self.folder / "flag.png"
        Image.new("RGB", (12, 8), (255, 0, 0)).save(path)
        denied = PermissionError(errno.EACCES, "Permission denied", str(path))
        with mock.patch.object(image_viewer_module, "open", side_effect=denied, create=True):
            self.load(path)
        self.assertIsNone(self.viewer.current_load())
        self.assertTrue(self.viewer.reload_if_changed(), "el permiso ya está arreglado")
        self.assertTrue(_qt.wait_until(lambda: not self.viewer.is_busy(), TIMEOUT_MS))
        self.assertEqual((self.viewer.current_load().width, self.viewer.current_load().height), (12, 8))
        broken = self.folder / "broken.tga"
        broken.write_bytes(b"no es una imagen")
        self.load(broken)
        self.assertIsNotNone(self.viewer.error())
        self.assertFalse(self.viewer.reload_if_changed(), "Pillow no la entiende: sin cambios no se reintenta")

    def test_retrying_a_read_failure_keeps_it_until_there_is_an_answer(self):
        """NF-R3-HEADER-BLINK: al reintentar un fallo de lectura se veían un instante el lienzo vacío y
        «cargando…» antes de volver al fallo. Este sigue a la vista hasta que hay respuesta o pasa el plazo."""
        viewer = self.viewer
        path = self.folder / "bandera.png"
        Image.new("RGB", (8, 6), (255, 0, 0)).save(path)
        failed = "bandera.png · no se pudo leer"
        seen = []
        set_details = viewer.header.set_details

        def record(text: str, *rest) -> None:
            seen.append((text, viewer.stack.currentWidget() is viewer.failure))
            set_details(text, *rest)

        denied = PermissionError(errno.EACCES, "Permission denied", str(path))
        with mock.patch.object(image_viewer_module, "open", side_effect=denied, create=True):
            self.load(path)
            with mock.patch.object(viewer.header, "set_details", record):
                self.assertTrue(viewer.reload_if_changed())
                self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), TIMEOUT_MS))
                _qt.process_events(2 * image_viewer_module.LOADING_DELAY_MS)
        self.assertTrue(seen)
        self.assertEqual(set(seen), {(failed, True)}, "un reintento que vuelve a fallar no parpadea")
        self.assertFalse(viewer.fit_button.isEnabled())
        gate = threading.Event()
        try_load_image = image_viewer_module.try_load_image

        def slow(*args, **kwargs):
            gate.wait(TIMEOUT_MS / 1000)
            return try_load_image(*args, **kwargs)

        # Un reintento cancelado (se elige otro archivo) nunca responderá: el fallo sigue, sin «cargando…».
        with mock.patch.object(image_viewer_module, "try_load_image", slow):
            self.assertTrue(viewer.reload_if_changed())
            viewer.cancel()
            _qt.process_events(2 * image_viewer_module.LOADING_DELAY_MS)
            gate.set()
            self.assertTrue(wait_for_tasks(TIMEOUT_MS))  # la tarea cancelada termina sin respuesta
        _qt.process_events(20)
        self.assertEqual((viewer.stack.currentWidget(), viewer.header.details.text()), (viewer.failure, failed))
        self.assertIsNotNone(viewer.error())
        gate.clear()
        # Ya se puede leer, pero tarda: el fallo sigue hasta el plazo; luego, «cargando…» en el lienzo.
        try:
            with mock.patch.object(image_viewer_module, "try_load_image", slow):
                self.assertTrue(viewer.reload_if_changed())
                self.assertIs(viewer.stack.currentWidget(), viewer.failure)
                self.assertEqual(viewer.header.details.text(), failed)
                self.assertTrue(_qt.wait_until(lambda: viewer.stack.currentWidget() is viewer.scroll, TIMEOUT_MS))
                self.assertEqual(viewer.header.details.text(), "bandera.png · cargando…")
                self.assertIsNone(viewer.error())
                gate.set()
                self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), TIMEOUT_MS))
        finally:
            gate.set()
        self.assertEqual(self.center_color(), (255, 0, 0))
        self.assertTrue(viewer.fit_button.isEnabled())
        # Si responde antes del plazo, la imagen sustituye directamente al fallo.
        os.utime(path, ns=(time.time_ns(), time.time_ns() + 1_000_000))
        with mock.patch.object(image_viewer_module, "open", side_effect=denied, create=True):
            self.assertTrue(viewer.reload_if_changed())
            self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), TIMEOUT_MS))
        self.assertIs(viewer.stack.currentWidget(), viewer.failure)
        viewer._loading_timer.setInterval(10 * TIMEOUT_MS)  # que responda antes aunque la máquina vaya lenta
        self.assertTrue(viewer.reload_if_changed())
        self.assertTrue(_qt.wait_until(lambda: not viewer.is_busy(), TIMEOUT_MS))
        self.assertIs(viewer.stack.currentWidget(), viewer.scroll)
        self.assertTrue(viewer.header.details.text().startswith("bandera.png · PNG · 8 × 6 px · RGB · "))
        self.assertEqual(self.center_color(), (255, 0, 0))

    def test_a_narrow_header_shortens_the_path_first(self):
        """Como en el visor de scripts: con poco ancho se acorta la ruta y no el formato o el tamaño."""
        path = self.folder / "gfx" / "flags" / "bandera_con_un_nombre_bastante_largo.png"
        path.parent.mkdir(parents=True)
        Image.new("RGB", (8, 6)).save(path)
        self.load(path)
        details = self.viewer.header.details
        full = details.text()
        tail = full[full.index(" · PNG · 8 × 6 px · RGB · "):]
        self.assertEqual(full, "gfx/flags/bandera_con_un_nombre_bastante_largo.png" + tail)
        details.setFixedWidth(details.fontMetrics().horizontalAdvance(full) // 2)
        shown = details.displayed_text()
        self.assertTrue(shown.startswith("gfx") and "…" in shown and shown.endswith(tail), shown)

    def test_loading_text_and_reduced_side(self):
        """FI-12: «analizando…» al cargar una imagen y «mostrada a N px» con el ancho y no con el lado mayor."""
        tall = self.folder / "tall.png"
        Image.new("RGB", (20, 100), (0, 0, 0)).save(tall)
        release = threading.Event()
        original = image_viewer_module.try_load_image
        with mock.patch.object(image_viewer_module, "MAX_DISPLAY_SIDE", 50), \
                mock.patch.object(image_viewer_module, "try_load_image",
                                  lambda path, **kw: release.wait(TIMEOUT_MS / 1000) and original(path, **kw)):
            self.viewer.load(tall, root=self.folder)
            self.assertEqual(self.viewer.header.details.text(), "tall.png · cargando…")
            release.set()
            self.assertTrue(_qt.wait_until(lambda: not self.viewer.is_busy(), TIMEOUT_MS))
        load = self.viewer.current_load()
        self.assertEqual((load.image.width(), load.image.height()), (10, 50))
        self.assertTrue(self.viewer.header.details.text().endswith("mostrada a 50 px"))

    def test_gif_images_open_in_the_viewer(self):
        """FI-5 y FI-13: un solo conjunto de extensiones de imagen, con .gif incluido."""
        path = self.folder / "anim.gif"
        Image.new("RGB", (20, 10), (10, 120, 40)).save(path)
        self.assertEqual(preview_kind(path), "image")
        self.load(path)
        self.assertEqual((self.viewer.current_load().width, self.viewer.current_load().height), (20, 10))

    def test_rich_text_keeps_line_breaks(self):
        state = EmptyState("info")
        state.set_texts("t", "uno\n\ndos `x`")
        self.assertIn("uno<br><br>dos", state.text.text())
        _qt.dispose(state)


class ImageSelectionTests(PageCase):
    def test_selecting_an_image_decodes_it_once_outside_the_ui_thread(self):
        """FI-5: la ficha oculta decodificaba cada imagen en el hilo de la interfaz para una miniatura."""
        self.set_mod()
        opened = []
        original = Image.open

        def spy(*args, **kwargs):
            opened.append(threading.current_thread() is threading.main_thread())
            return original(*args, **kwargs)

        with mock.patch.object(Image, "open", spy):
            self.assertTrue(self.project.reveal_file(self.mod / "gfx" / "flags" / "TST.tga"))
            image = self.project.image_viewer
            self.wait(lambda: image.current_load() is not None, "la imagen no cargó")
        self.assertEqual(opened, [False])
        self.assertIs(self.project.preview_widget(), image)


class SlowCheck:
    """Sustituto de ``check_mod`` que no termina hasta que se suelta o se cancela.

    Antes de esperar avisa de ``step`` (``hechos, total, ruta``), como el núcleo.
    """

    def __init__(self, fail: str | None = None, step: tuple[int, int, str] | None = None):
        self.release = threading.Event()
        self.started = threading.Event()
        self.fail = fail
        self.step = step
        self.calls = 0

    def __call__(self, root, *, extra_files=(), progress=None, cancelled=None):
        self.calls += 1
        if self.step is not None and progress is not None:
            progress(*self.step)
        self.started.set()
        while not self.release.wait(0.005):
            if cancelled is not None and cancelled():
                raise Cancelled()
        if self.fail:
            raise MemoryError(self.fail)
        from vic2studio.core.modcheck import check_mod
        return check_mod(root, extra_files=extra_files, progress=progress, cancelled=cancelled)


class ValidationStateTests(PageCase):
    def run_slow(self, check: SlowCheck):
        patcher = mock.patch.object(validation_panel_module, "check_mod", check)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(check.release.set)
        self.assertTrue(self.project.validate_mod())
        self.assertTrue(check.started.wait(TIMEOUT_MS / 1000))

    def tab_text(self) -> str:
        return self.project.left_tabs.tabText(1)

    def validate_with_errors(self) -> None:
        (self.mod / "decisions" / "broken.txt").write_text("political_decisions = {\n", encoding="cp1252")
        self.assertTrue(self.project.validate_mod())
        self.wait(lambda: self.project.validation_report() is not None, "la validación no terminó")
        self.assertEqual(self.tab_text(), tr("project.tab.validation_count", count=1))

    def test_validate_button_is_disabled_while_validating(self):
        """VAL-2: el botón de la cabecera seguía activo y reiniciaba la validación."""
        self.set_mod()
        check = SlowCheck()
        self.run_slow(check)
        self.assertTrue(self.project.validation.is_busy())
        self.assertFalse(self.project.validate_button.isEnabled())
        self.project.validate_button.click()
        self.assertEqual(check.calls, 1)
        check.release.set()
        self.wait(lambda: self.project.validation_report() is not None, "la validación no terminó")
        self.assertTrue(self.project.validate_button.isEnabled())

    def test_tab_and_status_follow_mod_change_cancel_and_failure(self):
        """VAL-3: «Validación (N)» y la barra de estado no se actualizaban al cambiar de mod, cancelar o fallar."""
        self.set_mod()
        self.validate_with_errors()
        self.project.set_mod_path(self.game / "mod")  # otro mod
        self.assertEqual(self.tab_text(), "Validación")
        self.set_mod()
        self.validate_with_errors()
        self.run_slow(SlowCheck())
        self.assertEqual(self.tab_text(), "Validación")
        self.project.validation.cancel_button.click()
        self.assertEqual(self.tab_text(), "Validación")
        self.assertEqual(self.status(), "Validación cancelada")
        self.assertTrue(self.project.validate_button.isEnabled())
        check = SlowCheck(fail="sin memoria simulada")
        self.run_slow(check)
        with self.assertLogs("vic2studio.ui.tasks", "WARNING"):  # la traza del fallo va al registro
            check.release.set()
            self.wait(lambda: not self.project.validation.is_busy(), "la validación no falló")
        self.assertEqual(self.tab_text(), "Validación")
        self.assertEqual(self.status(), "No se pudo validar el mod: MemoryError: sin memoria simulada")
        self.assertTrue(self.project.validate_button.isEnabled())

    def test_progress_label_starts_empty(self):
        """VAL-5: la etiqueta mostraba un archivo de la validación anterior (de otro mod)."""
        self.set_mod()
        panel = self.project.validation
        self.run_slow(SlowCheck(step=(2, 9, "decisions/c.txt")))
        self.wait(lambda: panel.current_file.text() == "decisions/c.txt", "no llegó el progreso")
        panel.cancel()
        self.run_slow(SlowCheck())
        self.assertEqual(panel.current_file.text(), "")
        self.assertEqual(panel.running_title.text(), "Validando el mod…")

    def test_scanning_shows_the_folder_and_can_be_cancelled(self):
        """VAL-M3: mientras el núcleo explora las carpetas, el panel lo dice y «Cancelar» lo detiene."""
        self.set_mod()
        panel = self.project.validation
        check = SlowCheck(step=(0, 0, "history/provinces"))
        self.run_slow(check)
        self.wait(lambda: panel.current_file.text() == "history/provinces", "no llegó el progreso")
        self.assertEqual(panel.running_title.text(), "Buscando los archivos del mod…")
        self.assertEqual(panel.progress_bar.maximum(), 0, "sin total, la barra es indeterminada")
        set_language("en")
        self.assertEqual(panel.running_title.text(), "Looking for the mod's files…")
        panel.cancel_button.click()
        self.assertFalse(panel.is_busy())
        self.assertTrue(wait_for_tasks(TIMEOUT_MS), "la exploración cancelada siguió en marcha")

    def test_missing_file_and_duration_in_the_status_bar(self):
        """VAL-10 y VAL-11: la fila de un archivo borrado no avisaba y la duración se redondeaba a «0,0 s»."""
        self.set_mod()
        self.validate_with_errors()
        report = self.project.validation_report()
        self.assertIn(f"terminada en {translator().locale().toString(report.elapsed, 'f', 2)} s", self.status())
        panel = self.project.validation
        broken = next(r for r in panel.model.all_rows() if r.relative == "decisions/broken.txt")
        (self.mod / "decisions" / "broken.txt").unlink()
        panel.issue_activated.emit(broken)
        self.assertEqual(self.status(), "decisions/broken.txt ya no existe: vuelve a validar el mod")

    def test_rows_are_built_in_the_validation_task(self):
        """VAL-8: con decenas de miles de diagnósticos, construir las filas al recibir el informe paraba la UI."""
        builders = []
        build = validation_panel_module.issue_rows

        def spy(report):
            builders.append(threading.current_thread() is threading.main_thread())
            return build(report)

        self.set_mod()
        with mock.patch.object(validation_panel_module, "issue_rows", spy):
            self.validate_with_errors()
        self.assertEqual(builders, [False], "las filas se construyeron en el hilo de la interfaz")
        panel = self.project.validation
        self.assertEqual([r.source for r in panel.model.all_rows()], panel.report().issues)

    def test_severity_filter_shows_its_whole_text(self):
        """VAL-12: el combo «Todas las gravedades» se quedaba con el ancho del idioma en que se mostró primero."""
        set_language("en")
        self.set_mod()
        self.validate_with_errors()
        self.project.left_tabs.setCurrentWidget(self.project.validation)
        _qt.process_events(50)
        combo = self.project.validation.severity_combo
        for language in ("es", "en"):
            set_language(language)
            _qt.process_events(50)
            fresh = QComboBox()  # mismo estilo y textos, medido desde cero
            fresh.setObjectName(combo.objectName())
            fresh.addItems([combo.itemText(i) for i in range(combo.count())])
            self.assertGreaterEqual(combo.width(), fresh.sizeHint().width(), language)
            _qt.dispose(fresh)

    def test_tab_text_is_translated(self):
        self.set_mod()
        self.validate_with_errors()
        set_language("en")
        self.assertEqual(self.tab_text(), "Validation (1)")
        self.assertEqual(tr("project.tab.validation"), "Validation")


if __name__ == "__main__":
    unittest.main()
