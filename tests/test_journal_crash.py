"""I2 y criterio 6: un fallo inyectado en cada paso de un guardado de 3 archivos deja, tras ``recover()``, todo
como antes o todo como después; recuperar dos veces da lo mismo (wizard §6.5).

Dos maneras de fallar en cada paso (``journal.FAULT_HOOK``):

- **excepción**: el propio ``commit`` revierte en el proceso;
- **corte**: desde ese momento todas las primitivas de ``fileio`` fallan (el disco
  desaparece), así que ``commit`` no puede revertir y queda el diario; después
  ``recover()`` resuelve.

Además, ``PermissionError`` en el tercer ``os.replace`` (antivirus en Windows).
La versión con ``os._exit`` en un subproceso está en ``test_journal_kill.py``.
"""

import errno
import os
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import build_layers  # noqa: E402
from vic2studio.core import fileio  # noqa: E402
from vic2studio.core.project import journal  # noqa: E402
from vic2studio.core.project.model import PlannedWrite, WriteAction  # noqa: E402
from vic2studio.core.project.recovery import pending_journals, recover, recover_all  # noqa: E402
from vic2studio.core.vfs import Fingerprint, VPath, WriteGuard  # noqa: E402

GAME = {"common/cb_types.txt": "cb = 1\r\n"}
MOD = {"common/countries.txt": "AAA = x\r\n", "events/old.txt": "old = yes\r\n"}
# Primitivas de fileio que usa el diario: en un «corte» fallan todas.
PRIMITIVES = ("atomic_write_bytes", "stage_bytes", "commit_staged", "discard_staged", "copy_file", "move_file",
              "remove_file", "make_dirs", "remove_empty_dirs", "fsync_dir")
# Pasos tras los que el guardado ya está completo en disco (no se revierte).
COMMITTED_STEPS = ("journal_committed", "close")
# Pasos tras los que la recuperación avanza (los temporales ya son durables y las copias están hechas).
FORWARD_STEPS = ("journal_backed_up", "replace", "trash", *COMMITTED_STEPS)


class SimulatedFault(Exception):
    pass


class Scenario:
    """Mod con dos archivos y un guardado de 3: MODIFY, CREATE en una carpeta nueva y MODIFY (o TRASH)."""

    def __init__(self, test: unittest.TestCase, *, trash: bool = False, base: Path | None = None):
        self.layers = build_layers(game=GAME, mod=MOD, base=base)
        test.addCleanup(self.layers.cleanup)
        self.mod = self.layers.mod_root
        self.guard = WriteGuard(self.mod, extra_files=[self.layers.descriptor])
        self.journal_dir = self.mod / journal.PROJECT_DIR / journal.JOURNAL_DIR
        third = (("events/old.txt", WriteAction.TRASH, None) if trash
                 else ("events/old.txt", WriteAction.MODIFY, b"old = no\r\n"))
        self.specs = [("common/countries.txt", WriteAction.MODIFY, b"AAA = y\r\n"),
                      ("history/countries/AAA - Aland.txt", WriteAction.CREATE, b"capital = 1\r\n"),
                      third]
        self.rels = [rel for rel, _, _ in self.specs]
        self.before = self.state()
        self.after = {rel: data for rel, _, data in self.specs}

    def writes(self) -> list[PlannedWrite]:
        writes = []
        for rel, action, data in self.specs:
            target = self.mod / rel
            expected = Fingerprint.of_path(target, with_hash=True) if target.exists() else None
            writes.append(PlannedWrite(VPath.of(rel), target, action, data, expected))
        return writes

    def transaction(self) -> journal.SaveTransaction:
        transaction = journal.SaveTransaction(self.guard, self.journal_dir, label="save.label")
        for write in self.writes():
            transaction.add(write)
        return transaction

    def state(self) -> dict:
        state = {}
        for rel in self.rels:
            path = self.mod / rel
            state[rel] = path.read_bytes() if path.exists() else None
        return state

    def files(self) -> dict:
        """Todo lo que hay en el mod (para comparar dos recuperaciones), sin las fechas."""
        return {rel: data for rel, (_, _, data) in self.layers.tree().items()}

    def leftovers(self) -> list[str]:
        return sorted(p.name for p in self.mod.rglob("*") if p.name.endswith(".tmp"))


def fault_points(trash: bool, test: unittest.TestCase) -> list[tuple[str, int]]:
    """(paso, índice) por los que pasa un guardado completo del escenario."""
    seen = []
    scenario = Scenario(test, trash=trash)
    with mock.patch.object(journal, "FAULT_HOOK", lambda step, index: seen.append((step, index))):
        scenario.transaction().commit()
    return seen


def raise_at(point):
    def hook(step, index):
        if (step, index) == point:
            raise SimulatedFault(point)
    return hook


class PowerCut:
    """Desde el paso indicado, todas las primitivas de fileio fallan con OSError."""

    def __init__(self, point):
        self.point = point
        self.dead = False

    def hook(self, step, index):
        if (step, index) == self.point:
            self.dead = True
            raise SimulatedFault(self.point)

    def patches(self, stack: ExitStack) -> None:
        for name in PRIMITIVES:
            original = getattr(fileio, name)
            stack.enter_context(mock.patch.object(fileio, name, self._wrap(original)))
        stack.enter_context(mock.patch.object(journal, "FAULT_HOOK", self.hook))

    def _wrap(self, original):
        def wrapper(*args, **kwargs):
            if self.dead:
                raise OSError(errno.EIO, "el disco ya no responde")
            return original(*args, **kwargs)
        return wrapper


