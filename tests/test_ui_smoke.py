"""Ventana principal (offscreen): las 7 salas y sus secciones, la navegación, los textos y las preferencias.

Las pruebas del armazón con un proyecto abierto (guardar, deshacer, conflictos, cerrar con cambios) están en
``test_ui_shell.py``; las del descriptor, en ``test_ui_descriptor.py``.
"""

import math
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
from _corpus import corpus_roots  # noqa: E402
from _fake_project import isolate_app_dirs  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QSize, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QAction, QFontMetricsF, QGuiApplication, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QTabWidget,
    QWidget,
)

APP = _qt.application()
isolate_app_dirs()

from vic2studio.i18n import language, set_language, translator  # noqa: E402
from vic2studio.ui import theme  # noqa: E402
from vic2studio.ui.halls import HALL_KEYS  # noqa: E402
from vic2studio.ui.main_window import COMPACT_RAIL_WIDTH, MINIMUM_SIZE, MainWindow  # noqa: E402
from vic2studio.ui.pages import PAGE_KEYS, LocalisationPage, PlannedSectionPage, ProjectPage  # noqa: E402
from vic2studio.ui.shell import SectionRail  # noqa: E402
from vic2studio.ui.pages.project_page import (  # noqa: E402
    evaluate_game,
    evaluate_mod,
    inspect_folder,
    name_filters,
    same_folder,
)
from vic2studio.ui.tasks import wait_for_tasks  # noqa: E402
from vic2studio.ui.widgets import icon_names  # noqa: E402
from vic2studio.ui.widgets.icons import icon_pixmap  # noqa: E402

PSEUDO = "qps"
MARK_OPEN, MARK_CLOSE = "⟦", "⟧"
# Placas cortas de wizard §13.1, en español y en inglés.
PLATES = {"es": ["Proyecto", "Mapa", "Naciones", "Guerra", "Eventos", "Interfaz", "Textos"],
          "en": ["Project", "Map", "Nations", "War", "Events", "Interface", "Texts"]}


def _is_data(widget: QWidget) -> bool:
    return bool(widget.property("i18nData"))


def collect_texts(root: QWidget) -> dict[str, str]:
    """Todo texto visible para el usuario: textos, títulos, tooltips, placeholders, cabeceras y acciones."""
    texts: dict[str, str] = {}

    def add(owner, what: str, value: str) -> None:
        if value and value.strip():
            texts[f"{type(owner).__name__}#{owner.objectName()}@{id(owner):x}.{what}"] = value

    for widget in [root, *root.findChildren(QWidget)]:
        add(widget, "toolTip", widget.toolTip())
        if isinstance(widget, QMainWindow):
            add(widget, "windowTitle", widget.windowTitle())
        if _is_data(widget):
            continue
        if isinstance(widget, QLabel):
            add(widget, "text", widget.text())
        elif isinstance(widget, QAbstractButton):
            add(widget, "text", widget.text())
        if isinstance(widget, QLineEdit):
            add(widget, "placeholder", widget.placeholderText())
        if isinstance(widget, QGroupBox):
            add(widget, "title", widget.title())
        if isinstance(widget, QComboBox):
            for i in range(widget.count()):
                add(widget, f"item{i}", widget.itemText(i))
        if isinstance(widget, QTabWidget):
            for i in range(widget.count()):
                add(widget, f"tab{i}", widget.tabText(i))
        if isinstance(widget, QAbstractItemView) and widget.model() is not None and hasattr(widget, "header"):
            header = widget.header()
            for section in range(widget.model().columnCount()):
                if not header.isSectionHidden(section):
                    add(widget, f"header{section}", str(widget.model().headerData(
                        section, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) or ""))
    for action in root.findChildren(QAction):
        if action.isSeparator():
            continue
        add(action, "text", action.text())
        add(action, "toolTip", action.toolTip())
    return texts


def pseudo_catalog() -> dict[str, str]:
    return {key: f"{MARK_OPEN}{value}{MARK_CLOSE}" for key, value in translator().catalog("en").items()}


