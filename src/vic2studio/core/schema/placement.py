"""Política de colocación (wizard §10.7).

Al añadir una entrada, en este orden:

1. **Repetible con hermanos**: justo tras el último de la misma clave
   (``add_core = DEN`` tras ``add_core = GER``).
2. **Orden del esquema**: tras la última entrada existente cuyo campo va antes
   en el esquema; si no hay, antes de la primera cuyo campo va después.
3. **Bloques fechados**: una entrada sin fecha nunca se coloca detrás del
   primer bloque fechado (``append`` dejaría ``fort = 2`` detrás de
   ``1861.1.1 = { … }``).
4. **Claves dinámicas**: tras la última del mismo catálogo; si no hay, al final
   de su sección.
5. **Registro**: ``Registry(before=K)`` inserta en el índice de ``K``
   (``Block.index_of``); la entrada nueva se escribe delante de la trivia
   (comentarios) que precede a ``K``.
6. **Documento nuevo**: orden completo del esquema con ``format_canonical``, en
   cp1252 y con el salto de línea de los demás archivos del mod (CRLF por
   defecto).

La función central es ``insertion_index``: el índice de ``block.entries`` donde
debe ir la entrada nueva de la clave ``key``. En esta fase es contrato; la
lógica llega en la fase 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..clausewitz.nodes import Block
    from .fields import FieldLike, Section


@dataclass(frozen=True)
class SchemaOrder:
    """Orden canónico de las claves de un esquema (todas las secciones, en orden)."""

    keys: tuple[str, ...]


def insertion_index(block: Block, *, key: str, order: SchemaOrder,
                    first_dated: int | None = None, dynamic_after: int | None = None) -> int:
    """Índice de ``block.entries`` donde insertar la clave ``key`` (reglas 1–4 de §10.7).

    ``first_dated``: índice del primer bloque fechado (nada sin fecha va detrás, regla 3).
    ``dynamic_after``: índice de la última clave del mismo catálogo dinámico (regla 4), None si
    no hay. La regla 1 (repetibles) la aplica quien llama con ``add``; aquí se resuelven 2–4.
    """
    raise NotImplementedError


def registry_index(block: Block, *, before: str) -> int:
    """Índice de inserción de un registro: justo antes de la clave ``before`` (regla 5)."""
    raise NotImplementedError
