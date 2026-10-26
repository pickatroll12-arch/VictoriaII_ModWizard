"""Tareas en segundo plano (``ui.tasks``): entrega, cancelación, grupos de hilos, recolector y cierre.

Las funciones de las tareas esperan a ``threading.Event`` en vez de dormir, para
que el orden de los sucesos no dependa de lo cargada que esté la máquina.
"""

import contextlib
import gc
import io
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import weakref
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _qt  # noqa: E402  (antes de PySide6.QtWidgets: plataforma offscreen y avisos)
from PySide6.QtCore import QElapsedTimer, QObject, QThread, QTimer  # noqa: E402
from shiboken6 import delete  # noqa: E402

APP = _qt.application()

from vic2studio.core.cancel import Cancelled  # noqa: E402
from vic2studio.ui import tasks  # noqa: E402
from vic2studio.ui.tasks import (  # noqa: E402
    GC_FREEZE_MIN_OBJECTS,
    POOL_IMAGES,
    POOL_PREVIEW,
    POOL_VALIDATION,
    TaskFailure,
    TaskRunner,
    cancel_all,
    thread_pool,
    wait_for_tasks,
)

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT_MS = 10000
STALL_LIMIT_MS = 250


class Result(list):
    """Resultado grande que admite referencias débiles, como los de verdad (dataclasses)."""


class Node:
    pass


def make_cycle(freed: list, tag: str) -> None:
    """Basura cíclica: solo la libera el recolector, y entonces anota ``tag`` en ``freed``."""
    a, b = Node(), Node()
    a.other, b.other = b, a
    weakref.finalize(a, freed.append, tag)


class TaskCase(unittest.TestCase):
    def setUp(self):
        _qt.take_qt_messages()
        self.events: list[threading.Event] = []
        self.owner = QObject()

    def tearDown(self):
        for event in self.events:
            event.set()
        cancel_all()
        self.assertTrue(wait_for_tasks(TIMEOUT_MS), "quedaron tareas sin terminar")
        _qt.process_events()
        delete(self.owner)
        _qt.process_events()
        self.assertTrue(gc.isenabled(), "el recolector de basura quedó desactivado")
        self.assertEqual(_qt.take_qt_messages(), [], "avisos de Qt durante la prueba")

    def event(self) -> threading.Event:
        event = threading.Event()
        self.events.append(event)
        return event

    def runner(self, pool: str = POOL_PREVIEW) -> tuple[TaskRunner, list, list]:
        runner = TaskRunner(self.owner, pool=pool)
        finished, failed = [], []
        runner.finished.connect(finished.append)
        runner.failed.connect(failed.append)
        return runner, finished, failed

    def wait(self, predicate, message: str) -> None:
        self.assertTrue(_qt.wait_until(predicate, TIMEOUT_MS), message)


class DeliveryTests(TaskCase):
    def test_result_reaches_the_ui_thread(self):
        runner, finished, failed = self.runner()
        threads = []

        def work(ctx):
            threads.append(QThread.currentThread())
            return 42

        runner.finished.connect(lambda _: threads.append(QThread.currentThread()))
        runner.start(work)
        self.assertTrue(runner.is_busy())
        self.wait(lambda: finished, "la tarea no entregó su resultado")
        self.assertEqual((finished, failed), ([42], []))
        self.assertFalse(runner.is_busy())
        self.assertIsNot(threads[0], APP.thread())
        self.assertIs(threads[1], APP.thread())

    def test_exception_is_delivered_as_failure(self):
        runner, finished, failed = self.runner()

        def work(ctx):
            raise ValueError("dato roto")

        with self.assertLogs("vic2studio.ui.tasks", "WARNING") as logs:
            runner.start(work)
            self.wait(lambda: failed, "el fallo no llegó a la interfaz")
        self.assertEqual(finished, [])
        self.assertIsInstance(failed[0], TaskFailure)
        self.assertIsInstance(failed[0].exception, ValueError)
        self.assertEqual(str(failed[0]), "ValueError: dato roto")
        self.assertIn("dato roto", failed[0].traceback)
        self.assertIn("ValueError", logs.output[0])
        self.assertFalse(runner.is_busy())

    def test_progress_is_throttled_but_forced_reports_arrive(self):
        runner, finished, _ = self.runner()
        progress = []
        runner.progress.connect(progress.append)

        def work(ctx):
            for i in range(1000):
                ctx.report(i)
            ctx.report("fin", force=True)
            return True

        runner.start(work)
        self.wait(lambda: finished, "la tarea no terminó")
        _qt.process_events()
        self.assertEqual(progress[0], 0)
        self.assertEqual(progress[-1], "fin")
        self.assertLess(len(progress), 100, "el progreso debe limitarse en frecuencia")


