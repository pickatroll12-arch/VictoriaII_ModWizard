"""Fronteras del mapa: máscaras de borde por provincia, estado y país (wizard §16.1, §16.3). Contrato.

Una frontera es un píxel cuyo vecino de la derecha o de abajo (en ``y`` creciente) pertenece a otro grupo. El
grupo de un píxel es su id (frontera de provincia) o ``group_lut[id]`` (estado, país…): así las tres capas salen
del mismo ráster con una LUT distinta, sin recorrer píxeles en Python. La vista las pinta encima de la imagen del
modo (``ui/map/layers``) ya volteadas con ``raster.to_display_row``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .facts import ProvinceFacts

LEVEL_PROVINCE = "province"
LEVEL_STATE = "state"                # región de region.txt (las de mar, por region_sea.txt)
LEVEL_COUNTRY = "country"            # dueño en la fecha de trabajo
LEVELS = (LEVEL_PROVINCE, LEVEL_STATE, LEVEL_COUNTRY)


def border_mask(ids: np.ndarray, group_lut: np.ndarray | None = None, *, wrap_x: bool = True) -> np.ndarray:
    """Máscara ``(alto, ancho)`` ``bool``: True donde el píxel es frontera de su grupo.

    ``group_lut`` es ``(N+1,)`` con el grupo de cada id (None = el propio id). Con ``wrap_x`` la última columna se
    compara con la primera. Los píxeles sin provincia (id 0) forman su propio grupo."""
    raise NotImplementedError


def level_lut(facts: ProvinceFacts, level: str) -> np.ndarray | None:
    """La LUT de grupo de un nivel: None para ``LEVEL_PROVINCE``, ``facts.region`` para ``LEVEL_STATE`` y
    ``facts.owner`` para ``LEVEL_COUNTRY`` (el mar y lo que no tiene dueño comparten el grupo 0, así que no se
    dibujan fronteras de país dentro del mar). ``ValueError`` con otro nivel."""
    raise NotImplementedError


def border_rgba(mask: np.ndarray, color: int) -> np.ndarray:
    """Imagen ``(alto, ancho)`` ``uint32`` ``0xAARRGGBB`` premultiplicado: ``color`` donde ``mask`` y 0 (transparente)
    en el resto. Misma orientación que ``mask`` (la vista la voltea)."""
    raise NotImplementedError
