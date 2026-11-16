"""Tareas en segundo plano (``QThreadPool``) que devuelven su resultado al hilo de la interfaz.

La función de una tarea corre en un hilo y nunca toca widgets: recibe un
``TaskContext`` para consultar la cancelación y notificar progreso. Sus
resultados viajan por un único despachador que vive toda la aplicación, de modo
que un widget destruido a mitad de tarea no deja señales huérfanas: la entrega
usa una referencia débil y se descarta si el destinatario ya no existe, o si el
propio despachador ya se destruyó porque la aplicación se está cerrando.

``TaskRunner`` mantiene una sola tarea vigente: lanzar otra cancela la anterior
y los resultados que lleguen tarde de ella se ignoran (número de generación).
Cancelar solo avisa: la tarea para cuando consulta ``TaskContext.cancelled``
(las funciones del núcleo lo hacen con ``cancelled=`` y lanzan
``core.cancel.Cancelled``), y una tarea cancelada que aún esperaba en la cola ni
siquiera empieza. Cada runner usa un grupo de hilos propio de su área
(``POOL_*``), para que el trabajo de una (o el que tarda en cancelarse) no deje
en cola al de las demás. Al salir, ``cancel_all`` y ``wait_for_tasks`` evitan que
quede algún hilo ejecutando Python mientras se cierra el intérprete.

Las tareas son Python puro y compiten por el GIL con el hilo de la interfaz, que
lo necesita en cada ``paintEvent`` escrito en Python. Con el intervalo de cambio
por defecto (5 ms) un repintado completo esperaba ~100 ms mientras corría una
tarea; con 0,5 ms la espera baja a ~25 ms sin que las tareas tarden más (medido
con la validación del mod del usuario y con ``text.csv``).

El intervalo no sirve con el recolector de basura: un archivo grande crea
millones de objetos, y cada pasada de la generación más vieja los recorre todos
con el GIL tomado (unos 2 s con 20 MB vivos). Por eso, mientras corre alguna
tarea, el recolector cíclico está parado; al terminar la última, si quedan muchos
objetos nuevos vivos (el resultado), ``gc.freeze()`` los aparta antes de
reactivarlo para que ninguna pasada vuelva a recorrerlos. Los árboles del parser
y del CSV no tienen ciclos: el recuento de referencias los libera igualmente.

Congelar aparta todo lo que el recolector sigue, también la basura cíclica que
aún no había recogido. Para que no quede inmortal, se vigilan con referencias
débiles los resultados entregados mientras estaba parado, y cuando ya no vive
ninguno ``gc.unfreeze()`` lo devuelve todo a la generación más vieja: la próxima
pasada solo recorre lo que sigue vivo, ya sin el archivo grande. Con varios
resultados grandes seguidos (el visor suelta uno al recibir el siguiente, que ya
llega congelado), la basura congelada con el primero espera a que no viva
ninguno: recogerla antes obligaría a recorrer el que vive (unos 2 s con 20 MB) o a
una pasada completa al empezar cada tarea (~20 ms con la ventana abierta). Por
eso quien recibe un resultado grande lo guarda entero mientras use sus partes, y
este módulo es el único que congela.

Congelado, un objeto solo muere por recuento de referencias: un resultado que
formara parte de un ciclo no moriría nunca, y ya no se descongelaría nada. Los
de la aplicación no los forman (las pruebas lo comprueban) y los fallos no se
vigilan; además ``TaskFailure`` suelta las trazas, que formaban uno con el marco
del hilo que guarda el fallo. Sin nada que vigilar (un resultado que no admite
referencias débiles, como una lista), se descongela en el acto: los objetos
pasan a la generación más vieja sin recorrerlos, pero la siguiente pasada
completa los recorrerá si siguen vivos. Lo que entrega una tarea solo lo retiene
quien lo recibe: viaja en una lista que se vacía al llegar, así que el hilo, aunque
aún no haya vuelto, no lo mantiene vivo (ni congelado) si la interfaz lo suelta.

Soltar un resultado grande también cuesta: el recuento de referencias libera el
árbol de 20 MB en una sola cascada en C (~0,9 s) que no suelta el GIL, así que
hacerlo en otro hilo tal cual pararía la interfaz igual. ``release_in_background``
lo suelta en el hilo de ``POOL_RELEASE`` con una función que lo desmonta por
trozos; entre trozo y trozo el hilo cede el GIL como cualquier otra tarea. Empieza
con un pequeño retraso (``RELEASE_DELAY``) para no competir con el repintado que
sigue al cambio (~30 ms de hueco con 5 MB en vez de 40–95 ms).
"""

