"""Hoja de ruta de los módulos planificados: numeración de wizard.md §22 y reparto en filas (offscreen)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
from PySide6.QtWidgets import QScrollArea  # noqa: E402

APP = _qt.application()

from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.main_window import MainWindow  # noqa: E402
from vic2studio.ui.pages import PAGE_KEYS  # noqa: E402
from vic2studio.ui.pages.planned import ROADMAP_KEYS  # noqa: E402
from vic2studio.ui.widgets import RoadmapStrip  # noqa: E402

# Iteración en la que llega cada módulo según docs/diseno/wizard.md §22.
PLAN = {"map": 5, "countries": 6, "events": 7}


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


class RoadmapPageTests(unittest.TestCase):
    def setUp(self):
        _qt.reset_settings()
        set_language("es")
        self.window = MainWindow()

    def tearDown(self):
        self.assertEqual(_qt.dispose(self.window), [])
        set_language("es")
        self.assertEqual(_qt.take_qt_messages(), [])

    def show(self, key: str, width: int, height: int):
        self.window.resize(width, height)
        self.window.show()
        self.window.set_current_page(PAGE_KEYS.index(key))
        _qt.process_events()
        page = self.window.page(key)
        scroll = page.findChild(QScrollArea)
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        _qt.process_events()
        return page

    def test_plan_has_ten_milestones(self):
        self.assertEqual(len(ROADMAP_KEYS), 10)

    def test_pages_announce_the_iteration_of_the_plan(self):
        for language, module in (("es", "este módulo"), ("en", "this module")):
            set_language(language)
            for key, iteration in PLAN.items():
                with self.subTest(language=language, page=key):
                    page = self.window.page(key)
                    self.assertEqual(page.iteration, iteration)
                    self.assertIn(str(iteration), page.ribbon.text())
                    self.assertIn(str(iteration), page.arrival.text())
                    titles = [label.text() for label in page.roadmap.titles]
                    self.assertEqual(len(titles), 10)
                    self.assertTrue(all(titles), titles)
                    self.assertFalse([t for t in titles if t.startswith("roadmap.")], titles)
                    self.assertIn(module, page.roadmap.states[iteration - 1].text())

    def test_localisation_promises_editing_in_iteration_3(self):
        for language in ("es", "en"):
            set_language(language)
            self.assertIn("3", tr("loc.read_only"))
            self.assertIn("3", tr("localisation.roadmap"))

    def test_strip_wraps_at_the_minimum_size_and_not_at_full_hd(self):
        for (width, height), per_row in (((1100, 700), 5), ((1920, 1080), 10)):
            for language in ("es", "en"):
                set_language(language)
                with self.subTest(size=(width, height), language=language):
                    strip = self.show("map", width, height).roadmap
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
