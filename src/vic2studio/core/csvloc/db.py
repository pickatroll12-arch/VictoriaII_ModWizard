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

La base es una instantánea: tras editar sus archivos hay que llamar a ``rebuild``.
Las claves se comparan tal cual, distinguiendo mayúsculas (vanilla tiene pares
como ``CANCEL``/``cancel``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Union

from .model import Lang, LocalisationFile, LocRow, RowKind
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


def _location(file: LocalisationFile, row: LocRow) -> Location:
    line = row.line
    if line is None:
        line = next((n for n, r in enumerate(file.rows, 1) if r is row), None)
    return file.path, line


class LocalisationDB:
    """Índice de claves sobre una lista ordenada de archivos (el primero tiene prioridad)."""

    def __init__(self, files: Iterable[LocalisationFile] = ()):
        self.files: list[LocalisationFile] = list(files)
        # (archivo ignorado, archivo de una carpeta anterior que lo sustituye)
        self.replaced_files: list[tuple[Path, Path]] = []
        self._first: dict[str, tuple[LocalisationFile, LocRow]] = {}
        self._later: dict[str, list[tuple[LocalisationFile, LocRow]]] = {}
        self.rebuild()

    @classmethod
    def from_dirs(cls, dirs: PathLike | Iterable[PathLike], *, encoding: str | None = None) -> LocalisationDB:
        """Carga las carpetas en orden de prioridad (mod primero, vanilla después).

        Las carpetas que no existen se omiten.
        """
        if isinstance(dirs, (str, os.PathLike)):
            dirs = [dirs]
        chosen: dict[str, Path] = {}
        replaced: list[tuple[Path, Path]] = []
        for directory in map(Path, dirs):
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
        ordered = sorted(chosen.values(), key=lambda p: load_order_key(p.name))
        db = cls(read_csv_file(path, encoding=encoding) for path in ordered)
        db.replaced_files = replaced
        return db

    def rebuild(self) -> None:
        first: dict[str, tuple[LocalisationFile, LocRow]] = {}
        later: dict[str, list[tuple[LocalisationFile, LocRow]]] = {}
        for file in self.files:
            for row in file.rows:
                if row.kind is not RowKind.DATA or not row.key:
                    continue
                if row.key in first:
                    later.setdefault(row.key, []).append((file, row))
                else:
                    first[row.key] = (file, row)
        self._first, self._later = first, later

    def add_file(self, file: LocalisationFile) -> None:
        """Añade un archivo al final del orden de carga (menor prioridad)."""
        self.files.append(file)
        self.rebuild()

    def __contains__(self, key: object) -> bool:
        return key in self._first

    def __len__(self) -> int:
        return len(self._first)

    def keys(self) -> list[str]:
        """Claves efectivas en orden de carga."""
        return list(self._first)

    def entry(self, key: str) -> LocRow | None:
        """Fila que usa el juego para ``key``."""
        found = self._first.get(key)
        return None if found is None else found[1]

    def file_of(self, key: str) -> LocalisationFile | None:
        found = self._first.get(key)
        return None if found is None else found[0]

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
        """Claves definidas más de una vez (en el mismo archivo o en varios), en orden de carga."""
        result = []
        for key, shadowed in self._later.items():
            result.append(KeyOverride(key, _location(*self._first[key]),
                                      tuple(_location(*item) for item in shadowed)))
        order = {key: index for index, key in enumerate(self._first) if key in self._later}
        result.sort(key=lambda item: order[item.key])
        return result
