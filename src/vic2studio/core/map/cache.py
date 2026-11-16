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

import hashlib
import io
import os
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from .. import appdirs, fileio
from ..cancel import CancelCheck
from .bmp import read_bmp
from .definition import DefinitionTable
from .raster import ProgressFn, ProvinceRaster, UnknownColor

CACHE_FORMAT = 1                     # subirlo invalida todas las entradas
CACHE_FOLDER = "raster"
KEEP_ENTRIES = 4                     # entradas que ``prune`` conserva (las más recientes)


_PARTS = ("ids", "stats", "unknown")


def cache_root() -> Path:
    """``<cache_dir>/raster``. No crea nada."""
    return appdirs.cache_dir() / CACHE_FOLDER


def raster_key(provinces_bmp: bytes, definition_csv: bytes) -> str:
    """Clave de la entrada: ``sha1`` en hexadecimal de ``CACHE_FORMAT``, el ``sha1`` del BMP y el de
    ``definition.csv``. Depende solo del contenido (ni de rutas ni de fechas)."""
    digest = hashlib.sha1(f"raster-v{CACHE_FORMAT}".encode("ascii"))
    digest.update(hashlib.sha1(provinces_bmp).digest())
    digest.update(hashlib.sha1(definition_csv).digest())
    return digest.hexdigest()


def _path(root: Path, key: str, part: str) -> Path:
    return root / f"{key}.v{CACHE_FORMAT}.{part}.npy"


def _is_under(path: Path, folder: Path) -> bool:
    try:
        real = os.path.normcase(os.path.realpath(path))
        base = os.path.normcase(os.path.realpath(folder))
    except OSError:
        return False
    return real == base or real.startswith(base.rstrip(os.sep) + os.sep)


def _allowed(root: Path, forbidden: Iterable[Path]) -> bool:
    return not any(_is_under(root, Path(folder)) for folder in forbidden)


def _load_array(path: Path) -> np.ndarray:
    return np.load(io.BytesIO(path.read_bytes()), allow_pickle=False)


def load(key: str, *, root: Path | None = None) -> ProvinceRaster | None:
    """El ráster guardado con ``key`` o None si no está entero y coherente. No escribe."""
    root = cache_root() if root is None else Path(root)
    try:
        ids = _load_array(_path(root, key, "ids"))
        stats = _load_array(_path(root, key, "stats"))
        unknown = _load_array(_path(root, key, "unknown"))
    except (OSError, ValueError, EOFError):
        return None
    if ids.ndim != 2 or ids.dtype != np.uint16 or stats.ndim != 2 or stats.shape[1] != 7 \
            or unknown.ndim != 2 or unknown.shape[1] != 6 or stats.dtype != np.float64:
        return None
    if ids.size and int(ids.max()) >= stats.shape[0]:
        return None
    pixel_count = stats[:, 0].astype(np.int64)
    bbox = stats[:, 1:5].astype(np.int32)
    centroid = np.ascontiguousarray(stats[:, 5:7])
    colors = tuple(UnknownColor((int(r), int(g), int(b)), int(n), (int(x), int(y)))
                   for r, g, b, n, x, y in unknown.tolist())
    return ProvinceRaster(ids, pixel_count, bbox, centroid, colors)


def _array_bytes(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return buffer.getvalue()


def store(key: str, raster: ProvinceRaster, *, root: Path | None = None,
          forbidden: Iterable[Path] = ()) -> bool:
    """Guarda ``raster`` con ``key``. False (sin escribir nada) si la carpeta cae dentro de ``forbidden`` o si
    el disco falla: la caché es opcional y nunca rompe una carga."""
    root = cache_root() if root is None else Path(root)
    if not _allowed(root, forbidden):
        return False
    stats = np.empty((raster.pixel_count.shape[0], 7), dtype=np.float64)
    stats[:, 0] = raster.pixel_count
    stats[:, 1:5] = raster.bbox
    stats[:, 5:7] = raster.centroid
    unknown = np.array([[*u.rgb, u.pixels, *u.sample] for u in raster.unknown], dtype=np.int64).reshape(-1, 6)
    try:
        fileio.make_dirs(root)
        # El de ids va el último: sin él la entrada no existe para ``load``, así que nunca queda a medias.
        fileio.atomic_write_bytes(_path(root, key, "stats"), _array_bytes(stats))
        fileio.atomic_write_bytes(_path(root, key, "unknown"), _array_bytes(unknown))
        fileio.atomic_write_bytes(_path(root, key, "ids"), _array_bytes(np.ascontiguousarray(raster.ids)))
    except OSError:
        return False
    return True


def prune(*, root: Path | None = None, keep: int = KEEP_ENTRIES, forbidden: Iterable[Path] = ()) -> int:
    """Borra las entradas más viejas hasta dejar ``keep`` (y las de otro ``CACHE_FORMAT``); devuelve cuántas
    borró. Un mapa de vanilla ocupa unos 24 MB."""
    root = cache_root() if root is None else Path(root)
    if not _allowed(root, forbidden):
        return 0
    try:
        files = [path for path in root.iterdir() if path.is_file() and path.name.endswith(".npy")]
    except OSError:
        return 0
    entries: dict[str, list[Path]] = {}
    stale: dict[str, list[Path]] = {}
    suffix = f".v{CACHE_FORMAT}."
    for path in files:
        name = path.name
        key = name.split(".", 1)[0]
        (entries if suffix in name else stale).setdefault(key + name.split(".")[1], []).append(path)

    def age(paths: list[Path]) -> float:
        try:
            return max(path.stat().st_mtime for path in paths)
        except OSError:
            return 0.0

    ordered = sorted(entries.items(), key=lambda item: age(item[1]), reverse=True)
    doomed = [paths for _, paths in ordered[max(0, keep):]] + list(stale.values())
    removed = 0
    for paths in doomed:
        try:
            for path in paths:
                fileio.remove_file(path)
        except OSError:
            continue
        removed += 1
    return removed


def load_or_build(provinces_bmp: bytes, definition_csv: bytes, *, root: Path | None = None,
                  forbidden: Iterable[Path] = (), use_cache: bool = True, progress: ProgressFn | None = None,
                  cancelled: CancelCheck = None) -> tuple[ProvinceRaster, bool]:
    """``(ráster, vino_de_la_caché)``: lo carga con su clave o lo construye (``read_bmp`` +
    ``DefinitionTable.parse`` + ``ProvinceRaster.build``) y lo guarda. Es lo que ejecuta la tarea de fondo de
    ``ui/session_map``: recibe bytes y devuelve un valor inmutable (I12). ``BmpError`` si el BMP no es de 24
    bits sin comprimir; ``Cancelled`` si se cancela (entonces no guarda nada)."""
    key = raster_key(provinces_bmp, definition_csv) if use_cache else ""
    if use_cache:
        cached = load(key, root=root)
        if cached is not None:
            return cached, True
    image = read_bmp(provinces_bmp)
    if image.pixels.ndim != 3:
        from .bmp import BMP_UNSUPPORTED, BmpError
        raise BmpError(BMP_UNSUPPORTED, "24")
    table, _ = DefinitionTable.parse(definition_csv)
    raster = ProvinceRaster.build(image.pixels, table, progress=progress, cancelled=cancelled)
    if use_cache:
        if store(key, raster, root=root, forbidden=forbidden):
            prune(root=root, forbidden=forbidden)
    return raster, False
