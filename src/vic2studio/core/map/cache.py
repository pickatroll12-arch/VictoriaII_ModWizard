"""Caché del ráster de provincias en la carpeta de caché de la aplicación (wizard §16.1, §16.5). Contrato.

La clave es un ``sha1`` del contenido del BMP de provincias y de ``definition.csv`` (los bytes efectivos, con lo
sin guardar): cambia cualquiera de los dos y la entrada vieja deja de servir sola. Cada entrada son archivos
``.npy`` con el prefijo ``<clave>.v<CACHE_FORMAT>.`` (``ids``, ``stats`` con píxeles, cajas y centroides, y
``unknown``) dentro de ``appdirs.cache_dir() / "raster"``: **nunca** en el mod ni en el juego (I1, I4). Criterio:
cargar el ráster de vanilla desde la caché tarda ≤ 0,5 s.

Se escribe solo con ``core.fileio.atomic_write_bytes`` (el array se serializa en memoria; ``numpy.save`` sobre una
ruta está vetado por ``test_arch_writes``) y nunca si la carpeta de caché cae dentro de una de las raíces
``forbidden`` (el juego, el mod y las dependencias), como hacen ``index.cache`` y ``validate.baseline``. Una
entrada rota, truncada o de otro formato se ignora (``load`` da None) y se vuelve a construir. Todo se puede
llamar desde un hilo de tarea.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .. import appdirs
from ..cancel import CancelCheck
from .raster import ProgressFn, ProvinceRaster

CACHE_FORMAT = 1                     # subirlo invalida todas las entradas
CACHE_FOLDER = "raster"
KEEP_ENTRIES = 4                     # entradas que ``prune`` conserva (las más recientes)


def cache_root() -> Path:
    """``<cache_dir>/raster``. No crea nada."""
    return appdirs.cache_dir() / CACHE_FOLDER


def raster_key(provinces_bmp: bytes, definition_csv: bytes) -> str:
    """Clave de la entrada: ``sha1`` en hexadecimal de ``CACHE_FORMAT``, el ``sha1`` del BMP y el de
    ``definition.csv``. Depende solo del contenido (ni de rutas ni de fechas)."""
    raise NotImplementedError


def load(key: str, *, root: Path | None = None) -> ProvinceRaster | None:
    """El ráster guardado con ``key`` o None si no está entero y coherente. No escribe."""
    raise NotImplementedError


def store(key: str, raster: ProvinceRaster, *, root: Path | None = None,
          forbidden: Iterable[Path] = ()) -> bool:
    """Guarda ``raster`` con ``key``. False (sin escribir nada) si la carpeta cae dentro de ``forbidden`` o si
    el disco falla: la caché es opcional y nunca rompe una carga."""
    raise NotImplementedError


def prune(*, root: Path | None = None, keep: int = KEEP_ENTRIES, forbidden: Iterable[Path] = ()) -> int:
    """Borra las entradas más viejas hasta dejar ``keep`` (y las de otro ``CACHE_FORMAT``); devuelve cuántas
    borró. Un mapa de vanilla ocupa unos 24 MB."""
    raise NotImplementedError


def load_or_build(provinces_bmp: bytes, definition_csv: bytes, *, root: Path | None = None,
                  forbidden: Iterable[Path] = (), use_cache: bool = True, progress: ProgressFn | None = None,
                  cancelled: CancelCheck = None) -> tuple[ProvinceRaster, bool]:
    """``(ráster, vino_de_la_caché)``: lo carga con su clave o lo construye (``read_bmp`` +
    ``DefinitionTable.parse`` + ``ProvinceRaster.build``) y lo guarda. Es lo que ejecuta la tarea de fondo de
    ``ui/session_map``: recibe bytes y devuelve un valor inmutable (I12). ``BmpError`` si el BMP no es de 24
    bits sin comprimir; ``Cancelled`` si se cancela (entonces no guarda nada)."""
    raise NotImplementedError
