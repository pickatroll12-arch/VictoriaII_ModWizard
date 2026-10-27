"""Regresión: un .mod UTF-16 (el juego no lo lee) se puede editar y se guarda en cp1252 (§14.1, Project real)."""
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
import _qt  # noqa: E402,F401
import test_ui_descriptor as descriptor_tests  # noqa: E402
from test_ui_real_project import RealProjectMixin  # noqa: E402


UTF16 = '﻿name = "Victorian Spirit" # ñ\r\npath = "mod/VSM"\r\nuser_dir = "VSM"\r\n'.encode("utf-16-le")


class Utf16DescriptorFormTests(RealProjectMixin, descriptor_tests.DescriptorCase):
    descriptor = UTF16

    def test_the_form_converts_it_to_cp1252(self):
        page = self.open_window()
        self.assertTrue(page.name_edit.isEnabled(), "el proyecto no es de solo lectura")
        self.type_into(page.name_edit, "Shago Mod")
        self.assertTrue(self.window.save_project())
        self.assertEqual(self.layers.descriptor.read_bytes(),
                         b'name = "Shago Mod" # \xf1\r\npath = "mod/VSM"\r\nuser_dir = "VSM"\r\n')

    def test_create_button_alone_converts_it(self):
        page = self.open_window()
        self.assertTrue(page.commit(force=True))
        self.assertTrue(self.window.save_project())
        self.assertEqual(self.layers.descriptor.read_bytes(),
                         b'name = "Victorian Spirit" # \xf1\r\npath = "mod/VSM"\r\nuser_dir = "VSM"\r\n')


if __name__ == "__main__":
    unittest.main()
