"""Caché de hechos del índice: JSON-lines comprimido por capa, nunca pickle (wizard §7).

``<cache_dir>/index/game-<sha1(realpath)>/facts.v<INDEX_FORMAT>.jsonl.gz`` para el
juego base (compartida entre mods) y ``…/mod-<sha1>/`` para cada mod o
dependencia. Cada línea son los ``FileFacts`` de un archivo con su huella y la
versión de su extractor; al leer se descartan los de un extractor de otra versión.
Escribe solo fuera del mod, a través de ``core.fileio`` y con rutas de
``core.appdirs`` (I1, I4; lo vigila ``test_arch_writes``). Una caché ilegible o de
otro formato se ignora (se reconstruye), nunca hace fallar la apertura.

Formato: la primera línea es la cabecera ``{"format", "layer", "root"}``; cada
línea siguiente, ``[rel, extractor, versión, tamaño, mtime_ns, defs, refs]`` con
``defs = [[kind, name, line, attrs|null], …]`` y ``refs = [[kind, name, line,
column, role], …]``. Si la carpeta de la caché cayera dentro de la capa (una
variable de entorno mal puesta), no se escribe nada: indexar no escribe en el mod.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
from collections.abc import Iterable
from pathlib import Path
from types import MappingProxyType

from .. import appdirs, fileio
from ..vfs.model import Fingerprint, Layer, LayerKind
from ..vfs.paths import VPath
from .model import INDEX_FORMAT, FileFacts, Symbol, SymbolRef

_log = logging.getLogger(__name__)
_EMPTY = MappingProxyType({})
COMPRESS_LEVEL = 5


def _symbol(kind, name, rel, line, layer, attrs) -> Symbol:
    """``Symbol`` sin pasar por el ``__init__`` congelado (seis ``object.__setattr__``): leer la caché crea
    decenas de miles y tiene que bajar de 1 s (criterio 2). Mismo resultado que el constructor."""
    symbol = _new(Symbol)
    symbol.__dict__.update(kind=kind, name=name, rel=rel, line=line, layer=layer, attrs=attrs)
    return symbol


def _ref(kind, name, rel, line, column, role) -> SymbolRef:
    ref = _new(SymbolRef)
    ref.__dict__.update(kind=kind, name=name, rel=rel, line=line, column=column, role=role)
    return ref


_new = object.__new__


def _is_under(path: Path, folder: Path) -> bool:
    try:
        real = os.path.normcase(os.path.realpath(path))
        root = os.path.normcase(os.path.realpath(folder))
    except OSError:
        return False
    return real == root or real.startswith(root.rstrip(os.sep) + os.sep)


class FactsCache:
    def __init__(self, root: Path | None = None) -> None:
        """``root`` = carpeta de la caché (por defecto ``appdirs.cache_dir() / "index"``)."""
        self._root = Path(root) if root is not None else None

    @property
    def root(self) -> Path:
        return self._root if self._root is not None else appdirs.cache_dir() / "index"

    def folder(self, layer: Layer) -> Path:
        """Carpeta de la caché de una capa (``game-``/``mod-`` + sha1 de su ruta real)."""
        prefix = "game" if layer.kind is LayerKind.GAME else "mod"
        return self.root / f"{prefix}-{appdirs.mod_key(layer.root)}"

    def path(self, layer: Layer) -> Path:
        return self.folder(layer) / f"facts.v{INDEX_FORMAT}.jsonl.gz"

    def load(self, layer: Layer) -> dict[tuple[str, str], FileFacts]:
        """Hechos guardados de la capa por ``(rel.key, extractor)``; vacío si no hay o no se puede leer."""
        try:
            raw = self.path(layer).read_bytes()
        except OSError:
            return {}
        try:
            lines = gzip.decompress(raw).split(b"\n")
            header = json.loads(lines[0])
            if not isinstance(header, dict) or header.get("format") != INDEX_FORMAT \
                    or header.get("layer") != layer.kind.value:
                return {}
            found: dict[tuple[str, str], FileFacts] = {}
            kind = layer.kind
            loads = json.loads
            for line in lines[1:]:
                if not line:
                    continue
                rel_text, name, version, size, mtime, defs, refs = loads(line)
                rel = VPath.of(rel_text)
                symbols = tuple(_symbol(k, n, rel, ln, kind, _EMPTY if a is None else MappingProxyType(a))
                                for k, n, ln, a in defs)
                uses = tuple(_ref(k, n, rel, ln, col, role) for k, n, ln, col, role in refs)
                found[(rel.key, name)] = FileFacts(rel, kind, Fingerprint(size, mtime), symbols, uses, name,
                                                   version)
            return found
        except (OSError, EOFError, ValueError, TypeError, KeyError, IndexError) as exc:
            _log.info("caché del índice ilegible en %s (%s): se reconstruye", self.path(layer), exc)
            return {}

    def store(self, layer: Layer, facts: Iterable[FileFacts]) -> None:
        """Sustituye la caché de la capa por ``facts`` (escritura atómica)."""
        target = self.path(layer)
        if _is_under(target, layer.root):
            _log.warning("la caché del índice (%s) está dentro de la capa %s: no se escribe", target, layer.root)
            return
        dumps = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"), check_circular=False).encode
        lines = [dumps({"format": INDEX_FORMAT, "layer": layer.kind.value, "root": str(layer.root)})]
        for item in sorted(facts, key=lambda f: (f.rel.key, f.extractor)):
            defs = [[s.kind, s.name, s.line, dict(s.attrs) if s.attrs else None] for s in item.defs]
            refs = [[r.kind, r.name, r.line, r.column, r.role] for r in item.refs]
            lines.append(dumps([str(item.rel), item.extractor, item.version, item.fingerprint.size,
                                item.fingerprint.mtime_ns, defs, refs]))
        data = gzip.compress("\n".join(lines).encode("utf-8", "surrogatepass"), COMPRESS_LEVEL, mtime=0)
        fileio.atomic_write_bytes(target, data)

    def drop(self, layer: Layer, rels: Iterable[VPath] = ()) -> None:
        """Olvida la capa entera o solo esas rutas."""
        rels = list(rels)
        if not rels:
            target = self.path(layer)
            if not _is_under(target, layer.root):
                fileio.remove_file(target)
            return
        keys = {VPath.of(rel).key for rel in rels}
        kept = [facts for (key, _), facts in self.load(layer).items() if key not in keys]
        self.store(layer, kept)
