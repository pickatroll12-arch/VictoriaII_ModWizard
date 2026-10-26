"""Proyecto transaccional: documentos, deshacer por instantáneas y guardado con diario (wizard §6).

Todo el estado vive aquí, en Python puro y sin Qt (D2). La interfaz habla con
él a través de ``ui/session.py``. Dentro del mod solo escribe ``journal`` (I1).
"""

from .model import (
    ChangeSet,
    DirtyChanged,
    DocChanged,
    DocCreated,
    DocDeleted,
    DocHandle,
    DocKind,
    DocReplaced,
    ExternalChange,
    JournalState,
    PlannedWrite,
    ProjectSettings,
    RecoveryResult,
    Saved,
    SaveProblem,
    SaveReport,
    SaveResult,
    Snapshot,
    UndoApplied,
    UndoStep,
    WorkspaceEvent,
    WriteAction,
)
from .project import Project
from .workspace import ReadOnlyDocumentError, Txn, Workspace, WrongThreadError

__all__ = [
    "ChangeSet", "DirtyChanged", "DocChanged", "DocCreated", "DocDeleted", "DocHandle", "DocKind", "DocReplaced",
    "ExternalChange", "JournalState", "PlannedWrite", "Project", "ProjectSettings", "ReadOnlyDocumentError",
    "RecoveryResult", "SaveProblem", "SaveReport", "SaveResult", "Saved", "Snapshot", "Txn", "UndoApplied",
    "UndoStep", "Workspace", "WorkspaceEvent", "WriteAction", "WrongThreadError",
]
