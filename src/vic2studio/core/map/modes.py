"""Modos de mapa declarativos: una LUT de color por código y su leyenda (wizard §16.1, §16.2). Contrato.

Un ``MapMode`` no pinta: da ``lut(facts, index, param=…)``, un array ``(N+1,)`` ``uint32`` ``0xAARRGGBB`` con el
color de cada **provincia**, y el lienzo hace ``np.take(lut, ids)`` (cambio de modo ≤ 150 ms con vanilla). El
color de «sin provincia» (índice 0) y el del mar los decide el modo (``SEA_COLOR`` y ``VOID_COLOR`` por defecto).

Los modos se registran por descubrimiento: cada módulo de ``core/map/mapmodes/`` llama a ``register_mode`` y
``discover_modes`` los importa. La interfaz puede registrar los suyos igual (``Problemas`` necesita el informe de
validación e ``IDs`` dibuja números encima). Las claves de texto (``label`` y las de la leyenda) son de la
interfaz (``i18n/<idioma>/map.json``): el núcleo no lleva textos de modos.

Modos del núcleo en esta iteración (clave → color): ``political`` (el ``color`` del país dueño), ``rgo`` (el del
bien), ``infrastructure`` (degradado por ``railroad``), ``life_rating`` (degradado de 0 a 100), ``terrain``,
``regions``, ``continents``, ``climates`` (color estable por nombre: ``hash_color``), ``culture``, ``religion``,
``cores`` (los del TAG de ``param``) y ``population`` (escala logarítmica).
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .facts import ProvinceFacts

SEA_COLOR = 0xFF3A5F7D               # mar en los modos que no lo colorean
VOID_COLOR = 0xFF000000              # píxeles sin provincia
EMPTY_COLOR = 0xFF808080             # tierra sin dato (sin dueño, sin bien…)

# (facts, index, *, param=None) -> (N+1,) uint32 0xAARRGGBB
LutFn = Callable[..., np.ndarray]
# (facts, index, *, param=None) -> leyenda
LegendFn = Callable[..., "list[LegendItem]"]


@dataclass(frozen=True)
class LegendItem:
    """Una fila de la leyenda. El rótulo sale, por orden: de ``symbol`` (``(kind, name)`` del índice, que la
    interfaz muestra con su nombre localizado: un país, un bien), de ``text_key`` con ``args`` (clave de
    ``map.json``: «Sin dueño», «{low}–{high}») o de ``text`` tal cual (un número). ``count`` es cuántas
    provincias tienen ese color (None si no aplica)."""

    color: int
    symbol: tuple[str, str] | None = None
    text_key: str | None = None
    args: tuple[tuple[str, object], ...] = ()
    text: str = ""
    count: int | None = None


@dataclass(frozen=True)
class MapMode:
    """Un modo. ``label`` es su clave de texto (``map.mode.<key>``). ``needs`` dice de qué campos de
    ``ProvinceFacts`` depende su LUT (``("owner",)``): el lienzo solo la recalcula si la brocha tocó uno de ellos.
    ``param`` es el tipo de símbolo que hay que elegir antes (``"tag"`` en Núcleos; None si no hace falta).
    ``overlay`` nombra una capa extra de la interfaz (``"ids"``: el número de cada provincia en su punto de
    etiqueta)."""

    key: str
    label: str
    lut: LutFn
    legend: LegendFn
    order: int = 100
    needs: tuple[str, ...] = ()
    param: str | None = None
    overlay: str | None = None
    icon: str = "map"


MODES: dict[str, MapMode] = {}


def register_mode(mode: MapMode) -> MapMode:
    """Añade ``mode`` al registro; ``ValueError`` si su clave ya existe."""
    if mode.key in MODES:
        raise ValueError(f"modo de mapa repetido: {mode.key}")
    MODES[mode.key] = mode
    return mode


def discover_modes() -> list[MapMode]:
    """Importa ``core/map/mapmodes/*`` (registran con ``register_mode``) y devuelve todos los modos registrados,
    también los de la interfaz, por ``order`` y clave."""
    from . import mapmodes as package

    for info in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{package.__name__}.{info.name}")
    return sorted(MODES.values(), key=lambda mode: (mode.order, mode.key))


def argb(r: int, g: int, b: int, a: int = 255) -> int:
    """``0xAARRGGBB`` de un color (lo que entiende ``QImage.Format_RGB32``/``ARGB32``)."""
    raise NotImplementedError


def hash_color(name: str) -> int:
    """Color opaco estable para un nombre (regiones, continentes, climas, culturas sin color): el mismo en cada
    ejecución y en cada máquina (sin ``hash()`` de Python), ni muy oscuro ni muy claro."""
    raise NotImplementedError


def gradient(values: np.ndarray, low: float, high: float, start: int, end: int) -> np.ndarray:
    """Colores ``uint32`` interpolados entre ``start`` (en ``low``) y ``end`` (en ``high``), recortando fuera
    del intervalo. ``values`` es ``(N+1,)``; con ``low == high`` todo es ``end``."""
    raise NotImplementedError


def coded_lut(facts: ProvinceFacts, field_name: str, colors: Callable[[str], int | None]) -> np.ndarray:
    """LUT de un campo codificado (``owner``, ``trade_goods``…): ``colors(nombre)`` da el color de cada nombre
    de su tabla (None → ``hash_color``), el código 0 da ``EMPTY_COLOR``, el mar ``SEA_COLOR`` y el índice 0,
    ``VOID_COLOR``. Es la base de casi todos los modos."""
    raise NotImplementedError
