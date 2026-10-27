"""Sistema de archivos virtual: herencia juego base + dependencias + mod (docs/diseno/wizard.md §5).

El juego base es intocable: ``WriteGuard`` solo admite escribir en el subárbol
del mod y en su descriptor, comparando rutas reales (el mod suele vivir dentro
de ``<juego>/mod/``). ``VirtualFS`` resuelve qué archivo cargaría el juego
(``resolve``), con todas las capas debajo (``stack``), y dónde iría la copia en
el mod (``mod_target``). Las reglas de carga por carpeta están en ``rules``.
Sin Qt.
"""

from .guard import (
    EXPECTED_FOLDERS,
    GAME_DATA_MIN_FOLDERS,
    FolderReport,
    InvalidModRootError,
    WriteGuard,
    WriteOutsideModError,
    evaluate_game,
    evaluate_mod,
    folder_key,
    inspect_folder,
    is_under,
    mod_root_problem,
    same_folder,
)
from .model import DocKind, FileEntry, Fingerprint, Layer, LayerKind, VfsSnapshot
from .paths import (
    DESCRIPTOR_REL,
    INVALID_PATH,
    MAX_PATH_WARNING,
    WINDOWS_DEVICES,
    InvalidPathError,
    VPath,
    long_path_problem,
    windows_name_problems,
)
from .rules import LOAD_RULES, LoadMode, LoadRule, rule_for
from .vfs import VirtualFS

__all__ = [
    "DESCRIPTOR_REL", "EXPECTED_FOLDERS", "GAME_DATA_MIN_FOLDERS", "INVALID_PATH", "LOAD_RULES", "MAX_PATH_WARNING",
    "WINDOWS_DEVICES", "DocKind", "FileEntry", "Fingerprint", "FolderReport", "InvalidModRootError",
    "InvalidPathError", "Layer", "LayerKind", "LoadMode", "LoadRule", "VPath", "VfsSnapshot", "VirtualFS", "WriteGuard",
    "WriteOutsideModError", "evaluate_game", "evaluate_mod", "folder_key", "inspect_folder", "is_under",
    "long_path_problem", "mod_root_problem", "rule_for", "same_folder", "windows_name_problems",
]
