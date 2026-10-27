"""Hoja de ruta (Proyecto › Inicio) y secciones planificadas: numeración de wizard.md §22 y reparto en filas."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
from PySide6.QtWidgets import QScrollArea  # noqa: E402

APP = _qt.application()

from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.halls import discover_halls  # noqa: E402
from vic2studio.ui.main_window import MainWindow  # noqa: E402
from vic2studio.ui.pages import PlannedSectionPage  # noqa: E402
from vic2studio.ui.pages.planned import CURRENT_ITERATION, ROADMAP_KEYS  # noqa: E402
from vic2studio.ui.widgets import RoadmapStrip  # noqa: E402

# Iteración en que llega cada sección planificada según docs/diseno/wizard.md §22 (iteración 2 en curso).
PLAN = {
    "map:world": 5, "map:regions": 5, "map:climates": 5, "map:straits": 5, "map:forge": 9,
    "nations:countries": 6, "nations:cultures": 4, "nations:governments": 4,
    "war:bookmarks": 4, "war:wars": 6, "war:diplomacy": 6, "war:cb": 4, "war:land": 4, "war:naval": 4,
    "events:events": 7, "events:decisions": 7, "events:modifiers": 7,
    "interface:windows": 8, "interface:sprites": 8, "interface:images": 8,
}
# Lo que ya existe: lo de la iteración 2 y, desde la 3, Validación, Todos los textos y Pendientes de traducir.
READY = {"project:home", "project:descriptor", "project:files", "project:validation", "project:pending",
         "localisation:all", "localisation:pending", "localisation:csv"}


class ColumnsTests(unittest.TestCase):
    def test_all_in_one_row_when_they_fit(self):
        self.assertEqual(RoadmapStrip.columns_for(10, 10 * RoadmapStrip.MIN_COLUMN), 10)
        self.assertEqual(RoadmapStrip.columns_for(10, 1780), 10)

    def test_balanced_rows_when_they_do_not(self):
        self.assertEqual(RoadmapStrip.columns_for(10, 947), 5)    # 1100×700: 5 + 5
        self.assertEqual(RoadmapStrip.columns_for(10, 700), 4)    # 4 + 4 + 2 antes que 5 + 5 apretados
        self.assertEqual(RoadmapStrip.columns_for(10, 300), 2)
        self.assertEqual(RoadmapStrip.columns_for(10, 1), 1)

    def test_degenerate_counts(self):
        self.assertEqual(RoadmapStrip.columns_for(1, 10), 1)
        self.assertEqual(RoadmapStrip.columns_for(0, 500), 1)


class PlanTests(unittest.TestCase):
    def test_plan_has_ten_milestones_and_iteration_3_is_current(self):
        self.assertEqual(len(ROADMAP_KEYS), 10)
        self.assertEqual(CURRENT_ITERATION, 3)

    def test_every_section_is_ready_or_planned_with_its_iteration(self):
        found = {}
        for hall, sections in discover_halls():
            for section in sections:
                found[f"{hall.key}:{section.key}"] = None if section.factory is not None else section.iteration
        self.assertEqual({key for key, n in found.items() if n is None}, READY)
        self.assertEqual({key: n for key, n in found.items() if n is not None}, PLAN)
        self.assertTrue(all(n > CURRENT_ITERATION for n in PLAN.values()), "nada planificado para lo ya hecho")


class RoadmapPageTests(unittest.TestCase):
    def setUp(self):
        _qt.reset_settings()
        set_language("es")
        self.window = MainWindow()

    def tearDown(self):
        self.assertEqual(_qt.dispose(self.window), [])
        set_language("es")
        self.assertEqual(_qt.take_qt_messages(), [])

    def show_home(self, width: int, height: int):
        self.window.resize(width, height)
        self.window.show()
        page = self.window.show_page("home")
        # Tras cambiar de idioma, el alto de los títulos que ahora ocupan más líneas llega en varias pasadas.
        _qt.process_events(50)
        scroll = page.findChild(QScrollArea)
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        _qt.process_events()
        return page

    def test_planned_sections_announce_the_iteration_of_the_plan(self):
        for language in ("es", "en"):
            set_language(language)
            for key, iteration in PLAN.items():
                with self.subTest(language=language, section=key):
                    page = self.window.page(key)
                    self.assertIsInstance(page, PlannedSectionPage)
                    self.assertEqual(page.iteration, iteration)
                    self.assertIn(str(iteration), page.ribbon.text())
                    self.assertIn(str(iteration), page.arrival.text())
                    self.assertIn(page.hall_spec.key, key)
                    self.assertIn(tr(page.hall_spec.title_key), page.header.subtitle.text())

    def test_home_roadmap_marks_done_current_and_planned(self):
        roadmap = self.window.page("home").roadmap
        for language, done, current in (("es", "hecha", "en curso"), ("en", "done", "in progress")):
            set_language(language)
            with self.subTest(language=language):
                titles = [label.text() for label in roadmap.strip.titles]
                self.assertEqual(len(titles), 10)
                self.assertTrue(all(titles), titles)
                self.assertFalse([t for t in titles if t.startswith("roadmap.")], titles)
                states = [label.text() for label in roadmap.strip.states]
                self.assertIn(done, states[0])
                self.assertIn(current, states[CURRENT_ITERATION - 1])
                for n, state in enumerate(states[CURRENT_ITERATION:], start=CURRENT_ITERATION + 1):
                    self.assertIn(str(n), state)
                    self.assertNotIn(done, state)
                    self.assertNotIn(current, state)

    def test_the_read_only_csv_viewer_points_to_the_editable_table(self):
        """La edición llegó en la iteración 3 (Textos › Todos los textos): el visor de CSV ya no la promete."""
        for language in ("es", "en"):
            set_language(language)
            with self.subTest(language=language):
                for key in ("loc.read_only", "loc.read_only_tooltip", "localisation.roadmap"):
                    self.assertIn(tr("section.localisation.all"), tr(key))
                    self.assertNotIn("3", tr(key))

    def test_strip_wraps_at_the_minimum_size_and_not_at_full_hd(self):
        for (width, height), per_row in (((1100, 700), 5), ((1920, 1080), 10)):
            for language in ("es", "en"):
                set_language(language)
                with self.subTest(size=(width, height), language=language):
                    strip = self.show_home(width, height).roadmap.strip
                    self.assertEqual(strip.per_row, per_row)
                    rows = strip.rows()
                    self.assertEqual([len(row) for row in rows], [per_row] * (10 // per_row))
                    tops = [row[0].mapTo(strip, row[0].rect().topLeft()).y() for row in rows]
                    self.assertEqual(tops, sorted(set(tops)), "cada fila va debajo de la anterior")
                    for title in strip.titles:
                        # Ningún título se corta: cabe entero a su ancho.
                        self.assertLessEqual(title.heightForWidth(title.width()), title.height(), title.text())


if __name__ == "__main__":
    unittest.main()
