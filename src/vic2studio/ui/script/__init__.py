"""Interfaz del guion: constructores, buscador, MTTH, opciones, vistas previas e imágenes (wizard §14.5, §14.7).

- ``trigger_builder``: ``ScriptTreeModel`` (el modelo Qt de un ``ScriptTree``), ``ScriptBinding`` (de dónde
  sale el árbol) y ``TriggerBuilder``, el constructor de condiciones TODAS/ALGUNA/NINGUNA.
- ``effect_builder``: ``EffectBuilder``, el mismo modelo con ámbitos de efecto.
- ``catalog_picker``: ``CatalogPicker``, el buscador por categorías de «+ Condición», «+ Efecto» y «+ Ámbito».
- ``mtth_editor``: ``MtthEditor`` (base, modificadores y tiempo efectivo; también ``ai_chance`` y
  ``ai_will_do``).
- ``option_cards``: ``OptionCards``, las tarjetas de las opciones de un evento.
- ``event_preview`` y ``decision_preview``: vistas previas procedurales (el renderizador ``.gui`` real llega
  en la iteración 8).
- ``picture_picker``: ``PicturePicker`` y la conversión de una imagen propia al formato del juego.
- ``phrase_view``: ``PhraseView``, la frase legible bajo cada constructor.

Convenciones comunes (las de ``ui/pickers`` y ``ui/forms``): ningún widget toca el ``Workspace`` fuera de
``Session.edit(etiqueta, merge_key=…)``; tras cada cambio de documentos (``Session.documentsChanged``:
edición, deshacer, rehacer, recarga) se vuelve a pedir el árbol con ``Record.script`` y se recupera la
selección por ``ScriptNode.path``; todos tienen ``retranslate()`` y ``set_read_only(bool)``; los textos son
claves ``script_ui.*`` (``i18n/<idioma>/script.json``) y ``events.*``/``decisions.*``
(``i18n/<idioma>/events.json``).

Este ``__init__`` no importa sus submódulos: cada uno se importa por su nombre.
"""
