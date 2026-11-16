"""Registro de países (``common/countries.txt``, wizard §14.2, H11). Iteración 6.

``TAG = "countries/<Archivo>.txt"`` por país; ``dynamic_tags = yes`` marca dónde empiezan los dominios dinámicos
(D01–D50 en vanilla). Un TAG nuevo va **antes** de ``dynamic_tags`` y de los comentarios que lo preceden: detrás,
el juego lo tomaría por un dominio dinámico. Las entradas son escalares: el índice las lee (símbolos ``tag``) y la
línea nueva la pone el asistente «Nuevo país» (``core.domain.country``) o el arreglo ``register_tag``.
"""

from __future__ import annotations

from ..schema import EntitySchema, IdRule, LocSpec, Registry

COUNTRY_REGISTRY = EntitySchema(
    kind="country_registry",
    layout=Registry("common/countries.txt"),
    provides="tag",
    ident_rule=IdRule.TAG,
    fields=(),
    loc=(LocSpec("{id}", "countries"), LocSpec("{id}_ADJ", "countries")),
    unknown="keep", editable=False, icon="countries",
)

SCHEMAS = (COUNTRY_REGISTRY,)
