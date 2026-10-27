"""Aviso al arrancar con una combinación de Python y PySide6 que aborta (PySide6 6.12 en Python 3.10/3.11)."""

import contextlib
import io
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)

APP = _qt.application()

from vic2studio import app as app_module  # noqa: E402
from vic2studio import compat  # noqa: E402
from vic2studio.i18n import set_language  # noqa: E402


class CombinationTests(unittest.TestCase):
    def test_known_combinations(self):
        cases = [
            ((3, 10, 20), (6, 12, 0), True),
            ((3, 11, 9), (6, 12, 1), True),
            ((3, 10, 20), (6, 13, 0), True),
            ((3, 10, 20), (6, 11, 3), False),
            ((3, 11, 9), (6, 5, 3), False),
            ((3, 12, 0), (6, 12, 0), False),
            ((3, 13, 17), (6, 12, 0), False),
            ((3, 14, 0), (7, 0, 0), False),
        ]
        for python, pyside, broken in cases:
            with self.subTest(python=python, pyside=pyside):
                self.assertIs(compat.is_broken_combination(python, pyside), broken)

    def test_installed_combination_reports_versions_as_text(self):
        with mock.patch.object(compat, "pyside_version", return_value=(6, 12, 0)), \
                mock.patch.object(compat.sys, "version_info", (3, 10, 20, "final", 0)), \
                mock.patch.dict(os.environ, {compat.OVERRIDE_ENV: ""}):
            self.assertEqual(compat.broken_qt_binding(), ("3.10.20", "6.12.0"))

    def test_override_skips_the_check(self):
        with mock.patch.object(compat, "pyside_version", return_value=(6, 12, 0)), \
                mock.patch.object(compat.sys, "version_info", (3, 10, 20, "final", 0)):
            for value, skipped in (("1", True), ("yes", True), ("0", False), ("", False)):
                with self.subTest(value=value), mock.patch.dict(os.environ, {compat.OVERRIDE_ENV: value}):
                    self.assertIs(compat.broken_qt_binding() is None, skipped)

    def test_running_combination_is_not_refused(self):
        # Si esta batería llegó hasta aquí, la combinación en uso no está rota.
        self.assertFalse(compat.is_broken_combination(sys.version_info[:3], compat.pyside_version()))

    def test_message_names_both_versions_and_the_fix(self):
        message = compat.broken_binding_message("3.10.20", "6.12.0")
        for part in ("3.10.20", "6.12.0", "PySide6>=6.5,<6.12", "3.12", compat.OVERRIDE_ENV):
            self.assertIn(part, message)


class MainRefusesTests(unittest.TestCase):
    def tearDown(self):
        set_language("es")
        self.assertEqual(_qt.live_main_windows(), [])

    def run_main(self, language: str):
        set_language(language)
        stderr = io.StringIO()
        # Una aplicación cuyo exec() vuelve en el acto: si faltara la comprobación, la prueba falla en vez de colgarse.
        fake_app = mock.Mock(**{"exec.return_value": 0})
        with mock.patch.object(compat, "broken_qt_binding", return_value=("3.10.20", "6.12.0")), \
                mock.patch.object(app_module, "create_application", return_value=fake_app), \
                mock.patch("PySide6.QtWidgets.QMessageBox.critical") as critical, \
                mock.patch("vic2studio.ui.main_window.MainWindow") as window, \
                contextlib.redirect_stderr(stderr):
            code = app_module.main([])
        fake_app.exec.assert_not_called()
        return code, critical, window, stderr.getvalue()

    def test_main_stops_before_the_window_with_a_translated_message(self):
        for language, title_word in (("es", "incompatible"), ("en", "incompatible")):
            with self.subTest(language=language):
                code, critical, window, stderr = self.run_main(language)
                self.assertEqual(code, 1)
                window.assert_not_called()
                critical.assert_called_once()
                _parent, title, text = critical.call_args.args
                self.assertIn(title_word, title)
                self.assertIn("6.12.0", text)
                self.assertIn("3.10.20", text)
                self.assertNotIn("compat.", title + text)  # claves crudas
                self.assertIn("6.12.0", stderr)

    def test_texts_differ_by_language(self):
        _, es, _, _ = self.run_main("es")
        _, en, _, _ = self.run_main("en")
        self.assertNotEqual(es.call_args.args[2], en.call_args.args[2])


class TestHelperRefusesTests(unittest.TestCase):
    def run_import(self, override: str = "") -> subprocess.CompletedProcess:
        script = textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {str(TESTS)!r})
            import PySide6
            PySide6.__version_info__ = (6, 12, 0, "", "")
            sys.version_info = (3, 10, 20, "final", 0)
            try:
                import _qt
            except RuntimeError as error:
                print("REFUSED")
                print(error)
            else:
                print("IMPORTED")
        """)
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        env[compat.OVERRIDE_ENV] = override
        return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120, env=env)

    def test_importing_the_qt_helper_fails_with_a_clear_error(self):
        result = self.run_import()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("REFUSED"), result.stdout + result.stderr)
        self.assertIn("PySide6 6.12.0", result.stdout)
        self.assertIn("Python 3.10.20", result.stdout)

    def test_override_lets_the_helper_import(self):
        result = self.run_import(override="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "IMPORTED", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
