"""I5 (propiedad): secuencias aleatorias de edición con semilla fija sobre el minijuego.

Deshacer todo da los bytes originales y rehacer todo, los del avance. En cada
paso, un documento cuyo contenido difiere del disco está sucio, y sin guardados
de por medio deshacer todo no deja nada sucio. Las operaciones mezclan archivos
del juego (se copiarían), del mod, CSV, archivos nuevos, borrados, sustitución
del texto, transacciones de varios archivos y transacciones anidadas que fallan.
"""

import random
import string
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _layers import isolate_appdirs  # noqa: E402
from _minigame import CB_MONTHS, build_minigame  # noqa: E402
from vic2studio.core.project import DocKind, Workspace  # noqa: E402
from vic2studio.core.project.codecs import codec_for  # noqa: E402
from vic2studio.core.project.settings import default_settings  # noqa: E402
from vic2studio.core.vfs import VirtualFS  # noqa: E402

CB = "common/cb_types.txt"
DECISIONS = "decisions/tst_decisions.txt"
LOC = "localisation/00_TST_decisions.csv"
NEW = "events/tst_random.txt"
RELS = (CB, DECISIONS, LOC, NEW)
SEEDS = (20261026, 7, 1836)
STEPS = 40


class Abort(Exception):
    pass


class Editor:
    def __init__(self, ws: Workspace, rng: random.Random):
        self.ws = ws
        self.rng = rng

    def word(self) -> str:
        return "".join(self.rng.choice(string.ascii_lowercase) for _ in range(self.rng.randint(3, 8)))

    def live(self, rel):
        handle = self.ws.peek(rel)
        if handle is None:
            try:
                handle = self.ws.open(rel)
            except FileNotFoundError:
                return None
        return None if handle.deleted else handle

    # --- operaciones (dentro de una transacción) ---

    def months(self):
        handle = self.live(CB)
        if handle is None:
            return
        self.ws.touch(handle)
        handle.model.document.get(self.rng.choice(sorted(CB_MONTHS))).set("months", str(self.rng.randint(1, 60)))

    def decision(self):
        handle = self.live(DECISIONS)
        if handle is None:
            return
        self.ws.touch(handle)
        block = handle.model.document.get("political_decisions")
        if block.entries and self.rng.random() < 0.3:
            block.remove_entry(self.rng.choice(block.entries))
        else:
            block.append(self.word(), "yes")

    def localisation(self):
        handle = self.live(LOC)
        if handle is None:
            return
        self.ws.touch(handle)
        handle.model.set(self.rng.choice(["tst_reform", self.word()]), self.rng.choice(["en", "es"]), self.word())

    def new_file(self):
        handle = self.live(NEW)
        if handle is None:
            handle = self.ws.create(NEW, DocKind.CLAUSEWITZ)
        else:
            self.ws.touch(handle)
        handle.model.document.append(self.word(), str(self.rng.randint(0, 9)))

    def delete(self):
        rel = self.rng.choice((DECISIONS, LOC, NEW))
        if self.live(rel) is not None:
            self.ws.delete(rel)

    def replace_text(self):
        handle = self.live(DECISIONS)
        if handle is None:
            return
        self.ws.replace_text(handle, f"political_decisions = {{\r\n\t{self.word()} = yes\r\n}}\r\n".encode())

    def failing_inner(self):
        try:
            with self.ws.transaction("undo.inner"):
                self.months()
                self.decision()
                raise Abort()
        except Abort:
            pass

    OPS = ("months", "decision", "localisation", "new_file", "delete", "replace_text", "failing_inner")

    def step(self):
        ops = self.rng.sample(self.OPS, self.rng.randint(1, 3))
        with self.ws.transaction("undo.random", ops="+".join(ops)):
            for name in ops:
                getattr(self, name)()


def memory_state(ws):
    state = {}
    for rel in RELS:
        handle = ws.peek(rel)
        if handle is None:
            try:
                handle = ws.open(rel)
            except FileNotFoundError:
                state[rel] = None
                continue
        state[rel] = None if handle.deleted else codec_for(handle.kind).snapshot(handle.model)
    return state


def disk_state(game):
    state = {}
    for rel in RELS:
        for path in (game.mod(rel), game.game(rel)):
            if path.exists():
                state[rel] = path.read_bytes()
                break
        else:
            state[rel] = None
    return state


class UndoPropertyTests(unittest.TestCase):
    def setUp(self):
        isolate_appdirs(self)

    def workspace(self, game):
        vfs = VirtualFS(game.game_root, game.mod_root, descriptor=game.descriptor)
        vfs.scan()
        return Workspace(vfs, settings=default_settings(game.mod_root))

    def assertDirtyInvariant(self, ws, game, label):
        memory, disk = memory_state(ws), disk_state(game)
        for rel in RELS:
            handle = ws.peek(rel)
            if memory[rel] != disk[rel]:
                self.assertTrue(handle is not None and handle.dirty, f"{label}: {rel} difiere del disco y no está sucio")

    def run_sequence(self, seed, *, saves):
        game = build_minigame()
        self.addCleanup(game.cleanup)
        ws = self.workspace(game)
        self.addCleanup(ws.close)
        rng = random.Random(seed)
        editor = Editor(ws, rng)
        initial = memory_state(ws)
        states = [initial]
        for number in range(STEPS):
            editor.step()
            if ws.history() and (not states or memory_state(ws) != states[-1]):
                states.append(memory_state(ws))
            if saves and rng.random() < 0.2:
                self.assertTrue(ws.save().ok)
            self.assertDirtyInvariant(ws, game, f"semilla {seed}, paso {number}")
        final = memory_state(ws)
        self.assertNotEqual(final, initial, "la secuencia cambia algo")
        undone = 0
        while ws.can_undo():
            ws.undo()
            undone += 1
            self.assertDirtyInvariant(ws, game, f"semilla {seed}, deshacer {undone}")
        self.assertEqual(memory_state(ws), initial, f"semilla {seed}: deshacer todo da los bytes originales")
        if not saves:
            self.assertEqual(ws.dirty(), [], f"semilla {seed}: sin guardados, deshacer todo deja todo limpio")
        while ws.can_redo():
            ws.redo()
        self.assertEqual(memory_state(ws), final, f"semilla {seed}: rehacer todo da los bytes del avance")
        self.assertTrue(ws.save().ok)
        self.assertEqual(disk_state(game), final, f"semilla {seed}: guardar escribe exactamente el estado final")
        self.assertEqual(ws.dirty(), [])
        return undone

    def test_random_sequences_without_saves(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.assertGreater(self.run_sequence(seed, saves=False), 10)

    def test_random_sequences_with_saves(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.run_sequence(seed, saves=True)


if __name__ == "__main__":
    unittest.main()
