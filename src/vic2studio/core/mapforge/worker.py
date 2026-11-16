"""Proceso trabajador del taller (wizard §18.4 y §18.7): ``multiprocessing`` con ``spawn``, persistente.

La generación final ocupa cientos de MiB y segundos de CPU: corre en otro proceso para que la interfaz no se
congele y para que la memoria vuelva al sistema al cerrar el taller. Un solo proceso, un trabajo cada vez (los
envíos se encolan en orden):

- ``submit(cmd)`` devuelve un ``Future`` con el ``ForgeReply``; el progreso llega por ``on_progress`` desde el hilo
  lector (quien lo use en Qt lo reenvía con una señal: ``ui/mapforge/worker_client.py``).
- ``cancel()`` pone un ``Event`` compartido que los pasos consultan (``cancelled``). Si el proceso no contesta en
  ``CANCEL_GRACE`` s, se termina (``terminate``) y se arranca otro: el trabajo falla con ``Cancelled``.
- ``close()`` termina el proceso.

Los comandos (``ForgeCommand``): ``run_all``, ``run_cells``, ``run_raster``, ``export_bytes``, ``import_bitmaps`` y
``learn_install``.
Todo lo que cruza (``ForgeWorld``, ``InstallProfile``, ``ExportInputs``, ``ImportSet``) es picklable. El proceso no
escribe en disco: los bytes de la exportación vuelven al proceso de la interfaz y los escribe el ``Workspace``.
"""

from __future__ import annotations

import itertools
import multiprocessing as mp
import threading
import time
import traceback
from concurrent.futures import Future
from dataclasses import dataclass, field

from ..cancel import Cancelled

CANCEL_GRACE = 2.0
COMMANDS = ("run_all", "run_cells", "run_raster", "export_bytes", "import_bitmaps", "learn_install", "ping")


@dataclass
class ForgeCommand:
    kind: str
    args: dict = field(default_factory=dict)


@dataclass
class ForgeReply:
    kind: str
    world: object = None
    files: dict | None = None
    report: object = None
    seconds: float = 0.0


class ForgeError(RuntimeError):
    """Un error dentro del trabajador (con su traza)."""


def _execute(cmd: ForgeCommand, progress, cancelled) -> ForgeReply:
    from . import export, pipeline

    a = cmd.args
    t0 = time.perf_counter()
    if cmd.kind == "ping":
        return ForgeReply("ping", report=a.get("value"))
    if cmd.kind == "learn_install":
        from .install import learn_install

        return ForgeReply("install", report=learn_install(a["source"]), seconds=time.perf_counter() - t0)
    if cmd.kind == "run_all":
        if a.get("heightmap") is not None:
            w = pipeline.new_world(a["params"], a.get("install"))
            w = w.evolve(imported={"heightmap": _imported_heights(w, a["heightmap"], a.get("north_up", True))})
            w = pipeline.run_cells(w, progress=progress, cancelled=cancelled)
            w = pipeline.run_raster(w, scale=a.get("scale", 1), progress=progress, cancelled=cancelled,
                                    with_textures=a.get("with_textures", True))
        else:
            w = pipeline.run_all(a["params"], a.get("install"), scale=a.get("scale", 1), progress=progress,
                                 cancelled=cancelled, with_textures=a.get("with_textures", True))
        return ForgeReply("world", world=w, seconds=time.perf_counter() - t0)
    if cmd.kind == "run_cells":
        w = pipeline.run_cells(a["world"], from_step=a.get("from_step"), until=a.get("until"), progress=progress,
                               cancelled=cancelled)
        return ForgeReply("world", world=w, seconds=time.perf_counter() - t0)
    if cmd.kind == "run_raster":
        w = pipeline.run_raster(a["world"], scale=a.get("scale", 1), progress=progress, cancelled=cancelled,
                                with_textures=a.get("with_textures", True))
        return ForgeReply("world", world=w, seconds=time.perf_counter() - t0)
    if cmd.kind == "export_bytes":
        files, report = export.render_files(a["world"], a["inputs"])
        return ForgeReply("files", files=files, report=report, seconds=time.perf_counter() - t0)
    if cmd.kind == "import_bitmaps":
        from .imports import bitmaps

        rep = bitmaps.inspect(a["files"], a.get("install"), cancelled=cancelled)
        w = None
        if a.get("build") and rep.ok:
            w = bitmaps.build_world(a["files"], rep, a["params"], a.get("install"), progress=progress,
                                    cancelled=cancelled)
        return ForgeReply("import", world=w, report=rep, seconds=time.perf_counter() - t0)
    raise ValueError(f"unknown command {cmd.kind}")


def _imported_heights(world, data: bytes, north_up: bool):
    """Altura por celda de los bytes de una imagen en gris (PNG con el norte arriba; BMP en el orden del juego)."""
    from .imports import heightmap as hm

    gray, _ = hm.load_gray(data)
    if north_up and data[:2] != b"BM":
        gray = gray[::-1]
    return hm.heights_from_image(gray, world.cells.pts, world.params.size)


def execute(cmd: ForgeCommand, progress=None, cancelled=None) -> ForgeReply:
    """Ejecuta un comando en este mismo proceso (pruebas de la interfaz y capturas)."""
    return _execute(cmd, progress, cancelled)


