"""Política de colocación (wizard §10.7).

Al añadir una entrada, en este orden:

1. **Repetible con hermanos**: justo tras el último de la misma clave
   (``add_core = DEN`` tras ``add_core = GER``). La aplica ``Record.add``.
2. **Orden del esquema**: tras la última entrada existente cuyo campo va antes
   en el esquema; si no hay, antes de la primera cuyo campo va después
   (``insertion_index``).
3. **Bloques fechados**: una entrada sin fecha nunca se coloca detrás del
   primer bloque fechado (``first_dated`` recorta el tope de ``insertion_index``).
4. **Claves dinámicas**: tras la última del mismo catálogo; si no hay, al final
   de su sección (``dynamic_insert_index``).
5. **Registro**: ``Registry(before=K)`` inserta en el índice de ``K``
   (``registry_index``); la entrada nueva se escribe delante de la trivia
   (comentarios) que precede a ``K``.
6. **Documento nuevo**: orden completo del esquema con ``format_canonical``, en
   cp1252 y con el salto de línea de los demás archivos del mod (CRLF por
   defecto).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..clausewitz.nodes import Block, ClausewitzDate


@dataclass(frozen=True)
class SchemaOrder:
    """Orden canónico de las claves de un esquema (todas las secciones, en orden)."""

    keys: tuple[str, ...]

    def position(self, key: str) -> int | None:
        return self.keys.index(key) if key in self.keys else None


def first_dated_index(block: Block) -> int | None:
    """Índice de la primera entrada cuyo valor es un bloque fechado (``1861.1.1 = { … }``);
    None si no hay. Nada sin fecha va detrás (regla 3)."""
    for index, entry in enumerate(block.entries):
        if entry.key is not None and entry.key.is_date():
            return index
    return None


def insertion_index(block: Block, *, key: str, order: SchemaOrder,
                    first_dated: int | None = None, dynamic_after: int | None = None) -> int:
    """Índice de ``block.entries`` donde insertar la clave ``key`` (reglas 2–4 de §10.7).

    - ``first_dated``: índice del primer bloque fechado; la entrada nueva nunca va detrás
      (regla 3). None si no hay bloques fechados.
    - ``dynamic_after``: índice de la última clave del mismo catálogo dinámico (regla 4);
      None si la clave no es dinámica o no hay ninguna del catálogo.

    Regla 2: tras la última entrada existente cuyo campo va antes que ``key`` en ``order``;
    si no hay ninguna, antes de la primera cuyo campo va después. Las claves que no están en
    el orden (desconocidas o dinámicas) no cuentan como ancla.
    """
    limit = len(block.entries)
    if first_dated is not None and first_dated < limit:
        limit = first_dated
    position = order.position(key)
    if position is None:
        # Clave fuera del orden del esquema (dinámica o desconocida): tras el catálogo si se da.
        if dynamic_after is not None and dynamic_after + 1 < limit:
            return dynamic_after + 1
        return limit
    last_before = -1
    first_after = limit
    for index, entry in enumerate(block.entries[:limit]):
        if entry.key is None:
            continue
        other = order.position(entry.key.text)
        if other is None:
            continue
        if other < position:
            last_before = index
        elif other > position and first_after == limit:
            first_after = index
    return last_before + 1 if last_before >= 0 else first_after


def dynamic_insert_index(block: Block, *, fixed: frozenset[str]) -> int:
    """Índice de la clave dinámica nueva: tras la última clave del mismo catálogo (las que no
    son campos fijos del esquema); si no hay ninguna, antes del primer campo fijo del bloque
    (el final de su sección), o al final si el bloque no tiene campos fijos (regla 4)."""
    last_dynamic = -1
    first_fixed = len(block.entries)
    for index, entry in enumerate(block.entries):
        if entry.key is None:
            continue
        if entry.key.text in fixed:
            if first_fixed == len(block.entries):
                first_fixed = index
        else:
            last_dynamic = index
    if last_dynamic >= 0:
        return last_dynamic + 1
    return first_fixed


def registry_index(block: Block, *, before: str) -> int:
    """Índice de inserción de un registro: justo antes de la clave ``before`` (regla 5).

    Si ``before`` no está, al final del documento.
    """
    for index, entry in enumerate(block.entries):
        if entry.key is not None and entry.key.text.lower() == before.lower():
            return index
    return len(block.entries)
