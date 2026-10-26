"""Nodos del árbol sintáctico concreto (CST) de un archivo Clausewitz.

Los valores semánticos viven en ``Entry`` (clave, operador, valor) y ``Block``
(lista de entradas); los tokens originales solo guían el formato y nunca se
modifican. Al editar una parte de una entrada se conserva su trivia y se
regenera su texto, de modo que ``to_source`` solo cambia lo editado. Los nodos
creados por código no tienen tokens y se formatean según su contexto.

``Block.entries`` es una lista normal: se pueden quitar, reordenar o insertar
entradas existentes, también de otros bloques del mismo documento, con la API
(``move``, ``insert_entry``, ``remove_entry``) o directamente sobre la lista. Al
serializar, cada bloque se compara con su orden leído para conservar el
formato: una entrada movida se lleva los comentarios pegados encima de ella y
el de su línea, y se sangra según su nuevo sitio; reinsertar una entrada
borrada en su índice, o devolverle su valor leído, da el texto original exacto
(deshacer). Para copiar nodos a otro archivo se usa ``clone()``:
``copy.deepcopy`` conserva el formato del archivo de origen y no está pensado
para eso.

Comentarios: ``Entry.comments`` (líneas propias encima de la entrada; los de la
cabecera del archivo son de su primera entrada), ``Entry.line_comment`` (al
final de su línea), ``Block.open_comment`` (en la línea de su ``{``) y
``Block.trailing_comments`` (encima de su ``}``). Todos se pueden cambiar.

``Scalar`` y ``ClausewitzDate`` son inmutables y pueden compartirse. Los errores
de la API son ``EditError`` (un ``ValueError``) y ``EditTypeError`` (un
``TypeError``), con código, datos y mensaje en español o inglés.
"""

from __future__ import annotations

import math
import numbers
import operator
import re
from dataclasses import dataclass
from decimal import Decimal

from ..encoding import GAME_ENCODING, find_unencodable
from .diagnostics import EditError, EditTypeError
from .lexer import (
    BARE_WORD_RE,
    CONTROL_RE,
    INVISIBLE_RE,
    OPEN_STRING,
    WORD,
    Token,
    head_comments,
    scalar_text,
    tail_comment,
)

OPERATORS = ("=", "<", ">", "<=", ">=", "!=", "==")

_INT_RE = re.compile(r"[+-]?[0-9]+")
_NUMBER_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
_DATE_RE = re.compile(r"(-?[0-9]+)\.([0-9]+)\.([0-9]+)")
_POSITION_RE = re.compile(r"\[([0-9]+)\]")
# Calendario Clausewitz: sin años bisiestos.
_DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

_ANY = object()  # sin filtro de valor en find/remove
_new = object.__new__


def _type_name(value) -> str:
    return type(value).__name__


def _is_bool(value) -> bool:
    """bool de Python o de numpy (``numpy.bool_``, que no es ``numbers.Integral``)."""
    return isinstance(value, bool) or getattr(getattr(value, "dtype", None), "kind", None) == "b"


@dataclass(frozen=True, order=True)
class ClausewitzDate:
    """Fecha del juego (``1861.1.1``), ordenable y sin ceros a la izquierda al imprimirse."""

    year: int
    month: int = 1
    day: int = 1

    def __post_init__(self):
        for name in ("year", "month", "day"):
            value = getattr(self, name)
            if _is_bool(value) or not isinstance(value, numbers.Integral):
                raise EditTypeError("date_part_type", {"name": name, "type": _type_name(value)})
            object.__setattr__(self, name, operator.index(value))
        if not 1 <= self.month <= 12:
            raise EditError("date_month_range", {"month": self.month})
        if not 1 <= self.day <= _DAYS_IN_MONTH[self.month - 1]:
            raise EditError("date_day_range", {"month": self.month, "day": self.day})

    @classmethod
    def parse(cls, text: str) -> ClausewitzDate:
        match = _DATE_RE.fullmatch(text)
        if match is None:
            raise EditError("not_a_date", {"text": text})
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def __str__(self) -> str:
        return f"{self.year}.{self.month}.{self.day}"


