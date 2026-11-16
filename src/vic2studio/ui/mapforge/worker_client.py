"""Adaptador del proceso trabajador del taller a las señales de Qt (wizard §18.7).

``ForgeClient`` envía ``ForgeCommand`` a ``ForgeWorker`` y reemite en el hilo de la interfaz:
``progress(paso, i, n)``, ``finished(etiqueta, ForgeReply)``, ``failed(etiqueta, error)`` y ``cancelled(etiqueta)``.
Un ``QTimer`` recoge los ``Future`` terminados y el progreso (que el hilo lector deja en una cola), así ninguna
señal sale de otro hilo.

``inline=True`` ejecuta los comandos en este proceso, en el siguiente giro del bucle de eventos (pruebas de la
interfaz y capturas: sin procesos ni esperas).
"""

from __future__ import annotations

import queue

from PySide6.QtCore import QObject, QTimer, Signal

from ...core.cancel import Cancelled
from ...core.mapforge.worker import ForgeCommand, ForgeWorker, execute

POLL_MS = 40


class ForgeClient(QObject):
    progress = Signal(str, int, int)
    finished = Signal(str, object)
    failed = Signal(str, str)
    cancelled = Signal(str)
    busyChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None, *, inline: bool = False) -> None:
        super().__init__(parent)
        self.inline = inline
        self._worker: ForgeWorker | None = None
        self._progress: queue.SimpleQueue = queue.SimpleQueue()
        self._pending: list[tuple[str, object]] = []
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._inline_cancel = False

    @property
    def busy(self) -> bool:
        return bool(self._pending)

    def run(self, tag: str, cmd: ForgeCommand) -> None:
        was = self.busy
        if self.inline:
            self._inline_cancel = False
            self._pending.append((tag, None))
            QTimer.singleShot(0, lambda: self._run_inline(tag, cmd))
        else:
            if self._worker is None:
                self._worker = ForgeWorker(on_progress=lambda job, name, i, n: self._progress.put((name, i, n)))
            self._pending.append((tag, self._worker.submit(cmd)))
            self._timer.start()
        if not was:
            self.busyChanged.emit(True)

    def _run_inline(self, tag: str, cmd: ForgeCommand) -> None:
        entry = next((e for e in self._pending if e[0] == tag and e[1] is None), None)
        if entry is None:
            return
        self._pending.remove(entry)
        try:
            reply = execute(cmd, lambda name, i, n: self.progress.emit(str(name), int(i), int(n)),
                            lambda: self._inline_cancel)
        except Cancelled:
            self.cancelled.emit(tag)
        except Exception as exc:   # noqa: BLE001 — se enseña en la interfaz
            self.failed.emit(tag, f"{type(exc).__name__}: {exc}")
        else:
            self.finished.emit(tag, reply)
        if not self.busy:
            self.busyChanged.emit(False)

    def cancel(self) -> None:
        if self.inline:
            self._inline_cancel = True
            for tag, _ in list(self._pending):
                self.cancelled.emit(tag)
            self._pending.clear()
            self.busyChanged.emit(False)
            return
        if self._worker is not None:
            self._worker.cancel()
        self._poll()

    def _poll(self) -> None:
        while True:
            try:
                name, i, n = self._progress.get_nowait()
            except queue.Empty:
                break
            self.progress.emit(name, i, n)
        done = [(t, f) for t, f in self._pending if f is not None and f.done()]
        for tag, fut in done:
            self._pending.remove((tag, fut))
            exc = fut.exception() if not fut.cancelled() else Cancelled()
            if isinstance(exc, Cancelled):
                self.cancelled.emit(tag)
            elif exc is not None:
                self.failed.emit(tag, str(exc).strip().splitlines()[-1] if str(exc).strip() else repr(exc))
            else:
                self.finished.emit(tag, fut.result())
        if not self._pending:
            self._timer.stop()
            if done:
                self.busyChanged.emit(False)

    def close(self) -> None:
        self._timer.stop()
        self._pending.clear()
        if self._worker is not None:
            self._worker.close()
            self._worker = None


__all__ = ["ForgeClient", "ForgeCommand"]