class UiTestCase(unittest.TestCase):
    def setUp(self):
        _qt.reset_settings()
        set_language("es")
        _qt.take_qt_messages()
        self.missing_before = translator().missing_keys()
        self.windows: list[MainWindow] = []

    def tearDown(self):
        for window in self.windows:
            window.close()
        self.assertTrue(wait_for_tasks(10000), "quedaron tareas en segundo plano")
        _qt.process_events()
        self.assertEqual(_qt.dispose(*self.windows), [], "ventanas de la prueba que siguen vivas")
        self.assertEqual(_qt.live_main_windows(), [], "quedó viva otra ventana principal")
        _qt.process_events()
        set_language("es")
        _qt.process_events()
        self.assertEqual(_qt.take_qt_messages(), [], "avisos de Qt durante la prueba")
        self.assertEqual(sorted(translator().missing_keys() - self.missing_before), [],
                         "claves pedidas en tiempo de ejecución que no existen")

    def enter_context(self, manager):
        """``TestCase.enterContext``, que no existe hasta Python 3.11."""
        value = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        return value

    def make_window(self, show: bool = True, **kwargs) -> MainWindow:
        window = MainWindow(**kwargs)
        self.windows.append(window)
        if show:
            window.resize(1440, 900)
            window.show()
            _qt.process_events(50)
        return window


