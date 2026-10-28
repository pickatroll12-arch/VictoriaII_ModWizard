"""Tipos de valor del motor de esquemas (wizard §10.1).

Un ``ValueType`` describe cómo se lee y se escribe un valor del CST sin pérdidas
(I3): ``read`` convierte un ``Scalar`` o ``Block`` en un valor de Python
(``ValueError`` si no encaja), ``write`` convierte un valor de Python en lo que
``Block.set`` acepta (``Scalar``, ``Block``, ``int``, ``str``…), ``check``
valida el nodo contra las reglas del juego y ``example`` da un valor válido
para el arnés de pruebas (§19.3). ``describe`` es la descripción legible para
docgen («entero de 0 a 100»).

``check`` de los tipos simples está vacío: la forma la comprueba ``read`` y
``Record.issues`` emite ``bad_type`` con la línea exacta. ``Color`` y
``ListOf`` editan su bloque en su sitio: los valores que no cambian conservan
su texto (I3).

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
        unit = f" ({text(f'schema.measure.{self.unit}', lang)})" if self.unit else ""
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
        from ..clausewitz.nodes import needs_quotes

        if not isinstance(value, str):
            raise ValueError(f"se esperaba un texto, no {type(value).__name__}")
        quoted = old.quoted if isinstance(old, Scalar) else self.quoted
        return Scalar(value, quoted or needs_quotes(value))

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


def _loose_values(node, what: str) -> list[Scalar]:
    """Los valores sueltos de un bloque ``{ a b c }``; ``ValueError`` si es un escalar o lleva asignaciones."""
    if not isinstance(node, Block):
        raise ValueError(f"{what}: se esperaba un bloque {{ … }}")
    values = []
    for entry in node.entries:
        if entry.key is not None or not isinstance(entry.value, Scalar):
            raise ValueError(f"{what}: el bloque lleva asignaciones")
        values.append(entry.value)
    return values


def _edit_loose_block(old: Block, texts: list[tuple[str, bool]]) -> Block:
    """Lleva el bloque de valores sueltos ``old`` a ``texts`` editándolo en su sitio (I3).

    Los valores que siguen igual conservan su entrada (y su sangría y saltos de línea): solo se quitan los
    que desaparecen y se insertan los nuevos, así que añadir un nombre a ``first_names`` toca una línea.
    """
    from difflib import SequenceMatcher

    from ..clausewitz.nodes import Entry

    current = [entry.value.text for entry in old.entries]
    wanted = [text for text, _ in texts]
    matcher = SequenceMatcher(None, current, wanted, autojunk=False)
    # De atrás adelante: los índices de lo que queda por tocar no se mueven.
    for tag, i1, i2, j1, j2 in reversed(matcher.get_opcodes()):
        if tag == "equal":
            continue
        for entry in list(old.entries[i1:i2]):
            old.remove_entry(entry)
        for offset, (value, quoted) in enumerate(texts[j1:j2]):
            old.insert_entry(i1 + offset, Entry(None, None, Scalar(value, quoted)))
    return old


def _number(value) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"se esperaba un número, no {type(value).__name__}")
    return value


@dataclass(frozen=True)
class Color(ValueType):
    """``{ r g b }``; ``scale=1.0`` en ``religion.txt``. Se lee como tupla de tres números (enteros con
    ``scale=255``) y se escribe editando el bloque en su sitio."""

    scale: float = 255
    widget: str = "color"

    def read(self, node: Scalar | Block) -> tuple:
        values = _loose_values(node, "color")
        if len(values) != 3:
            raise ValueError("color: se esperaban tres componentes")
        if self.scale == 255:
            return tuple(value.as_int() for value in values)
        return tuple(value.as_float() for value in values)

    def write(self, value: object, old: Scalar | Block | None) -> object:
        if not isinstance(value, (tuple, list)) or len(value) != 3:
            raise ValueError("color: se esperaban tres componentes")
        parts = [_number(part) for part in value]
        if self.scale == 255:
            if any(not isinstance(part, int) or not 0 <= part <= 255 for part in parts):
                raise ValueError("color: cada componente es un entero de 0 a 255")
            texts = [(str(part), False) for part in parts]
        else:
            if any(not 0 <= part <= self.scale for part in parts):
                raise ValueError(f"color: cada componente va de 0 a {self.scale}")
            texts = [(format_float(float(part)), False) for part in parts]
        if isinstance(old, Block):
            try:
                _loose_values(old, "color")
            except ValueError:
                pass
            else:
                return _edit_loose_block(old, texts)
        block = Block()
        for text_value, quoted in texts:
            block.append_value(Scalar(text_value, quoted))
        return block

    def example(self, ctx: CheckContext) -> tuple:
        return (10, 20, 30) if self.scale == 255 else (0.1, 0.2, 0.3)

    def describe(self, lang: str = "en") -> str:
        return text("schema.type.color", lang, scale=format_float(float(self.scale)).removesuffix(".0"))


@dataclass(frozen=True)
class ListOf(ValueType):
    """Lista de valores sueltos: ``{ 1 2 3 }`` o ``{ "a" "b" }`` (``region.txt``, nombres de las culturas).

    Escribir edita el bloque en su sitio: los valores que siguen conservan su texto y su posición (I3).
    ``unique`` rechaza repetidos al escribir.
    """

    item: ValueType
    unique: bool = False
    widget: str = "list"

    def read(self, node: Scalar | Block) -> list:
        return [self.item.read(value) for value in _loose_values(node, "lista")]

    def write(self, value: object, old: Scalar | Block | None) -> object:
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"se esperaba una lista, no {type(value).__name__}")
        if self.unique and len(set(map(str, value))) != len(value):
            raise ValueError("la lista no admite valores repetidos")
        texts = []
        old_items = {}
        if isinstance(old, Block):
            try:
                old_items = {item.text: item.quoted for item in _loose_values(old, "lista")}
            except ValueError:
                old = None
        for item in value:
            from ..clausewitz.nodes import needs_quotes

            written = self.item.write(item, None)
            text_value = written.text if isinstance(written, Scalar) else str(written)
            # Un valor que ya estaba conserva sus comillas (``"Ahmad"`` frente a ``Ahmad``); uno nuevo con
            # espacios va entre comillas (``"von Alten"``).
            default_quoted = (written.quoted if isinstance(written, Scalar) else False) or needs_quotes(text_value)
            scalar = Scalar(text_value, default_quoted)
            quoted = old_items.get(scalar.text, scalar.quoted)
            texts.append((scalar.text, quoted))
        if isinstance(old, Block):
            return _edit_loose_block(old, texts)
        block = Block()
        for text_value, quoted in texts:
            block.append_value(Scalar(text_value, quoted))
        return block

    def example(self, ctx: CheckContext) -> list:
        return [self.item.example(ctx)]

    def describe(self, lang: str = "en") -> str:
        return text("schema.type.list", lang, item=self.item.describe(lang))


@dataclass(frozen=True)
class Path(ValueType):
    """Ruta a otro archivo (``oob = "ARG_oob.txt"``, relativa a ``base``); valida el sufijo."""

    base: str
    suffixes: tuple[str, ...] = (".txt",)
    widget: str = "path"

    def read(self, node: Scalar | Block) -> str:
        value = _scalar(node, "ruta").text
        if self.suffixes and not value.lower().endswith(tuple(s.lower() for s in self.suffixes)):
            raise ValueError(f"{value!r}: se esperaba {', '.join(self.suffixes)}")
        return value

    def write(self, value: object, old: Scalar | Block | None) -> object:
        if not isinstance(value, str):
            raise ValueError(f"se esperaba una ruta, no {type(value).__name__}")
        if self.suffixes and not value.lower().endswith(tuple(s.lower() for s in self.suffixes)):
            raise ValueError(f"{value!r}: se esperaba {', '.join(self.suffixes)}")
        return Scalar(value, True if old is None or not isinstance(old, Scalar) else old.quoted)

    def example(self, ctx: CheckContext) -> str:
        return f"example{self.suffixes[0] if self.suffixes else ''}"

    def describe(self, lang: str = "en") -> str:
        return text("schema.type.path", lang, base=self.base, suffixes=", ".join(self.suffixes))


@dataclass(frozen=True)
class LocKey(ValueType):
    """El VALOR es una clave de localización (``title = "EVTNAME16000"``).

    ``suggest`` es una plantilla de clave sugerida para el selector (``EVTNAME{id}``). Se conservan las
    comillas del valor anterior; uno nuevo va entre comillas, como en ``bookmarks.txt``.
    """

    suggest: str | None = None
    widget: str = "lockey"

    def read(self, node: Scalar | Block) -> str:
        return _scalar(node, "clave de texto").text

    def write(self, value: object, old: Scalar | Block | None) -> object:
        if not isinstance(value, str) or not value or any(ch in value for ch in ' ;"\t\r\n'):
            raise ValueError(f"{value!r} no es una clave de texto")
        return Scalar(value, old.quoted if isinstance(old, Scalar) else True)

    def example(self, ctx: CheckContext) -> str:
        return "EXAMPLE_KEY"

    def describe(self, lang: str = "en") -> str:
        return text("schema.type.lockey", lang)


@dataclass(frozen=True)
class SpriteFrame(ValueType):
    """Índice de fotograma de un sprite (``sprite_index`` → ``GFX_diplo_wargoal_icons``), de 1 en adelante."""

    sprite: str
    widget: str = "sprite"

    def read(self, node: Scalar | Block) -> int:
        value = _scalar(node, "fotograma").as_int()
        if value < 0:
            raise ValueError("el fotograma no puede ser negativo")
        return value

    def write(self, value: object, old: Scalar | Block | None) -> object:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("el fotograma es un entero de 0 en adelante")
        return value

    def frames(self, ctx: CheckContext) -> int | None:
        """Fotogramas del sprite según el índice (``noOfFrames``); None si no se sabe."""
        if ctx is None or ctx.index is None:
            return None
        frames = ctx.index.attrs("sprite", self.sprite, "frames")
        return frames if isinstance(frames, int) else None

    def example(self, ctx: CheckContext) -> int:
        return 1

    def describe(self, lang: str = "en") -> str:
        return text("schema.type.sprite", lang, sprite=self.sprite)


@dataclass(frozen=True)
class Picture(ValueType):
    """``picture = X`` → ``gfx/pictures/<folder>/X.(tga|dds)``; ``default``, plantilla (H21)."""

    folder: str
    default: str = "{id}"
    widget: str = "picture"

    def read(self, node: Scalar | Block) -> str:
        return _scalar(node, "imagen").text

    def write(self, value: object, old: Scalar | Block | None) -> object:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{value!r} no es un nombre de imagen")
        return Scalar(value, old.quoted if isinstance(old, Scalar) else False)

    def example(self, ctx: CheckContext) -> str:
        return "example"

    def describe(self, lang: str = "en") -> str:
        return text("schema.type.picture", lang, folder=self.folder)


_SIMPLE_SPECS = {"int": Int, "float": Float, "bool": Bool, "date": Date, "word": Word, "text": Text,
                 "lockey": LocKey}


def from_spec(spec: dict) -> ValueType:
    """Tipo desde JSON (``{"type": "ref", "kind": "tag"}``): el catálogo de guion usa los mismos.

    Mismas claves que los parámetros de las dataclasses de arriba (``{"type": "enum", "values": [...]}``,
    ``{"type": "list", "item": {...}}``). Un tipo desconocido o un parámetro de más da ``ValueError``.
    """
    if not isinstance(spec, dict) or "type" not in spec:
        raise ValueError(f"especificación de tipo sin «type»: {spec!r}")
    params = {key: value for key, value in spec.items() if key != "type"}
    kind = spec["type"]
    try:
        if kind in _SIMPLE_SPECS:
            return _SIMPLE_SPECS[kind](**params)
        if kind == "enum":
            return Enum(*params.pop("values"), **params)
        if kind == "ref":
            return Ref(params.pop("kind"), **params)
        if kind == "color":
            return Color(**params)
        if kind == "list":
            item = from_spec(params.pop("item"))
            return ListOf(item, **params)
        if kind == "path":
            return Path(params.pop("base"), tuple(params.pop("suffixes", (".txt",))), **params)
        if kind == "sprite":
            return SpriteFrame(params.pop("sprite"), **params)
        if kind == "picture":
            return Picture(params.pop("folder"), **params)
    except (TypeError, KeyError) as exc:
        raise ValueError(f"especificación de tipo inválida: {spec!r} ({exc})") from None
    raise ValueError(f"tipo desconocido: {kind!r}")
