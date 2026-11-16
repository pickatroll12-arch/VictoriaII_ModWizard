"""Climas (``map/climate.txt``, wizard §16.5, §22, H7). Contrato de la iteración 5.

Cada clima tiene **dos entradas con la misma clave**: una con sus modificadores y otra con la lista de
provincias (``PairedKeys``; vanilla trae primero las 4 de modificadores y luego las 4 listas). El registro es el
bloque de modificadores (catálogo abierto); la lista se edita con
``core.map.groups.ProvinceGroups(layout="paired")``. Un nombre con una sola entrada o con más de una lista da
``climate_layout``. Nace con ``editable=False``; su página es la sección «Continentes y climas».
"""

from __future__ import annotations

from ..schema import DynamicKeys, EntitySchema, Float, LocSpec, PairedKeys, Section
from ..schema.fields import OPEN_CATALOG

CLIMATE = EntitySchema(
    kind="climate",
    layout=PairedKeys("map/climate.txt"),
    provides="climate",
    fields=(Section("effects", (DynamicKeys("effects", OPEN_CATALOG, Float(), widget="table"),)),),
    loc=(LocSpec("{id}", "regions", required=False),),
    unknown="keep",
    hall="map", section="climates", order=6, icon="climate",
    editable=False,
)

SCHEMAS = (CLIMATE,)
