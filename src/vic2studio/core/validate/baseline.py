"""Línea base: los problemas del juego base solo, para no culpar al mod (wizard §11, I11).

``compute_baseline`` valida el contexto con solo la capa del juego y devuelve las
huellas (``Problem.fingerprint``) de sus problemas. Se guarda en caché por
instalación (``<cache_dir>/baseline/game-<sha1(realpath)>.v<N>.json``, a través de
``core.fileio``, nunca en el mod) con la firma de los archivos del juego y la
versión de las reglas: si cambia cualquiera de las dos, se recalcula.

La firma de los archivos es un sha1 de ``(rel.key, tamaño, mtime_ns)`` de cada
archivo de la capa del juego (sin leerlos). La versión de las reglas combina
``RULES_VERSION`` (se sube a mano cuando una regla cambia de comportamiento) con
los códigos registrados y su gravedad. Una caché ilegible se ignora.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from .. import appdirs, fileio
from ..cancel import CancelCheck
from ..vfs.model import LayerKind, VfsSnapshot
from .context import ValidationContext

_log = logging.getLogger(__name__)

BASELINE_FORMAT = 1
# Sube cuando una regla cambie lo que encuentra (invalida las líneas base guardadas).
RULES_VERSION = 1


def compute_baseline(game_only: ValidationContext, *, cancelled: CancelCheck = None) -> frozenset[tuple]:
    """Huellas de todos los problemas del contexto (que debe ser solo del juego: ``build_context(...,
    game_only=True)``). Lanza ``core.cancel.Cancelled``."""
    from .validator import Validator

    report = Validator(game_only).validate(cancelled=cancelled)
    return frozenset(problem.fingerprint() for problem in report.problems)


def rules_signature() -> str:
    """Versión de las reglas registradas (``RULES_VERSION`` + códigos y gravedades)."""
    from .registry import discover_rules

    rules = discover_rules()
    text = ";".join(f"{code}:{spec.severity.value}:{spec.family}" for code, spec in sorted(rules.items()))
    return hashlib.sha1(f"{RULES_VERSION}|{text}".encode()).hexdigest()


def files_signature(snapshot: VfsSnapshot) -> str:
    """Firma de los archivos del juego de ``snapshot`` (sin leerlos)."""
    digest = hashlib.sha1()
    for key in sorted(snapshot.entries):
        for entry in snapshot.entries[key]:
            if entry.layer.kind is LayerKind.GAME:
                digest.update(f"{key}|{entry.fingerprint.size}|{entry.fingerprint.mtime_ns}\n".encode(
                    "utf-8", "surrogatepass"))
    return digest.hexdigest()


def _game_root(snapshot: VfsSnapshot) -> Path | None:
    return next((layer.root for layer in snapshot.layers if layer.kind is LayerKind.GAME), None)


def _freeze(value):
    """Listas de JSON → tuplas, como las de ``Problem.fingerprint``."""
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


class BaselineCache:
    def __init__(self, root: Path | None = None) -> None:
        """``root`` = carpeta de la caché (por defecto ``appdirs.cache_dir() / "baseline"``)."""
        self._root = Path(root) if root is not None else None

    @property
    def root(self) -> Path:
        return self._root if self._root is not None else appdirs.cache_dir() / "baseline"

    def path(self, snapshot: VfsSnapshot) -> Path | None:
        game = _game_root(snapshot)
        if game is None:
            return None
        return self.root / f"game-{appdirs.mod_key(game)}.v{BASELINE_FORMAT}.json"

    def load(self, snapshot: VfsSnapshot) -> frozenset[tuple] | None:
        """Línea base guardada para el juego de ``snapshot`` si sigue valiendo; None si hay que calcularla."""
        path = self.path(snapshot)
        if path is None:
            return frozenset()          # sin juego base no hay nada heredado
        try:
            data = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, ValueError):
            return None
        try:
            if (data.get("format") != BASELINE_FORMAT or data.get("rules") != rules_signature()
                    or data.get("files") != files_signature(snapshot)):
                return None
            return frozenset(_freeze(item) for item in data["fingerprints"])
        except (AttributeError, KeyError, TypeError):
            return None

    def store(self, snapshot: VfsSnapshot, baseline: frozenset[tuple]) -> None:
        path = self.path(snapshot)
        if path is None:
            return
        game = _game_root(snapshot)
        from ..index.cache import _is_under

        if any(_is_under(path, layer.root) for layer in snapshot.layers):
            _log.warning("la caché de la línea base (%s) está dentro del juego o del mod: no se escribe", path)
            return
        payload = {"format": BASELINE_FORMAT, "game": str(game), "rules": rules_signature(),
                   "files": files_signature(snapshot), "fingerprints": sorted(baseline, key=repr)}
        fileio.atomic_write_bytes(path, json.dumps(payload, ensure_ascii=False).encode("utf-8", "surrogatepass"))
