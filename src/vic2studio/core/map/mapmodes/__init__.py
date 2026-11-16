"""Modos de mapa del núcleo, uno o varios por módulo (wizard §16.2, §20: sin listas centrales).

Cada módulo de este paquete registra sus modos con ``core.map.modes.register_mode`` al importarse;
``modes.discover_modes`` los importa todos con ``pkgutil``. Añadir un modo no toca ningún archivo compartido.
"""