class JournalCrashTests(unittest.TestCase):
    def assertConsistentAfterRecovery(self, scenario, expected, label):
        first = recover_all(scenario.journal_dir, scenario.guard)
        state = scenario.state()
        self.assertIn(state, (scenario.before, scenario.after), f"{label}: ni todo antes ni todo después")
        self.assertEqual(state, expected, label)
        self.assertEqual(scenario.leftovers(), [], f"{label}: quedan temporales")
        self.assertEqual(pending_journals(scenario.journal_dir), [], f"{label}: queda el diario")
        files = scenario.files()
        second = recover_all(scenario.journal_dir, scenario.guard)
        self.assertEqual(second, [], f"{label}: la segunda recuperación no tiene nada que hacer")
        self.assertEqual(scenario.files(), files, f"{label}: recuperar dos veces da lo mismo")
        for result in first:
            self.assertIn(result.outcome, ("rolled_back", "rolled_forward", "cleaned"))
            self.assertEqual(recover(scenario.journal_dir, scenario.guard, result.txid).outcome, "nothing")
        return first

    def test_fault_points_cover_every_step(self):
        points = fault_points(False, self) + fault_points(True, self)
        self.assertEqual({step for step, _ in points}, set(journal.STEPS))
        self.assertIn(("replace", 2), points)
        self.assertIn(("stage", 2), points)

    def test_exception_at_every_step(self):
        for trash in (False, True):
            for point in fault_points(trash, self):
                label = f"excepción en {point}{' con TRASH' if trash else ''}"
                with self.subTest(point=point, trash=trash):
                    scenario = Scenario(self, trash=trash)
                    with mock.patch.object(journal, "FAULT_HOOK", raise_at(point)):
                        with self.assertRaises(SimulatedFault):
                            scenario.transaction().commit()
                    committed = point[0] in COMMITTED_STEPS
                    self.assertConsistentAfterRecovery(scenario, scenario.after if committed else scenario.before,
                                                       label)

    def test_power_cut_at_every_step(self):
        for trash in (False, True):
            for point in fault_points(trash, self):
                label = f"corte en {point}{' con TRASH' if trash else ''}"
                with self.subTest(point=point, trash=trash):
                    scenario = Scenario(self, trash=trash)
                    cut = PowerCut(point)
                    with ExitStack() as stack:
                        cut.patches(stack)
                        with self.assertRaises(SimulatedFault):
                            scenario.transaction().commit()
                    self.assertTrue(pending_journals(scenario.journal_dir), f"{label}: el diario sobrevive al corte")
                    forward = point[0] in FORWARD_STEPS
                    results = self.assertConsistentAfterRecovery(
                        scenario, scenario.after if forward else scenario.before, label)
                    self.assertEqual(len(results), 1)

    def test_permission_error_on_the_third_replace(self):
        """El tercer os.replace falla siempre: commit revierte; recover no tiene nada que hacer; todo antes."""
        scenario = Scenario(self)
        third = os.fspath(scenario.mod / "events" / "old.txt")
        real = os.replace

        def locked(src, dst):
            if os.fspath(dst) == third and os.fspath(src).endswith(".tmp"):
                raise PermissionError(errno.EACCES, "abierto en otro programa")
            return real(src, dst)

        with mock.patch.object(fileio.os, "replace", locked), mock.patch.object(fileio.time, "sleep"):
            with self.assertRaises(PermissionError):
                scenario.transaction().commit()
        self.assertConsistentAfterRecovery(scenario, scenario.before, "PermissionError en el tercer os.replace")

    def test_permission_error_on_the_third_replace_and_a_failed_rollback(self):
        """Si además falla la reversión, queda el diario y recover() lo lleva a un estado completo."""
        scenario = Scenario(self)
        third = os.fspath(scenario.mod / "events" / "old.txt")
        real_replace, real_copy, real_move = os.replace, fileio.copy_file, fileio.move_file
        failed = {"replace": False}

        def locked(src, dst):
            if os.fspath(dst) == third and os.fspath(src).endswith(".tmp"):
                failed["replace"] = True
                raise PermissionError(errno.EACCES, "abierto en otro programa")
            return real_replace(src, dst)

        def breaks_after_the_error(real):
            def wrapper(*args, **kwargs):
                if failed["replace"]:
                    raise OSError(errno.EIO, "falla también al revertir")
                return real(*args, **kwargs)
            return wrapper

        with mock.patch.object(fileio.os, "replace", locked), mock.patch.object(fileio.time, "sleep"), \
                mock.patch.object(fileio, "copy_file", breaks_after_the_error(real_copy)), \
                mock.patch.object(fileio, "move_file", breaks_after_the_error(real_move)):
            with self.assertRaises(PermissionError):
                scenario.transaction().commit()
        self.assertEqual(len(pending_journals(scenario.journal_dir)), 1, "la reversión falló: queda el diario")
        self.assertNotIn(scenario.state(), (scenario.before, scenario.after), "a medias hasta recuperar")
        # Al reabrir, el antivirus ya soltó el archivo: el tercer temporal sigue ahí y se avanza.
        self.assertConsistentAfterRecovery(scenario, scenario.after, "reversión fallida")


if __name__ == "__main__":
    unittest.main()
