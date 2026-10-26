"""Página de Localización y editor CSV (offscreen): relectura, errores, carga, lista del mod, búsqueda y lint.

Todo se hace sobre CSV sintéticos creados por código en una carpeta temporal
(``<tmp>/LocMod/localisation``). Fallan ante cualquier aviso de Qt.
"""

import errno
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QAbstractItemModelTester  # noqa: E402

APP = _qt.application()

from vic2studio.core.cancel import Cancelled  # noqa: E402
from vic2studio.core.csvloc import END_MARKER_COLUMN, LANGUAGE_CODES, read_csv_file  # noqa: E402
from vic2studio.i18n import set_language, tr, translator  # noqa: E402
from vic2studio.ui.main_window import MainWindow  # noqa: E402
from vic2studio.ui.pages import PAGE_KEYS  # noqa: E402
from vic2studio.ui.tasks import wait_for_tasks  # noqa: E402
from vic2studio.ui.viewers import localisation_editor  # noqa: E402
from vic2studio.ui.viewers.common import describe_os_error  # noqa: E402
from vic2studio.ui.viewers.localisation_editor import COLUMNS, KEY, LANG, MARKER, load_localisation  # noqa: E402

TIMEOUT_MS = 15000
LOCALISATION = PAGE_KEYS.index("localisation")


def row(key: str, english: str = "", spanish: str = "", marker: bool = True) -> str:
    """Una entrada con sus 13 idiomas (English y Español rellenos) y, si se pide, la «x» de la columna 14."""
    fields = [key, english, "", "", "", spanish] + [""] * 8
    return ";".join(fields + (["x"] if marker else []))


def write_csv(path: Path, *rows: str) -> Path:
    path.write_bytes("".join(f"{line}\r\n" for line in rows).encode("cp1252"))
    return path


def rewrite_csv(path: Path, *rows: str) -> None:
    """Cambia el archivo y adelanta su fecha (aunque el sistema de archivos tenga poca resolución)."""
    before = path.stat()
    write_csv(path, *rows)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))


def python_calls(function) -> int:
    """Llamadas a funciones de Python (también las que hace Qt desde C++) mientras se ejecuta ``function``."""
    calls = 0

    def profile(frame, event, arg):
        nonlocal calls
        if event == "call":
            calls += 1

    sys.setprofile(profile)
    try:
        function()
    finally:
        sys.setprofile(None)
    return calls


class LocalisationCase(unittest.TestCase):
    def setUp(self):
        _qt.reset_settings()
        set_language("es")
        _qt.take_qt_messages()
        self.missing_before = translator().missing_keys()
        self._tmp = tempfile.TemporaryDirectory()
        self.mod = Path(self._tmp.name) / "LocMod"
        self.folder = self.mod / "localisation"
        self.folder.mkdir(parents=True)
        self.windows = []
        self.window = self.make_window()
        self.page = self.window.page("localisation")
        self.editor = self.page.editor

    def tearDown(self):
        for window in self.windows:
            window.close()
        self.assertTrue(wait_for_tasks(10000), "quedaron tareas en segundo plano")
        _qt.process_events()
        self.assertEqual(_qt.dispose(*self.windows), [], "ventanas de la prueba que siguen vivas")
        self.assertEqual(_qt.live_main_windows(), [], "quedó viva otra ventana principal")
        _qt.process_events()
        set_language("es")
        self._tmp.cleanup()
        self.assertEqual(_qt.take_qt_messages(), [], "avisos de Qt durante la prueba")
        self.assertEqual(sorted(translator().missing_keys() - self.missing_before), [],
                         "claves pedidas en tiempo de ejecución que no existen")

    def make_window(self) -> MainWindow:
        window = MainWindow()
        window.resize(1440, 900)
        window.show()
        _qt.process_events(30)
        self.windows.append(window)
        return window

    def wait(self, predicate, message: str, timeout: int = TIMEOUT_MS) -> None:
        self.assertTrue(_qt.wait_until(predicate, timeout), message)

    def open(self, path: Path, line: int | None = None, window: MainWindow | None = None) -> None:
        """Abre ``path`` como lo hace «Proyecto y Archivos» y espera a que termine de leerse."""
        window = window or self.window
        page = window.page("localisation")
        window.open_in_localisation(path, line=line)
        self.wait(lambda: not page.is_busy(), f"{path.name} no terminó de leerse")
        _qt.process_events(20)

    def cell(self, row_number: int, column: int):
        return self.editor.proxy.index(row_number, column).data()


