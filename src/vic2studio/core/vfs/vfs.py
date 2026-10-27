"""``VirtualFS``: el juego base, las dependencias y el mod vistos como el juego los carga (wizard §5.1–5.3).

Orden de prioridad: mod > dependencias (la última declarada primero) > juego.
``replace_paths`` oculta los archivos **del juego** bajo esas carpetas (siguen en
``stack`` para comparar, nunca en ``resolve``); los del propio mod se siguen
cargando (§5.3). ``replace_recursive`` decide si alcanza a las subcarpetas
[verificar en juego]: la opción es explícita y las pruebas cubren los dos valores.

``scan`` solo hace ``os.scandir``: no lee contenidos (I4). ``snapshot`` da una
copia inmutable para los hilos de fondo (I12).

``paths.DESCRIPTOR_REL`` nombra el descriptor (``.mod``, fuera de la carpeta del
mod): ``resolve``, ``stack``, ``read_bytes`` y ``mod_target`` lo tratan como un
archivo de la capa MOD cuya ruta real es ``descriptor_path``; no sale en ``list``.

En la capa del juego no se recorre ``<juego>/mod/``: ahí viven los mods (también
este), no archivos del juego base.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from itertools import combinations
from pathlib import Path
from types import MappingProxyType

from ..cancel import CancelCheck, raise_if_cancelled
from ..modfile import DESCRIPTOR_SUFFIX, ModDescriptor, read_descriptor
from .guard import InvalidModRootError, WriteGuard, mod_root_problem
from .model import FileEntry, Fingerprint, Layer, LayerKind, VfsSnapshot, matching_keys, winner
from .paths import DESCRIPTOR_REL, VPath, folder_key

# Carpetas de primer nivel que no son del juego y nunca se recorren (I4: abrir no escribe; tampoco las lista).
IGNORED_TOP_FOLDERS = frozenset({".vic2studio", ".git"})
IGNORED_SUFFIXES = frozenset({".bak", ".tmp"})
# En la capa del juego, <juego>/mod/ guarda los mods: no son archivos del juego base.
GAME_IGNORED_TOP_FOLDERS = frozenset({"mod"})

# rel.key -> entradas de una capa (más de una: archivos que solo difieren en mayúsculas).
_LayerFiles = dict


def resolve_dependencies(game_root: Path | None, names: Sequence[str]) -> tuple[list[Path], list[str]]:
    """Carpetas de los mods que ``names`` nombra (por su ``name``, en ``<juego>/mod/*.mod``), en el orden dado,
    y los nombres que no se encontraron."""
    found: list[Path] = []
    missing: list[str] = []
    if not names:
        return found, missing
    by_name: dict[str, Path] = {}
    if game_root is not None:
        mods_dir = Path(game_root) / "mod"
        try:
            files = sorted(p for p in mods_dir.iterdir() if p.suffix.lower() == DESCRIPTOR_SUFFIX and p.is_file())
        except OSError:
            files = []
        for file in files:
            descriptor = read_descriptor(file)
            if descriptor is not None and descriptor.name and descriptor.path:
                by_name.setdefault(descriptor.name.casefold(), Path(game_root) / _relative(descriptor.path))
    for name in names:
        root = by_name.get(name.strip().casefold())
        if root is None:
            missing.append(name)
        else:
            found.append(root)
    return found, missing


def _relative(path: str) -> str:
    return "/".join(p for p in path.replace("\\", "/").split("/") if p and p != ".")


class VirtualFS:
    def __init__(self, game_root: Path | None, mod_root: Path, *, descriptor: Path | None = None,
                 replace_paths: Sequence[str] = (), replace_recursive: bool = True,
                 dependencies: Sequence[Path] = (), extra_roots: Sequence[Path] = ()) -> None:
        """``descriptor`` es el ``.mod`` (lo admite ``guard``); ``game_root=None``: solo el mod (pruebas, mods sueltos).

        ``extra_roots`` pasa al ``WriteGuard`` (la carpeta de proyecto de un mod de solo lectura, §5.4).
        Lanza ``InvalidModRootError`` si ``mod_root`` no puede ser un mod de ``game_root`` (I1: el núcleo no
        confía en que la interfaz lo haya filtrado).
        """
        self._game_root = None if game_root is None else Path(game_root)
        self._mod_root = Path(mod_root)
        problem = mod_root_problem(self._mod_root, self._game_root)
        if problem is not None:
            raise InvalidModRootError(self._mod_root, problem)
        self._descriptor = None if descriptor is None else Path(descriptor)
        self._replace = tuple(sorted({k for k in (folder_key(p) for p in replace_paths) if k}))
        self._replace_recursive = replace_recursive
        self._dependencies = tuple(Path(d) for d in dependencies)
        self.missing_dependencies: tuple[str, ...] = ()
        layers = [Layer(LayerKind.MOD, self._mod_root, self._mod_root.name)]
        layers += [Layer(LayerKind.DEPENDENCY, d, d.name) for d in reversed(self._dependencies)]
        if self._game_root is not None:
            layers.append(Layer(LayerKind.GAME, self._game_root, self._game_root.name))
        self._layers = tuple(layers)
        self._guard = WriteGuard(self._mod_root, extra_files=[self._descriptor] if self._descriptor else [],
                                 extra_roots=extra_roots)
        self._files: list[_LayerFiles] = [{} for _ in self._layers]

    @classmethod
    def from_descriptor(cls, game_root: Path, descriptor: ModDescriptor, *,
                        replace_recursive: bool = True) -> VirtualFS:
        """Mod en ``<juego>/<descriptor.path>``, con sus ``replace_path`` y ``dependencies`` resueltas por nombre."""
        game_root = Path(game_root)
        if descriptor.path:
            mod_root = game_root / _relative(descriptor.path)
        else:
            mod_root = descriptor.file.with_suffix("")
        dependencies, missing = resolve_dependencies(game_root, descriptor.dependencies)
        vfs = cls(game_root, mod_root, descriptor=descriptor.file, replace_paths=descriptor.replace_paths,
                  replace_recursive=replace_recursive, dependencies=dependencies)
        vfs.missing_dependencies = tuple(missing)
        return vfs

    @property
    def guard(self) -> WriteGuard:
        return self._guard

    @property
    def layers(self) -> tuple[Layer, ...]:
        """De más prioritaria a menos: mod, dependencias, juego."""
        return self._layers

    @property
    def mod_layer(self) -> Layer:
        return self._layers[0]

    @property
    def game_root(self) -> Path | None:
        return self._game_root

    @property
    def mod_root(self) -> Path:
        return self._mod_root

    @property
    def descriptor_path(self) -> Path | None:
        return self._descriptor

    @property
    def dependencies(self) -> tuple[Path, ...]:
        """Carpetas de las dependencias, en el orden declarado."""
        return self._dependencies

    @property
    def replace_paths(self) -> tuple[str, ...]:
        """Carpetas reemplazadas, como claves (``folder_key``: en mayúsculas)."""
        return self._replace

    @property
    def replace_recursive(self) -> bool:
        return self._replace_recursive

    # --- escaneo -----------------------------------------------------------------------

    def scan(self, *, progress=None, cancelled: CancelCheck = None) -> None:
        """Recorre las capas con ``os.scandir`` (sin leer contenidos); lanza ``core.cancel.Cancelled``.

        ``progress(done, total)`` es opcional: cuenta las entradas de primer nivel de
        todas las capas. Omite ``IGNORED_TOP_FOLDERS`` y los ``IGNORED_SUFFIXES``. Si
        se cancela, la VFS se queda como estaba.
        """
        raise_if_cancelled(cancelled)
        tops = [self._top_entries(layer) for layer in self._layers]
        total = sum(len(top) for top in tops)
        done = 0
        files: list[_LayerFiles] = []
        for layer, top in zip(self._layers, tops):
            found: _LayerFiles = {}
            for entry in top:
                raise_if_cancelled(cancelled)
                _scan_tree(layer, entry, found, cancelled)
                done += 1
                if progress is not None:
                    progress(done, total)
            for stack in found.values():
                stack.sort(key=lambda e: e.rel)
            files.append(found)
        self._files = files
        self._add_descriptor()

    def _top_entries(self, layer: Layer) -> list[os.DirEntry]:
        try:
            with os.scandir(layer.root) as it:
                entries = list(it)
        except OSError:
            return []
        ignored = IGNORED_TOP_FOLDERS | (GAME_IGNORED_TOP_FOLDERS if layer.kind is LayerKind.GAME else frozenset())
        return sorted((e for e in entries if e.name.lower() not in ignored), key=lambda e: e.name)

    def _add_descriptor(self) -> None:
        mod_files = self._files[0]
        mod_files.pop(DESCRIPTOR_REL.key, None)
        if self._descriptor is None:
            return
        try:
            fingerprint = Fingerprint.of_path(self._descriptor)
        except OSError:
            return
        mod_files[DESCRIPTOR_REL.key] = [FileEntry(DESCRIPTOR_REL, self._layers[0], self._descriptor, fingerprint)]

    # --- consulta ----------------------------------------------------------------------

    def _hidden(self, key: str) -> bool:
        """True si ``replace_path`` oculta los archivos del juego con esta clave."""
        if not self._replace or key == DESCRIPTOR_REL.key:
            return False
        parent = key.rpartition("/")[0]
        for folder in self._replace:
            if parent == folder or (self._replace_recursive and parent.startswith(folder + "/")):
                return True
        return False

    def _stack(self, key: str) -> list[FileEntry]:
        stack: list[FileEntry] = []
        for layer_files in self._files:
            entries = layer_files.get(key)
            if entries:
                stack.extend(entries)
        return stack

    def resolve(self, rel: str | VPath) -> FileEntry | None:
        """Archivo que cargaría el juego (el ganador efectivo), o None."""
        key = VPath.of(rel).key
        return winner(self._stack(key), self._hidden(key))

    def stack(self, rel: str | VPath) -> list[FileEntry]:
        """Todas las capas que tienen ``rel``, ganador primero (incluidos los ocultos por replace_path)."""
        return self._stack(VPath.of(rel).key)

    def entry(self, rel: str | VPath, kind: LayerKind) -> FileEntry | None:
        """La entrada de ``rel`` en la primera capa de ese tipo (aunque no gane), o None."""
        key = VPath.of(rel).key
        for layer, layer_files in zip(self._layers, self._files):
            if layer.kind is kind and layer_files.get(key):
                return layer_files[key][0]
        return None

    def _keys(self) -> set[str]:
        keys: set[str] = set()
        for layer_files in self._files:
            keys.update(layer_files)
        return keys

    def list(self, folder: str, pattern: str = "*.txt", *, recursive: bool | None = None) -> list[FileEntry]:
        """Ganadores bajo ``folder`` ordenados por ``rel.key``; ``recursive=None`` usa la regla de carga."""
        found = []
        for key in matching_keys(self._keys(), folder, pattern, recursive):
            entry = winner(self._stack(key), self._hidden(key))
            if entry is not None:
                found.append(entry)
        return found

    def hidden_by_replace_path(self, entry: FileEntry) -> bool:
        return entry.layer.kind is LayerKind.GAME and self._hidden(entry.rel.key)

    def mod_target(self, rel: str | VPath) -> Path:
        """Destino en el mod: la misma ruta, reutilizando la mayúscula de las carpetas que el mod ya tenga.

        Si el mod ya tiene ese archivo (con otra mayúscula), es ese archivo. El
        descriptor (``DESCRIPTOR_REL``) es ``descriptor_path``. Mira el disco, no el
        último escaneo: las carpetas creadas por un guardado anterior cuentan.
        """
        rel = VPath.of(rel)
        if rel == DESCRIPTOR_REL:
            if self._descriptor is None:
                raise FileNotFoundError("este proyecto no tiene descriptor .mod")
            return self._descriptor
        existing = self._files[0].get(rel.key)
        if existing:
            return existing[0].path
        return _case_path(self._mod_root, rel)

    def read_bytes(self, rel_or_entry: str | VPath | FileEntry) -> bytes:
        """Bytes del ganador (o de la entrada dada); ``FileNotFoundError`` si no hay."""
        if isinstance(rel_or_entry, FileEntry):
            return rel_or_entry.path.read_bytes()
        entry = self.resolve(rel_or_entry)
        if entry is None:
            raise FileNotFoundError(str(rel_or_entry))
        return entry.path.read_bytes()

    def same_as_game(self, rel: str | VPath) -> bool:
        """True si el archivo del mod es idéntico byte a byte al del juego (mods copia completa, H15)."""
        mod = self.entry(rel, LayerKind.MOD)
        game = self.entry(rel, LayerKind.GAME)
        if mod is None or game is None or mod.fingerprint.size != game.fingerprint.size:
            return False
        try:
            return mod.path.read_bytes() == game.path.read_bytes()
        except OSError:
            return False

    def snapshot(self) -> VfsSnapshot:
        entries = {}
        hidden = set()
        for key in self._keys():
            stack = tuple(self._stack(key))
            entries[key] = stack
            if self._hidden(key) and any(e.layer.kind is LayerKind.GAME for e in stack):
                hidden.add(key)
        return VfsSnapshot(self._layers, MappingProxyType(entries), frozenset(hidden))

    def refresh(self, rels: Iterable[VPath] | None = None) -> set[VPath]:
        """Vuelve a mirar ``rels`` (o todo) y devuelve las rutas cuya huella o ganador cambió."""
        if rels is None:
            keys = self._keys()
            before = {key: self._signature(key) for key in keys}
            names = {key: self._stack(key)[0].rel for key in keys}
            self.scan()
            changed = set()
            for key in keys | self._keys():
                if before.get(key) != self._signature(key):
                    stack = self._stack(key)
                    changed.add(stack[0].rel if stack else names[key])
            return changed
        changed = set()
        for rel in rels:
            rel = VPath.of(rel)
            before = self._signature(rel.key)
            for index, layer in enumerate(self._layers):
                self._refresh_one(index, layer, rel)
            if before != self._signature(rel.key):
                changed.add(rel)
        return changed

    def _refresh_one(self, index: int, layer: Layer, rel: VPath) -> None:
        layer_files = self._files[index]
        key = rel.key
        if rel == DESCRIPTOR_REL:
            if index == 0:
                self._add_descriptor()
            return
        top = rel.parts[0].lower()
        if top in IGNORED_TOP_FOLDERS or rel.suffix in IGNORED_SUFFIXES:
            return
        if layer.kind is LayerKind.GAME and top in GAME_IGNORED_TOP_FOLDERS:
            return
        candidates = {e.path for e in layer_files.get(key, ())}
        candidates.add(_case_path(layer.root, rel))
        unique: dict[str, FileEntry] = {}
        for path in sorted(candidates):
            try:
                stat = os.stat(path)
            except OSError:
                continue
            if not os.path.isfile(path):
                continue
            actual = VPath.of(Path(path).relative_to(layer.root).as_posix())
            if actual.key != key:
                continue
            # Dos rutas que el sistema de archivos considera la misma (Windows): una sola entrada.
            unique.setdefault(os.path.normcase(os.path.realpath(path)),
                              FileEntry(actual, layer, Path(path), Fingerprint(stat.st_size, stat.st_mtime_ns)))
        if unique:
            layer_files[key] = sorted(unique.values(), key=lambda e: e.rel)
        else:
            layer_files.pop(key, None)

    def _signature(self, key: str) -> tuple:
        stack = self._stack(key)
        winner_entry = winner(stack, self._hidden(key))
        return (tuple((e.layer.kind, str(e.path), e.fingerprint.size, e.fingerprint.mtime_ns) for e in stack),
                None if winner_entry is None else str(winner_entry.path))

    def case_collisions(self) -> list[tuple[FileEntry, FileEntry]]:
        """Pares de archivos de una misma capa que solo difieren en mayúsculas (Windows los confundiría)."""
        pairs = []
        for layer_files in self._files:
            for key in sorted(layer_files):
                entries = layer_files[key]
                if len(entries) > 1:
                    pairs.extend(combinations(entries, 2))
        return pairs


def _scan_tree(layer: Layer, top: os.DirEntry, found: _LayerFiles, cancelled: CancelCheck) -> None:
    """Añade a ``found`` los archivos bajo ``top`` (iterativo: sin límite de profundidad ni ciclos de enlaces)."""
    pending = [(top, "")]
    seen: set[str] = set()
    while pending:
        item, base = pending.pop()
        name = item.name
        rel_text = f"{base}/{name}" if base else name
        try:
            is_dir = item.is_dir()
        except OSError:
            continue
        if is_dir:
            real = os.path.realpath(item.path)
            if real in seen:
                continue
            seen.add(real)
            raise_if_cancelled(cancelled)
            try:
                with os.scandir(item.path) as it:
                    pending.extend((child, rel_text) for child in it)
            except OSError:
                continue
            continue
        if os.path.splitext(name)[1].lower() in IGNORED_SUFFIXES:
            continue
        try:
            stat = item.stat()
            rel = VPath.of(rel_text)
        except (OSError, ValueError):
            continue
        found.setdefault(rel.key, []).append(
            FileEntry(rel, layer, Path(item.path), Fingerprint(stat.st_size, stat.st_mtime_ns)))


def _existing_case(folder: Path, name: str, *, want_dir: bool) -> str:
    """``name`` con la mayúscula de una entrada que ya exista en ``folder`` (la exacta si la hay)."""
    try:
        names = os.listdir(folder)
    except OSError:
        return name
    if name in names:
        return name
    upper = name.upper()
    matches = sorted(n for n in names if n.upper() == upper and os.path.isdir(folder / n) == want_dir)
    return matches[0] if matches else name


def _case_path(root: Path, rel: VPath) -> Path:
    """Ruta de ``rel`` bajo ``root`` con la mayúscula de cada componente que ya exista."""
    current = root
    parts = rel.parts
    for index, part in enumerate(parts):
        current = current / _existing_case(current, part, want_dir=index < len(parts) - 1)
    return current
