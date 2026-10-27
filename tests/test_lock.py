"""Bloqueo entre instancias (wizard §6.5): la segunda instancia abre en solo lectura; un pid muerto caduca."""

import json
import os
import socket
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "src"))

from _layers import isolate_appdirs  # noqa: E402
from _minigame import build_minigame  # noqa: E402
from vic2studio.core.project import Project  # noqa: E402
from vic2studio.core.project.lock import ProjectLock, pid_alive  # noqa: E402
from vic2studio.core.project.model import SAVE_READ_ONLY  # noqa: E402

HOLDER = textwrap.dedent("""
    import sys
    sys.path[:0] = [sys.argv[2]]
    from vic2studio.core.project.lock import ProjectLock
    lock = ProjectLock(sys.argv[1])
    print("held" if lock.acquire() else "busy", flush=True)
    sys.stdin.readline()
    lock.release()
""")


def dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


class LockTests(unittest.TestCase):
    def setUp(self):
        self.appdata = isolate_appdirs(self)
        self.game = build_minigame()
        self.addCleanup(self.game.cleanup)

    def write_lock(self, pid, host=None):
        lock = ProjectLock(self.game.mod_root)
        lock.path.parent.mkdir(parents=True, exist_ok=True)
        lock.path.write_text(json.dumps({"pid": pid, "host": host or socket.gethostname(), "started": "x"}),
                             encoding="utf-8")
        return lock

    def test_acquire_and_release(self):
        lock = ProjectLock(self.game.mod_root)
        self.assertTrue(lock.path.is_relative_to(self.appdata))
        self.assertNotIn(str(self.game.mod_root), str(lock.path), "el bloqueo vive fuera del mod")
        self.assertTrue(lock.acquire())
        self.assertEqual(lock.holder().pid, os.getpid())
        self.assertFalse(ProjectLock(self.game.mod_root).acquire(), "otro Project del mismo proceso: solo lectura")
        other = ProjectLock(self.game.mod_root)
        other.release()
        self.assertTrue(lock.path.exists(), "release solo borra el bloqueo propio")
        lock.release()
        self.assertFalse(lock.path.exists())
        with ProjectLock(self.game.mod_root) as again:
            self.assertTrue(again.held)
        self.assertFalse(lock.path.exists())

    def test_stale_lock_of_a_dead_process_is_replaced(self):
        lock = self.write_lock(dead_pid())
        self.assertTrue(lock.acquire())
        self.assertEqual(lock.holder().pid, os.getpid())
        lock.release()

    def test_unreadable_lock_is_replaced(self):
        lock = self.write_lock(1)
        lock.path.write_text("{roto", encoding="utf-8")
        self.assertTrue(lock.acquire())
        lock.release()

    def test_lock_from_another_host_is_respected(self):
        lock = self.write_lock(dead_pid(), host="otro-equipo-" + socket.gethostname())
        self.assertFalse(lock.acquire())

    def test_pid_alive(self):
        self.assertTrue(pid_alive(os.getpid()))
        self.assertFalse(pid_alive(dead_pid()))
        self.assertFalse(pid_alive(0))
        self.assertFalse(pid_alive(-5))

    def test_second_instance_opens_read_only(self):
        """Otro proceso tiene el mod abierto: este Project es de solo lectura y no guarda."""
        holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(self.game.mod_root), str(TESTS.parent / "src")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                  env={**os.environ})
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            project = Project.open(self.game.game_root, self.game.mod_root)
            try:
                self.assertTrue(project.read_only)
                self.assertTrue(project.ws.read_only)
                self.assertEqual([p.code for p in project.save().problems], [SAVE_READ_ONLY])
                self.assertEqual(project.orphan_sessions, [])
            finally:
                project.close()
            self.assertTrue(ProjectLock(self.game.mod_root).path.exists(), "cerrar no suelta un bloqueo ajeno")
        finally:
            holder.communicate("\n", timeout=30)
        project = Project.open(self.game.game_root, self.game.mod_root)
        self.addCleanup(project.close)
        self.assertFalse(project.read_only, "al irse la otra instancia, el mod vuelve a ser editable")


if __name__ == "__main__":
    unittest.main()