class ReopenTests(LocalisationCase):
    """LOC-1: abrir un CSV ya abierto relee el disco si cambió."""

    def test_reopening_rereads_a_file_changed_on_disk(self):
        path = write_csv(self.folder / "00_a.csv", row("KEY_A", "Hello", "Hola", marker=False))
        self.open(path)
        self.assertEqual(self.cell(0, 2), "Hola")
        self.assertEqual(len(self.editor.diagnostics_model.all_rows()), 1)
        # Sin cambios se reutiliza la lectura (no se lanza otra).
        self.page.open_file(path)
        self.assertFalse(self.page.is_busy())
        rewrite_csv(path, row("KEY_A", "Hello", "Hola corregido"))
        self.open(path)
        self.assertEqual(self.cell(0, 2), "Hola corregido")
        self.assertEqual(self.editor.diagnostics_model.all_rows(), [])
        self.assertEqual(self.editor.diagnostics_title.text(),
                         tr("loc.diagnostics_title", count=0, errors=0, warnings=0, infos=0))

    def test_validation_line_opens_the_current_version(self):
        path = write_csv(self.folder / "00_a.csv", row("KEY_A", "Hello", "Hola"))
        self.open(path)
        rewrite_csv(path, row("KEY_A", "Hello", "Hola"), row("KEY_B", "Bye", "Adiós"), "KEY_C;Bye;x")
        # Lo que hace un doble clic en un diagnóstico de la línea 3 del informe de «Validar mod».
        self.open(path, line=3)
        self.assertEqual(self.editor.total_rows(), 3)
        self.assertEqual(self.editor.selected_line(), 3)
        self.assertIn(3, [r.line for r in self.editor.diagnostics_model.all_rows()])

    def test_returning_to_the_page_rereads_the_open_file(self):
        path = write_csv(self.folder / "00_a.csv", row("KEY_A", "Hello", "Hola"), row("KEY_B", "Bye", "Adiós"))
        self.open(path, line=2)
        self.window.set_current_page(0)
        rewrite_csv(path, row("KEY_A", "Hello", "Hola"), row("KEY_B", "Bye", "Hasta luego"))
        self.window.set_current_page(LOCALISATION)
        self.wait(lambda: not self.page.is_busy() and self.cell(1, 2) == "Hasta luego", "no releyó el archivo")
        self.assertEqual(self.editor.selected_line(), 2, "la relectura conserva la fila seleccionada")

    def test_reopening_a_deleted_file_reports_it(self):
        path = write_csv(self.folder / "00_a.csv", row("KEY_A", "Hello", "Hola"))
        self.open(path)
        path.unlink()
        self.open(path)
        self.assertTrue(self.page.error_badge.isVisible())
        self.assertEqual(self.page.error_badge.label.text(),
                         tr("status.csv_failed", name=path.name, error=tr("file_error.not_found")))


