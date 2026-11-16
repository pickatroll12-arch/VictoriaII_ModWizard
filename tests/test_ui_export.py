"""«Exportar a zip» en la interfaz (``ui/dialogs/export.py``, criterio 4 de la iteración 10): el diálogo pide
guardar y validar antes, bloquea con errores del mod y escribe un zip sin la carpeta del Studio."""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets)
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from test_ui_entity import EntityWindowCase, WAIT_MS  # noqa: E402
from test_ui_smoke import MARK_OPEN, PSEUDO, collect_texts, pseudo_catalog  # noqa: E402
from vic2studio.core.clausewitz import Severity  # noqa: E402
from vic2studio.core.vfs.paths import VPath  # noqa: E402
from vic2studio.i18n import N_, set_language, tr, translator  # noqa: E402
from vic2studio.ui.dialogs.export import ExportZipDialog  # noqa: E402


class ExportDialogTests(EntityWindowCase):
    def setUp(self):
        super().setUp()
        set_language("es")
        self.addCleanup(set_language, "es")
        self._out = tempfile.TemporaryDirectory()
        self.addCleanup(self._out.cleanup)
        self.out = Path(self._out.name)

    def dialog(self) -> ExportZipDialog:
        dialog = ExportZipDialog(self.window.session, self.window)
        self.assertTrue(_qt.wait_until(lambda: dialog.plan is not None, WAIT_MS), "el plan no llegó")
        return dialog

    def badges(self, dialog) -> list[tuple[str, str]]:
        return [(b.level, b.label.text()) for b in dialog._badges]

    def validate(self):
        session = self.window.session
        session.validate()
        self.assertTrue(_qt.wait_until(lambda: session.report is not None and not session.is_validating(), WAIT_MS))
        _qt.process_events(20)

    def test_validate_then_export_a_clean_zip(self):
        self.open_window()
        (self.game.mod_root / "notas.txt.bak").write_bytes(b"copia\r\n")
        dialog = self.dialog()
        self.assertFalse(dialog.export_button.isEnabled())
        self.assertIn(("warning", tr("export.validate_first")), self.badges(dialog))
        self.assertTrue(dialog.validate_button.isVisibleTo(dialog))
        self.assertIn(tr("export.skip.backup", count="1"), dialog.skipped.text())
        dialog.validate_button.click()
        self.assertTrue(_qt.wait_until(lambda: self.window.session.report is not None
                                       and not self.window.session.is_validating(), WAIT_MS))
        _qt.process_events(20)
        dialog.dest_edit.setText(str(self.out / "minijuego.zip"))
        with mock.patch.object(self.window.session, "problems", return_value=[]):
            dialog.refresh()
            self.assertEqual(self.badges(dialog), [])
            self.assertTrue(dialog.export_button.isEnabled())
            dialog.export_button.click()
            self.assertTrue(_qt.wait_until(lambda: dialog.result is not None, WAIT_MS), self.badges(dialog))
        with zipfile.ZipFile(self.out / "minijuego.zip") as zf:
            names = zf.namelist()
        folder = self.game.mod_root.name
        self.assertTrue(names and all(n.startswith(folder + "/") or "/" not in n for n in names), names)
        self.assertFalse([n for n in names if ".vic2studio" in n or n.endswith(".bak")])
        self.assertEqual(len(names), len(dialog.plan.members))
        self.assertEqual(self.badges(dialog)[-1][0], "ok")

    def test_errors_unsaved_changes_and_a_bad_destination_block(self):
        window = self.open_window()
        self.validate()
        dialog = self.dialog()
        error = mock.Mock(severity=Severity.ERROR)
        with mock.patch.object(window.session, "problems", return_value=[error, error]):
            dialog.dest_edit.setText(str(self.out / "x.zip"))
            self.assertIn(("error", tr("export.errors", count="2")), self.badges(dialog))
            self.assertFalse(dialog.export_button.isEnabled())
            self.assertFalse(dialog.export())
        with mock.patch.object(window.session, "problems", return_value=[]):
            dialog.dest_edit.setText(str(self.game.mod_root / "x.zip"))
            self.assertIn(("error", tr("export.dest.inside_mod")), self.badges(dialog))
            self.assertFalse(dialog.export_button.isEnabled())
            session = window.session
            rel = "common/countries.txt"
            with session.edit(N_("pending.undo_revert"), name=rel):
                handle = session.project.ws.open(VPath.of(rel))
                session.project.ws.replace_text(handle, b"# cambio sin guardar\r\n")
            _qt.process_events(20)
            dialog.dest_edit.setText(str(self.out / "x.zip"))
            levels = self.badges(dialog)
            self.assertEqual(levels[0], ("error", tr("export.unsaved", count="1")))
            self.assertFalse(dialog.export_button.isEnabled())
        self.assertFalse((self.out / "x.zip").exists())

    def test_ctrl_e_and_the_validation_button_open_the_dialog(self):
        window = self.open_window()
        window.show()
        QTest.keyClick(window, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
        _qt.process_events(20)
        page = window.show_page("project:validation")
        page.export_button.click()
        _qt.process_events(20)
        self.assertEqual(self.dialogs.types(), [ExportZipDialog, ExportZipDialog])
        self.assertEqual(page.export_button.text(), tr("checks.export"))

    def test_every_text_is_translated_and_fits_at_1100x700(self):
        self.open_window()
        (self.game.mod_root / "notas.txt.bak").write_bytes(b"copia\r\n")
        dialog = self.dialog()
        translator().register_catalog(PSEUDO, pseudo_catalog())
        try:
            for language in (PSEUDO, "en", "es"):
                with self.subTest(language=language):
                    set_language(language)
                    dialog.retranslate()
                    _qt.process_events(20)
                    texts = {k: v for k, v in collect_texts(dialog).items() if v}
                    if language == PSEUDO:
                        self.assertEqual({k: v for k, v in texts.items() if MARK_OPEN not in v}, {})
                    hint = dialog.minimumSizeHint()
                    self.assertLessEqual(hint.width(), 1100, language)
                    self.assertLessEqual(hint.height(), 700, language)
        finally:
            set_language("es")


if __name__ == "__main__":
    unittest.main()
