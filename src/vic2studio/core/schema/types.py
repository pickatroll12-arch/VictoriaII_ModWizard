"""Tipos de valor del motor de esquemas (wizard §10.1).

Un ``ValueType`` describe cómo se lee y se escribe un valor del CST sin pérdidas
(I3): ``read`` convierte un ``Scalar`` o ``Block`` en un valor de Python
(``ValueError`` si no encaja), ``write`` convierte un valor de Python en lo que
``Block.set`` acepta (``Scalar``, ``Block``, ``int``, ``str``…), ``check``
valida el nodo contra las reglas del juego y ``example`` da un valor válido
para el arnés de pruebas (§19.3). ``describe`` es la descripción legible para
docgen («entero de 0 a 100»).

``check`` de los tipos simples está vacío: la forma la comprueba ``read`` y
``Record.issues`` emite ``bad_type`` con la línea exacta; las referencias
rotas de ``Ref`` llegarán con los esquemas que lo usen. La lógica de los tipos
que no usan ``government`` ni ``unit`` (``Color``, ``ListOf``, ``Path``,
``LocKey``, ``SpriteFrame``, ``Picture``, ``from_spec``) sigue como contrato y
lanza ``NotImplementedError``.

``widget`` es una pista para el formulario generado (``int``, ``float``,
``bool``, ``date``, ``word``, ``text``, ``enum``, ``ref``, ``color``, ``list``,
``path``, ``lockey``, ``sprite``, ``picture``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..clausewitz.nodes import Block, ClausewitzDate, Scalar, format_float
from ..texts import text

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from ..index.model import Symbol
    from ..validate.model import Problem
    from .validate import CheckContext


def _scalar(node, what: str) -> Scalar:
    """El ``Scalar`` de ``node``; ``ValueError`` si es un bloque (``what`` lo explica)."""
    if not isinstance(node, Scalar):
        raise ValueError(f"{what}: se esperaba un valor, no un bloque")
    return node


def _decimal_places(source: str) -> int:
    """Decimales del texto tal como está escrito (``"4.00"`` → 2, ``"8"`` → 0): se conservan
    al escribir otro número (criterio 6: ``maximum_speed = 4.00`` puesto a 5 queda ``5.00``)."""
    if "." not in source:
        return 0
    return len(source.rsplit(".", 1)[1])


class ValueType:
    """Base de los tipos de valor. ``widget`` dice al formulario qué editor usar."""

    widget: str = "text"

    def read(self, node: Scalar | Block) -> object:
        """CST → valor de Python; ``ValueError`` si el nodo no encaja."""
        raise NotImplementedError

    def write(self, value: object, old: Scalar | Block | None) -> object:
        """Valor de Python → valor que acepta ``Block.set``, conservando el formato de ``old`` (I3)."""
        raise NotImplementedError

    def check(self, node: Scalar | Block, ctx: CheckContext) -> Iterable[Problem]:
        """Problemas del nodo contra el juego (referencias rotas, cotas…); vacío si está bien."""
        return ()

    def example(self, ctx: CheckContext) -> object:
        """Un valor válido (para el arnés de pruebas y la plantilla de «Nuevo»)."""
        raise NotImplementedError

    def describe(self, lang: str = "en") -> str:
        """Descripción legible para docgen: «entero de 0 a 100», «sí/no»…"""
        raise NotImplementedError


@dataclass(frozen=True)
class FromSymbol:
    """Cota dinámica sacada del índice: ``Int(min=FromSymbol(K.BUILDING, "railroad", "max_level"))``.

    ``attr`` es el atributo del símbolo ``(kind, name)`` en el índice; ``None`` si el símbolo no
    existe o no lleva el atributo.
    """

    kind: str
    name: str
    attr: str

    def resolve(self, ctx: CheckContext) -> object | None:
        """Valor de la cota según el índice del contexto; ``None`` si no se puede resolver."""
        return ctx.index.attrs(self.kind, self.name, self.attr)


@dataclass(frozen=True)
class Int(ValueType):
    """Entero, con cota opcional ``min``/``max`` (números o ``FromSymbol``) y ``unit`` para docgen."""

    min: object | None = None
    max: object | None = None
    unit: str | None = None
    widget: str = "int"

    def read(self, node: Scalar | Block) -> int:
        return _scalar(node, "entero").as_int()

    def write(self, value: object, old: Scalar | Block | None) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"se esperaba un entero, no {type(value).__name__}")
        return value

    def example(self, ctx: CheckContext) -> int:
        if isinstance(self.min, int):
            return self.min
        if isinstance(self.max, int):
            return self.max
        return 0

    def describe(self, lang: str = "en") -> str:
        unit = f" {self.unit}" if self.unit else ""
        if self.min is not None and self.max is not None and not isinstance(self.min, FromSymbol) \
                and not isinstance(self.max, FromSymbol):
            return text("schema.type.int_range", lang, min=self.min, max=self.max, unit=unit)
        return text("schema.type.int", lang, unit=unit)


@dataclass(frozen=True)
class Float(ValueType):
    """Decimal. Al escribir se conservan los decimales del texto anterior (``25.0`` → ``30.0``, I3)."""

    min: float | None = None
    max: float | None = None
    step: float = 0.1
    widget: str = "float"

    def read(self, node: Scalar | Block) -> float:
        return _scalar(node, "número").as_float()

    def write(self, value: object, old: Scalar | Block | None) -> object:
        number = float(value)   # ValueError si no es numérico
        if isinstance(value, bool):
            raise ValueError("se esperaba un número, no un booleano")
        places = _decimal_places(old.text) if isinstance(old, Scalar) else 0
        if places:
            return Scalar(f"{number:.{places}f}", False)
        rendered = format_float(number)
        if rendered.endswith(".0"):
            rendered = rendered[:-2]   # «8» se conserva entero, como en vanilla
        return Scalar(rendered, False)

    def example(self, ctx: CheckContext) -> float:
        return 0.0 if self.min is None else self.min

    def describe(self, lang: str = "en") -> str:
        return text("schema.type.float", lang, min="" if self.min is None else self.min,
                    max="" if self.max is None else self.max)


@dataclass(frozen=True)
class Bool(ValueType):
    """Sí/no del motor (``yes``/``no``)."""

    widget: str = "bool"

    def read(self, node: Scalar | Block) -> bool:
        return _scalar(node, "sí/no").as_bool()

    def write(self, value: object, old: Scalar | Block | None) -> object:
        if not isinstance(value, bool):
            raise ValueError(f"se esperaba un booleano, no {type(value).__name__}")
        return "yes" if value else "no"

    def example(self, ctx: CheckContext) -> bool:
        return True

    def describe(self, lang: str = "en") -> str:
        return text("schema.type.bool", lang)


@dataclass(frozen=True)
class Date(ValueType):
    """Fecha del juego (``ClausewitzDate``); se conservan las comillas si las había (H20)."""

    widget: str = "date"

    def read(self, node: Scalar | Block) -> ClausewitzDate:
        return _scalar(node, "fecha").as_date()

    def write(self, value: object, old: Scalar | Block | None) -> object:
        if not isinstance(value, ClausewitzDate):
            raise ValueError(f"se esperaba una fecha, no {type(value).__name__}")
        quoted = isinstance(old, Scalar) and old.quoted
        return Scalar(str(value), quoted)

    def example(self, ctx: CheckContext) -> ClausewitzDate:
        return ClausewitzDate(1836, 1, 1)

    def describe(self, lang: str = "en") -> str:
        return text("schema.type.date", lang)


@dataclass(frozen=True)
class Word(ValueType):
    """Palabra sin comillas (ids, banderas); ``pattern`` opcional valida su forma."""

    pattern: str | None = None
    widget: str = "word"

    def read(self, node: Scalar | Block) -> str:
        scalar = _scalar(node, "palabra")
        if scalar.quoted:
            raise ValueError("se esperaba una palabra sin comillas")
        return scalar.text

    def write(self, value: object, old: Scalar | Block | None) -> object:
        if not isinstance(value, str):
            raise ValueError(f"se esperaba una palabra, no {type(value).__name__}")
        if self.pattern is not None:
            import re

            if re.fullmatch(self.pattern, value) is None:
                raise ValueError(f"{value!r} no cumple el patrón {self.pattern}")
        return Scalar(value, False)

    def example(self, ctx: CheckContext) -> str:
        return "example"

    def describe(self, lang: str = "en") -> str:
        return text("schema.type.word", lang)


@dataclass(frozen=True)
class Text(ValueType):
    """Cadena entre comillas (``quoted=True``) o tal cual."""

    quoted: bool = True
    widget: str = "text"

    def read(self, node: Scalar | Block) -> str:
        return _scalar(node, "texto").text

    def write(self, value: object, old: Scalar | Block | None) -> object:
        if not isinstance(value, str):
            raise ValueError(f"se esperaba un texto, no {type(value).__name__}")
        return Scalar(value, self.quoted)

    def example(self, ctx: CheckContext) -> str:
        return "Example"

    def describe(self, lang: str = "en") -> str:
        return text("schema.type.text", lang)


@dataclass(frozen=True, init=False)
class Enum(ValueType):
    """Uno de unos valores fijos del motor (``flagType``, ``Orientation``…)."""

    values: tuple[str, ...]
    widget: str = "enum"

    def __init__(self, *values: str, widget: str = "enum"):
        if not values:
            raise ValueError("Enum necesita al menos un valor")
        object.__setattr__(self, "values", tuple(values))
        object.__setattr__(self, "widget", widget)

    def read(self, node: Scalar | Block) -> str:
        scalar = _scalar(node, "valor fijo")
        if scalar.text not in self.values:
            raise ValueError(f"{scalar.text!r} no es uno de {', '.join(self.values)}")
        return scalar.text

    def write(self, value: object, old: Scalar | Block | None) -> object:
        if value not in self.values:
            raise ValueError(f"{value!r} no es uno de {', '.join(self.values)}")
        return Scalar(str(value), False)

    def example(self, ctx: CheckContext) -> str:
        return self.values[0]

    def describe(self, lang: str = "en") -> str:
        return text("schema.type.enum", lang, values=", ".join(self.values))


@dataclass(frozen=True)
class Ref(ValueType):
    """Símbolo del índice (``Ref("tag")``, ``Ref("goods", allow_new=True)``).

    ``filter(symbol, record) -> bool`` descarta candidatos; ``allow_new`` admite un id que aún
    no existe (para crearlo después).
    """

    kind: str
    filter: Callable[[Symbol, "Record"], bool] | None = None  # noqa: F821 - Record de .record
    allow_new: bool = False
    widget: str = "ref"

    def read(self, node: Scalar | Block) -> str:
        return _scalar(node, "referencia").text

    def write(self, value: object, old: Scalar | Block | None) -> object:
        if not isinstance(value, str):
            raise ValueError(f"se esperaba un id, no {type(value).__name__}")
        return Scalar(value, False)

    def check(self, node: Scalar | Block, ctx: CheckContext) -> Iterable[Problem]:
        from ..clausewitz.diagnostics import Severity
        from ..validate.model import Problem

        try:
            name = self.read(node)
        except ValueError:
            return ()
        if ctx.index is None or ctx.index.exists(self.kind, name) or self.allow_new:
            return ()
        return (Problem("ref_missing", Severity.ERROR, None, None, None, None, (),
                        {"kind": self.kind, "name": name}),)

    def example(self, ctx: CheckContext) -> str:
        names = ctx.index.names(self.kind) if ctx.index is not None else []
        return names[0] if names else "example"

    def describe(self, lang: str = "en") -> str:
        return text("schema.type.ref", lang, kind=self.kind)


@dataclass(frozen=True)
class Color(ValueType):
    """``{ r g b }``; ``scale=1.0`` en ``religion.txt``."""

    scale: float = 255
    widget: str = "color"


@dataclass(frozen=True)
class ListOf(ValueType):
    """Lista de valores sueltos: ``{ 1 2 3 }`` o ``{ "a" "b" }`` (``region.txt``)."""

    item: ValueType
    unique: bool = False
    widget: str = "list"


@dataclass(frozen=True)
class Path(ValueType):
    """Ruta a otro archivo (``oob = "ARG_oob.txt"``, relativa a ``base``); valida el sufijo."""

    base: str
    suffixes: tuple[str, ...] = (".txt",)
    widget: str = "path"


@dataclass(frozen=True)
class LocKey(ValueType):
    """El VALOR es una clave de localización (``title = "EVTNAME16000"``).

    ``suggest`` es una plantilla de clave sugerida para el selector (``EVTNAME{id}``).
    """

    suggest: str | None = None
    widget: str = "lockey"


@dataclass(frozen=True)
class SpriteFrame(ValueType):
    """Índice de fotograma de un sprite (``sprite_index`` → ``GFX_diplo_wargoal_icons``)."""

    sprite: str
    widget: str = "sprite"


@dataclass(frozen=True)
class Picture(ValueType):
    """``picture = X`` → ``gfx/pictures/<folder>/X.(tga|dds)``; ``default``, plantilla (H21)."""

    folder: str
    default: str = "{id}"
    widget: str = "picture"


def from_spec(spec: dict) -> ValueType:
    """Tipo desde JSON (``{"type": "ref", "kind": "tag"}``): el catálogo de guion usa los mismos.

    Mismas claves que los parámetros de las dataclasses de arriba.
    """
    raise NotImplementedError
