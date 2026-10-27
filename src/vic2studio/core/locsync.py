"""``LocSync``: editar la localización con la política del juego (wizard §8, D6).

Gana la primera clave cargada: los CSV se cargan por orden alfabético de nombre
(``csvloc.db.load_order_key``) y un CSV del mod sustituye al del juego con el mismo
nombre (la VFS ya lo resuelve). Al escribir un texto:

- **clave nueva** → fila en ``localisation/00_<P>_<área>.csv`` (``countries``,
  ``events``…); si ya hay un archivo del mod que sigue el patrón, se reutiliza;
- **clave cuyo ganador está en un archivo del mod** → se edita en su sitio
  (``LocRow.set``); en VSM, su copia de ``text.csv`` (diff de 1 línea);
- **clave cuyo ganador está en el juego** → fila en
  ``localisation/00_<P>_overrides.csv``, que carga antes que ``text.csv`` y gana.
  Nunca se copia el CSV del juego. La fila nueva copia los 13 idiomas de la del juego
  (solo cambia el que se edita): sobrescribir una clave no borra sus otras traducciones.
  Si algún archivo de las capas de abajo cargara antes que ``00_<P>_overrides.csv``, el
  nombre se adelanta con ceros (``000_<P>_overrides.csv``) hasta que gane.

Formato de un archivo nuevo: imita a los del mod (cabecera ``key;English;…`` si
los del usuario la llevan, copiada tal cual, y su convención de marcador ``x``, por
mayoría de sus filas); si no hay ninguno, el de vanilla (clave, 13 idiomas y ``x``,
cp1252 y CRLF). Una fila que se añade a un archivo existente sigue la convención de
ese archivo, y editar una fila conserva la suya (``LocRow.set(keep_layout=True)``). Un
``;`` o un salto de línea en un texto se rechazan antes de escribir (``check_text``,
``InvalidFieldError``); un carácter que no cabe en cp1252 lo rechaza el ``Workspace`` al
cerrar la transacción (``UnencodableTextError``). Se rellenan las columnas de
``languages``; ``copy_en_to`` copia el inglés a francés o alemán cuando esa columna está
vacía o tenía la copia del inglés anterior (nunca pisa una traducción de verdad). Todo
son ediciones del ``Workspace`` dentro de la transacción de quien llama: deshacibles con
ella. Python puro, en el hilo del ``Workspace`` (I12).

**Vista efectiva** (I7): los ganadores de ``localisation/*.csv`` en la VFS más los
documentos abiertos en el ``Workspace`` (sus modelos vivos, también los nuevos sin
guardar; un documento borrado deja ver lo que hay debajo). Los archivos del disco que
no están abiertos se leen una vez y se guardan por huella; ``read_localisation`` los
lee en un hilo de fondo (sin tocar el ``Workspace``) y ``adopt`` los incorpora, para que
la primera tabla no lea megas en el hilo de la interfaz. Leer nunca escribe (I4).

Indicadores de ``LocEntry`` (filtros de la sala Textos): ``created_by_studio`` (el
ganador es un ``00_<P>_<área>.csv`` del mod), ``overrides_game`` (el juego base o una
dependencia también la define y gana el mod) y ``degraded`` (H15: la fila del CSV del
mod que sustituye a uno del juego con el mismo nombre solo difiere de la del juego por
«?» donde había un carácter no ASCII, a veces junto con el carácter siguiente, como en
``Efficacit?fiscale`` frente a ``Efficacité fiscale``). La fila de cabecera
(``key;English;…``) no cuenta como clave.
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .cancel import CancelCheck, raise_if_cancelled
from .csvloc.db import LocalisationDB, load_order_key
from .csvloc.lint import is_header_row
from .csvloc.model import (
    LANGUAGE_CODES,
    LANGUAGE_COUNT,
    LocalisationFile,
    LocRow,
    check_key,
    check_text,
    language_column,
    normalized_fields,
)
from .encoding import GAME_ENCODING
from .vfs.model import DocKind, FileEntry, LayerKind
from .vfs.paths import VPath

log = logging.getLogger(__name__)

AREA_OVERRIDES = "overrides"
# Áreas de los archivos nuevos (wizard §8); la interfaz las ofrece al añadir una clave.
AREAS = ("countries", "events", "decisions", "cb", "governments", "units", "cultures", "map", "misc",
         AREA_OVERRIDES)
LOCALISATION_FOLDER = "localisation"
# Idiomas que muestra el juego (los de las columnas que ve el jugador) y que siempre lleva ``LocEntry.texts``.
DISPLAYED = ("en", "fr", "de", "es")
NEW_FILE_NEWLINE = "\r\n"
_LANG_BY_COLUMN = {column: code for code, column in LANGUAGE_CODES.items()}
_OVERRIDES_TRIES = 12


def is_localisation_rel(rel: str | VPath) -> bool:
    """True si el juego carga ``rel`` como localización: un ``.csv`` directamente en ``localisation/``."""
    rel = VPath.of(rel)
    parts = rel.parts
    return len(parts) == 2 and parts[0].lower() == LOCALISATION_FOLDER and rel.suffix == ".csv"


@dataclass(frozen=True)
class LocEntry:
    """Una clave efectiva para la tabla de la sala Textos."""

    key: str
    texts: Mapping[str, str]            # idioma → texto efectivo («en», «fr», «de», «es»…)
    rel: VPath                          # archivo ganador
    line: int | None
    layer: LayerKind                    # capa del archivo ganador (MOD para un documento sin guardar)
    created_by_studio: bool             # está en un 00_<P>_<área>.csv del mod
    overrides_game: bool                # el juego también la define y el mod gana («sustituye a vanilla»)
    degraded: bool                      # difiere de la del juego solo por «?» en lugar de letras acentuadas (H15)


# --- lectura en segundo plano -------------------------------------------------------------------------------


class LocalisationReadout:
    """CSV leídos del disco por ``read_localisation`` (en cualquier hilo): ``files`` y ``errors``.

    Quien la recibe la conserva mientras use sus archivos (``ui.tasks`` vigila los resultados grandes).
    """

    __slots__ = ("files", "errors", "__weakref__")

    def __init__(self, files: list[tuple[FileEntry, LocalisationFile]], errors: list[tuple[FileEntry, str]]):
        self.files = files
        self.errors = errors


def _load_csv(data: bytes) -> LocalisationFile:
    """El mismo modelo que abriría el ``Workspace`` (``LocalisationCodec``)."""
    from .project.codecs import codec_for

    return codec_for(DocKind.LOCALISATION).load(data, VPath.of("localisation/x.csv"))[0]


def read_localisation(entries: Iterable[FileEntry], *, cancelled: CancelCheck = None) -> LocalisationReadout:
    """Lee y analiza ``entries`` (sin tocar el ``Workspace``): apto para un hilo de fondo. Lanza ``Cancelled``."""
    files, errors = [], []
    for entry in entries:
        raise_if_cancelled(cancelled)
        try:
            data = entry.path.read_bytes()
        except OSError as exc:
            errors.append((entry, f"{type(exc).__name__}: {exc}"))
            continue
        files.append((entry, _load_csv(data)))
    return LocalisationReadout(files, errors)


# --- filas degradadas (H15) ----------------------------------------------------------------------------------


def is_degraded_copy(mod_fields: Sequence[str], game_fields: Sequence[str]) -> bool:
    """True si la fila del mod solo difiere de la del juego por «?» donde había un carácter no ASCII (H15).

    Cada «?» del mod puede ser un «?» del juego, o un carácter no ASCII del juego más, a veces, el siguiente
    (la conversión rota se comió también un espacio o un «;»).
    """
    a, b = ";".join(mod_fields), ";".join(game_fields)
    if a == b or "?" not in a or len(a) > len(b):
        return False
    parts = a.split("?")
    last = len(parts) - 1
    pending, seen = [(0, 0)], set()
    while pending:
        state = pending.pop()
        if state in seen:
            continue
        seen.add(state)
        k, j = state
        piece = parts[k]
        if not b.startswith(piece, j):
            continue
        j += len(piece)
        if k == last:
            if j == len(b):
                return True
            continue
        if j >= len(b):
            continue
        char = b[j]
        if char == "?":
            pending.append((k + 1, j + 1))
        elif ord(char) > 127:
            pending.append((k + 1, j + 1))
            if j + 1 < len(b):
                pending.append((k + 1, j + 2))
    return False


# --- vista efectiva ------------------------------------------------------------------------------------------


class _Source:
    """Un archivo efectivo: del disco (``entry``) o documento del ``Workspace`` (``handle``)."""

    __slots__ = ("rel", "layer", "entry", "handle")

    def __init__(self, rel: VPath, layer: LayerKind, entry: FileEntry | None, handle=None):
        self.rel = rel
        self.layer = layer
        self.entry = entry
        self.handle = handle

    def signature(self) -> tuple:
        if self.handle is not None:
            return (self.rel.key, "doc", id(self.handle.model), self.handle.version)
        fingerprint = self.entry.fingerprint
        return (self.rel.key, str(self.entry.path), fingerprint.size, fingerprint.mtime_ns)


class _Effective:
    """Base efectiva y, por archivo de la base, de dónde viene (``info``: id del archivo → ``_Source``)."""

    __slots__ = ("db", "info", "sources", "positions")

    def __init__(self, db: LocalisationDB, info: dict[int, _Source], sources: list[_Source]):
        self.db = db
        self.info = info
        self.sources = sources
        self.positions: dict[int, dict[int, int]] = {}

    def line_of(self, file: LocalisationFile, row: LocRow) -> int | None:
        """Línea actual de ``row`` (su posición: vale también tras editar y para filas nuevas)."""
        positions = self.positions.get(id(file))
        if positions is None:
            positions = self.positions[id(file)] = {id(r): i for i, r in enumerate(file.rows, 1)}
        return positions.get(id(row))


class LocSync:
    def __init__(self, ws, vfs, *, prefix: str, languages: Sequence[str] = ("en", "es"),
                 copy_en_to: Sequence[str] = ()) -> None:
        """``ws`` es el ``Workspace`` del proyecto y ``vfs`` su ``VirtualFS``."""
        self._ws = ws
        self._vfs = vfs
        self.prefix = prefix
        self.languages: tuple[str, ...] = tuple(languages)
        self.copy_en_to: tuple[str, ...] = tuple(copy_en_to)
        self._disk: dict[str, tuple[int, int, LocalisationFile]] = {}
        self._readouts: list[LocalisationReadout] = []
        self._effective: _Effective | None = None
        self._signature: tuple | None = None
        self._base: tuple[tuple, LocalisationDB, dict[str, LocalisationFile]] | None = None
        self._entries: tuple[tuple, list[LocEntry]] | None = None
        self.errors: dict[str, str] = {}     # ruta → motivo, de los CSV que no se pudieron leer

    # --- ajustes ---------------------------------------------------------------------------------------------

    def configure(self, *, prefix: str | None = None, languages: Sequence[str] | None = None,
                  copy_en_to: Sequence[str] | None = None) -> None:
        """Cambia los ajustes (``project.json`` cambió); los textos efectivos no cambian por ello."""
        if prefix is not None:
            self.prefix = prefix
        if languages is not None:
            self.languages = tuple(languages)
        if copy_en_to is not None:
            self.copy_en_to = tuple(copy_en_to)
        self.invalidate()

    def invalidate(self) -> None:
        """Olvida la base efectiva calculada (se recalcula en la próxima consulta)."""
        self._effective = None
        self._signature = None
        self._entries = None

    # --- lectura del disco -----------------------------------------------------------------------------------

    def disk_entries(self, *, missing_only: bool = True) -> list[FileEntry]:
        """Los CSV de ``localisation/`` de todas las capas que cuentan (para ``read_localisation``)."""
        found = []
        for winner in self._vfs.list(LOCALISATION_FOLDER, "*.csv", recursive=False):
            for entry in self._vfs.stack(winner.rel):
                if self._vfs.hidden_by_replace_path(entry):
                    continue
                if missing_only and self._cached(entry) is not None:
                    continue
                found.append(entry)
        return found

    def adopt(self, readout: LocalisationReadout) -> None:
        """Incorpora lo que leyó ``read_localisation`` (en el hilo del ``Workspace``)."""
        self._readouts.append(readout)
        for entry, file in readout.files:
            self._disk[str(entry.path)] = (entry.fingerprint.size, entry.fingerprint.mtime_ns, file)
        for entry, error in readout.errors:
            self.errors[str(entry.path)] = error
        self.invalidate()

    def _cached(self, entry: FileEntry) -> LocalisationFile | None:
        cached = self._disk.get(str(entry.path))
        if cached is not None and cached[:2] == (entry.fingerprint.size, entry.fingerprint.mtime_ns):
            return cached[2]
        return None

    def _disk_model(self, entry: FileEntry) -> LocalisationFile | None:
        file = self._cached(entry)
        if file is not None:
            return file
        readout = read_localisation([entry])
        self.adopt(readout)
        return readout.files[0][1] if readout.files else None

    # --- vista efectiva --------------------------------------------------------------------------------------

    def _below_mod(self, rel: VPath) -> FileEntry | None:
        """Lo que cargaría el juego en ``rel`` sin el archivo del mod (dependencia o juego, si no está oculto)."""
        for entry in self._vfs.stack(rel):
            if entry.layer.kind is not LayerKind.MOD and not self._vfs.hidden_by_replace_path(entry):
                return entry
        return None

    def _sources(self) -> list[_Source]:
        found: dict[str, _Source] = {}
        for entry in self._vfs.list(LOCALISATION_FOLDER, "*.csv", recursive=False):
            found[entry.rel.key] = _Source(entry.rel, entry.layer.kind, entry)
        for handle in self._ws.documents():
            rel = handle.rel
            if handle.kind is not DocKind.LOCALISATION or not is_localisation_rel(rel):
                continue
            if handle.deleted:
                below = self._below_mod(rel)
                if below is None:
                    found.pop(rel.key, None)
                else:
                    found[rel.key] = _Source(below.rel, below.layer.kind, below)
                continue
            origin = handle.origin
            if handle.dirty or origin is None or origin.layer.kind is LayerKind.MOD:
                layer = LayerKind.MOD
            else:
                layer = origin.layer.kind
            found[rel.key] = _Source(rel, layer, origin, handle)
        return sorted(found.values(), key=lambda s: load_order_key(s.rel.name))

    def _path_of(self, source: _Source) -> Path:
        if source.handle is None:
            return source.entry.path
        try:
            return self._vfs.mod_target(source.rel) if source.layer is LayerKind.MOD else source.entry.path
        except (OSError, ValueError, AttributeError):
            return Path(str(source.rel))

    def _state(self) -> _Effective:
        sources = self._sources()
        signature = tuple(s.signature() for s in sources)
        if self._effective is not None and signature == self._signature:
            return self._effective
        files, info = [], {}
        for source in sources:
            model = source.handle.model if source.handle is not None else self._disk_model(source.entry)
            if model is None:
                continue
            view = copy.copy(model)        # comparte las filas (vivas); solo la ruta es propia
            view.path = self._path_of(source)
            files.append(view)
            info[id(view)] = source
        self._effective = _Effective(LocalisationDB(files), info, sources)
        self._signature = signature
        return self._effective

    def _base_state(self, sources: list[_Source]) -> tuple[LocalisationDB, dict[str, LocalisationFile]]:
        """Lo que cargaría el juego sin el mod: la base para «sustituye a vanilla» y «degradadas»."""
        entries = []
        for source in sources:
            below = self._below_mod(source.rel)
            if below is not None:
                entries.append(below)
        signature = tuple((str(e.path), e.fingerprint.size, e.fingerprint.mtime_ns) for e in entries)
        if self._base is not None and self._base[0] == signature:
            return self._base[1], self._base[2]
        files, by_name = [], {}
        for entry in sorted(entries, key=lambda e: load_order_key(e.rel.name)):
            model = self._disk_model(entry)
            if model is None:
                continue
            files.append(model)
            by_name[entry.rel.name.upper()] = model
        db = LocalisationDB(files)
        self._base = (signature, db, by_name)
        return db, by_name

    def localisation_db(self) -> LocalisationDB:
        """``LocalisationDB`` efectiva: mod + juego + documentos sin guardar (modelos vivos del ``Workspace``).

        Sus archivos son vistas de los modelos (comparten las filas) con ``path`` real, así que ``source_of``
        da la ruta del disco (o el destino en el mod de un documento nuevo). Solo para el hilo del ``Workspace``.
        """
        return self._state().db

    # --- consultas -------------------------------------------------------------------------------------------

    def text(self, key: str, lang: str = "es") -> str | None:
        """Texto efectivo (I7: con los cambios sin guardar)."""
        return self._state().db.lookup(key, lang)

    def where(self, key: str) -> tuple[VPath, int] | None:
        """Archivo y línea ganadores."""
        state = self._state()
        file = state.db.file_of(key)
        if file is None:
            return None
        return state.info[id(file)].rel, state.line_of(file, state.db.entry(key))

    def _is_studio_name(self, name: str) -> bool:
        upper = name.upper()
        return upper.startswith(f"00_{self.prefix}_".upper()) and upper.endswith(".CSV")

    def _langs(self) -> tuple[tuple[str, int], ...]:
        """(idioma, posición en ``LocRow.fields``) de los textos de ``LocEntry``."""
        langs = DISPLAYED + tuple(lang for lang in self.languages if lang not in DISPLAYED)
        return tuple((lang, language_column(lang) - 1) for lang in langs)

    def _entry(self, state: _Effective, base: LocalisationDB, twins: dict[str, LocalisationFile], key: str,
               langs: tuple[tuple[str, int], ...]) -> LocEntry | None:
        file = state.db.file_of(key)
        row = state.db.entry(key)
        if file is None or (key.lower() == "key" and is_header_row(row)):
            return None
        source = state.info[id(file)]
        mod = source.layer is LayerKind.MOD
        overrides = mod and key in base
        degraded = False
        fields = row.fields
        if overrides:
            twin = twins.get(source.rel.name.upper())
            twin_row = twin.get_row(key) if twin is not None else None
            degraded = (twin_row is not None and twin_row.fields != fields
                        and is_degraded_copy(fields, twin_row.fields))
        size = len(fields)
        texts = {lang: fields[index] if index < size else "" for lang, index in langs}
        return LocEntry(key, MappingProxyType(texts), source.rel, state.line_of(file, row), source.layer,
                        mod and self._is_studio_name(source.rel.name), overrides, degraded)

    def entries(self) -> list[LocEntry]:
        """Todas las claves efectivas en orden de carga (para la tabla y sus filtros).

        La lista se reutiliza mientras no cambie nada (no la modifiques): consultarla otra vez cuesta lo que
        comprobar la firma de los archivos efectivos."""
        state = self._state()
        base, twins = self._base_state(state.sources)
        langs = self._langs()
        cache_key = (self._signature, self._base[0], langs, self.prefix)
        if self._entries is not None and self._entries[0] == cache_key:
            return self._entries[1]
        found = (self._entry(state, base, twins, key, langs) for key in state.db.keys())
        entries = [entry for entry in found if entry is not None]
        self._entries = (cache_key, entries)
        return entries

    def entry(self, key: str) -> LocEntry | None:
        """La ``LocEntry`` de una clave (None si no existe): refrescar una fila sin recalcularlas todas."""
        state = self._state()
        if key not in state.db:
            return None
        base, twins = self._base_state(state.sources)
        return self._entry(state, base, twins, key, self._langs())

    def untranslated(self, entry: LocEntry) -> list[str]:
        """Idiomas del proyecto (``languages``) en los que ``entry`` no tiene texto."""
        return [lang for lang in self.languages if not (entry.texts.get(lang) or "").strip()]

    def missing(self, keys: Iterable[str], langs: Sequence[str] = ("en", "es")) -> dict[str, list[str]]:
        """Clave → idiomas sin texto (o sin clave)."""
        db = self._state().db
        result = {}
        for key in keys:
            row = db.entry(key)
            gaps = list(langs) if row is None else [lang for lang in langs if not row.get(lang).strip()]
            if gaps:
                result[key] = gaps
        return result

    def orphans(self, index) -> list[str]:
        """Claves del mod que nada usa según el ``SymbolIndex`` (información).

        Cuenta como uso una referencia ``loc_key`` del índice o, para las claves que el juego busca por su
        nombre, que exista un símbolo con ese nombre (``AAA``, ``AAA_ADJ``, ``PROV1``, ``<cb>_desc``…).
        """
        from .index.model import KIND_LOC_KEY

        state = self._state()
        known = {name for kind in index.kinds() if kind != KIND_LOC_KEY for name in index.names(kind)}
        found = []
        for key in state.db.keys():
            source = state.info[id(state.db.file_of(key))]
            if source.layer is not LayerKind.MOD or is_header_row(state.db.entry(key)):
                continue
            if index.refs_to(KIND_LOC_KEY, key) or _implicit_use(key, known):
                continue
            found.append(key)
        return found

    # --- escritura -------------------------------------------------------------------------------------------

    def target_file(self, area: str) -> VPath:
        """``localisation/00_<P>_<area>.csv`` (o el del mod que ya siga el patrón)."""
        name = f"00_{self.prefix}_{area}.csv"
        for source in self._sources():
            if source.layer is LayerKind.MOD and source.rel.name.upper() == name.upper():
                return source.rel
        return VPath.of(f"{LOCALISATION_FOLDER}/{name}")

    def _require_txn(self) -> None:
        if not getattr(self._ws, "in_transaction", True):
            raise RuntimeError("LocSync escribe dentro de una transacción del Workspace (Session.edit)")

    def _overrides_rel(self, key: str, db: LocalisationDB) -> VPath:
        rel = self.target_file(AREA_OVERRIDES)
        name = rel.name
        for _ in range(_OVERRIDES_TRIES):
            if db.would_win(name, key):
                return rel if name == rel.name else VPath.of(f"{LOCALISATION_FOLDER}/{name}")
            name = "0" + name
        raise ValueError(f"ningún nombre de archivo del mod carga antes que el ganador de {key!r}")

    def _mod_files(self) -> list[LocalisationFile]:
        state = self._state()
        return [file for file in state.db.files if state.info[id(file)].layer is LayerKind.MOD]

    def _new_file_format(self) -> tuple[str | None, bool, str]:
        """(cabecera, con «x», salto de línea) de un archivo nuevo, imitando a los del mod."""
        header, newline, marked, unmarked = None, None, 0, 0
        for file in self._mod_files():
            first = next(file.data_rows(), None)
            if header is None and first is not None and is_header_row(first):
                header = first.to_line()
            if newline is None and file.rows:
                newline = file.newline
            for row in file.data_rows():
                if not is_header_row(row):
                    marked += row.has_end_marker
                    unmarked += not row.has_end_marker
        return header, marked >= unmarked, newline or NEW_FILE_NEWLINE

    @staticmethod
    def _file_marker(file: LocalisationFile, default: bool) -> bool:
        marked = unmarked = 0
        for row in file.data_rows():
            if not is_header_row(row):
                marked += row.has_end_marker
                unmarked += not row.has_end_marker
        return default if marked == unmarked == 0 else marked >= unmarked

    def _new_model(self) -> tuple[LocalisationFile, bool]:
        from .csvloc.serialization import parse_csv

        header, marker, newline = self._new_file_format()
        model = parse_csv(header + newline, encoding=GAME_ENCODING) if header else LocalisationFile(
            encoding=GAME_ENCODING, newline=newline)
        model.newline = newline
        return model, marker

    def _open_for_write(self, rel: VPath):
        """Documento de ``rel`` listo para mutar (abierto y tocado, o creado con el formato del mod)."""
        ws = self._ws
        handle = ws.peek(rel)
        if handle is None and self._vfs.resolve(rel) is not None:
            handle = ws.open(rel)
        if handle is None or handle.deleted:
            model, _ = self._new_model()
            return ws.create(rel, DocKind.LOCALISATION, model)
        ws.touch(handle)
        return handle

    def _texts_for(self, column: int, text: str, base: Mapping[int, str] | None = None) -> dict[int, str]:
        """Columnas de una fila nueva: ``base`` (p. ej. la fila del juego), ``text`` en ``column`` y, si es el
        inglés, su copia en ``copy_en_to`` donde no haya traducción (vacía o igual al inglés anterior)."""
        texts = dict(base or {})
        english = LANGUAGE_CODES["en"]
        previous = texts.get(english, "")
        texts[column] = text
        if column == english:
            for lang in self.copy_en_to:
                target = language_column(lang)
                if (texts.get(target) or "") in ("", previous):
                    texts[target] = text
        return texts

    def _append(self, handle, key: str, texts: Mapping[int, str]) -> LocRow:
        file: LocalisationFile = handle.model
        _, default_marker, _ = self._new_file_format()
        return file.add_row(key, texts, end_marker=self._file_marker(file, default_marker))

    def set_text(self, key: str, lang: str, text: str, *, area: str = AREA_OVERRIDES) -> VPath:
        """Escribe ``text`` según la política; devuelve el archivo tocado. ``InvalidFieldError`` si no vale.
        Debe llamarse dentro de una transacción del ``Workspace``."""
        self._require_txn()
        column = language_column(lang)
        check_text(text)
        state = self._state()
        db = state.db
        winner = db.file_of(key)
        if winner is None:
            check_key(key)
            handle = self._open_for_write(self.target_file(area))
            self._append(handle, key, self._texts_for(column, text))
        elif state.info[id(winner)].layer is LayerKind.MOD:
            source = state.info[id(winner)]
            handle = source.handle if source.handle is not None and not source.handle.deleted else None
            if handle is None:
                handle = self._ws.open(source.rel)
            self._ws.touch(handle)
            row = handle.model.get_row(key)
            old_english = row.get("en")
            row.set(column, text, keep_layout=True)
            if column == LANGUAGE_CODES["en"]:
                for target in self.copy_en_to:
                    if row.get(target) in ("", old_english):
                        row.set(target, text, keep_layout=True)
        else:
            rel = self._overrides_rel(key, db)
            game_row = db.entry(key)
            handle = self._open_for_write(rel)
            existing = handle.model.get_row(key)
            if existing is not None:
                existing.set(column, text, keep_layout=True)
            else:
                # Los idiomas de la fila del juego, sin su «x» (en las filas cortas está desplazada).
                languages = normalized_fields(game_row.fields)[:LANGUAGE_COUNT]
                copied = {c: text for c, text in enumerate(languages, 1) if text}
                self._append(handle, key, self._texts_for(column, text, copied))
        self.invalidate()
        return handle.rel

    def ensure(self, keys: Mapping[str, Mapping[str, str]], *, area: str) -> list[str]:
        """Crea las claves que falten (``clave → {idioma: texto}``); devuelve las creadas."""
        self._require_txn()
        db = self._state().db
        wanted: list[tuple[str, dict[int, str]]] = []
        for key, texts in keys.items():
            check_key(key)
            columns: dict[int, str] = {}
            for lang, text in texts.items():
                check_text(text)
                columns[language_column(lang)] = text
            if key in db or any(key == k for k, _ in wanted):
                continue
            english = columns.get(LANGUAGE_CODES["en"])
            if english is not None:
                columns = self._texts_for(LANGUAGE_CODES["en"], english, columns)
            wanted.append((key, columns))
        if not wanted:
            return []
        handle = self._open_for_write(self.target_file(area))
        for key, columns in wanted:
            self._append(handle, key, columns)
        self.invalidate()
        return [key for key, _ in wanted]

    def _mod_handles_with(self, key: str) -> list:
        """Documentos del mod (abiertos o por abrir) que tienen filas con ``key``."""
        state = self._state()
        found = []
        for file in state.db.files:
            source = state.info[id(file)]
            if source.layer is LayerKind.MOD and key in file:
                found.append(source)
        return found

    def rename(self, old: str, new: str) -> None:
        """Renombra la clave en las filas del mod (nunca toca el juego)."""
        from .csvloc.model import DuplicateKeyError

        self._require_txn()
        check_key(new)
        if new == old:
            return
        sources = self._mod_handles_with(old)
        state = self._state()
        for file in state.db.files:   # todo o nada: se comprueba antes de cambiar ninguno
            if state.info[id(file)] in sources and new in file:
                raise DuplicateKeyError(new)
        for source in sources:
            handle = source.handle if source.handle is not None else self._ws.open(source.rel)
            self._ws.touch(handle)
            handle.model.rename_key(old, new, all=True)
        self.invalidate()

    def delete(self, key: str) -> None:
        """Quita las filas del mod; nunca borra del juego."""
        self._require_txn()
        for source in self._mod_handles_with(key):
            handle = source.handle if source.handle is not None else self._ws.open(source.rel)
            self._ws.touch(handle)
            handle.model.remove_row(key)
        self.invalidate()


# Prefijos y sufijos de las claves que el juego busca a partir del nombre de un símbolo.
_IMPLICIT_SUFFIXES = ("_ADJ", "_desc", "_title", "_setup", "_short", "_name")
_IMPLICIT_PREFIXES = ("NORMAL_", "AGRESSION_")
_PARTY_GOVERNMENT_RE = re.compile(r"^([A-Z][A-Z0-9]{2})_")


def _implicit_use(key: str, known: set[str]) -> bool:
    if key in known:
        return True
    for suffix in _IMPLICIT_SUFFIXES:
        if key.endswith(suffix) and key[:-len(suffix)] in known:
            return True
    for prefix in _IMPLICIT_PREFIXES:
        if key.startswith(prefix) and key[len(prefix):] in known:
            return True
    if key.startswith("PROV") and key[4:] in known:
        return True
    match = _PARTY_GOVERNMENT_RE.match(key)        # «AGC_absolute_monarchy», «AGC_conservative»
    return bool(match and match.group(1) in known and key[4:] in known)


__all__ = [
    "AREAS", "AREA_OVERRIDES", "DISPLAYED", "LOCALISATION_FOLDER", "LocEntry", "LocSync", "LocalisationReadout",
    "is_degraded_copy", "is_localisation_rel", "read_localisation",
]
