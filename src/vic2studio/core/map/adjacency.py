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

from ..tablecsv import Table
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


class AdjacencyTable:
    """Vista editable de la tabla. ``table`` se puede leer; las ediciones van por ``add``, ``set`` y ``remove``."""

    def __init__(self, table: Table) -> None:
        self.table = table

    @classmethod
    def parse(cls, source: str | bytes, *, rel: VPath = ADJACENCIES_REL) -> tuple[AdjacencyTable, list[Problem]]:
        """Tabla y avisos de forma (``ADJACENCY_BAD_ROW``, ``ADJACENCY_BAD_TYPE``); nunca lanza por el
        contenido. Que las provincias existan y que ``through`` sea de mar lo comprueba ``coherence``."""
        raise NotImplementedError

    def rows(self) -> list[Adjacency]:
        """Filas de datos en su orden (sin comentarios, ni la cabecera, ni las filas desactivadas)."""
        raise NotImplementedError

    def find(self, a: int, b: int) -> list[Adjacency]:
        """Filas entre ``a`` y ``b`` en cualquiera de los dos sentidos."""
        raise NotImplementedError

    def add(self, start: int, end: int, type: str, *, through: int = 0, data: int = 0,
            comment: str = "") -> Adjacency:
        """Fila nueva tras la última fila de datos (o tras la cabecera si no hay ninguna), con el salto del
        archivo. ``ValueError`` si ``type`` no es de ``TYPES``; ``TableValueError`` si el comentario lleva
        ``;`` o un salto. No comprueba duplicados (lo hace quien llama con ``find``)."""
        raise NotImplementedError

    def set(self, row: Adjacency, *, start: int | None = None, end: int | None = None, type: str | None = None,
            through: int | None = None, data: int | None = None, comment: str | None = None) -> Adjacency:
        """Cambia solo las celdas indicadas de ``row`` (por su línea) y devuelve la fila releída."""
        raise NotImplementedError

    def remove(self, row: Adjacency) -> None:
        """Quita la fila (``KeyError`` si ya no está)."""
        raise NotImplementedError

    def to_text(self) -> str:
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        """``to_bytes(parse(b)) == b`` si no se editó nada."""
        raise NotImplementedError


def open_adjacencies(ws: Workspace, rel: VPath = ADJACENCIES_REL) -> AdjacencyTable:
    """La tabla efectiva (con lo sin guardar, I7), leída de los bytes del documento. Leer no escribe (I4).
    ``FileNotFoundError`` si ni el mod ni el juego la tienen."""
    raise NotImplementedError


def store_adjacencies(ws: Workspace, table: AdjacencyTable, rel: VPath = ADJACENCIES_REL) -> None:
    """Deja ``table`` como contenido del documento (``Workspace.restore_bytes``), dentro de la transacción ya
    abierta por quien llama; al guardar, el archivo se copia entero al mod en la misma ruta. No hace nada si
    los bytes no cambian."""
    raise NotImplementedError