class OpenErrorTests(LocalisationCase):
    """LOC-2: el motivo de un fallo al abrir se traduce y queda en la página hasta el siguiente intento."""

    def test_missing_file_error_is_translated_and_stays_on_the_page(self):
        missing = self.folder / "no_existe.csv"
        self.window.set_current_page(LOCALISATION)
        self.page.open_file(missing)
        self.wait(lambda: not self.page.is_busy(), "la lectura no terminó")
        badge = self.page.error_badge
        expected = tr("status.csv_failed", name="no_existe.csv", error=tr("file_error.not_found"))
        self.assertTrue(badge.isVisible())
        self.assertEqual(badge.label.text(), expected)
        self.assertEqual(self.window.status_label.text(), expected)
        self.assertNotIn(os.strerror(errno.ENOENT), expected)
        self.assertIn(os.strerror(errno.ENOENT), badge.toolTip(), "el detalle del sistema queda en la ayuda")
        self.assertIs(self.page.stack.currentWidget(), self.page.empty_card)
        # Cambiar de página sobrescribe la barra de estado, pero no el aviso de la página.
        self.window.set_current_page(0)
        self.window.set_current_page(LOCALISATION)
        self.assertTrue(badge.isVisible())
        set_language("en")
        self.assertEqual(badge.label.text(), tr("status.csv_failed", name="no_existe.csv",
                                                error=tr("file_error.not_found")))
        self.assertIn("does not exist", badge.label.text())
        # El siguiente intento lo retira.
        self.open(write_csv(self.folder / "00_a.csv", row("KEY_A", "Hello", "Hola")))
        self.assertFalse(badge.isVisible())

    def test_failed_open_keeps_the_previous_file(self):
        path = write_csv(self.folder / "00_a.csv", row("KEY_A", "Hello", "Hola"))
        self.open(path)
        folder = self.folder / "carpeta.csv"
        folder.mkdir()
        self.page.open_file(folder)
        self.wait(lambda: not self.page.is_busy(), "la lectura no terminó")
        self.assertEqual(self.page.error_badge.label.text(),
                         tr("status.csv_failed", name="carpeta.csv", error=tr("file_error.not_file")))
        self.assertIs(self.page.stack.currentWidget(), self.editor)
        self.assertEqual(self.page.current_file(), path)
        self.assertEqual(self.page.file_label.text(), tr("localisation.current_file", name=path.name))

    def test_os_errors_are_described_by_kind(self):
        for error, key in ((PermissionError(errno.EACCES, os.strerror(errno.EACCES)), "file_error.permission"),
                           (FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT)), "file_error.not_found"),
                           (IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR)), "file_error.not_file")):
            self.assertEqual(describe_os_error(error), (tr(key), error.strerror))
        self.assertEqual(describe_os_error(OSError(errno.EIO, "I/O error")),
                         (tr("file_error.generic", detail="I/O error"), "I/O error"))
        # Vive en viewers.common (también lo usa el visor Clausewitz); el nombre de antes sigue sirviendo.
        self.assertIs(localisation_editor.describe_os_error, describe_os_error)


class LoadingStateTests(LocalisationCase):
    """LOC-8: mientras se lee otro CSV, la página sigue nombrando el que se ve."""

    def test_label_names_the_visible_file_while_another_loads(self):
        first = write_csv(self.folder / "00_a.csv", row("KEY_A", "Hello", "Hola"))
        second = write_csv(self.folder / "00_b.csv", row("KEY_B", "Bye", "Adiós"))
        self.page.set_mod_path(self.mod)
        self.open(first)
        self.page.open_file(second)  # sin procesar eventos: la lectura sigue en curso
        self.assertTrue(self.page.is_busy())
        self.assertEqual(self.page.current_file(), first)
        label = self.page.file_label.text()
        self.assertIn(tr("status.csv_loading", name=second.name), label)
        self.assertIn(tr("localisation.current_file", name=first.name), label)
        self.assertTrue(self.page.loading_bar_action.isVisible())
        self.page.mod_files_menu.aboutToShow.emit()
        self.assertEqual([a.text() for a in self.page.mod_files_menu.actions() if a.isChecked()], [first.name])
        self.wait(lambda: not self.page.is_busy(), "la lectura no terminó")
        self.assertEqual(self.page.current_file(), second)
        self.assertEqual(self.page.file_label.text(), tr("localisation.current_file", name=second.name))
        self.assertFalse(self.page.loading_bar_action.isVisible())

    def test_closing_during_a_load_clears_the_loading_state(self):
        first = write_csv(self.folder / "00_a.csv", row("KEY_A", "Hello", "Hola"))
        second = write_csv(self.folder / "00_b.csv", row("KEY_B", "Bye", "Adiós"))
        self.open(first)
        self.page.open_file(second)
        self.page.close_file()
        self.assertEqual(self.window.status_label.text(), tr("status.csv_closed", name=first.name))
        self.assertEqual(self.page.file_label.text(), tr("localisation.no_file"))
        self.assertFalse(self.page.loading_bar_action.isVisible())
        self.assertTrue(wait_for_tasks(10000))
        _qt.process_events(50)
        self.assertIsNone(self.editor.current_load(), "la lectura cancelada no vuelve a abrir el archivo")
        self.assertIs(self.page.stack.currentWidget(), self.page.empty_card)

    def test_opening_from_another_page_shows_the_loading_message(self):
        path = write_csv(self.folder / "00_a.csv", row("KEY_A", "Hello", "Hola"))
        self.window.set_current_page(0)
        self.window.open_in_localisation(path)
        self.assertEqual(self.window.current_page_index(), LOCALISATION)
        self.assertEqual(self.window.status_label.text(), tr("status.csv_loading", name=path.name))
        self.wait(lambda: not self.page.is_busy(), "la lectura no terminó")


