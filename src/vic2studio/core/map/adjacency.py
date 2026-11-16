"""``map/adjacencies.csv``: estrechos, pasos infranqueables y canales, sin pérdidas (wizard §16.4). Contrato.

Encima de ``tablecsv``: cada fila es ``desde;hasta;tipo;a_través;dato;comentario``. La primera línea es la
cabecera **comentada** (``#From;To;…``) y hay comentarios de sección, filas desactivadas con ``#`` y líneas en
blanco: todo eso se conserva tal cual, y editar regenera solo la fila tocada (I3). En vanilla hay 84 filas de
datos de 6 columnas (63 ``sea``, 18 ``impassable`` y 3 ``canal`` con dato 1–3), 26 comentarios (3 de ellos, filas
``sea`` desactivadas) y 7 líneas en blanco, con CRLF.

El archivo es un documento TABLE del ``Workspace``, que no tiene códec propio (se abre como binario): se edita
con ``open_adjacencies`` / ``store_adjacencies`` dentro de la transacción de quien llama, igual que
``defines.lua`` (``Workspace.restore_bytes`` guarda los bytes tal cual y el deshacer los devuelve).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from types import MappingProxyType

from ..tablecsv import RowKind, Table, TableRow, cell_int, check_value
from ..clausewitz import Severity
from ..validate.model import Problem
from ..vfs.paths import VPath

if TYPE_CHECKING:
    from ..project.workspace import Workspace

ADJACENCIES_REL = VPath.of("map/adjacencies.csv")
TYPE_SEA = "sea"                     # estrecho: dos provincias de tierra unidas a través de una de mar
TYPE_IMPASSABLE = "impassable"       # dos provincias vecinas entre las que no se pasa
TYPE_CANAL = "canal"                 # ``data`` es el número del canal (1–3 en vanilla)
TYPES = (TYPE_SEA, TYPE_IMPASSABLE, TYPE_CANAL)
COLUMNS = ("from", "to", "type", "through", "data", "comment")

ADJACENCY_BAD_ROW = "adjacency_bad_row"            # menos de 5 columnas o ids que no son números
ADJACENCY_BAD_TYPE = "adjacency_bad_type"          # el tipo no es uno de ``TYPES``


@dataclass(frozen=True)
class Adjacency:
    """Una fila de datos. Los enteros se leen al estilo ``atoi`` (``tablecsv.cell_int``); None si la celda no
    es un número. ``raw`` es el texto exacto de la fila."""

    line: int
    start: int | None
    end: int | None
    type: str
    through: int | None
    data: int | None
    comment: str
    raw: str


def _read(row: TableRow) -> Adjacency:
    fields = row.fields
    def num(i):
        return cell_int(fields[i]) if i < len(fields) else None
    return Adjacency(row.line, num(0), num(1), row.field(2).strip(), num(3), num(4), row.field(5), row.raw)


def _problem(code: str, rel: VPath, line: int, **args) -> Problem:
    return Problem(code, Severity.WARNING, rel, line, args=MappingProxyType(args))


class AdjacencyTable:
    """Vista editable de la tabla. ``table`` se puede leer; las ediciones van por ``add``, ``set`` y ``remove``."""

    def __init__(self, table: Table) -> None:
        self.table = table

    @classmethod
    def parse(cls, source: str | bytes, *, rel: VPath = ADJACENCIES_REL) -> tuple[AdjacencyTable, list[Problem]]:
        """Tabla y avisos de forma (``ADJACENCY_BAD_ROW``, ``ADJACENCY_BAD_TYPE``); nunca lanza por el
        contenido. Que las provincias existan y que ``through`` sea de mar lo comprueba ``coherence``."""
        table = Table.from_bytes(source) if isinstance(source, bytes) else Table.from_text(source)
        adjacencies = cls(table)
        problems: list[Problem] = []
        for row in table.data_rows():
            fields = row.fields
            item = _read(row)
            if len(fields) < 5 or item.start is None or item.end is None:
                problems.append(_problem(ADJACENCY_BAD_ROW, rel, row.line, row=row.raw))
            elif item.type not in TYPES:
                problems.append(_problem(ADJACENCY_BAD_TYPE, rel, row.line, type=item.type, row=row.raw))
        return adjacencies, problems

    def rows(self) -> list[Adjacency]:
        """Filas de datos en su orden (sin comentarios, ni la cabecera, ni las filas desactivadas)."""
        return [_read(row) for row in self.table.data_rows()]

    def find(self, a: int, b: int) -> list[Adjacency]:
        """Filas entre ``a`` y ``b`` en cualquiera de los dos sentidos."""
        return [row for row in self.rows() if {row.start, row.end} == {a, b} and (a != b or row.start == row.end)]

    def _row(self, item: Adjacency) -> TableRow:
        index = item.line - 1
        if 0 <= index < len(self.table.rows):
            row = self.table.rows[index]
            if row.kind is RowKind.DATA and row.raw == item.raw:
                return row
        raise KeyError(item.line)

    def add(self, start: int, end: int, type: str, *, through: int = 0, data: int = 0,
            comment: str = "") -> Adjacency:
        """Fila nueva tras la última fila de datos (o tras la cabecera si no hay ninguna), con el salto del
        archivo. ``ValueError`` si ``type`` no es de ``TYPES``; ``TableValueError`` si el comentario lleva
        ``;`` o un salto. No comprueba duplicados (lo hace quien llama con ``find``)."""
        if type not in TYPES:
            raise ValueError(f"tipo de adyacencia desconocido: {type}")
        check_value(comment)
        rows = self.table.rows
        last = max((i for i, row in enumerate(rows) if row.kind is RowKind.DATA), default=None)
        if last is None:
            last = 0 if rows else -1         # tras la cabecera comentada
        row = self.table.insert(last + 1, [str(int(start)), str(int(end)), type, str(int(through)),
                                           str(int(data)), comment])
        return _read(row)

    def set(self, row: Adjacency, *, start: int | None = None, end: int | None = None, type: str | None = None,
            through: int | None = None, data: int | None = None, comment: str | None = None) -> Adjacency:
        """Cambia solo las celdas indicadas de ``row`` (por su línea) y devuelve la fila releída."""
        if type is not None and type not in TYPES:
            raise ValueError(f"tipo de adyacencia desconocido: {type}")
        target = self._row(row)
        for column, value in ((0, start), (1, end), (3, through), (4, data)):
            if value is not None and cell_int(target.field(column)) != int(value):
                target.set(column, str(int(value)))
        if type is not None and target.field(2).strip() != type:
            target.set(2, type)
        if comment is not None and target.field(5) != comment:
            target.set(5, comment)
        return _read(target)

    def remove(self, row: Adjacency) -> None:
        """Quita la fila (``KeyError`` si ya no está)."""
        self.table.remove(self._row(row))

    def to_text(self) -> str:
        return self.table.to_text()

    def to_bytes(self) -> bytes:
        """``to_bytes(parse(b)) == b`` si no se editó nada."""
        return self.table.to_bytes()


def open_adjacencies(ws: Workspace, rel: VPath = ADJACENCIES_REL) -> AdjacencyTable:
    """La tabla efectiva (con lo sin guardar, I7), leída de los bytes del documento. Leer no escribe (I4).
    ``FileNotFoundError`` si ni el mod ni el juego la tienen."""
    from ..project.codecs import codec_for

    handle = ws.open(rel)
    data = codec_for(handle.kind).snapshot(handle.model)
    return AdjacencyTable.parse(data, rel=rel)[0]


def store_adjacencies(ws: Workspace, table: AdjacencyTable, rel: VPath = ADJACENCIES_REL) -> None:
    """Deja ``table`` como contenido del documento (``Workspace.restore_bytes``), dentro de la transacción ya
    abierta por quien llama; al guardar, el archivo se copia entero al mod en la misma ruta. No hace nada si
    los bytes no cambian."""
    from ..project.codecs import codec_for

    handle = ws.open(rel)
    data = table.to_bytes()
    if codec_for(handle.kind).snapshot(handle.model) == data:
        return
    ws.restore_bytes(handle, data)


# --- estrechos sugeridos (taller de mapas, wizard §18.5) ---------------------------------------------------

def suggest_straits(ids, is_sea, pairs=None, *, max_gap: int = 8):
    """Estrechos sugeridos entre tierras separadas por ≤ ``max_gap`` px de mar: ``(k, 4)`` con
    ``from, to, through, hueco``, un par por fila (el de menor hueco).

    Las ids de tierra se propagan por el mar con ``max_gap/2`` dilataciones 4-conexas; hay colisión donde dos
    píxeles de mar contiguos llevan tierras distintas. ``through`` es la provincia de mar del punto de colisión.
    Se descartan los pares ya vecinos por tierra (``pairs``: vecinos del ráster, a < b)."""
    import numpy as np

    ids = np.asarray(ids)
    is_sea = np.asarray(is_sea, bool)
    D = max(2, int(max_gap))
    src = np.where(is_sea[ids], 0, ids).astype(np.int64)
    dsea = np.where(src > 0, 0, 255).astype(np.int64)
    seam = is_sea[ids]
    for k in range(1, D // 2 + 1):
        for sh, ax in ((1, 0), (-1, 0), (1, 1), (-1, 1)):
            s2 = np.roll(src, sh, axis=ax)
            d2 = np.roll(dsea, sh, axis=ax)
            m = seam & (src == 0) & (s2 > 0) & (d2 == k - 1)
            src[m] = s2[m]
            dsea[m] = k
    found = []
    for sh, ax in ((1, 0), (1, 1)):
        s2 = np.roll(src, sh, axis=ax)
        d2 = np.roll(dsea, sh, axis=ax)
        m = seam & (src > 0) & (s2 > 0) & (src != s2) & (dsea + d2 <= D)
        found.append(np.column_stack([np.minimum(src[m], s2[m]), np.maximum(src[m], s2[m]), ids[m].astype(np.int64),
                                      dsea[m] + d2[m]]))
    P = np.concatenate(found).astype(np.int64) if found else np.zeros((0, 4), np.int64)
    if pairs is not None and len(pairs) and P.size:
        pairs = np.asarray(pairs)
        ll = pairs[(~is_sea[pairs[:, 0]]) & (~is_sea[pairs[:, 1]])]
        base = int(ids.max()) + 1
        known = np.isin(P[:, 0] * base + P[:, 1], ll[:, 0].astype(np.int64) * base + ll[:, 1])
        P = P[~known]
    if P.size:
        o = np.lexsort((P[:, 2], P[:, 3], P[:, 1], P[:, 0]))
        P = P[o]
        f = np.ones(len(P), bool)
        f[1:] = (P[1:, 0] != P[:-1, 0]) | (P[1:, 1] != P[:-1, 1])
        P = P[f]
    return P
