"""Guion: catálogo, árbol sin pérdidas, frases, MTTH e ids de evento (wizard §12, iteración 7).

- ``scopes``: ``ScriptKind`` (condiciones o efectos), ``Scope`` (país, provincia, estado, POP) y los
  cambios de ámbito. Es una hoja: no importa nada de ``core.schema``.
- ``catalog``: ``Role``, ``ScriptKeyDef`` y ``ScriptCatalog`` sobre ``data/{triggers,effects,scopes}.json``
  (datos propios: solo nombres de claves, tipos y frases ES/EN).
- ``tree``: ``ScriptNode`` y ``ScriptTree``, una vista sobre el CST (I3) con nodos crudos.
- ``phrases``: la frase legible ES/EN con los nombres localizados del índice.
- ``mtth``: el tiempo efectivo y el modelo de modificadores de ``mean_time_to_happen``, ``ai_chance`` y
  ``ai_will_do``.
- ``idalloc``: ``EventIdAllocator`` (rango del proyecto, D15).
- ``textonly``: qué pasa con un archivo con errores de sintaxis (D17, criterio 4 de la iteración 7).

Este ``__init__`` no importa sus submódulos a propósito: ``core.schema.fields`` importa ``scopes`` (el tipo
``Script``), y ``catalog``, ``tree`` y ``mtth`` importan ``core.schema``. Un import ansioso aquí cerraría el
ciclo. Se importa cada módulo por su nombre: ``from vic2studio.core.script.catalog import ScriptCatalog``.
"""