class ModFilesTests(LocalisationCase):
    """LOC-9 y LOC-M2: la lista y el menú «CSV del mod» reflejan la carpeta, también los «.CSV»."""

    def names(self) -> list[str]:
        return [self.page.files_list.item(i).text() for i in range(self.page.files_list.count())]

    def test_menu_and_list_follow_the_folder(self):
        write_csv(self.folder / "a.csv", row("KEY_A"))
        self.page.set_mod_path(self.mod)
        self.assertEqual(self.names(), ["a.csv"])
        (self.folder / "a.csv").unlink()
        write_csv(self.folder / "b.csv", row("KEY_B"))
        write_csv(self.folder / "00_UPPER.CSV", row("KEY_C"))
        (self.folder / "notes.txt").write_text("no es un CSV", encoding="cp1252")
        self.page.mod_files_menu.aboutToShow.emit()
        self.assertEqual([a.text() for a in self.page.mod_files_menu.actions()], ["00_UPPER.CSV", "b.csv"])
        self.assertEqual(self.names(), ["00_UPPER.CSV", "b.csv"])
        self.assertEqual(self.page.files_group.title(), tr("localisation.mod_files", count=2))
        # Al volver a la página también se relee la carpeta.
        write_csv(self.folder / "c.csv", row("KEY_D"))
        self.window.set_current_page(0)
        self.window.set_current_page(LOCALISATION)
        self.assertEqual(self.names(), ["00_UPPER.CSV", "b.csv", "c.csv"])
        self.open(self.folder / "00_UPPER.CSV")
        self.assertEqual(self.cell(0, 0), "KEY_C")


class SearchAndLintTests(LocalisationCase):
    """LOC-7 y LOC-M1: la búsqueda pendiente no oculta la fila elegida; el lint sigue a la fila actual."""

    def test_select_line_applies_the_pending_search_first(self):
        path = write_csv(self.folder / "00_a.csv", *(row(f"KEY_{i:03}", f"Text {i}") for i in range(20)))
        self.open(path)
        self.page.search_edit.setText("KEY_003")  # se filtraría 150 ms después
        self.assertTrue(self.editor.select_line(16))
        _qt.process_events(400)
        self.assertEqual(self.editor.selected_line(), 16)
        self.assertEqual(self.page.search_edit.text(), "", "la fila no coincide: se vacía el buscador")
        self.assertEqual(self.editor.visible_rows(), 20)
        # Si la fila coincide, la búsqueda se conserva.
        self.page.search_edit.setText("KEY_01")
        self.assertTrue(self.editor.select_line(13))
        _qt.process_events(400)
        self.assertEqual((self.editor.selected_line(), self.editor.visible_rows()), (13, 10))
        self.assertEqual(self.page.search_edit.text(), "KEY_01")

    def test_lint_selection_follows_rows_back_and_forth(self):
        path = write_csv(self.folder / "00_a.csv", row("KEY_A", "Hello", "Hola"), "KEY_B;Bye", row("KEY_C", "a", "b"))
        self.open(path)

        def selected_diagnostics() -> list[int]:
            view = self.editor.diagnostics_view
            return [self.editor.diagnostics_model.row_at(i).line for i in view.selectionModel().selectedRows()]

        for line, expected in ((2, [2]), (1, []), (2, [2]), (3, []), (2, [2])):
            self.assertTrue(self.editor.select_line(line))
            self.assertEqual(selected_diagnostics(), expected, f"línea {line}")

    def test_filtering_keeps_the_selected_row(self):
        path = write_csv(self.folder / "00_a.csv", *(row(f"KEY_{i:03}", f"Text {i}") for i in range(30)))
        self.open(path, line=12)
        self.editor.set_query("key_01")
        self.assertEqual(self.editor.selected_line(), 12)
        self.editor.set_query("")
        self.assertEqual(self.editor.selected_line(), 12)
        self.editor.set_query("key_02")
        self.assertIsNone(self.editor.selected_line(), "la fila filtrada deja de estar seleccionada")


