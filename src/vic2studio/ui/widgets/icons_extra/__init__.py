"""Iconos nuevos de las salas, cada archivo de un dueño (wizard §13.10, §20).

Cada módulo ``icons_extra/<área>.py`` registra los suyos con el mismo decorador
``icons._icon``. ``load()`` los importa todos por descubrimiento: la ventana
principal lo llama antes de construir las salas.
"""

from __future__ import annotations

import importlib
import pkgutil

_loaded = False


def load() -> None:
    """Importa (una sola vez) todos los módulos de iconos de este paquete."""
    global _loaded
    if _loaded:
        return
    for info in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{info.name}")
    _loaded = True