def needs_quotes(text: str) -> bool:
    """True si ``text`` no puede escribirse como palabra sin comillas.

    Las palabras con caracteres invisibles (espacio de no separación, de ancho cero...)
    también van entre comillas: sin ellas el parser avisa de que no son lo que aparentan.
    """
    return BARE_WORD_RE.fullmatch(text) is None or (not text.isascii() and INVISIBLE_RE.search(text) is not None)


def _check_line(text: str) -> None:
    """Rechaza lo que el juego no lee en una sola línea: saltos de línea y caracteres de control."""
    if "\n" in text or "\r" in text:
        raise EditError("line_break", {"text": text})
    match = CONTROL_RE.search(text)
    if match is not None:
        raise EditError("control_character", {"text": text, "codepoint": f"{ord(match.group()):04X}"})


def _check_written(text: str, quoted: bool, *, invisible: bool = True) -> None:
    """Lo que hace falta para escribir el texto sin perderlo: el formato no tiene escapes.

    Con ``invisible`` una palabra con caracteres invisibles también exige comillas (ver ``needs_quotes``).
    """
    if quoted:
        if '"' in text:
            raise EditError("quote_in_string")
    elif needs_quotes(text) if invisible else BARE_WORD_RE.fullmatch(text) is None:
        raise EditError("needs_quotes", {"text": text})


class Scalar:
    """Valor escalar: ``text`` sin comillas y si iba entre comillas (``quoted``).

    Rechaza (``EditError``) el texto que no se puede escribir (comillas dentro de una
    cadena, espacios o símbolos sin comillas) y el que el juego no lee bien (saltos de
    línea y caracteres de control; el tab sí se admite entre comillas).
    """

    __slots__ = ("_text", "_quoted")

    def __init__(self, text: str, quoted: bool = False):
        if not isinstance(text, str):
            raise EditTypeError("text_type", {"type": _type_name(text)})
        quoted = bool(quoted)
        _check_written(text, quoted)
        _check_line(text)
        self._text = text
        self._quoted = quoted

    @classmethod
    def _trusted(cls, text: str, quoted: bool) -> Scalar:
        scalar = _new(cls)
        scalar._text = text
        scalar._quoted = quoted
        return scalar

    @classmethod
    def _lenient(cls, text, quoted) -> Scalar:
        """Como el constructor, pero admite todo lo que puede leerse de un archivo (cadenas de varias
        líneas, palabras con caracteres invisibles...): solo exige que se pueda escribir tal cual."""
        if not isinstance(text, str):
            raise EditTypeError("text_type", {"type": _type_name(text)})
        quoted = bool(quoted)
        _check_written(text, quoted, invisible=False)
        return cls._trusted(text, quoted)

    @property
    def text(self) -> str:
        return self._text

    @property
    def quoted(self) -> bool:
        return self._quoted

    def as_int(self) -> int:
        if _INT_RE.fullmatch(self._text) is None:
            raise EditError("not_an_integer", {"text": self._text})
        return int(self._text)

    def as_float(self) -> float:
        if _NUMBER_RE.fullmatch(self._text) is None:
            raise EditError("not_a_number", {"text": self._text})
        return float(self._text)

    def as_bool(self) -> bool:
        lowered = self._text.lower()
        if lowered == "yes":
            return True
        if lowered == "no":
            return False
        raise EditError("not_a_bool", {"text": self._text})

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


def format_float(value) -> str:
    """Decimal exacto sin notación científica (el juego no la entiende).

    Es el texto más corto que identifica el valor (``0.1``, ``0.0000123``, ``3092.0``;
    con los ``float32`` de numpy, el más corto en esa precisión); el cero negativo se
    escribe ``0.0``. Infinito y NaN dan ``EditError``.
    """
    number = float(value)
    if not math.isfinite(number):
        raise EditError("not_finite", {"value": repr(number)})
    if number == 0:
        return "0.0"
    dtype = getattr(value, "dtype", None)
    shortest = str(value) if dtype is not None and dtype.kind == "f" and dtype.itemsize < 8 else float.__repr__(number)
    text = format(Decimal(shortest), "f")
    return text if "." in text else text + ".0"


def _number_text(value) -> str | None:
    """Texto de un bool o un número por su protocolo numérico (no por su ``str``/``repr``); None si no lo es."""
    if _is_bool(value):
        return "yes" if value else "no"
    if isinstance(value, numbers.Integral):
        return str(operator.index(value))
    if isinstance(value, numbers.Real):
        return format_float(value)
    return None


