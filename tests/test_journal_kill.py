"""I2 y criterio 6 con un proceso que muere de verdad: ``os._exit`` en el paso k de un guardado de 3 archivos.

El subproceso no ejecuta ningún ``finally`` ni reversión; al «reabrir», ``recover()``
deja todo como antes o todo como después, y recuperar dos veces da lo mismo.
"""

import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "src"))

from test_journal_crash import FORWARD_STEPS, Scenario, fault_points  # noqa: E402
from vic2studio.core.project.recovery import pending_journals, recover_all  # noqa: E402

EXIT_CODE = 37
CHILD = textwrap.dedent("""
    import json, os, sys
    from pathlib import Path
    sys.path[:0] = [sys.argv[2], sys.argv[3]]
    from vic2studio.core.project import journal
    from vic2studio.core.project.model import PlannedWrite, WriteAction
    from vic2studio.core.vfs import Fingerprint, VPath, WriteGuard

    args = json.loads(sys.argv[1])
    point = tuple(args["point"])

    def hook(step, index):
        if (step, index) == point:
            os._exit(args["exit_code"])

    journal.FAULT_HOOK = hook
    mod = Path(args["mod"])
    guard = WriteGuard(mod, extra_files=[Path(args["descriptor"])])
    transaction = journal.SaveTransaction(guard, Path(args["journal_dir"]), label="save.label")
    for rel, action, data in args["specs"]:
        target = mod / rel
        expected = Fingerprint.of_path(target, with_hash=True) if target.exists() else None
        transaction.add(PlannedWrite(VPath.of(rel), target, WriteAction(action),
                                     None if data is None else data.encode("latin-1"), expected))
    transaction.commit()
    os._exit(0)
""")


class JournalKillTests(unittest.TestCase):
    def run_child(self, scenario, point):
        args = {
            "point": list(point), "exit_code": EXIT_CODE, "mod": str(scenario.mod),
            "descriptor": str(scenario.layers.descriptor), "journal_dir": str(scenario.journal_dir),
            "specs": [[rel, action.value, None if data is None else data.decode("latin-1")]
                      for rel, action, data in scenario.specs],
        }
        return subprocess.run([sys.executable, "-c", CHILD, json.dumps(args), str(TESTS.parent / "src"),
                               str(TESTS)], capture_output=True, text=True, timeout=60)

    def test_kill_at_each_step(self):
        points = []
        for trash in (False, True):
            for point in fault_points(trash, self):
                # Todos los pasos en el primer índice y el reemplazo de cada archivo.
                if point[1] == 0 or point[0] in ("replace", "stage"):
                    points.append((trash, point))
        self.assertGreaterEqual(len(points), 12)
        for trash, point in points:
            with self.subTest(point=point, trash=trash):
                scenario = Scenario(self, trash=trash)
                done = self.run_child(scenario, point)
                self.assertEqual(done.returncode, EXIT_CODE, done.stderr)
                self.assertEqual(len(pending_journals(scenario.journal_dir)), 1, "el diario sobrevive al proceso")
                recover_all(scenario.journal_dir, scenario.guard)
                expected = scenario.after if point[0] in FORWARD_STEPS else scenario.before
                self.assertEqual(scenario.state(), expected, point)
                self.assertEqual(scenario.leftovers(), [])
                files = scenario.files()
                self.assertEqual(recover_all(scenario.journal_dir, scenario.guard), [])
                self.assertEqual(scenario.files(), files)

    def test_child_without_fault_saves_everything(self):
        scenario = Scenario(self)
        done = self.run_child(scenario, ("never", -1))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(scenario.state(), scenario.after)
        self.assertEqual(pending_journals(scenario.journal_dir), [])


if __name__ == "__main__":
    unittest.main()
