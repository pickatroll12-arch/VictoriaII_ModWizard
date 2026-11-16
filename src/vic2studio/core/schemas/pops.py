"""Bloques de POPs (``history/pops/<fecha>/<Zona>.txt``, wizard §16.4, §22). Contrato de la iteración 5.

Cada archivo trae un bloque ``<id de provincia> = { <tipo> = { culture religion size … } … }`` por provincia
(``KeyedAcross``, decisión 1 del informe). El registro es el bloque de una provincia en una carpeta de fecha y
su id es ``"<carpeta>:<provincia>"`` (el nombre del símbolo ``pop_block``); la aparición repetida de una
provincia en un archivo lleva ``#n``. Vanilla: 2 carpetas de fecha con 179 archivos cada una, sin subcarpetas;
2 703 y 2 704 bloques (una provincia repetida) y ninguna provincia en dos archivos de la misma fecha.

Dentro del bloque, cada entrada es un POP: su clave es un **tipo de POP** (``poptypes/*.txt``) y puede repetirse
(en vanilla el mismo tipo se repite dentro de una provincia en 7 713 y 8 123 casos). Son hijos sin clave fija
(``Children(POP)``): ``POP`` declara sus claves para la referencia y la validación, pero no se registra (no tiene
lista propia). La edición va por ``core.domain.pops.ProvincePops``, que distingue las repeticiones por posición.
Nace con ``editable=False`` (la cadena A lo cambia al implementar la disposición); su página es la ficha de la
provincia en «Mundo».
"""

from __future__ import annotations

from ..schema import Children, EntitySchema, Field, Float, Int, KeyedAcross, Ref, Section

GLOB = "history/pops/*/*.txt"

POP = EntitySchema(
    kind="pop",
    layout=KeyedAcross(GLOB),
    fields=(
        Section("pop", (
            Field("culture", Ref("culture"), required=True),
            Field("religion", Ref("religion"), required=True),
            Field("size", Int(1), required=True),
            Field("militancy", Float(0, 10), advanced=True),
            Field("rebel_type", Ref("rebel_type"), advanced=True),
        )),
    ),
    unknown="keep", editable=False, icon="map",
)

POPS = EntitySchema(
    kind="pops",
    layout=KeyedAcross(GLOB),
    provides="pop_block",
    fields=(Children(POP),),
    unknown="keep",
    hall="map", section="world", order=2, icon="map",
    editable=False,
)

SCHEMAS = (POPS,)
