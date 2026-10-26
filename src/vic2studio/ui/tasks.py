"""Tareas en segundo plano (``QThreadPool``) que devuelven su resultado al hilo de la interfaz.

La función de una tarea corre en un hilo del pool y nunca toca widgets: recibe
un ``TaskContext`` para consultar la cancelación y notificar progreso. Sus
resultados viajan por un único despachador que vive toda la aplicación, de modo
que un widget destruido a mitad de tarea no deja señales huérfanas: la entrega
usa una referencia débil y se descarta si el destinatario ya no existe.

``TaskRunner`` mantiene una sola tarea vigente: lanzar otra cancela la anterior
y los resultados que lleguen tarde de ella se ignoran (número de generación).

Las tareas son Python puro y compiten por el GIL con el hilo de la interfaz, que
lo necesita en cada ``paintEvent`` escrito en Python. Con el intervalo de cambio
por defecto (5 ms) un repintado completo esperaba ~100 ms mientras corría una
tarea; con 0,5 ms la espera baja a ~25 ms sin que las tareas tarden más (medido
con la validación del mod del usuario y con ``text.csv``).
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
import weakref
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from shiboken6 import isValid

log = logging.getLogger(__name__)

PROGRESS_INTERVAL = 0.04  # segundos entre notificaciones de progreso
UI_SWITCH_INTERVAL = 0.0005  # segundos: cada cuánto cede el GIL un hilo de Python ocupado

_FINISHED, _FAILED, _PROGRESS = "finished", "failed", "progress"


class _Dispatcher(QObject):
    """Recibe en el hilo de la interfaz lo que emiten los hilos del pool."""

    delivered = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.delivered.connect(self._deliver)

    @Slot(object, object)
    def _deliver(self, target, payload) -> None:
        runner = target()
        if runner is not None and isValid(runner):
            runner._receive(payload)


_dispatcher: _Dispatcher | None = None


def _get_dispatcher() -> _Dispatcher:
    # Se crea en el hilo de la interfaz: el primer TaskRunner se construye siempre ahí.
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = _Dispatcher()
        if sys.getswitchinterval() > UI_SWITCH_INTERVAL:
            sys.setswitchinterval(UI_SWITCH_INTERVAL)
    return _dispatcher


class TaskFailure:
    """Excepción de una tarea con su traza ya formateada (las trazas no cruzan bien hilos)."""

    def __init__(self, exc: BaseException):
        self.exception = exc
        self.traceback = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    def __str__(self) -> str:
        return f"{type(self.exception).__name__}: {self.exception}"


class TaskContext:
    """Lo que ve la función de la tarea: cancelación y progreso (limitado en frecuencia)."""

    __slots__ = ("_cancel", "_emit", "_last")

    def __init__(self, cancel: threading.Event, emit: Callable[[Any], None]):
        self._cancel = cancel
        self._emit = emit
        self._last = 0.0

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def report(self, value: Any, *, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last >= PROGRESS_INTERVAL:
            self._last = now
            self._emit(value)


class _Job(QRunnable):
    def __init__(self, fn: Callable[[TaskContext], Any], context: TaskContext, deliver: Callable[[str, Any], None]):
        super().__init__()
        self.fn = fn
        self.context = context
        self.deliver = deliver

    def run(self) -> None:
        try:
            result = self.fn(self.context)
        except BaseException as exc:  # noqa: BLE001 - toda excepción se entrega a la interfaz
            self.deliver(_FAILED, TaskFailure(exc))
        else:
            self.deliver(_FINISHED, result)


def thread_pool() -> QThreadPool:
    return QThreadPool.globalInstance()


class TaskRunner(QObject):
    """Ejecuta funciones en segundo plano; como mucho una vigente a la vez.

    ``finished(result)``, ``failed(TaskFailure)`` y ``progress(valor)`` se emiten
    en el hilo de la interfaz y solo para la tarea vigente.
    """

    finished = Signal(object)
    failed = Signal(object)
    progress = Signal(object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._dispatcher = _get_dispatcher()
        self._generation = 0
        self._cancel: threading.Event | None = None
        self._busy = False

    def start(self, fn: Callable[[TaskContext], Any]) -> int:
        """Lanza ``fn(context)`` en el pool y devuelve su número de generación."""
        self.cancel()
        self._generation += 1
        generation = self._generation
        cancel = threading.Event()
        self._cancel = cancel
        self._busy = True
        target = weakref.ref(self)
        emit = self._dispatcher.delivered.emit

        def deliver(kind: str, value: Any) -> None:
            emit(target, (generation, kind, value))

        context = TaskContext(cancel, lambda value: deliver(_PROGRESS, value))
        thread_pool().start(_Job(fn, context, deliver))
        return generation

    def cancel(self) -> None:
        """Pide a la tarea vigente que pare y descarta lo que entregue a partir de ahora."""
        if self._cancel is not None:
            self._cancel.set()
            self._cancel = None
        if self._busy:
            self._busy = False
            self._generation += 1

    def is_busy(self) -> bool:
        return self._busy

    def _receive(self, payload: tuple[int, str, Any]) -> None:
        generation, kind, value = payload
        if generation != self._generation:
            return
        if kind == _PROGRESS:
            self.progress.emit(value)
            return
        self._busy = False
        self._cancel = None
        if kind == _FINISHED:
            self.finished.emit(value)
        else:
            log.warning("tarea en segundo plano fallida:\n%s", value.traceback)
            self.failed.emit(value)
