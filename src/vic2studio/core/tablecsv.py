"""Tablas separadas por ``;`` sin pérdidas: ``map/definition.csv`` y ``map/adjacencies.csv`` (wizard §4.1, §6.1, H4).

Como el lector CSV del juego, las filas se parten solo en LF: un CRLF es el salto de su fila y un CR suelto es
texto de la fila (igual que ``csvloc`` y ``encoding.detect_newline(lone_cr=False)``). Cada fila guarda su texto
exacto (``raw``) y su salto, así que ``to_bytes(from_bytes(b)) == b`` para cualquier entrada (I3): también los
comentarios ``#``, las filas en blanco, la falta de salto al final, los BOM y los bytes que cp1252 no define.
Editar regenera solo la fila tocada; las demás se escriben tal cual. Sin E/S: se trabaja con bytes.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from enum import Enum

from .encoding import (
    BOM,
    GAME_ENCODING,
    decode_bytes,
    detect_newline,
    encode_text,
    match_bom,
    split_bom,
    split_extra_boms,
)

SEPARATOR = ";"
COMMENT_PREFIX = "#"
TABLE_VALUE_SEPARATOR = "table_value_separator"
TABLE_VALUE_NEWLINE = "table_value_newline"


class RowKind(Enum):
    DATA = "data"
    COMMENT = "comment"
    BLANK = "blank"


class TableValueError(ValueError):
    """Un valor que no cabe en una celda (lleva ``;`` o un salto de línea); no se cambió nada."""

    def __init__(self, code: str, value: str):
        self.code = code
        self.value = value
        super().__init__(f"{code}: {value!r}")

    def __reduce__(self):
        return (type(self), (self.code, self.value))


def check_value(value: str) -> None:
    """``TableValueError`` si ``value`` no puede ir en una celda."""
    if SEPARATOR in value:
        raise TableValueError(TABLE_VALUE_SEPARATOR, value)
    if "\n" in value or "\r" in value:
        raise TableValueError(TABLE_VALUE_NEWLINE, value)


def cell_int(text: str) -> int | None:
    """Entero al estilo ``atoi``: espacios delante, signo opcional y dígitos, hasta el primer carácter que no lo
    es (``"223."`` → 223, ``" 12abc"`` → 12). Sin ningún dígito, None (``atoi`` daría 0, pero aquí importa
    distinguir una celda vacía de un 0)."""
    index, size = 0, len(text)
    while index < size and text[index] in " \t":
        index += 1
    sign = 1
    if index < size and text[index] in "+-":
        sign = -1 if text[index] == "-" else 1
        index += 1
    start = index
    while index < size and "0" <= text[index] <= "9":
        index += 1
    if index == start:
        return None
    return sign * int(text[start:index])


class TableRow:
    """Una fila: ``raw`` es su texto exacto sin el salto, ``newline`` su salto (``""`` en la última si el archivo
    no acaba en salto) y ``line`` su número desde 1 (lo mantiene la tabla)."""

    __slots__ = ("raw", "newline", "line")

    def __init__(self, raw: str, newline: str = "\r\n", line: int = 0) -> None:
        self.raw = raw
        self.newline = newline
        self.line = line

    @property
    def kind(self) -> RowKind:
        stripped = self.raw.strip()
        if not stripped:
            return RowKind.BLANK
        if stripped.startswith(COMMENT_PREFIX):
            return RowKind.COMMENT
        return RowKind.DATA

    @property
    def fields(self) -> list[str]:
        return self.raw.split(SEPARATOR)

    def field(self, column: int, default: str = "") -> str:
        fields = self.fields
        return fields[column] if 0 <= column < len(fields) else default

    def set(self, column: int, value: str) -> None:
        """Cambia una celda; las demás quedan tal cual. Si la fila tiene menos columnas, se añaden vacías."""
        check_value(value)
        if column < 0:
            raise IndexError(column)
        fields = self.fields
        if column >= len(fields):
            fields.extend([""] * (column + 1 - len(fields)))
        fields[column] = value
        self.raw = SEPARATOR.join(fields)

    def __repr__(self) -> str:
        return f"TableRow({self.line}, {self.raw!r})"


def _split_rows(text: str) -> list[TableRow]:
    rows: list[TableRow] = []
    start, size = 0, len(text)
    while start < size:
        end = text.find("\n", start)
        if end < 0:
            rows.append(TableRow(text[start:], ""))
            break
        if end > start and text[end - 1] == "\r":
            rows.append(TableRow(text[start:end - 1], "\r\n"))
        else:
            rows.append(TableRow(text[start:end], "\n"))
        start = end + 1
    for number, row in enumerate(rows, 1):
        row.line = number
    return rows


class Table:
    """Una tabla ``;`` completa. ``rows`` incluye comentarios y filas en blanco, en su orden."""

    def __init__(self, rows: Iterable[TableRow] = (), *, encoding: str = GAME_ENCODING, extra_boms: int = 0,
                 newline: str = "\r\n") -> None:
        self.rows: list[TableRow] = list(rows)
        self.encoding = encoding
        self.extra_boms = extra_boms        # BOM repetidos tras el de la codificación (``split_extra_boms``)
        self._newline = newline
        self._renumber()

    @classmethod
    def from_text(cls, text: str, *, encoding: str = GAME_ENCODING) -> Table:
        newline = detect_newline(text, lone_cr=False) if "\n" in text else "\r\n"
        return cls(_split_rows(text), encoding=encoding, newline=newline)

    @classmethod
    def from_bytes(cls, data: bytes, *, encoding: str | None = None) -> Table:
        """Detecta la codificación como el resto del núcleo (``decode_bytes``; cp1252 si no es otra)."""
        decoded = decode_bytes(data, encoding)
        text, name = split_bom(decoded.text, match_bom(data, decoded.encoding))
        text, extra = split_extra_boms(text, name)
        table = cls.from_text(text, encoding=name)
        table.extra_boms = extra
        return table

    def to_text(self) -> str:
        return "".join(row.raw + row.newline for row in self.rows)

    def to_bytes(self) -> bytes:
        """``UnencodableTextError`` si un valor nuevo no cabe en la codificación del archivo."""
        return encode_text(BOM * self.extra_boms + self.to_text(), self.encoding)

    @property
    def newline(self) -> str:
        """Salto predominante del archivo (el de las filas nuevas)."""
        return self._newline

    def data_rows(self) -> Iterator[TableRow]:
        return (row for row in self.rows if row.kind is RowKind.DATA)

    def _renumber(self, start: int = 0) -> None:
        for number in range(start, len(self.rows)):
            self.rows[number].line = number + 1

    def insert(self, index: int, fields: Sequence[str]) -> TableRow:
        """Fila nueva en la posición ``index`` (como ``list.insert``) con el salto predominante."""
        for value in fields:
            check_value(value)
        index = max(0, min(index, len(self.rows)))
        if index == len(self.rows) and self.rows and not self.rows[-1].newline:
            # Archivo sin salto final: la anterior última gana el salto y la nueva sigue sin él.
            self.rows[-1].newline = self._newline
            row = TableRow(SEPARATOR.join(fields), "")
        else:
            row = TableRow(SEPARATOR.join(fields), self._newline)
        self.rows.insert(index, row)
        self._renumber(index)
        return row

    def append(self, fields: Sequence[str]) -> TableRow:
        return self.insert(len(self.rows), fields)

    def remove(self, row: TableRow) -> None:
        """Quita ``row`` (por identidad). Si era la última y no tenía salto, la nueva última tampoco lo tiene."""
        index = next((i for i, other in enumerate(self.rows) if other is row), None)
        if index is None:
            raise ValueError("la fila no es de esta tabla")
        last = index == len(self.rows) - 1
        del self.rows[index]
        if last and not row.newline and self.rows:
            self.rows[-1].newline = ""
        self._renumber(index)