class MainWindowTests(UiTestCase):
    def test_contract(self):
        window = self.make_window()
        self.assertEqual([hall.spec.key for hall in window.halls], list(HALL_KEYS))
        self.assertEqual(HALL_KEYS, ("project", "map", "nations", "war", "events", "interface", "localisation"))
        for index, key in enumerate(HALL_KEYS):
            self.assertIs(window.hall(key), window.halls[index])
        # Compatibilidad con la iteración 1: las dos páginas siguen a mano con su clave.
        self.assertEqual(PAGE_KEYS, ("project", "localisation"))
        self.assertIsInstance(window.page("project"), ProjectPage)
        self.assertIsInstance(window.page("localisation"), LocalisationPage)
        self.assertIs(window.page("project"), window.hall("project").section_widget("files"))
        self.assertIs(window.page("localisation"), window.hall("localisation").section_widget("csv"))
        self.assertIs(window.page("home"), window.page("project:home"))
        # map:forge (iteración 9a) era la última tarjeta planificada: ahora es el taller de mapas.
        from vic2studio.ui.halls.map.forge import ForgePage

        self.assertIsInstance(window.page("map:forge"), ForgePage)
        self.assertIs(window.page("map.forge"), window.page("map:forge"))
        for bad in ("nope", "war:nope", "nope:cb"):
            with self.assertRaises(KeyError):
                window.page(bad)
        self.assertGreaterEqual(window.minimumWidth(), 1100)
        self.assertGreaterEqual(window.minimumHeight(), 700)
        self.assertEqual(window.banner.title_label.text(), "Victoria II Mod Studio")
        self.assertEqual([window.language_combo.itemData(i) for i in range(window.language_combo.count())],
                         ["es", "en"])
        self.assertEqual(len(window.sections()), sum(len(hall.sections) for hall in window.halls))

    def test_opens_on_home_and_compat_page_index(self):
        window = self.make_window()
        self.assertEqual(window.current_hall_index(), 0)
        self.assertEqual(window.current_page_key(), "project:home")
        self.assertEqual(window.current_page_index(), -1, "Inicio no es ninguna de las páginas de la iteración 1")
        window.set_current_page(PAGE_KEYS.index("localisation"))
        self.assertEqual((window.current_hall_index(), window.current_page_key()), (6, "localisation"))
        self.assertTrue(window.page("localisation").isVisible())
        window.set_current_page(0)
        self.assertEqual(window.current_page_index(), 0)
        self.assertTrue(window.page("project").isVisible())
        with self.assertRaises(IndexError):
            window.set_current_page(len(PAGE_KEYS))
        with self.assertRaises(IndexError):
            window.set_current_hall(len(HALL_KEYS))

    def test_walk_every_hall_and_section(self):
        window = self.make_window()
        # Se empieza por la segunda sala: así cambiar a cada una (también a Proyecto, al final) avisa en el estado.
        for index in [*range(1, len(window.halls)), 0]:
            hall = window.halls[index]
            window.set_current_hall(index)
            _qt.process_events(10)
            self.assertIs(window.stack.currentWidget(), hall)
            self.assertTrue(window.nav.buttons[index].isChecked())
            for section, widget in enumerate(hall.widgets):
                hall.set_current_section(section)
                _qt.process_events(10)
                self.assertIs(hall.current_widget(), widget)
                self.assertTrue(widget.isVisible(), f"{hall.spec.key}:{hall.sections[section].key}")
                self.assertTrue(hall.rail.buttons[section].isChecked())
                title = hall.section_title()
                self.assertIn(title, window.windowTitle())
                self.assertIn(title, window.status_label.text())
                self.assertIn(PLATES["es"][index], window.windowTitle())
            self.assertFalse(window.grab().toImage().isNull())

    def test_nav_click_and_rail_click(self):
        window = self.make_window()
        QTest.mouseClick(window.nav.buttons[3], Qt.MouseButton.LeftButton)
        self.assertEqual(window.current_hall_index(), 3)
        war = window.hall("war")
        QTest.mouseClick(war.rail.buttons[3], Qt.MouseButton.LeftButton)
        self.assertEqual(war.current_section().key, "cb")
        self.assertEqual(window.current_page_key(), "war:cb")

    def test_ctrl_number_shortcuts(self):
        window = self.make_window()
        window.activateWindow()
        self.assertTrue(QTest.qWaitForWindowActive(window, 2000), "la ventana no llegó a activarse")
        for number in (3, 7, 1, 5, 2, 6, 4):
            QTest.keyClick(window, Qt.Key(Qt.Key.Key_0 + number), Qt.KeyboardModifier.ControlModifier)
            _qt.process_events()
            self.assertEqual(window.current_hall_index(), number - 1, f"Ctrl+{number}")
        self.assertEqual([a.shortcut().toString() for a in window.hall_actions()],
                         [f"Ctrl+{n}" for n in range(1, 8)])
        self.assertEqual([s.toString() for s in window.save_action.shortcuts()], ["Ctrl+S"])
        self.assertEqual([s.toString() for s in window.undo_action.shortcuts()], ["Ctrl+Z"])
        self.assertEqual([s.toString() for s in window.redo_action.shortcuts()], ["Ctrl+Y", "Ctrl+Shift+Z"])
        self.assertEqual([s.toString() for s in window.validate_action.shortcuts()], ["F7"])

    def test_arrow_keys_move_between_halls_and_sections(self):
        window = self.make_window()
        window.activateWindow()
        QTest.qWaitForWindowActive(window, 2000)
        window.set_current_hall(0)
        window.nav.buttons[0].setFocus(Qt.FocusReason.TabFocusReason)
        QTest.keyClick(window.nav.buttons[0], Qt.Key.Key_Right)
        _qt.process_events()
        self.assertEqual(window.current_hall_index(), 1)
        QTest.keyClick(window.focusWidget(), Qt.Key.Key_Left)
        _qt.process_events()
        self.assertEqual(window.current_hall_index(), 0)
        rail = window.hall("project").rail
        rail.buttons[0].setFocus(Qt.FocusReason.TabFocusReason)
        QTest.keyClick(rail.buttons[0], Qt.Key.Key_Down)
        _qt.process_events()
        self.assertEqual(window.current_page_key(), "project:descriptor")
        QTest.keyClick(window.focusWidget(), Qt.Key.Key_Up)
        self.assertEqual(window.current_page_key(), "project:home")

    def test_plates_fit_in_one_line_at_the_minimum_size(self):
        """wizard §13.1: las placas cortas caben a 1100 px, en una línea y sin recortar."""
        window = self.make_window()
        window.resize(MINIMUM_SIZE)
        _qt.process_events(50)
        for lang in ("es", "en"):
            set_language(lang)
            _qt.process_events(20)
            self.assertEqual([button.text() for button in window.nav.buttons], PLATES[lang])
            self.assertEqual([button.label_text() for button in window.nav.buttons], PLATES[lang], lang)

    def test_nav_button_wraps_and_elides_a_long_name(self):
        """REVIEW-NAV-NAMES: un nombre que no cabe se parte en dos líneas sin dejar una palabra corta al final de
        la primera y, si ni así cabe, se recorta."""
        window = self.make_window()
        button = window.nav.buttons[1]
        button.setText("Editor de Mapa")
        metrics = QFontMetricsF(button.font())
        lines = ("Editor", "de Mapa")
        room = max(metrics.horizontalAdvance(line) for line in lines) + 2
        self.assertGreater(metrics.horizontalAdvance(button.text()), room)
        button.setFixedWidth(math.ceil(room) + 81)  # 81: icono, número y márgenes de ``NavButton.label_text``
        self.assertEqual(button.label_text(), "\n".join(lines))
        painted, label_text = [], type(button).label_text
        with mock.patch.object(type(button), "label_text", lambda self: painted.append(self) or label_text(self)):
            button.grab()
        self.assertIn(button, painted, "se pinta lo que devuelve label_text()")
        button.setFixedWidth(math.ceil(metrics.horizontalAdvance("Editor") / 2) + 81)
        self.assertTrue(button.label_text().endswith("…"), "si ni en dos líneas cabe, se recorta")

    def test_rail_is_a_column_with_room_and_a_strip_when_narrow(self):
        window = self.make_window()
        hall = window.hall("war")
        window.set_current_hall(3)
        window.resize(COMPACT_RAIL_WIDTH + 80, 900)
        _qt.process_events(50)
        self.assertFalse(hall.rail.compact)
        self.assertTrue(hall.rail.heading.isVisible())
        self.assertLess(hall.rail.width(), hall.width() // 4)
        self.assertGreater(hall.frame.x(), hall.rail.x(), "la columna va a la izquierda de la sección")
        window.resize(MINIMUM_SIZE)
        _qt.process_events(50)
        self.assertTrue(hall.rail.compact)
        self.assertFalse(hall.rail.heading.isVisible())
        self.assertGreater(hall.frame.y(), hall.rail.y(), "la franja va encima de la sección")
        self.assertEqual(hall.frame.width(), hall.width(), "la sección conserva todo el ancho")
        for lang in ("es", "en"):
            set_language(lang)
            for index, current in enumerate(window.halls):
                window.set_current_hall(index)  # una sala oculta no se maqueta: se mira la que está a la vista
                _qt.process_events(20)
                self.assertTrue(current.rail.compact)
                for button in current.rail.buttons:
                    self.assertFalse(button.label_text().endswith("…"), (lang, button.text()))
                    self.assertGreater(button.width(), 0)
                # Placas bajas si caben los nombres en una línea; si no, altas y en dos líneas.
                slim = current.rail.strip_fits_one_line()
                self.assertEqual(current.rail.height(), SectionRail.STRIP_HEIGHT if slim
                                 else SectionRail.TALL_STRIP_HEIGHT, (lang, current.spec.key))
                if slim:
                    self.assertTrue(all("\n" not in b.label_text() for b in current.rail.buttons))
        # Desde la iteración 6 todas las salas caben en placas bajas a 1100 px, también en español (Guerras y
        # Diplomacia ya no llevan «It. 6»). La altura alta se prueba con la franja de Guerra a la mitad de ancho.
        set_language("es")
        for key in ("project", "war"):
            window.set_current_hall(next(i for i, hall in enumerate(window.halls) if hall.spec.key == key))
            _qt.process_events(20)
            self.assertTrue(window.hall(key).rail.strip_fits_one_line(), key)
        war = window.hall("war").rail
        self.assertFalse(war.strip_fits_one_line(war.width() // 2), "a media franja, seis secciones no caben")

    def test_planned_sections_say_their_iteration(self):
        window = self.make_window()
        for hall in window.halls:
            for spec, widget, button in zip(hall.sections, hall.widgets, hall.rail.buttons):
                if not spec.planned:
                    self.assertEqual(button.tag, "")
                    continue
                with self.subTest(section=f"{hall.spec.key}:{spec.key}"):
                    self.assertIsInstance(widget, PlannedSectionPage)
                    self.assertIn(str(spec.iteration), widget.ribbon.text())
                    self.assertIn(str(spec.iteration), widget.arrival.text())
                    self.assertEqual(button.tag, f"It. {spec.iteration}")
                    self.assertIn(str(spec.iteration), button.toolTip())
                    self.assertEqual(len(widget.items), len(spec.planned_keys) - 1)
                    self.assertTrue(all(item.text() for item in widget.items))

    def test_language_combo_switches_language(self):
        window = self.make_window()
        window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
        self.assertEqual(language(), "en")
        self.assertEqual(window.nav.buttons[1].text(), "Map")
        self.assertEqual(window.hall("map").rail.heading.text(), "Map Editor")
        set_language("es")
        self.assertEqual(window.language_combo.currentData(), "es")
        self.assertEqual(window.nav.buttons[1].text(), "Mapa")

    def test_language_switch_retranslates_every_widget(self):
        window = self.make_window()
        es_catalog = translator().catalog("es")
        en_catalog = translator().catalog("en")
        spanish_only = {v for k, v in es_catalog.items() if v != en_catalog[k]}
        for key in ("project:home", "project:descriptor", "project", "project:pending", "map:world", "war:cb",
                    "localisation"):
            window.show_page(key)
            set_language("es")
            before = collect_texts(window)
            set_language("en")
            after = collect_texts(window)
            self.assertEqual(before.keys(), after.keys(), key)
            changed = [k for k in before if before[k] != after[k]]
            self.assertGreater(len(changed), 40, f"{key}: muy pocos textos cambiaron de idioma")
            stale = {k: v for k, v in after.items() if v in spanish_only}
            self.assertEqual(stale, {}, f"{key}: textos que siguen en español tras cambiar a inglés")
            set_language("es")
            self.assertEqual(collect_texts(window), before, f"{key}: volver a español no restaura los textos")

    def test_pseudo_locale_covers_all_visible_text(self):
        """Con un catálogo marcado ⟦…⟧, todo texto visible de cada sección debe venir del catálogo."""
        window = self.make_window()
        mod = self.enter_context(_temp_mod())
        window.page("project").set_mod_path(mod)
        _qt.wait_until(lambda: not window.is_busy())
        translator().register_catalog(PSEUDO, pseudo_catalog())
        for hall in window.halls:
            for section in hall.sections:
                window.show_page(f"{hall.spec.key}:{section.key}")
                set_language(PSEUDO)
                texts = collect_texts(window)
                self.assertGreater(len(texts), 60)
                untranslated = {k: v for k, v in texts.items() if MARK_OPEN not in v}
                self.assertEqual(untranslated, {}, f"{hall.spec.key}:{section.key}: textos que no pasan por tr()")
                set_language("es")

    def test_settings_are_restored(self):
        window = self.make_window()
        window.show_page("war:cb")
        window.show_page("project:descriptor")
        window.set_current_hall(3)
        set_language("en")
        window.resize(1300, 820)
        _qt.process_events(20)
        window.close()
        second = self.make_window(show=False)
        self.assertEqual(second.current_hall_index(), 3)
        self.assertEqual(second.current_page_key(), "war:cb")
        self.assertEqual(second.hall("project").current_section().key, "descriptor")
        self.assertEqual(second.language_combo.currentData(), "en")
        self.assertEqual(second.nav.buttons[0].text(), "Project")
        # restoreGeometry encoge la ventana si no cabe en la pantalla virtual de offscreen.
        available = QGuiApplication.primaryScreen().availableGeometry()
        if available.width() >= 1300 and available.height() >= 820:
            self.assertEqual(second.size(), QSize(1300, 820))
        else:
            self.assertTrue(second.restoreGeometry(window.saveGeometry()))


class _temp_mod:
    """Mod mínimo en una carpeta temporal: <tmp>/mod/MiMod + <tmp>/mod/MiMod.mod."""

    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name) / "mod"
        mod = base / "MiMod"
        (mod / "common").mkdir(parents=True)
        (mod / "localisation").mkdir()
        (mod / "history" / "countries").mkdir(parents=True)
        (mod / "common" / "countries.txt").write_bytes("GER = \"countries/Germany.txt\"\n# Ñandú\n".encode("cp1252"))
        (mod / "localisation" / "mimod.csv").write_bytes(b"KEY;Hello;;;;Hola;;;;;;;;;x\n")
        (mod / "gfx" / "flags").mkdir(parents=True)
        Image.new("RGB", (93, 64), (200, 30, 40)).save(mod / "gfx" / "flags" / "MIM.tga")
        (base / "MiMod.mod").write_text('name = "Mi Mod"\npath = "mod/MiMod"\nuser_dir = "MiMod"\n', encoding="cp1252")
        return mod

    def __exit__(self, *exc) -> None:
        self._tmp.cleanup()


class ProjectPageTests(UiTestCase):
    """«Archivos» (la página «Proyecto y Archivos» de la iteración 1), ahora una sección de la sala Proyecto.

    La ventana abre en Proyecto › Inicio: las pruebas que miran lo que se ve ponen antes «Archivos» a la vista.
    """

    def make_window(self, show: bool = True, **kwargs) -> MainWindow:
        window = super().make_window(show, **kwargs)
        if show:
            window.show_page("project")
            _qt.process_events(20)
        return window

    def test_temp_mod_validation_explorer_and_preview(self):
        window = self.make_window()
        window.set_current_page(0)
        project = window.page("project")
        mod = self.enter_context(_temp_mod())
        paths = []
        project.mod_path_changed.connect(paths.append)
        project.set_mod_path(mod)
        self.assertEqual(paths, [mod])
        self.assertEqual(project.mod_field.badge.level, "ok")
        present = {chip.folder for chip in project.mod_field.chips if chip.property("present")}
        self.assertEqual(present, {"common", "history", "localisation", "gfx"})
        self.assertIn("Mi Mod", project.mod_field.descriptor.text())
        self.assertTrue(_qt.wait_until(lambda: not project.is_busy()), "el explorador no terminó de cargar")
        self.assertEqual(project.explorer_root(), mod)

        # Lo que se comprueba es lo que se ve: dentro de un QStackedWidget, isVisible() y no isVisibleTo().
        activated = []
        project.file_activated.connect(activated.append)
        target = mod / "common" / "countries.txt"
        self.assertTrue(project.reveal_file(target))
        _qt.process_events(50)
        self.assertEqual(activated, [target])
        self.assertIsInstance(activated[0], Path)
        viewer = project.clausewitz_viewer
        self.assertTrue(_qt.wait_until(lambda: viewer.current_load() is not None and not project.is_busy()))
        self.assertIs(project.preview_widget(), viewer)
        self.assertTrue(viewer.isVisible())
        self.assertFalse(project.preview.isVisible())
        self.assertEqual(viewer.header.name.text(), "countries.txt")
        self.assertIn("common/countries.txt", viewer.header.details.text())
        self.assertIn("1252", viewer.header.details.text())
        self.assertIn("Ñandú", viewer.code.text_document().toPlainText())  # se cuelga al ver la pestaña
        self.assertIn("common/countries.txt", window.status_label.text())
        self.assertFalse(project.reveal_file(Path(tempfile.gettempdir())))

        # Seleccionar una imagen en el explorador la muestra en ImageViewer, a su tamaño.
        self.assertTrue(project.reveal_file(mod / "gfx" / "flags" / "MIM.tga"))
        image = project.image_viewer
        self.assertTrue(_qt.wait_until(lambda: image.current_load() is not None and not project.is_busy()))
        self.assertIs(project.preview_widget(), image)
        self.assertTrue(image.canvas.isVisible())
        self.assertFalse(project.preview.isVisible())
        load = image.current_load()
        self.assertEqual((load.width, load.height), (93, 64))
        self.assertIn("93 × 64 px", image.header.details.text())
        canvas = image.canvas.grab().toImage()
        self.assertEqual(canvas.pixelColor(canvas.width() // 2, canvas.height() // 2).getRgb()[:3], (200, 30, 40))

        # Una carpeta muestra la ficha, y la barra de estado la nombra.
        self.assertTrue(project.reveal_file(mod / "common"))
        _qt.process_events(20)
        self.assertIsNone(project.preview_widget())
        self.assertTrue(project.preview.isVisible())
        self.assertEqual(project.preview.name.text(), "common")
        self.assertEqual(project.preview.form_values["entries"].text(), "1 elemento")
        self.assertEqual(window.status_label.text(), "Seleccionado: common")
        # Un CSV de localización muestra su ficha con el extracto y el botón para abrirlo.
        self.assertTrue(project.reveal_file(mod / "localisation" / "mimod.csv"))
        _qt.process_events(20)
        self.assertTrue(project.preview.excerpt.isVisible())
        self.assertIn("Hola", project.preview.excerpt.toPlainText())
        self.assertTrue(project.preview.csv_button.isVisible())
        self.assertTrue(project.preview.note.isVisible())

        custom = QLabel("visor")
        project.set_preview_widget(custom)
        self.assertIs(project.preview_stack.currentWidget(), custom)
        self.assertIs(project.preview_widget(), custom)
        project.set_preview_widget(None)
        self.assertIs(project.preview_stack.currentWidget(), project.preview)
        self.assertIsNone(project.preview_widget())

        project.filter_edit.setText("*.csv; countries")
        self.assertEqual(project.fs.nameFilters(), ["*.csv", "*countries*"])
        project.filter_edit.clear()

        localisation = window.page("localisation")
        self.assertEqual([localisation.files_list.item(i).text() for i in range(localisation.files_list.count())],
                         ["mimod.csv"])

    def test_paths_persist_and_game_folder_is_rejected_as_mod(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp) / "Victoria 2"
            for name in ("common", "history", "localisation", "map", "events", "interface", "gfx"):
                (game / name).mkdir(parents=True)
            (game / "v2game.exe").write_bytes(b"MZ")
            window = self.make_window()
            project = window.page("project")
            project.set_game_path(game)
            self.assertEqual(project.game_field.badge.level, "ok")
            self.assertIn("v2game.exe", project.game_field.badge.label.text())
            project.set_mod_path(game)
            self.assertEqual(project.mod_field.badge.level, "error")
            _qt.wait_until(lambda: not project.is_busy())
            second = self.make_window(show=False)
            self.assertEqual(second.page("project").game_path(), game)
            self.assertEqual(second.page("project").mod_path(), game)

    def test_reveal_scrolls_to_file_in_large_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp) / "BigMod"
            flags = mod / "gfx" / "flags"
            flags.mkdir(parents=True)
            for n in range(600):
                (flags / f"T{n:03d}.tga").write_bytes(b"")
            window = self.make_window()
            project = window.page("project")
            project.set_mod_path(mod)
            self.assertTrue(_qt.wait_until(lambda: not project.is_busy()))
            target = flags / "T450.tga"
            self.assertTrue(project.reveal_file(target))
            self.assertTrue(_qt.wait_until(lambda: not project.is_busy()))
            _qt.process_events(50)
            current = project.tree.currentIndex()
            self.assertEqual(project.model.file_path(current), target)
            self.assertTrue(project.tree.viewport().rect().intersects(project.tree.visualRect(current)),
                            "el archivo revelado no quedó a la vista")

    def test_reveal_waits_until_the_folder_is_listed_and_sorted(self):
        """El modelo ordena en diferido las filas nuevas de una carpeta; con la máquina cargada lo hacía cuando ya
        había pasado la ventana para volver a centrar el archivo revelado, que quedaba fuera de la vista, y
        ``is_busy()`` no esperaba a que se listara su carpeta. Ahora se ordena en cuanto se termina de listar."""
        with tempfile.TemporaryDirectory() as tmp:
            mod = Path(tmp) / "BigMod"
            notes = mod / "notes"  # la única carpeta que falta listar: se termina con su directoryLoaded
            notes.mkdir(parents=True)
            for n in range(600):
                (notes / f"N{n:03d}.lua").write_bytes(b"")  # sin visor propio: la vista previa no tarda nada
            window = self.make_window()
            project = window.page("project")
            project.set_mod_path(mod)
            self.assertTrue(_qt.wait_until(lambda: not project.is_busy()))
            rows = []
            project.fs.directoryLoaded.connect(  # después del de la página: ve lo que ella dejó hecho
                lambda folder: rows.append(project.tree.currentIndex().row()) if same_folder(Path(folder), notes)
                else None)
            self.assertTrue(project.reveal_file(notes / "N450.lua"))
            self.assertTrue(project.is_busy(), "mientras se lista su carpeta, la página está ocupada")
            self.assertTrue(_qt.wait_until(lambda: not project.is_busy()))
            self.assertEqual(rows, [450], "al terminar de listar su carpeta, el archivo ya está en su sitio")
            _qt.process_events(50)
            current = project.tree.currentIndex()
            self.assertEqual(project.model.file_path(current), notes / "N450.lua")
            self.assertTrue(project.tree.viewport().rect().intersects(project.tree.visualRect(current)))

    def test_folder_evaluation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(evaluate_game(inspect_folder(None))[0], "neutral")
            self.assertEqual(evaluate_mod(inspect_folder(root / "missing"), None)[:2], ("error", "check.missing"))
            self.assertEqual(evaluate_mod(inspect_folder(root), None)[:2], ("warning", "check.mod_empty"))
            (root / "notes.txt").write_text("x")
            self.assertEqual(evaluate_mod(inspect_folder(root), None)[:2], ("warning", "check.mod_unknown"))
            (root / "events").mkdir()
            self.assertEqual(evaluate_mod(inspect_folder(root), None), ("ok", "check.mod_ok_one", {"count": 1}))
            self.assertEqual(evaluate_mod(inspect_folder(root), root)[:2], ("error", "check.mod_is_game"))
            self.assertEqual(evaluate_game(inspect_folder(root))[:2], ("error", "check.game_no_data"))

    def test_corpus_folders(self):
        roots = corpus_roots()
        if not roots:
            self.skipTest("sin corpus disponible")
        for root in roots:
            for candidate in [root, *[p for p in root.iterdir() if p.is_dir()]]:
                report = inspect_folder(candidate)
                if not report.present:
                    continue
                self.assertFalse(report.is_game, candidate)
                self.assertEqual(evaluate_mod(report, None)[0], "ok", candidate)
                if (candidate.parent / f"{candidate.name}.mod").is_file():
                    self.assertIsNotNone(report.descriptor, candidate)
                    self.assertTrue(report.descriptor.name, candidate)

    def test_name_filters(self):
        self.assertEqual(name_filters(""), [])
        self.assertEqual(name_filters("france"), ["*france*"])
        self.assertEqual(name_filters(" *.txt; ger ,a?c "), ["*.txt", "*ger*", "a?c"])
        # Los espacios son parte del nombre (historia de provincias) y los corchetes se buscan tal cual.
        self.assertEqual(name_filters("400 - Dunkirk"), ["*400 - Dunkirk*"])
        self.assertEqual(name_filters("["), ["*[[]*"])
        self.assertEqual(name_filters("a[1]"), ["*a[[]1[]]*"])


class LocalisationPageTests(UiTestCase):
    def test_central_widget_and_open_signal(self):
        window = self.make_window()
        page = window.show_page("localisation")
        self.assertIs(page.stack.currentWidget(), page.empty_card)
        self.assertFalse(page.search_edit.isEnabled())
        editor = QLabel("editor")
        page.set_central_widget(editor)
        self.assertIs(page.stack.currentWidget(), editor)
        self.assertIs(page.central_widget(), editor)
        self.assertTrue(page.search_edit.isEnabled())
        searches = []
        page.search_changed.connect(searches.append)
        page.search_edit.setText("GER")
        self.assertEqual(searches, ["GER"])
        page.set_central_widget(None)
        self.assertIs(page.stack.currentWidget(), page.empty_card)
        opened = []
        page.open_requested.connect(opened.append)
        page.open_file(Path("/tmp/x.csv"))
        self.assertEqual(opened, [Path("/tmp/x.csv")])
        self.assertIn("x.csv", page.file_label.text())
        self.assertIn("x.csv", window.status_label.text())


class ThemeTests(UiTestCase):
    def test_textures_are_generated_and_cached(self):
        for name in ("parchment", "wood", "velvet"):
            image = theme.texture_image(name)
            self.assertFalse(image.isNull())
            self.assertGreaterEqual(min(image.width(), image.height()), 256)
            colors = {image.pixel(x, y) for x in range(0, image.width(), 37) for y in range(0, image.height(), 41)}
            self.assertGreater(len(colors), 20, f"{name} parece uniforme")
            self.assertIs(theme.texture(name), theme.texture(name))

    def test_stylesheet_and_glyphs(self):
        sheet = theme.build_stylesheet()
        self.assertNotIn("$", sheet)
        self.assertEqual(APP.styleSheet(), sheet)
        for path in theme.glyph_dir().glob("*.png"):
            self.assertFalse(QImage(str(path)).isNull(), path)
        self.assertGreater(len(list(theme.glyph_dir().glob("*.png"))), 20)

    def test_every_object_name_rule_has_a_widget(self):
        """REG-4: una regla ``Tipo#nombre`` de style.qss cuyo objectName ya no pone nadie no se aplica a nada."""
        sources = "\n".join(path.read_text(encoding="utf-8") for path in theme.STYLESHEET_PATH.parent.rglob("*.py"))
        names = set(re.findall(r"\w#(\w+)", theme.STYLESHEET_PATH.read_text(encoding="utf-8")))
        self.assertIn("folderChip", names)
        unused = sorted(name for name in names if not re.search(rf"[\"']{name}[\"']", sources))
        self.assertEqual(unused, [], "reglas para objectName que ningún widget usa")

    def test_fonts_resolve_to_serif(self):
        family = theme.resolve_family(theme.DISPLAY_FAMILIES + theme.BODY_FAMILIES)
        if family is None:
            self.skipTest("no hay ninguna serifa de la lista instalada")
        self.assertEqual(theme.font("title").capitalization(), theme.font("title").capitalization().SmallCaps)
        self.assertEqual(QApplication.font().family(), theme.font("body").family())

    def test_bundled_fonts_folder_is_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertEqual(theme.load_bundled_fonts(folder / "missing"), [])
            source = next((p for p in Path("/usr/share/fonts").rglob("LiberationSerif-Regular.ttf")), None) \
                if Path("/usr/share/fonts").is_dir() else None
            if source is None:
                self.skipTest("no hay una .ttf de ejemplo en el sistema")
            shutil.copy(source, folder / source.name)
            (folder / "readme.txt").write_text("no es una fuente")
            self.assertIn("Liberation Serif", theme.load_bundled_fonts(folder))

    def test_every_icon_draws_something(self):
        for name in icon_names():
            image = icon_pixmap(name, 24, theme.color("ink")).toImage()
            opaque = sum(1 for x in range(24) for y in range(24) if image.pixelColor(x, y).alpha() > 0)
            self.assertGreater(opaque, 20, name)


class AppTests(UiTestCase):
    def test_main_runs_event_loop_and_returns(self):
        from vic2studio.app import main

        QTimer.singleShot(150, QApplication.instance().quit)
        self.assertEqual(main([]), 0)
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, MainWindow) and widget not in self.windows:
                self.windows.append(widget)


if __name__ == "__main__":
    unittest.main()