from __future__ import annotations

import builtins
import gc
import logging
import sys
import threading
import time
import traceback
import weakref
from typing import Any, Callable, Iterable

from PySide6.QtCore import QDeadlineTimer, QObject, QRunnable, QThreadPool, Signal, Slot
from shiboken6 import isValid

from ..core.cancel import Cancelled

log = logging.getLogger(__name__)

PROGRESS_INTERVAL = 0.04  # segundos entre notificaciones de progreso
UI_SWITCH_INTERVAL = 0.0005  # segundos: cada cuánto cede el GIL un hilo de Python ocupado
# Objetos nuevos vivos al terminar las tareas a partir de los que se congelan (recorrerlos costaría >10 ms).
GC_FREEZE_MIN_OBJECTS = 100_000
# Segundos que espera una liberación antes de empezar: quien suelta algo grande acaba de cambiar lo que
# muestra y aún tiene que maquetarlo y pintarlo, y con otro hilo ocupado cada llamada a Python esperaría el GIL.
RELEASE_DELAY = 0.1

# Grupos de hilos: vistas previas y editores (scripts, JSON, CSV), imágenes, validación del mod,
# liberación de resultados grandes que ya no se usan (``release_in_background``) y el índice de símbolos
# (construcción y reextracción incremental, wizard §7). ``POOL_MAP`` (iteración 5): el ráster de provincias y los
# hechos del mapa, que tardan segundos la primera vez y no deben esperar al índice ni a la validación.
POOL_PREVIEW, POOL_IMAGES, POOL_VALIDATION, POOL_RELEASE = "preview", "images", "validation", "release"
POOL_INDEX = "index"
POOL_MAP = "map"
POOL_THREADS = {POOL_PREVIEW: 2, POOL_IMAGES: 1, POOL_VALIDATION: 1, POOL_RELEASE: 1, POOL_INDEX: 1, POOL_MAP: 1}

_FINISHED, _FAILED, _PROGRESS = "finished", "failed", "progress"
_STEPS_DONE = object()  # fin de los pasos de un ``dismantle`` (sus pasos dan None)


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
_pools: dict[str, QThreadPool] = {}
_runners: weakref.WeakSet[TaskRunner] = weakref.WeakSet()


def _get_dispatcher() -> _Dispatcher:
    # Se crea en el hilo de la interfaz: el primer TaskRunner se construye siempre ahí.
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = _Dispatcher()
        if sys.getswitchinterval() > UI_SWITCH_INTERVAL:
            sys.setswitchinterval(UI_SWITCH_INTERVAL)
    return _dispatcher


def thread_pool(name: str = POOL_PREVIEW) -> QThreadPool:
    """Grupo de hilos ``name`` (``POOL_*``), creado al pedirlo por primera vez."""
    pool = _pools.get(name)
    if pool is None:
        pool = QThreadPool()
        pool.setObjectName(f"vic2studio-{name}")
        pool.setMaxThreadCount(POOL_THREADS[name])
        _pools[name] = pool
    return pool


def cancel_all() -> None:
    """Cancela la tarea vigente de todos los runners que siguen vivos."""
    for runner in list(_runners):
        if isValid(runner):
            runner.cancel()


def wait_for_tasks(timeout_ms: int = -1) -> bool:
    """Espera a que no quede ninguna tarea en ningún grupo (-1: sin límite); ``False`` si vence el plazo.

    El plazo es uno para todos los grupos. Se pasa en milisegundos a
    ``waitForDone(int)``: la sobrecarga con ``QDeadlineTimer`` no existe antes de Qt 6.8.
    """
    deadline = QDeadlineTimer(timeout_ms)  # remainingTime(): -1 sin límite, 0 si ya venció
    return all(pool.waitForDone(deadline.remainingTime()) for pool in list(_pools.values()))


# --- recolector de basura -----------------------------------------------------------------
# Su estado es global del proceso: un contador reúne las tareas de todos los hilos.

