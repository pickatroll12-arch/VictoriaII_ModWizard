"""Caché de hechos del índice: JSON-lines comprimido por capa, nunca pickle (wizard §7).

``<cache_dir>/index/game-<sha1(realpath)>/facts.v<INDEX_FORMAT>.jsonl.gz`` para el
juego base (compartida entre mods), ``…/mod-<sha1>/`` para el mod y
``…/dependency-<sha1>/`` para cada dependencia: el tipo de capa va en el nombre
para que dos capas con la misma carpeta (un mod que se declara dependencia de sí
mismo) no se pisen. Cada línea son los ``FileFacts`` de un archivo con su huella y
la versión de su extractor; al leer se descartan los de un extractor de otra
versión. Escribe solo fuera del mod, a través de ``core.fileio`` y con rutas de
``core.appdirs`` (I1, I4; lo vigila ``test_arch_writes``). Una caché ilegible o de
otro formato se ignora (se reconstruye), nunca hace fallar la apertura.

Formato: la primera línea es la cabecera ``{"format", "layer", "root"}``; cada
línea siguiente, ``[rel, extractor, versión, tamaño, mtime_ns, defs, refs]`` con
``defs = [[kind, name, line, attrs|null], …]`` y ``refs = [[kind, name, line,
column, role], …]``. Si la carpeta de la caché cayera dentro de la capa o de
cualquiera de las ``roots`` que se le pasan (las de todas las capas de la vista: una
variable de entorno mal puesta), no se escribe nada: indexar no escribe en el juego
ni en el mod.
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
from ..vfs.model import Fingerprint, Layer
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
        """Carpeta de la caché de una capa (``game-``/``mod-``/``dependency-`` + sha1 de su ruta real)."""
        return self.root / f"{layer.kind.value}-{appdirs.mod_key(layer.root)}"

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
            root = str(layer.root)
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
                                                   version, root)
            return found
        except (OSError, EOFError, ValueError, TypeError, KeyError, IndexError) as exc:
            _log.info("caché del índice ilegible en %s (%s): se reconstruye", self.path(layer), exc)
            return {}

    def _inside(self, target: Path, layer: Layer, roots: Iterable[Path]) -> Path | None:
        """La raíz (de la capa o de ``roots``) que contiene ``target``; None si no cae dentro de ninguna."""
        return next((root for root in (layer.root, *roots) if _is_under(target, root)), None)

    def store(self, layer: Layer, facts: Iterable[FileFacts], *, roots: Iterable[Path] = ()) -> None:
        """Sustituye la caché de la capa por ``facts`` (escritura atómica). ``roots``: las demás capas de la vista
        (``build_index`` pasa todas): si la caché cae dentro de alguna, no se escribe."""
        target = self.path(layer)
        inside = self._inside(target, layer, roots)
        if inside is not None:
            _log.warning("la caché del índice (%s) está dentro de la capa %s: no se escribe", target, inside)
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

    def drop(self, layer: Layer, rels: Iterable[VPath] = (), *, roots: Iterable[Path] = ()) -> None:
        """Olvida la capa entera o solo esas rutas (``roots`` como en ``store``)."""
        rels = list(rels)
        roots = list(roots)
        if not rels:
            target = self.path(layer)
            if self._inside(target, layer, roots) is None:
                fileio.remove_file(target)
            return
        keys = {VPath.of(rel).key for rel in rels}
        kept = [facts for (key, _), facts in self.load(layer).items() if key not in keys]
        self.store(layer, kept, roots=roots)
