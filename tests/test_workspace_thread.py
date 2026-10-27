"""I12 (D18): el ``Workspace`` solo se usa desde su hilo; ``bind_to_current_thread`` lo entrega a otro."""

import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402
from vic2studio.core.project import Project, WrongThreadError  # noqa: E402

CB = "common/cb_types.txt"


def in_thread(fn):
    """Ejecuta ``fn`` en otro hilo y devuelve (resultado, excepción)."""
    box = {}

    def run():
        try:
            box["result"] = fn()
        except BaseException as exc:   # noqa: BLE001 - se devuelve para comprobarla
            box["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(30)
    return box.get("result"), box.get("error")


class WorkspaceThreadTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)
        self.game = build_minigame()
        self.addCleanup(self.game.cleanup)

    def test_other_threads_are_refused(self):
        project = Project.open(self.game.game_root, self.game.mod_root)
        self.addCleanup(project.close)
        ws = project.ws
        handle = ws.open(CB)
        calls = {
            "open": lambda: ws.open(CB),
            "peek": lambda: ws.peek(CB),
            "transaction": lambda: ws.transaction("undo.x").__enter__(),
            "touch": lambda: ws.touch(handle),
            "undo": ws.undo,
            "redo": ws.redo,
            "dirty": ws.dirty,
            "changeset": ws.changeset,
            "save": ws.save,
            "revert": lambda: ws.revert(CB),
            "check_external_changes": ws.check_external_changes,
            "write_recovery": ws.write_recovery,
            "subscribe": lambda: ws.subscribe(print),
            "history": ws.history,
        }
        for name, call in calls.items():
            with self.subTest(call=name):
                _, error = in_thread(call)
                self.assertIsInstance(error, WrongThreadError)
        self.assertFalse(ws.in_transaction, "un intento desde otro hilo no deja nada abierto")
        self.assertIs(ws.open(CB), handle, "el hilo dueño sigue pudiendo")

    def test_built_in_background_and_bound_to_the_ui_thread(self):
        project, error = in_thread(lambda: Project.open(self.game.game_root, self.game.mod_root))
        self.assertIsNone(error)
        self.addCleanup(lambda: project.close() if not project.ws._closed else None)
        with self.assertRaises(WrongThreadError):
            project.ws.open(CB)
        project.ws.bind_to_current_thread()
        handle = project.ws.open(CB)
        with project.edit("undo.edit"):
            project.ws.touch(handle)
            handle.model.document.get("conquer_land").set("months", "13")
        self.assertTrue(handle.dirty)

    def test_cannot_rebind_with_an_open_transaction(self):
        project = Project.open(self.game.game_root, self.game.mod_root)
        self.addCleanup(project.close)
        with project.edit("undo.x"):
            with self.assertRaises(RuntimeError):
                project.ws.bind_to_current_thread()


if __name__ == "__main__":
    unittest.main()
