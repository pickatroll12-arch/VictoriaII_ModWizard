"""Base de datos de localización: varias carpetas fusionadas como las carga el juego.

Reglas (mod antes que vanilla):

* De cada carpeta se toman los ``*.csv`` (sin distinguir mayúsculas en la
  extensión ni en el nombre, como en Windows). Si dos carpetas tienen un archivo
  con el mismo nombre, se usa el de la primera y el otro se ignora entero.
* Los archivos resultantes se cargan en orden alfabético de nombre, sin
  distinguir mayúsculas (orden de NTFS: se comparan los nombres en mayúsculas),
  sin importar de qué carpeta venga cada uno.
* Si una clave aparece más de una vez gana la primera cargada; por eso los mods
  nombran sus archivos con prefijos como ``00_`` para cargarse antes que
  ``text.csv``.

La base es una instantánea: tras editar sus archivos por fuera hay que llamar a
``rebuild``; ``define`` y ``add_file`` la mantienen al día por sí solos. Las
claves se comparan tal cual, distinguiendo mayúsculas (vanilla tiene pares como
``CANCEL``/``cancel``). Si el mod sustituye la carpeta entera
(``replace_path = "localisation"``, ver ``ModDescriptor.replaces``), basta con
no pasar la de vanilla.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import Iterable, Mapping, Union

from ..cancel import CancelCheck, Cancelled
from .model import Lang, LocalisationFile, LocRow, RowKind, check_text, language_column
from .serialization import read_csv_file

PathLike = Union[str, os.PathLike]
Location = tuple[Union[Path, None], Union[int, None]]


@dataclass(frozen=True)
class KeyOverride:
    """Clave definida varias veces: ``winner`` es la que usa el juego."""

    key: str
    winner: Location
    shadowed: tuple[Location, ...]


def load_order_key(name: str) -> tuple[str, str]:
    return name.upper(), name


def _same_file(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _location(file: LocalisationFile, row: LocRow) -> Location:
    line = row.line
    if line is None:
        # Fila nueva: ``define`` (y casi siempre ``add_row``) la añade al final, así que se busca desde allí.
        rows = file.rows
        line = next((n for n in range(len(rows), 0, -1) if rows[n - 1] is row), None)
    return file.path, line


class LocalisationDB:
    """Índice de claves sobre una lista ordenada de archivos (el primero tiene prioridad).

    ``dirs`` son las carpetas de ``from_dirs`` (vacía si se construye a mano) y
    ``errors`` los archivos que no se pudieron leer, con su excepción.
    """

    def __init__(self, files: Iterable[LocalisationFile] = ()):
        self.files: list[LocalisationFile] = list(files)
        self.dirs: list[Path] = []
        # (archivo ignorado, archivo de una carpeta anterior que lo sustituye)
        self.replaced_files: list[tuple[Path, Path]] = []
        self.errors: list[tuple[Path, Exception]] = []
        self._first: dict[str, tuple[LocalisationFile, LocRow]] = {}
        self._later: dict[str, list[tuple[LocalisationFile, LocRow]]] = {}
        # Claves que gana cada archivo (por id), en orden de fila y con los archivos en orden de
        # carga: encadenadas son ``keys``. ``define`` solo añade filas al final de un archivo, así
        # que mantener este orden le cuesta O(1).
        self._won: dict[int, dict[str, None]] = {}
        self.rebuild()

    @classmethod
    def from_dirs(cls, dirs: PathLike | Iterable[PathLike], *, encoding: str | None = None,
                  cancelled: CancelCheck = None) -> LocalisationDB:
        """Carga las carpetas en orden de prioridad (mod primero, vanilla después).

        Las carpetas que no existen se omiten; un archivo que no se puede leer
        no detiene la carga y queda en ``errors``. Si ``cancelled()`` devuelve
        True lanza ``core.cancel.Cancelled``.
        """
        if isinstance(dirs, (str, os.PathLike)):
            dirs = [dirs]
        dirs = [Path(d) for d in dirs]
        chosen: dict[str, Path] = {}
        replaced: list[tuple[Path, Path]] = []
        for directory in dirs:
            if not directory.is_dir():
                continue
            for path in sorted(directory.iterdir(), key=lambda p: load_order_key(p.name)):
                if path.suffix.lower() != ".csv" or not path.is_file():
                    continue
                name = path.name.upper()
                if name in chosen:
                    replaced.append((path, chosen[name]))
                else:
                    chosen[name] = path
        files, errors = [], []
        for path in sorted(chosen.values(), key=lambda p: load_order_key(p.name)):
            try:
                files.append(read_csv_file(path, encoding=encoding, cancelled=cancelled))
            except Cancelled:
                raise
            except (OSError, ValueError, LookupError) as exc:
                errors.append((path, exc))
        db = cls(files)
        db.dirs, db.replaced_files, db.errors = dirs, replaced, errors
        return db

    def rebuild(self) -> None:
        first: dict[str, tuple[LocalisationFile, LocRow]] = {}
        later: dict[str, list[tuple[LocalisationFile, LocRow]]] = {}
        won: dict[int, dict[str, None]] = {}
        data = RowKind.DATA
        for file in self.files:
            mine = won.setdefault(id(file), {})
            for row in file.rows:
                key = row.key
                if row.kind is not data or not key:
                    continue
                if key in first:
                    later.setdefault(key, []).append((file, row))
                else:
                    first[key] = (file, row)
                    mine[key] = None
        self._first, self._later, self._won = first, later, won

    def _dir_index(self, path: Path | None) -> int | None:
        """Índice en ``dirs`` de la carpeta de ``path`` (0 = la de más prioridad); ``None`` si no es de ninguna."""
        if path is None:
            return None
        folder = os.path.normcase(os.path.abspath(path.parent))
        return next((i for i, d in enumerate(self.dirs) if os.path.normcase(os.path.abspath(d)) == folder), None)

    def add_file(self, file: LocalisationFile) -> None:
        """Añade un archivo en su sitio del orden de carga del juego (por nombre).

        Si ya hay uno con el mismo nombre, se queda el de la carpeta con más
        prioridad de ``dirs``, como en ``from_dirs``, y el otro se anota en
        ``replaced_files``. Si son el mismo archivo (al recargarlo) o alguno no es
        de ``dirs``, el nuevo sustituye al anterior. Un archivo sin ruta va al final
        (menor prioridad).
        """
        if file.path is not None:
            name = file.path.name.upper()
            other = next((f for f in self.files if f.path is not None and f.path.name.upper() == name), None)
            if other is not None:
                if not _same_file(other.path, file.path):
                    mine, theirs = self._dir_index(file.path), self._dir_index(other.path)
                    if mine is not None and theirs is not None and theirs < mine:
                        # Sigue ganando el de la carpeta con más prioridad: el nuevo se ignora, como en from_dirs.
                        if (file.path, other.path) not in self.replaced_files:
                            self.replaced_files.append((file.path, other.path))
                        return
                    # Lo que tapaba el anterior lo tapa ahora el nuevo.
                    self.replaced_files = [(ignored, file.path if winner == other.path else winner)
                                           for ignored, winner in self.replaced_files]
                    self.replaced_files.append((other.path, file.path))
                self.files.remove(other)
            order = load_order_key(file.path.name)
            position = next((i for i, other in enumerate(self.files)
                             if other.path is None or load_order_key(other.path.name) > order), len(self.files))
            self.files.insert(position, file)
        else:
            self.files.append(file)
        self.rebuild()

    def define(self, key: str, texts: Mapping[Lang, str], file: LocalisationFile) -> LocRow:
        """Escribe los textos de ``key`` en ``file`` (uno de ``files``) y actualiza la base sin reconstruirla.

        Si ``file`` no tiene la clave, añade la fila al final de ``file``; si la
        tiene, cambia esos textos en su primera fila. Para que la definición sea la
        que use el juego, ``file`` debe cargarse antes que el ganador actual (ver
        ``would_win``).
        """
        order = next((i for i, other in enumerate(self.files) if other is file), None)
        if order is None:
            raise ValueError(f"{file!r} no es un archivo de esta base")
        row = file.get_row(key)
        if row is not None:
            for lang, text in texts.items():  # todo o nada
                language_column(lang)
                check_text(text)
            for lang, text in texts.items():
                row.set(lang, text)
            return row
        row = file.add_row(key, texts)
        positions = {id(other): i for i, other in enumerate(self.files)}
        entries = [self._first[key], *self._later.get(key, ())] if key in self._first else []
        # Las demás definiciones de ``file`` (ninguna, porque no tenía la clave) irían antes.
        at = next((i for i, (other, _) in enumerate(entries) if positions[id(other)] > order), len(entries))
        entries.insert(at, (file, row))
        if at == 0:
            # Gana la fila nueva, la última de ``file``: la clave va tras las demás que gana ``file``.
            if len(entries) > 1:
                self._won[id(entries[1][0])].pop(key, None)
            self._won.setdefault(id(file), {})[key] = None
        self._first[key] = entries[0]
        if len(entries) > 1:
            self._later[key] = entries[1:]
        return row

    def __contains__(self, key: object) -> bool:
        return key in self._first

    def __len__(self) -> int:
        return len(self._first)

    def keys(self) -> list[str]:
        """Claves efectivas en orden de carga (el de la definición que gana), como tras ``rebuild``."""
        return list(chain.from_iterable(self._won.values()))

    def entry(self, key: str) -> LocRow | None:
        """Fila que usa el juego para ``key``."""
        found = self._first.get(key)
        return None if found is None else found[1]

    def file_of(self, key: str) -> LocalisationFile | None:
        found = self._first.get(key)
        return None if found is None else found[0]

    def origin(self, key: str) -> int | None:
        """Índice en ``dirs`` de la carpeta de la definición que gana (0 = el mod si se pasó primero)."""
        file = self.file_of(key)
        return None if file is None else self._dir_index(file.path)

    def would_win(self, file_name: str, key: str) -> bool:
        """True si definir ``key`` en un archivo llamado ``file_name`` haría que el juego usara esa definición."""
        winner = self.file_of(key)
        if winner is None or winner.path is None:
            return True
        if winner.path.name.upper() == file_name.upper():
            return True
        return load_order_key(file_name) < load_order_key(winner.path.name)

    def lookup(self, key: str, lang: Lang = "en", *, fallback: Lang | None = None) -> str | None:
        """Texto efectivo de ``key``; ``None`` si no está definida.

        Con ``fallback``, si la columna pedida está vacía se devuelve la de ese idioma.
        """
        row = self.entry(key)
        if row is None:
            return None
        text = row.get(lang)
        if not text and fallback is not None:
            text = row.get(fallback)
        return text

    def source_of(self, key: str) -> Location | None:
        """(ruta, línea) de la definición que gana."""
        found = self._first.get(key)
        return None if found is None else _location(*found)

    def definitions(self, key: str) -> list[Location]:
        """Todas las definiciones de ``key`` en orden de carga; la primera es la que gana."""
        found = self._first.get(key)
        if found is None:
            return []
        return [_location(*found)] + [_location(*item) for item in self._later.get(key, ())]

    def overrides(self) -> list[KeyOverride]:
        """Claves definidas más de una vez (en el mismo archivo o en varios), en el orden de ``keys``."""
        later = self._later
        return [KeyOverride(key, _location(*self._first[key]), tuple(_location(*item) for item in later[key]))
                for key in filter(later.__contains__, chain.from_iterable(self._won.values()))]
