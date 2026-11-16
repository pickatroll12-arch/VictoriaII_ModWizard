"""Taller de mapas (wizard §18): generar o importar un mapa de Victoria II y exportarlo como un mapa normal del mod.

Los dos caminos, generar (``pipeline``) e importar (``imports``), llenan el mismo ``ForgeWorld``. Desde ahí
comparten la vista previa, las ediciones (``edits``), la validación (``validate``), la auditoría (``audit``) y la
exportación en una sola transacción (``export``). Todo es numpy y Pillow, sin Qt (I1) y sin escribir en disco: los
bytes salen en memoria y los escribe el diario al guardar.

Los módulos que portan algoritmos de Azgaar's Fantasy Map Generator (MIT, © Max Haniyeu) lo dicen en su cabecera;
el texto de la licencia está en ``THIRD_PARTY_NOTICES.md``.
"""
