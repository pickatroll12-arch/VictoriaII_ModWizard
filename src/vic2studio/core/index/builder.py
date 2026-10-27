"""Construcción del índice: extraer hechos de cada archivo, con caché por huella (wizard §7).

``build_index`` recorre la instantánea de la VFS (sin el CST vivo, I12): para cada
archivo de cada capa con algún extractor, reutiliza los hechos de la caché si la
huella (tamaño y mtime) y la versión del extractor coinciden, y si no lo lee y lo
extrae. ``overrides`` son los documentos sin guardar (``rel → bytes`` del
``snapshot`` de su códec): sustituyen al archivo del mod (o lo crean) sin tocar la
caché. Lanza ``core.cancel.Cancelled``.

Un archivo se lee y se analiza una sola vez aunque lo procesen varios
extractores (todos reciben el mismo objeto ``bytes`` y ``parsing.document`` lo
recuerda). Un ``override`` con valor ``None`` es un documento borrado sin guardar:
el archivo del mod deja de contar (ampliación compatible del contrato).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

from ..cancel import CancelCheck, Cancelled, raise_if_cancelled
from ..vfs.model import FileEntry, Fingerprint, Layer, LayerKind, VfsSnapshot
from ..vfs.paths import VPath
from . import parsing
from .cache import FactsCache
from .index import SymbolIndex
from .model import ExtractorSpec, FileFacts, discover_extractors, extractors_for

_log = logging.getLogger(__name__)

# Contador de extracciones de la última construcción (criterio 2: «cambiar un archivo reprocesa solo ese»).
ParseCounter = Callable[[VPath, str], None]


def _run(spec: ExtractorSpec, rel: VPath, data: bytes, layer: LayerKind, fingerprint: Fingerprint) -> FileFacts:
    try:
        defs, refs = spec.fn(rel, data if spec.needs_data else b"", layer)
    except Cancelled:
        raise
    except Exception:  # noqa: BLE001 - un archivo roto nunca tumba el índice
        _log.exception("el extractor %s falló con %s", spec.name, rel)
        defs, refs = (), ()
    return FileFacts(rel, layer, fingerprint, tuple(defs), tuple(refs), spec.name, spec.version)


def extract_bytes(rel: VPath, data: bytes, layer: LayerKind, *, fingerprint=None) -> list[FileFacts]:
    """Hechos de unos bytes con todos los extractores que procesan ``rel`` (uno por extractor; vacío si ninguno).

    Nunca lanza por el contenido: un archivo roto da los hechos que se puedan sacar.
    """
    discover_extractors()
    rel = VPath.of(rel)
    data = bytes(data)
    fingerprint = fingerprint if fingerprint is not None else Fingerprint(len(data), 0)
    try:
        return [_run(spec, rel, data, layer, fingerprint) for spec in extractors_for(rel)]
    finally:
        parsing.forget()


def extract_entry(entry: FileEntry) -> list[FileFacts]:
    """``extract_bytes`` del archivo en disco de ``entry`` (``OSError`` si no se puede leer)."""
    discover_extractors()
    specs = extractors_for(entry.rel)
    data = entry.path.read_bytes() if any(spec.needs_data for spec in specs) else b""
    return extract_bytes(entry.rel, data, entry.layer.kind, fingerprint=entry.fingerprint)


class _Specs:
    """``extractors_for`` con memoria por ruta (la misma ruta en varias capas)."""

    def __init__(self) -> None:
        self._memo: dict[str, list[ExtractorSpec]] = {}

    def __call__(self, rel: VPath) -> list[ExtractorSpec]:
        key = rel.key
        found = self._memo.get(key)
        if found is None:
            found = self._memo[key] = extractors_for(rel)
        return found


def build_index(snapshot: VfsSnapshot, cache: FactsCache | None, overrides: Mapping[VPath, bytes] | None = None, *,
                progress: Callable[[int, int], None] | None = None, cancelled: CancelCheck = None,
                on_extract: ParseCounter | None = None) -> SymbolIndex:
    """Índice de la vista efectiva. ``cache=None`` no usa caché. ``progress(hechos, total)`` por archivo;
    ``on_extract(rel, extractor)`` cada vez que se extrae de verdad (no desde la caché). Guarda en la caché lo
    nuevo antes de volver."""
    raise_if_cancelled(cancelled)
    discover_extractors()
    specs_for = _Specs()
    pending = {VPath.of(rel).key: (VPath.of(rel), data) for rel, data in (overrides or {}).items()}
    by_layer: dict[int, list[tuple[FileEntry, list[ExtractorSpec]]]] = {}
    layers: list[Layer] = list(snapshot.layers)
    position = {id(layer): index for index, layer in enumerate(layers)}
    for key, stack in snapshot.entries.items():
        for entry in stack:
            if entry.layer.kind is LayerKind.MOD and key in pending:
                continue                     # el documento sin guardar sustituye al archivo del mod
            specs = specs_for(entry.rel)
            if specs:
                index = position.get(id(entry.layer))
                if index is None:            # capa que no está en snapshot.layers (no debería pasar)
                    layers.append(entry.layer)
                    index = position[id(entry.layer)] = len(layers) - 1
                by_layer.setdefault(index, []).append((entry, specs))
    total = sum(len(items) for items in by_layer.values()) + len(pending)
    done = 0
    all_facts: list[FileFacts] = []
    for index in sorted(by_layer):
        layer = layers[index]
        cached = cache.load(layer) if cache is not None else {}
        layer_facts: list[FileFacts] = []
        changed = False
        for entry, specs in by_layer[index]:
            raise_if_cancelled(cancelled)
            key = entry.rel.key
            reused: list[FileFacts] = []
            missing: list[ExtractorSpec] = []
            for spec in specs:
                found = cached.get((key, spec.name))
                if (found is not None and found.version == spec.version and found.rel == entry.rel
                        and found.fingerprint.same_stat(entry.fingerprint)):
                    reused.append(found)
                else:
                    missing.append(spec)
            fresh: list[FileFacts] = []
            if missing:
                try:
                    data = entry.path.read_bytes() if any(s.needs_data for s in missing) else b""
                except OSError as exc:
                    _log.info("no se pudo leer %s para el índice: %s", entry.path, exc)
                    data = None
                if data is not None:
                    try:
                        for spec in missing:
                            fresh.append(_run(spec, entry.rel, data, entry.layer.kind, entry.fingerprint))
                            if on_extract is not None:
                                on_extract(entry.rel, spec.name)
                    finally:
                        parsing.forget()
                changed = True
            layer_facts.extend(reused)
            layer_facts.extend(fresh)
            done += 1
            if progress is not None:
                progress(done, total)
        if cache is not None:
            current = {(f.rel.key, f.extractor) for f in layer_facts}
            if changed or current != set(cached):
                try:
                    cache.store(layer, layer_facts)
                except OSError as exc:      # la caché es una ayuda: sin ella solo se tarda más
                    _log.warning("no se pudo guardar la caché del índice: %s", exc)
        all_facts.extend(layer_facts)
    for key, (rel, data) in pending.items():
        raise_if_cancelled(cancelled)
        if data is not None:
            for item in extract_bytes(rel, data, LayerKind.MOD):
                all_facts.append(item)
                if on_extract is not None:
                    on_extract(rel, item.extractor)
        done += 1
        if progress is not None:
            progress(done, total)
    return SymbolIndex(all_facts, snapshot=snapshot)
