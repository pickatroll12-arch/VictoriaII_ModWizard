"""Regresión: cambios externos en la ventana con el Project real (un foco = una relectura, sin diálogos falsos)."""
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
import _qt  # noqa: E402
import test_ui_shell as shell  # noqa: E402
from test_ui_real_project import RealProjectMixin  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

from vic2studio.core.vfs import VPath  # noqa: E402

REL = VPath.of("common/vsm_new.txt")


class ExternalChangeWindowTests(RealProjectMixin, shell.ProjectWindowCase):
    def focus(self, window):
        window._on_application_state(Qt.ApplicationState.ApplicationActive)
        _qt.process_events(20)

    def test_a_clean_file_changed_outside_is_read_once(self):
        window = self.open_window()
        clean = self.project.ws.open(REL)
        emitted = []
        window.session.documentsChanged.connect(emitted.append)
        self.layers.mod("common/vsm_new.txt").write_bytes(b"y = 99\r\n")
        version = clean.version
        self.focus(window)
        self.assertEqual(len(emitted), 1, "un foco, una señal documentsChanged")
        self.assertEqual(clean.version, version + 1, "se relee una sola vez")
        self.assertEqual(self.dialogs.types(), [])

    def test_a_clean_file_deleted_outside_asks_nothing(self):
        window = self.open_window()
        self.project.ws.open(REL)
        self.layers.mod("common/vsm_new.txt").unlink()
        self.focus(window)
        self.assertEqual(self.dialogs.types(), [], "no había cambios en memoria: nada que decidir")
        self.assertIsNone(self.project.ws.peek(REL))


if __name__ == "__main__":
    unittest.main()