class CancellationTests(TaskCase):
    def test_late_result_of_a_cancelled_task_is_ignored(self):
        runner, finished, failed = self.runner()
        release = self.event()
        runner.start(lambda ctx: release.wait(TIMEOUT_MS / 1000) and "viejo")
        runner.cancel()
        self.assertFalse(runner.is_busy())
        release.set()
        self.assertTrue(wait_for_tasks(TIMEOUT_MS))
        _qt.process_events(50)
        self.assertEqual((finished, failed), ([], []))

    def test_starting_again_discards_the_previous_generation(self):
        runner, finished, _ = self.runner()
        release = self.event()
        first = runner.start(lambda ctx: release.wait(TIMEOUT_MS / 1000) and "viejo")
        second = runner.start(lambda ctx: "nuevo")
        self.assertGreater(second, first)
        release.set()
        self.wait(lambda: finished, "la tarea nueva no terminó")
        self.assertTrue(wait_for_tasks(TIMEOUT_MS))
        _qt.process_events(50)
        self.assertEqual(finished, ["nuevo"])

    def test_cooperative_cancellation_ends_quietly(self):
        runner, finished, failed = self.runner()
        started, stopped = self.event(), self.event()

        def work(ctx):
            started.set()
            while not ctx.cancelled():
                time.sleep(0.001)
            stopped.set()
            raise Cancelled()

        runner.start(work)
        self.assertTrue(started.wait(TIMEOUT_MS / 1000))
        runner.cancel()
        self.assertTrue(stopped.wait(TIMEOUT_MS / 1000), "la tarea no vio la cancelación")
        self.assertTrue(wait_for_tasks(TIMEOUT_MS))
        _qt.process_events(50)
        self.assertEqual((finished, failed), ([], []))

    def test_cancelled_task_waiting_in_the_queue_never_runs(self):
        busy, _, _ = self.runner(POOL_VALIDATION)  # el grupo de validación tiene un solo hilo
        release = self.event()
        busy.start(lambda ctx: release.wait(TIMEOUT_MS / 1000))
        runner, finished, _ = self.runner(POOL_VALIDATION)
        ran = []
        runner.start(lambda ctx: ran.append("cancelada"))
        runner.start(lambda ctx: ran.append("vigente") or "vigente")
        release.set()
        self.wait(lambda: finished, "la tarea vigente no terminó")
        self.assertEqual(ran, ["vigente"])

    def test_work_in_one_pool_does_not_block_the_others(self):
        """Validaciones largas, o que tardan en cancelarse, no dejan en cola a las vistas previas (CP-9, VAL-4)."""
        release = self.event()
        for _ in range(4):  # tantas como hilos tenía el grupo global que compartían todas
            stuck, _, _ = self.runner(POOL_VALIDATION)
            stuck.start(lambda ctx: release.wait(TIMEOUT_MS / 1000))  # ignora la cancelación
        image, image_done, _ = self.runner(POOL_IMAGES)
        preview, preview_done, _ = self.runner(POOL_PREVIEW)
        clock = time.perf_counter()
        image.start(lambda ctx: "imagen")
        preview.start(lambda ctx: "vista previa")
        self.assertTrue(_qt.wait_until(lambda: image_done and preview_done, 3000),
                        "las otras tareas quedaron en cola tras la validación")
        self.assertLess(time.perf_counter() - clock, 2.0)
        self.assertEqual(thread_pool(POOL_VALIDATION).activeThreadCount(), 1)

    def test_cancel_all_reaches_every_runner(self):
        runners = [self.runner(pool)[0] for pool in (POOL_PREVIEW, POOL_IMAGES, POOL_VALIDATION)]
        seen = []

        def work(ctx, entered):
            entered.set()
            while not ctx.cancelled():
                time.sleep(0.001)
            seen.append(True)
            raise Cancelled()

        for runner in runners:
            entered = self.event()
            runner.start(lambda ctx, entered=entered: work(ctx, entered))
            self.assertTrue(entered.wait(TIMEOUT_MS / 1000))
        cancel_all()
        self.assertFalse(any(runner.is_busy() for runner in runners))
        self.assertTrue(wait_for_tasks(TIMEOUT_MS))
        self.assertEqual(len(seen), 3)


