"""Campos y secciones del motor de esquemas (wizard §10.2).

Un campo describe una clave del CST (``Field``), un bloque anidado (``Group``),
un catálogo de claves dinámicas sacadas del índice (``DynamicKeys``, H19), una
lista de valores sueltos (``Values``), hijos sin clave fija (``Children``,
H18), guion (``Script``) o código conservado tal cual (``Opaque``). Las
``Section`` agrupan campos para el formulario generado. Todo son dataclasses
congeladas sin E/S; la lógica llega en la fase 2.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

from .types import ValueType

if TYPE_CHECKING:
    from .entity import EntitySchema

# El centinela «sin valor»: distingue «el campo no está» de «el campo vale None»
# (``Field.default``, ``Record.get`` sin el campo).
MISSING = object()

# Centinela para ``Children.match``: todo bloque que el esquema no haya reclamado.
REMAINING_BLOCKS = object()

# ``DynamicKeys.key_kind`` de un catálogo abierto: cualquier clave que no sea un campo fijo.
OPEN_CATALOG = "*"


class Condition:
    """Condición de visibilidad de un campo (``Field.visible_if``).

    ``evaluate(record) -> bool`` decide si el campo se muestra (fase 2).
    """

    def evaluate(self, record) -> bool:  # noqa: F821 - Record de .record
        raise NotImplementedError


@dataclass(frozen=True)
class When(Condition):
    """El campo se muestra cuando ``field`` vale ``value`` (``When("election", True)``)."""

    field: str
    value: object

    def evaluate(self, record) -> bool:  # noqa: F821
        return record.get(self.field, None) == self.value


@dataclass(frozen=True)
class SetOps:
    """Historia acumulativa: el valor se reparte entre ``add_<clave>`` y ``remove_<clave>``
    (``SetOps(add="add_core", remove="remove_core")``)."""

    add: str
    remove: str


class Scope:
    """Ámbito de un bloque de guion (§10.2): ``Script.scope``."""

    COUNTRY = "country"
    PROVINCE = "province"
    POP = "pop"
    WAR = "war"


# Tipo de guion: condiciones o efectos (los edita core.script, iteración 7).
ScriptKind = str


@dataclass(frozen=True)
class Field:
    """Una clave del CST: ``key`` con su ``type`` y su política de presencia.

    ``repeat``: clave repetible (``add_core``, ``culture``, ``regiment``). ``accumulate``: en
    historia, el valor se reparte entre ``add_/remove_``. ``default``: lo que asume el juego si
    falta; se muestra en gris y NO se escribe. ``aliases``: claves equivalentes (``.gui``:
    ``Orientation``/``orientation``, H23); ``ignore_case`` hace la búsqueda sin mayúsculas.
    ``visible_if`` oculta el campo según otros valores. ``advanced`` lo esconde en modo sencillo
    (P4). ``label``/``help``: claves de texto; por defecto ``schema.<kind>.<key>`` y su ``.help``.
    """

    key: str
    type: ValueType
    required: bool = False
    default: object = MISSING
    repeat: bool = False
    accumulate: SetOps | None = None
    ignore_case: bool = False
    aliases: tuple[str, ...] = ()
    visible_if: Condition | None = None
    advanced: bool = False
    ui: str | None = None                    # "slider", "chips", "map_pick", "matrix"
    label: str = ""
    help: str = ""


@dataclass(frozen=True)
class DynamicKeys:
    """Claves sacadas del índice (H19): ``upper_house = { fascist = 0 liberal = 20 … }``.

    ``name`` da el nombre para ``Record.dynamic``; ``key_kind``, el tipo de símbolo del índice
    (``"technology"``, ``"invention"``, ``"issue_group"``, ``"ideology"``, ``"tag"``,
    ``"government"``, ``"goods"``…). ``OPEN_CATALOG`` (``"*"``) admite cualquier clave que no sea
    un campo fijo: los efectos de un modificador (``event_modifiers.txt``), que el índice no cataloga. ``key_filter`` descarta claves (solo reformas políticas y
    sociales, solo unidades navales…). ``value`` puede ser un tipo o una función
    ``Callable[[str], ValueType]`` que lo elige según la clave. ``only_true`` escribe solo las
    claves ``yes``/``1`` y borra en vez de escribir ``= no`` (§10.10: ideologías).
    """

    name: str
    key_kind: str
    value: ValueType | Callable[[str], ValueType]
    key_filter: Callable | None = None
    widget: str = "auto"                     # checklist | grid | table | sliders
    group_by: str | None = None              # tecnologías por "folder" y "area"
    only_true: bool = False


@dataclass(frozen=True)
class Group:
    """Bloque anidado con subcampos (``party``, ``war_goal``, ``position``).

    ``repeat``: puede haber varios bloques iguales (partidos). ``id_field``: la clave que
    identifica cada repetición (party → ``name``). ``dynamic``: las claves del bloque salen del
    índice (``upper_house``). ``widget="table"`` si todo son escalares; si no, ``"cards"``.
    """

    key: str
    fields: tuple[FieldLike, ...]
    repeat: bool = False
    required: bool = False
    id_field: str | None = None
    widget: str = "auto"
    dynamic: DynamicKeys | None = None


@dataclass(frozen=True)
class Values:
    """El bloque ES una lista (``region.txt``: ``USA_1 = { 1 2 3 }``)."""

    item: ValueType


@dataclass(frozen=True)
class Children:
    """Bloques hijos sin clave fija (culturas dentro de su grupo, H18).

    ``match`` devuelve las entradas que son hijos; por defecto ``REMAINING_BLOCKS``: todo bloque
    que el esquema no haya reclamado.
    """

    schema: EntitySchema
    match: Callable = REMAINING_BLOCKS


@dataclass(frozen=True)
class Script:
    """Condiciones y efectos: los edita ``core.script`` (iteración 7).

    ``key`` da la clave del bloque; ``REST`` (una cadena) indica «el resto del bloque»
    (``modifier = { factor = 2 <condiciones> }``). ``kind`` es ``ScriptKind``
    (``"condition"``/``"effect"``).
    """

    key: str
    kind: ScriptKind
    scope: str = Scope.COUNTRY
    repeat: bool = False
    required: bool = False


@dataclass(frozen=True)
class Opaque:
    """Clave que se conserva y se edita como código (I6)."""

    key: str


@dataclass(frozen=True)
class Section:
    """Tarjeta del formulario: un grupo de campos con su nombre (texto ``schema.section.<name>``)."""

    name: str
    items: tuple[FieldLike, ...]
    collapsed: bool = False


FieldLike = Union[Field, Group, DynamicKeys, Values, Children, Script, Opaque]

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])([A-Z])")


def field_text_key(kind: str, key: str) -> str:
    """Clave del catálogo de un campo: ``schema.<kind>.field.<clave>`` con la clave técnica en
    minúsculas con guiones (``flagType`` → ``flag_type``): el patrón de claves de i18n no
    admite mayúsculas (test_i18n). La etiqueta visible lleva el nombre técnico aparte."""
    snake = _CAMEL_RE.sub(r"_\1", key).lower()
    return f"schema.{kind}.field.{snake}"


def field(key: str, type: ValueType, **kwargs) -> Field:
    """Atajo legible para declarar un ``Field`` (``field("election", Bool(), required=True)``)."""
    return Field(key, type, **kwargs)
