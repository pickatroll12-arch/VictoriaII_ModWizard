"""Familia «map»: coherencia del mapa (wizard §16.6). Contrato de la iteración 5: aún no registra ninguna regla.

La lógica vive en ``core.map.coherence.check_map`` y la tabla de códigos y gravedades, en
``core.map.coherence.CODES``. Este módulo es donde la cadena A registra con ``@rule`` los códigos **nuevos**
(los que ya existían siguen en ``rules/provinces.py`` y en los avisos de ``definition.csv``):

    bmp_size_mismatch, definition_bad_number, province_without_pixels, province_fragmented,
    max_provinces_too_small, sea_start_unknown, sea_start_duplicate, region_empty, region_not_contiguous,
    climate_layout, positions_missing, missing_history, province_file_name, missing_prov_localisation,
    adjacency_unknown_province, adjacency_bad_type, adjacency_through_not_sea, terrain_sea_mismatch

Forma prevista: una regla por código (o una por grupo que devuelve varios códigos, como ``rules/provinces``)
que llama a ``check_map(ctx, codes={…})`` y devuelve sus problemas; los códigos de ``RASTER_CODES`` comparten
una sola carga del ráster por validación. Cada código registrado necesita ``issue.<código>``,
``explain.title.<código>`` y ``explain.outcome.<código>`` en ES y EN (``core/map/texts`` o
``core/validate/texts``) y un caso en ``tests/test_validate_rules.py``; por eso no se registran en el commit de
contrato, donde no hay lógica que probar. ``sea_start_duplicate`` entra en la línea base del juego (I11,
criterio 8).
"""

from __future__ import annotations

FAMILY = "map"