class EditorTextTests(LocalisationCase):
    """LOC-4, LOC-5, LOC-14, LOC-M3 y R3: textos coherentes con el lint, la validación del mod y la codificación."""

    def header_tooltip(self, kind: str, column: int | None = None) -> str:
        section = next(i for i, (k, c) in enumerate(COLUMNS) if k == kind and column in (None, c))
        return self.editor.proxy.headerData(section, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)

    def test_header_tooltips_use_the_lint_column_numbers(self):
        path = write_csv(self.folder / "00_a.csv", row("KEY_A", "Hello", "Hola", marker=False))
        self.open(path)
        for lang, word in (("es", "columna"), ("en", "column")):
            set_language(lang)
            message = read_csv_file(path).diagnostics[0].message(lang)
            in_lint = re.search(rf"{word} (\d+)", message).group(1)
            self.assertEqual(in_lint, str(END_MARKER_COLUMN))
            numbers = [re.search(r"\d+", self.header_tooltip(*spec)).group() for spec in
                       ((MARKER,), (KEY,), (LANG, LANGUAGE_CODES["es"]))]
            self.assertEqual(numbers, [in_lint, "0", str(LANGUAGE_CODES["es"])])

    def test_severity_combo_fits_its_texts_after_a_language_switch(self):
        path = write_csv(self.folder / "00_a.csv", row("KEY_A", "Hello", "Hola"))
        self.window.close()
        set_language("en")
        english = self.make_window()
        self.open(path, window=english)
        set_language("es")
        spanish = self.make_window()
        self.open(path, window=spanish)
        combos = [w.page("localisation").editor.severity_combo for w in (english, spanish)]
        self.assertEqual(combos[0].currentText(), combos[1].currentText())
        self.assertEqual(combos[0].sizeHint(), combos[1].sizeHint())
        self.assertGreaterEqual(combos[0].width(), combos[0].sizeHint().width())

    def test_texts_agree_with_the_read_only_editor(self):
        path = write_csv(self.folder / "00_a.csv", "key;English;French;German;;Spanish;;;;;;;;;x",
                         row("KEY_A", "Hello", "Hola"), "KEY_B;Bye")
        self.open(path)
        counts = {s: sum(1 for r in self.editor.diagnostics_model.all_rows() if r.severity == s)
                  for s in ("error", "warning", "info")}
        self.assertEqual(counts["info"], 1)
        for lang, verb in (("es", "editar"), ("en", "edit")):
            set_language(lang)
            self.assertNotIn(verb, tr("localisation.empty_text").casefold(), "el editor aún es de solo lectura")
            self.assertIn(tr("severity.info").casefold(), tr("loc.diag_filter.infos").casefold())
            self.assertEqual(self.editor.diagnostics_title.text(),
                             tr("loc.diagnostics_title", count=sum(counts.values()), errors=counts["error"],
                                warnings=counts["warning"], infos=counts["info"]))

    def test_notes_have_the_same_name_in_the_lint_and_the_validation(self):
        def label(text: str, value: int) -> str:
            return re.search(rf"(\w+): {value}\b", text).group(1)

        for lang in ("es", "en"):
            set_language(lang)
            self.assertEqual(tr("validation.filter.infos"), tr("loc.diag_filter.infos"))
            title = tr("loc.diagnostics_title", count=9, errors=2, warnings=3, infos=4)
            summary = tr("validation.summary", files=5, seconds="6", errors=2, warnings=3, infos=4)
            self.assertEqual(label(summary, 4), label(title, 4), summary)

    def test_utf16_file_shows_a_whole_file_error(self):
        path = self.folder / "00_unicode.csv"
        path.write_bytes(f"{row('KEY_A', 'Hello', 'Hola España')}\r\n".encode("utf-16"))
        self.open(path)
        self.assertEqual((self.cell(0, 0), self.cell(0, 2)), ("KEY_A", "Hola España"))
        notice = self.editor.file_notice
        self.assertTrue(notice.isVisible())
        self.assertEqual(notice.level, "error")
        self.assertIn("utf-16", notice.label.text().casefold())
        # Un CSV correcto lo retira.
        self.open(write_csv(self.folder / "00_a.csv", row("KEY_A", "Hello", "Hola")))
        self.assertFalse(notice.isVisible())