class Qt65Pool:
    """Grupo de hilos como en Qt 6.5-6.7 (el mínimo declarado): ``waitForDone`` solo admite milisegundos."""

    def __init__(self, pool):
        self._pool = pool

    def waitForDone(self, msecs: int = -1) -> bool:
        if type(msecs) is not int:
            raise TypeError(f"waitForDone(int msecs = -1): no admite {type(msecs).__name__}")
        return self._pool.waitForDone(msecs)


class WaitTests(TaskCase):
    def test_wait_only_needs_what_qt_6_5_offers(self):
        """REG-1: ``waitForDone(QDeadlineTimer)`` llegó con Qt 6.8 y el proyecto admite PySide6 >= 6.5."""
        stuck, _, _ = self.runner(POOL_VALIDATION)
        release = self.event()
        stuck.start(lambda ctx: release.wait(TIMEOUT_MS / 1000))  # ignora la cancelación
        pools = {name: Qt65Pool(thread_pool(name)) for name in (POOL_PREVIEW, POOL_IMAGES, POOL_VALIDATION)}
        with mock.patch.dict(tasks._pools, pools):
            clock = time.perf_counter()
            self.assertFalse(wait_for_tasks(300), "la tarea sigue en marcha: debe vencer el plazo")
            self.assertGreaterEqual(time.perf_counter() - clock, 0.25)
            release.set()
            self.assertTrue(wait_for_tasks(), "sin límite espera a que termine")
        self.assertEqual(thread_pool(POOL_VALIDATION).activeThreadCount(), 0)


class LifetimeTests(TaskCase):
    def test_owner_destroyed_mid_task(self):
        parent = QObject()
        runner = TaskRunner(parent)
        delivered = []
        runner.finished.connect(delivered.append)
        release = self.event()
        runner.start(lambda ctx: release.wait(TIMEOUT_MS / 1000) and "tarde")
        delete(parent)
        release.set()
        self.assertTrue(wait_for_tasks(TIMEOUT_MS))
        _qt.process_events(50)
        self.assertEqual(delivered, [])

    def test_delivery_after_the_dispatcher_is_destroyed_does_not_raise(self):
        """Al cerrar la aplicación el despachador se destruye con tareas en marcha (CP-8, VAL-1)."""
        original = tasks._dispatcher
        tasks._dispatcher = tasks._Dispatcher()
        try:
            runner = TaskRunner(self.owner)
            for kind in ("resultado", "fallo"):
                release = self.event()

                def work(ctx, release=release, kind=kind):
                    release.wait(TIMEOUT_MS / 1000)
                    ctx.report("progreso", force=True)
                    if kind == "fallo":
                        raise ValueError(kind)
                    return kind

                runner.start(work)
            delete(tasks._dispatcher)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                for event in self.events:
                    event.set()
                self.assertTrue(wait_for_tasks(TIMEOUT_MS))
            self.assertNotIn("RuntimeError", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())
        finally:
            tasks._dispatcher = original


