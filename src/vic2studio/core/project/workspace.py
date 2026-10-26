"""``Workspace``: documentos, transacciones con nombre, deshacer y guardado (wizard §6.2).

Python puro y de un solo hilo: llamar desde otro hilo lanza ``WrongThreadError``
(I12). Toda mutación va dentro de ``transaction``: antes de tocar un modelo se
llama a ``touch(handle)``, que toma la instantánea (una vez por transacción) y sube
``version``. Las transacciones anidadas se funden en la exterior; si una lanza, sus
documentos vuelven a la instantánea y no se apila nada.

Guardar (``save``): renderiza todos los sucios con su códec (aquí saltan los
errores de codificación y de verificación sin tocar el disco), planifica cada
escritura (CREATE, MODIFY, COPY_FROM_GAME a la misma ruta del mod, TRASH), la
comprueba y la confirma con ``journal.SaveTransaction``. Guardar sin cambios no
escribe nada ni crea ``.vic2studio/`` (I4).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager

from ..vfs.model import DocKind
from ..vfs.paths import VPath
from ..vfs.vfs import VirtualFS
from .model import ChangeSet, DocHandle, ExternalChange, ProjectSettings, SaveReport, UndoStep, WorkspaceEvent


class WrongThreadError(RuntimeError):
    """El ``Workspace`` se usó desde un hilo que no es el suyo (I12)."""


class ReadOnlyDocumentError(PermissionError):
    """Se intentó mutar un documento con ``read_only_reason`` (sintaxis rota, binario, bloqueo)."""

    def __init__(self, rel: VPath, reason: str):
        self.rel = rel
        self.reason = reason
        super().__init__(f"{rel}: {reason}")


class Txn:
    """Transacción abierta: ``label`` y ``fmt`` dan el nombre del paso de deshacer."""

    label: str
    fmt: dict
    merge_key: str | None

    def touched(self) -> list[VPath]:
        raise NotImplementedError


class Workspace:
    AUTOSAVE_SECONDS = 60
    AUTOSAVE_TRANSACTIONS = 20

    def __init__(self, vfs: VirtualFS, *, settings: ProjectSettings, lru_bytes: int = 300 * 2**20,
                 read_only: bool = False, session_id: str | None = None) -> None:
        raise NotImplementedError

    def bind_to_current_thread(self) -> None:
        """Hace dueño al hilo actual (``Project.open`` se construye en segundo plano y se entrega a la interfaz).
        Lanza ``RuntimeError`` si hay una transacción abierta."""
        raise NotImplementedError

    @property
    def vfs(self) -> VirtualFS:
        raise NotImplementedError

    @property
    def read_only(self) -> bool:
        raise NotImplementedError

    def open(self, rel: str | VPath, *, kind: DocKind | None = None, create: bool = False) -> DocHandle:
        """Documento efectivo de ``rel`` (ganador de la VFS, o el nuevo/sucio en memoria). Leer no escribe (I4).

        Sin archivo y sin ``create``: ``FileNotFoundError``. Con errores de sintaxis
        se abre con ``read_only_reason="parse_errors"`` (D17).
        """
        raise NotImplementedError

    def peek(self, rel: str | VPath) -> DocHandle | None:
        raise NotImplementedError

    @contextmanager
    def transaction(self, label: str, *, merge_key: str | None = None, **fmt) -> Iterator[Txn]:
        raise NotImplementedError
        yield  # pragma: no cover

    def touch(self, handle: DocHandle) -> None:
        """Llamar antes de mutar ``handle.model`` (dentro de una transacción; si no, ``RuntimeError``)."""
        raise NotImplementedError

    def replace_model(self, handle: DocHandle, model: object) -> None:
        """Sustituye el modelo entero (edición de texto libre, arreglo de sintaxis); también se deshace."""
        raise NotImplementedError

    def replace_text(self, handle: DocHandle, data: bytes) -> None:
        """``replace_model(handle, codec.load(data))`` y recalcula ``read_only_reason`` (D17: tras arreglar la
        sintaxis se habilita la edición estructural)."""
        raise NotImplementedError

    def create(self, rel: str | VPath, kind: DocKind, model: object | None = None) -> DocHandle:
        """Documento nuevo (dentro de una transacción); ``model=None`` usa ``codec.empty``."""
        raise NotImplementedError

    def delete(self, rel: str | VPath) -> None:
        """Lápida (dentro de una transacción): al guardar, el archivo del mod va a la papelera. Uno del juego no se
        puede borrar (``PermissionError``)."""
        raise NotImplementedError

    def undo(self) -> UndoStep | None:
        raise NotImplementedError

    def redo(self) -> UndoStep | None:
        raise NotImplementedError

    def can_undo(self) -> bool:
        raise NotImplementedError

    def can_redo(self) -> bool:
        raise NotImplementedError

    def history(self) -> list[tuple[str, dict]]:
        raise NotImplementedError

    def dirty(self) -> list[DocHandle]:
        raise NotImplementedError

    def changeset(self, rels: Iterable[VPath] | None = None) -> ChangeSet:
        """Lo que escribiría ``save(rels)``, con su diff; no toca el disco. Puede lanzar los errores de render."""
        raise NotImplementedError

    def save(self, rels: Iterable[VPath] | None = None) -> SaveReport:
        raise NotImplementedError

    def revert(self, rel: str | VPath) -> None:
        """Vuelve a lo que hay en disco (dentro de una transacción, así que también se deshace)."""
        raise NotImplementedError

    def check_external_changes(self) -> list[ExternalChange]:
        """Al recuperar el foco y antes de guardar: documentos abiertos cuyo archivo cambió fuera."""
        raise NotImplementedError

    def reload(self, rel: str | VPath) -> None:
        """Descarta lo de memoria y vuelve a leer (respuesta «Recargar del disco» al conflicto). No se deshace."""
        raise NotImplementedError

    def accept_external(self, rel: str | VPath) -> None:
        """«Conservar mis cambios»: adopta la huella actual del disco como base, así que el próximo guardado
        sobrescribe el cambio externo (el diario hace su .bak). No toca el modelo."""
        raise NotImplementedError

    def external_diff(self, rel: str | VPath) -> str:
        """«Comparar»: diff entre lo que hay ahora en disco y el documento en memoria."""
        raise NotImplementedError

    def write_recovery(self) -> None:
        """Autoguardado de los sucios en ``recovery/<sesión>/`` (no crea nada si no hay sucios)."""
        raise NotImplementedError

    def subscribe(self, fn: Callable[[WorkspaceEvent], None]) -> Callable[[], None]:
        """Devuelve la función que cancela la suscripción."""
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
