"""Nodos del árbol sintáctico concreto (CST) de un archivo Clausewitz.

Los valores semánticos viven en ``Entry`` (clave, operador, valor) y ``Block``
(lista de entradas); los tokens originales solo guían el formato. Al editar una
parte de una entrada se conserva su trivia y se regenera su texto, de modo que
``to_source`` solo cambia lo editado. Los nodos creados por código no tienen
tokens y se formatean según su contexto al serializar.

``Scalar`` y ``ClausewitzDate`` son valores inmutables y pueden compartirse.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .lexer import BARE_WORD_RE, Token, is_clean_trivia, trivia_comments

OPERATORS = ("=", "<", ">", "<=", ">=", "!=", "==")

_INT_RE = re.compile(r"[+-]?[0-9]+")
_NUMBER_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
_DATE_RE = re.compile(r"(-?[0-9]+)\.([0-9]+)\.([0-9]+)")
# Calendario Clausewitz: sin años bisiestos.
_DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_BLANK = " \t\r\x0b\x0c"

_new = object.__new__


@dataclass(frozen=True, order=True)
class ClausewitzDate:
    """Fecha del juego (``1861.1.1``), ordenable y sin ceros a la izquierda al imprimirse."""

    year: int
    month: int = 1
    day: int = 1

    def __post_init__(self):
        for name in ("year", "month", "day"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} debe ser int, no {type(value).__name__}")
        if not 1 <= self.month <= 12:
            raise ValueError(f"mes fuera de rango: {self.month}")
        if not 1 <= self.day <= _DAYS_IN_MONTH[self.month - 1]:
            raise ValueError(f"día fuera de rango para el mes {self.month}: {self.day}")

    @classmethod
    def parse(cls, text: str) -> ClausewitzDate:
        match = _DATE_RE.fullmatch(text)
        if match is None:
            raise ValueError(f"no es una fecha año.mes.día: {text!r}")
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def __str__(self) -> str:
        return f"{self.year}.{self.month}.{self.day}"


def needs_quotes(text: str) -> bool:
    """True si ``text`` no puede escribirse como palabra sin comillas."""
    return BARE_WORD_RE.fullmatch(text) is None


class Scalar:
    """Valor escalar: ``text`` sin comillas y si iba entre comillas (``quoted``)."""

    __slots__ = ("_text", "_quoted")

    def __init__(self, text: str, quoted: bool = False):
        if not isinstance(text, str):
            raise TypeError(f"el texto de un escalar debe ser str, no {type(text).__name__}")
        quoted = bool(quoted)
        if quoted:
            if '"' in text:
                raise ValueError('Clausewitz no admite comillas dobles dentro de una cadena (no hay escapes)')
        elif needs_quotes(text):
            raise ValueError(f"{text!r} no es una palabra válida sin comillas; usa quoted=True")
        self._text = text
        self._quoted = quoted

    @classmethod
    def _trusted(cls, text: str, quoted: bool) -> Scalar:
        scalar = _new(cls)
        scalar._text = text
        scalar._quoted = quoted
        return scalar

    @property
    def text(self) -> str:
        return self._text

    @property
    def quoted(self) -> bool:
        return self._quoted

    def as_int(self) -> int:
        if _INT_RE.fullmatch(self._text) is None:
            raise ValueError(f"no es un entero: {self._text!r}")
        return int(self._text)

    def as_float(self) -> float:
        if _NUMBER_RE.fullmatch(self._text) is None:
            raise ValueError(f"no es un número: {self._text!r}")
        return float(self._text)

    def as_bool(self) -> bool:
        lowered = self._text.lower()
        if lowered == "yes":
            return True
        if lowered == "no":
            return False
        raise ValueError(f"no es yes/no: {self._text!r}")

    def as_date(self) -> ClausewitzDate:
        return ClausewitzDate.parse(self._text)

    def is_number(self) -> bool:
        return _NUMBER_RE.fullmatch(self._text) is not None

    def is_date(self) -> bool:
        try:
            ClausewitzDate.parse(self._text)
        except ValueError:
            return False
        return True

    def __str__(self) -> str:
        return self._text

    def __repr__(self) -> str:
        return f"Scalar({self._text!r}, quoted=True)" if self._quoted else f"Scalar({self._text!r})"

    def __eq__(self, other):
        if isinstance(other, Scalar):
            return self._text == other._text and self._quoted == other._quoted
        return NotImplemented

    def __hash__(self):
        return hash((self._text, self._quoted))


def scalar_source(scalar: Scalar) -> str:
    """Texto del escalar tal como se escribe en el archivo."""
    return '"' + scalar._text + '"' if scalar._quoted else scalar._text


def format_float(value: float) -> str:
    """Representación decimal sin notación científica (el juego no la entiende)."""
    if not math.isfinite(value):
        raise ValueError(f"valor no representable en Clausewitz: {value!r}")
    text = repr(value)
    if "e" in text or "E" in text:
        text = f"{value:.12f}".rstrip("0")
        if text.endswith("."):
            text += "0"
    return text


def key_text(key) -> str:
    """Texto de una clave de búsqueda: str, Scalar, int o ClausewitzDate."""
    if isinstance(key, str):
        return key
    if isinstance(key, Scalar):
        return key._text
    if isinstance(key, ClausewitzDate):
        return str(key)
    if isinstance(key, int) and not isinstance(key, bool):
        return str(key)
    raise TypeError(f"clave no válida: {key!r}")


def coerce_key(key) -> Scalar:
    if isinstance(key, Scalar):
        return key
    text = key_text(key)
    return Scalar(text, quoted=needs_quotes(text))


def coerce_value(value) -> Scalar | Block:
    """Convierte un valor de Python en ``Scalar`` o ``Block`` (ver ``Block.set``)."""
    if isinstance(value, (Scalar, Block)):
        return value
    if isinstance(value, bool):
        return Scalar._trusted("yes" if value else "no", False)
    if isinstance(value, int):
        return Scalar._trusted(str(value), False)
    if isinstance(value, float):
        return Scalar._trusted(format_float(value), False)
    if isinstance(value, str):
        return Scalar(value, quoted=needs_quotes(value))
    if isinstance(value, ClausewitzDate):
        return Scalar._trusted(str(value), False)
    if isinstance(value, dict):
        block = Block()
        for key, item in value.items():
            if key is None:
                raise TypeError("las claves de un dict no pueden ser None")
            block.entries.append(Entry(key, "=", item))
        return block
    if isinstance(value, (list, tuple)):
        block = Block()
        for item in value:
            block.entries.append(Entry(None, None, item))
        return block
    raise TypeError(f"valor no admitido: {type(value).__name__}")


def _check_op(op) -> str:
    if op not in OPERATORS:
        raise ValueError(f"operador no válido: {op!r}; se admiten {', '.join(OPERATORS)}")
    return op


def first_token(entry: Entry) -> Token | None:
    """Token que lleva la trivia previa de la entrada; None si la entrada es nueva."""
    if entry._key is not None:
        return entry._ktok
    if entry._vtok is not None:
        return entry._vtok
    value = entry._value
    if value.__class__ is not Scalar:
        return value._open
    return None


class Entry:
    """``clave op valor`` o, con ``key`` None, un valor suelto (``{ 1 2 3 }``)."""

    __slots__ = ("_key", "_op", "_value", "_ktok", "_otok", "_vtok", "_comments")

    def __init__(self, key, op: str | None = "=", value=None):
        if value is None:
            raise TypeError("una entrada necesita un valor")
        if key is None:
            self._key = None
            self._op = None
        else:
            self._key = coerce_key(key)
            self._op = _check_op("=" if op is None else op)
        self._value = coerce_value(value)
        self._ktok = self._otok = self._vtok = None
        self._comments = None

    @classmethod
    def _parsed(cls, key, ktok, op, otok, value, vtok) -> Entry:
        entry = _new(cls)
        entry._key = key
        entry._ktok = ktok
        entry._op = op
        entry._otok = otok
        entry._value = value
        entry._vtok = vtok
        entry._comments = None
        return entry

    @property
    def key(self) -> Scalar | None:
        return self._key

    @key.setter
    def key(self, key) -> None:
        if key is None:
            if self._key is None:
                return
            # Asignación -> valor suelto: el valor hereda la trivia previa de la clave.
            lead = self._ktok
            self._key = self._op = self._ktok = self._otok = None
            if lead is not None:
                self._vtok = lead.detached()
            return
        new = coerce_key(key)
        if self._key is None:
            # Valor suelto -> asignación: la clave hereda la trivia previa del valor.
            lead = first_token(self)
            self._key = new
            self._op = "="
            if lead is not None:
                self._ktok = lead.detached()
                self._vtok = Token(lead.kind, None, " ", lead.offset, lead.line, lead.column)
            return
        if new is self._key:
            return
        self._key = new
        if self._ktok is not None and self._ktok.raw is not None:
            self._ktok = self._ktok.detached()

    @property
    def op(self) -> str | None:
        return self._op

    @op.setter
    def op(self, op: str) -> None:
        if self._key is None:
            raise ValueError("un valor suelto no tiene operador; asigna antes una clave")
        op = _check_op(op)
        if op == self._op:
            return
        self._op = op
        if self._otok is not None and self._otok.raw is not None:
            self._otok = self._otok.detached()

    @property
    def value(self) -> Scalar | Block:
        return self._value

    @value.setter
    def value(self, value) -> None:
        new = coerce_value(value)
        old = self._value
        if new is old:
            return
        token = self._vtok
        if token is None:
            if old.__class__ is not Scalar and old._open is not None:
                self._vtok = old._open.detached()
        elif token.raw is not None:
            self._vtok = token.detached()
        self._value = new

    @property
    def is_assignment(self) -> bool:
        return self._key is not None

    @property
    def line(self) -> int | None:
        token = first_token(self)
        return None if token is None else token.line

    @property
    def column(self) -> int | None:
        token = first_token(self)
        return None if token is None else token.column

    @property
    def comments(self) -> list[str]:
        """Comentarios en las líneas anteriores a la entrada (y el final de la línea previa)."""
        if self._comments is not None:
            return list(self._comments)
        token = first_token(self)
        return [] if token is None else trivia_comments(token.trivia)

    def __repr__(self) -> str:
        value = self._value
        shown = repr(value) if value.__class__ is Scalar else f"<Block {len(value.entries)} entries>"
        if self._key is None:
            return f"Entry({shown})"
        return f"Entry({self._key!r} {self._op} {shown})"


def _match_all(entries, key, ignore_case):
    text = key_text(key)
    if ignore_case:
        text = text.lower()
        return [e for e in entries if e._key is not None and e._key._text.lower() == text]
    return [e for e in entries if e._key is not None and e._key._text == text]


class Block:
    """Bloque ``{ ... }``: lista ordenada de entradas (asignaciones y/o valores sueltos)."""

    __slots__ = ("entries", "_open", "_close", "_unclosed", "_trailing_comments")

    def __init__(self, entries=None):
        self.entries: list[Entry] = []
        if entries is not None:
            for entry in entries:
                if not isinstance(entry, Entry):
                    raise TypeError(f"se esperaba Entry, no {type(entry).__name__}")
                self.entries.append(entry)
        self._open = self._close = None
        self._unclosed = False
        self._trailing_comments = None

    @classmethod
    def _parsed(cls, open_token: Token) -> Block:
        block = _new(cls)
        block.entries = []
        block._open = open_token
        block._close = None
        block._unclosed = False
        block._trailing_comments = None
        return block

    # --- consulta ---------------------------------------------------------------

    def __iter__(self):
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, key) -> bool:
        return self.find(key) is not None

    def find(self, key, *, ignore_case: bool = False) -> Entry | None:
        text = key_text(key)
        if ignore_case:
            text = text.lower()
            for entry in self.entries:
                if entry._key is not None and entry._key._text.lower() == text:
                    return entry
        else:
            for entry in self.entries:
                if entry._key is not None and entry._key._text == text:
                    return entry
        return None

    def find_all(self, key, *, ignore_case: bool = False) -> list[Entry]:
        return _match_all(self.entries, key, ignore_case)

    def get(self, key, default=None, *, ignore_case: bool = False):
        entry = self.find(key, ignore_case=ignore_case)
        return default if entry is None else entry._value

    def get_all(self, key, *, ignore_case: bool = False) -> list:
        return [entry._value for entry in _match_all(self.entries, key, ignore_case)]

    def get_text(self, key, default=None, *, ignore_case: bool = False):
        """Texto del primer valor escalar con esa clave."""
        for entry in _match_all(self.entries, key, ignore_case):
            if entry._value.__class__ is Scalar:
                return entry._value._text
        return default

    def has(self, key, *, ignore_case: bool = False) -> bool:
        return self.find(key, ignore_case=ignore_case) is not None

    def keys(self) -> list[str]:
        """Claves en orden de aparición, sin repetidos."""
        seen = {}
        for entry in self.entries:
            if entry._key is not None:
                seen.setdefault(entry._key._text, None)
        return list(seen)

    def values(self) -> list:
        """Valores sueltos (entradas sin clave)."""
        return [entry._value for entry in self.entries if entry._key is None]

    @property
    def line(self) -> int | None:
        return None if self._open is None else self._open.line

    @property
    def column(self) -> int | None:
        return None if self._open is None else self._open.column

    @property
    def is_closed(self) -> bool:
        """False si el bloque se leyó de un archivo y le falta la llave de cierre."""
        return not self._unclosed

    @property
    def trailing_comments(self) -> list[str]:
        """Comentarios entre la última entrada y la llave de cierre."""
        if self._trailing_comments is not None:
            return list(self._trailing_comments)
        token = self._closer_token()
        return [] if token is None else trivia_comments(token.trivia)

    def _closer_token(self) -> Token | None:
        return self._close

    # --- edición ----------------------------------------------------------------

    def set(self, key, value, *, ignore_case: bool = False) -> Entry:
        """Reemplaza el valor de la primera entrada con esa clave o, si no existe, la añade.

        Con un ``str`` se conservan las comillas del valor anterior (``name = "X"``).
        """
        entry = self.find(key, ignore_case=ignore_case)
        if entry is None:
            return self.append(key, value)
        old = entry._value
        if isinstance(value, str) and old.__class__ is Scalar and old._quoted:
            value = Scalar(value, quoted=True)
        entry.value = value
        return entry

    def append(self, key, value, op: str = "=") -> Entry:
        entry = Entry(key, None if key is None else op, value)
        self.entries.append(entry)
        return entry

    def append_value(self, value) -> Entry:
        entry = Entry(None, None, value)
        self.entries.append(entry)
        return entry

    def insert(self, index: int, key, value, op: str = "=") -> Entry:
        entry = Entry(key, None if key is None else op, value)
        self.entries.insert(index, entry)
        return entry

    def remove(self, key, *, ignore_case: bool = False) -> int:
        """Elimina todas las entradas con esa clave; devuelve cuántas."""
        targets = _match_all(self.entries, key, ignore_case)
        for entry in targets:
            self.remove_entry(entry)
        return len(targets)

    def remove_entry(self, entry: Entry) -> None:
        """Elimina la entrada y su línea, conservando los comentarios de líneas anteriores."""
        entries = self.entries
        for index, candidate in enumerate(entries):
            if candidate is entry:
                break
        else:
            raise ValueError("la entrada no pertenece a este bloque")
        lead = first_token(entry)
        following = None
        at_end = True
        for later in range(index + 1, len(entries)):
            following = first_token(entries[later])
            if following is not None:
                at_end = False
                break
        if at_end:
            following = self._closer_token()
        del entries[index]
        if lead is not None and following is not None:
            following.trivia = join_after_removal(
                lead.trivia,
                following.trivia,
                first=index == 0,
                line_start=index == 0 and isinstance(self, Document),
                at_end=at_end,
            )

    def __repr__(self) -> str:
        return f"<Block {len(self.entries)} entries>"


class Document(Block):
    """Bloque raíz de un archivo. ``newline`` se usa para el texto generado."""

    __slots__ = ("newline", "encoding", "_eof", "_indent_unit")

    def __init__(self, entries=None, *, newline: str = "\n", encoding: str | None = None):
        super().__init__(entries)
        self.newline = newline
        self.encoding = encoding
        self._eof = None
        self._indent_unit = "\t"

    @property
    def line(self) -> int:
        return 1

    @property
    def column(self) -> int:
        return 1

    def _closer_token(self) -> Token | None:
        return self._eof

    def __repr__(self) -> str:
        return f"<Document {len(self.entries)} entries>"


# --- trivia al eliminar entradas -------------------------------------------------


def _is_blank(text: str) -> bool:
    return not text.strip(_BLANK)


def _strip_trailing_blank_lines(prefix: str) -> tuple[str, int]:
    """``prefix`` acaba en salto de línea; quita las líneas completas en blanco del final."""
    lines = prefix.split("\n")
    end = len(lines) - 1  # el último elemento es "" (tras el salto final)
    keep = end - 1
    while keep >= 1 and _is_blank(lines[keep]):
        keep -= 1
    removed = end - 1 - keep
    if removed <= 0:
        return prefix, 0
    return "\n".join(lines[: keep + 1]) + "\n", removed


def _strip_leading_blank_lines(suffix: str) -> tuple[str, int]:
    parts = suffix.split("\n")
    index = 0
    while index < len(parts) - 1 and _is_blank(parts[index]):
        index += 1
    if not index:
        return suffix, 0
    return "\n".join(parts[index:]), index


def join_after_removal(lead: str, trail: str, *, first: bool = False, line_start: bool = False,
                       at_end: bool = False) -> str:
    """Nueva trivia del token que sigue a una entrada eliminada.

    ``lead`` es la trivia previa de la entrada y ``trail`` la del token siguiente;
    ``first`` indica que era la primera del bloque, ``line_start`` que empezaba el
    documento y ``at_end`` que el token siguiente es el cierre. Si la entrada
    ocupaba su propia línea, se elimina la línea entera (incluido un comentario al
    final de ella) sin dejar líneas en blanco sueltas; los comentarios de líneas
    anteriores se conservan. Si hay texto descartado por errores de sintaxis en esa
    línea, solo se eliminan los tokens de la entrada.
    """
    lf = lead.rfind("\n")
    if lf < 0 and not line_start:
        # Comparte línea con lo anterior: desaparece el separador previo.
        return trail if is_clean_trivia(lead) else lead + trail
    prefix, indent = lead[: lf + 1], lead[lf + 1:]
    tf = trail.find("\n")
    if tf < 0:
        # Algo la sigue en la misma línea: ese token ocupa su lugar.
        return lead if is_clean_trivia(trail) else lead + trail
    rest_of_line, suffix = trail[: tf + 1], trail[tf + 1:]
    if not (is_clean_trivia(indent) and is_clean_trivia(rest_of_line)):
        return lead + trail
    stripped_prefix, blank_before = _strip_trailing_blank_lines(prefix) if prefix else (prefix, 0)
    stripped_suffix, blank_after = _strip_leading_blank_lines(suffix)
    if blank_before and blank_after:
        # Había separación en blanco a ambos lados: se conserva solo la de arriba.
        return prefix + stripped_suffix
    if blank_before and at_end and _is_blank(suffix):
        # Detrás solo queda el cierre: sobra la separación de arriba.
        return stripped_prefix + suffix
    if blank_after and first:
        # Delante solo queda la apertura: sobra la separación de abajo.
        return prefix + stripped_suffix
    return prefix + suffix