_gc_lock = threading.RLock()  # reentrante: un resultado vigilado puede morir con el cerrojo tomado
_gc_tasks = 0
_gc_paused = False
_gc_delivered: list[weakref.ref] = []  # resultados de las tareas que terminaron con el recolector parado
_gc_watched: dict[int, weakref.ref] = {}  # resultados vivos congelados (por id de la referencia)
_gc_released = 0  # lo que release_in_background descontó del contador de la generación joven mientras estaba parado


def _pause_gc() -> None:
    global _gc_tasks, _gc_paused, _gc_released
    with _gc_lock:
        if _gc_tasks == 0 and gc.isenabled():
            gc.disable()
            _gc_paused = True
            _gc_released = 0
        _gc_tasks += 1


def _count_released(before: int) -> None:
    """Suma lo que soltar un trozo (``release_in_background``) descontó del contador de la generación joven."""
    global _gc_released
    dropped = before - gc.get_count()[0]
    if dropped > 0:
        with _gc_lock:
            _gc_released += dropped


def _resume_gc(result: Any = None) -> None:
    """Al terminar una tarea con su resultado (``None`` si falló o no lo hay)."""
    global _gc_tasks, _gc_paused
    with _gc_lock:
        _gc_tasks -= 1
        if _gc_paused and result is not None:
            try:
                _gc_delivered.append(weakref.ref(result, _on_result_released))
            except TypeError:
                pass  # no admite referencias débiles: no se puede vigilar
        if _gc_tasks == 0 and _gc_paused:
            _gc_paused = False
            # Sin congelarlos, la primera pasada tras reactivarlo recorrería todos los objetos nuevos de golpe. Lo que
            # suelta a la vez release_in_background descuenta del contador aunque no fuera nuevo: se le devuelve.
            # Nunca gc.get_objects() aquí: su lista retendría cada objeto joven, y si la interfaz suelta mientras uno
            # suyo (un QPainter, un QBrush), moriría en este hilo y dejaría corrupto el motor de pintado.
            young = gc.get_count()[0] + _gc_released
            if young >= GC_FREEZE_MIN_OBJECTS:
                gc.freeze()
                for ref in _gc_delivered:
                    if ref() is not None:
                        _gc_watched[id(ref)] = ref
                if not _gc_watched:
                    gc.unfreeze()  # nada que vigilar: a la generación más vieja, sin recorrerlos
            _gc_delivered.clear()
            gc.enable()


def _on_result_released(ref: weakref.ref, _lock=_gc_lock, _watched=_gc_watched, _unfreeze=gc.unfreeze) -> None:
    # Llega en el hilo que suelta el resultado, también al cerrar el intérprete: no usa globales del módulo.
    with _lock:
        if _watched.pop(id(ref), None) is not None and not _watched:
            _unfreeze()  # ya no vive ningún resultado congelado: la basura que se congeló con ellos se recoge


_EXCEPTION_GROUP = getattr(builtins, "BaseExceptionGroup", ())  # Python 3.11+


def _drop_tracebacks(exc: BaseException) -> None:
    """Quita la traza a ``exc`` y a las excepciones que encadena."""
    pending, seen = [exc], set()
    while pending:
        error = pending.pop()
        if error is None or id(error) in seen:
            continue
        seen.add(id(error))
        error.__traceback__ = None
        pending += [error.__cause__, error.__context__]
        if isinstance(error, _EXCEPTION_GROUP):
            pending += error.exceptions


