"""``map/definition.csv``: id de provincia → color del ``provinces.bmp`` (wizard §16.1, H4), sin pérdidas.

Encima de ``tablecsv``: cada fila es ``id;rojo;verde;azul;nombre;x``. Se toleran:

- la cabecera (``province;red;green;blue;x;x``): una primera fila cuyo id no es un entero;
- las filas sin id del final de vanilla (``;54;14;244;x;``): conservan su color, con ``id=None``;
- valores como ``223.``, que el motor lee al estilo ``atoi`` (223) y se conservan tal cual.

Lo raro sale como ``Problem`` (aviso), nunca como excepción. Solo se regeneran las filas tocadas.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from ..clausewitz import Severity
from ..tablecsv import RowKind, Table, TableRow, cell_int
from ..validate.model import Problem
from ..vfs.paths import VPath

DEFINITION_REL = VPath.of("map/definition.csv")
DEFINITION_BAD_ROW = "definition_bad_row"
DEFINITION_DUPLICATE_ID = "definition_duplicate_id"
DEFINITION_DUPLICATE_COLOR = "definition_duplicate_color"
END_MARKER = "x"

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class DefinitionRow:
    line: int
    id: int | None
    rgb: RGB | None                      # None si los colores no son números
    name: str
    raw: str


def _row_values(row: TableRow) -> tuple[int | None, RGB | None, str]:
    fields = row.fields
    pid = cell_int(fields[0]) if fields else None
    channels = [cell_int(f) for f in fields[1:4]]
    rgb = tuple(channels) if len(channels) == 3 and all(c is not None for c in channels) else None
    return pid, rgb, row.field(4)


class DefinitionTable:
    def __init__(self, table: Table, header: TableRow | None) -> None:
        """Las ediciones van por ``add`` y ``set_rgb`` (mantienen el índice de colores); ``table`` se puede leer."""
        self.table = table
        self.header = header
        self._maps: tuple[dict[int, RGB], dict[RGB, int]] | None = None

    @classmethod
    def parse(cls, source: str | bytes, *, rel: VPath = DEFINITION_REL) -> tuple[DefinitionTable, list[Problem]]:
        """Tabla y avisos (filas con id pero sin colores numéricos, ids y colores repetidos entre las filas
        con id)."""
        table = Table.from_bytes(source) if isinstance(source, bytes) else Table.from_text(source)
        header = None
        first = next(table.data_rows(), None)
        if first is not None and cell_int(first.field(0)) is None and first.field(0).strip():
            header = first
        definition = cls(table, header)
        problems: list[Problem] = []
        seen_ids: dict[int, int] = {}
        seen_colors: dict[RGB, int] = {}
        for row in definition._rows():
            if row.id is None:
                continue
            if row.rgb is None:
                problems.append(_problem(DEFINITION_BAD_ROW, rel, row.line, id=row.id, row=row.raw))
                continue
            if row.id in seen_ids:
                problems.append(_problem(DEFINITION_DUPLICATE_ID, rel, row.line, id=row.id,
                                         first=seen_ids[row.id]))
            else:
                seen_ids[row.id] = row.line
            if row.rgb in seen_colors:
                problems.append(_problem(DEFINITION_DUPLICATE_COLOR, rel, row.line, id=row.id,
                                         color=" ".join(map(str, row.rgb)), first=seen_colors[row.rgb]))
            else:
                seen_colors[row.rgb] = row.line
        return definition, problems

    def _data(self) -> list[TableRow]:
        return [row for row in self.table.rows if row.kind is RowKind.DATA and row is not self.header]

    def _rows(self) -> list[DefinitionRow]:
        rows = []
        for row in self._data():
            pid, rgb, name = _row_values(row)
            rows.append(DefinitionRow(row.line, pid, rgb, name, row.raw))
        return rows

    def rows(self) -> list[DefinitionRow]:
        """Filas de datos (sin la cabecera), con y sin id, en su orden."""
        return self._rows()

    def ids(self) -> list[int]:
        """Ids en orden de aparición, sin repetir."""
        return list(dict.fromkeys(r.id for r in self._rows() if r.id is not None))

    def _index(self) -> tuple[dict[int, RGB], dict[RGB, int]]:
        if self._maps is None:
            by_id: dict[int, RGB] = {}
            by_rgb: dict[RGB, int] = {}
            for row in self._rows():
                if row.id is not None and row.rgb is not None:
                    by_id.setdefault(row.id, row.rgb)
                    by_rgb.setdefault(row.rgb, row.id)
            self._maps = (by_id, by_rgb)
        return self._maps

    def id_of(self, rgb: RGB) -> int | None:
        """Id de la primera fila con ese color (None si ningún id lo usa)."""
        return self._index()[1].get(tuple(rgb))

    def rgb_of(self, pid: int) -> RGB:
        """Color de ``pid`` (el de la primera fila); ``KeyError`` si no está o no tiene colores numéricos."""
        return self._index()[0][pid]

    def _table_row(self, pid: int) -> TableRow:
        for row in self._data():
            if cell_int(row.field(0)) == pid:
                return row
        raise KeyError(pid)

    def add(self, pid: int, rgb: RGB, name: str) -> None:
        """Fila ``pid;r;g;b;name;x`` tras la última fila con id (delante de las filas sin id del final)."""
        fields = [str(int(pid)), *(str(int(c)) for c in rgb), name, END_MARKER]
        rows = self.table.rows
        last = max((i for i, row in enumerate(rows)
                    if row.kind is RowKind.DATA and row is not self.header and cell_int(row.field(0)) is not None),
                   default=None)
        if last is None:
            last = next((i for i, row in enumerate(rows) if row is self.header), -1)
        self.table.insert(last + 1, fields)
        self._maps = None

    def set_rgb(self, pid: int, rgb: RGB) -> None:
        """Cambia el color de ``pid`` (solo sus tres celdas; ``KeyError`` si no está)."""
        row = self._table_row(pid)
        for column, value in zip((1, 2, 3), rgb):
            row.set(column, str(int(value)))
        self._maps = None

    def to_text(self) -> str:
        return self.table.to_text()

    def to_bytes(self) -> bytes:
        return self.table.to_bytes()


def _problem(code: str, rel: VPath, line: int, **args) -> Problem:
    return Problem(code, Severity.WARNING, rel, line, args=MappingProxyType(args))
