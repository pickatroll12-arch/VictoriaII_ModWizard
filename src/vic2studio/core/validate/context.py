"""``ValidationContext``: lo que ven las reglas, inmutable y apto para un hilo de fondo (wizard §11, I12).

Une la instantánea de la VFS, los documentos sin guardar (``overrides``: bytes del
``snapshot`` de su códec), el índice, la localización efectiva y las reglas del
juego. Las reglas leen archivos solo a través de ``read``/``parse``, que dan
primero el documento sin guardar y guardan en caché lo ya analizado.

Ampliaciones compatibles: un ``override`` con valor ``None`` es un documento
borrado sin guardar. ``build_context`` lo aplica a la instantánea
(``apply_unsaved_deletions``: vuelve a ganar lo que haya debajo del mod); un
``ValidationContext`` construido a mano lo da por inexistente. ``files`` limita las
reglas de archivo (``SCOPE_FILE``) a unas rutas (lo pone ``Validator.validate``);
``languages`` son las columnas que el proyecto rellena (``loc_untranslated``);
``read_count`` cuenta los archivos distintos que se leyeron.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from ..cancel import CancelCheck
from ..clausewitz.nodes import ClausewitzDate
from ..vfs.model import FileEntry, LayerKind, VfsSnapshot, matching_keys, winner
from ..vfs.paths import DESCRIPTOR_REL, VPath

PARSE_CACHE_SIZE = 64      # árboles analizados que recuerda un contexto (los archivos que consultan varias reglas)


@dataclass
class ValidationContext:
    snapshot: VfsSnapshot
    index: object                         # SymbolIndex
    loc: object                           # csvloc.LocalisationDB efectiva (mod + juego + sin guardar)
    rules: object                         # rules.GameRules
    overrides: Mapping[VPath, bytes] = field(default_factory=dict)
    date: ClausewitzDate | None = None    # fecha de trabajo (historia fechada)
    mapdata: object | None = None         # iteración 5
    game_only: bool = False               # contexto de la línea base: solo la capa del juego
    cancelled: CancelCheck = None
    # Ampliaciones de la iteración 3:
    files: Collection[str] | None = None  # rel.key de los archivos de las reglas SCOPE_FILE (None: todos)
    languages: tuple[str, ...] = ("en", "es")

    def __post_init__(self) -> None:
        self._overrides = {VPath.of(rel).key: (VPath.of(rel), data) for rel, data in dict(self.overrides).items()}
        self._parsed: OrderedDict[str, object] = OrderedDict()
        self._read: set[str] = set()

    # --- archivos ---------------------------------------------------------------------------------

    def entry(self, rel: VPath) -> FileEntry | None:
        """Ganador de ``rel`` en la instantánea (None si solo existe como documento sin guardar o no existe)."""
        return self.snapshot.resolve(rel)

    def stack(self, rel: VPath) -> list[FileEntry]:
        """Todas las capas que tienen ``rel`` (ganador primero, ocultos incluidos). Ampliación."""
        return self.snapshot.stack(rel)

    def hidden(self, rel: VPath) -> bool:
        """True si ``replace_path`` oculta el archivo del juego de ``rel``. Ampliación."""
        return VPath.of(rel).key in self.snapshot.hidden

    def unsaved(self, rel: VPath) -> bool:
        """True si ``rel`` tiene un documento sin guardar (también uno borrado). Ampliación."""
        return VPath.of(rel).key in self._overrides

    def layer_of(self, rel: VPath) -> LayerKind | None:
        """Capa del ganador; ``LayerKind.MOD`` para un documento sin guardar."""
        key = VPath.of(rel).key
        if key in self._overrides:
            return LayerKind.MOD if self._overrides[key][1] is not None else None
        entry = self.snapshot.resolve(rel)
        return None if entry is None else entry.layer.kind

    def read(self, rel: VPath) -> bytes | None:
        """Bytes efectivos de ``rel`` (el documento sin guardar si lo hay); None si no existe o no se puede leer."""
        key = VPath.of(rel).key
        self._read.add(key)
        if key in self._overrides:
            return self._overrides[key][1]
        entry = self.snapshot.resolve(rel)
        return None if entry is None else self.read_entry(entry)

    def read_entry(self, entry: FileEntry) -> bytes | None:
        """Bytes del archivo de una capa concreta (para comparar capas); None si no se puede leer. Ampliación."""
        self._read.add(entry.rel.key)
        try:
            return entry.path.read_bytes()
        except OSError:
            return None

    def identical(self, a: FileEntry, b: FileEntry) -> bool:
        """True si los archivos de dos entradas son iguales byte a byte (por trozos, sin cargarlos enteros); False
        si no se pueden leer. Ampliación (``mod_shadow_identical``)."""
        if a.fingerprint.size != b.fingerprint.size:
            return False
        self._read.update((a.rel.key, b.rel.key))
        try:
            with open(a.path, "rb") as first, open(b.path, "rb") as second:
                while True:
                    chunk = first.read(1 << 20)
                    if chunk != second.read(1 << 20):
                        return False
                    if not chunk:
                        return True
        except OSError:
            return False

    def parse(self, rel: VPath):
        """``clausewitz.ParseResult`` de ``read(rel)`` (en caché por contexto); None si no existe."""
        key = VPath.of(rel).key
        cached = self._parsed.get(key)
        if cached is not None:
            self._parsed.move_to_end(key)
            return cached
        data = self.read(rel)
        if data is None:
            return None
        from ..project.codecs import parse_bytes

        result = parse_bytes(data)
        self._parsed[key] = result
        while len(self._parsed) > PARSE_CACHE_SIZE:
            self._parsed.popitem(last=False)
        return result

    def rels(self, folder: str, pattern: str = "*.txt") -> list[VPath]:
        """Rutas efectivas bajo ``folder`` (con los documentos nuevos sin guardar), ordenadas."""
        found: dict[str, VPath] = {e.rel.key: e.rel for e in self.snapshot.list(folder, pattern)}
        for key in matching_keys(self._overrides.keys(), folder, pattern, None):
            rel, data = self._overrides[key]
            if data is None:
                found.pop(key, None)
            else:
                found[key] = rel
        return [found[key] for key in sorted(found)]

    def all_rels(self) -> list[VPath]:
        """Todas las rutas efectivas (ganadores de la instantánea más documentos nuevos, sin los borrados), sin el
        descriptor. Ampliación."""
        found: dict[str, VPath] = {}
        for key, stack in self.snapshot.entries.items():
            if key == DESCRIPTOR_REL.key:
                continue
            entry = winner(stack, key in self.snapshot.hidden)
            if entry is not None:
                found[key] = entry.rel
        for key, (rel, data) in self._overrides.items():
            if key == DESCRIPTOR_REL.key:
                continue
            if data is None:
                found.pop(key, None)
            else:
                found[key] = rel
        return [found[key] for key in sorted(found)]

    def wants(self, rel: VPath) -> bool:
        """True si una regla de archivo debe revisar ``rel`` (``files`` vacío o None: todos). Ampliación."""
        return self.files is None or VPath.of(rel).key in self.files

    @property
    def read_count(self) -> int:
        return len(self._read)

    @property
    def start_date(self) -> ClausewitzDate:
        """La fecha a la que se miran las historias: la de trabajo o, si no, la de inicio del juego."""
        if self.date is not None:
            return self.date
        return getattr(self.rules, "start_date", ClausewitzDate(1836, 1, 1))


def build_context(snapshot: VfsSnapshot, index, overrides: Mapping[VPath, bytes] | None = None, *,
                  date: ClausewitzDate | None = None, loc=None, game_only: bool = False,
                  cancelled: CancelCheck = None) -> ValidationContext:
    """Contexto completo: si no se da ``loc``, construye la ``LocalisationDB`` efectiva de ``localisation/*.csv``
    (``LocalisationDB.from_entries``); calcula ``GameRules.from_snapshot``.

    Con ``game_only`` la instantánea se reduce a la capa del juego (``game_only_snapshot``) y no se usan
    ``overrides`` (línea base, I11). ``index=None`` construye el índice de esa vista con la caché de
    ``core.appdirs`` (``FactsCache()``).
    """
    from ..rules.game import GameRules

    overrides = {} if game_only else dict(overrides or {})
    snapshot, overrides = apply_unsaved_deletions(snapshot, overrides)
    if game_only:
        snapshot = game_only_snapshot(snapshot)
        if index is not None and any(f.layer is not LayerKind.GAME for f in index.facts()):
            index = None      # el índice con el mod daría una línea base falsa: se usa el del juego solo
    if index is None:
        from ..index import FactsCache, build_index

        index = build_index(snapshot, FactsCache(), overrides, cancelled=cancelled)
    if loc is None:
        loc = effective_localisation(snapshot, overrides)
    rules = GameRules.from_snapshot(snapshot, overrides)
    return ValidationContext(snapshot, index, loc, rules, MappingProxyType(overrides), date, None, game_only,
                             cancelled)


def apply_unsaved_deletions(snapshot: VfsSnapshot, overrides: Mapping[VPath, bytes | None]
                            ) -> tuple[VfsSnapshot, dict[VPath, bytes]]:
    """La vista con los borrados sin guardar aplicados: un ``override`` ``None`` quita el archivo del mod de su pila,
    así que vuelve a ganar lo de debajo (el juego o una dependencia, salvo que ``replace_path`` lo oculte), y deja de
    ser un ``override``. Sin esto, borrar la copia del mod de un archivo del juego lo daba por inexistente.
    """
    deleted = {VPath.of(rel).key for rel, data in overrides.items() if data is None}
    kept = {rel: data for rel, data in overrides.items() if data is not None}
    if not deleted:
        return snapshot, kept
    entries = dict(snapshot.entries)
    for key in deleted:
        stack = tuple(e for e in entries.get(key, ()) if e.layer.kind is not LayerKind.MOD)
        if stack:
            entries[key] = stack
        else:
            entries.pop(key, None)
    return replace(snapshot, entries=MappingProxyType(entries)), kept


def effective_localisation(snapshot: VfsSnapshot, overrides: Mapping[VPath, bytes] | None = None):
    """``LocalisationDB`` de los CSV efectivos de ``localisation/`` (ganador de cada nombre más los documentos sin
    guardar), en orden de carga. Un archivo que no se puede leer se omite. Ampliación."""
    from ..csvloc.db import LocalisationDB
    from ..csvloc.serialization import parse_csv
    from ..encoding import decode_bytes

    position = {id(layer): index for index, layer in enumerate(snapshot.layers)}
    mod_position = next((i for i, layer in enumerate(snapshot.layers) if layer.kind is LayerKind.MOD), 0)
    by_key: dict[str, tuple[VPath, FileEntry | None, bytes | None]] = {}
    for key in matching_keys(snapshot.entries.keys(), "localisation", "*.csv", False):
        entry = winner(snapshot.entries[key], key in snapshot.hidden)
        if entry is not None:
            by_key[key] = (entry.rel, entry, None)
    overridden = dict(overrides or {})
    for key in matching_keys({VPath.of(r).key for r in overridden}, "localisation", "*.csv", False):
        rel, data = next((VPath.of(r), d) for r, d in overridden.items() if VPath.of(r).key == key)
        if data is None:
            by_key.pop(key, None)
        else:
            by_key[key] = (rel, None, data)
    files = []
    folders: dict[str, tuple[int, object]] = {}
    for key in sorted(by_key):
        rel, entry, data = by_key[key]
        try:
            raw = data if data is not None else entry.path.read_bytes()
        except OSError:
            continue
        decoded = decode_bytes(raw)
        file = parse_csv(decoded.text, encoding=decoded.encoding)
        file.path = entry.path if entry is not None else _virtual_path(snapshot, rel)
        files.append(file)
        rank = position.get(id(entry.layer), len(position)) if entry is not None else mod_position
        folders.setdefault(str(file.path.parent), (rank, file.path.parent))
    dirs = [folder for _, folder in sorted(folders.values(), key=lambda item: item[0])]
    return LocalisationDB.from_entries(files, dirs=dirs)


def _virtual_path(snapshot: VfsSnapshot, rel: VPath):
    """Ruta en el mod de un CSV nuevo sin guardar (solo para ordenar y mostrar; nunca se escribe)."""
    from pathlib import Path

    mod = next((layer.root for layer in snapshot.layers if layer.kind is LayerKind.MOD), None)
    return (Path(mod) if mod is not None else Path(".")).joinpath(*rel.parts)


def game_only_snapshot(snapshot: VfsSnapshot) -> VfsSnapshot:
    """La misma instantánea con solo la capa del juego (contexto de la línea base, I11).

    ``replace_path`` no se aplica: sin el mod, el juego base carga todos sus archivos.
    """
    layers = tuple(layer for layer in snapshot.layers if layer.kind is LayerKind.GAME)
    entries = {}
    for key, stack in snapshot.entries.items():
        kept = tuple(e for e in stack if e.layer.kind is LayerKind.GAME)
        if kept:
            entries[key] = kept
    return VfsSnapshot(layers, MappingProxyType(entries), frozenset())