class LoadCostTests(LocalisationCase):
    """LOC-13: la lectura se cancela y poner un archivo en pantalla no ejecuta Python por cada fila."""

    def test_load_can_be_cancelled(self):
        path = write_csv(self.folder / "00_a.csv", row("KEY_A", "Hello", "Hola"))
        with self.assertRaises(Cancelled):
            load_localisation(path, lambda: True)

    def test_showing_and_filtering_run_no_python_per_row(self):
        small = load_localisation(write_csv(self.folder / "small.csv", *(row(f"KEY_{i}", "a") for i in range(50))))
        large = load_localisation(write_csv(self.folder / "large.csv", *(row(f"KEY_{i}", "a") for i in range(5000))))
        self.window.set_current_page(LOCALISATION)
        self.page.set_central_widget(self.editor)
        _qt.process_events(20)
        costs = []
        for load in (small, large):
            costs.append((python_calls(lambda: self.editor.set_load(load)),
                          python_calls(lambda: self.editor.set_query("key_1")),
                          python_calls(lambda: self.editor.set_query(""))))
            _qt.process_events(20)
        for operation, (cost_small, cost_large) in zip(("set_load", "filtrar", "quitar el filtro"), zip(*costs)):
            self.assertLess(cost_large, cost_small + 100, f"{operation}: {cost_small} llamadas con 50 filas, "
                                                         f"{cost_large} con 5000")

    def test_filter_proxy_passes_the_model_tester(self):
        path = write_csv(self.folder / "00_a.csv", "# comentario", row("KEY_A", "Hello", "Hola"), "",
                         row("KEY_B", "Bye", "Adiós"), "KEY_C;Bye")
        tester = QAbstractItemModelTester(self.editor.proxy, QAbstractItemModelTester.FailureReportingMode.Warning)
        self.open(path, line=4)
        self.assertEqual(self.editor.visible_rows(), 3)
        self.editor.comments_check.setChecked(True)
        self.assertEqual(self.editor.visible_rows(), 5)
        self.assertEqual(self.editor.proxy.headerData(1, Qt.Orientation.Vertical), "2")
        self.editor.set_query("bye")
        self.assertEqual([self.cell(i, 0) for i in range(self.editor.visible_rows())], ["KEY_B", "KEY_C"])
        self.assertEqual(self.editor.selected_line(), 4)
        self.editor.set_query("nada")
        self.assertEqual(self.editor.visible_rows(), 0)
        self.assertEqual(self.editor.proxy.headerData(0, Qt.Orientation.Horizontal), tr("loc.col.key"))
        set_language("en")
        self.editor.set_query("")
        self.page.close_file()
        self.assertEqual(self.editor.visible_rows(), 0)
        del tester


if __name__ == "__main__":
    unittest.main()
