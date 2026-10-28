"""Selectores básicos de la iteración 4 (wizard §13.7).

``SymbolPicker`` (un símbolo del índice, con búsqueda por id y por nombre), ``DateEdit`` (fecha del juego, con
las fechas de inicio a mano), ``ColorField`` (color RGB con aviso de colores parecidos), ``GoodsAmountsField``
(bienes y cantidades: costes de las unidades), ``NameListEditor`` (listas de nombres: pegar, quitar
repetidos y comprobar cp1252) y ``SpriteFramePicker`` (un fotograma de un sprite).

Todos dan la misma API mínima: ``value()``, ``set_value(valor)``, la señal ``value_committed(object)`` (el
valor ya confirmado: al perder el foco, al pulsar Intro o al elegir) y ``retranslate()``. ``None`` es «sin
valor». No tocan el ``Workspace``: lo hace el formulario (``ui/forms``) dentro de una transacción.
"""

from __future__ import annotations

from .fields import (
    ColorField,
    DateEdit,
    GoodsAmountsField,
    NameListEditor,
    SpriteFramePicker,
    SymbolPicker,
    similar_colors,
)

__all__ = ["ColorField", "DateEdit", "GoodsAmountsField", "NameListEditor", "SpriteFramePicker", "SymbolPicker",
           "similar_colors"]
