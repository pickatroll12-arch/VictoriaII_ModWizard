"""Regresión: «Descriptor .mod» (Project real) con un nombre que cp1252 no admite: se avisa y no se escribe nada."""
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
import _qt  # noqa: E402
import test_ui_descriptor as descriptor_tests  # noqa: E402
from test_ui_real_project import RealProjectMixin  # noqa: E402


class UnencodableNameFormTests(RealProjectMixin, descriptor_tests.DescriptorCase):
    def setUp(self):
        super().setUp()
        self.layers.descriptor.unlink()      # mod sin .mod: el formulario lo crea al confirmar un campo

    def test_a_name_cp1252_cannot_write_is_a_problem_not_an_exception(self):
        page = self.open_window()
        hooks = []
        previous = sys.excepthook
        sys.excepthook = lambda kind, value, tb: hooks.append(value)
        try:
            # QTest.keyClicks no sabe teclear 日 (Qt aborta): se pone el texto y se emiten las señales del usuario.
            page.name_edit.setText("Mod 日本")
            page.name_edit.textEdited.emit("Mod 日本")
            page.name_edit.editingFinished.emit()
            _qt.process_events()
        finally:
            sys.excepthook = previous
        self.assertEqual([type(e).__name__ for e in hooks], [], "ninguna excepción sale del slot")
        self.assertIsNone(self.handle(), "nada llega al documento")
        self.assertTrue(any("日" in text for text in self.problem_texts()), self.problem_texts())


if __name__ == "__main__":
    unittest.main()