class TaskFailure:
    """Excepción de una tarea con su traza ya formateada (las trazas no cruzan bien hilos).

    La excepción (y las que encadena) se queda sin traza: sus marcos retendrían los locales de la
    tarea, como un árbol a medio construir, y el de ``_Job.run``, que guarda este fallo: un ciclo
    que, congelado, no se liberaría nunca.
    """

    def __init__(self, exc: BaseException):
        self.exception = exc
        self.traceback = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        _drop_tracebacks(exc)

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
        """Se puede pasar tal cual como ``cancelled=`` a las funciones del núcleo."""
        return self._cancel.is_set()

    def report(self, value: Any, *, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last >= PROGRESS_INTERVAL:
            self._last = now
            self._emit(value)


class _Job(QRunnable):
    """Corre ``fn`` y entrega ``[(tipo, valor)]`` a ``deliver``: quien lo recibe saca el par de la lista."""

    def __init__(self, fn: Callable[[TaskContext], Any], context: TaskContext, deliver: Callable[[list], None]):
        super().__init__()
        self.fn = fn
        self.context = context
        self.deliver = deliver

    def run(self) -> None:
        if self.context.cancelled():
            return  # se canceló mientras esperaba en la cola
        _pause_gc()
        outcome = None
        try:
            outcome = _FINISHED, self.fn(self.context)
        except Cancelled:
            return  # quien canceló ya descartó esta generación
        except BaseException as exc:  # noqa: BLE001 - toda excepción se entrega a la interfaz
            outcome = _FAILED, TaskFailure(exc)
        finally:
            # Se vigila el resultado, nunca un fallo: no lleva nada que convenga mantener congelado.
            _resume_gc(outcome[1] if outcome is not None and outcome[0] == _FINISHED else None)
        # Va en una lista que vacía quien lo recibe: este hilo deja de retenerlo en cuanto llega, aunque aún
        # no haya vuelto de entregarlo, y si la interfaz lo suelta muere en el acto (y descongela lo demás).
        handoff = [outcome]
        del outcome
        self.deliver(handoff)


class TaskRunner(QObject):
    """Ejecuta funciones en segundo plano en el grupo ``pool``; como mucho una vigente a la vez.

    ``finished(result)``, ``failed(TaskFailure)`` y ``progress(valor)`` se emiten
    en el hilo de la interfaz y solo para la tarea vigente. ``discarded(result)``
    entrega el resultado de una tarea ya superada que terminó de todos modos, para
    que quien sepa desmontarlo lo suelte fuera del hilo de la interfaz (si nadie
    lo escucha, se suelta allí mismo, como antes).
    """

    finished = Signal(object)
    failed = Signal(object)
    progress = Signal(object)
    discarded = Signal(object)

    def __init__(self, parent: QObject | None = None, *, pool: str = POOL_PREVIEW):
        super().__init__(parent)
        self._dispatcher = _get_dispatcher()
        self._pool = thread_pool(pool)
        self._generation = 0
        self._cancel: threading.Event | None = None
        self._busy = False
        _runners.add(self)

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

        def deliver(handoff: list) -> None:
            try:
                emit(target, (generation, handoff))
            except RuntimeError:
                pass  # el despachador ya se destruyó: la aplicación se está cerrando

        context = TaskContext(cancel, lambda value: deliver([(_PROGRESS, value)]))
        self._pool.start(_Job(fn, context, deliver))
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

    def _receive(self, payload: tuple[int, list]) -> None:
        generation, handoff = payload
        kind, value = handoff.pop()  # desde aquí, solo lo retiene la interfaz
        if generation != self._generation:
            if kind == _FINISHED:
                self.discarded.emit(value)
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


# --- liberación en segundo plano -----------------------------------------------------------

def release_in_background(value: Any, dismantle: Callable[[Any], Iterable[Any]]) -> None:
    """Suelta ``value`` en el hilo de ``POOL_RELEASE``, recorriendo allí los pasos de ``dismantle(value)``.

    Cada paso debe soltar poco: entre uno y otro el hilo cede el GIL. Quien llama le entrega su
    última referencia y ya no lo toca, ni lo hace nada de lo que muestra, porque se vacía mientras la
    interfaz sigue. Nada de lo que lleve puede ser un objeto de Qt, que se destruiría fuera de su
    hilo. No se cancela: ``wait_for_tasks`` también la espera.
    """
    holder = [value]
    del value

    def release(context: TaskContext) -> None:
        time.sleep(RELEASE_DELAY)  # sin el GIL
        item = holder.pop()
        steps, done = iter(dismantle(item)), False
        while not done:
            before = gc.get_count()[0]   # lo que cada trozo descuenta, para _resume_gc
            done = next(steps, _STEPS_DONE) is _STEPS_DONE
            _count_released(before)
        before = gc.get_count()[0]
        del item, steps   # muere aquí con lo poco que quede (y avisa a la vigilancia del recolector si la tenía)
        _count_released(before)

    def report(handoff: list) -> None:
        kind, outcome = handoff.pop()
        if kind == _FAILED:
            log.warning("liberación en segundo plano fallida:\n%s", outcome.traceback)

    thread_pool(POOL_RELEASE).start(_Job(release, TaskContext(threading.Event(), lambda value: None), report))
