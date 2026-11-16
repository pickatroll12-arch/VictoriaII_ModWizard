"""Estrechos, pasos cerrados y canales (``map/adjacencies.csv``, wizard §16.6, §22). Contrato de la iteración 5.

Una fila por adyacencia especial: ``from;to;type;through;data;comment`` (``Table``). Vanilla: 117
líneas, 84 de datos (63 ``sea``, 18 ``impassable`` y 3 ``canal`` con dato 1–3), 26 comentarios (la cabecera es
uno) y 7 en blanco. ``sea`` une dos provincias de tierra a través de una de mar (``adjacency_through_not_sea``);
``impassable`` cierra el paso entre dos vecinas; ``canal`` abre uno con el edificio de canal del dato.

No es un bloque Clausewitz, así que ``Entities`` no sirve sus filas: se leen y se editan con
``core.map.adjacency.AdjacencyTable`` (sin pérdidas, con ``Workspace.restore_bytes``). El esquema existe para
que la referencia, la navegación (un problema ``adjacency_*`` abre «Estrechos») y los textos salgan del registro.
``editable=False`` para siempre: su página es la sección «Estrechos» de la sala Mapa.
"""

from __future__ import annotations

from ..map.adjacency import ADJACENCIES_REL, COLUMNS, TYPES
from ..schema import EntitySchema, Enum, Field, Int, Section, Table, Text

ADJACENCY = EntitySchema(
    kind="adjacency",
    layout=Table(str(ADJACENCIES_REL), COLUMNS),
    fields=(
        Section("row", (
            Field("from", Int(1), required=True, ui="map_pick"),
            Field("to", Int(1), required=True, ui="map_pick"),
            Field("type", Enum(*TYPES), required=True),
            Field("through", Int(0), ui="map_pick"),
            Field("data", Int(0)),
            Field("comment", Text(quoted=False)),
        )),
    ),
    unknown="keep",
    hall="map", section="straits", order=9, icon="anchor",
    editable=False,
)

SCHEMAS = (ADJACENCY,)