def key_text(key) -> str:
    """Texto de una clave de búsqueda: str, Scalar, entero o ClausewitzDate."""
    if key.__class__ is str:
        return key
    if isinstance(key, str):
        return str.__str__(key)
    if isinstance(key, Scalar):
        return key._text
    if isinstance(key, ClausewitzDate):
        return str(key)
    if isinstance(key, numbers.Integral) and not _is_bool(key):
        return str(operator.index(key))
    raise EditTypeError("invalid_key_type", {"type": _type_name(key)})


def coerce_key(key) -> Scalar:
    """Clave de una entrada nueva o renombrada; rechaza las vacías y las que el juego no reconocería."""
    text = key_text(key)
    if not text:
        raise EditError("empty_key")
    _check_line(text)
    match = INVISIBLE_RE.search(text)
    if match is not None:
        raise EditError("invisible_character", {"text": text, "codepoint": f"{ord(match.group()):04X}"})
    if isinstance(key, Scalar):
        return key
    if '"' in text:
        raise EditError("quote_in_string")
    return Scalar._trusted(text, needs_quotes(text))


def _simple_value(value) -> Scalar | Block | None:
    """``Scalar``/``Block`` de un valor que no es dict ni lista; None para esos dos."""
    cls = value.__class__
    if cls is Scalar:
        return value
    if cls is str:
        return Scalar(value, needs_quotes(value))
    if cls is int:
        return Scalar._trusted(int.__repr__(value), False)
    if cls is float:
        return Scalar._trusted(format_float(value), False)
    if isinstance(value, (Block, Scalar)):
        return value
    if isinstance(value, ClausewitzDate):
        return Scalar._trusted(str(value), False)
    if isinstance(value, str):
        text = str.__str__(value)
        return Scalar(text, needs_quotes(text))
    text = _number_text(value)
    if text is not None:
        return Scalar._trusted(text, False)
    if isinstance(value, (dict, list, tuple)):
        return None
    raise EditTypeError("unsupported_value", {"type": _type_name(value)})


