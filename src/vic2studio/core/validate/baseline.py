"""Línea base: los problemas de lo que no es el mod (juego y dependencias), para no culpar al mod (wizard §11, I11).

``compute_baseline`` valida el contexto sin el mod (``build_context(base_snapshot(s),
…, game_only=True)``) y devuelve las huellas (``Problem.fingerprint``) de sus
problemas; un ``check_failed`` nunca entra (es un fallo de una regla, no del juego).
Se guarda en caché por instalación y dependencias
(``<cache_dir>/baseline/game-<sha1(realpath)>[-<variante>].v<N>.json``, a través de
``core.fileio``, nunca en el juego ni en el mod) con la firma de los archivos de la
base, la versión de las reglas y la fecha de trabajo: si cambia cualquiera, se
recalcula. La variante (un sha1 de las raíces de las dependencias, en su orden, y de
la fecha) separa las líneas base de mods con distintas dependencias o fechas, para
que no se pisen; sin dependencias ni fecha el nombre es el de siempre.

La firma de los archivos es un sha1 de ``(capa, rel.key, tamaño, mtime_ns)`` de cada
archivo que no es del mod (sin leerlos). La versión de las reglas combina
``RULES_VERSION`` (se sube a mano cuando una regla cambia de comportamiento), los
códigos registrados con su gravedad, ``INDEX_FORMAT`` y la versión de cada extractor
(un extractor nuevo cambia lo que encuentran las reglas). Una caché ilegible se
ignora.

``baseline_for`` hace todo el ciclo (caché o cálculo y guardado) para quien valida.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import replace
from pathlib import Path

from .. import appdirs, fileio
from ..cancel import CancelCheck
from ..clausewitz.nodes import ClausewitzDate
from ..vfs.model import LayerKind, VfsSnapshot
from .context import ValidationContext, base_snapshot

_log = logging.getLogger(__name__)

# 2: huellas con las rutas de los args sin mayúsculas, base con dependencias y fecha (las de la 1 no valen).
BASELINE_FORMAT = 2
# Sube cuando una regla cambie lo que encuentra (invalida las líneas base guardadas).
RULES_VERSION = 1


def compute_baseline(base: ValidationContext, *, cancelled: CancelCheck = None,
                     date: ClausewitzDate | None = None) -> frozenset[tuple]:
    """Huellas de todos los problemas del contexto, que debe ser el de la base (``build_context(...,
    game_only=True)``: sin el mod). ``date``: la fecha de trabajo del proyecto, si el contexto no la trae ya (la
    línea base debe mirar las historias a la misma fecha que la validación). Los ``check_failed`` no entran.
    Lanza ``core.cancel.Cancelled``."""
    from .validator import CHECK_FAILED, Validator

    if date is not None and base.date != date:
        base = replace(base, date=date)
    report = Validator(base).validate(cancelled=cancelled)
    return frozenset(problem.fingerprint() for problem in report.problems if problem.code != CHECK_FAILED)


def rules_signature() -> str:
    """Versión de las reglas registradas (``RULES_VERSION`` + códigos y gravedades) y de lo que las alimenta
    (``INDEX_FORMAT`` y la versión de cada extractor)."""
    from ..index.model import INDEX_FORMAT, discover_extractors
    from .registry import discover_rules

    rules = discover_rules()
    text = ";".join(f"{code}:{spec.severity.value}:{spec.family}" for code, spec in sorted(rules.items()))
    extractors = ";".join(f"{spec.name}:{spec.version}" for spec in sorted(discover_extractors(),
                                                                          key=lambda s: s.name))
    return hashlib.sha1(f"{RULES_VERSION}|{INDEX_FORMAT}|{text}|{extractors}".encode()).hexdigest()


def files_signature(snapshot: VfsSnapshot) -> str:
    """Firma de los archivos que no son del mod (juego y dependencias) de ``snapshot`` (sin leerlos): la misma
    con la instantánea completa que con su ``base_snapshot``."""
    base_layers = [layer for layer in snapshot.layers if layer.kind is not LayerKind.MOD]
    position = {id(layer): index for index, layer in enumerate(base_layers)}
    digest = hashlib.sha1()
    for key in sorted(snapshot.entries):
        for entry in snapshot.entries[key]:
            if entry.layer.kind is not LayerKind.MOD:
                digest.update(f"{position.get(id(entry.layer), -1)}|{entry.layer.kind.value}|{key}|"
                              f"{entry.fingerprint.size}|{entry.fingerprint.mtime_ns}\n".encode(
                                  "utf-8", "surrogatepass"))
    return digest.hexdigest()


def _game_root(snapshot: VfsSnapshot) -> Path | None:
    return next((layer.root for layer in snapshot.layers if layer.kind is LayerKind.GAME), None)


def _dependencies(snapshot: VfsSnapshot) -> list[str]:
    """Raíces reales de las dependencias, en el orden de la instantánea."""
    return [appdirs.mod_key(layer.root) for layer in snapshot.layers if layer.kind is LayerKind.DEPENDENCY]


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

    @staticmethod
    def _variant(snapshot: VfsSnapshot, date: ClausewitzDate | None) -> str:
        deps = _dependencies(snapshot)
        if not deps and date is None:
            return ""
        text = "|".join(deps) + "#" + ("" if date is None else str(date))
        return "-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]

    def path(self, snapshot: VfsSnapshot, *, date: ClausewitzDate | None = None) -> Path | None:
        """Archivo de la línea base del juego y las dependencias de ``snapshot`` a la fecha ``date``."""
        game = _game_root(snapshot)
        if game is None and not _dependencies(snapshot):
            return None
        prefix = f"game-{appdirs.mod_key(game)}" if game is not None else "nogame"
        return self.root / f"{prefix}{self._variant(snapshot, date)}.v{BASELINE_FORMAT}.json"

    def load(self, snapshot: VfsSnapshot, *, date: ClausewitzDate | None = None) -> frozenset[tuple] | None:
        """Línea base guardada para la base (juego y dependencias) de ``snapshot`` a la fecha ``date``, si sigue
        valiendo; None si hay que calcularla."""
        path = self.path(snapshot, date=date)
        if path is None:
            return frozenset()          # sin juego ni dependencias no hay nada heredado
        try:
            data = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, ValueError):
            return None
        try:
            if (data.get("format") != BASELINE_FORMAT or data.get("rules") != rules_signature()
                    or data.get("files") != files_signature(snapshot)
                    or data.get("date") != (None if date is None else str(date))
                    or data.get("dependencies") != _dependencies(snapshot)):
                return None
            return frozenset(_freeze(item) for item in data["fingerprints"])
        except (AttributeError, KeyError, TypeError):
            return None

    def store(self, snapshot: VfsSnapshot, baseline: frozenset[tuple], *,
              date: ClausewitzDate | None = None) -> None:
        path = self.path(snapshot, date=date)
        if path is None:
            return
        game = _game_root(snapshot)
        from ..index.cache import _is_under

        if any(_is_under(path, layer.root) for layer in snapshot.layers):
            _log.warning("la caché de la línea base (%s) está dentro del juego o del mod: no se escribe", path)
            return
        payload = {"format": BASELINE_FORMAT, "game": None if game is None else str(game),
                   "dependencies": _dependencies(snapshot), "date": None if date is None else str(date),
                   "rules": rules_signature(), "files": files_signature(snapshot),
                   "fingerprints": sorted(baseline, key=repr)}
        fileio.atomic_write_bytes(path, json.dumps(payload, ensure_ascii=False).encode("utf-8", "surrogatepass"))


def baseline_for(snapshot: VfsSnapshot, *, date: ClausewitzDate | None = None, cancelled: CancelCheck = None,
                 cache: BaselineCache | None = None, facts_cache=None) -> frozenset[tuple]:
    """La línea base del proyecto de ``snapshot``: de la caché (``BaselineCache``) si vale; si no, la calcula sobre
    ``base_snapshot`` (índice con ``facts_cache``, por defecto ``FactsCache()``) a la fecha ``date`` y la guarda.
    Es lo que hace la ``Session`` en segundo plano. Lanza ``core.cancel.Cancelled``."""
    from ..index import FactsCache, build_index
    from .context import build_context

    cache = cache if cache is not None else BaselineCache()
    cached = cache.load(snapshot, date=date)
    if cached is not None:
        return cached
    base = base_snapshot(snapshot)
    index = build_index(base, facts_cache if facts_cache is not None else FactsCache(), {}, cancelled=cancelled)
    context = build_context(base, index, {}, game_only=True, date=date, cancelled=cancelled)
    baseline = compute_baseline(context, cancelled=cancelled)
    try:
        cache.store(snapshot, baseline, date=date)
    except OSError as exc:          # la caché es una ayuda: sin ella solo se tarda más la próxima vez
        _log.warning("no se pudo guardar la línea base: %s", exc)
    return baseline