class GarbageCollectorTests(TaskCase):
    def test_collector_is_paused_while_any_task_runs(self):
        first_in, second_in = self.event(), self.event()
        release_first, release_second = self.event(), self.event()
        states = {}

        def work(name, entered, release):
            def fn(ctx):
                entered.set()
                states[name] = gc.isenabled()
                release.wait(TIMEOUT_MS / 1000)
            return fn

        a, a_done, _ = self.runner(POOL_PREVIEW)
        b, b_done, _ = self.runner(POOL_IMAGES)
        a.start(work("a", first_in, release_first))
        self.assertTrue(first_in.wait(TIMEOUT_MS / 1000))
        b.start(work("b", second_in, release_second))
        self.assertTrue(second_in.wait(TIMEOUT_MS / 1000))
        self.assertFalse(gc.isenabled())
        release_first.set()
        self.wait(lambda: a_done, "la primera tarea no terminó")
        self.assertFalse(gc.isenabled(), "otra tarea sigue en marcha: el recolector debe seguir parado")
        release_second.set()
        self.wait(lambda: b_done, "la segunda tarea no terminó")
        self.assertEqual(states, {"a": False, "b": False})
        self.assertTrue(gc.isenabled())

    def test_large_results_are_frozen_and_still_freed(self):
        """Sin fugas: lo congelado que se suelta sale de la generación permanente."""
        gc.collect()
        gc.freeze()  # lo que ya vivía no cuenta
        baseline = gc.get_freeze_count()
        runner, finished, _ = self.runner()
        for _ in range(3):
            finished.clear()
            runner.start(lambda ctx: Result([i] for i in range(2 * GC_FREEZE_MIN_OBJECTS)))
            self.wait(lambda: finished, "la tarea no terminó")
            self.assertGreaterEqual(gc.get_freeze_count(), baseline + 2 * GC_FREEZE_MIN_OBJECTS)
            finished.clear()  # el resultado se suelta: el recuento de referencias lo libera
            self.assertLess(gc.get_freeze_count(), baseline + GC_FREEZE_MIN_OBJECTS / 10)
        gc.unfreeze()
        self.assertLess(gc.collect(), 1000, "basura con ciclos atrapada en la generación permanente")

    def test_garbage_frozen_with_a_large_result_is_collected_once_it_is_released(self):
        """VIEW-NF-2: congelar apartaba también la basura cíclica pendiente, y para siempre."""
        gc.collect()
        gc.unfreeze()
        freed, entered, release = [], self.event(), self.event()
        make_cycle(freed, "antes")  # pendiente al empezar la tarea

        def work(ctx):
            make_cycle(freed, "en la tarea")
            entered.set()
            release.wait(TIMEOUT_MS / 1000)
            return Result([i] for i in range(2 * GC_FREEZE_MIN_OBJECTS))

        runner, finished, _ = self.runner()
        runner.start(work)
        self.assertTrue(entered.wait(TIMEOUT_MS / 1000))
        make_cycle(freed, "en la interfaz")  # el recolector está parado: no la recoge nadie
        release.set()
        self.wait(lambda: finished, "la tarea no terminó")
        gc.collect()
        self.assertGreaterEqual(gc.get_freeze_count(), 2 * GC_FREEZE_MIN_OBJECTS,
                                "el resultado vivo debe seguir fuera del alcance de las pasadas")
        finished.clear()  # quien lo recibió lo suelta
        gc.collect()
        self.assertEqual(sorted(freed), ["antes", "en la interfaz", "en la tarea"])
        self.assertEqual(gc.get_freeze_count(), 0)

    def test_nothing_is_thawed_while_another_frozen_result_lives(self):
        gc.unfreeze()
        runner, finished, _ = self.runner()
        for _ in range(2):
            runner.start(lambda ctx: Result([i] for i in range(2 * GC_FREEZE_MIN_OBJECTS)))
            self.wait(lambda n=len(finished) + 1: len(finished) == n, "la tarea no terminó")
        first, second = finished
        finished.clear()
        del first
        self.assertGreaterEqual(gc.get_freeze_count(), 2 * GC_FREEZE_MIN_OBJECTS, "el segundo sigue vivo")
        del second
        self.assertEqual(gc.get_freeze_count(), 0)

    def test_results_that_cannot_be_watched_are_not_left_frozen(self):
        """Una lista no admite referencias débiles: pasa a la generación más vieja sin recorrerla."""
        gc.collect()
        gc.unfreeze()
        freed = []
        make_cycle(freed, "antes")
        runner, finished, _ = self.runner()
        runner.start(lambda ctx: [[i] for i in range(2 * GC_FREEZE_MIN_OBJECTS)])
        self.wait(lambda: finished, "la tarea no terminó")
        self.assertEqual(gc.get_freeze_count(), 0)
        result = finished[0]
        self.assertTrue(any(obj is result for obj in gc.get_objects(generation=2)),
                        "una pasada de la generación joven recorrió el resultado")
        del result
        gc.collect()
        self.assertEqual(freed, ["antes"])

    def test_a_failed_task_keeps_nothing_alive_and_never_blocks_thawing(self):
        """R1: la traza de un fallo apunta al marco que guarda el propio fallo (un ciclo) y retiene los
        locales de la tarea. Congelado así, no moría nunca: ya no se descongelaba nada en toda la sesión."""
        gc.collect()
        gc.unfreeze()
        freed, partial = [], []
        make_cycle(freed, "antes")

        def fail(ctx):
            result = Result([i] for i in range(2 * GC_FREEZE_MIN_OBJECTS))
            partial.append(weakref.ref(result))
            try:
                {}["clave"]
            except KeyError:  # encadenada: su traza también apunta a este marco
                raise ValueError("fallo interno")

        runner, finished, failed = self.runner()
        with self.assertLogs("vic2studio.ui.tasks", "WARNING"):
            runner.start(fail)
            self.wait(lambda: failed, "el fallo no llegó a la interfaz")
        self.assertIn("fallo interno", failed[0].traceback)
        self.assertIn("in fail", failed[0].traceback, "la traza formateada se conserva")
        self.assertIn("KeyError", failed[0].traceback)
        error = failed[0].exception  # el visor guarda la excepción para explicarla
        self.assertIsNone(partial[0](), "la excepción retiene lo que la tarea tenía a medias")
        failure = weakref.ref(failed.pop())
        self.assertIsNone(failure(), "el fallo forma un ciclo: congelado, no moriría nunca")
        gc.collect()
        self.assertEqual(freed, ["antes"])
        make_cycle(freed, "después")
        runner.start(lambda ctx: Result([i] for i in range(2 * GC_FREEZE_MIN_OBJECTS)))
        self.wait(lambda: finished, "la tarea no terminó")
        self.assertGreaterEqual(gc.get_freeze_count(), 2 * GC_FREEZE_MIN_OBJECTS)
        finished.clear()
        self.assertEqual(gc.get_freeze_count(), 0, "algo vigilado sigue sin morir")
        gc.collect()
        self.assertEqual(freed, ["antes", "después"])
        self.assertEqual(str(error), "fallo interno")

    def test_garbage_frozen_with_a_chain_of_large_results_waits_for_the_last_one(self):
        """R2: cada resultado grande llega ya congelado, antes de que se suelte el anterior; lo congelado con
        el primero espera a que no viva ninguno, pero no se queda para siempre."""
        gc.collect()
        gc.unfreeze()
        freed = []
        runner, finished, _ = self.runner()

        def work(entered, release):
            def fn(ctx):
                entered.set()
                release.wait(TIMEOUT_MS / 1000)
                return Result([i] for i in range(2 * GC_FREEZE_MIN_OBJECTS))
            return fn

        for tag in ("con el primero", "con el segundo"):
            entered, release = self.event(), self.event()
            runner.start(work(entered, release))
            self.assertTrue(entered.wait(TIMEOUT_MS / 1000))
            make_cycle(freed, tag)  # con el recolector parado: se congela con el resultado
            release.set()
            self.wait(lambda: finished, "la tarea no terminó")
            current = finished.pop()  # como el visor: el nuevo sustituye al anterior
        gc.collect()
        self.assertEqual(freed, [], "recogerla con el segundo vivo obligaría a recorrerlo")
        self.assertGreaterEqual(gc.get_freeze_count(), 2 * GC_FREEZE_MIN_OBJECTS)
        del current
        self.assertEqual(gc.get_freeze_count(), 0)
        gc.collect()
        self.assertEqual(sorted(freed), ["con el primero", "con el segundo"])

    def test_results_of_the_application_tasks_die_by_reference_counting(self):
        """Congelado, un resultado solo muere por recuento de referencias: uno que formara un ciclo no moriría
        nunca y ya no se descongelaría nada. Ninguno de los que entregan las tareas de la aplicación lo forma."""
        from PySide6.QtGui import QFont

        from vic2studio.ui.viewers.clausewitz_viewer import ClausewitzFailure, ClausewitzLoad, try_load_clausewitz
        from vic2studio.ui.viewers.code_view import build_document
        from vic2studio.ui.viewers.image_viewer import ImageFailure, ImageLoad, try_load_image
        from vic2studio.ui.viewers.localisation_editor import (
            LocalisationFailure,
            LocalisationLoad,
            try_load_localisation,
        )
        from vic2studio.ui.viewers.validation_panel import ValidationResult, validate

        mod = Path(tempfile.mkdtemp(prefix="vic2studio-tasks-"))
        self.addCleanup(shutil.rmtree, mod, True)
        script = mod / "common" / "a.txt"
        script.parent.mkdir()
        script.write_bytes(b"a = {\n\tb = 1\n")  # sin cerrar: con diagnósticos y marcas
        csv = mod / "localisation" / "a.csv"
        csv.parent.mkdir()
        csv.write_bytes("CLAVE;Texto;;;;;;;;;;;;x\nOTRA;sin x\n".encode("cp1252"))
        image = mod / "gfx" / "a.png"
        image.parent.mkdir()
        from PIL import Image

        Image.new("RGB", (4, 3)).save(image)
        missing = mod / "no_existe.txt"
        font = QFont()

        def make_document(text, cancelled=None):
            return build_document(text, font, 32.0, cancelled)

        producers = {
            "Clausewitz": (lambda: try_load_clausewitz(script, make_document), ClausewitzLoad),
            "Clausewitz sin leer": (lambda: try_load_clausewitz(missing, make_document), ClausewitzFailure),
            "imagen": (lambda: try_load_image(image), ImageLoad),
            "imagen sin leer": (lambda: try_load_image(missing), ImageFailure),
            "localización": (lambda: try_load_localisation(csv), LocalisationLoad),
            "localización sin leer": (lambda: try_load_localisation(missing), LocalisationFailure),
            "validación": (lambda: validate(mod), ValidationResult),
        }
        enabled = gc.isenabled()
        gc.disable()  # que nada lo libere salvo el recuento de referencias
        try:
            for name, (produce, kind) in producers.items():
                result = produce()
                self.assertIsInstance(result, kind, name)
                if name == "Clausewitz":
                    self.assertTrue(result.rows and result.markers and result.document is not None)
                if name == "validación":
                    self.assertTrue(result.rows)
                released = weakref.ref(result)
                del result
                self.assertIsNone(released(), f"{name}: el resultado forma parte de un ciclo")
        finally:
            if enabled:
                gc.enable()

    def test_small_results_are_not_frozen(self):
        gc.unfreeze()
        runner, finished, _ = self.runner()
        runner.start(lambda ctx: [[i] for i in range(100)])
        self.wait(lambda: finished, "la tarea no terminó")
        self.assertEqual(gc.get_freeze_count(), 0)

    def test_parsing_large_files_does_not_freeze_the_interface(self):
        """Las pasadas del recolector con millones de nodos vivos congelaban la interfaz (CP-3, VAL-6).

        Como en el visor, el árbol del primer archivo sigue vivo mientras se analiza el siguiente.
        """
        from vic2studio.ui.viewers.clausewitz_viewer import load_clausewitz

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big_events.txt"
            path.write_text("".join(
                f"country_event = {{\n\tid = {n}\n\ttitle = EVT_{n}_NAME\n\toption = {{\n\t\tname = EVT_{n}_A\n"
                f"\t\tprestige = {n % 7}\n\t\tadd_core = {n % 3000}\n\t}}\n}}\n" for n in range(32_000)),
                encoding="cp1252")
            runner, finished, failed = self.runner()
            gaps = []
            clock = QElapsedTimer()
            heartbeat = QTimer()
            heartbeat.setInterval(5)
            heartbeat.timeout.connect(lambda: gaps.append(clock.restart()))
            clock.start()
            heartbeat.start()
            for count in (1, 2):
                runner.start(lambda ctx: load_clausewitz(path))
                self.wait(lambda count=count: len(finished) + len(failed) == count, "el análisis no terminó")
            heartbeat.stop()
            self.assertEqual((len(finished), failed), (2, []))
            print(f"\n[tasks] 2 × {path.stat().st_size / 1e6:.1f} MB ({len(finished[0].index)} nodos cada uno): "
                  f"mayor hueco del hilo de la interfaz {max(gaps)} ms", file=sys.stderr)
            self.assertLess(max(gaps), STALL_LIMIT_MS, "la interfaz se congeló durante el análisis")
            finished.clear()


