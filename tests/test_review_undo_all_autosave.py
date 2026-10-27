"""Regresión (ronda 2): deshacerlo todo y morir antes del siguiente latido del autoguardado no ofrece, al reabrir,
cambios que el usuario ya había deshecho (arreglo incompleto de la integración: solo se borraba en el latido)."""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS.parent / "src"))

from _layers import build_layers, isolate_appdirs  # noqa: E402

from vic2studio.core.project import Project  # noqa: E402

CHILD = textwrap.dedent("""
    import os, sys, time
    sys.path[:0] = [sys.argv[1], os.path.join(sys.argv[1], "..", "src")]
    import _qt
    app = _qt.application()
    from PySide6.QtCore import QCoreApplication
    from vic2studio.core.project import Workspace
    from vic2studio.i18n import N_
    from vic2studio.ui.session import Session
    session = Session()
    session.open_project(sys.argv[2], sys.argv[3])
    while session.is_busy():
        QCoreApplication.processEvents(); time.sleep(0.01)
    for i in range(Workspace.AUTOSAVE_TRANSACTIONS):          # el autoguardado salta en la vigésima
        with session.edit(N_("pending.undo_revert"), name="x"):
            ws = session.project.ws
            ws.replace_text(ws.open("common/x.txt"), b"a = %d\\r\\n" % (10 + i))
    while session.undo() is not None:
        pass
    QCoreApplication.processEvents()
    assert session.dirty_count() == 0
    os._exit(0)   # corte antes del siguiente latido (60 s)
""")


class UndoAllThenCrashTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)
        self.layers = build_layers(game={"common/x.txt": "a = 1\r\n"}, mod={"common/x.txt": "a = 2\r\n"})
        self.addCleanup(self.layers.cleanup)

    def test_nothing_undone_is_offered_again(self):
        script = Path(tempfile.mkdtemp()) / "child.py"
        script.write_text(CHILD, encoding="utf-8")
        subprocess.run([sys.executable, str(script), str(TESTS), str(self.layers.game_root),
                        str(self.layers.mod_root)], check=True, env=os.environ.copy(), timeout=60)
        project = Project.open(self.layers.game_root, self.layers.mod_root)
        self.addCleanup(project.close)
        self.assertEqual(project.orphan_sessions, [], "todo estaba deshecho: no hay nada que recuperar")


if __name__ == "__main__":
    unittest.main()