def _container_items(value):
    """Pares (clave, valor) de un dict o (None, valor) de una lista o tupla."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key is None:
                raise EditTypeError("dict_none_key")
            yield key, item
    else:
        for item in value:
            yield None, item


def coerce_value(value) -> Scalar | Block:
    """Convierte un valor de Python en ``Scalar`` o ``Block`` (ver ``Block.set``).

    Un dict da un bloque de asignaciones ``clave = valor`` y una lista o tupla un
    bloque de valores sueltos; para claves repetidas u operadores, ``Block.from_pairs``.
    """
    simple = _simple_value(value)
    if simple is not None:
        return simple
    root = Block()
    active = {id(value)}  # contenedores en conversión: uno que se contiene a sí mismo es un ciclo
    stack = [(value, root, _container_items(value))]
    while stack:
        source, block, items = stack[-1]
        for key, item in items:
            node = _simple_value(item)
            child = None
            if node is None:
                if id(item) in active:
                    raise EditError("cycle")
                node = child = Block()
                active.add(id(item))
                stack.append((item, child, _container_items(item)))
            block.entries.append(Entry._made(None if key is None else coerce_key(key), node))
            if child is not None:
                break
        else:
            active.discard(id(source))
            stack.pop()
    return root


def _check_op(op) -> str:
    if op not in OPERATORS:
        raise EditError("invalid_operator", {"op": op, "allowed": ", ".join(OPERATORS)})
    return op


def normalize_comments(comments) -> list[str]:
    """Líneas de comentario ``# ...`` a partir de un texto o una lista (una línea por elemento).

    Se parten los saltos de línea, se quitan los espacios finales y se añade ``# `` a
    las líneas que no empiezan por ``#``; los caracteres de control dan ``EditError``.
    """
    if isinstance(comments, str):
        comments = [comments]
    lines = []
    for comment in comments:
        if not isinstance(comment, str):
            raise EditTypeError("text_type", {"type": _type_name(comment)})
        for line in re.split("\r\n?|\n", comment):
            line = line.rstrip()
            match = CONTROL_RE.search(line)
            if match is not None:
                raise EditError("control_character", {"text": line, "codepoint": f"{ord(match.group()):04X}"})
            lines.append(line if line.startswith("#") else "# " + line if line else "#")
    return lines


def normalize_line_comment(comment) -> str:
    """Comentario de una sola línea (como ``normalize_comments``); "" para ninguno (None o "")."""
    if comment is None or comment == "":
        return ""
    lines = normalize_comments(comment)
    if len(lines) != 1:
        raise EditError("line_break", {"text": comment})
    return lines[0]


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


class _Replaced(Token):
    """Token de un valor sustituido: conserva trivia y posición y recuerda el leído (``source``) para deshacer."""

    __slots__ = ("source",)

    def __init__(self, source: Token):
        super().__init__(source.kind, None, source.trivia, source.offset, source.line, source.column)
        self.source = source


def starts_document(token: Token) -> bool:
    """True si la trivia del token empieza en el primer carácter del archivo."""
    return token.offset == len(token.trivia)


def _blocks_under(node: Block):
    """Bloques del subárbol de ``node`` (incluido), cada uno una vez aunque se repita."""
    seen = {id(node)}
    stack = [node]
    while stack:
        block = stack.pop()
        yield block
        for entry in block.entries:
            value = entry._value
            if value.__class__ is not Scalar and id(value) not in seen:
                seen.add(id(value))
                stack.append(value)


def _same_value(actual, wanted: str) -> bool:
    """Compara un valor con el texto buscado; los números y las fechas, por su valor."""
    if actual.__class__ is not Scalar:
        return False
    text = actual._text
    if text == wanted:
        return True
    if _NUMBER_RE.fullmatch(text) and _NUMBER_RE.fullmatch(wanted):
        return float(text) == float(wanted)
    if _DATE_RE.fullmatch(text) and _DATE_RE.fullmatch(wanted):
        try:
            return ClausewitzDate.parse(text) == ClausewitzDate.parse(wanted)
        except ValueError:
            return False
    return False


def _wanted_text(value) -> str:
    """Texto de un valor buscado: str, Scalar, número, bool o fecha."""
    if isinstance(value, (str, Scalar, ClausewitzDate)):
        return key_text(value)
    text = _number_text(value)
    if text is None:
        raise EditTypeError("unsupported_value", {"type": _type_name(value)})
    return text


class Entry:
    """``clave op valor`` o, con ``key`` None, un valor suelto (``{ 1 2 3 }``)."""

    __slots__ = ("_key", "_op", "_value", "_ktok", "_otok", "_vtok", "_comments", "_line_comment")

    def __init__(self, key, op: str | None = "=", value=None):
        if value is None:
            raise EditTypeError("entry_without_value")
        if key is None:
            self._key = None
            self._op = None
        else:
            self._key = coerce_key(key)
            self._op = _check_op("=" if op is None else op)
        self._value = coerce_value(value)
        self._ktok = self._otok = self._vtok = None
        self._comments = None
        self._line_comment = None

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
        entry._line_comment = None
        return entry

    @classmethod
    def _made(cls, key: Scalar | None, value: Scalar | Block, op: str = "=") -> Entry:
        """Entrada nueva con clave y valor ya validados."""
        return cls._parsed(key, None, None if key is None else op, None, value, None)

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
            raise EditError("loose_value_operator")
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
        """Con un ``str`` se conservan las comillas del valor anterior (``name = "X"``).

        Volver a poner el valor leído (el mismo bloque o un escalar igual) devuelve su texto
        original exacto: deshacer un cambio de valor no altera el archivo.
        """
        old = self._value
        if isinstance(value, str) and old.__class__ is Scalar and old._quoted:
            new = Scalar(str.__str__(value), True)
        else:
            new = coerce_value(value)
        if new is old:
            return
        if new.__class__ is not Scalar and any(e is self for b in _blocks_under(new) for e in b.entries):
            raise EditError("cycle")
        # Token del valor leído: el del escalar, la "{" del bloque o el que recuerda un _Replaced.
        token = self._vtok
        if token is None:
            source = None if old.__class__ is Scalar else old._open
        elif token.raw is not None:
            source = token
        else:
            source = token.source if token.__class__ is _Replaced else None
        if source is not None:
            kind = source.kind
            if new.__class__ is not Scalar:
                self._vtok = None if new._open is source else _Replaced(source)
            elif kind <= OPEN_STRING and new == Scalar._trusted(scalar_text(kind, source.raw), kind != WORD):
                self._vtok = source
            else:
                self._vtok = _Replaced(source)
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
        """Comentarios de las líneas propias de encima de la entrada (``["# ..."]``).

        No incluye el de final de la línea anterior, que es ``line_comment`` de la entrada
        anterior. Asignar una lista (o un texto) los sustituye; ``[]`` los quita.
        """
        if self._comments is not None:
            return list(self._comments)
        token = first_token(self)
        return [] if token is None else head_comments(token.trivia, starts_document(token))

    @comments.setter
    def comments(self, comments) -> None:
        self._comments = normalize_comments(comments)

    @property
    def line_comment(self) -> str | None:
        """Comentario al final de la línea de la entrada (``"# ..."``) o None.

        Asignar None lo quita; al asignar un texto se le añade ``# `` si no lo lleva.
        """
        return self._line_comment or None

    @line_comment.setter
    def line_comment(self, comment) -> None:
        self._line_comment = normalize_line_comment(comment)

    def clone(self, *, comments: bool = True) -> Entry:
        """Copia profunda sin formato de origen, lista para insertarla en otro archivo.

        Conserva claves, operadores y textos (con sus comillas) y, con ``comments``,
        todos los comentarios; se formatea según su destino, como lo creado por código.
        """
        value = self._value
        copy = Entry._made(self._key, value if value.__class__ is Scalar else _clone_block(value, comments), self._op)
        if comments:
            copy._comments = self.comments
            copy._line_comment = self._line_comment or None
        return copy

    def __repr__(self) -> str:
        value = self._value
        shown = repr(value) if value.__class__ is Scalar else f"<Block {len(value.entries)} entries>"
        if self._key is None:
            return f"Entry({shown})"
        return f"Entry({self._key!r} {self._op} {shown})"


def _block_shell(block: Block, comments: bool) -> Block:
    """Bloque nuevo vacío con los comentarios propios de ``block``."""
    shell = Block()
    if comments:
        shell._open_comment = block.open_comment or ""
        shell._trailing_comments = block.trailing_comments
    return shell


def _clone_block(block: Block, comments: bool) -> Block:
    root = _block_shell(block, comments)
    active = {id(block)}
    stack = [(block, root, iter(block.entries))]
    while stack:
        source, target, items = stack[-1]
        for entry in items:
            value = entry._value
            child = None
            if value.__class__ is not Scalar:
                if id(value) in active:
                    raise EditError("cycle")
                child = _block_shell(value, comments)
                active.add(id(value))
                stack.append((value, child, iter(value.entries)))
            copy = Entry._made(entry._key, value if child is None else child, entry._op)
            if comments:
                copy._comments = entry.comments
                copy._line_comment = entry._line_comment or None
            target.entries.append(copy)
            if child is not None:
                break
        else:
            active.discard(id(source))
            stack.pop()
    return root


class Block:
    """Bloque ``{ ... }``: lista ordenada de entradas (asignaciones y/o valores sueltos)."""

    __slots__ = ("entries", "_open", "_close", "_unclosed", "_orig", "_open_comment", "_trailing_comments")

    def __init__(self, entries=None):
        self.entries: list[Entry] = []
        if entries is not None:
            for entry in entries:
                if not isinstance(entry, Entry):
                    raise EditTypeError("not_an_entry", {"type": _type_name(entry)})
                self.entries.append(entry)
        self._open = self._close = None
        self._unclosed = False
        self._orig = None  # entradas en el orden leído (las pone el parser)
        self._open_comment = None
        self._trailing_comments = None

    @classmethod
    def _parsed(cls, open_token: Token) -> Block:
        block = _new(cls)
        block.entries = []
        block._open = open_token
        block._close = None
        block._unclosed = False
        block._orig = None
        block._open_comment = None
        block._trailing_comments = None
        return block

    @classmethod
    def from_pairs(cls, pairs) -> Block:
        """Bloque nuevo desde pares ``(clave, valor)`` o ``(clave, operador, valor)``.

        Admite claves repetidas y operadores, que un dict no puede expresar::

            Block.from_pairs([("tag", "GEL"), ("tag", "MAJ"), ("literacy", ">", 0.5)])

        Una clave None da un valor suelto. Los valores admiten lo mismo que ``set``.
        """
        block = cls()
        for pair in pairs:
            if not isinstance(pair, (tuple, list)) or len(pair) not in (2, 3):
                raise EditTypeError("pair_shape", {"value": repr(pair)})
            key, op, value = (pair[0], "=", pair[1]) if len(pair) == 2 else pair
            block.entries.append(Entry(key, None if key is None else op, value))
        return block

    # --- consulta ---------------------------------------------------------------

    def __iter__(self):
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, key) -> bool:
        return self.find(key) is not None

    def _select(self, key, value, ignore_case: bool):
        """Entradas con esa clave (y, si se da, ese valor), en orden."""
        text = key_text(key)
        wanted = None if value is _ANY else _wanted_text(value)
        if ignore_case:
            text = text.lower()
        for entry in self.entries:
            found = entry._key
            if found is None:
                continue
            found = found._text.lower() if ignore_case else found._text
            if found == text and (wanted is None or _same_value(entry._value, wanted)):
                yield entry

    def find(self, key, value=_ANY, *, ignore_case: bool = False) -> Entry | None:
        """Primera entrada con esa clave; con ``value``, la primera que además tiene ese valor.

        ``value`` se compara con el texto del escalar; los números y las fechas por su
        valor (``5`` encuentra ``5.000``).
        """
        return next(self._select(key, value, ignore_case), None)

    def find_all(self, key, value=_ANY, *, ignore_case: bool = False) -> list[Entry]:
        return list(self._select(key, value, ignore_case))

    def get(self, key, default=None, *, ignore_case: bool = False):
        entry = self.find(key, ignore_case=ignore_case)
        return default if entry is None else entry._value

    def get_all(self, key, *, ignore_case: bool = False) -> list:
        return [entry._value for entry in self._select(key, _ANY, ignore_case)]

    def get_text(self, key, default=None, *, ignore_case: bool = False):
        """Texto del primer valor escalar con esa clave."""
        for entry in self._select(key, _ANY, ignore_case):
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

    def index_by_key(self, *, ignore_case: bool = False) -> dict[str, list[Entry]]:
        """Índice ``clave -> [entradas]`` (en minúsculas con ``ignore_case``) para búsquedas repetidas.

        Es una foto: no se actualiza al editar el bloque.
        """
        index: dict[str, list[Entry]] = {}
        for entry in self.entries:
            if entry._key is not None:
                text = entry._key._text
                index.setdefault(text.lower() if ignore_case else text, []).append(entry)
        return index

    def _path_item(self, item, ignore_case: bool) -> Entry | None:
        if isinstance(item, str):
            match = _POSITION_RE.fullmatch(item)
            if match is not None:
                position = int(match.group(1))
                return self.entries[position] if position < len(self.entries) else None
        return self.find(item, ignore_case=ignore_case)

    def find_path(self, path, *, ignore_case: bool = False) -> Entry | None:
        """Entrada al final de ``path``, una secuencia de claves desde este bloque.

        Cada elemento es una clave (la primera entrada que la tiene) o ``"[i]"``, la
        entrada en la posición ``i``: ``doc.find_path(("country_event", "option", "name"))``.
        ``walk`` usa ``"[i]"`` solo para los valores sueltos, así que con claves repetidas
        su ruta lleva a la primera; ``path_of`` da la ruta exacta de una entrada.
        """
        if isinstance(path, (str, Scalar)):
            raise EditTypeError("invalid_path_item", {"item": repr(path)})
        block = self
        entry = None
        for item in path:
            if entry is not None:
                block = entry._value
                if block.__class__ is Scalar:
                    return None
            entry = block._path_item(item, ignore_case)
            if entry is None:
                return None
        return entry

    def get_path(self, path, default=None, *, ignore_case: bool = False):
        """Valor de ``find_path(path)``, o ``default`` si no existe."""
        entry = self.find_path(path, ignore_case=ignore_case)
        return default if entry is None else entry._value

    def path_of(self, entry: Entry) -> tuple[str, ...] | None:
        """Ruta de ``entry`` bajo este bloque, tal que ``find_path`` la devuelva; None si no está.

        Usa la clave si es su primera aparición en el bloque y ``"[i]"`` si no.
        """
        stack = [(self, -1)]
        active = {id(self)}
        iterators = [enumerate(self.entries)]
        while iterators:
            for index, candidate in iterators[-1]:
                stack[-1] = (stack[-1][0], index)
                if candidate is entry:
                    path = []
                    for block, position in stack:
                        found = block.entries[position]
                        key = found._key
                        first = key is not None and block.find(key) is found
                        path.append(key._text if first else f"[{position}]")
                    return tuple(path)
                value = candidate._value
                if value.__class__ is not Scalar:
                    if id(value) in active:
                        raise EditError("cycle")
                    active.add(id(value))
                    stack.append((value, -1))
                    iterators.append(enumerate(value.entries))
                    break
            else:
                active.discard(id(stack.pop()[0]))
                iterators.pop()
        return None

    @property
    def line(self) -> int | None:
        return None if self._open is None else self._open.line

    @property
    def column(self) -> int | None:
        return None if self._open is None else self._open.column

    @property
    def is_closed(self) -> bool:
        """False si el bloque se leyó de un archivo y le falta la llave de cierre (ver ``close``)."""
        return not self._unclosed

    @property
    def open_comment(self) -> str | None:
        """Comentario al final de la línea de la ``{`` (antes de la primera entrada) o None."""
        if self._open_comment is not None:
            return self._open_comment or None
        if self._open is None:
            return None
        if self._orig:
            token = first_token(self._orig[0])
            return None if token is None else tail_comment(token.trivia)
        return None if self._close is None else tail_comment(self._close.trivia)

    @open_comment.setter
    def open_comment(self, comment) -> None:
        self._open_comment = normalize_line_comment(comment)

    @property
    def trailing_comments(self) -> list[str]:
        """Comentarios de las líneas propias entre la última entrada y la llave de cierre."""
        if self._trailing_comments is not None:
            return list(self._trailing_comments)
        token = self._closer_token()
        return [] if token is None else head_comments(token.trivia, starts_document(token))

    @trailing_comments.setter
    def trailing_comments(self, comments) -> None:
        self._trailing_comments = normalize_comments(comments)

    def _closer_token(self) -> Token | None:
        return self._close

    # --- edición ----------------------------------------------------------------

    def _check_cycle(self, value) -> None:
        """Un bloque no puede quedar dentro de sí mismo (ni de un descendiente suyo)."""
        if value.__class__ is not Scalar and any(block is self for block in _blocks_under(value)):
            raise EditError("cycle")

    def _new_entry(self, key, value, op) -> Entry:
        entry = Entry(key, None if key is None else op, value)
        self._check_cycle(entry._value)
        return entry

    def _index_of(self, entry: Entry) -> int:
        try:
            return self.entries.index(entry)  # Entry no redefine ==: se compara por identidad
        except ValueError:
            raise EditError("entry_not_in_block") from None

    def set(self, key, value, *, op: str | None = None, ignore_case: bool = False) -> Entry:
        """Reemplaza el valor de la primera entrada con esa clave o, si no existe, la añade.

        Con un ``str`` se conservan las comillas del valor anterior (``name = "X"``). Con
        ``op`` se cambia también el operador (``set("literacy", 0.5, op=">")``).
        """
        if op is not None:
            _check_op(op)
        entry = self.find(key, ignore_case=ignore_case)
        if entry is None:
            return self.append(key, value, "=" if op is None else op)
        entry.value = value
        if op is not None:
            entry.op = op
        return entry

    def append(self, key, value, op: str = "=") -> Entry:
        entry = self._new_entry(key, value, op)
        self.entries.append(entry)
        return entry

    def append_value(self, value) -> Entry:
        return self.append(None, value)

    def insert(self, index: int, key, value, op: str = "=") -> Entry:
        """Inserta una entrada nueva en la posición ``index`` (como ``list.insert``)."""
        entry = self._new_entry(key, value, op)
        self.entries.insert(index, entry)
        return entry

    def insert_before(self, entry: Entry, key, value, op: str = "=") -> Entry:
        """Inserta una entrada nueva justo antes de ``entry`` (que debe estar en el bloque)."""
        return self.insert(self._index_of(entry), key, value, op)

    def insert_after(self, entry: Entry, key, value, op: str = "=") -> Entry:
        """Inserta una entrada nueva justo después de ``entry`` (que debe estar en el bloque)."""
        return self.insert(self._index_of(entry) + 1, key, value, op)

    def insert_entry(self, index: int, entry: Entry) -> Entry:
        """Inserta una entrada existente (movida o borrada antes) en la posición ``index``.

        Deshacer ``remove_entry`` es ``insert_entry(índice_devuelto, entrada)``: el texto
        vuelve a ser el original.
        """
        if not isinstance(entry, Entry):
            raise EditTypeError("not_an_entry", {"type": _type_name(entry)})
        self._check_cycle(entry._value)
        self.entries.insert(index, entry)
        return entry

    def move(self, entry: Entry, index: int | None = None, *, to: Block | None = None) -> Entry:
        """Mueve una entrada de este bloque a la posición ``index`` de ``to`` (por defecto, este).

        ``index`` es la posición final (como ``list.insert`` tras quitarla); None, al final.
        La entrada conserva sus tokens, se lleva sus comentarios y se sangra según su
        nuevo sitio. Para llevarla a otro archivo, ``clone()``.
        """
        target = self if to is None else to
        if not isinstance(target, Block):
            raise EditTypeError("not_a_node", {"type": _type_name(target)})
        position = self._index_of(entry)
        target._check_cycle(entry._value)
        del self.entries[position]
        if index is None:
            target.entries.append(entry)
        else:
            target.entries.insert(index, entry)
        return entry

    def remove(self, key, value=_ANY, *, ignore_case: bool = False) -> int:
        """Elimina las entradas con esa clave (y, si se da, ese valor); devuelve cuántas.

        ``remove("add_core", "RUS")`` quita solo ``add_core = RUS``.
        """
        targets = list(self._select(key, value, ignore_case))
        for entry in targets:
            self.remove_entry(entry)
        return len(targets)

    def remove_entry(self, entry: Entry) -> int:
        """Quita la entrada y devuelve su índice (para deshacer con ``insert_entry``).

        Al serializar se elimina su línea entera, con su comentario de final de línea, y
        se conservan los comentarios de las líneas de encima.
        """
        index = self._index_of(entry)
        del self.entries[index]
        return index

    def close(self) -> None:
        """Añade la llave de cierre que le falta a un bloque leído, y a los que contiene.

        La ``}`` se escribe al final del archivo, tras lo que contiene el bloque y sus
        comentarios finales, en una línea propia con la sangría de su línea de apertura.
        """
        for block in _blocks_under(self):
            block._unclosed = False

    def clone(self, *, comments: bool = True) -> Block:
        """Copia profunda sin formato de origen (ver ``Entry.clone``)."""
        return _clone_block(self, comments)

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

    @property
    def open_comment(self) -> None:
        """Un documento no tiene ``{``: los comentarios de cabecera son de su primera entrada."""
        return None

    def _closer_token(self) -> Token | None:
        return self._eof

    def unclosed_blocks(self) -> list[Block]:
        """Bloques sin llave de cierre, del más externo al más interno (ver ``Block.close``)."""
        found = []
        stack = [self]
        seen = {id(self)}
        while stack:
            block = stack.pop()
            if block._unclosed:
                found.append(block)
            for entry in reversed(block.entries):
                value = entry._value
                if value.__class__ is not Scalar and id(value) not in seen:
                    seen.add(id(value))
                    stack.append(value)
        return found

    def check_text(self, text: str, *, key: bool = False) -> EditError | None:
        """Problema que tendría ``text`` como valor (o clave, con ``key``) de este documento; None si ninguno.

        Comprueba lo mismo que ``set``/``append`` y, además, que se pueda guardar en la
        codificación del documento: sirve para avisar en un formulario mientras se teclea.
        """
        if not isinstance(text, str):
            raise EditTypeError("text_type", {"type": _type_name(text)})
        try:
            if key:
                coerce_key(text)
            else:
                coerce_value(text)
        except EditError as error:
            return error
        encoding = self.encoding or GAME_ENCODING
        problems = find_unencodable(text, encoding)
        if problems:
            char = problems[0][3]
            params = {"char": char, "codepoint": f"{ord(char):04X}", "encoding": encoding}
            return EditError("unencodable_character", params)
        return None

    def __repr__(self) -> str:
        return f"<Document {len(self.entries)} entries>"