SHUTDOWN_SCRIPT = textwrap.dedent('''
    import os, sys, threading, time
    sys.path.insert(0, {src!r})
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["VIC2STUDIO_SETTINGS_DIR"] = {settings!r}
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from vic2studio import app as appmod
    from vic2studio.ui.main_window import MainWindow
    from vic2studio.ui.tasks import TaskRunner
    qapp = appmod.create_application([])
    started, done = threading.Event(), threading.Event()

    def work(ctx):  # no consulta la cancelación: como un análisis largo de una biblioteca
        started.set()
        time.sleep({work_seconds})
        done.set()
        return "hecho"

    def begin():
        window = next(w for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow))
        global runner
        runner = TaskRunner(window)
        runner.start(work)
        started.wait(5)
        clock = time.perf_counter()
        window.close()
        print(f"close {{time.perf_counter() - clock:.3f}}", flush=True)

    QTimer.singleShot(100, begin)
    if {use_main}:
        code = appmod.main([])
    else:
        window = MainWindow()
        window.show()
        code = qapp.exec()
    print("tarea", "terminada" if done.is_set() else "en marcha", flush=True)
    print("exit", code, flush=True)
    sys.exit(code)
''')


class ShutdownTests(unittest.TestCase):
    """Cerrar la ventana con una tarea larga en marcha, en un proceso aparte (CP-8, VAL-1)."""

    def run_app(self, use_main: bool, work_seconds: float = 1.5) -> tuple[subprocess.CompletedProcess, float]:
        with tempfile.TemporaryDirectory() as tmp:
            script = SHUTDOWN_SCRIPT.format(src=str(ROOT / "src"), settings=tmp, work_seconds=work_seconds,
                                            use_main=use_main)
            clock = time.perf_counter()
            result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120,
                                    env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
            return result, time.perf_counter() - clock

    def closing_time(self, result: subprocess.CompletedProcess) -> float:
        line = next(line for line in result.stdout.splitlines() if line.startswith("close "))
        return float(line.split()[1])

    def test_main_closes_at_once_and_waits_for_the_task_before_exiting(self):
        result, elapsed = self.run_app(use_main=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(self.closing_time(result), 0.5, "cerrar la ventana no debe esperar a las tareas")
        self.assertIn("tarea terminada\nexit 0", result.stdout, "main() debe volver con la tarea ya terminada")
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("Error calling Python override", result.stderr)
        self.assertLess(elapsed, 60)

    def test_exit_with_a_task_still_running_does_not_print_errors(self):
        """Sin app.main la tarea termina con el intérprete ya cerrándose: la entrega no debe fallar."""
        result, _ = self.run_app(use_main=False, work_seconds=2.0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(self.closing_time(result), 0.5)
        self.assertIn("tarea en marcha", result.stdout)
        self.assertNotIn("Signal source has been deleted", result.stderr)
        self.assertNotIn("Error calling Python override", result.stderr)


if __name__ == "__main__":
    unittest.main()
