"""Recuentos con 1 en singular, con textos literales (R2-PLURAL-*, segunda revisión de la última ronda de T4).

Las pruebas de NF-SINGULAR-LINE comparaban con la misma clave que usa el código; aquí se compara con el texto
que ve el usuario: «1 carpeta», «1 entrada», «1 fila», «1 archivo», «se muestra 1», «1 byte».
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)

APP = _qt.application()

from vic2studio.core.vfs.guard import evaluate_mod, inspect_folder  # noqa: E402
from vic2studio.i18n import set_language, tr  # noqa: E402
from vic2studio.ui.main_window import MainWindow  # noqa: E402
from vic2studio.ui.pages.project_page import FilePreview, gather_facts  # noqa: E402
from vic2studio.ui.tasks import wait_for_tasks  # noqa: E402
from vic2studio.ui.viewers.validation_panel import SEVERITY_FILTERS, ValidationPanel  # noqa: E402

TIMEOUT_MS = 20000


class CountCase(unittest.TestCase):
    def setUp(self):
        _qt.reset_settings()
        set_language("es")
        _qt.take_qt_messages()
        # Las limpiezas van en orden inverso: esta, la primera registrada, es la última (tras destruir los widgets).
        self.addCleanup(lambda: self.assertEqual(_qt.live_main_windows(), [], "quedó una ventana viva"))
        self.folder = Path(tempfile.mkdtemp(prefix="vic2studio-counts-"))
        self.addCleanup(shutil.rmtree, self.folder, True)

    def tearDown(self):
        self.assertTrue(wait_for_tasks(10000), "quedaron tareas en segundo plano")
        _qt.process_events()
        set_language("es")
        self.assertEqual(_qt.take_qt_messages(), [], "avisos de Qt durante la prueba")

    def widget(self, widget, width: int = 900, height: int = 600):
        widget.setMinimumSize(200, 200)
        widget.resize(width, height)
        widget.show()
        self.addCleanup(lambda: _qt.dispose(widget))
        _qt.process_events(20)
        return widget

    def wait(self, predicate, message: str) -> None:
        self.assertTrue(_qt.wait_until(predicate, TIMEOUT_MS), message)


class CountTests(CountCase):
    def test_a_mod_with_one_recognised_folder(self):
        """«Mod válido: 1 carpetas reconocidas» (un mod solo de traducción es normal)."""
        mod = self.folder / "Traduccion"
        (mod / "localisation").mkdir(parents=True)
        level, key, fmt = evaluate_mod(inspect_folder(mod), None)
        for lang, text in (("es", "Mod válido: 1 carpeta reconocida"), ("en", "Valid mod: 1 recognised folder")):
            set_language(lang)
            self.assertEqual((level, tr(key, **fmt)), ("ok", text), lang)
        (mod / "common").mkdir()
        level, key, fmt = evaluate_mod(inspect_folder(mod), None)
        set_language("es")
        self.assertEqual(tr(key, **fmt), "Mod válido: 2 carpetas reconocidas")

    def test_a_csv_with_one_entry(self):
        """«1 entradas leídas» en la barra de estado y «1 de 1 filas» en el editor."""
        path = self.folder / "00_uno.csv"
        path.write_bytes("KEY_A;Hello;;;;Hola;;;;;;;;;x\r\n".encode("cp1252"))
        window = self.widget(MainWindow(), 1440, 900)
        page = window.page("localisation")
        window.open_in_localisation(path)
        self.wait(lambda: not page.is_busy(), "el CSV no terminó de leerse")
        _qt.process_events(20)
        for lang, status, rows in (("es", "00_uno.csv: 1 entrada leída en ", "1 de 1 fila"),
                                   ("en", "00_uno.csv: 1 entry read in ", "1 of 1 row")):
            set_language(lang)
            _qt.process_events(20)
            self.assertTrue(window.status_label.text().startswith(status), (lang, window.status_label.text()))
            self.assertEqual(page.editor.count_label.text(), rows, lang)

    def test_validation_progress_and_filtered_summary_with_one(self):
        """«0 de 1 archivos» en la barra de progreso y «(se muestran 1)» en el resumen filtrado."""
        panel = self.widget(ValidationPanel())
        panel._on_progress((0, 1, "events/a.txt"))
        for lang, text in (("es", "0 de 1 archivo"), ("en", "0 of 1 file")):
            set_language(lang)
            panel.retranslate()
            self.assertTrue(panel.progress_bar.format().endswith(text), (lang, panel.progress_bar.format()))
        set_language("es")
        mod = self.folder / "Mod"
        (mod / "decisions").mkdir(parents=True)
        (mod / "decisions" / "roto.txt").write_bytes(b"political_decisions = {\r\n")  # un error
        (mod / "events").mkdir()
        (mod / "events" / "utf8.txt").write_bytes("a = \"León\"\n".encode("utf-8"))  # un aviso
        panel.start(mod)
        self.wait(lambda: panel.report() is not None and not panel.is_busy(), "la validación no terminó")
        errors_only = next(i for i, (key, _, _) in enumerate(SEVERITY_FILTERS) if key == "error")
        panel.severity_combo.setCurrentIndex(errors_only)
        panel._apply_filter()
        self.assertEqual(len(panel.model.visible_rows()), 1)
        for lang, text in (("es", "(se muestra 1)"), ("en", "(1 shown)")):
            set_language(lang)
            panel.retranslate()
            self.assertIn(text, panel.summary.text(), lang)

    def test_a_one_byte_file_in_the_file_card(self):
        """La ficha decía «1 bytes (1 bytes)»: ahora «1 byte», sin repetir el tamaño en bytes."""
        path = self.folder / "uno.txt"
        path.write_bytes(b"a")
        preview = self.widget(FilePreview())
        preview.show_facts(gather_facts(path, self.folder))
        for lang in ("es", "en"):
            set_language(lang)
            preview.retranslate()
            self.assertEqual(preview.form_values["size"].text(), "1 byte", lang)
        big = self.folder / "grande.txt"
        big.write_bytes(b"a" * 2048)
        preview.show_facts(gather_facts(big, self.folder))
        set_language("es")
        preview.retranslate()
        self.assertIn("(2048 bytes)", preview.form_values["size"].text().replace(" ", "").replace(".", ""))


if __name__ == "__main__":
    unittest.main()