def _main(conn, cancel_event) -> None:
    """Bucle del proceso trabajador: ``(id, ForgeCommand)`` → ``("progress"|"done"|"cancelled"|"error", id, …)``."""
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return
        job, cmd = msg
        cancel_event.clear()

        def progress(name, i, n, _job=job):
            try:
                conn.send(("progress", _job, (str(name), int(i), int(n))))
            except (OSError, ValueError):
                pass

        try:
            reply = _execute(cmd, progress, cancel_event.is_set)
            conn.send(("done", job, reply))
        except Cancelled:
            conn.send(("cancelled", job, None))
        except Exception:   # noqa: BLE001 — la traza viaja a la interfaz
            conn.send(("error", job, traceback.format_exc()))


class ForgeWorker:
    """El proceso trabajador visto desde la interfaz."""

    def __init__(self, *, on_progress=None) -> None:
        self.on_progress = on_progress
        self._ctx = mp.get_context("spawn")
        self._proc = None
        self._conn = None
        self._event = None
        self._reader = None
        self._lock = threading.Lock()
        self._futures: dict[int, Future] = {}
        self._ids = itertools.count(1)
        self._current: int | None = None
        self._queue: list[tuple[int, ForgeCommand]] = []

    # --- ciclo de vida ------------------------------------------------------------------------------------

    def start(self) -> None:
        if self._proc is not None and self._proc.is_alive():
            return
        parent, child = self._ctx.Pipe()
        self._event = self._ctx.Event()
        self._proc = self._ctx.Process(target=_main, args=(child, self._event), daemon=True,
                                       name="vic2studio-mapforge")
        self._proc.start()
        child.close()
        self._conn = parent
        self._reader = threading.Thread(target=self._read, args=(parent, self._proc), daemon=True)
        self._reader.start()

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    def close(self) -> None:
        with self._lock:
            proc, conn = self._proc, self._conn
            self._proc = self._conn = None
            pending = list(self._futures.values())
            self._futures.clear()
            self._queue.clear()
            self._current = None
        for f in pending:
            f.cancel() or f.done() or f.set_exception(Cancelled())
        if conn is not None:
            try:
                conn.send(None)
            except (OSError, ValueError):
                pass
        if proc is not None:
            proc.join(1.0)
            if proc.is_alive():
                proc.terminate()
                proc.join(1.0)
        if conn is not None:
            conn.close()

    # --- trabajos -----------------------------------------------------------------------------------------

    def submit(self, cmd: ForgeCommand) -> Future:
        if cmd.kind not in COMMANDS:
            raise ValueError(cmd.kind)
        self.start()
        fut: Future = Future()
        with self._lock:
            job = next(self._ids)
            self._futures[job] = fut
            self._queue.append((job, cmd))
            self._pump()
        return fut

    def _pump(self) -> None:
        """Envía el siguiente trabajo si no hay ninguno en curso (con el cerrojo tomado)."""
        if self._current is not None or not self._queue or self._conn is None:
            return
        job, cmd = self._queue.pop(0)
        self._current = job
        try:
            self._conn.send((job, cmd))
        except Exception as exc:   # noqa: BLE001 — OSError, o algo que no se puede picklear
            self._current = None
            fut = self._futures.pop(job, None)
            if fut is not None:
                fut.set_exception(ForgeError(str(exc)))
            self._pump()

    def cancel(self) -> None:
        """Cancela el trabajo en curso y los encolados. Si el proceso no responde en ``CANCEL_GRACE`` s, se termina
        y se arranca otro."""
        with self._lock:
            queued = [self._futures.pop(j, None) for j, _ in self._queue]
            self._queue.clear()
            job = self._current
            event = self._event
        for f in queued:
            if f is not None and not f.done():
                f.set_exception(Cancelled())
        if job is None or event is None:
            return
        event.set()
        fut = self._futures.get(job)
        deadline = time.monotonic() + CANCEL_GRACE
        while fut is not None and not fut.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        if fut is not None and not fut.done():
            self._kill(job)

    def _kill(self, job: int) -> None:
        with self._lock:
            proc, conn = self._proc, self._conn
            self._proc = self._conn = None
            fut = self._futures.pop(job, None)
            self._current = None
            queue = list(self._queue)
            self._queue.clear()
        if proc is not None:
            proc.terminate()
            proc.join(2.0)
        if conn is not None:
            conn.close()
        if fut is not None and not fut.done():
            fut.set_exception(Cancelled())
        if queue:
            self.start()
            with self._lock:
                self._queue = queue
                self._pump()

    # --- hilo lector --------------------------------------------------------------------------------------

    def _read(self, conn, proc) -> None:
        while True:
            try:
                kind, job, payload = conn.recv()
            except (EOFError, OSError, TypeError, ValueError):
                break
            if kind == "progress":
                if self.on_progress is not None:
                    try:
                        self.on_progress(job, *payload)
                    except Exception:   # noqa: BLE001 — un fallo de la interfaz no tumba el lector
                        pass
                continue
            with self._lock:
                fut = self._futures.pop(job, None)
                if self._current == job:
                    self._current = None
                self._pump()
            if fut is None or fut.done():
                continue
            if kind == "done":
                fut.set_result(payload)
            elif kind == "cancelled":
                fut.set_exception(Cancelled())
            else:
                fut.set_exception(ForgeError(payload))
        # El proceso murió (o se cerró): los trabajos de este proceso fallan.
        with self._lock:
            if self._proc is not proc:
                return
            pending = [(j, f) for j, f in self._futures.items()]
            self._futures.clear()
            self._current = None
            self._queue.clear()
        for _, f in pending:
            if not f.done():
                f.set_exception(ForgeError("worker exited"))


__all__ = ["ForgeWorker", "ForgeCommand", "ForgeReply", "ForgeError", "CANCEL_GRACE", "execute"]
