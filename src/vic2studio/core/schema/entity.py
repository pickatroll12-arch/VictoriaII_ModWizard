"""Entidad: esquema, localización, variantes y vistas (wizard §10.3).

``EntitySchema`` declara una familia de entidades: dónde viven (``layout``),
qué campos tienen (``fields``), cómo se identifica cada registro (``ident``),
qué símbolo define en el índice (``provides``), sus claves de localización
(``loc``), sus validadores (``validators``) y sus compañeros (``companions``).
``Variant`` reparte campos según una clave (``unit``: ``type`` → land/naval) y
``View`` da secciones distintas sobre el mismo esquema (§10.3, el criterio de
las dos vistas de ``unit``). Todo son dataclasses congeladas sin E/S.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .fields import FieldLike, Section

if TYPE_CHECKING:
    from .companions import Companion
    from .layouts import FileLayout
    from .record import Record
    from .validate import RecordValidator


@dataclass(frozen=True)
class LocSpec:
    """Clave de localización que la entidad crea, renombra y borra con ella.

    ``template`` es la plantilla de la clave (``"{id}"``, ``"{id}_desc"``, ``"PROV{id}"``…);
    ``area``, el área de destino (``localisation/00_<P>_<area>.csv``, §2.7). ``shared``: la clave
    la comparten varias entidades (``NORMAL_<war_name>``, H17): no se renombra ni se borra con
    ninguna.

    ``field`` (iteración 7): ruta del campo ``LocKey`` del registro que **guarda** la clave
    (``("title",)``, ``("option", "name")``). Con ``field``, la clave efectiva es el valor de ese
    campo, una por cada repetición del grupo, y la plantilla solo sirve al crear: se escribe en el
    campo y se crea su fila. ``{letter}`` es A, B, C… según la posición de la repetición
    (``EVTOPT{letter}{id}``). Un valor que no es una clave (texto en prosa, con espacios) se respeta
    y no cuenta. En vanilla, 253 de 1 064 títulos, 272 descripciones y 352 de 1 655 nombres de opción
    no son la plantilla con el id de su propio evento (reutilizan la clave de otro): por eso manda el
    campo y no la plantilla, y al borrar un registro no se borra una clave que otro sigue usando
    (``index.refs_to``).
    """

    template: str
    area: str
    required: bool = True
    shared: bool = False
    field: tuple[str, ...] = ()


@dataclass(frozen=True)
class HistorySpec:
    """Política de historia fechada (§10.6). ``"state"``: un valor vigente por fecha (provincias,
    países); ``"log"``: cada bloque fechado es un suceso (guerras)."""

    mode: str = "state"


@dataclass(frozen=True)
class Variant:
    """Campos según el valor de una clave: ``unit`` → ``{"land": (…,), "naval": (…,)}`` (§10.3)."""

    field: str
    cases: Mapping[str, tuple[FieldLike, ...]]


@dataclass(frozen=True)
class View:
    """Una sección sobre un esquema: ``key`` la nombra (``"land"``, ``"naval"``),
    ``filter(record)`` decide qué registros entran y ``section`` es la sección de la interfaz."""

    key: str
    filter: Callable[[Record], bool]
    section: str


@dataclass(frozen=True)
class IdSpec:
    """De dónde sale el id de un registro (§10.3):

    - ``IdSpec.KEY``: de la clave de la entrada (gobiernos, CB);
    - ``IdSpec.FIELD("name")``: de un campo del bloque (bookmarks);
    - ``IdSpec.FILE("id")``: del nombre del archivo (``units/<id>.txt``, provincias);
    - ``IdSpec.COMPOSITE(("first", "second", "start_date"))``: de varias claves.
    """

    mode: str                                # "key" | "field" | "file" | "composite"
    value: object = None                     # nombre del campo, patrón del archivo o tupla de claves

    @classmethod
    def FIELD(cls, name: str) -> IdSpec:
        return cls("field", name)

    @classmethod
    def FILE(cls, pattern: str) -> IdSpec:
        return cls("file", pattern)

    @classmethod
    def COMPOSITE(cls, parts: tuple[str, ...]) -> IdSpec:
        return cls("composite", tuple(parts))


IdSpec.KEY = IdSpec("key")


@dataclass(frozen=True)
class IdRule:
    """Qué ids se admiten para una entidad nueva (§10.3, `core/rules/ids`).

    ``IdRule.WORD`` (palabra suelta), ``IdRule.TAG`` (tres letras),
    ``IdRule.SNAKE`` (minúsculas con guiones bajos) e
    ``IdRule.INT_RANGE("event")`` (entero en el rango que ``core/rules/ids`` da para esa familia).
    """

    mode: str                                # "word" | "tag" | "snake" | "int_range"
    value: str | None = None                 # familia del rango (INT_RANGE("event"))

    @classmethod
    def INT_RANGE(cls, family: str) -> IdRule:
        return cls("int_range", family)


IdRule.WORD = IdRule("word")
IdRule.TAG = IdRule("tag")
IdRule.SNAKE = IdRule("snake")


@dataclass(frozen=True)
class EntitySchema:
    """Declaración completa de una familia de entidades (§10.3).

    ``fields`` alterna ``Section`` y ``FieldLike`` sueltos; el orden es el orden canónico
    (colocación §10.7, documento nuevo §10.7.6). ``provides``: tipo de símbolo que define en el
    índice (debe coincidir con el ``KIND_*`` que ya extrae el extractor; no se duplican
    extractores). ``symbol_attrs(record)`` da los ``attrs`` del símbolo. ``unknown``: qué hacer
    con las claves no declaradas (``"keep_warn"``: se conservan, salen en «Otros campos» y
    avisan, I6). ``template(ident, index)``: valores iniciales de «Nuevo».
    """

    kind: str
    layout: FileLayout
    fields: tuple[FieldLike | Section, ...]
    ident: IdSpec = IdSpec.KEY
    ident_rule: IdRule = IdRule.WORD
    provides: str | None = None
    symbol_attrs: Callable[[Record], dict] | None = None
    history: HistorySpec | None = None
    variants: Variant | None = None
    views: tuple[View, ...] = ()
    loc: tuple[LocSpec, ...] = ()
    validators: tuple[RecordValidator, ...] = ()
    companions: tuple[Companion, ...] = ()
    template: Callable[[str, object], dict] | None = None
    unknown: str = "keep_warn"
    ignore_case: bool = False
    hall: str | None = None
    section: str | None = None
    order: int = 100
    icon: str = "file_text"
    preview: str | None = None               # "event", "decision", "unit_card", "flag"…
    editable: bool = True                    # False: solo se indexa (tecnologías, ideologías…)
